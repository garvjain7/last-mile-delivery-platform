"""Persist supported driver stop events from Redis Streams."""

import asyncio
import logging
import socket
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError
from redis.exceptions import ResponseError
from sqlalchemy import func, select

from db_models.models import (
    Driver,
    DriverStatus,
    FailureReason,
    Order,
    OrderEvent,
    OrderStatus,
    Route,
    RouteStatus,
    RouteStop,
    StopStatus,
)
from services.routing_worker.app.database.connection import async_session_factory, engine
from streaming.client import close_redis_client, get_redis_client
from streaming.schemas.events import (
    DriverPackageScannedEvent,
    DriverPickupConfirmedEvent,
    DriverTelemetryEvent,
)

logger = logging.getLogger(__name__)

STREAM_NAME = "driver_events_stream"
GROUP_NAME = "routing-terminal-events"
CONSUMER_NAME = f"{socket.gethostname()}-{uuid4().hex[:8]}"
BATCH_SIZE = 50
CLAIM_IDLE_MS = 60_000


class InvalidDriverEvent(Exception):
    """A permanently invalid or unauthorized event that should not be retried."""


async def apply_terminal_event(session, event: DriverTelemetryEvent) -> None:
    """Apply a stop arrival or terminal outcome using only schema-backed fields."""
    result = await session.execute(
        select(RouteStop, Route, Order)
        .join(Route, RouteStop.route_id == Route.id)
        .join(Order, RouteStop.order_id == Order.id)
        .where(
            Route.id == event.current_route_id,
            Route.driver_id == event.driver_id,
            Route.status == RouteStatus.in_progress,
            RouteStop.order_id == event.order_id,
        )
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise InvalidDriverEvent(
            "Driver event does not identify an open stop on the driver's active route."
        )
    stop, route, order = row
    if event.event_type == "stop.arrived":
        if stop.status == StopStatus.pending and stop.arrived_at is None:
            now = datetime.now(timezone.utc)
            stop.arrived_at = now
            stop.updated_at = now
        return

    desired_stop_status = (
        StopStatus.delivered
        if event.event_type == "delivery.completed"
        else StopStatus.failed
    )
    desired_order_status = (
        OrderStatus.delivered
        if event.event_type == "delivery.completed"
        else OrderStatus.returned
        if event.return_to_hub
        else OrderStatus.attempt_failed
    )
    if stop.status in {StopStatus.delivered, StopStatus.failed}:
        if stop.status == desired_stop_status and order.status == desired_order_status:
            return
        raise InvalidDriverEvent("Stop already has a different terminal outcome.")
    if stop.status != StopStatus.pending:
        raise InvalidDriverEvent("Only pending stops can receive a terminal outcome.")

    now = datetime.now(timezone.utc)
    stop.status = desired_stop_status
    stop.failure_reason = (
        FailureReason(event.failure_reason)
        if event.event_type == "delivery.failed"
        else None
    )
    stop.completed_at = now
    stop.updated_at = now
    if order.status != desired_order_status:
        session.add(
            OrderEvent(
                order_id=order.id,
                from_status=order.status,
                to_status=desired_order_status,
                route_stop_id=stop.id,
                actor_user_id=event.driver_id,
                occurred_at=now,
            )
        )
        order.status = desired_order_status
        order.updated_at = now

    pending_stops = await session.scalar(
        select(func.count())
        .select_from(RouteStop)
        .where(
            RouteStop.route_id == route.id,
            RouteStop.status == StopStatus.pending,
        )
    )
    if pending_stops == 0:
        route.status = RouteStatus.completed
        route.completed_at = now
        route.updated_at = now
        driver = await session.scalar(
            select(Driver).where(Driver.user_id == event.driver_id).with_for_update()
        )
        if driver is not None and driver.status == DriverStatus.on_route:
            driver.status = DriverStatus.available
            driver.updated_at = now


async def validate_nonterminal_event(session, fields: dict[str, str]) -> None:
    """Validate stream-only scan and pickup events against the assigned route."""
    event_type = fields.get("event_type")
    if event_type == "package.scanned":
        event = DriverPackageScannedEvent.model_validate(fields)
        matching_stops = await session.scalar(
            select(func.count())
            .select_from(RouteStop)
            .join(Route, RouteStop.route_id == Route.id)
            .join(Order, RouteStop.order_id == Order.id)
            .where(
                Route.id == event.route_id,
                Route.driver_id == event.driver_id,
                Route.status == RouteStatus.in_progress,
                RouteStop.order_id == event.order_id,
                RouteStop.status == StopStatus.pending,
                Order.tracking_token == event.tracking_token,
            )
        )
        if matching_stops != 1:
            raise InvalidDriverEvent("Scanned parcel is not an open stop on the assigned route.")
    elif event_type == "pickup.confirmed":
        event = DriverPickupConfirmedEvent.model_validate(fields)
        assigned_orders = await session.scalars(
            select(RouteStop.order_id)
            .join(Route, RouteStop.route_id == Route.id)
            .where(
                Route.id == event.route_id,
                Route.driver_id == event.driver_id,
                Route.status == RouteStatus.in_progress,
                RouteStop.status == StopStatus.pending,
            )
        )
        if set(assigned_orders.all()) != set(event.scanned_order_ids):
            raise InvalidDriverEvent("Pickup confirmation does not cover the route manifest.")


def _decode_fields(fields: dict[str, str]) -> dict[str, str]:
    return {
        key.decode() if isinstance(key, bytes) else key:
        value.decode() if isinstance(value, bytes) else value
        for key, value in fields.items()
    }


async def _acknowledge(redis_client, message_id: str) -> None:
    await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)


