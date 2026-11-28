
import json

from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_database_engine
from app.redis_client import redis_client

router = APIRouter()


@router.get("/dashboard/data")
async def get_dashboard_data():

    # STEP 1: Fetch statistics from Neon PostgreSQL
    engine = get_database_engine()

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM public.orders)
                        AS total_orders,

                    (SELECT COUNT(*) FROM public.orders
                     WHERE status = 'delivered')
                        AS delivered_orders,

                    (SELECT COUNT(*) FROM public.orders
                     WHERE status = 'pending')
                        AS pending_orders,

                    (SELECT COUNT(*) FROM public.orders
                     WHERE status = 'out_for_delivery')
                        AS out_for_delivery,

                    (SELECT COUNT(*) FROM public.drivers)
                        AS total_drivers,

                    (SELECT COUNT(*) FROM public.drivers
                     WHERE status = 'available')
                        AS available_drivers,

                    (SELECT COUNT(*) FROM public.routes
                     WHERE status = 'in_progress')
                        AS active_routes,

                    (SELECT COUNT(*) FROM public.routes
                     WHERE status = 'completed')
                        AS completed_routes,

                    (SELECT COUNT(*) FROM public.vehicles)
                        AS total_vehicles
            """))

            stats = dict(result.mappings().one())
            # STEP: Fetch recent shipment records and their event history
            shipment_result = await connection.execute(text("""
                SELECT
                    o.id::text AS order_id,
                    o.merchant_order_ref,
                    o.recipient_name,
                    o.locality,
                    o.status::text AS status,
                    o.created_at,

                    COALESCE(
                        (
                            SELECT json_agg(
                                json_build_object(
                                    'from_status', events.from_status,
                                    'to_status', events.to_status,
                                    'occurred_at', events.occurred_at
                                )
                                ORDER BY events.occurred_at
                            )
                            FROM (
                                SELECT
                                    from_status::text AS from_status,
                                    to_status::text AS to_status,
                                    occurred_at
                                FROM public.order_events
                                WHERE order_id = o.id
                                ORDER BY occurred_at
                            ) events
                        ),
                        '[]'::json
                    ) AS events,

                    (
                        SELECT rs.status::text
                        FROM public.route_stops rs
                        WHERE rs.order_id = o.id
                        ORDER BY rs.updated_at DESC
                        LIMIT 1
                    ) AS stop_status

                FROM (
    SELECT ranked.*
    FROM (
        SELECT
            orders.*,
            ROW_NUMBER() OVER (
                PARTITION BY status
                ORDER BY created_at DESC
            ) AS status_rank
        FROM public.orders
    ) ranked
    WHERE ranked.status_rank <= 20
) o
ORDER BY o.created_at DESC
            """))

            shipments = []

            for row in shipment_result.mappings().all():
                shipment = dict(row)

                # Ensure events is a Python list, not a JSON string
                if isinstance(shipment["events"], str):
                    shipment["events"] = json.loads(shipment["events"])

                shipments.append(shipment)

            # Fetch actual warehouse information from Neon
            warehouse_result = await connection.execute(text("""
                SELECT
                    w.id::text AS warehouse_id,
                    w.code,
                    w.name,
                    w.address,
                    w.is_active,
                    COUNT(o.id) AS total_orders,
                    COUNT(o.id) FILTER (
                        WHERE o.status = 'out_for_delivery'
                    ) AS out_for_delivery,
                    COUNT(o.id) FILTER (
                        WHERE o.status = 'delivered'
                    ) AS delivered_orders
                FROM public.warehouses w
                LEFT JOIN public.orders o
                    ON o.warehouse_id = w.id
                GROUP BY w.id
                ORDER BY w.code
            """))

            db_warehouses = [
                dict(row)
                for row in warehouse_result.mappings().all()
            ]

            # Fetch all registered drivers from Neon
            driver_result = await connection.execute(text("""
                SELECT
                    d.user_id::text AS driver_id,
                    u.full_name AS driver_name,
                    d.vehicle_id::text AS vehicle_id,
                    d.status::text AS status
                FROM public.drivers d
                JOIN public.users u ON u.id = d.user_id
                ORDER BY u.full_name
            """))

            db_drivers = [
                dict(row) for row in driver_result.mappings().all()
            ]

                        # Fetch all saved routes and their stops from Neon
            route_result = await connection.execute(text("""
                SELECT
                    r.id::text AS route_id,
                    r.driver_id::text AS driver_id,
                    r.vehicle_id::text AS vehicle_id,
                    r.status::text AS status,
                    r.version,
                    r.total_distance_m,
                    r.total_duration_s,
                    COUNT(rs.id) AS total_stops,

                    COALESCE(
                        json_agg(
                            json_build_object(
                                'stop_id', rs.id::text,
                                'order_id', rs.order_id::text,
                                'recipient_name', o.recipient_name,
                                'sequence', rs.sequence,
                                'order_status', o.status::text,
                                'stop_status', rs.status::text
                            )
                            ORDER BY rs.sequence
                        ) FILTER (WHERE rs.id IS NOT NULL),
                        '[]'::json
                    ) AS stops

                FROM public.routes r

                LEFT JOIN public.route_stops rs
                    ON rs.route_id = r.id

                LEFT JOIN public.orders o
                    ON o.id = rs.order_id

                GROUP BY r.id
                ORDER BY r.created_at DESC
            """))

            db_routes = [
                dict(row) for row in route_result.mappings().all()
            ]

            # Fetch recent delivery exceptions
            exception_result = await connection.execute(text("""
                SELECT
                    e.id::text AS exception_id,
                    e.order_id::text AS order_id,
                    e.route_id::text AS route_id,
                    e.driver_id::text AS driver_id,
                    o.recipient_name,
                    u.full_name AS driver_name,
                    e.failure_reason::text AS failure_reason,
                    e.notes,
                    e.return_to_hub,
                    e.created_at
                FROM public.delivery_exceptions e
                LEFT JOIN public.orders o
                    ON o.id = e.order_id
                LEFT JOIN public.users u
                    ON u.id = e.driver_id
                ORDER BY e.created_at DESC
                LIMIT 20
            """))

            db_exceptions = [
                dict(row)
                for row in exception_result.mappings().all()
            ]

    except SQLAlchemyError as e:
        print("DASHBOARD DATABASE ERROR:", repr(e))
        raise HTTPException(
            status_code=500,
            detail="Could not fetch dashboard statistics."
        ) from e

    finally:
        await engine.dispose()

    # STEP 2: Fetch live driver information from Redis
    driver_ids = await redis_client.smembers("fleet:drivers")
    route_ids = await redis_client.smembers("fleet:routes:active")

    # Merge Redis live data with Neon driver records
    live_drivers = {}

    for driver_id in driver_ids:
        data = await redis_client.hgetall(
            f"fleet:driver:active:{driver_id}"
        )
        if data:
            live_drivers[driver_id] = data

    drivers = []

    for driver in db_drivers:
        driver_id = driver["driver_id"]

        drivers.append({
            **driver,
            **live_drivers.get(driver_id, {}),
            "driver_id": driver_id,
        })

    # Merge Redis live data with Neon route records
    live_routes = {}

    for route_id in route_ids:
        data = await redis_client.hgetall(
            f"fleet:route:{route_id}"
        )

        if data:
            live_routes[route_id] = data

    routes = []

    for route in db_routes:
        route_id = route["route_id"]
        live_data = live_routes.get(route_id, {})

        stops = route.get("stops", [])

        if isinstance(stops, str):
            try:
                stops = json.loads(stops)
            except json.JSONDecodeError:
                stops = []

        routes.append({
            **route,
            **live_data,
            "route_id": route_id,
            "stops": stops,
        })

    return {
    "stats": stats,
    "drivers": drivers,
    "routes": routes,
    "shipments": shipments,
    "warehouses": db_warehouses,
    "exceptions": db_exceptions,
}