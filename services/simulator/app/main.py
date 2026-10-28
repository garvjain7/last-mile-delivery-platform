# World Simulator — external client that plays every actor through the public APIs.
#
# Version 1: one order's full life, end to end, narrated step by step:
#   customer orders -> merchant sends (nearest hub chosen) -> hub receives ->
#   Routing Worker plans -> the assigned rider's app finds it -> route started ->
#   delivered -> Routing Worker records it -> customer tracking shows Delivered.
#
# The simulator never touches Postgres (AGENTS.md). Until the Routing Worker
# runs as a continuous stream consumer, the simulator triggers one worker run
# ("tick") as a separate process at the two points the worker would react.
#
#   python -m services.simulator.app.main
#   python -m services.simulator.app.main --address "Telibandha, Raipur, Chhattisgarh"

import argparse
import asyncio
import logging
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

import httpx

from services.simulator.app.config import config

logger = logging.getLogger("simulator")

DEV_PASSWORD = "LastMile#2026"   # dev-only accounts from data/README.md
DOMAIN = "lastmile.example.com"
FLEET_PER_HUB = {"two_wheeler": 7, "three_wheeler": 2, "van": 1}


class Actor:
    """One signed-in person (customer, merchant, hub staff or rider)."""

    def __init__(self, email, password=DEV_PASSWORD):
        self.email, self.password = email, password
        # Origin must match Core API's PUBLIC_BASE_URL for its CSRF check.
        self.http = httpx.AsyncClient(base_url=config.core_api_url, timeout=30,
                                      headers={"Origin": config.core_api_url})
        self.user_id = self.token = None

    async def login(self):
        r = await self.http.post("/auth/login", json={"email": self.email, "password": self.password})
        r.raise_for_status()
        self.user_id, self.token = r.json()["user_id"], r.cookies.get("access_token")
        return self

    async def close(self):
        await self.http.aclose()


def step(n, who, text):
    print(f"\n[{n}] {who}: {text}")


def worker_tick(module, *args):
    """Run one Routing Worker pass (stand-in for its stream consumer)."""
    p = subprocess.run([sys.executable, "-m", module, *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-800:])
    return p.stdout.strip()


async def rider_event(rider, payload):
    async with httpx.AsyncClient(base_url=config.driver_gateway_url, timeout=30) as gw:
        r = await gw.post("/driver/events", headers={"Authorization": f"Bearer {rider.token}"},
                          json={"event_id": str(uuid.uuid4()), "driver_id": rider.user_id,
                                "timestamp": datetime.now(timezone.utc).isoformat(), **payload})
        r.raise_for_status()


async def run_one_order(address, seller_name, customer_email, merchant_email):
    started = time.time()
    customer = await Actor(customer_email).login()
    step(1, "Customer", f"signs in as {customer_email} and requests a delivery to '{address}'")
    sellers = (await customer.http.get(f"/api/users/{customer.user_id}/request/sellers")).json()
    sellers = sellers.get("sellers", sellers) if isinstance(sellers, dict) else sellers
    seller = next(s for s in sellers if s["name"] == seller_name)
    r = await customer.http.post(f"/api/users/{customer.user_id}/request",
                                 headers={"Idempotency-Key": str(uuid.uuid4())},
                                 json={"seller_id": seller["id"], "recipient_name": "Simulated Recipient",
                                       "recipient_phone": "+919000088888", "delivery_address": address,
                                       "weight_kg": 1.2, "volume_m3": 0.006})
    r.raise_for_status()
    order = r.json()
    code = order["tracking_token"]
    print(f"    order {order['order_id']} placed with {seller_name}; tracking code {code}")

    merchant = await Actor(merchant_email).login()
    step(2, "Merchant", f"{merchant_email} presses Send")
    r = await merchant.http.post(f"/api/merchant/orders/{order['order_id']}/send", json={})
    r.raise_for_status()
    hub = r.json()["warehouse"]
    print(f"    nearest active hub chosen: {hub['code']} ({hub['name']}), {hub['distance_m'] / 1000:.1f} km away")

    staff = await Actor(f"dispatch.{hub['code'].lower()}@{DOMAIN}").login()
    step(3, "Hub staff", f"{staff.email} scans the parcel in at {hub['code']}")
    (await staff.http.post(f"/api/hub/orders/{order['order_id']}/receive", json={})).raise_for_status()
    print("    status: pending (waiting at the hub)")

    step(4, "Routing Worker", f"plans {hub['code']}'s waiting parcels onto free riders with VROOM")
    out = worker_tick("services.routing_worker.app.plan_pending", "--hub", hub["code"], "--ignore-shifts")
    print("    " + "\n    ".join(out.splitlines()))

    step(5, "Rider apps", f"each {hub['code']} rider checks their route for the parcel")
    rider, route = None, None
    for vtype, n in FLEET_PER_HUB.items():
        for i in range(1, n + 1):
            candidate = await Actor(f"rider.{hub['code'].lower()}.{vtype}.{i}@{DOMAIN}").login()
            got = (await candidate.http.get("/api/driver/route")).json()["route"]
            if got and any(s["order_id"] == order["order_id"] for s in got["stops"]):
                rider, route = candidate, got
                break
            await candidate.close()
        if rider:
            break
    if rider is None:
        print("    no rider got the parcel (no free rider or no capacity) — it stays pending. Stopping here.")
        return False
    ours = next(s for s in route["stops"] if s["order_id"] == order["order_id"])
    print(f"    {rider.email}: route with {len(route['stops'])} stops; our parcel is stop {ours['sequence']}")

    step(6, "Rider app", "starts the route, then delivers each stop in order up to ours")
    await rider_event(rider, {"event_type": "route.started", "route_id": route["id"]})
    for s in route["stops"][: ours["sequence"]]:
        await rider_event(rider, {"event_type": "delivery.completed", "order_id": s["order_id"],
                                  "current_route_id": route["id"], "latitude": s["lat"], "longitude": s["lon"]})
    print(f"    sent route.started + {ours['sequence']} delivery.completed events to the Driver Gateway")

    step(7, "Routing Worker", "reads the rider's events and records them in the database")
    out = worker_tick("services.routing_worker.app.terminal_events", "--once")
    print("    " + "\n    ".join(out.splitlines()))

    step(8, "Customer", f"opens the public tracking page for {code}")
    async with httpx.AsyncClient(base_url=config.core_api_url, timeout=30) as public:
        track = (await public.get(f"/api/track/{code}")).json()
    print(f"    status shown: {track['status']}")
    for s in track.get("steps", []):
        print(f"      {s['label']:10} {s['state']:7} {s.get('time') or ''}")
    print(f"\nDone in {time.time() - started:.0f}s. Open {config.core_api_url}/track?code={code}")
    for actor in (customer, merchant, staff, rider):
        await actor.close()
    return track["status"].lower().startswith("delivered")


def main():
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser(description="Simulate one order end to end through the public APIs.")
    # Telibandha is served by the Mana Camp hub, which has free riders in the demo data.
    ap.add_argument("--address", default="Telibandha, Raipur, Chhattisgarh")
    ap.add_argument("--seller", default="Mahanadi Electronics")
    ap.add_argument("--customer", default=f"customer003@{DOMAIN}")
    ap.add_argument("--merchant", default=f"merchant2@{DOMAIN}", help="a member of --seller")
    a = ap.parse_args()
    ok = asyncio.run(run_one_order(a.address, a.seller, a.customer, a.merchant))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
