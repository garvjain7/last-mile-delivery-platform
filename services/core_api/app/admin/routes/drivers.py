# admin/routes/drivers.py  — §7.2 Drivers
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db_models.models import (
    Driver,
    DriverStatus,
    Route,
    RouteStatus,
    RouteStop,
    StopStatus,
    User,
    Vehicle,
)
from services.core_api.app.admin.audit import write_audit
from services.core_api.app.admin.common import _404, _409, _422
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.admin.emails import send_driver_approved, send_driver_rejected
from services.core_api.app.admin.rules import (
    DRIVER_SORT_COLS,
    driver_reject_transition,
    driver_verify_transition,
    prepare_q,
    validate_dir,
    validate_sort,
)
from services.core_api.app.admin.security import get_client_ip
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class VehicleOut(BaseModel):
    id: str
    type: str
    registration_number: str
    max_weight_kg: Optional[float] = None
    max_volume_m3: Optional[float] = None

    model_config = {"extra": "forbid"}


class VehicleListOut(BaseModel):
    id: str
    type: str
    registration_number: str

    model_config = {"extra": "forbid"}


class DriverListItem(BaseModel):
    user_id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    status: str
    account_active: bool
    vehicle: Optional[VehicleListOut]
    created_at: datetime
    last_login_at: Optional[datetime]

    model_config = {"extra": "forbid"}


class DriverCounts(BaseModel):
    pending: int
    active: int
    rejected: int
    all: int

    model_config = {"extra": "forbid"}


class DriverListOut(BaseModel):
    items: List[DriverListItem]
    total: int
    page: int
    page_size: int
    counts: DriverCounts

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# GET /drivers
# ---------------------------------------------------------------------------

