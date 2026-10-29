"""Read-only audit of the order -> route -> delivery demo data."""

from __future__ import annotations

import asyncio
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import asyncpg
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

# All audit thresholds and sampling limits are kept here.
CONFIG = {
    "sample_limit": 10,
    "speed_limit_kmh": 90.0,
    "future_clock_skew_seconds": 60,
    "same_created_at_min_rows": 5,
    "synthetic_interarrival_cv_max": 0.05,
    "min_interarrival_orders": 5,
    "many_names_per_phone": 3,
    "near_perfect_weight_volume_corr": 0.995,
    "min_density_kg_m3": 0.1,
    "max_density_kg_m3": 2000.0,
}

TABLE_CAUSES = {
    "users": "services/core_api/app/auth/service.py; db/seed/create_admin.py",
    "user_roles": "services/core_api/app/auth/service.py; db/seed/create_admin.py",
    "merchants": "services/core_api/app/admin/routes/merchants.py; db/seed/create_admin.py",
    "merchant_members": "services/core_api/app/admin/routes/merchants.py",
    "warehouses": "services/core_api/app/admin/routes/warehouses.py; db/seed/create_admin.py",
    "warehouse_staff": "services/core_api/app/admin/routes/warehouses.py; services/core_api/app/admin/routes/users.py",
    "vehicles": "No vehicle seed path found under db/seed; admin vehicle creation path not found",
    "drivers": "services/core_api/app/auth/service.py; db/seed/create_admin.py",
    "orders": "services/core_api/app/orders/router.py is a stub; services/simulator/app/main.py has a TODO order generator",
    "routes": "services/routing_worker/app/consumers/orders_consumer.py is a stub",
    "route_stops": "services/routing_worker/app/consumers/orders_consumer.py is a stub",
    "order_events": "No order-event writer found; expected order lifecycle and terminal-event consumer paths",
}


