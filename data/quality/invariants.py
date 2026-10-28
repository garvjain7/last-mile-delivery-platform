"""
Data-quality invariants for the Last-Mile database.

Each check is a SQL query returning the offending rows (zero rows = pass).
They encode the rules from docs/end-to-end-system-flow.md, docs/architecture.md
and schema.sql that the database itself does not enforce.

Run from repo root:
    python data/quality/invariants.py            # uses DATABASE_URL from .env
    python data/quality/invariants.py --json out.json
"""

import argparse
import asyncio
import json
import os
import re
import sys

import asyncpg
from dotenv import load_dotenv

# Order lifecycle (docs/end-to-end-system-flow.md, Section "Order statuses").
LEGAL_TRANSITIONS = {
    (None, "placed"),
    ("placed", "sent"),
    ("sent", "pending"),
    ("pending", "assigned"),
    ("assigned", "out_for_delivery"),
    ("assigned", "pending"),            # unassigned by rescue / re-plan
    ("out_for_delivery", "delivered"),
    ("out_for_delivery", "attempt_failed"),
    ("out_for_delivery", "pending"),    # rescue moves remaining stops off a vehicle
    ("attempt_failed", "pending"),      # dispatcher re-queue
    ("attempt_failed", "returned"),
    ("placed", "cancelled"),
    ("sent", "cancelled"),
    ("pending", "cancelled"),
}
_transitions_sql = ",".join(
    f"({'NULL' if a is None else repr(a)}::order_status,{b!r}::order_status)" for a, b in LEGAL_TRANSITIONS
)

# Maximum delivery radius from the serving warehouse used as a sanity bound.
SERVICE_RADIUS_M = 40_000

