from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import asyncio

import pytest

from db_models.models import (
    AttemptOutcome,
    DeliveryAttempt,
    DeliveryException,
    DeliveryProof,
    DriverStatus,
    OrderStatus,
    OrderEvent,
    PackageScan,
    RouteStatus,
    StopStatus,
)
from services.routing_worker.app.consumers import terminal_events_consumer as consumer
from services.routing_worker.app.consumers.terminal_events_consumer import (
    apply_terminal_event,
    validate_nonterminal_event,
)
from streaming.schemas.events import DriverTelemetryEvent


class FakeResult:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row

    def all(self):
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

    async def commit(self):
        pass


class FakeClaimResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class ReceiptSession:
    def __init__(self, claim):
        self.claim = claim
        self.statements = []
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return FakeClaimResult(self.claim)
        return FakeResult(None)

    async def commit(self):
        self.committed = True


class FakeRedis:
    def __init__(self, session):
        self.session = session
        self.acknowledged = []

    async def xack(self, *args):
        assert self.session.committed or not self.session.claim
        self.acknowledged.append(args)


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


def test_delivery_completion_updates_ledger_and_finishes_route(monkeypatch):
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
        planned_distance_m=4200,
    )
    order = SimpleNamespace(
        id=uuid4(),
        status=OrderStatus.out_for_delivery,
        updated_at=None,
        weight_kg=Decimal("2.50"),
    )
    driver = SimpleNamespace(status=DriverStatus.on_route, updated_at=None)
    session = FakeSession((stop, route, order), [0, driver])
    earnings_calls = []

    async def record_earnings(*args, **kwargs):
        earnings_calls.append((args, kwargs))

    monkeypatch.setattr(
        "services.routing_worker.app.consumers.terminal_events_consumer.post_delivery_earnings",
        record_earnings,
    )
    event = terminal_event(driver_id=driver_id, order_id=order.id, route_id=route_id)

    asyncio.run(
        apply_terminal_event(session, event)
    )

    assert stop.status == StopStatus.delivered
    assert stop.completed_at.tzinfo == timezone.utc
    assert order.status == OrderStatus.delivered
    order_event = next(row for row in session.added if isinstance(row, OrderEvent))
    attempt = next(row for row in session.added if isinstance(row, DeliveryAttempt))
    assert order_event.to_status == OrderStatus.delivered
    assert attempt.outcome == AttemptOutcome.delivered
    assert attempt.client_event_id == event.event_id
    assert attempt.failure_reason is None
    assert route.status == RouteStatus.completed
    assert driver.status == DriverStatus.available
    assert earnings_calls == [
        (
            (session,),
            {
                "driver_id": driver_id,
                "route_id": route_id,
                "route_stop_id": stop.id,
                "order_id": order.id,
                "source_event_id": event.event_id,
                "weight_kg": Decimal("2.50"),
                "planned_distance_m": 4200,
                "actor_user_id": driver_id,
            },
        )
    ]


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
    assert stop.failure_notes == "No one answered."
    order_event = next(row for row in session.added if isinstance(row, OrderEvent))
    attempt = next(row for row in session.added if isinstance(row, DeliveryAttempt))
    exception = next(row for row in session.added if isinstance(row, DeliveryException))
    assert order_event.to_status == OrderStatus.returned
    assert attempt.outcome == AttemptOutcome.failed
    assert attempt.failure_reason.value == "recipient_unavailable"
    assert exception.notes == "No one answered."
    assert exception.return_to_hub is True


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
    route = SimpleNamespace(
        id=uuid4(),
        status=RouteStatus.in_progress,
        completed_at=None,
        updated_at=None,
    )
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


def test_package_scan_is_persisted_with_its_stage():
    route_stop_id = uuid4()
    order_id = uuid4()
    driver_id = uuid4()
    route_id = uuid4()
    stop = SimpleNamespace(id=route_stop_id, order_id=order_id)
    session = FakeSession(None, [stop])
    fields = {
        "event_id": str(uuid4()),
        "driver_id": str(driver_id),
        "event_type": "package.scanned",
        "route_id": str(route_id),
        "order_id": str(order_id),
        "tracking_token": "TRACK001",
        "scan_stage": "stop",
        "timestamp": "2026-10-22T05:00:00Z",
    }

    route_context = asyncio.run(validate_nonterminal_event(session, fields))

    assert route_context == (route_id, route_stop_id)
    assert len(session.added) == 1
    scan = session.added[0]
    assert isinstance(scan, PackageScan)
    assert session.added[0].event_type == "package.scanned"
    assert session.added[0].stage == "stop"
    assert session.added[0].tracking_token == "TRACK001"
    assert session.added[0].is_valid is True
    assert session.added[0].route_stop_id == route_stop_id