class Audit:
    def __init__(self, connection: asyncpg.Connection) -> None:
        self.connection = connection
        self.checks: list[dict[str, object]] = []
        self.sections: list[tuple[str, list[str]]] = []
        self.tables: set[str] = set()
        self.warehouse_extent: dict[str, float | int | None] = {}
        self.service_radius_m: float | None = None
        self.region_box: dict[str, float] | None = None

    async def fetch(self, query: str, *args: object) -> list[asyncpg.Record]:
        return list(await self.connection.fetch(query, *args))

    async def add_check(
        self,
        name: str,
        rows_affected: int,
        sample_ids: list[object] | None,
        severity: str,
        action: str,
        code_path: str,
    ) -> None:
        self.checks.append({
            "name": name,
            "rows_affected": rows_affected,
            "sample_ids": [str(value) for value in (sample_ids or [])[: CONFIG["sample_limit"]]],
            "severity": severity,
            "action": action,
            "code_path": code_path,
        })

    async def query_check(
        self,
        name: str,
        query: str,
        severity: str,
        action: str,
        code_path: str,
        id_column: str = "id",
    ) -> list[asyncpg.Record]:
        try:
            rows = await self.fetch(query)
            ids = [row[id_column] for row in rows if id_column in row.keys()]
            await self.add_check(name, len(rows), ids, severity if rows else "fine", action if rows else "No action; check passed.", code_path)
            return rows
        except Exception as exc:
            await self.add_check(name, 0, [], "broken", f"Check query failed ({type(exc).__name__}): {exc}", code_path)
            return []

    async def profile(self) -> None:
        table_rows = await self.fetch(
            """SELECT table_name FROM information_schema.tables
               WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
               ORDER BY table_name"""
        )
        self.tables = {row["table_name"] for row in table_rows}
        counts: list[str] = []
        for table in sorted(self.tables):
            quoted = '"' + table.replace('"', '""') + '"'
            count = await self.connection.fetchval(f"SELECT count(*) FROM public.{quoted}")
            counts.append(f"| `{table}` | {count} |")
        await self.add_check(
            "Profile: row counts per table", len(self.tables), [], "fine" if self.tables else "useless",
            "Use these counts as the audit baseline.", "All public tables; writers mapped in the report.",
        )
        self.sections.append(("Row counts", ["| Table | Rows |", "|---|---:|", *counts]))

        stats = await self.fetch(
            """SELECT tablename, attname, null_frac, n_distinct,
                      most_common_vals::text AS most_common_vals,
                      most_common_freqs::text AS most_common_freqs
               FROM pg_stats WHERE schemaname = 'public'
               ORDER BY tablename, attname"""
        )
        stats_lines = ["| Table | Column | null_frac | n_distinct | top values | top frequencies |", "|---|---|---:|---:|---|---|"]
        for row in stats:
            vals = self.md(row["most_common_vals"])
            freqs = self.md(row["most_common_freqs"])
            stats_lines.append(
                f"| `{row['tablename']}` | `{row['attname']}` | {row['null_frac']:.4f} | {row['n_distinct']} | {vals} | {freqs} |"
            )
        await self.add_check(
            "Profile: pg_stats null_frac, n_distinct and top values",
            len(stats), [], "fine" if stats else "useless",
            "Existing statistics are reported. ANALYZE is not run because the session is read-only; refresh statistics separately if required.",
            "PostgreSQL pg_stats; ANALYZE intentionally skipped under default_transaction_read_only=on.",
        )
        self.sections.append(("Column statistics (existing pg_stats)", stats_lines or ["No visible pg_stats rows."]))

        freshness = await self.fetch(
            """SELECT relname AS table_name, last_analyze, last_autoanalyze
               FROM pg_stat_user_tables WHERE schemaname = 'public'
               ORDER BY relname"""
        )
        stale = [row["table_name"] for row in freshness if row["last_analyze"] is None and row["last_autoanalyze"] is None]
        await self.add_check(
            "Profile: ANALYZE freshness",
            len(stale), stale, "useless" if stale else "fine",
            "This read-only audit cannot run ANALYZE. Run it separately on the Neon branch only if statistics refresh is authorized.",
            "Database maintenance; not performed by this read-only script.",
        )
        lines = ["| Table | last_analyze | last_autoanalyze |", "|---|---|---|"]
        lines.extend(f"| `{row['table_name']}` | {row['last_analyze'] or 'never'} | {row['last_autoanalyze'] or 'never'} |" for row in freshness)
        self.sections.append(("Statistics freshness (no ANALYZE executed)", lines))

    async def derive_region(self) -> None:
        if "warehouses" not in self.tables:
            self.region_box = None
            self.service_radius_m = None
            return
        extent = await self.connection.fetchrow(
            """SELECT count(*) AS n, min(ST_X(location::geometry)) AS min_lon,
                      max(ST_X(location::geometry)) AS max_lon,
                      min(ST_Y(location::geometry)) AS min_lat,
                      max(ST_Y(location::geometry)) AS max_lat,
                      avg(ST_Y(location::geometry)) AS mean_lat
               FROM warehouses WHERE is_active"""
        )
        self.warehouse_extent = dict(extent)
        if extent["n"] >= 2:
            self.service_radius_m = float(await self.connection.fetchval(
                """SELECT max(nearest_m) FROM (
                       SELECT w.id, min(ST_Distance(w.location, other.location)) AS nearest_m
                       FROM warehouses w JOIN warehouses other ON other.id <> w.id AND other.is_active
                       WHERE w.is_active GROUP BY w.id
                   ) distances"""
            ))
            # A diagnostic service envelope: warehouse extent padded by the
            # largest nearest-neighbour spacing observed among active warehouses.
            import math
            lat_pad = self.service_radius_m / 111_320.0
            cos_lat = max(abs(math.cos(math.radians(float(extent["mean_lat"])))), 0.01)
            lon_pad = self.service_radius_m / (111_320.0 * cos_lat)
            self.region_box = {
                "min_lon": float(extent["min_lon"]) - lon_pad,
                "max_lon": float(extent["max_lon"]) + lon_pad,
                "min_lat": float(extent["min_lat"]) - lat_pad,
                "max_lat": float(extent["max_lat"]) + lat_pad,
            }
        box_text = "not derivable (need at least two active warehouses)"
        if self.region_box:
            box_text = ", ".join(f"{key}={value:.6f}" for key, value in self.region_box.items())
        radius_text = f"{self.service_radius_m:.0f} m" if self.service_radius_m is not None else "not derivable"
        self.sections.append(("Warehouse-derived region", [
            f"Active warehouses: {extent['n']}",
            f"Diagnostic service radius: {radius_text} (largest active-warehouse nearest-neighbour distance)",
            f"Bounding box: {box_text}",
            "Bounding box uses active warehouse min/max coordinates padded by the derived radius; it is a diagnostic envelope, not a configured dispatch policy.",
        ]))

    async def logic(self) -> None:
        if {"orders", "order_events"} <= self.tables:
            await self.query_check(
                "Logic: order.status vs latest event, including no-event orders",
                """SELECT o.id::text AS id FROM orders o
                   LEFT JOIN LATERAL (SELECT e.to_status FROM order_events e WHERE e.order_id=o.id
                     ORDER BY e.occurred_at DESC, e.id DESC LIMIT 1) last_event ON true
                   WHERE o.status::text IS DISTINCT FROM last_event.to_status::text""",
                "broken", "Reconcile lifecycle state and add/repair the missing event through the order lifecycle writer.",
                "No implemented order-event writer found; expected services/core_api/app/orders/router.py and services/routing_worker/app/consumers/terminal_events_consumer.py.",
            )
            await self.query_check(
                "Logic: order_events chain continuity",
                """WITH ordered AS (
                     SELECT id, order_id, from_status::text AS from_status,
                            lag(to_status::text) OVER (PARTITION BY order_id ORDER BY occurred_at,id) AS previous_to,
                            row_number() OVER (PARTITION BY order_id ORDER BY occurred_at,id) AS event_number
                     FROM order_events)
                   SELECT id::text AS id FROM ordered
                   WHERE (event_number=1 AND from_status IS NOT NULL)
                      OR (event_number>1 AND from_status IS DISTINCT FROM previous_to)""",
                "broken", "Repair the event chain at its lifecycle writer; do not rewrite append-only history without a reviewed migration.",
                "No event writer is implemented in services/core_api/app/orders/router.py or services/routing_worker/app/consumers/terminal_events_consumer.py.",
            )
            pairs = await self.fetch(
                """SELECT coalesce(from_status::text, 'NULL') AS from_status,
                          to_status::text AS to_status, count(*) AS event_count
                   FROM order_events GROUP BY from_status,to_status ORDER BY from_status,to_status"""
            )
            pair_lines = ["| from_status | to_status | events |", "|---|---|---:|"]
            pair_lines.extend(f"| {row['from_status']} | {row['to_status']} | {row['event_count']} |" for row in pairs)
            await self.add_check("Logic: count of each order event (from,to) pair", len(pairs), [], "fine", "Review the transition distribution below against the intended lifecycle.", "order_events writer not found in application paths.")
            self.sections.append(("Order event transition counts", pair_lines))
            await self.query_check(
                "Logic: events before orders.created_at",
                "SELECT e.id::text AS id FROM order_events e JOIN orders o ON o.id=e.order_id WHERE e.occurred_at < o.created_at",
                "broken", "Correct event timestamps or the order/event creation path after verifying source data.",
                "No implemented event writer found; services/core_api/app/orders/router.py and services/routing_worker/app/consumers/terminal_events_consumer.py are stubs.",
            )
        if {"route_stops", "orders"} <= self.tables:
            await self.query_check(
                "Logic: delivered stop but order not delivered",
                "SELECT DISTINCT rs.order_id::text AS id FROM route_stops rs JOIN orders o ON o.id=rs.order_id WHERE rs.status='delivered' AND o.status::text <> 'delivered'",
                "broken", "Reconcile stop and order states through the terminal delivery-event consumer.",
                "services/routing_worker/app/consumers/terminal_events_consumer.py is a stub.",
            )
            await self.query_check(
                "Logic: delivered order without a delivered stop",
                """SELECT o.id::text AS id FROM orders o WHERE o.status::text='delivered'
                   AND NOT EXISTS (SELECT 1 FROM route_stops rs WHERE rs.order_id=o.id AND rs.status='delivered')""",
                "broken", "Verify whether delivery was recorded outside route_stops; otherwise repair via the delivery lifecycle writer.",
                "services/routing_worker/app/consumers/terminal_events_consumer.py is a stub.",
            )
        if {"drivers", "routes"} <= self.tables:
            await self.query_check(
                "Logic: driver.status vs active routes (both directions)",
                """SELECT d.user_id::text AS id FROM drivers d WHERE
                   (d.status::text='on_route') IS DISTINCT FROM EXISTS (
                     SELECT 1 FROM routes r WHERE r.driver_id=d.user_id AND r.status::text='in_progress')""",
                "broken", "Reconcile driver state when route assignment starts or finishes.",
                "services/routing_worker/app/consumers/orders_consumer.py and services/routing_worker/app/consumers/terminal_events_consumer.py are stubs.",
            )
        timestamp_keys = {
            "users": "id::text", "merchants": "id::text", "warehouses": "id::text",
            "vehicles": "id::text", "drivers": "user_id::text", "orders": "id::text",
            "routes": "id::text", "route_stops": "id::text",
            "merchant_members": "user_id::text || ':' || merchant_id::text",
            "warehouse_staff": "user_id::text || ':' || warehouse_id::text",
        }
        created_tables = sorted(self.tables & timestamp_keys.keys())
        if created_tables:
            union = " UNION ALL ".join(
                f"SELECT '{table}' AS table_name, {timestamp_keys[table]} AS id, created_at FROM {table}"
                for table in created_tables
            )
            await self.query_check(
                "Logic: created_at in the future",
                f"SELECT table_name || ':' || id AS id FROM ({union}) records WHERE created_at > now() + interval '{CONFIG['future_clock_skew_seconds']} seconds'",
                "broken", "Correct future timestamps after checking the inserting process clock.",
                "Seed and application insert paths listed in db/seed/create_admin.py and table-specific paths; no general demo data generator exists.",
            )
        updated_tables = sorted(self.tables & (timestamp_keys.keys() - {"merchant_members", "warehouse_staff"}))
        if updated_tables:
            union = " UNION ALL ".join(
                f"SELECT '{table}' AS table_name, {timestamp_keys[table]} AS id, created_at, updated_at FROM {table}"
                for table in updated_tables
            )
            await self.query_check(
                "Logic: updated_at earlier than created_at",
                f"SELECT table_name || ':' || id AS id FROM ({union}) records WHERE updated_at < created_at",
                "broken", "Correct the timestamp update path; updated_at must not predate row creation.",
                "Table-specific create/update handlers; see db/seed/create_admin.py and services/core_api/app/admin/routes/.",
            )
        if "orders" in self.tables:
            await self.query_check(
                "Logic: window_latest earlier than order created_at",
                "SELECT id::text AS id FROM orders WHERE window_latest IS NOT NULL AND window_latest < created_at",
                "broken", "Validate requested windows against creation time in the order intake path.",
                "services/core_api/app/orders/router.py is a stub; external inserts cannot be traced from this repository.",
            )
        if {"route_stops", "routes"} <= self.tables:
            await self.query_check(
                "Logic: arrived_at before route.started_at",
                "SELECT rs.id::text AS id FROM route_stops rs JOIN routes r ON r.id=rs.route_id WHERE rs.arrived_at IS NOT NULL AND r.started_at IS NOT NULL AND rs.arrived_at < r.started_at",
                "broken", "Check driver event timestamps and the route start transition.",
                "services/driver_gateway/app/ingestion/router.py and services/routing_worker/app/consumers/terminal_events_consumer.py are stubs.",
            )

    async def realism(self) -> None:
        if {"orders", "warehouses"} <= self.tables:
            await self.query_check(
                "Realism: assigned warehouse differs from nearest active warehouse",
                """SELECT o.id::text AS id FROM orders o CROSS JOIN LATERAL (
                     SELECT w.id FROM warehouses w WHERE w.is_active
                     ORDER BY w.location <-> o.delivery_location, w.id LIMIT 1) nearest
                   WHERE o.warehouse_id IS DISTINCT FROM nearest.id""",
                "synthetic", "Check warehouse assignment logic and whether the order coordinates are valid.",
                "services/core_api/app/orders/router.py documents KNN assignment but is currently a stub.",
            )
            if self.service_radius_m is None:
                await self.add_check("Realism: order distance from nearest warehouse vs derived service radius", 0, [], "useless", "At least two active warehouses are needed to derive a radius; no fallback radius was guessed.", "Derived from warehouses table.")
            else:
                radius = self.service_radius_m
                await self.query_check(
                    "Realism: order distance from nearest active warehouse exceeds derived radius",
                    f"""SELECT o.id::text AS id FROM orders o CROSS JOIN LATERAL (
                         SELECT ST_Distance(w.location,o.delivery_location) AS distance_m
                         FROM warehouses w WHERE w.is_active ORDER BY w.location <-> o.delivery_location,w.id LIMIT 1) nearest
                       WHERE nearest.distance_m > {radius:.6f}""",
                    "synthetic", "Review out-of-envelope points and the warehouse coverage represented by this data.",
                    "Warehouse geometry source is db/seed/create_admin.py; order coordinate writer is not implemented in services/core_api/app/orders/router.py.",
                )
            if self.region_box is None:
                await self.add_check("Realism: delivery points outside warehouse-derived region box", 0, [], "useless", "Need at least two active warehouses to derive a diagnostic region envelope.", "Derived from warehouses table.")
            else:
                b = self.region_box
                await self.query_check(
                    "Realism: delivery points outside warehouse-derived region box",
                    f"""SELECT id::text AS id FROM orders WHERE
                       ST_X(delivery_location::geometry) < {b['min_lon']:.10f} OR ST_X(delivery_location::geometry) > {b['max_lon']:.10f}
                       OR ST_Y(delivery_location::geometry) < {b['min_lat']:.10f} OR ST_Y(delivery_location::geometry) > {b['max_lat']:.10f}""",
                    "synthetic", "Review coordinates outside the derived warehouse region; correct geocoding or source fixtures as appropriate.",
                    "services/core_api/app/orders/router.py is a stub; db/seed/create_admin.py only seeds one warehouse.",
                )
            await self.query_check(
                "Realism: duplicate delivery pins",
                """SELECT min(id::text) AS id FROM orders GROUP BY ST_X(delivery_location::geometry),ST_Y(delivery_location::geometry) HAVING count(*)>1""",
                "synthetic", "Inspect repeated coordinates to distinguish legitimate shared destinations from placeholder pins.",
                "services/core_api/app/orders/router.py has no implemented geocoder; simulator order generation is a TODO.",
            )
            await self.query_check(
                "Realism: same normalized address with different coordinates",
                """SELECT min(id::text) AS id FROM orders GROUP BY lower(trim(delivery_address))
                   HAVING count(DISTINCT ST_AsEWKB(delivery_location::geometry))>1""",
                "synthetic", "Check address normalization and geocoding consistency.",
                "services/core_api/app/orders/router.py has a TODO for Nominatim geocoding.",
            )
            metrics = await self.connection.fetchrow(
                """SELECT count(*) AS n,
                   percentile_cont(ARRAY[0.0,0.25,0.5,0.75,0.95,0.99,1.0]) WITHIN GROUP (ORDER BY weight_kg) AS weights,
                   percentile_cont(ARRAY[0.0,0.25,0.5,0.75,0.95,0.99,1.0]) WITHIN GROUP (ORDER BY volume_m3) AS volumes,
                   corr(weight_kg::double precision,volume_m3::double precision) AS weight_volume_corr,
                   percentile_cont(ARRAY[0.0,0.5,0.95,0.99,1.0]) WITHIN GROUP (ORDER BY weight_kg::double precision / NULLIF(volume_m3::double precision,0)) AS density
                   FROM orders"""
            )
            metrics_lines = [f"Orders measured: {metrics['n']}", f"Weight percentiles [0,25,50,75,95,99,100]: {metrics['weights']}", f"Volume m³ percentiles [0,25,50,75,95,99,100]: {metrics['volumes']}", f"Density kg/m³ percentiles [0,50,95,99,100]: {metrics['density']}", f"corr(weight_kg, volume_m3): {metrics['weight_volume_corr']}"]
            await self.add_check("Realism: weight and volume percentiles, density and correlation", int(metrics["n"]), [], "fine", "Review the distribution summary below; this check reports measurements rather than assuming a payload distribution.", "Order source: services/core_api/app/orders/router.py (stub) or external imports.")
            self.sections.append(("Order weight, volume, density and correlation", metrics_lines))
            corr = metrics["weight_volume_corr"]
            corr_suspicious = corr is not None and abs(float(corr)) >= CONFIG["near_perfect_weight_volume_corr"]
            densities = await self.fetch("SELECT id::text AS id FROM orders WHERE weight_kg::double precision / NULLIF(volume_m3::double precision,0) < 0.1 OR weight_kg::double precision / NULLIF(volume_m3::double precision,0) > 2000")
            await self.add_check("Realism: implausible order density", len(densities), [r["id"] for r in densities], "synthetic" if densities else "fine", "Inspect outlier weight/volume pairs; adjust source data only after checking units.", "Order intake payload mapping is TODO in services/core_api/app/orders/router.py; simulator generation is TODO.")
            if corr_suspicious:
                await self.add_check("Realism: near-perfect weight/volume correlation", 1, [], "synthetic", "Inspect whether generated dimensions use a fixed formula.", "services/simulator/app/main.py has no implemented order generator; data may have been loaded externally.")
            else:
                await self.add_check("Realism: near-perfect weight/volume correlation", 0, [], "fine", "No near-perfect linear correlation detected.", "services/simulator/app/main.py.")
            vehicles = await self.connection.fetchrow("SELECT max(max_weight_kg) AS max_weight, max(max_volume_m3) AS max_volume, count(*) AS n FROM vehicles WHERE is_active") if "vehicles" in self.tables else None
            if vehicles and vehicles["n"]:
                oversized = await self.fetch(
                    """SELECT o.id::text AS id FROM orders o WHERE o.weight_kg > (SELECT max(max_weight_kg) FROM vehicles WHERE is_active)
                       OR o.volume_m3 > (SELECT max(max_volume_m3) FROM vehicles WHERE is_active)"""
                )
                await self.add_check("Realism: order exceeds largest active vehicle capacity", len(oversized), [r["id"] for r in oversized], "broken" if oversized else "fine", "Correct the package dimensions or expand the active vehicle capacity after confirming units.", "Order source is external; vehicle creation path is absent from db/seed and admin routes.")
            else:
                await self.add_check("Realism: order exceeds largest active vehicle capacity", 0, [], "useless", "No active vehicle capacity exists for comparison.", "No vehicle seed path found under db/seed.")
        if {"routes", "route_stops", "orders", "vehicles"} <= self.tables:
            overloaded = await self.fetch(
                """SELECT r.id::text AS id FROM routes r JOIN vehicles v ON v.id=r.vehicle_id
                   JOIN route_stops rs ON rs.route_id=r.id JOIN orders o ON o.id=rs.order_id
                   GROUP BY r.id,v.max_weight_kg,v.max_volume_m3
                   HAVING sum(o.weight_kg)>v.max_weight_kg OR sum(o.volume_m3)>v.max_volume_m3"""
            )
            await self.add_check("Realism: route load over vehicle capacity", len(overloaded), [r["id"] for r in overloaded], "broken" if overloaded else "fine", "Replan overloaded routes or correct package/vehicle dimensions.", "services/routing_worker/app/consumers/orders_consumer.py has no implemented route writer.")
            fast_stops = await self.fetch(
                f"""WITH ordered AS (
                     SELECT rs.id, rs.route_id, rs.sequence, rs.arrived_at, rs.planned_location,
                       lag(rs.arrived_at) OVER (PARTITION BY rs.route_id ORDER BY rs.sequence) AS prev_arrived,
                       lag(rs.planned_location) OVER (PARTITION BY rs.route_id ORDER BY rs.sequence) AS prev_location
                     FROM route_stops rs)
                   SELECT id::text AS id FROM ordered WHERE arrived_at IS NOT NULL AND prev_arrived IS NOT NULL
                     AND extract(epoch FROM arrived_at-prev_arrived)>0
                     AND ST_Distance(planned_location,prev_location)/extract(epoch FROM arrived_at-prev_arrived)*3.6 > {CONFIG['speed_limit_kmh']}"""
            )
            await self.add_check("Realism: stop-to-stop speed over 90 km/h", len(fast_stops), [r["id"] for r in fast_stops], "synthetic" if fast_stops else "fine", "Review stop coordinates and arrival timestamps; the threshold is 90 km/h.", "services/driver_gateway/app/ingestion/router.py and services/routing_worker/app/consumers/terminal_events_consumer.py are stubs.")
            fast_routes = await self.fetch(
                f"""SELECT id::text AS id FROM routes WHERE total_distance_m IS NOT NULL AND total_duration_s>0
                   AND total_distance_m::double precision / total_duration_s * 3.6 > {CONFIG['speed_limit_kmh']}"""
            )
            await self.add_check("Realism: route distance/duration speed over 90 km/h", len(fast_routes), [r["id"] for r in fast_routes], "synthetic" if fast_routes else "fine", "Check route metrics and unit conversion; threshold is 90 km/h.", "services/routing_worker/app/consumers/orders_consumer.py is a stub.")
        if "orders" in self.tables:
            phones = await self.fetch(
                """SELECT id::text AS id FROM orders WHERE regexp_replace(recipient_phone,'[^0-9]','','g') ~ '^([0-9])\\1{7,}$'"""
            )
            await self.add_check("Realism: repeated-digit recipient phones", len(phones), [r["id"] for r in phones], "synthetic" if phones else "fine", "Replace placeholder phone values with valid demo numbers, preserving constraints.", "Order creation is stubbed in services/core_api/app/orders/router.py; simulator does not generate orders.")
            many_names = await self.fetch(
                f"""SELECT min(id::text) AS id FROM orders GROUP BY recipient_phone
                   HAVING count(DISTINCT lower(trim(recipient_name))) >= {CONFIG['many_names_per_phone']}"""
            )
            await self.add_check("Realism: one recipient phone used for many names", len(many_names), [r["id"] for r in many_names], "synthetic" if many_names else "fine", "Inspect shared phone groups; retain only intentional household/building reuse.", "Order creation is stubbed in services/core_api/app/orders/router.py; simulator does not generate orders.")
        if "users" in self.tables:
            domains = await self.fetch(
                """SELECT lower(split_part(email::text,'@',2)) AS domain, count(*) AS users
                   FROM users WHERE email IS NOT NULL GROUP BY 1 ORDER BY users DESC,domain"""
            )
            lines = ["| Email domain | Users |", "|---|---:|"]
            lines.extend(f"| `{row['domain']}` | {row['users']} |" for row in domains)
            await self.add_check("Realism: user email domain distribution", len(domains), [], "fine", "Review domain distribution below for test-only domains.", "User creation: services/core_api/app/auth/service.py; db/seed/create_admin.py.")
            self.sections.append(("User email domains", lines))
            hashes = await self.connection.fetchrow("SELECT count(*) AS users, count(DISTINCT password_hash) AS distinct_hashes FROM users")
            duplicate_hashes = int(hashes["users"] - hashes["distinct_hashes"])
            await self.add_check("Realism: distinct password_hash count vs users", duplicate_hashes, [], "synthetic" if duplicate_hashes else "fine", f"Users={hashes['users']}; distinct hashes={hashes['distinct_hashes']}. If hashes repeat, inspect seed/import code; do not expose hash values.", "db/seed/create_admin.py and services/core_api/app/auth/service.py.")

    async def provenance(self) -> None:
        identity_columns = {
            "users": "id::text", "merchants": "id::text", "warehouses": "id::text",
            "vehicles": "id::text", "drivers": "user_id::text", "orders": "id::text",
            "routes": "id::text", "route_stops": "id::text",
            "merchant_members": "user_id::text || ':' || merchant_id::text",
            "warehouse_staff": "user_id::text || ':' || warehouse_id::text",
        }
        tables = sorted(self.tables & identity_columns.keys())
        if tables:
            union = " UNION ALL ".join(
                f"SELECT '{table}' AS table_name,{identity_columns[table]} AS id,created_at FROM {table}"
                for table in tables
            )
            shared = await self.fetch(
                f"""SELECT table_name || ':' || min(id) AS id, table_name, created_at, count(*) AS n
                    FROM ({union}) all_created GROUP BY table_name,created_at
                    HAVING count(*) >= {CONFIG['same_created_at_min_rows']} ORDER BY n DESC,table_name LIMIT 200"""
            )
            sample = [row["id"] for row in shared]
            await self.add_check("Provenance: large groups sharing created_at", len(shared), sample, "synthetic" if shared else "fine", f"Inspect batches of at least {CONFIG['same_created_at_min_rows']} rows with identical created_at; seed/import batches can be intentional.", "db/seed/create_admin.py uses server defaults; simulator has no implemented generator.")
            lines = ["| Table | created_at | rows |", "|---|---|---:|"]
            lines.extend(f"| `{r['table_name']}` | {r['created_at']} | {r['n']} |" for r in shared)
            self.sections.append(("Rows sharing created_at", lines))
        if "orders" in self.tables:
            arrivals = await self.connection.fetchrow(
                """WITH gaps AS (SELECT extract(epoch FROM created_at-lag(created_at) OVER (ORDER BY created_at,id)) AS seconds
                                  FROM orders)
                   SELECT count(seconds) AS n, avg(seconds) AS mean_s, stddev_samp(seconds) AS sd_s,
                          stddev_samp(seconds)/NULLIF(avg(seconds),0) AS cv FROM gaps"""
            )
            n = int(arrivals["n"] or 0)
            cv = arrivals["cv"]
            suspicious = n >= CONFIG["min_interarrival_orders"] and cv is not None and float(cv) <= CONFIG["synthetic_interarrival_cv_max"]
            await self.add_check("Provenance: order inter-arrival coefficient of variation", 1 if suspicious else 0, [], "synthetic" if suspicious else ("useless" if n < CONFIG["min_interarrival_orders"] else "fine"), f"Intervals={n}; mean={arrivals['mean_s']}; sd={arrivals['sd_s']}; CV={cv}. Low-CV threshold={CONFIG['synthetic_interarrival_cv_max']}.", "services/simulator/app/main.py has a TODO order generator; import source otherwise unknown.")
            hist = await self.fetch("SELECT extract(hour FROM created_at AT TIME ZONE 'UTC')::int AS hour_utc, count(*) AS orders FROM orders GROUP BY 1 ORDER BY 1")
            hist_lines = ["| UTC hour | Orders |", "|---:|---:|"]
            hist_lines.extend(f"| {r['hour_utc']:02d} | {r['orders']} |" for r in hist)
            await self.add_check("Provenance: order hour-of-day histogram", len(hist), [], "fine", "Inspect the UTC histogram below for batch-shaped or implausible activity windows.", "services/simulator/app/main.py has no order generator implementation.")
            self.sections.append(("Order creation hour histogram (UTC)", hist_lines))
            merchant_dist = await self.fetch(
                """SELECT m.id::text AS id,m.name,count(o.id) AS orders FROM merchants m
                   LEFT JOIN orders o ON o.merchant_id=m.id GROUP BY m.id,m.name ORDER BY orders DESC,m.name"""
            )
            dist_lines = ["| Merchant | Orders |", "|---|---:|"]
            dist_lines.extend(f"| {self.md(r['name'])} (`{r['id']}`) | {r['orders']} |" for r in merchant_dist)
            counts = [int(r["orders"]) for r in merchant_dist]
            summary = f"min={min(counts)}, median={statistics.median(counts)}, max={max(counts)}" if counts else "no merchants"
            await self.add_check("Provenance: orders per merchant distribution", len(merchant_dist), [r["id"] for r in merchant_dist], "fine", f"Merchant distribution: {summary}; detail below.", "services/core_api/app/orders/router.py has no implemented order insert; data may be externally loaded.")
            self.sections.append(("Orders per merchant", dist_lines))
        if "order_events" in self.tables:
            gap_row = await self.connection.fetchrow(
                """SELECT min(id) AS min_id,max(id) AS max_id,count(*) AS n,
                          greatest(coalesce(max(id)-min(id)+1-count(*),0),0) AS gaps FROM order_events"""
            )
            missing = await self.fetch(
                """WITH ordered AS (SELECT id,lag(id) OVER (ORDER BY id) AS prev_id FROM order_events),
                   gaps AS (SELECT generate_series(prev_id+1,id-1) AS missing_id FROM ordered WHERE id-prev_id>1)
                   SELECT missing_id::text AS id FROM gaps ORDER BY missing_id LIMIT 10"""
            ) if gap_row["gaps"] else []
            await self.add_check("Provenance: order_events identity gaps", int(gap_row["gaps"]), [r["id"] for r in missing], "fine", f"min={gap_row['min_id']}, max={gap_row['max_id']}, rows={gap_row['n']}; sequence gaps are normal after rollbacks/concurrent inserts.", "PostgreSQL identity sequence; no repair recommended.")

    async def useless(self) -> None:
        checks = [
            ("Useless: users with no role", """SELECT u.id::text AS id FROM users u WHERE NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id=u.id)""", "broken", "Assign an intended role or remove an accidental unlinked user after review.", "services/core_api/app/auth/service.py; db/seed/create_admin.py."),
            ("Useless: merchants with no members", """SELECT m.id::text AS id FROM merchants m WHERE NOT EXISTS (SELECT 1 FROM merchant_members mm WHERE mm.merchant_id=m.id)""", "useless", "Add a merchant member if the merchant is intended for the demo.", "db/seed/create_admin.py creates a merchant but no member; services/core_api/app/admin/routes/merchants.py creates membership for admins."),
            ("Useless: merchants with no orders", """SELECT m.id::text AS id FROM merchants m WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.merchant_id=m.id)""", "useless", "Add demo orders for active merchants or mark unused fixtures inactive after review.", "services/core_api/app/orders/router.py and services/simulator/app/main.py order generation are TODOs."),
            ("Useless: warehouses with no staff", """SELECT w.id::text AS id FROM warehouses w WHERE NOT EXISTS (SELECT 1 FROM warehouse_staff ws WHERE ws.warehouse_id=w.id)""", "useless", "Assign operational staff only if the warehouse participates in the demo.", "db/seed/create_admin.py creates a warehouse without staff."),
            ("Useless: warehouses with no orders", """SELECT w.id::text AS id FROM warehouses w WHERE NOT EXISTS (SELECT 1 FROM orders o WHERE o.warehouse_id=w.id)""", "useless", "Add orders for the warehouse or mark an unused fixture inactive after review.", "services/core_api/app/orders/router.py has no insert implementation; simulator generation is TODO."),
            ("Useless: merchant_members whose user lacks merchant role", """SELECT mm.user_id::text AS id FROM merchant_members mm WHERE NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id=mm.user_id AND ur.role::text='merchant')""", "broken", "Grant the merchant role or remove the inconsistent membership after review.", "services/core_api/app/admin/routes/merchants.py creates memberships; role grants occur in auth/admin user flows."),
            ("Useless: exact duplicate orders", """SELECT min(id::text) AS id FROM orders GROUP BY merchant_id,merchant_order_ref,warehouse_id,customer_id,status,recipient_name,recipient_phone,delivery_address,ST_AsEWKB(delivery_location::geometry),window_earliest,window_latest,weight_kg,volume_m3,tracking_token,created_at,updated_at HAVING count(*)>1""", "broken", "Review duplicate imports; unique merchant/order-reference and tracking-token constraints should normally prevent these.", "Order insert path is not implemented in services/core_api/app/orders/router.py; external importer unknown."),
        ]
        for name, query, severity, action, cause in checks:
            await self.query_check(name, query, severity, action, cause)

    async def insights(self) -> None:
        if {"orders", "order_events"} <= self.tables:
            lifecycle = await self.connection.fetchrow(
                """SELECT count(*) AS covered_orders,
                          count(*) FILTER (WHERE event_count=1) AS one_event_orders,
                          count(*) FILTER (WHERE event_count>1) AS multi_event_orders,
                          max(event_count) AS max_events_per_order
                   FROM (SELECT o.id,count(e.id) AS event_count
                         FROM orders o LEFT JOIN order_events e ON e.order_id=o.id
                         GROUP BY o.id) counts"""
            )
            one_event = await self.fetch(
                """SELECT order_id::text AS id FROM order_events
                   GROUP BY order_id HAVING count(*)=1"""
            )
            await self.add_check(
                "Logic: order lifecycle event depth",
                int(lifecycle["one_event_orders"]), [row["id"] for row in one_event],
                "synthetic" if lifecycle["one_event_orders"] and not lifecycle["multi_event_orders"] else "fine",
                f"Orders with events={lifecycle['covered_orders']}; exactly one event={lifecycle['one_event_orders']}; multiple events={lifecycle['multi_event_orders']}; max events/order={lifecycle['max_events_per_order']}. A single initial event per order does not demonstrate a lifecycle.",
                "No implemented order-event writer found in services/core_api/app/orders/router.py or services/routing_worker/app/consumers/terminal_events_consumer.py; rows appear externally loaded.",
            )
            status_counts = await self.fetch(
                "SELECT status::text AS status,count(*) AS n FROM orders GROUP BY status ORDER BY status"
            )
            status_lines = ["| Order status | Orders |", "|---|---:|"]
            status_lines.extend(f"| {row['status']} | {row['n']} |" for row in status_counts)
            self.sections.append(("Order status distribution", status_lines))
            event_link_rows = await self.fetch(
                """SELECT order_id::text AS id FROM order_events
                   WHERE to_status::text IN ('delivered','attempt_failed') AND route_stop_id IS NULL"""
            )
            await self.add_check(
                "Logic: terminal delivery events without route_stop reference",
                len(event_link_rows), [row["id"] for row in event_link_rows],
                "broken" if event_link_rows else "fine",
                "Link terminal attempt events to their route stop, or verify whether these events were bulk-generated independently of route operations.",
                "No implemented terminal-event persistence path found in services/routing_worker/app/consumers/terminal_events_consumer.py.",
            )
        if {"routes", "route_stops"} <= self.tables:
            route_rows = await self.fetch(
                """SELECT r.id::text AS route_id,r.status::text AS status,r.started_at,r.completed_at,
                          count(rs.id) AS stops,
                          count(rs.id) FILTER (WHERE rs.status::text='delivered') AS delivered_stops,
                          count(rs.id) FILTER (WHERE rs.status::text='failed') AS failed_stops,
                          count(rs.id) FILTER (WHERE rs.status::text='pending') AS pending_stops
                   FROM routes r LEFT JOIN route_stops rs ON rs.route_id=r.id
                   GROUP BY r.id,r.status,r.started_at,r.completed_at ORDER BY r.created_at,r.id"""
            )
            route_lines = ["| Route | Status | Started | Completed | Stops | Delivered | Failed | Pending |", "|---|---|---|---|---:|---:|---:|---:|"]
            route_lines.extend(
                f"| `{row['route_id']}` | {row['status']} | {row['started_at'] or '—'} | {row['completed_at'] or '—'} | {row['stops']} | {row['delivered_stops']} | {row['failed_stops']} | {row['pending_stops']} |"
                for row in route_rows
            )
            self.sections.append(("Route and stop operational summary", route_lines))
        if {"orders", "order_events", "warehouses"} <= self.tables:
            rows = await self.fetch(
                """SELECT w.id::text AS warehouse_id,w.name,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM (delivered_at-o.created_at))) AS median_seconds,
                   count(*) AS delivered_orders FROM orders o JOIN warehouses w ON w.id=o.warehouse_id
                   JOIN LATERAL (SELECT min(e.occurred_at) AS delivered_at FROM order_events e WHERE e.order_id=o.id AND e.to_status::text='delivered') d ON d.delivered_at IS NOT NULL
                   GROUP BY w.id,w.name ORDER BY w.name"""
            )
            lines = ["| Warehouse | Median create-to-delivered (s) | Delivered orders |", "|---|---:|---:|"]
            lines.extend(f"| {self.md(r['name'])} (`{r['warehouse_id']}`) | {r['median_seconds']:.1f} | {r['delivered_orders']} |" for r in rows)
            await self.add_check("Insight: median created-to-delivered time per warehouse", len(rows), [r["warehouse_id"] for r in rows], "fine", "Metric is based on the first delivered order_event per order; see detail below.", "Order-event insertion path is not implemented in services/core_api/app/orders/router.py or routing worker terminal consumer.")
            self.sections.append(("Median create-to-delivered by warehouse", lines))
        if {"orders", "merchants"} <= self.tables:
            rows = await self.fetch(
                """SELECT m.id::text AS merchant_id,m.name,count(o.id) AS total,
                   count(o.id) FILTER (WHERE o.status::text='delivered') AS delivered,
                   count(o.id) FILTER (WHERE o.status::text='delivered')::double precision/NULLIF(count(o.id),0) AS rate
                   FROM merchants m LEFT JOIN orders o ON o.merchant_id=m.id GROUP BY m.id,m.name ORDER BY m.name"""
            )
            lines = ["| Merchant | Delivered | Total | Delivery rate |", "|---|---:|---:|---:|"]
            lines.extend(f"| {self.md(r['name'])} (`{r['merchant_id']}`) | {r['delivered']} | {r['total']} | {r['rate']:.1%}" if r["rate"] is not None else f"| {self.md(r['name'])} (`{r['merchant_id']}`) | 0 | 0 | n/a" for r in rows)
            await self.add_check("Insight: delivery rate per merchant", len(rows), [r["merchant_id"] for r in rows], "fine", "Metric uses orders.status='delivered' divided by all merchant orders; see detail below.", "Order creation/delivery writers are stubs; external data source unknown.")
            self.sections.append(("Delivery rate by merchant", lines))
        if {"orders", "route_stops"} <= self.tables:
            rows = await self.fetch(
                """WITH attempts AS (
                     SELECT rs.order_id,rs.status::text,
                       row_number() OVER (PARTITION BY rs.order_id ORDER BY r.started_at NULLS LAST,rs.sequence,rs.created_at) AS attempt_number
                     FROM route_stops rs JOIN routes r ON r.id=rs.route_id
                     WHERE rs.status::text IN ('delivered','failed'))
                   SELECT count(*) FILTER (WHERE status='delivered' AND attempt_number=1) AS first_success,
                          count(*) FILTER (WHERE attempt_number=1) AS attempted_orders,
                          count(*) FILTER (WHERE status='delivered') AS delivered_attempts
                   FROM attempts"""
            )
            r = rows[0]
            first_rate = (r["first_success"] / r["attempted_orders"]) if r["attempted_orders"] else None
            await self.add_check("Insight: first-attempt success", int(r["attempted_orders"]), [], "fine", f"First-attempt delivered={r['first_success']}; first-attempt denominator={r['attempted_orders']}; rate={first_rate:.1%}" if first_rate is not None else "No attempted orders.", "Route-stop generation is not implemented in services/routing_worker/app/consumers/orders_consumer.py.")
            self.sections.append(("First-attempt success", [f"First-attempt success rate: {first_rate:.1%}" if first_rate is not None else "First-attempt success rate: n/a (no attempts)", f"First-attempt successes: {r['first_success']}", f"Orders with an attempt: {r['attempted_orders']}"]))
        if {"routes", "route_stops"} <= self.tables:
            rows = await self.fetch(
                """SELECT r.driver_id::text || ':' || (r.started_at AT TIME ZONE 'UTC')::date::text AS id,
                   count(*) AS stops,avg(count(*)) OVER () AS average_stops_per_driver_day
                   FROM routes r JOIN route_stops rs ON rs.route_id=r.id WHERE r.started_at IS NOT NULL
                   GROUP BY r.driver_id,(r.started_at AT TIME ZONE 'UTC')::date ORDER BY id"""
            )
            lines = ["| Driver: UTC date | Stops |", "|---|---:|"]
            lines.extend(f"| `{r['id']}` | {r['stops']} |" for r in rows)
            await self.add_check("Insight: stops per driver per day", len(rows), [r["id"] for r in rows], "fine", "Counts route stops by UTC date of route.started_at; see detail below.", "Route creation is not implemented in services/routing_worker/app/consumers/orders_consumer.py.")
            self.sections.append(("Stops per driver per day", lines))

    @staticmethod
    def md(value: object) -> str:
        if value is None:
            return "—"
        return str(value).replace("|", "\\|").replace("\n", " ")

    def render(self, connected_at: datetime) -> str:
        lines = [
            "# Database Data Audit",
            "",
            f"Read-only audit generated at {connected_at.isoformat()}.",
            "",
            "The session set `default_transaction_read_only=on` and verified it before querying. No data-changing statements were issued.",
            "`ANALYZE` was not executed: PostgreSQL rejects it under read-only mode and it updates database statistics. Existing `pg_stats` values and analyze timestamps are reported instead.",
            "",
            "## Checks",
            "",
            "| Check name | Rows affected | 10 sample IDs | Severity | Proposed action | Likely inserting code path |",
            "|---|---:|---|---|---|---|",
        ]
        for check in self.checks:
            ids = ", ".join(f"`{self.md(item)}`" for item in check["sample_ids"]) or "—"
            lines.append(
                f"| {self.md(check['name'])} | {check['rows_affected']} | {ids} | **{check['severity']}** | {self.md(check['action'])} | {self.md(check['code_path'])} |"
            )
        for title, body in self.sections:
            lines.extend(["", f"## {title}", "", *body])
        lines.extend(["", "## Source-path review", "", "- `db/seed/create_admin.py` inserts only the seed admin, one warehouse, one merchant, and one pending driver. It does not insert merchant membership, warehouse staff, vehicles, orders, routes, stops, or order events.", "- `services/simulator/app/main.py` has TODOs for driver simulation and synthetic order generation; both functions currently do no inserts or requests.", "- `services/core_api/app/orders/router.py` returns a stub order response and has TODOs for geocoding, warehouse assignment, persistence, and stream publishing.", "- `services/driver_gateway/app/ingestion/router.py` accepts a request but the Redis XADD is a TODO; it does not write Postgres.", "- `services/routing_worker/app/consumers/orders_consumer.py` and `terminal_events_consumer.py` are stubs; they do not create routes/stops or persist delivery events.", "- Therefore, demo rows beyond `create_admin.py` fixtures were not attributable to an implemented repository writer and may have been loaded externally.", ""])
        return "\n".join(lines)


