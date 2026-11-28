
import asyncio
import logging

from redis.exceptions import ResponseError

from app.redis_client import redis_client
from app.services.fleet_state_manager import FleetStateManager

logger = logging.getLogger(__name__)

STREAM_NAME = "routes_stream"
CONSUMER_GROUP = "control-tower-routes"
CONSUMER_NAME = "control-tower-routes-1"

state_manager = FleetStateManager(redis_client)


async def ensure_consumer_group() -> None:
    try:
        await redis_client.xgroup_create(
            STREAM_NAME,
            CONSUMER_GROUP,
            id="$",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def process_route_event(event: dict) -> None:
    event_type = event.get("event_type") or event.get("type")

    if event_type != "route.published":
        logger.warning("Ignoring unsupported route event: %s", event_type)
        return

    route_id = event.get("route_id")
    if not route_id:
        logger.warning("Ignoring route event without route_id")
        return

    route_data = {
        key: value
        for key, value in event.items()
        if key in (
            "version",
            "driver_id",
            "vehicle_id",
            "status",
            "stops",
            "warehouse_id",
        )
    }

    if "stops" in route_data and isinstance(route_data["stops"], str):
        import json
        route_data["stops"] = json.loads(route_data["stops"])

    await state_manager.update_route(route_id, route_data)


async def consume_routes() -> None:
    await ensure_consumer_group()
    logger.info("Listening to Redis stream: %s", STREAM_NAME)

    while True:
        messages = await redis_client.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            streams={STREAM_NAME: ">"},
            count=10,
            block=5000,
        )

        for stream, entries in messages:
            for message_id, fields in entries:
                try:
                    await process_route_event(fields)
                    await redis_client.xack(
                        stream,
                        CONSUMER_GROUP,
                        message_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to process route event %s",
                        message_id,
                    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    try:
        asyncio.run(consume_routes())
    except KeyboardInterrupt:
        logger.info("Route consumer stopped")
    finally:
        asyncio.run(redis_client.aclose())