@router.get("/drivers", response_model=DriverListOut)
async def list_drivers(
    segment: Literal["pending", "active", "rejected", "all"] = "pending",
    q: Optional[str] = Query(None, max_length=100),
    sort: str = Query("created_at"),
    dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> DriverListOut:
    try:
        validate_sort(sort, DRIVER_SORT_COLS)
        validate_dir(dir)
    except ValueError as e:
        raise _422(str(e))

    def _seg_filter(seg: str):
        if seg == "pending":
            return Driver.status == DriverStatus.pending
        if seg == "active":
            return Driver.status.in_([DriverStatus.offline, DriverStatus.available, DriverStatus.on_route])
        if seg == "rejected":
            return Driver.status == DriverStatus.rejected
        return True  # all

    counts_rows = (await db.execute(
        select(
            func.count().filter(Driver.status == DriverStatus.pending).label("pending"),
            func.count().filter(Driver.status.in_([DriverStatus.offline, DriverStatus.available, DriverStatus.on_route])).label("active"),
            func.count().filter(Driver.status == DriverStatus.rejected).label("rejected"),
            func.count().label("all"),
        ).select_from(Driver)
    )).one()

    q_pat = prepare_q(q)

    base_stmt = (
        select(Driver, User, Vehicle)
        .join(User, User.id == Driver.user_id)
        .outerjoin(Vehicle, Vehicle.id == Driver.vehicle_id)
    )

    if segment != "all":
        base_stmt = base_stmt.where(_seg_filter(segment))

    if q_pat:
        base_stmt = base_stmt.where(
            or_(
                User.full_name.ilike(q_pat),
                User.email.ilike(q_pat),
                User.phone.ilike(q_pat),
                Vehicle.registration_number.ilike(q_pat),
            )
        )

    sort_col_map = {
        "created_at": Driver.created_at,
        "full_name": User.full_name,
        "last_login_at": User.last_login_at,
        "status": Driver.status,
    }
    sort_col = sort_col_map[sort]
    order_expr = sort_col.asc() if dir == "asc" else sort_col.desc()

    total_row = await db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    )
    total = total_row.scalar_one()

    rows = (await db.execute(
        base_stmt.order_by(order_expr, Driver.user_id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )).all()

    items = [
        DriverListItem(
            user_id=str(d.user_id),
            full_name=u.full_name,
            email=str(u.email) if u.email else None,
            phone=u.phone,
            status=d.status.value,
            account_active=u.is_active,
            vehicle=VehicleListOut(
                id=str(v.id),
                type=v.type.value,
                registration_number=v.registration_number,
            ) if v else None,
            created_at=d.created_at,
            last_login_at=u.last_login_at,
        )
        for d, u, v in rows
    ]

    return DriverListOut(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        counts=DriverCounts(
            pending=counts_rows.pending,
            active=counts_rows.active,
            rejected=counts_rows.rejected,
            all=counts_rows.all,
        ),
    )


# ---------------------------------------------------------------------------
# GET /drivers/{user_id}
# ---------------------------------------------------------------------------

class ActiveRouteOut(BaseModel):
    id: str
    status: str
    started_at: Optional[datetime]
    stops_total: int
    stops_done: int

    model_config = {"extra": "forbid"}


class RecentRouteOut(BaseModel):
    id: str
    status: str
    created_at: datetime
    stops_total: int
    stops_done: int

    model_config = {"extra": "forbid"}


class DriverStatsOut(BaseModel):
    completed_deliveries: int
    failed_stops: int

    model_config = {"extra": "forbid"}


class DriverDetailOut(BaseModel):
    user_id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    status: str
    account_active: bool
    vehicle: Optional[VehicleOut]
    created_at: datetime
    last_login_at: Optional[datetime]
    stats: DriverStatsOut
    active_route: Optional[ActiveRouteOut]
    recent_routes: List[RecentRouteOut]

    model_config = {"extra": "forbid"}


@router.get("/drivers/{user_id}", response_model=DriverDetailOut)
async def get_driver(
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> DriverDetailOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    row = (await db.execute(
        select(Driver, User, Vehicle)
        .join(User, User.id == Driver.user_id)
        .outerjoin(Vehicle, Vehicle.id == Driver.vehicle_id)
        .where(Driver.user_id == uid)
    )).first()

    if row is None:
        raise _404()

    d, u, v = row

    stats_row = (await db.execute(
        select(
            func.count().filter(RouteStop.status == StopStatus.delivered).label("completed"),
            func.count().filter(RouteStop.status == StopStatus.failed).label("failed"),
        )
        .select_from(RouteStop)
        .join(Route, Route.id == RouteStop.route_id)
        .where(Route.driver_id == uid)
    )).one()

    active_route_row = (await db.execute(
        select(Route)
        .where(
            Route.driver_id == uid,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress]),
        )
        .order_by(Route.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    active_route = None
    if active_route_row:
        total_stops = (await db.execute(
            select(func.count()).where(RouteStop.route_id == active_route_row.id)
        )).scalar_one()
        done_stops = (await db.execute(
            select(func.count()).where(
                RouteStop.route_id == active_route_row.id,
                RouteStop.status.in_([StopStatus.delivered, StopStatus.failed, StopStatus.skipped]),
            )
        )).scalar_one()
        active_route = ActiveRouteOut(
            id=str(active_route_row.id),
            status=active_route_row.status.value,
            started_at=active_route_row.started_at,
            stops_total=total_stops,
            stops_done=done_stops,
        )

    recent_route_rows = (await db.execute(
        select(Route)
        .where(
            Route.driver_id == uid,
            Route.status.in_([RouteStatus.completed, RouteStatus.cancelled]),
        )
        .order_by(Route.created_at.desc())
        .limit(5)
    )).scalars().all()

    recent_routes = []
    for rt in recent_route_rows:
        t = (await db.execute(
            select(func.count()).where(RouteStop.route_id == rt.id)
        )).scalar_one()
        dn = (await db.execute(
            select(func.count()).where(
                RouteStop.route_id == rt.id,
                RouteStop.status.in_([StopStatus.delivered, StopStatus.failed, StopStatus.skipped]),
            )
        )).scalar_one()
        recent_routes.append(RecentRouteOut(
            id=str(rt.id), status=rt.status.value,
            created_at=rt.created_at, stops_total=t, stops_done=dn,
        ))

    return DriverDetailOut(
        user_id=str(d.user_id),
        full_name=u.full_name,
        email=str(u.email) if u.email else None,
        phone=u.phone,
        status=d.status.value,
        account_active=u.is_active,
        vehicle=VehicleOut(
            id=str(v.id),
            type=v.type.value,
            registration_number=v.registration_number,
            max_weight_kg=float(v.max_weight_kg),
            max_volume_m3=float(v.max_volume_m3),
        ) if v else None,
        created_at=d.created_at,
        last_login_at=u.last_login_at,
        stats=DriverStatsOut(
            completed_deliveries=stats_row.completed,
            failed_stops=stats_row.failed,
        ),
        active_route=active_route,
        recent_routes=recent_routes,
    )


# ---------------------------------------------------------------------------
# POST /drivers/{user_id}/verify
# ---------------------------------------------------------------------------

class DriverVerifyOut(BaseModel):
    user_id: str
    status: str

    model_config = {"extra": "forbid"}


@router.post("/drivers/{user_id}/verify", response_model=DriverVerifyOut)
async def verify_driver(
    request: Request,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> DriverVerifyOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    result = await db.execute(
        update(Driver)
        .where(
            Driver.user_id == uid,
            Driver.status.in_([DriverStatus.pending, DriverStatus.rejected]),
        )
        .values(status=DriverStatus.offline, updated_at=datetime.now(timezone.utc))
        .returning(Driver.user_id, Driver.status)
    )
    row = result.first()
    if row is None:
        existing = await db.scalar(select(Driver).where(Driver.user_id == uid))
        if existing is None:
            raise _404()
        raise _409(
            f"Driver is already in status '{existing.status.value}'; cannot verify.",
            "invalid_state", {"current": existing.status.value},
        )

    user = await db.get(User, uid)
    await write_audit(
        db, actor=actor, action="driver.verify",
        target_type="driver", target_id=uid,
        target_label=user.full_name if user else str(uid),
        ip=get_client_ip(request),
    )
    await db.commit()

    if user and user.email:
        await send_driver_approved(str(user.email), user.full_name)

    return DriverVerifyOut(user_id=str(uid), status="offline")


# ---------------------------------------------------------------------------
# POST /drivers/{user_id}/reject
# ---------------------------------------------------------------------------

class RejectBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=200)

    model_config = {"extra": "forbid"}


@router.post("/drivers/{user_id}/reject", response_model=DriverVerifyOut)
async def reject_driver(
    request: Request,
    body: RejectBody,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> DriverVerifyOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    result = await db.execute(
        update(Driver)
        .where(Driver.user_id == uid, Driver.status == DriverStatus.pending)
        .values(status=DriverStatus.rejected, updated_at=datetime.now(timezone.utc))
        .returning(Driver.user_id)
    )
    row = result.first()
    if row is None:
        existing = await db.scalar(select(Driver).where(Driver.user_id == uid))
        if existing is None:
            raise _404()
        raise _409(
            f"Driver is in status '{existing.status.value}'; only pending drivers can be rejected.",
            "invalid_state", {"current": existing.status.value},
        )

    user = await db.get(User, uid)
    details: Dict[str, Any] = {}
    if body.reason:
        details["reason"] = body.reason

    await write_audit(
        db, actor=actor, action="driver.reject",
        target_type="driver", target_id=uid,
        target_label=user.full_name if user else str(uid),
        details=details, ip=get_client_ip(request),
    )
    await db.commit()

    if user and user.email:
        await send_driver_rejected(str(user.email), user.full_name, body.reason)

    return DriverVerifyOut(user_id=str(uid), status="rejected")


# ---------------------------------------------------------------------------
# POST /drivers/bulk
# ---------------------------------------------------------------------------

class BulkDriverBody(BaseModel):
    action: Literal["verify", "reject"]
    user_ids: List[str] = Field(..., min_length=1, max_length=50)
    reason: Optional[str] = Field(None, max_length=200)

    model_config = {"extra": "forbid"}

    @field_validator("user_ids")
    @classmethod
    def unique_ids(cls, v: List[str]) -> List[str]:
        if len(set(v)) != len(v):
            raise ValueError("user_ids must be unique")
        return v


class BulkResultItem(BaseModel):
    user_id: str
    ok: bool
    code: Optional[str] = None

    model_config = {"extra": "forbid"}


class BulkDriverOut(BaseModel):
    results: List[BulkResultItem]

    model_config = {"extra": "forbid"}


@router.post("/drivers/bulk", response_model=BulkDriverOut)
async def bulk_driver_action(
    request: Request,
    body: BulkDriverBody,
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> BulkDriverOut:
    results: List[BulkResultItem] = []
    pending_notifications: List[Dict[str, Any]] = []
    ip = get_client_ip(request)

    # 1. Execute database mutations and audit logs in isolated savepoints
    for uid_str in body.user_ids:
        try:
            uid = _uuid.UUID(uid_str)
        except ValueError:
            results.append(BulkResultItem(user_id=uid_str, ok=False, code="validation_error"))
            continue

        try:
            async with db.begin_nested():
                if body.action == "verify":
                    res = await db.execute(
                        update(Driver)
                        .where(
                            Driver.user_id == uid,
                            Driver.status.in_([DriverStatus.pending, DriverStatus.rejected]),
                        )
                        .values(status=DriverStatus.offline, updated_at=datetime.now(timezone.utc))
                        .returning(Driver.user_id)
                    )
                    if res.first() is None:
                        existing = await db.scalar(select(Driver).where(Driver.user_id == uid))
                        code = "not_found" if existing is None else "invalid_state"
                        results.append(BulkResultItem(user_id=uid_str, ok=False, code=code))
                        continue
                    action_name = "driver.verify"
                else:  # reject
                    res = await db.execute(
                        update(Driver)
                        .where(Driver.user_id == uid, Driver.status == DriverStatus.pending)
                        .values(status=DriverStatus.rejected, updated_at=datetime.now(timezone.utc))
                        .returning(Driver.user_id)
                    )
                    if res.first() is None:
                        existing = await db.scalar(select(Driver).where(Driver.user_id == uid))
                        code = "not_found" if existing is None else "invalid_state"
                        results.append(BulkResultItem(user_id=uid_str, ok=False, code=code))
                        continue
                    action_name = "driver.reject"

                user = await db.get(User, uid)
                details: Dict[str, Any] = {}
                if body.reason:
                    details["reason"] = body.reason
                await write_audit(
                    db, actor=actor, action=action_name,
                    target_type="driver", target_id=uid,
                    target_label=user.full_name if user else str(uid),
                    details=details, ip=ip,
                )

            # Mark item successful in DB and stage notification for post-commit dispatch
            results.append(BulkResultItem(user_id=uid_str, ok=True))
            if user and user.email:
                pending_notifications.append({
                    "user_id": str(uid),
                    "email": str(user.email),
                    "full_name": user.full_name,
                    "action": body.action,
                    "reason": body.reason,
                })

        except Exception:
            logger.exception("bulk_driver_action DB update failed for %s", uid_str)
            results.append(BulkResultItem(user_id=uid_str, ok=False, code="internal_error"))

    # 2. Durable commit: driver mutations and audit records committed first
    await db.commit()

    # 3. Post-commit email dispatch — same path as single-driver endpoints.
    #    Never raises: failures are logged but do not affect the 2xx response.
    for notif in pending_notifications:
        try:
            if notif["action"] == "verify":
                await send_driver_approved(notif["email"], notif["full_name"])
            else:
                await send_driver_rejected(notif["email"], notif["full_name"], notif["reason"])
        except Exception:
            logger.exception("Bulk notification email failed for driver %s", notif["user_id"])

    return BulkDriverOut(results=results)

