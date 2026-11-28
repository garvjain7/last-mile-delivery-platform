from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.database import get_database_engine
from app.redis_client import redis_client

router = APIRouter(tags=["Rescue"])


@router.post("/rescue/{route_id}")
async def request_route_rescue(route_id: UUID):

    engine = get_database_engine()

    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("""
                    SELECT
                        id::text AS route_id,
                        driver_id::text AS driver_id,
                        status::text AS status
                    FROM public.routes
                    WHERE id = :route_id
                """),
                {"route_id": route_id}
            )

            route = result.mappings().first()

    finally:
        await engine.dispose()

    if not route:
        raise HTTPException(
            status_code=404,
            detail="Route not found"
        )

    if route["status"] != "in_progress":
        raise HTTPException(
            status_code=400,
            detail="Rescue can only be requested for active routes"
        )

    event_id = await redis_client.xadd(
        "orders_stream",
        {
            "event_type": "route.rescue_requested",
            "route_id": str(route_id),
            "driver_id": route["driver_id"] or "",
            "reason": "Manual rescue request from Control Tower",
        },
    )

    return {
        "message": "Rescue request published",
        "route_id": str(route_id),
        "event_id": event_id,
        "stream": "orders_stream",
    }