CHECKS = [
    # --- Order lifecycle / history -------------------------------------------
    ("order_without_history", "critical",
     "select o.id, o.status from orders o where not exists (select 1 from order_events e where e.order_id = o.id)"),
    ("history_first_event_not_placed", "high",
     """select distinct on (order_id) order_id, from_status, to_status from order_events
        order by order_id, occurred_at, id"""
     " ", ),  # filtered below
    ("history_last_event_mismatch", "critical",
     """select o.id, o.status, last.to_status from orders o
        join lateral (select to_status from order_events e where e.order_id = o.id
                      order by occurred_at desc, id desc limit 1) last on true
        where last.to_status <> o.status"""),
    ("history_illegal_transition", "high",
     f"""select e.order_id, e.from_status, e.to_status from order_events e
         where (e.from_status, e.to_status) not in (select * from (values {_transitions_sql}) t(a,b))
           and not (e.from_status is null and e.to_status = 'placed')"""),
    ("history_broken_chain", "high",
     """select order_id, from_status, prev_to from (
          select order_id, from_status, lag(to_status) over (partition by order_id order by occurred_at, id) prev_to,
                 row_number() over (partition by order_id order by occurred_at, id) rn
          from order_events) x
        where rn > 1 and from_status is distinct from prev_to"""),
    ("history_event_before_order_created", "medium",
     "select e.order_id from order_events e join orders o on o.id = e.order_id where e.occurred_at < o.created_at - interval '1 second'"),

    # --- Orders vs warehouse / routing ---------------------------------------
    ("post_handoff_order_without_warehouse", "critical",
     "select id, status from orders where warehouse_id is null and status not in ('placed','cancelled')"),
    ("pre_handoff_order_with_warehouse", "medium",
     "select id from orders where warehouse_id is not null and status = 'placed'"),
    ("assigned_or_ofd_without_active_stop", "critical",
     """select o.id, o.status from orders o where o.status in ('assigned','out_for_delivery')
        and not exists (select 1 from route_stops s join routes r on r.id = s.route_id
                        where s.order_id = o.id and s.status = 'pending' and r.status in ('planned','in_progress'))"""),
    ("delivered_without_delivered_stop", "critical",
     "select o.id from orders o where o.status = 'delivered' and not exists (select 1 from route_stops s where s.order_id = o.id and s.status = 'delivered')"),
    ("failed_without_failed_stop", "high",
     "select o.id from orders o where o.status in ('attempt_failed','returned') and not exists (select 1 from route_stops s where s.order_id = o.id and s.status = 'failed')"),
    ("stop_status_vs_order_status", "high",
     """select s.id, s.status, o.status from route_stops s join orders o on o.id = s.order_id
        where (s.status = 'delivered' and o.status <> 'delivered')"""),
    ("order_on_multiple_active_routes", "critical",
     """select s.order_id, count(*) from route_stops s join routes r on r.id = s.route_id
        where r.status in ('planned','in_progress') and s.status = 'pending' group by 1 having count(*) > 1"""),
    ("route_warehouse_differs_from_order", "high",
     "select s.id from route_stops s join routes r on r.id = s.route_id join orders o on o.id = s.order_id where o.warehouse_id is distinct from r.warehouse_id"),
    ("order_outside_service_radius", "medium",
     f"select o.id, round(st_distance(o.delivery_location, w.location)) m from orders o join warehouses w on w.id = o.warehouse_id where st_distance(o.delivery_location, w.location) > {SERVICE_RADIUS_M}"),
    ("order_not_served_by_nearest_warehouse", "low",
     """select o.id from orders o where o.warehouse_id is not null and o.warehouse_id <> (
          select w.id from warehouses w where w.is_active order by w.location <-> o.delivery_location limit 1)"""),
    ("window_ends_before_order_created", "medium",
     "select id from orders where window_latest is not null and window_latest < created_at"),
    ("duplicate_delivery_location_cluster", "low",
     "select st_astext(delivery_location::geometry), count(*) from orders group by 1 having count(*) > 25"),
    ("placeholder_address_text", "medium",
     "select id, delivery_address from orders where delivery_address ilike '%synthetic%' or delivery_address ilike '%test%'"),

    # --- Routes / stops --------------------------------------------------------
    ("stop_sequence_gap", "high",
     "select route_id, count(*), max(sequence) from route_stops group by 1 having max(sequence) <> count(*)"),
    ("stop_eta_not_monotonic", "medium",
     """select route_id, sequence from (select route_id, sequence, planned_arrival_at,
           lag(planned_arrival_at) over (partition by route_id order by sequence) prev from route_stops) x
        where planned_arrival_at < prev"""),
    ("route_without_stops", "medium",
     "select r.id, r.status from routes r where not exists (select 1 from route_stops s where s.route_id = r.id) and r.status <> 'cancelled'"),
    ("route_over_weight_capacity", "critical",
     """select r.id, sum(o.weight_kg) kg, v.max_weight_kg from routes r join vehicles v on v.id = r.vehicle_id
        join route_stops s on s.route_id = r.id join orders o on o.id = s.order_id
        group by r.id, v.max_weight_kg having sum(o.weight_kg) > v.max_weight_kg"""),
    ("route_over_volume_capacity", "critical",
     """select r.id, sum(o.volume_m3) m3, v.max_volume_m3 from routes r join vehicles v on v.id = r.vehicle_id
        join route_stops s on s.route_id = r.id join orders o on o.id = s.order_id
        group by r.id, v.max_volume_m3 having sum(o.volume_m3) > v.max_volume_m3"""),
    ("route_vehicle_not_drivers_vehicle", "high",
     "select r.id from routes r join drivers d on d.user_id = r.driver_id where d.vehicle_id is distinct from r.vehicle_id and r.status in ('planned','in_progress')"),
    ("driver_with_multiple_active_routes", "high",
     "select driver_id, count(*) from routes where status = 'in_progress' group by 1 having count(*) > 1"),
    ("in_progress_route_driver_not_on_route", "medium",
     "select r.id, d.status from routes r join drivers d on d.user_id = r.driver_id where r.status = 'in_progress' and d.status <> 'on_route'"),
    ("route_timestamps_inconsistent", "medium",
     """select id, status from routes where (status = 'in_progress' and started_at is null)
        or (status = 'completed' and (started_at is null or completed_at is null)) or (completed_at < started_at)"""),
    ("stop_far_from_order_location", "medium",
     "select s.id from route_stops s join orders o on o.id = s.order_id where st_distance(s.planned_location, o.delivery_location) > 50"),

    # --- People / fleet --------------------------------------------------------
    ("driver_role_without_driver_row", "high",
     "select ur.user_id from user_roles ur where ur.role = 'driver' and not exists (select 1 from drivers d where d.user_id = ur.user_id)"),
    ("driver_row_without_driver_role", "high",
     "select d.user_id from drivers d where not exists (select 1 from user_roles ur where ur.user_id = d.user_id and ur.role = 'driver')"),
    ("active_driver_without_vehicle", "medium",
     "select user_id, status from drivers where status in ('available','on_route') and vehicle_id is null"),
    ("merchant_without_members", "low",
     "select m.id, m.name from merchants m where not exists (select 1 from merchant_members mm where mm.merchant_id = m.id)"),
    ("warehouse_without_staff", "low",
     "select w.id, w.name from warehouses w where not exists (select 1 from warehouse_staff ws where ws.warehouse_id = w.id)"),
    ("colocated_warehouses", "medium",
     "select a.name, b.name from warehouses a join warehouses b on a.id < b.id where st_dwithin(a.location, b.location, 100)"),
    ("leftover_probe_accounts", "low",
     "select email from users where email ilike '%probe%' or email ilike '%codex%'"),

    # --- Delivery records and idempotency (tables added 2026-10-28) -------------
    ("delivered_without_successful_attempt", "critical",
     "select o.id from orders o where o.status = 'delivered' and not exists (select 1 from delivery_attempts a where a.order_id = o.id and a.outcome = 'delivered')"),
    ("attempt_outcome_vs_stop_status", "high",
     """select a.id from delivery_attempts a join route_stops s on s.id = a.route_stop_id
        where (a.outcome = 'delivered') <> (s.status = 'delivered')"""),
    ("attempt_driver_not_route_driver", "high",
     """select a.id from delivery_attempts a join route_stops s on s.id = a.route_stop_id join routes r on r.id = s.route_id
        where a.driver_id <> r.driver_id"""),
    ("attempt_not_in_idempotency_ledger", "high",
     "select a.id from delivery_attempts a where not exists (select 1 from processed_events p where p.event_id = a.client_event_id)"),
    ("more_than_three_attempts", "medium",
     "select order_id, count(*) from delivery_attempts group by 1 having count(*) > 3"),

    # --- India addressing, COD, rider base/shift (columns added 2026-10-28) ----
    ("cod_order_without_amount", "high",
     "select id from orders where payment_mode = 'cod' and cod_amount_inr is null"),
    ("order_pincode_not_in_hub_region", "medium",
     "select o.id, o.pincode from orders o where o.pincode is not null and left(o.pincode, 2) not in (select distinct left(pincode, 2) from warehouses where pincode is not null)"),
    ("active_route_outside_driver_base", "high",
     """select r.id from routes r join drivers d on d.user_id = r.driver_id
        where r.status in ('planned','in_progress') and d.home_warehouse_id is distinct from r.warehouse_id"""),
    ("routable_driver_without_shift", "medium",
     "select user_id from drivers where status in ('available','on_route') and (shift_start is null or home_warehouse_id is null)"),
]


