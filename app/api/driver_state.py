
from fastapi import APIRouter, HTTPException

from app.redis_client import redis_client

router = APIRouter(tags=["Driver State"])


@router.get("/drivers/{driver_id}/state")
async def get_driver_state(driver_id: str):
    key = f"fleet:driver:active:{driver_id}"
    data = await redis_client.hgetall(key)

    if not data:
        raise HTTPException(
            status_code=404,
            detail=f"Driver '{driver_id}' not found in live state",
        )

    return {
        "driver_id": driver_id,
        **data,
    }
