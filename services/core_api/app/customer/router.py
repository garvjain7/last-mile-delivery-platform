"""Private customer order history and ownership APIs."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import Merchant, Order, OrderEvent, OrderStatus, User
from services.core_api.app.admin.security import csrf_check
from services.core_api.app.auth.dependencies import require_self_customer
from services.core_api.app.database.connection import get_db_session
from services.core_api.app.orders.timeline import STATUS_LABELS, build_timeline
from services.core_api.app.orders.router import CreateOrderRequest, _response
from services.core_api.app.orders.service import create_order, reverse_geocode

router = APIRouter(prefix="/api/users", tags=["Customer"])
_TERMINAL_STATUSES = {OrderStatus.delivered, OrderStatus.returned, OrderStatus.cancelled}


class ClaimOrderRequest(BaseModel):
    tracking_code: str
    recipient_phone: str


def _status_label(status_value: OrderStatus | str) -> str:
    value = status_value.value if isinstance(status_value, OrderStatus) else status_value
    return STATUS_LABELS.get(value, value.replace("_", " ").title())


def _encode_cursor(created_at: datetime, order_id: UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(order_id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_at, order_id = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(created_at), UUID(order_id)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


async def _enforce_limit(user_id: UUID, action: str, maximum: int, seconds: int) -> None:
    from streaming.client import get_redis_client

    client = await get_redis_client()
    count = await client.eval(
        "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]); end; return n",
        1,
        f"rate:customer:{action}:{user_id}",
        seconds,
    )
    if count > maximum:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(seconds)},
        )


def _tab_filter(tab: str):
    if tab not in {"active", "past", "all"}:
        raise HTTPException(status_code=422, detail="tab must be active, past, or all")
    if tab == "active":
        return Order.status.not_in(_TERMINAL_STATUSES)
    if tab == "past":
        return Order.status.in_(_TERMINAL_STATUSES)
    return None


@router.get("/{user_id}")
async def get_customer_dashboard(
    user_id: UUID,
    customer: User = Depends(require_self_customer),
    db: AsyncSession = Depends(get_db_session),
):
    """Return only the counts and brief recent-order details needed for the overview."""
    grouped = await db.execute(
        select(Order.status, func.count())
        .where(Order.customer_id == customer.id)
        .group_by(Order.status)
    )
    counts_by_status = {row.status: row[1] for row in grouped}
    active_count = sum(count for order_status, count in counts_by_status.items() if order_status not in _TERMINAL_STATUSES)
    all_count = sum(counts_by_status.values())

    recent = await db.execute(
        select(Order, Merchant.name)
        .join(Merchant, Merchant.id == Order.merchant_id)
        .where(Order.customer_id == customer.id, Order.status.not_in(_TERMINAL_STATUSES))
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(5)
    )
    return {
        "counts": {"active": active_count, "past": all_count - active_count, "all": all_count},
        "recent_active_orders": [
            {
                "id": str(order.id),
                "seller_name": seller_name,
                "status": order.status.value,
                "status_label": _status_label(order.status),
                "tracking_token": order.tracking_token,
                "created_at": order.created_at,
            }
            for order, seller_name in recent
        ],
    }


@router.get("/{user_id}/orders")
async def list_customer_orders(
    user_id: UUID,
    tab: str = Query("active"),
    status_filter: Optional[str] = Query(None, alias="status"),
    seller: Optional[UUID] = None,
    q: Optional[str] = None,
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = None,
    cursor: Optional[str] = None,
    limit: int = Query(20, ge=1, le=50),
    customer: User = Depends(require_self_customer),
    db: AsyncSession = Depends(get_db_session),
):
    conditions = [Order.customer_id == customer.id]
    tab_condition = _tab_filter(tab)
    if tab_condition is not None:
        conditions.append(tab_condition)
    if status_filter:
        try:
            conditions.append(Order.status == OrderStatus(status_filter))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Invalid status") from exc
    if seller:
        conditions.append(Order.merchant_id == seller)
    if from_:
        conditions.append(Order.created_at >= from_)
    if to:
        conditions.append(Order.created_at <= to)
    if q is not None:
        query = q.strip()
        if len(query) < 2:
            raise HTTPException(status_code=422, detail="q must contain at least 2 characters")
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        conditions.append(or_(
            Order.merchant_order_ref.ilike(pattern, escape="\\"),
            Merchant.name.ilike(pattern, escape="\\"),
            Order.delivery_address.ilike(pattern, escape="\\"),
            Order.recipient_name.ilike(pattern, escape="\\"),
            Order.tracking_token == query.upper(),
        ))
    if cursor:
        cursor_created_at, cursor_id = _decode_cursor(cursor)
        conditions.append(or_(
            Order.created_at < cursor_created_at,
            and_(Order.created_at == cursor_created_at, Order.id < cursor_id),
        ))

    result = await db.execute(
        select(Order, Merchant.name)
        .join(Merchant, Merchant.id == Order.merchant_id)
        .where(*conditions)
        .order_by(Order.created_at.desc(), Order.id.desc())
        .limit(limit + 1)
    )
    rows = list(result.all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for order, seller_name in rows:
        timeline = build_timeline(order, [])
        items.append({
            "id": str(order.id),
            "status": order.status.value,
            "status_label": _status_label(order.status),
            "rail": timeline["rail"],
            "tracking_token": order.tracking_token,
            "seller_name": seller_name,
            "created_at": order.created_at,
        })

    next_cursor = _encode_cursor(rows[-1][0].created_at, rows[-1][0].id) if has_more and rows else None
    response = {"items": items, "next_cursor": next_cursor}
    if not cursor:
        grouped = await db.execute(
            select(Order.status, func.count())
            .where(Order.customer_id == customer.id)
            .group_by(Order.status)
        )
        counts_by_status = {row.status: row[1] for row in grouped}
        all_count = sum(counts_by_status.values())
        active_count = sum(count for order_status, count in counts_by_status.items() if order_status not in _TERMINAL_STATUSES)
        response["counts"] = {"active": active_count, "past": all_count - active_count, "all": all_count}
        sellers = await db.execute(
            select(Merchant.id, Merchant.name)
            .join(Order, Order.merchant_id == Merchant.id)
            .where(Order.customer_id == customer.id)
            .distinct()
            .order_by(Merchant.name)
        )
        response["sellers"] = [{"id": str(row.id), "name": row.name} for row in sellers]
    return response


@router.get("/{user_id}/orders/{order_id}")
async def get_customer_order(
    user_id: UUID,
    order_id: UUID,
    customer: User = Depends(require_self_customer),
    db: AsyncSession = Depends(get_db_session),
):
    order = await db.scalar(
        select(Order)
        .where(Order.id == order_id, Order.customer_id == customer.id)
        .options(selectinload(Order.merchant), selectinload(Order.events))
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Not found")
    events = sorted(order.events, key=lambda event: (event.occurred_at, event.id))
    return {
        "id": str(order.id),
        "merchant_id": str(order.merchant_id),
        "merchant_order_ref": order.merchant_order_ref,
        "warehouse_id": str(order.warehouse_id) if order.warehouse_id else None,
        "status": order.status.value,
        "recipient_name": order.recipient_name,
        "recipient_phone": order.recipient_phone,
        "delivery_address": order.delivery_address,
        "window_earliest": order.window_earliest,
        "window_latest": order.window_latest,
        "weight_kg": order.weight_kg,
        "volume_m3": order.volume_m3,
        "tracking_token": order.tracking_token,
        "seller": {"id": str(order.merchant.id), "name": order.merchant.name},
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "events": [{"from_status": event.from_status.value if event.from_status else None,
                    "to_status": event.to_status.value,
                    "occurred_at": event.occurred_at} for event in events],
        **build_timeline(order, events),
    }


@router.get("/{user_id}/request/sellers")
async def list_request_sellers(
    user_id: UUID,
    customer: User = Depends(require_self_customer),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(
        select(Merchant.id, Merchant.name)
        .where(Merchant.is_active.is_(True))
        .order_by(Merchant.name)
    )
    return [{"id": str(row.id), "name": row.name} for row in result]


@router.get("/{user_id}/request/address")
async def reverse_geocode_customer_address(
    user_id: UUID,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    customer: User = Depends(require_self_customer),
):
    address = await reverse_geocode(lng, lat)
    return {"address": address, "lat": lat, "lng": lng}


@router.post("/{user_id}/request", dependencies=[Depends(csrf_check)])
async def submit_customer_order(
    user_id: UUID,
    payload: CreateOrderRequest,
    response: Response,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    customer: User = Depends(require_self_customer),
    db: AsyncSession = Depends(get_db_session),
):
    await _enforce_limit(customer.id, "order_create", 10, 3600)
    if idempotency_key is None:
        raise HTTPException(status_code=400, detail="Idempotency-Key header is required")
    idempotency_key = idempotency_key.strip()
    if not idempotency_key or len(idempotency_key) > 200:
        raise HTTPException(status_code=400, detail="Invalid Idempotency-Key")
    order, created = await create_order(
        db,
        customer_id=customer.id,
        seller_id=payload.seller_id,
        recipient_name=payload.recipient_name,
        recipient_phone=payload.recipient_phone,
        delivery_address=payload.delivery_address,
        weight_kg=payload.weight_kg,
        volume_m3=payload.volume_m3,
        idempotency_key=idempotency_key,
        window_earliest=payload.window_earliest,
        window_latest=payload.window_latest,
    )
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _response(order, created)


@router.post("/{user_id}/orders/claim", dependencies=[Depends(csrf_check)])
async def claim_customer_order(
    user_id: UUID,
    payload: ClaimOrderRequest,
    customer: User = Depends(require_self_customer),
    db: AsyncSession = Depends(get_db_session),
):
    await _enforce_limit(customer.id, "claim", 5, 600)
    code = payload.tracking_code.strip().upper()
    result = await db.execute(
        update(Order)
        .where(
            Order.tracking_token == code,
            Order.customer_id.is_(None),
            Order.recipient_phone == payload.recipient_phone,
        )
        .values(customer_id=customer.id)
        .returning(Order.id)
    )
    claimed_id = result.scalar_one_or_none()
    if claimed_id is not None:
        await db.commit()
        return {"order_id": str(claimed_id), "status": "claimed"}

    existing = await db.scalar(
        select(Order).where(
            Order.tracking_token == code,
            Order.customer_id == customer.id,
            Order.recipient_phone == payload.recipient_phone,
        )
    )
    if existing is not None:
        return {"order_id": str(existing.id), "status": "claimed"}
    raise HTTPException(status_code=404, detail="Not found")
