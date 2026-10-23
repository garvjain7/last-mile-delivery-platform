
from fastapi import APIRouter, HTTPException

from app.redis_client import redis_client

router = APIRouter(tags=["Rescue"])


@router.post("/rescue/{route_id}")
async def request_route_rescue(route_id: str):
    route_key = f"fleet:route:{route_id}"
    route = await redis_client.hgetall(route_key)

    if not route:
        raise HTTPException(
            status_code=404,
            detail=f"Route '{route_id}' not found",
        )

    event_id = await redis_client.xadd(
        "orders_stream",
        {
            "event_type": "route.rescue_requested",
            "route_id": route_id,
            "driver_id": route.get("driver_id", ""),
            "reason": "Manual rescue request from Control Tower",
        },
    )

    return {
        "message": "Rescue request published",
        "route_id": route_id,
        "event_id": event_id,
        "stream": "orders_stream",
    }
