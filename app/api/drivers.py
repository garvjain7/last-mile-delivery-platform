from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_database_engine

router = APIRouter()
ALLOWED_DRIVER_STATUSES = {"pending", "offline", "available", "on_route", "rejected"}


@router.get("/drivers")
async def get_drivers():
    engine = get_database_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT user_id, vehicle_id, status, created_at, updated_at
                FROM public.drivers
                ORDER BY created_at DESC
                LIMIT 100
            """))
            return [dict(row) for row in result.mappings().all()]
    except SQLAlchemyError as exc:
        print("GET /drivers database error:", repr(exc))
        raise HTTPException(status_code=500, detail="Could not fetch drivers from the database.") from exc
    finally:
        await engine.dispose()


@router.get("/drivers/status/{status}")
async def get_drivers_by_status(status: str):
    status = status.lower()
    if status not in ALLOWED_DRIVER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid driver status.")
    engine = get_database_engine()
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("""
                SELECT user_id, vehicle_id, status, created_at, updated_at
                FROM public.drivers
                WHERE status::text = :status
                ORDER BY created_at DESC
                LIMIT 100
            """), {"status": status})
            return [dict(row) for row in result.mappings().all()]
    except SQLAlchemyError as exc:
        print("GET /drivers/status database error:", repr(exc))
        raise HTTPException(status_code=500, detail="Could not fetch drivers by status.") from exc
    finally:
        await engine.dispose()


@router.patch("/drivers/{user_id}/status")
async def update_driver_status(user_id: str, status: str = Query(...)):
    status = status.lower()
    if status not in ALLOWED_DRIVER_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid driver status. Allowed: {', '.join(sorted(ALLOWED_DRIVER_STATUSES))}.")

    engine = get_database_engine()
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text("""
                UPDATE public.drivers
                SET status = CAST(:status AS public.driver_status), updated_at = NOW()
                WHERE user_id = CAST(:user_id AS uuid)
                RETURNING user_id, vehicle_id, status, created_at, updated_at
            """), {"status": status, "user_id": user_id})
            row = result.mappings().first()
            if row is None:
                raise HTTPException(status_code=404, detail="Driver not found.")
            return dict(row)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        print("PATCH /drivers status database error:", repr(exc))
        raise HTTPException(status_code=400, detail="Could not update driver status. Check the user ID and status.") from exc
    finally:
        await engine.dispose()
