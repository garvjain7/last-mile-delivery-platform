from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import asyncio

from db_models.models import (
    DriverStatus,
    OrderStatus,
    RouteStatus,
    StopStatus,
)
from services.routing_worker.app.consumers.terminal_events_consumer import apply_terminal_event
from streaming.schemas.events import DriverTelemetryEvent


class FakeResult:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class FakeSession:
    def __init__(self, row, scalar_values):
        self.row = row
        self.scalar_values = iter(scalar_values)
        self.added = []

    async def execute(self, _statement):
        return FakeResult(self.row)

    async def scalar(self, _statement):
        return next(self.scalar_values)

    def add(self, instance):
        self.added.append(instance)


def terminal_event(event_type="delivery.completed", **fields):
    return DriverTelemetryEvent(
        event_id=uuid4(),
        driver_id=fields.get("driver_id", uuid4()),
        event_type=event_type,
        latitude=12.9,
        longitude=77.5,
        current_route_id=fields.get("route_id", uuid4()),
        order_id=fields.get("order_id", uuid4()),
        timestamp=datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc),
        **{
            key: value
            for key, value in fields.items()
            if key not in {"driver_id", "route_id", "order_id"}
        },
    )


def test_delivery_completion_updates_stop_order_history_and_finishes_route():
    driver_id = uuid4()
    route_id = uuid4()
    route = SimpleNamespace(id=route_id, status=RouteStatus.in_progress, completed_at=None, updated_at=None)
    stop = SimpleNamespace(
        id=uuid4(),
        status=StopStatus.pending,
        failure_reason=None,
        completed_at=None,
        updated_at=None,
        arrived_at=None,
    )
    order = SimpleNamespace(
        id=uuid4(),
        status=OrderStatus.out_for_delivery,
        updated_at=None,
    )
    driver = SimpleNamespace(status=DriverStatus.on_route, updated_at=None)
    session = FakeSession((stop, route, order), [0, driver])

    asyncio.run(
        apply_terminal_event(
            session,
            terminal_event(driver_id=driver_id, order_id=order.id, route_id=route_id),
        )
    )

    assert stop.status == StopStatus.delivered
    assert stop.completed_at.tzinfo == timezone.utc
    assert order.status == OrderStatus.delivered
    assert len(session.added) == 1
    assert session.added[0].to_status == OrderStatus.delivered
    assert route.status == RouteStatus.completed
    assert driver.status == DriverStatus.available


def test_failed_delivery_can_mark_existing_order_status_returned():
    order = SimpleNamespace(id=uuid4(), status=OrderStatus.out_for_delivery, updated_at=None)
    stop = SimpleNamespace(
        id=uuid4(),
        status=StopStatus.pending,
        failure_reason=None,
        completed_at=None,
        updated_at=None,
        arrived_at=None,
    )
    route_id = uuid4()
    route = SimpleNamespace(id=route_id, status=RouteStatus.in_progress, completed_at=None, updated_at=None)
    session = FakeSession((stop, route, order), [1])

    asyncio.run(
        apply_terminal_event(
            session,
            terminal_event(
                event_type="delivery.failed",
                driver_id=uuid4(),
                order_id=order.id,
                route_id=route_id,
                failure_reason="recipient_unavailable",
                failure_notes="No one answered.",
                return_to_hub=True,
            ),
        )
    )

    assert stop.status == StopStatus.failed
    assert stop.failure_reason.value == "recipient_unavailable"
    assert order.status == OrderStatus.returned
    assert session.added[0].to_status == OrderStatus.returned


def test_replayed_terminal_outcome_does_not_add_duplicate_order_history():
    order = SimpleNamespace(id=uuid4(), status=OrderStatus.delivered, updated_at=None)
    stop = SimpleNamespace(
        id=uuid4(),
        status=StopStatus.delivered,
        failure_reason=None,
        completed_at=datetime(2026, 10, 22, 5, 0, tzinfo=timezone.utc),
        updated_at=None,
        arrived_at=None,
    )
    route = SimpleNamespace(status=RouteStatus.in_progress, completed_at=None, updated_at=None)
    session = FakeSession((stop, route, order), [])

    asyncio.run(
        apply_terminal_event(
            session,
            terminal_event(
                driver_id=uuid4(),
                order_id=order.id,
                route_id=uuid4(),
            ),
        )
    )

    assert session.added == []


def test_stop_arrival_persists_gps_timestamp_without_terminal_transition():
    stop = SimpleNamespace(
        id=uuid4(),
        status=StopStatus.pending,
        failure_reason=None,
        completed_at=None,
        updated_at=None,
        arrived_at=None,
    )
    route = SimpleNamespace(id=uuid4(), status=RouteStatus.in_progress)
    order = SimpleNamespace(id=uuid4(), status=OrderStatus.out_for_delivery)
    session = FakeSession((stop, route, order), [])
    asyncio.run(
        apply_terminal_event(
            session,
            terminal_event(
                event_type="stop.arrived",
                driver_id=uuid4(),
                order_id=order.id,
                route_id=route.id,
            ),
        )
    )

    assert stop.arrived_at.tzinfo == timezone.utc
    assert stop.status == StopStatus.pending
    assert session.added == []
