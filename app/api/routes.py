from fastapi import APIRouter, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_database_engine

router = APIRouter()


@router.post("/routes")
async def create_route(warehouse_id: str, driver_id: str, vehicle_id: str):
    engine = get_database_engine()
    try:
        async with engine.begin() as connection:
            warehouse = (await connection.execute(text("""
                SELECT id FROM public.warehouses WHERE id = CAST(:warehouse_id AS uuid)
            """), {"warehouse_id": warehouse_id})).mappings().first()
            if warehouse is None:
                raise HTTPException(status_code=404, detail="Warehouse not found.")

            driver = (await connection.execute(text("""
                SELECT user_id FROM public.drivers
                WHERE user_id = CAST(:driver_id AS uuid)
                  AND vehicle_id = CAST(:vehicle_id AS uuid)
                  AND status = 'available'
            """), {"driver_id": driver_id, "vehicle_id": vehicle_id})).mappings().first()
            if driver is None:
                raise HTTPException(status_code=400, detail="Driver must be available and assigned to this vehicle.")

            vehicle = (await connection.execute(text("""
                SELECT id FROM public.vehicles
                WHERE id = CAST(:vehicle_id AS uuid) AND is_active = TRUE
            """), {"vehicle_id": vehicle_id})).mappings().first()
            if vehicle is None:
                raise HTTPException(status_code=400, detail="Vehicle not found or inactive.")

            result = await connection.execute(text("""
                INSERT INTO public.routes (warehouse_id, driver_id, vehicle_id, status)
                VALUES (CAST(:warehouse_id AS uuid), CAST(:driver_id AS uuid),
                        CAST(:vehicle_id AS uuid), 'planned')
                RETURNING id, warehouse_id, driver_id, vehicle_id, status,
                          version, created_at
            """), {"warehouse_id": warehouse_id, "driver_id": driver_id, "vehicle_id": vehicle_id})
            return dict(result.mappings().one())
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        print("POST /routes database error:", repr(exc))
        raise HTTPException(status_code=400, detail="Could not create route. Check the IDs and database constraints.") from exc
    finally:
        await engine.dispose()


@router.post("/routes/{route_id}/stops")
async def add_order_to_route(route_id: str, order_id: str):
    engine = get_database_engine()
    try:
        async with engine.begin() as connection:
            route = (await connection.execute(text("""
                SELECT id, warehouse_id, status
                FROM public.routes WHERE id = CAST(:route_id AS uuid)
                FOR UPDATE
            """), {"route_id": route_id})).mappings().first()
            if route is None:
                raise HTTPException(status_code=404, detail="Route not found.")
            if route["status"] not in ("planned", "in_progress"):
                raise HTTPException(status_code=400, detail="Orders can only be added to planned or in-progress routes.")

            order = (await connection.execute(text("""
                SELECT id, warehouse_id, status, window_earliest
                FROM public.orders WHERE id = CAST(:order_id AS uuid)
                FOR UPDATE
            """), {"order_id": order_id})).mappings().first()
            if order is None:
                raise HTTPException(status_code=404, detail="Order not found.")
            if order["warehouse_id"] != route["warehouse_id"]:
                raise HTTPException(status_code=400, detail="Order and route must belong to the same warehouse.")
            if order["status"] != "pending":
                raise HTTPException(status_code=400, detail="Only pending orders can be added to a route.")

            sequence = (await connection.execute(text("""
                SELECT COALESCE(MAX(sequence), 0) + 1
                FROM public.route_stops WHERE route_id = CAST(:route_id AS uuid)
            """), {"route_id": route_id})).scalar_one()

            result = await connection.execute(text("""
                INSERT INTO public.route_stops (
                    route_id, order_id, sequence, status,
                    planned_location, planned_arrival_at
                ) VALUES (
                    CAST(:route_id AS uuid), CAST(:order_id AS uuid), :sequence,
                    'pending',
                    (SELECT delivery_location FROM public.orders WHERE id = CAST(:order_id AS uuid)),
                    COALESCE(:window_earliest, NOW())
                )
                RETURNING id, route_id, order_id, sequence, status,
                          planned_arrival_at, created_at
            """), {"route_id": route_id, "order_id": order_id,
                  "sequence": sequence, "window_earliest": order["window_earliest"]})
            stop = dict(result.mappings().one())

            await connection.execute(text("""
                UPDATE public.orders
                SET status = 'assigned', updated_at = NOW()
                WHERE id = CAST(:order_id AS uuid)
            """), {"order_id": order_id})
            stop["order_status"] = "assigned"
            return stop
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        print("POST /routes/{route_id}/stops database error:", repr(exc))
        raise HTTPException(status_code=400, detail="Could not add order to route. Check the IDs, status, and database constraints.") from exc
    finally:
        await engine.dispose()
