"""
Routing Worker — terminal driver-event consumer (docs/architecture.md §3.6).

Reads driver_events_stream with its own consumer group and persists the
events that change Postgres state:

    route.started       route planned -> in_progress, its orders
                        assigned -> out_for_delivery, driver -> on_route
    delivery.completed  stop delivered, order delivered, delivery_attempts row
    delivery.failed     stop failed, order attempt_failed, delivery_attempts row

Idempotent: the event_id is inserted into processed_events in the same
transaction; a replayed event finds it and changes nothing. The stream
entry is XACKed only after that transaction commits (AGENTS.md §4).
Location pings are ignored here (Control Tower owns them).

    python -m services.routing_worker.app.terminal_events --once   # drain and exit
    python -m services.routing_worker.app.terminal_events          # keep consuming
"""

import argparse
import asyncio
import logging
import os
import re
import uuid
from datetime import datetime

import asyncpg
from dotenv import load_dotenv

from streaming.client import get_redis_client

STREAM, GROUP = "driver_events_stream", "routing-workers-terminal"
HANDLED = {"route.started", "delivery.completed", "delivery.failed"}
FAILURE_REASONS = {"recipient_unavailable", "wrong_address", "refused", "other"}

log = logging.getLogger("routing-worker.terminal")


async def apply(conn, ev):
    """Apply one event inside the caller's transaction. Returns a short outcome string."""
    event_id = uuid.UUID(ev["event_id"])
    fresh = await conn.fetchval(
        "INSERT INTO processed_events (event_id, event_type) VALUES ($1, $2) ON CONFLICT DO NOTHING RETURNING event_id",
        event_id, ev["event_type"])
    if fresh is None:
        return "duplicate, ignored"
    at = datetime.fromisoformat(ev["timestamp"])
    driver_id = uuid.UUID(ev["driver_id"])

    if ev["event_type"] == "route.started":
        route_id = uuid.UUID(ev["route_id"])
        updated = await conn.execute("""
            UPDATE routes SET status = 'in_progress', started_at = $3, updated_at = now()
            WHERE id = $1 AND driver_id = $2 AND status = 'planned'""", route_id, driver_id, at)
        if updated.endswith(" 0"):
            return "route not planned for this driver, ignored"
        orders = await conn.fetch("""
            UPDATE orders o SET status = 'out_for_delivery', updated_at = now()
            FROM route_stops s WHERE s.route_id = $1 AND s.order_id = o.id AND o.status = 'assigned'
            RETURNING o.id, s.id stop_id""", route_id)
        await conn.executemany("""
            INSERT INTO order_events (order_id, from_status, to_status, route_stop_id, actor_user_id, occurred_at)
            VALUES ($1, 'assigned', 'out_for_delivery', $2, $3, $4)""",
            [(o["id"], o["stop_id"], driver_id, at) for o in orders])
        await conn.execute("UPDATE drivers SET status = 'on_route', updated_at = now() WHERE user_id = $1", driver_id)
        return f"route started, {len(orders)} parcels out for delivery"

    delivered = ev["event_type"] == "delivery.completed"
    stop = await conn.fetchrow("""
        SELECT s.id, s.order_id FROM route_stops s JOIN routes r ON r.id = s.route_id
        WHERE s.order_id = $1 AND r.driver_id = $2 AND r.status = 'in_progress' AND s.status = 'pending'
        FOR UPDATE OF s""", uuid.UUID(ev["order_id"]), driver_id)
    if stop is None:
        return "no pending stop for this driver and order, ignored"
    reason = None if delivered else (ev.get("failure_reason") if ev.get("failure_reason") in FAILURE_REASONS else "other")
    await conn.execute("""
        UPDATE route_stops SET status = $2, failure_reason = $3::failure_reason, arrived_at = $4, completed_at = $4, updated_at = now()
        WHERE id = $1""", stop["id"], "delivered" if delivered else "failed", reason, at)
    new_status = "delivered" if delivered else "attempt_failed"
    await conn.execute("UPDATE orders SET status = $2::order_status, updated_at = now() WHERE id = $1", stop["order_id"], new_status)
    await conn.execute("""
        INSERT INTO order_events (order_id, from_status, to_status, route_stop_id, actor_user_id, occurred_at)
        VALUES ($1, 'out_for_delivery', $2::order_status, $3, $4, $5)""", stop["order_id"], new_status, stop["id"], driver_id, at)
    await conn.execute("""
        INSERT INTO delivery_attempts (order_id, route_stop_id, driver_id, outcome, failure_reason, pod_photo_url, client_event_id, occurred_at)
        VALUES ($1, $2, $3, $4::attempt_outcome, $5::failure_reason, $6, $7, $8)""",
        stop["order_id"], stop["id"], driver_id, "delivered" if delivered else "failed", reason,
        ev.get("pod_photo_url"), event_id, at)
    # The route is finished once no stop is left pending.
    await conn.execute("""
        UPDATE routes r SET status = 'completed', completed_at = $2, updated_at = now()
        WHERE r.id = (SELECT route_id FROM route_stops WHERE id = $1)
          AND NOT EXISTS (SELECT 1 FROM route_stops s WHERE s.route_id = r.id AND s.status = 'pending')""", stop["id"], at)
    return new_status


async def run(once):
    load_dotenv()
    url = re.sub(r"\?.*$", "?sslmode=require", os.environ["DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://"))
    conn = await asyncpg.connect(url, statement_cache_size=0)
    redis = await get_redis_client()
    try:
        await redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    except Exception as exc:  # BUSYGROUP: the group already exists
        if "BUSYGROUP" not in str(exc):
            raise
    consumer = f"worker-{os.getpid()}"
    counts = {}
    try:
        while True:
            batch = await redis.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=100, block=None if once else 5000)
            entries = batch[0][1] if batch else []
            if not entries and once:
                break
            for entry_id, ev in entries:
                outcome = "location ping, not for this worker"
                if ev.get("event_type") in HANDLED:
                    async with conn.transaction():
                        outcome = await apply(conn, ev)
                await redis.xack(STREAM, GROUP, entry_id)
                counts[outcome] = counts.get(outcome, 0) + 1
                log.info("%s %s -> %s", ev.get("event_type"), ev.get("order_id") or ev.get("route_id"), outcome)
    finally:
        await conn.close()
    for outcome, n in sorted(counts.items()):
        print(f"{n:4}  {outcome}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="process what is in the stream, then exit")
    asyncio.run(run(ap.parse_args().once))