def test_pickup_confirmation_persists_one_row_per_assigned_stop():
    first_stop_id, second_stop_id = uuid4(), uuid4()
    first_order_id, second_order_id = uuid4(), uuid4()
    driver_id, route_id = uuid4(), uuid4()
    session = FakeSession(
        [
            (first_stop_id, first_order_id, "TRACK001"),
            (second_stop_id, second_order_id, "TRACK002"),
        ],
        [],
    )
    fields = {
        "event_id": str(uuid4()),
        "driver_id": str(driver_id),
        "event_type": "pickup.confirmed",
        "route_id": str(route_id),
        "scanned_order_ids": f'["{first_order_id}","{second_order_id}"]',
        "timestamp": "2026-10-22T05:00:00Z",
    }

    route_context = asyncio.run(validate_nonterminal_event(session, fields))

    assert route_context == (route_id, None)
    assert len(session.added) == 2
    assert all(isinstance(row, PackageScan) for row in session.added)
    assert {row.order_id for row in session.added} == {first_order_id, second_order_id}
    assert all(row.event_type == "pickup.confirmed" for row in session.added)
    assert all(row.stage == "pickup" for row in session.added)
    assert {row.tracking_token for row in session.added} == {"TRACK001", "TRACK002"}


def test_pod_photo_is_linked_to_the_open_route_stop():
    route_stop_id, order_id, driver_id, route_id = uuid4(), uuid4(), uuid4(), uuid4()
    stop = SimpleNamespace(id=route_stop_id, order_id=order_id)
    session = FakeSession(None, [stop])
    fields = {
        "event_id": str(uuid4()),
        "driver_id": str(driver_id),
        "event_type": "pod.captured",
        "route_id": str(route_id),
        "order_id": str(order_id),
        "object_key": f"drivers/{driver_id}/routes/{route_id}/orders/{order_id}/proof.jpg",
        "evidence_type": "photo",
        "timestamp": "2026-10-22T05:00:00Z",
    }

    route_context = asyncio.run(consumer._persist_pod_evidence(session, fields))

    assert route_context == (route_id, route_stop_id)
    assert len(session.added) == 1
    proof = session.added[0]
    assert isinstance(proof, DeliveryProof)
    assert proof.route_id == route_id
    assert session.added[0].object_key == fields["object_key"]
    assert session.added[0].proof_type == "photo"
    assert session.added[0].route_stop_id == route_stop_id


def test_unsupported_exception_evidence_is_not_reported_as_committed():
    fields = {
        "event_id": str(uuid4()),
        "driver_id": str(uuid4()),
        "event_type": "delivery.exception.evidence",
        "route_id": str(uuid4()),
        "order_id": str(uuid4()),
        "object_key": "drivers/proof.jpg",
        "evidence_type": "photo",
        "timestamp": "2026-10-22T05:00:00Z",
    }

    with pytest.raises(consumer.InvalidDriverEvent, match="Exception evidence"):
        asyncio.run(consumer._persist_pod_evidence(FakeSession(None, []), fields))


def test_event_receipt_is_committed_before_redis_ack(monkeypatch):
    event_id = uuid4()
    driver_id = uuid4()
    session = ReceiptSession(event_id)
    redis_client = FakeRedis(session)
    monkeypatch.setattr(consumer, "async_session_factory", lambda: session)
    fields = {
        "event_id": str(event_id),
        "driver_id": str(driver_id),
        "event_type": "driver.location.updated",
        "latitude": "12.9",
        "longitude": "77.5",
        "timestamp": "2026-10-22T05:00:00Z",
    }

    asyncio.run(consumer._process_message(redis_client, "1-0", fields))

    assert session.committed
    assert len(redis_client.acknowledged) == 1
    update_statement = session.statements[1]
    assert update_statement.compile().params["status"] == "committed"


def test_duplicate_event_receipt_skips_processing_and_is_acked(monkeypatch):
    session = ReceiptSession(None)
    redis_client = FakeRedis(session)
    monkeypatch.setattr(consumer, "async_session_factory", lambda: session)
    monkeypatch.setattr(
        consumer,
        "_apply_driver_event",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Duplicate event was processed.")),
    )
    fields = {
        "event_id": str(uuid4()),
        "driver_id": str(uuid4()),
        "event_type": "driver.location.updated",
        "latitude": "12.9",
        "longitude": "77.5",
        "timestamp": "2026-10-22T05:00:00Z",
    }

    asyncio.run(consumer._process_message(redis_client, "1-0", fields))

    assert not session.committed
    assert len(redis_client.acknowledged) == 1


def test_invalid_event_receipt_is_rejected_before_ack(monkeypatch):
    event_id = uuid4()
    session = ReceiptSession(event_id)
    redis_client = FakeRedis(session)
    monkeypatch.setattr(consumer, "async_session_factory", lambda: session)
    fields = {
        "event_id": str(event_id),
        "driver_id": str(uuid4()),
        "event_type": "delivery.failed",
        "timestamp": "2026-10-22T05:00:00Z",
    }

    asyncio.run(consumer._process_message(redis_client, "1-0", fields))

    assert session.committed
    update_params = session.statements[1].compile().params
    assert update_params["status"] == "rejected"
    assert update_params["reject_reason"]
    assert len(redis_client.acknowledged) == 1


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
