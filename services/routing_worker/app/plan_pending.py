"""
One routing run: plan every hub's `pending` parcels onto available riders.

MVP stand-in for the Routing Worker's orders_stream consumer: same job
(pending orders -> VROOM -> routes + stops + `assigned` events, one
transaction), triggered by hand instead of by Redis Streams.

    python -m services.routing_worker.app.plan_pending            # plan and write
    python -m services.routing_worker.app.plan_pending --dry-run  # plan, print, write nothing
    python -m services.routing_worker.app.plan_pending --at 2026-10-28T13:30+05:30  # plan as of a time

Travel times are straight-line distance x detour / speed until OSRM is
running (docs/architecture.md); VROOM runs in-process via pyvroom.
"""

import argparse
import asyncio
import math
import os
import re
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import asyncpg
import vroom
from dotenv import load_dotenv

DETOUR_FACTOR = 1.35
BASE_SPEED_KMH = 18.0
SPEED_KMH = {"two_wheeler": 20.0, "three_wheeler": 16.0, "van": 15.0, "light_truck": 15.0}
MAX_STOPS = {"two_wheeler": 35, "three_wheeler": 55, "van": 70, "light_truck": 80}
# A parcel this heavy or large cannot ride on a two-wheeler (vehicle skill 1).
BULKY_WEIGHT_KG, BULKY_VOLUME_M3 = 10.0, 0.06
DEFAULT_SERVICE_S = 90


