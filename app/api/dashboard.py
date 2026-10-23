
import json

from fastapi import APIRouter
from app.redis_client import redis_client

router = APIRouter()


@router.get("/dashboard/data")
async def get_dashboard_data():
    driver_ids = await redis_client.smembers("fleet:drivers")
    route_ids = await redis_client.smembers("fleet:routes:active")

    drivers = []

    for driver_id in sorted(driver_ids):
        data = await redis_client.hgetall(
            f"fleet:driver:active:{driver_id}"
        )
        drivers.append({
            "driver_id": driver_id,
            **data,
        })

    routes = []

    for route_id in sorted(route_ids):
        data = await redis_client.hgetall(
            f"fleet:route:{route_id}"
        )

        if not data:
            continue

        stops = data.get("stops", "[]")
        try:
            stops = json.loads(stops)
        except (TypeError, json.JSONDecodeError):
            stops = []

        routes.append({
            "route_id": route_id,
            **data,
            "stops": stops,
        })

    return {
        "drivers": drivers,
        "routes": routes,
    }
