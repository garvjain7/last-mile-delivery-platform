
import json

from fastapi import APIRouter, HTTPException
from app.redis_client import redis_client

router = APIRouter()


@router.get("/routes/{route_id}", tags=["Route State"])
async def get_route_state(route_id: str):
    key = f"fleet:route:{route_id}"
    data = await redis_client.hgetall(key)

    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Route '{route_id}' not found",
        )

    stops = data.get("stops", "[]")

    try:
        stops = json.loads(stops)
    except (TypeError, json.JSONDecodeError):
        stops = []

    return {
        "route_id": route_id,
        **data,
        "stops": stops,
    }
