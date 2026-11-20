"""Persist supported driver events from Redis Streams."""

import asyncio
import logging
import socket
from datetime import datetime, timezone
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from pydantic import ValidationError
from redis.exceptions import ResponseError
from sqlalchemy import cast, func, select, update
from sqlalchemy.dialects.postgresql import insert

from db_models.models import (
    AttemptOutcome,
    DeliveryAttempt,
    DeliveryException,
    DeliveryProof,
    Driver,
    DriverStatus,
    FailureReason,
    Order,
    OrderEvent,
    OrderStatus,
    PackageScan,
    ProcessedEvent,
    Route,
    RouteStatus,
    RouteStop,
    StopStatus,
    Warehouse,
)
from services.routing_worker.app.database.connection import async_session_factory, engine
from services.routing_worker.app.earnings import post_delivery_earnings
from services.routing_worker.app.engines.osrm import OSRMClient
from streaming.client import close_redis_client, decode_stream_fields, get_redis_client
from streaming.schemas.events import (
    DriverEvidenceCapturedEvent,
    DriverPackageScannedEvent,
    DriverPickupConfirmedEvent,
    DriverRouteStartedEvent,
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


async def _ensure_planned_distance(session, stop: RouteStop, route: Route) -> int:
    if stop.planned_distance_m is not None:
        return stop.planned_distance_m
    point_type = Geometry(geometry_type="POINT", srid=4326)
    target = await session.execute(
        select(
            func.ST_X(cast(RouteStop.planned_location, point_type)),
            func.ST_Y(cast(RouteStop.planned_location, point_type)),
        ).where(RouteStop.id == stop.id)
    )
    target_row = target.one_or_none()
    if target_row is None:
        raise RuntimeError(f"Could not load planned destination for route stop {stop.id}.")
    previous = await session.execute(
        select(
            func.ST_X(cast(RouteStop.planned_location, point_type)),
            func.ST_Y(cast(RouteStop.planned_location, point_type)),
        )
        .where(
            RouteStop.route_id == route.id,
            RouteStop.sequence < stop.sequence,
        )
        .order_by(RouteStop.sequence.desc())
        .limit(1)
    )
    previous_row = previous.one_or_none()
    if previous_row is None:
        origin = await session.execute(
            select(
                func.ST_X(cast(Warehouse.location, point_type)),
                func.ST_Y(cast(Warehouse.location, point_type)),
            )
            .join(Route, Route.warehouse_id == Warehouse.id)
            .where(Route.id == route.id)
        )
        origin_row = origin.one_or_none()
    else:
        origin_row = previous_row
    if origin_row is None:
        raise RuntimeError(f"Could not load route origin for route {route.id}.")
    origin = (float(origin_row[0]), float(origin_row[1]))
    destination = (float(target_row[0]), float(target_row[1]))
    stop.planned_distance_m = await OSRMClient().get_route_distance(origin, destination)
    return stop.planned_distance_m


async def apply_terminal_event(session, event: DriverTelemetryEvent) -> tuple[UUID, UUID]:
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
        return route.id, stop.id

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
            return route.id, stop.id
        raise InvalidDriverEvent("Stop already has a different terminal outcome.")
    if stop.status != StopStatus.pending:
        raise InvalidDriverEvent("Only pending stops can receive a terminal outcome.")

    planned_distance_m = None
    if event.event_type == "delivery.completed":
        planned_distance_m = await _ensure_planned_distance(session, stop, route)

    now = datetime.now(timezone.utc)
    stop.status = desired_stop_status
    failure_reason = (
        FailureReason(event.failure_reason)
        if event.event_type == "delivery.failed"
        else None
    )
    stop.failure_reason = failure_reason
    stop.failure_notes = (
        event.failure_notes
        if event.event_type == "delivery.failed"
        else None
    )
    stop.completed_at = now
    stop.updated_at = now
    session.add(
        DeliveryAttempt(
            order_id=order.id,
            route_stop_id=stop.id,
            driver_id=event.driver_id,
            outcome=(
                AttemptOutcome.delivered
                if event.event_type == "delivery.completed"
                else AttemptOutcome.failed
            ),
            failure_reason=failure_reason,
            client_event_id=event.event_id,
            occurred_at=now,
        )
    )
    if event.event_type == "delivery.failed":
        session.add(
            DeliveryException(
                route_id=route.id,
                order_id=order.id,
                driver_id=event.driver_id,
                failure_reason=failure_reason,
                notes=event.failure_notes,
                return_to_hub=event.return_to_hub,
            )
        )
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
    if event.event_type == "delivery.completed":
        await post_delivery_earnings(
            session,
            driver_id=event.driver_id,
            route_id=route.id,
            route_stop_id=stop.id,
            order_id=order.id,
            source_event_id=event.event_id,
            weight_kg=order.weight_kg,
            planned_distance_m=planned_distance_m,
            actor_user_id=event.driver_id,
        )

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
    return route.id, stop.id


async def validate_nonterminal_event(session, fields: dict[str, str]) -> tuple[UUID, UUID | None]:
    """Validate and persist scan or pickup events against the assigned route."""
    event_type = fields.get("event_type")
    if event_type == "package.scanned":
        event = DriverPackageScannedEvent.model_validate(fields)
        stop = await session.scalar(
            select(RouteStop)
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
            .with_for_update()
        )
        if stop is None:
            raise InvalidDriverEvent("Scanned parcel is not an open stop on the assigned route.")
        session.add(
            PackageScan(
                route_id=event.route_id,
                route_stop_id=stop.id,
                order_id=stop.order_id,
                driver_id=event.driver_id,
                event_type=event.event_type,
                stage=event.scan_stage,
                tracking_token=event.tracking_token,
                is_valid=True,
                scanned_at=event.timestamp,
            )
        )
        return event.route_id, stop.id
    elif event_type == "pickup.confirmed":
        event = DriverPickupConfirmedEvent.model_validate(fields)
        result = await session.execute(
            select(RouteStop.id, RouteStop.order_id, Order.tracking_token)
            .join(Route, RouteStop.route_id == Route.id)
            .join(Order, RouteStop.order_id == Order.id)
            .where(
                Route.id == event.route_id,
                Route.driver_id == event.driver_id,
                Route.status == RouteStatus.in_progress,
                RouteStop.status == StopStatus.pending,
            )
            .with_for_update()
        )
        stops = result.all()
        if {order_id for _, order_id, _ in stops} != set(event.scanned_order_ids):
            raise InvalidDriverEvent("Pickup confirmation does not cover the route manifest.")
        for route_stop_id, order_id, tracking_token in stops:
            session.add(
                PackageScan(
                    route_id=event.route_id,
                    route_stop_id=route_stop_id,
                    order_id=order_id,
                    driver_id=event.driver_id,
                    event_type=event.event_type,
                    stage="pickup",
                    tracking_token=tracking_token,
                    is_valid=True,
                    scanned_at=event.timestamp,
                )
            )
        return event.route_id, None
    raise InvalidDriverEvent("Unsupported scan or pickup event type.")


async def _persist_pod_evidence(
    session,
    fields: dict[str, str],
) -> tuple[UUID, UUID]:
    event = DriverEvidenceCapturedEvent.model_validate(fields)
    if event.event_type != "pod.captured":
        raise InvalidDriverEvent("Exception evidence is not supported by the POD evidence record.")
    if event.evidence_type not in {"photo", "signature"}:
        raise InvalidDriverEvent("Recipient-name evidence cannot be stored as photo or signature evidence.")

    stop = await session.scalar(
        select(RouteStop)
        .join(Route, RouteStop.route_id == Route.id)
        .where(
            Route.id == event.route_id,
            Route.driver_id == event.driver_id,
            Route.status == RouteStatus.in_progress,
            RouteStop.order_id == event.order_id,
            RouteStop.status == StopStatus.pending,
        )
        .with_for_update()
    )
    if stop is None:
        raise InvalidDriverEvent("Evidence does not identify an open stop on the driver's active route.")
    session.add(
        DeliveryProof(
            route_id=event.route_id,
            route_stop_id=stop.id,
            order_id=event.order_id,
            driver_id=event.driver_id,
            proof_type=event.evidence_type,
            object_key=event.object_key,
            captured_at=event.timestamp,
        )
    )
    return event.route_id, stop.id


async def _persist_route_started(session, fields: dict[str, str]) -> tuple[UUID, None]:
    event = DriverRouteStartedEvent.model_validate(fields)
    route_id = await session.scalar(
        select(Route.id).where(
            Route.id == event.route_id,
            Route.driver_id == event.driver_id,
            Route.status == RouteStatus.in_progress,
        )
    )
    if route_id is None:
        raise InvalidDriverEvent("Route-start event does not match the driver's active route.")
    return event.route_id, None


async def _apply_driver_event(session, fields: dict[str, str]) -> tuple[UUID | None, UUID | None]:
    """Apply one supported event and return its verified route/stop context."""
    event_type = fields.get("event_type")
    if event_type in {"package.scanned", "pickup.confirmed"}:
        return await validate_nonterminal_event(session, fields)
    if event_type in {"pod.captured", "delivery.exception.evidence"}:
        return await _persist_pod_evidence(session, fields)
    if event_type == "route.started":
        return await _persist_route_started(session, fields)
    if event_type in {
        "driver.location.updated",
        "stop.arrived",
        "delivery.completed",
        "delivery.failed",
    }:
        event = DriverTelemetryEvent.model_validate(fields)
        if event.event_type == "driver.location.updated":
            return None, None
        return await apply_terminal_event(session, event)
    raise InvalidDriverEvent("Unsupported driver event type.")


async def _acknowledge(redis_client, message_id: str) -> None:
    await redis_client.xack(STREAM_NAME, GROUP_NAME, message_id)


async def _process_message(redis_client, message_id: str, raw_fields: dict[str, str]) -> None:
    fields = decode_stream_fields(raw_fields)
    try:
        event_id = UUID(fields["event_id"])
        driver_id = UUID(fields["driver_id"])
        event_type = fields["event_type"]
    except (KeyError, ValueError, TypeError):
        logger.warning("Acknowledging driver event %s without a valid receipt identity.", message_id)
        await _acknowledge(redis_client, message_id)
        return

    async with async_session_factory() as session:
        claim = await session.execute(
            insert(ProcessedEvent)
            .values(
                event_id=event_id,
                event_type=event_type,
                driver_id=driver_id,
                status="rejected",
                reject_reason="Event processing did not complete.",
            )
            .on_conflict_do_nothing(index_elements=[ProcessedEvent.event_id])
            .returning(ProcessedEvent.event_id)
        )
        claimed_event_id = claim.scalar_one_or_none()
        if claimed_event_id is None:
            logger.info("Skipping previously processed driver event %s", event_id)
        else:
            route_id = None
            route_stop_id = None
            try:
                route_id, route_stop_id = await _apply_driver_event(session, fields)
            except ValidationError as exc:
                reject_reason = "; ".join(
                    error["msg"]
                    for error in exc.errors(include_input=False, include_context=False)
                ) or "Invalid driver event."
                final_status = "rejected"
            except InvalidDriverEvent as exc:
                reject_reason = str(exc)
                final_status = "rejected"
            else:
                reject_reason = None
                final_status = "committed"

            await session.execute(
                update(ProcessedEvent)
                .where(ProcessedEvent.event_id == event_id)
                .values(
                    status=final_status,
                    reject_reason=reject_reason,
                    route_id=route_id,
                    route_stop_id=route_stop_id,
                )
            )
            await session.commit()

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
    """Read, persist, then acknowledge driver events with at-least-once delivery."""
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
                for _, entries in batches:
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