def _first_event_filter(rows):
    return [r for r in rows if not (r["from_status"] is None and r["to_status"] == "placed")]


async def run(url: str):
    # No statement cache: through Neon's pooler a cached plan goes stale
    # after a schema reset (scripts/reset_demo_db.sh).
    conn = await asyncpg.connect(url, statement_cache_size=0)
    results = []
    try:
        for name, severity, sql in CHECKS:
            try:
                rows = await conn.fetch(sql)
                if name == "history_first_event_not_placed":
                    rows = _first_event_filter(rows)
                results.append({"check": name, "severity": severity, "violations": len(rows),
                                "sample": [dict(r) for r in rows[:3]]})
            except Exception as exc:  # report and continue; a missing table is itself a finding
                results.append({"check": name, "severity": severity, "violations": None, "error": str(exc)})
    finally:
        await conn.close()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json")
    parser.add_argument("--url", help="Override DATABASE_URL")
    args = parser.parse_args()
    load_dotenv()
    url = args.url or os.environ["DATABASE_URL"]
    url = re.sub(r"\?.*$", "?sslmode=require", url.replace("postgresql+asyncpg://", "postgresql://"))
    results = asyncio.run(run(url))
    failed = 0
    for r in results:
        v = r["violations"]
        mark = "ERROR" if v is None else ("PASS " if v == 0 else "FAIL ")
        failed += v != 0
        print(f"{mark} [{r['severity']:8}] {r['check']:42} {r.get('error') or v}")
    print(f"\n{len(results) - failed}/{len(results)} checks pass")
    if args.json:
        with open(args.json, "w") as fh:
            json.dump(results, fh, indent=2, default=str)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
