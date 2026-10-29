from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from redis.exceptions import RedisError
from sqlalchemy.dialects import postgresql

from db_models.models import OrderStatus
from services.core_api.app.staff import service


class QueryResult:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def one_or_none(self):
        return self.row

    def all(self):
        return self.rows


@pytest.mark.asyncio
async def test_list_staff_orders_applies_filters_and_bounds():
    db = SimpleNamespace(execute=AsyncMock(return_value=QueryResult(rows=[])))
    merchant_id = uuid4()
    warehouse_id = uuid4()
    created_from = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created_to = datetime(2026, 2, 1, tzinfo=timezone.utc)

    await service.list_staff_orders(
        db,
        q="parcel",
        statuses=[OrderStatus.placed, OrderStatus.sent],
        merchant_id=merchant_id,
        warehouse_id=warehouse_id,
        created_from=created_from,
        created_to=created_to,
        limit=25,
        offset=50,
    )

    statement = db.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert compiled.params["status_1"] == [OrderStatus.placed, OrderStatus.sent]
    assert compiled.params["merchant_id_1"] == merchant_id
    assert compiled.params["warehouse_id_1"] == warehouse_id
    assert created_from in compiled.params.values()
    assert created_to in compiled.params.values()
    assert 25 in compiled.params.values()
    assert 50 in compiled.params.values()


@pytest.mark.asyncio
async def test_republish_stale_placed_order_preserves_status_and_marks_retry(monkeypatch):
    now = datetime.now(timezone.utc)
    order = SimpleNamespace(
        id=uuid4(),
        merchant_id=uuid4(),
        warehouse_id=None,
        status=OrderStatus.placed,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        delivery_address="10 Main Street",
        window_earliest=None,
        window_latest=None,
        weight_kg=1.25,
        volume_m3=0.5,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=QueryResult((order, "POINT(77.5 12.9)"))
        ),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    publish = AsyncMock(return_value="stream-id")
    monkeypatch.setattr(service, "add_to_stream", publish)

    await service.republish_stale_placed_order(db, order.id)

    stream_name, payload = publish.await_args.args
    assert stream_name == "orders_stream"
    assert payload["order_id"] == str(order.id)
    assert payload["dropoff_location"] == "POINT(77.5 12.9)"
    assert payload["warehouse_id"] is None
    assert payload["time_window"] == ""
    assert order.status is OrderStatus.placed
    assert order.updated_at > now - timedelta(minutes=1)
    db.commit.assert_awaited_once()
    db.rollback.assert_not_awaited()


@pytest.mark.asyncio
async def test_republish_rejects_recently_updated_order(monkeypatch):
    now = datetime.now(timezone.utc)
    order = SimpleNamespace(
        id=uuid4(),
        status=OrderStatus.placed,
        created_at=now - timedelta(days=2),
        updated_at=now,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=QueryResult((order, "POINT(77.5 12.9)"))
        ),
        commit=AsyncMock(),
    )
    publish = AsyncMock()
    monkeypatch.setattr(service, "add_to_stream", publish)

    with pytest.raises(service.OrderNotEligibleError):
        await service.republish_stale_placed_order(db, order.id)

    publish.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_republish_rolls_back_when_redis_publish_fails(monkeypatch):
    now = datetime.now(timezone.utc)
    order = SimpleNamespace(
        id=uuid4(),
        merchant_id=uuid4(),
        warehouse_id=None,
        status=OrderStatus.placed,
        created_at=now - timedelta(days=2),
        updated_at=now - timedelta(days=2),
        delivery_address="10 Main Street",
        window_earliest=None,
        window_latest=None,
        weight_kg=1.25,
        volume_m3=0.5,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=QueryResult((order, "POINT(77.5 12.9)"))
        ),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )
    publish = AsyncMock(side_effect=RedisError("unavailable"))
    monkeypatch.setattr(service, "add_to_stream", publish)

    with pytest.raises(service.OrderStreamPublishError):
        await service.republish_stale_placed_order(db, order.id)

    db.rollback.assert_awaited_once()
    db.commit.assert_not_awaited()
    assert order.updated_at == now - timedelta(days=2)
