from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.redis_client import redis_client
from app.database import get_database_engine

router = APIRouter(tags=["Driver State"])


class DriverLocation(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


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


@router.post("/drivers/{driver_id}/location")
async def update_driver_location(
    driver_id: UUID,
    location: DriverLocation
):
    engine = get_database_engine()
    recorded_at = datetime.now(timezone.utc)

    try:
        async with engine.begin() as connection:

            result = await connection.execute(
                text("""
                    SELECT user_id
                    FROM public.drivers
                    WHERE user_id = :driver_id
                """),
                {"driver_id": driver_id}
            )

            if result.first() is None:
                raise HTTPException(
                    status_code=404,
                    detail="Driver not found"
                )

            await connection.execute(
                text("""
                    INSERT INTO public.driver_locations
                    (
                        id,
                        driver_id,
                        latitude,
                        longitude,
                        source,
                        recorded_at
                    )
                    VALUES
                    (
                        :id,
                        :driver_id,
                        :latitude,
                        :longitude,
                        :source,
                        :recorded_at
                    )
                """),
                {
                    "id": uuid4(),
                    "driver_id": driver_id,
                    "latitude": location.latitude,
                    "longitude": location.longitude,
                    "source": "simulator",
                    "recorded_at": recorded_at
                }
            )

        key = f"fleet:driver:active:{driver_id}"

        await redis_client.hset(
            key,
            mapping={
                "latitude": str(location.latitude),
                "longitude": str(location.longitude),
                "lat": str(location.latitude),
                "lng": str(location.longitude),
                "last_ping": recorded_at.isoformat(),
                "last_updated": recorded_at.isoformat()
            }
        )

        await redis_client.expire(key, 43200)
        await redis_client.sadd("fleet:drivers", str(driver_id))

        return {
            "message": "Driver location updated successfully",
            "driver_id": str(driver_id),
            "latitude": location.latitude,
            "longitude": location.longitude,
            "recorded_at": recorded_at.isoformat()
        }

    except HTTPException:
        raise

    except Exception as exc:
        print("Driver location error:", repr(exc))
        raise HTTPException(
            status_code=500,
            detail="Could not fully update driver location"
        ) from exc

    finally:
        await engine.dispose()