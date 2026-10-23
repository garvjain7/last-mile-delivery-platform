
import asyncio
import json
import logging

from redis.exceptions import ResponseError

from app.redis_client import redis_client
from app.services.fleet_state_manager import FleetStateManager

logger = logging.getLogger(__name__)

STREAM_NAME = "driver_events_stream"
CONSUMER_GROUP = "control-tower"
CONSUMER_NAME = "control-tower-1"

state_manager = FleetStateManager(redis_client)


async def ensure_consumer_group() -> None:
    try:
        await redis_client.xgroup_create(
            STREAM_NAME,
            CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def process_event(event: dict) -> None:
    event_type = event.get("event_type")

    if isinstance(event_type, bytes):
        event_type = event_type.decode()

    if event_type == "driver.location.updated":
        driver_id = event.get("driver_id")
        if not driver_id:
            logger.warning("Ignoring location event without driver_id")
            return

        driver_data = {
            key: event.get(key)
            for key in (
                "latitude",
                "longitude",
                "speed",
                "status",
                "timestamp",
            )
            if event.get(key) is not None
        }

        await state_manager.update_driver(driver_id, driver_data)

    elif event_type in (
        "stop.arrived",
        "delivery.completed",
        "delivery.failed",
    ):
        logger.info("Received event type: %s", event_type)

    else:
        logger.warning("Ignoring unsupported event type: %s", event_type)


async def consume_driver_events() -> None:
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
                    await process_event(fields)
                    await redis_client.xack(
                        stream,
                        CONSUMER_GROUP,
                        message_id,
                    )
                except Exception:
                    logger.exception(
                        "Failed to process event %s; leaving it unacknowledged",
                        message_id,
                    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    try:
        asyncio.run(consume_driver_events())
    except KeyboardInterrupt:
        logger.info("Consumer stopped")
    finally:
        asyncio.run(redis_client.aclose())