def connection_args(database_url: str) -> dict[str, object]:
    parsed = urlsplit(database_url)
    if parsed.scheme not in {"postgresql", "postgres", "postgresql+asyncpg"}:
        raise ValueError("DATABASE_URL must use postgresql:// or postgresql+asyncpg://")
    query = parse_qs(parsed.query)
    ssl = query.get("ssl", query.get("sslmode", ["require"]))[0]
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or ""),
        "password": unquote(parsed.password or ""),
        "database": unquote(parsed.path.lstrip("/")),
        "ssl": ssl,
        "timeout": 10,
        "command_timeout": 60,
        "server_settings": {"default_transaction_read_only": "on"},
    }


async def run() -> None:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is required; load it from the Neon branch environment.")
    connection = await asyncpg.connect(**connection_args(database_url))
    try:
        await connection.execute("SET default_transaction_read_only = on")
        read_only = await connection.fetchval("SHOW default_transaction_read_only")
        if read_only != "on":
            raise RuntimeError("PostgreSQL did not enable default_transaction_read_only.")
        audit = Audit(connection)
        await audit.profile()
        if not audit.tables:
            await audit.add_check(
                "Audit blocked: no application tables visible in public schema", 0, [], "useless",
                "No requested data checks can run because this DATABASE_URL database has no public application tables. Point DATABASE_URL at the Neon branch containing the demo schema, then rerun.",
                "DATABASE_URL currently resolves to an empty public schema; no application writer can explain absent schema.",
            )
            report_path = REPO_ROOT / "audit_report.md"
            report_path.write_text(audit.render(datetime.now(timezone.utc)), encoding="utf-8")
            print(f"Audit blocked: no application tables visible: {report_path}")
            print("Read-only mode: on")
            return
        await audit.derive_region()
        await audit.logic()
        await audit.realism()
        await audit.provenance()
        await audit.useless()
        await audit.insights()
        report_path = REPO_ROOT / "audit_report.md"
        report_path.write_text(audit.render(datetime.now(timezone.utc)), encoding="utf-8")
        print(f"Read-only audit completed: {report_path}")
        print(f"Checks recorded: {len(audit.checks)}")
        print(f"Read-only mode: {read_only}")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(run())
