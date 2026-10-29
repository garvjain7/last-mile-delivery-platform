"""Database queries and recovery operations for the minimal staff API."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from redis.exceptions import RedisError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from db_models.models import Merchant, Order, OrderStatus, Warehouse
from services.core_api.app.config import config
from streaming.client import add_to_stream
from streaming.schemas.events import OrderCreatedEvent

logger = logging.getLogger(__name__)


class OrderNotFoundError(LookupError):
    """Raised when a requested order does not exist."""


class OrderNotEligibleError(RuntimeError):
    """Raised when an order is not eligible for stale-order recovery."""


class OrderStreamPublishError(RuntimeError):
    """Raised when an order recovery event cannot be appended to Redis."""


async def list_staff_orders(
    db: AsyncSession,
    *,
    q: Optional[str],
    statuses: Optional[list[OrderStatus]],
    merchant_id: Optional[uuid.UUID],
    warehouse_id: Optional[uuid.UUID],
    created_from: Optional[datetime],
    created_to: Optional[datetime],
    limit: int,
    offset: int,
) -> list[tuple[Order, Merchant, Optional[Warehouse]]]:
    """Fetch a bounded, filtered order list with seller and warehouse details."""
    statement = (
        select(Order, Merchant, Warehouse)
        .join(Merchant, Merchant.id == Order.merchant_id)
        .outerjoin(Warehouse, Warehouse.id == Order.warehouse_id)
    )

    search = q.strip() if q else ""
    if len(search) >= 2:
        statement = statement.where(
            or_(
                Order.tracking_token == search.upper(),
                Order.merchant_order_ref.ilike(f"%{search}%"),
                Order.recipient_name.ilike(f"%{search}%"),
            )
        )
    if statuses:
        statement = statement.where(Order.status.in_(statuses))
    if merchant_id is not None:
        statement = statement.where(Order.merchant_id == merchant_id)
    if warehouse_id is not None:
        statement = statement.where(Order.warehouse_id == warehouse_id)
    if created_from is not None:
        statement = statement.where(Order.created_at >= created_from)
    if created_to is not None:
        statement = statement.where(Order.created_at <= created_to)

    statement = (
        statement
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(statement)
    return list(result.all())


async def republish_stale_placed_order(
    db: AsyncSession,
    order_id: uuid.UUID,
) -> None:
    """Append a stale placed order to orders_stream and leave its status unchanged."""
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=config.stale_pending_hours)

    result = await db.execute(
        select(
            Order,
            func.ST_AsText(Order.delivery_location).label("dropoff_location"),
        )
        .where(Order.id == order_id)
        .with_for_update()
    )
    row = result.one_or_none()
    if row is None:
        raise OrderNotFoundError("Order not found.")

    order, dropoff_location = row
    if (
        order.status != OrderStatus.placed
        or order.created_at > stale_cutoff
        or order.updated_at > stale_cutoff
    ):
        raise OrderNotEligibleError(
            "Only stale placed orders that have not been recently re-published can be unstuck."
        )

    time_window = ""
    if order.window_earliest is not None and order.window_latest is not None:
        time_window = (
            f"{order.window_earliest.isoformat()}/{order.window_latest.isoformat()}"
        )

    event = OrderCreatedEvent(
        event_id=str(uuid.uuid4()),
        order_id=str(order.id),
        merchant_id=str(order.merchant_id),
        warehouse_id=str(order.warehouse_id) if order.warehouse_id else None,
        dropoff_location=dropoff_location,
        dropoff_raw_address=order.delivery_address,
        time_window=time_window,
        weight_kg=float(order.weight_kg),
        volume_m3=float(order.volume_m3),
        created_at=order.created_at.isoformat(),
    )

    try:
        await add_to_stream("orders_stream", event.model_dump(mode="json"))
    except (RedisError, OSError) as exc:
        await db.rollback()
        logger.exception("Failed to re-publish stale order %s", order.id)
        raise OrderStreamPublishError from exc

    order.updated_at = now
    try:
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception(
            "Order %s was published but its re-publish timestamp did not commit",
            order.id,
        )
        raise
