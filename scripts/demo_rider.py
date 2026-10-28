"""
Play one rider's day through the real public APIs (demo + smoke test).

1. Finds a `planned` route (a DB read — stand-in until Core API exposes
   "my assigned route" to drivers).
2. Logs in as that rider through Core API (POST /auth/login) to get a JWT.
3. Posts events to the Driver Gateway (POST /driver/events), exactly as the
   rider app would: route.started, N deliveries, one failed attempt, and the
   first delivery AGAIN with the same event_id (a phone retrying offline).

Then run the consumer to persist them:
    python -m services.routing_worker.app.terminal_events --once

    python scripts/demo_rider.py --deliver 5
    python scripts/demo_rider.py --tracking WZDESTWJAV   # the rider carrying this parcel,
                                                         # delivering up to and including it
"""

import argparse
import asyncio
import os
import re
import uuid
from datetime import datetime, timezone

import asyncpg
import httpx
from dotenv import load_dotenv

CORE_API = "http://localhost:8000"
GATEWAY = "http://localhost:8002"
DEV_PASSWORD = "LastMile#2026"   # data/README.md (dev-only test accounts)


async def find_route(tracking=None):
    load_dotenv()
    url = re.sub(r"\?.*$", "?sslmode=require", os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    conn = await asyncpg.connect(url, statement_cache_size=0)
    try:
        # Several routes can be created in the same instant, so "latest" is
        # ambiguous; --tracking picks the route that carries a given parcel.
        route = await conn.fetchrow("""
            SELECT r.id, u.email, w.code hub, v.type::text vtype FROM routes r
            JOIN users u ON u.id = r.driver_id JOIN warehouses w ON w.id = r.warehouse_id
            JOIN vehicles v ON v.id = r.vehicle_id
            WHERE r.status = 'planned'
              AND ($1::text IS NULL OR EXISTS (SELECT 1 FROM route_stops s JOIN orders o ON o.id = s.order_id
                                               WHERE s.route_id = r.id AND o.tracking_token = $1))
            ORDER BY r.created_at DESC, r.id LIMIT 1""", tracking)
        if route is None and tracking:
            raise SystemExit(f"No planned route carries {tracking}. Is it assigned, and has the route not started yet?")
        if route is None:
            raise SystemExit("No planned route. Run: python -m services.routing_worker.app.plan_pending --at 2026-10-28T13:30+05:30")
        stops = await conn.fetch("""
            SELECT s.order_id, o.merchant_order_ref, o.tracking_token,
                   ST_Y(s.planned_location::geometry) lat, ST_X(s.planned_location::geometry) lon
            FROM route_stops s JOIN orders o ON o.id = s.order_id
            WHERE s.route_id = $1 ORDER BY s.sequence""", route["id"])
        return route, stops
    finally:
        await conn.close()


def event(kind, driver_id, **fields):
    return {"event_id": str(uuid.uuid4()), "event_type": kind, "driver_id": driver_id,
            "timestamp": datetime.now(timezone.utc).isoformat(), **fields}


async def main(deliver, tracking):
    route, stops = await find_route(tracking)
    if tracking:
        # Deliver every stop up to and including the chosen parcel.
        deliver = next(i for i, s in enumerate(stops, start=1) if s["tracking_token"] == tracking)
    print(f"Rider {route['email']} ({route['vtype']}, hub {route['hub']}) — route with {len(stops)} stops")
    async with httpx.AsyncClient(timeout=20) as http:
        login = await http.post(f"{CORE_API}/auth/login", json={"email": route["email"], "password": DEV_PASSWORD})
        login.raise_for_status()
        token = login.cookies.get("access_token")
        driver_id = login.json()["user_id"]
        headers = {"Authorization": f"Bearer {token}"}

        async def send(ev, label):
            r = await http.post(f"{GATEWAY}/driver/events", json=ev, headers=headers)
            print(f"  {r.status_code}  {label}")
            r.raise_for_status()

        await send(event("route.started", driver_id, route_id=str(route["id"])), "route.started")
        first = None
        for s in stops[:deliver]:
            ev = event("delivery.completed", driver_id, order_id=str(s["order_id"]), current_route_id=str(route["id"]),
                       latitude=s["lat"], longitude=s["lon"])
            first = first or ev
            await send(ev, f"delivered {s['merchant_order_ref']}  (track: {CORE_API}/track?code={s['tracking_token']})")
        if len(stops) > deliver:
            s = stops[deliver]
            await send(event("delivery.failed", driver_id, order_id=str(s["order_id"]), current_route_id=str(route["id"]),
                             latitude=s["lat"], longitude=s["lon"], failure_reason="recipient_unavailable"),
                       f"FAILED {s['merchant_order_ref']} (recipient unavailable)")
        if first:
            await send(first, "same delivery event re-sent (offline retry) — must be ignored")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--deliver", type=int, default=5)
    ap.add_argument("--tracking", help="play the rider whose planned route carries this tracking code")
    a = ap.parse_args()
    asyncio.run(main(a.deliver, a.tracking))
