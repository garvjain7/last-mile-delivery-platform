# admin/routes/overview.py  — §7.1 Meta + §7.1 Overview
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import (
    AdminAuditLog,
    Driver,
    DriverStatus,
    Merchant,
    Order,
    OrderEvent,
    OrderStatus,
    Route,
    RouteStatus,
    User,
    UserRole,
    UserRole_,
    Warehouse,
)
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.config import config
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# §7.1 Meta — /me
# ---------------------------------------------------------------------------


class MeOut(BaseModel):
    id: str
    full_name: str
    email: Optional[str]
    roles: List[str]
    app_timezone: str

    model_config = {"extra": "forbid"}


@router.get("/me", response_model=MeOut)
async def admin_me(
    actor: User = Depends(require_admin),
) -> MeOut:
    return MeOut(
        id=str(actor.id),
        full_name=actor.full_name,
        email=str(actor.email) if actor.email else None,
        roles=[r.role.value for r in actor.roles],
        app_timezone=config.app_timezone,
    )


# ---------------------------------------------------------------------------
# §7.1 Overview — /overview
# ---------------------------------------------------------------------------

STALE_PENDING_HOURS: int = config.stale_pending_hours
APP_TIMEZONE: str = config.app_timezone


def _local_midnight() -> datetime:
    """Return today's midnight in APP_TIMEZONE as UTC datetime."""
    import zoneinfo
    tz = zoneinfo.ZoneInfo(APP_TIMEZONE)
    now_local = datetime.now(tz)
    midnight_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_local.astimezone(timezone.utc)


class KPIs(BaseModel):
    orders_today: int
    open_orders: int
    delivered_today: int
    failed_attempts_today: int
    delivery_success_rate_7d: Optional[float]  # null when denominator=0

    model_config = {"extra": "forbid"}


class PendingDriverItem(BaseModel):
    user_id: str
    full_name: str
    created_at: datetime

    model_config = {"extra": "forbid"}


class LockedUserItem(BaseModel):
    id: str
    full_name: str
    locked_until: Optional[datetime]

    model_config = {"extra": "forbid"}


class StaleOrderItem(BaseModel):
    tracking_token: str
    merchant_order_ref: str
    merchant_name: str
    created_at: datetime

    model_config = {"extra": "forbid"}


class FailedOrderItem(BaseModel):
    tracking_token: str
    merchant_order_ref: str
    merchant_name: str
    updated_at: datetime

    model_config = {"extra": "forbid"}


class NeedsAttention(BaseModel):
    pending_drivers: Dict[str, Any]
    locked_users: Dict[str, Any]
    stale_pending_orders: Dict[str, Any]
    failed_attempt_orders: Dict[str, Any]

    model_config = {"extra": "forbid"}


class WarehouseOverviewItem(BaseModel):
    id: str
    code: str
    name: str
    open_orders: int
    active_routes: int

    model_config = {"extra": "forbid"}


class RecentActivityItem(BaseModel):
    id: int
    occurred_at: datetime
    actor_name: Optional[str]
    action: str
    target_label: str

    model_config = {"extra": "forbid"}


class OverviewOut(BaseModel):
    generated_at: datetime
    kpis: KPIs
    needs_attention: NeedsAttention
    open_orders_by_status: Dict[str, int]
    drivers_by_status: Dict[str, int]
    users_by_role: Dict[str, int]
    warehouses: List[WarehouseOverviewItem]
    recent_activity: List[RecentActivityItem]

    model_config = {"extra": "forbid"}