def haversine_m(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def travel_s(a, b):
    m = haversine_m(a, b) * DETOUR_FACTOR
    return int(m / (BASE_SPEED_KMH * 1000 / 3600)) + (30 if m > 30 else 0)


async def load_hub(conn, hub_id):
    orders = await conn.fetch("""
        SELECT o.id, ST_Y(o.delivery_location::geometry) lat, ST_X(o.delivery_location::geometry) lon,
               o.weight_kg, o.volume_m3, coalesce(o.service_time_s, $2) service_s,
               o.window_earliest, o.window_latest, o.merchant_order_ref,
               ST_Distance(o.delivery_location, w.location) dist_m, w.service_radius_m
        FROM orders o JOIN warehouses w ON w.id = o.warehouse_id
        WHERE o.warehouse_id = $1 AND o.status = 'pending'
        ORDER BY o.created_at
        FOR UPDATE OF o SKIP LOCKED""", hub_id, DEFAULT_SERVICE_S)
    riders = await conn.fetch("""
        SELECT d.user_id driver_id, v.id vehicle_id, v.type::text vtype, v.max_weight_kg, v.max_volume_m3,
               d.shift_start, d.shift_end
        FROM drivers d JOIN vehicles v ON v.id = d.vehicle_id
        WHERE d.home_warehouse_id = $1 AND d.status = 'available' AND v.is_active
          AND NOT EXISTS (SELECT 1 FROM routes r WHERE r.driver_id = d.user_id AND r.status IN ('planned','in_progress'))
        ORDER BY v.type, v.registration_number""", hub_id)
    return orders, riders


def solve(hub, orders, riders, start_at, ignore_shifts=False):
    """Return (routes, skipped) where routes = [(rider, [(order, arrival_dt)])]."""
    skipped, jobs_src = [], []
    for o in orders:
        if o["service_radius_m"] and o["dist_m"] > o["service_radius_m"]:
            skipped.append((o, "outside service area"))
        elif o["window_latest"] and o["window_latest"] <= start_at:
            skipped.append((o, "delivery slot already over"))
        else:
            jobs_src.append(o)
    if not jobs_src or not riders:
        return [], skipped + [(o, "no rider available") for o in jobs_src]
    t0 = start_at
    locs = [(hub["lat"], hub["lon"])] + [(o["lat"], o["lon"]) for o in jobs_src]
    matrix = [[travel_s(a, b) for b in locs] for a in locs]
    inp = vroom.Input()
    inp.set_durations_matrix(profile="car", matrix_input=matrix)
    vehicles = []
    for i, r in enumerate(riders):
        day = start_at.astimezone(hub["tz"]).date()
        sh0 = datetime.combine(day, r["shift_start"], hub["tz"]) if r["shift_start"] else start_at
        sh1 = datetime.combine(day, r["shift_end"], hub["tz"]) if r["shift_end"] else start_at + timedelta(hours=10)
        sh0 = max(sh0, start_at)
        if ignore_shifts:
            # Simulation runs at any hour; treat every free rider as on shift.
            sh0, sh1 = start_at, start_at + timedelta(hours=8)
        if sh1 <= sh0:
            continue
        vehicles.append(vroom.Vehicle(
            id=i + 1, start=0, end=0,
            capacity=[int(float(r["max_volume_m3"]) * 1e6), int(float(r["max_weight_kg"]) * 1000)],
            skills=set() if r["vtype"] == "two_wheeler" else {1},
            time_window=vroom.TimeWindow(int((sh0 - t0).total_seconds()), int((sh1 - t0).total_seconds())),
            speed_factor=SPEED_KMH.get(r["vtype"], BASE_SPEED_KMH) / BASE_SPEED_KMH,
            max_tasks=MAX_STOPS.get(r["vtype"], 50)))
    if not vehicles:
        return [], skipped + [(o, "no rider on shift") for o in jobs_src]
    inp.add_vehicle(vehicles)
    jobs = []
    for j, o in enumerate(jobs_src):
        bulky = float(o["weight_kg"]) > BULKY_WEIGHT_KG or float(o["volume_m3"]) > BULKY_VOLUME_M3
        tws = ()
        if o["window_latest"]:
            a = max(o["window_earliest"], start_at)
            tws = [vroom.TimeWindow(int((a - t0).total_seconds()), int((o["window_latest"] - t0).total_seconds()))]
        jobs.append(vroom.Job(id=j + 1, location=j + 1, default_service=int(o["service_s"]),
                              delivery=[max(1, int(float(o["volume_m3"]) * 1e6)), max(1, int(float(o["weight_kg"]) * 1000))],
                              skills={1} if bulky else set(), time_windows=tws))
    inp.add_job(jobs)
    sol = inp.solve(exploration_level=3, nb_threads=4)
    routes, assigned = [], set()
    for vid, grp in sol.routes.groupby("vehicle_id"):
        steps = [s for s in grp.to_dict("records") if s["type"] == "job"]
        if not steps:
            continue
        stops = []
        for s in steps:
            idx = int(s["id"]) - 1
            assigned.add(idx)
            stops.append((jobs_src[idx], t0 + timedelta(seconds=int(s["arrival"]))))
        end = t0 + timedelta(seconds=int(grp.iloc[-1]["arrival"]))
        dist = sum(haversine_m(a, b) for a, b in zip([locs[0]] + [(o["lat"], o["lon"]) for o, _ in stops],
                                                     [(o["lat"], o["lon"]) for o, _ in stops] + [locs[0]]))
        routes.append((riders[int(vid) - 1], stops, end, int(dist * DETOUR_FACTOR)))
    skipped += [(o, "no capacity left") for i, o in enumerate(jobs_src) if i not in assigned]
    return routes, skipped


async def write(conn, hub_id, routes, now):
    for rider, stops, end, dist in routes:
        route_id = uuid.uuid4()
        await conn.execute("""
            INSERT INTO routes (id, warehouse_id, driver_id, vehicle_id, status, total_distance_m, total_duration_s)
            VALUES ($1, $2, $3, $4, 'planned', $5, $6)""",
            route_id, hub_id, rider["driver_id"], rider["vehicle_id"], dist, int((end - stops[0][1]).total_seconds()))
        for seq, (o, arrival) in enumerate(stops, start=1):
            stop_id = uuid.uuid4()
            await conn.execute("""
                INSERT INTO route_stops (id, route_id, order_id, sequence, status, planned_location, planned_arrival_at)
                SELECT $1, $2, o.id, $3, 'pending', o.delivery_location, $4 FROM orders o WHERE o.id = $5""",
                stop_id, route_id, seq, arrival, o["id"])
            await conn.execute("UPDATE orders SET status = 'assigned', updated_at = $2 WHERE id = $1", o["id"], now)
            await conn.execute("""
                INSERT INTO order_events (order_id, from_status, to_status, route_stop_id, occurred_at)
                VALUES ($1, 'pending', 'assigned', $2, $3)""", o["id"], stop_id, now)


async def main(dry_run, at, hub_code=None, ignore_shifts=False):
    load_dotenv()
    url = re.sub(r"\?.*$", "?sslmode=require", os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    conn = await asyncpg.connect(url)
    now = at or datetime.now(timezone.utc)
    from zoneinfo import ZoneInfo
    totals = defaultdict(int)
    try:
        hubs = await conn.fetch("""SELECT id, code, ST_Y(location::geometry) lat, ST_X(location::geometry) lon
                                   FROM warehouses WHERE is_active AND ($1::text IS NULL OR code = $1) ORDER BY code""", hub_code)
        for h in hubs:
            hub = dict(h, tz=ZoneInfo("Asia/Kolkata"))
            async with conn.transaction():
                orders, riders = await load_hub(conn, h["id"])
                routes, skipped = solve(hub, orders, riders, now, ignore_shifts)
                if not dry_run:
                    await write(conn, h["id"], routes, now)
            n = sum(len(s) for _, s, _, _ in routes)
            print(f"{h['code']}: {len(orders)} pending, {len(riders)} riders free -> {len(routes)} routes, {n} parcels assigned")
            for rider, stops, end, dist in routes:
                print(f"    {rider['vtype']:13} {len(stops):3} stops  {dist / 1000:5.1f} km  back {end.astimezone(hub['tz']):%H:%M}")
            reasons = defaultdict(list)
            for o, why in skipped:
                reasons[why].append(o["merchant_order_ref"])
            for why, refs in reasons.items():
                print(f"    not planned ({why}): {len(refs)}  e.g. {', '.join(refs[:3])}")
            totals["routes"] += len(routes); totals["assigned"] += n; totals["skipped"] += len(skipped)
    finally:
        await conn.close()
    print(f"{'DRY RUN - nothing written. ' if dry_run else ''}total: {totals['routes']} routes, "
          f"{totals['assigned']} parcels assigned, {totals['skipped']} left pending")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--at", type=datetime.fromisoformat, help="plan as of this time (ISO, with offset); default now")
    ap.add_argument("--hub", help="plan only this warehouse code, e.g. RPR-URLA")
    ap.add_argument("--ignore-shifts", action="store_true", help="simulation: every free rider counts as on shift")
    a = ap.parse_args()
    asyncio.run(main(a.dry_run, a.at, a.hub, a.ignore_shifts))
