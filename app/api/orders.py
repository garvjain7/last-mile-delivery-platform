from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_database_engine
from app.orders_schema import OrderCreate

router = APIRouter()


@router.get("/orders")
async def get_orders():
    engine = get_database_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT id, merchant_order_ref, status, recipient_name,
                       delivery_address, created_at
                FROM public.orders
                ORDER BY created_at DESC
                LIMIT 100
            """))
            return [dict(row) for row in result.mappings().all()]
    except SQLAlchemyError as exc:
        print("GET /orders database error:", repr(exc))
        raise HTTPException(status_code=500, detail="Could not fetch orders from the database.") from exc
    finally:
        await engine.dispose()


@router.get("/orders/status/{status}")
async def get_orders_by_status(status: str):
    engine = get_database_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT id, merchant_order_ref, status, recipient_name,
                       delivery_address, created_at
                FROM public.orders
                WHERE status::text = :status
                ORDER BY created_at DESC
                LIMIT 100
            """), {"status": status.lower()})
            return [dict(row) for row in result.mappings().all()]
    except SQLAlchemyError as exc:
        print("GET /orders/status database error:", repr(exc))
        raise HTTPException(status_code=500, detail="Could not fetch orders by status.") from exc
    finally:
        await engine.dispose()


@router.get("/orders/{order_id}")
async def get_order_by_id(order_id: str):
    engine = get_database_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT id, merchant_order_ref, status, recipient_name,
                       recipient_phone, delivery_address, created_at
                FROM public.orders
                WHERE id = CAST(:order_id AS uuid)
            """), {"order_id": order_id})
            row = result.mappings().first()
            if row is None:
                raise HTTPException(status_code=404, detail="Order not found.")
            return dict(row)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        print("GET /orders/{order_id} database error:", repr(exc))
        raise HTTPException(status_code=500, detail="Could not fetch the order.") from exc
    finally:
        await engine.dispose()


@router.post("/orders", status_code=status.HTTP_201_CREATED)
async def create_order(order: OrderCreate):
    # OrderCreate should provide the fields used below, including longitude/latitude.
    data = order.model_dump()
    engine = get_database_engine()
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text("""
                INSERT INTO public.orders (
                    merchant_id, merchant_order_ref, warehouse_id, customer_id,
                    status, recipient_name, recipient_phone, delivery_address,
                    delivery_location, window_earliest, window_latest,
                    weight_kg, volume_m3, tracking_token
                ) VALUES (
                    CAST(:merchant_id AS uuid), :merchant_order_ref,
                    CAST(:warehouse_id AS uuid), CAST(:customer_id AS uuid),
                    'pending', :recipient_name, :recipient_phone, :delivery_address,
                    ST_SetSRID(ST_MakePoint(:longitude, :latitude), 4326)::geography,
                    :window_earliest, :window_latest, :weight_kg, :volume_m3,
                    COALESCE(:tracking_token, generate_tracking_token(10))
                )
                RETURNING id, merchant_order_ref, status, recipient_name,
                          delivery_address, created_at
            """), data)
            row = result.mappings().one()
            return dict(row)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        print("POST /orders database error:", repr(exc))
        raise HTTPException(status_code=400, detail="Could not create order. Check required fields, UUIDs, and database constraints.") from exc
    finally:
        await engine.dispose()