@router.get("/overview", response_model=OverviewOut)
async def admin_overview(
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> OverviewOut:
    now = datetime.now(timezone.utc)
    midnight = _local_midnight()
    seven_days_ago = now - timedelta(days=7)
    stale_cutoff = now - timedelta(hours=STALE_PENDING_HOURS)

    # --- KPIs ---
    orders_today_row = await db.execute(
        select(func.count()).select_from(Order).where(Order.created_at >= midnight)
    )
    orders_today = orders_today_row.scalar_one()

    open_orders_row = await db.execute(
        select(func.count()).select_from(Order).where(Order.status.in_([
            OrderStatus.placed, OrderStatus.sent, OrderStatus.pending, OrderStatus.assigned,
            OrderStatus.out_for_delivery, OrderStatus.attempt_failed,
        ]))
    )
    open_orders = open_orders_row.scalar_one()

    delivered_today_row = await db.execute(
        select(func.count()).select_from(OrderEvent).where(
            OrderEvent.to_status == OrderStatus.delivered,
            OrderEvent.occurred_at >= midnight,
        )
    )
    delivered_today = delivered_today_row.scalar_one()

    failed_today_row = await db.execute(
        select(func.count()).select_from(OrderEvent).where(
            OrderEvent.to_status == OrderStatus.attempt_failed,
            OrderEvent.occurred_at >= midnight,
        )
    )
    failed_attempts_today = failed_today_row.scalar_one()

    rate_row = await db.execute(
        select(
            func.count().filter(OrderEvent.to_status == OrderStatus.delivered).label("del_"),
            func.count().filter(OrderEvent.to_status == OrderStatus.attempt_failed).label("fail"),
        ).select_from(OrderEvent).where(
            OrderEvent.to_status.in_([OrderStatus.delivered, OrderStatus.attempt_failed]),
            OrderEvent.occurred_at >= seven_days_ago,
        )
    )
    rate_vals = rate_row.one()
    denominator = rate_vals.del_ + rate_vals.fail
    delivery_success_rate = round(rate_vals.del_ / denominator, 4) if denominator > 0 else None

    # --- Needs attention ---
    pd_total_row = await db.execute(
        select(func.count()).select_from(Driver).where(Driver.status == DriverStatus.pending)
    )
    pd_total = pd_total_row.scalar_one()
    pd_rows = (await db.execute(
        select(Driver, User)
        .join(User, User.id == Driver.user_id)
        .where(Driver.status == DriverStatus.pending)
        .order_by(Driver.created_at.asc())
        .limit(5)
    )).all()
    pending_driver_items = [
        {"user_id": str(d.user_id), "full_name": u.full_name, "created_at": d.created_at}
        for d, u in pd_rows
    ]

    lu_total_row = await db.execute(
        select(func.count()).select_from(User).where(
            User.locked_until.isnot(None), User.locked_until > now
        )
    )
    lu_total = lu_total_row.scalar_one()
    lu_rows = (await db.execute(
        select(User).where(User.locked_until.isnot(None), User.locked_until > now)
        .order_by(User.locked_until.asc()).limit(5)
    )).scalars().all()
    locked_user_items = [
        {"id": str(u.id), "full_name": u.full_name, "locked_until": u.locked_until}
        for u in lu_rows
    ]

    sp_total_row = await db.execute(
        select(func.count()).select_from(Order).where(
            Order.status == OrderStatus.pending, Order.created_at <= stale_cutoff
        )
    )
    sp_total = sp_total_row.scalar_one()
    sp_rows = (await db.execute(
        select(Order, Merchant.name.label("merchant_name"))
        .join(Merchant, Merchant.id == Order.merchant_id)
        .where(Order.status == OrderStatus.pending, Order.created_at <= stale_cutoff)
        .order_by(Order.created_at.asc()).limit(5)
    )).all()
    stale_items = [
        {"tracking_token": o.tracking_token, "merchant_order_ref": o.merchant_order_ref,
         "merchant_name": mn, "created_at": o.created_at}
        for o, mn in sp_rows
    ]

    fa_total_row = await db.execute(
        select(func.count()).select_from(Order).where(Order.status == OrderStatus.attempt_failed)
    )
    fa_total = fa_total_row.scalar_one()
    fa_rows = (await db.execute(
        select(Order, Merchant.name.label("merchant_name"))
        .join(Merchant, Merchant.id == Order.merchant_id)
        .where(Order.status == OrderStatus.attempt_failed)
        .order_by(Order.updated_at.asc()).limit(5)
    )).all()
    fa_items = [
        {"tracking_token": o.tracking_token, "merchant_order_ref": o.merchant_order_ref,
         "merchant_name": mn, "updated_at": o.updated_at}
        for o, mn in fa_rows
    ]

    # --- Open orders by status ---
    oobs_rows = (await db.execute(
        select(Order.status, func.count().label("cnt"))
        .where(Order.status.in_([
            OrderStatus.placed, OrderStatus.sent, OrderStatus.pending, OrderStatus.assigned,
            OrderStatus.out_for_delivery, OrderStatus.attempt_failed,
        ]))
        .group_by(Order.status)
    )).all()
    open_orders_by_status: Dict[str, int] = {
        "placed": 0, "sent": 0, "pending": 0, "assigned": 0,
        "out_for_delivery": 0, "attempt_failed": 0
    }
    for s, c in oobs_rows:
        open_orders_by_status[s.value] = c

    # --- Drivers by status ---
    dbs_rows = (await db.execute(
        select(Driver.status, func.count().label("cnt")).group_by(Driver.status)
    )).all()
    drivers_by_status: Dict[str, int] = {
        "pending": 0, "offline": 0, "available": 0, "on_route": 0, "rejected": 0
    }
    for s, c in dbs_rows:
        drivers_by_status[s.value] = c

    # --- Users by role ---
    ubr_rows = (await db.execute(
        select(UserRole_.role, func.count().label("cnt")).group_by(UserRole_.role)
    )).all()
    users_by_role: Dict[str, int] = {
        "customer": 0, "merchant": 0, "dispatcher": 0,
        "driver": 0, "fleet_manager": 0, "admin": 0,
    }
    for r, c in ubr_rows:
        users_by_role[r.value] = c

    # --- Warehouses (top 8 active by open orders) ---
    open_order_count = (
        select(func.count())
        .where(
            Order.warehouse_id == Warehouse.id,
            Order.status.in_([
                OrderStatus.pending, OrderStatus.assigned,
                OrderStatus.out_for_delivery, OrderStatus.attempt_failed,
            ]),
        )
        .correlate(Warehouse)
        .scalar_subquery()
    )
    active_route_count = (
        select(func.count())
        .where(
            Route.warehouse_id == Warehouse.id,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress]),
        )
        .correlate(Warehouse)
        .scalar_subquery()
    )
    wh_rows = (await db.execute(
        select(
            Warehouse.id,
            Warehouse.code,
            Warehouse.name,
            open_order_count.label("open_orders"),
            active_route_count.label("active_routes"),
        )
        .where(Warehouse.is_active == True)
        .order_by(open_order_count.desc())
        .limit(8)
    )).all()
    warehouses = [
        WarehouseOverviewItem(
            id=str(r.id), code=r.code, name=r.name,
            open_orders=r.open_orders, active_routes=r.active_routes,
        )
        for r in wh_rows
    ]

    # --- Recent activity (last 8) ---
    ra_rows = (await db.execute(
        select(AdminAuditLog, User.full_name.label("actor_name"))
        .outerjoin(User, User.id == AdminAuditLog.actor_user_id)
        .order_by(AdminAuditLog.occurred_at.desc())
        .limit(8)
    )).all()
    recent_activity = [
        RecentActivityItem(
            id=row.AdminAuditLog.id,
            occurred_at=row.AdminAuditLog.occurred_at,
            actor_name=row.actor_name,
            action=row.AdminAuditLog.action,
            target_label=row.AdminAuditLog.target_label,
        )
        for row in ra_rows
    ]

    return OverviewOut(
        generated_at=now,
        kpis=KPIs(
            orders_today=orders_today,
            open_orders=open_orders,
            delivered_today=delivered_today,
            failed_attempts_today=failed_attempts_today,
            delivery_success_rate_7d=delivery_success_rate,
        ),
        needs_attention=NeedsAttention(
            pending_drivers={"count": pd_total, "items": pending_driver_items},
            locked_users={"count": lu_total, "items": locked_user_items},
            stale_pending_orders={"count": sp_total, "items": stale_items},
            failed_attempt_orders={"count": fa_total, "items": fa_items},
        ),
        open_orders_by_status=open_orders_by_status,
        drivers_by_status=drivers_by_status,
        users_by_role=users_by_role,
        warehouses=warehouses,
        recent_activity=recent_activity,
    )
