# admin/routes/orders.py  — §7.6 Orders (read-only + counts)
from __future__ import annotations

import logging
import re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import (
    Merchant,
    Order,
    OrderEvent,
    OrderStatus,
    Route,
    RouteStop,
    User,
    Vehicle,
    Warehouse,
)
from services.core_api.app.admin.common import _404, _422
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.admin.rules import (
    classify_q,
    decode_cursor,
    encode_cursor,
    prepare_q,
)
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


def _uuid_safe(val: str) -> Optional[_uuid.UUID]:
    """Return UUID from string or None if invalid (prevents 500 on tampered cursors)."""
    try:
        return _uuid.UUID(val)
    except (ValueError, AttributeError):
        return None


def _order_search_filter(value: Optional[str]):
    """Apply the documented OR search across public order references and recipients."""
    if not value or len(value.strip()) < 2:
        return None

    query = value.strip()
    search_terms = []
    kind = classify_q(query)
    if kind == "tracking_token":
        search_terms.append(Order.tracking_token == query.upper())
    if kind == "phone":
        search_terms.append(Order.recipient_phone == query)

    query_pattern = prepare_q(query)
    if query_pattern:
        search_terms.extend((
            Order.merchant_order_ref.ilike(query_pattern),
            Order.recipient_name.ilike(query_pattern),
        ))
    return or_(*search_terms)

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class OrderDriverOut(BaseModel):
    id: str
    full_name: str

    model_config = {"extra": "forbid"}


class OrderListItem(BaseModel):
    merchant_order_ref: str
    tracking_token: str
    merchant: Dict[str, str]
    warehouse: Optional[Dict[str, str]]
    status: str
    recipient_name: str
    is_guest: bool
    window_earliest: Optional[datetime]
    window_latest: Optional[datetime]
    driver: Optional[OrderDriverOut]
    created_at: datetime

    model_config = {"extra": "forbid"}


class OrderListOut(BaseModel):
    items: List[OrderListItem]
    next_cursor: Optional[str]

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# GET /orders
# ---------------------------------------------------------------------------