async def _process_message(redis_client, message_id: str, raw_fields: dict[str, str]) -> None:
    fields = _decode_fields(raw_fields)
    event_type = fields.get("event_type")
    if event_type in {"package.scanned", "pickup.confirmed"}:
        try:
            async with async_session_factory() as session:
                await validate_nonterminal_event(session, fields)
            await _acknowledge(redis_client, message_id)
        except (ValidationError, InvalidDriverEvent):
            logger.exception("Acknowledging invalid scan or pickup event %s", message_id)
            await _acknowledge(redis_client, message_id)
        return
    if event_type not in {"delivery.completed", "delivery.failed", "stop.arrived"}:
        logger.debug("Acknowledging non-persistence driver event %s (%s)", message_id, event_type)
        await _acknowledge(redis_client, message_id)
        return

    try:
        event = DriverTelemetryEvent.model_validate(fields)
    except ValidationError:
        logger.exception("Acknowledging invalid driver event %s", message_id)
        await _acknowledge(redis_client, message_id)
        return

    try:
        async with async_session_factory() as session:
            await apply_terminal_event(session, event)
            await session.commit()
    except InvalidDriverEvent:
        logger.exception(
            "Acknowledging unauthorized or stale driver event %s for route %s order %s",
            message_id,
            event.current_route_id,
            event.order_id,
        )
        await _acknowledge(redis_client, message_id)
        return

    await _acknowledge(redis_client, message_id)


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


async def run_terminal_events_consumer() -> None:
    """Read, persist, then acknowledge driver stop events with at-least-once delivery."""
    redis_client = await get_redis_client()
    await _ensure_consumer_group(redis_client)
    logger.info(
        "Driver event consumer started (group=%s, consumer=%s)",
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
                messages = claimed[1]
                for message_id, fields in messages:
                    await _process_message(redis_client, message_id, fields)

                batches = await redis_client.xreadgroup(
                    GROUP_NAME,
                    CONSUMER_NAME,
                    {STREAM_NAME: ">"},
                    count=BATCH_SIZE,
                    block=5_000,
                )
                for _stream, entries in batches:
                    for message_id, fields in entries:
                        await _process_message(redis_client, message_id, fields)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Driver event batch failed; unacknowledged events will be retried.")
                await asyncio.sleep(1)
    finally:
        await close_redis_client()
        await engine.dispose()
