"""Plan warehouse delivery routes from the orders Redis Stream."""

import asyncio
import logging
import socket
from uuid import UUID, uuid4

from pydantic import ValidationError
from redis.exceptions import ResponseError

from services.routing_worker.app.database.connection import engine
from services.routing_worker.app.engines.route_planner import (
    InvalidOrderEvent,
    plan_warehouse_routes,
)
from streaming.client import (
    add_to_stream,
    close_redis_client,
    decode_stream_fields,
    get_redis_client,
)
from streaming.schemas.events import OrderCreatedEvent

logger = logging.getLogger(__name__)

STREAM_NAME = "orders_stream"
GROUP_NAME = "routing-workers"
CONSUMER_NAME = f"{socket.gethostname()}-{uuid4().hex[:8]}"
BATCH_SIZE = 50
CLAIM_IDLE_MS = 60_000


async def _acknowledge(redis_client, message_id: str) -> None:
    await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)


async def _process_message(redis_client, message_id: str, raw_fields: dict[str, str]) -> None:
    fields = decode_stream_fields(raw_fields)
    try:
        event = OrderCreatedEvent.model_validate(fields)
        order_id = UUID(event.order_id)
        warehouse_id = UUID(event.warehouse_id)
    except (ValidationError, ValueError):
        logger.exception("Acknowledging invalid order stream event %s", message_id)
        await _acknowledge(redis_client, message_id)
        return

    try:
        trigger_assigned, route_events = await plan_warehouse_routes(
            warehouse_id,
            order_id,
        )
    except InvalidOrderEvent:
        logger.exception("Acknowledging inconsistent order event %s", message_id)
        await _acknowledge(redis_client, message_id)
        return

    for route_event in route_events:
        await add_to_stream("route_stream", route_event)
    if trigger_assigned:
        await _acknowledge(redis_client, message_id)
    else:
        logger.info(
            "Order %s remains pending; no eligible VROOM assignment is available yet.",
            order_id,
        )


async def _ensure_consumer_group(redis_client) -> None:
    try:
        await redis_client.xgroup_create(
            STREAM_NAME,
            GROUP_NAME,
            id="0-0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def run_orders_consumer() -> None:
    """Read, plan, commit, publish, and acknowledge order events."""
    redis_client = await get_redis_client()
    await _ensure_consumer_group(redis_client)
    logger.info(
        "Orders consumer started (group=%s, consumer=%s)",
        GROUP_NAME,
        CONSUMER_NAME,
    )
    try:
        while True:
            try:
                claimed = await redis_client.xautoclaim(
                    STREAM_NAME,
                    GROUP_NAME,
                    CONSUMER_NAME,
                    min_idle_time=CLAIM_IDLE_MS,
                    start_id="0-0",
                    count=BATCH_SIZE,
                )
                for message_id, fields in claimed[1]:
                    await _process_message(redis_client, message_id, fields)

                batches = await redis_client.xreadgroup(
                    GROUP_NAME,
                    CONSUMER_NAME,
                    {STREAM_NAME: ">"},
                    count=BATCH_SIZE,
                    block=5_000,
                )
                for _, entries in batches:
                    for message_id, fields in entries:
                        await _process_message(redis_client, message_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Order batch failed; unacknowledged orders will be retried.")
                await asyncio.sleep(1)
    finally:
        await close_redis_client()
        await engine.dispose()