@router.get("/orders", response_model=OrderListOut)
async def list_orders(
    q: Optional[str] = Query(None, max_length=100),
    status: Optional[List[str]] = Query(None),
    merchant_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    overdue: Optional[bool] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> OrderListOut:
    now = datetime.now(timezone.utc)

    # Fix 10: Reject naive (timezone-unaware) datetimes
    if from_ is not None and from_.tzinfo is None:
        raise _422("'from' must be timezone-aware (e.g. include Z or +00:00).", "from")
    if to is not None and to.tzinfo is None:
        raise _422("'to' must be timezone-aware (e.g. include Z or +00:00).", "to")

    stmt = (
        select(Order, Merchant, Warehouse)
        .join(Merchant, Merchant.id == Order.merchant_id)
        .outerjoin(Warehouse, Warehouse.id == Order.warehouse_id)
    )

    search_filter = _order_search_filter(q)
    if search_filter is not None:
        stmt = stmt.where(search_filter)

    if status:
        valid_statuses = []
        for s in status:
            try:
                valid_statuses.append(OrderStatus(s))
            except ValueError:
                raise _422(f"Unknown order status: {s!r}", "status")
        stmt = stmt.where(Order.status.in_(valid_statuses))

    if merchant_id:
        try:
            mid = _uuid.UUID(merchant_id)
        except ValueError:
            raise _422("Invalid merchant_id UUID.")
        stmt = stmt.where(Order.merchant_id == mid)

    if warehouse_id:
        try:
            wid = _uuid.UUID(warehouse_id)
        except ValueError:
            raise _422("Invalid warehouse_id UUID.")
        stmt = stmt.where(Order.warehouse_id == wid)

    if from_:
        stmt = stmt.where(Order.created_at >= from_)
    if to:
        stmt = stmt.where(Order.created_at <= to)

    if overdue:
        stmt = stmt.where(
            Order.window_latest < now,
            Order.status.in_([OrderStatus.placed, OrderStatus.sent, OrderStatus.pending, OrderStatus.assigned,
                               OrderStatus.out_for_delivery, OrderStatus.attempt_failed]),
        )


    if cursor:
        try:
            cursor_ts, cursor_rownum = decode_cursor(cursor)
        except ValueError:
            raise _422("Invalid cursor.", "cursor")
        cursor_uuid = _uuid_safe(cursor_rownum)
        if cursor_uuid is None:
            raise _422("Invalid cursor.", "cursor")
        stmt = stmt.where(
            or_(
                Order.created_at < cursor_ts,
                and_(Order.created_at == cursor_ts, Order.id < cursor_uuid),
            )
        )


    stmt = stmt.order_by(Order.created_at.desc(), Order.id.desc()).limit(limit + 1)
    rows = (await db.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    # Fix 7: Batch-resolve driver info in a single query instead of N+1 per order.
    order_ids = [r.Order.id for r in rows]
    driver_by_order: dict = {}
    if order_ids:
        driver_rows = (await db.execute(
            select(
                RouteStop.order_id,
                User.id.label("driver_id"),
                User.full_name.label("driver_full_name"),
                RouteStop.created_at.label("rs_created_at"),
            )
            .join(Route, Route.id == RouteStop.route_id)
            .join(User, User.id == Route.driver_id)
            .where(RouteStop.order_id.in_(order_ids))
            .order_by(RouteStop.order_id, RouteStop.created_at.desc())
        )).all()
        # Keep only the most recent driver per order
        for dr in driver_rows:
            if dr.order_id not in driver_by_order:
                driver_by_order[dr.order_id] = dr

    items = []
    for r in rows:
        o, m, wh = r.Order, r.Merchant, r.Warehouse

        dr = driver_by_order.get(o.id)
        driver_out = OrderDriverOut(id=str(dr.driver_id), full_name=dr.driver_full_name) if dr else None

        items.append(OrderListItem(
            merchant_order_ref=o.merchant_order_ref,
            tracking_token=o.tracking_token,
            merchant={"id": str(m.id), "name": m.name},
            warehouse={"id": str(wh.id), "code": wh.code} if wh else None,
            status=o.status.value,
            recipient_name=o.recipient_name,
            is_guest=o.customer_id is None,
            window_earliest=o.window_earliest,
            window_latest=o.window_latest,
            driver=driver_out,
            created_at=o.created_at,
        ))

    next_cursor = None
    if has_more and rows:
        last = rows[-1].Order
        # Fix 9: cursor is opaque base64; id is encoded but never appears as plaintext UUID in the URL
        next_cursor = encode_cursor(last.created_at, str(last.id))

    return OrderListOut(items=items, next_cursor=next_cursor)


# ---------------------------------------------------------------------------
# GET /orders/counts
# ---------------------------------------------------------------------------


class OrderCountsOut(BaseModel):
    placed: int
    sent: int
    pending: int
    assigned: int
    out_for_delivery: int
    delivered: int
    attempt_failed: int
    returned: int
    cancelled: int

    model_config = {"extra": "forbid"}


@router.get("/orders/counts", response_model=OrderCountsOut)
async def order_counts(
    q: Optional[str] = Query(None, max_length=100),
    merchant_id: Optional[str] = Query(None),
    warehouse_id: Optional[str] = Query(None),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    overdue: Optional[bool] = Query(None),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> OrderCountsOut:
    now = datetime.now(timezone.utc)

    stmt = select(Order.status, func.count().label("cnt")).select_from(Order)

    search_filter = _order_search_filter(q)
    if search_filter is not None:
        stmt = stmt.where(search_filter)

    if merchant_id:
        try:
            stmt = stmt.where(Order.merchant_id == _uuid.UUID(merchant_id))
        except ValueError:
            raise _422("Invalid merchant_id UUID.")

    if warehouse_id:
        try:
            stmt = stmt.where(Order.warehouse_id == _uuid.UUID(warehouse_id))
        except ValueError:
            raise _422("Invalid warehouse_id UUID.")

    if from_:
        stmt = stmt.where(Order.created_at >= from_)
    if to:
        stmt = stmt.where(Order.created_at <= to)
    if overdue:
        stmt = stmt.where(
            Order.window_latest < now,
            Order.status.in_([OrderStatus.placed, OrderStatus.sent, OrderStatus.pending, OrderStatus.assigned,
                               OrderStatus.out_for_delivery, OrderStatus.attempt_failed])
        )

    rows = (await db.execute(stmt.group_by(Order.status))).all()
    counts: Dict[str, int] = {s.value: 0 for s in OrderStatus}
    for s, c in rows:
        counts[s.value] = c

    return OrderCountsOut(
        placed=counts["placed"], sent=counts["sent"],
        pending=counts["pending"], assigned=counts["assigned"],
        out_for_delivery=counts["out_for_delivery"], delivered=counts["delivered"],
        attempt_failed=counts["attempt_failed"], returned=counts["returned"],
        cancelled=counts["cancelled"],
    )


# ---------------------------------------------------------------------------
# GET /orders/{tracking_token}
# ---------------------------------------------------------------------------


class OrderEventOut(BaseModel):
    from_status: Optional[str]
    to_status: str
    occurred_at: datetime
    seconds_since_previous: Optional[int]
    actor: Optional[Dict[str, str]]

    model_config = {"extra": "forbid"}


class StopRouteLoad(BaseModel):
    weight_kg: float
    volume_m3: float

    model_config = {"extra": "forbid"}


class OrderStopOut(BaseModel):
    stop_id: str
    route_id: str
    route_status: str
    driver: Optional[Dict[str, str]]
    vehicle: Optional[Dict[str, Any]]
    sequence: int
    status: str
    failure_reason: Optional[str]
    planned_arrival_at: datetime
    arrived_at: Optional[datetime]
    completed_at: Optional[datetime]
    route_load: StopRouteLoad
    parcel_exceeds_vehicle: bool

    model_config = {"extra": "forbid"}


class OrderDetailOut(BaseModel):
    merchant_order_ref: str
    tracking_token: str
    merchant: Dict[str, str]
    warehouse: Optional[Dict[str, Any]]
    status: str
    recipient_name: str
    recipient_phone: str
    is_guest: bool
    delivery_address: str
    latitude: float
    longitude: float
    weight_kg: float
    volume_m3: float
    window_earliest: Optional[datetime]
    window_latest: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    customer: Optional[Dict[str, str]]
    distance_km_straight: Optional[float]
    events: List[OrderEventOut]
    stops: List[OrderStopOut]

    model_config = {"extra": "forbid"}


@router.get("/orders/{tracking_token}", response_model=OrderDetailOut)
async def get_order(
    tracking_token: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> OrderDetailOut:
    code = tracking_token.strip().upper()
    if not re.match(r"^[A-Z]{10}$", code):
        raise _404("Order not found.")

    row = (await db.execute(
        select(
            Order,
            Merchant,
            Warehouse,
            text("ST_Y(orders.delivery_location::geometry)").label("dlat"),
            text("ST_X(orders.delivery_location::geometry)").label("dlon"),
            text("ST_Y(warehouses.location::geometry)").label("wlat"),
            text("ST_X(warehouses.location::geometry)").label("wlon"),
        )
        .join(Merchant, Merchant.id == Order.merchant_id)
        .outerjoin(Warehouse, Warehouse.id == Order.warehouse_id)
        .where(Order.tracking_token == code)
    )).first()

    if row is None:
        raise _404("Order not found.")

    o, m, wh = row.Order, row.Merchant, row.Warehouse
    dlat, dlon = float(row.dlat), float(row.dlon)
    if wh:
        wlat, wlon = float(row.wlat), float(row.wlon)
        dist_row = (await db.execute(
            text(
                "SELECT ST_Distance("
                "  ST_SetSRID(ST_MakePoint(:olon, :olat), 4326)::geography,"
                "  ST_SetSRID(ST_MakePoint(:wlon, :wlat), 4326)::geography"
                ") / 1000 AS dist_km"
            ).bindparams(olat=dlat, olon=dlon, wlat=wlat, wlon=wlon)
        )).first()
        distance_km = round(float(dist_row.dist_km), 1) if dist_row else None
        warehouse_out = {
            "id": str(wh.id), "code": wh.code, "name": wh.name,
            "latitude": wlat, "longitude": wlon,
        }
    else:
        distance_km = None
        warehouse_out = None

    customer_out = None
    if o.customer_id:
        cust = await db.get(User, o.customer_id)
        if cust:
            customer_out = {"id": str(cust.id), "full_name": cust.full_name}

    events_rows = (await db.execute(
        select(OrderEvent).options(selectinload(OrderEvent.order))
        .where(OrderEvent.order_id == o.id)
        .order_by(OrderEvent.occurred_at.desc(), OrderEvent.id.desc())
    )).scalars().all()

    event_outs = []
    prev_ts: Optional[datetime] = None
    for ev in reversed(events_rows):
        actor_info = None
        if ev.actor_user_id:
            a = await db.get(User, ev.actor_user_id)
            actor_info = {"id": str(ev.actor_user_id), "full_name": a.full_name if a else "Unknown"}
        secs = int((ev.occurred_at - prev_ts).total_seconds()) if prev_ts else None
        prev_ts = ev.occurred_at
        event_outs.append(OrderEventOut(
            from_status=ev.from_status.value if ev.from_status else None,
            to_status=ev.to_status.value,
            occurred_at=ev.occurred_at,
            seconds_since_previous=secs,
            actor=actor_info,
        ))
    event_outs.reverse()  # newest first for response

    stop_rows = (await db.execute(
        select(RouteStop, Route, Vehicle, User.full_name.label("driver_name"), User.id.label("driver_id"))
        .join(Route, Route.id == RouteStop.route_id)
        .outerjoin(Vehicle, Vehicle.id == Route.vehicle_id)
        .outerjoin(User, User.id == Route.driver_id)
        .where(RouteStop.order_id == o.id)
        .order_by(RouteStop.created_at.desc())
    )).all()

    stop_outs = []
    for sr in stop_rows:
        rs, rt, v = sr.RouteStop, sr.Route, sr.Vehicle
        load_row = (await db.execute(
            select(
                func.sum(Order.weight_kg).label("w"),
                func.sum(Order.volume_m3).label("v"),
            )
            .join(RouteStop, RouteStop.order_id == Order.id)
            .where(RouteStop.route_id == rt.id)
        )).first()

        route_load = StopRouteLoad(
            weight_kg=float(load_row.w or 0),
            volume_m3=float(load_row.v or 0),
        )
        exceeds = False
        if v:
            exceeds = (float(o.weight_kg) > float(v.max_weight_kg) or
                       float(o.volume_m3) > float(v.max_volume_m3))

        driver_out = {"id": str(sr.driver_id), "full_name": sr.driver_name} if sr.driver_id else None
        vehicle_out = {
            "type": v.type.value,
            "registration_number": v.registration_number,
            "max_weight_kg": float(v.max_weight_kg),
            "max_volume_m3": float(v.max_volume_m3),
        } if v else None

        stop_outs.append(OrderStopOut(
            stop_id=str(rs.id), route_id=str(rt.id),
            route_status=rt.status.value, driver=driver_out, vehicle=vehicle_out,
            sequence=rs.sequence, status=rs.status.value,
            failure_reason=rs.failure_reason.value if rs.failure_reason else None,
            planned_arrival_at=rs.planned_arrival_at, arrived_at=rs.arrived_at,
            completed_at=rs.completed_at,
            route_load=route_load, parcel_exceeds_vehicle=exceeds,
        ))

    return OrderDetailOut(
        merchant_order_ref=o.merchant_order_ref,
        tracking_token=o.tracking_token,
        merchant={"id": str(m.id), "name": m.name},
        warehouse=warehouse_out,
        status=o.status.value,
        recipient_name=o.recipient_name, recipient_phone=o.recipient_phone,
        is_guest=o.customer_id is None,
        delivery_address=o.delivery_address,
        latitude=dlat, longitude=dlon,
        weight_kg=float(o.weight_kg), volume_m3=float(o.volume_m3),
        window_earliest=o.window_earliest, window_latest=o.window_latest,
        created_at=o.created_at, updated_at=o.updated_at,
        customer=customer_out, distance_km_straight=distance_km,
        events=event_outs, stops=stop_outs,
    )
