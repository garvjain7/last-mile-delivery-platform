# admin/routes/warehouses.py  — §7.5 Warehouses
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import (
    Order,
    OrderStatus,
    Route,
    RouteStatus,
    RouteStop,
    StopStatus,
    User,
    UserRole,
    UserRole_,
    Warehouse,
    WarehouseStaff,
)
from services.core_api.app.admin.audit import write_audit
from services.core_api.app.admin.common import _404, _409, _422
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.admin.rules import (
    WAREHOUSE_SORT_COLS,
    prepare_q,
    validate_coordinates,
    validate_dir,
    validate_sort,
    validate_warehouse_code,
)
from services.core_api.app.admin.security import get_client_ip
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Shared sub-queries
# ---------------------------------------------------------------------------


def _wh_open_orders_subq():
    return (
        select(func.count()).where(
            Order.warehouse_id == Warehouse.id,
            Order.status.in_([OrderStatus.pending, OrderStatus.assigned,
                               OrderStatus.out_for_delivery, OrderStatus.attempt_failed])
        ).correlate(Warehouse).scalar_subquery()
    )


def _wh_active_routes_subq():
    return (
        select(func.count()).where(
            Route.warehouse_id == Warehouse.id,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress])
        ).correlate(Warehouse).scalar_subquery()
    )


def _wh_staff_count_subq():
    return (
        select(func.count()).where(
            WarehouseStaff.warehouse_id == Warehouse.id
        ).correlate(Warehouse).scalar_subquery()
    )


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class WarehouseListItem(BaseModel):
    id: str
    code: str
    name: str
    address: str
    latitude: float
    longitude: float
    is_active: bool
    staff_count: int
    open_orders: int
    active_routes: int
    created_at: datetime

    model_config = {"extra": "forbid"}


class WarehouseCounts(BaseModel):
    all: int
    active: int
    inactive: int

    model_config = {"extra": "forbid"}


class WarehouseListOut(BaseModel):
    items: List[WarehouseListItem]
    total: int
    page: int
    page_size: int
    counts: WarehouseCounts

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# GET /warehouses
# ---------------------------------------------------------------------------


@router.get("/warehouses", response_model=WarehouseListOut)
async def list_warehouses(
    q: Optional[str] = Query(None, max_length=100),
    status: Optional[Literal["all", "active", "inactive"]] = Query("all"),
    sort: str = Query("code"),
    dir: str = Query("asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> WarehouseListOut:
    try:
        validate_sort(sort, WAREHOUSE_SORT_COLS)
        validate_dir(dir)
    except ValueError as e:
        raise _422(str(e))

    counts_row = (await db.execute(
        select(
            func.count().label("all"),
            func.count().filter(Warehouse.is_active == True).label("active"),
            func.count().filter(Warehouse.is_active == False).label("inactive"),
        ).select_from(Warehouse)
    )).one()

    open_orders_subq = _wh_open_orders_subq()
    active_routes_subq = _wh_active_routes_subq()
    staff_count_subq = _wh_staff_count_subq()

    base = select(
        Warehouse,
        text("ST_Y(location::geometry)").label("lat"),
        text("ST_X(location::geometry)").label("lon"),
        staff_count_subq.label("staff_count"),
        open_orders_subq.label("open_orders"),
        active_routes_subq.label("active_routes"),
    )

    q_pat = prepare_q(q)
    if q_pat:
        base = base.where(
            or_(Warehouse.code.ilike(q_pat), Warehouse.name.ilike(q_pat), Warehouse.address.ilike(q_pat))
        )

    if status == "active":
        base = base.where(Warehouse.is_active == True)
    elif status == "inactive":
        base = base.where(Warehouse.is_active == False)

    sort_col_map = {
        "code": Warehouse.code,
        "name": Warehouse.name,
        "open_orders": open_orders_subq,
        "created_at": Warehouse.created_at,
    }
    sort_col = sort_col_map[sort]
    order_expr = sort_col.asc() if dir == "asc" else sort_col.desc()

    total_row = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_row.scalar_one()

    rows = (await db.execute(base.order_by(order_expr, Warehouse.id.asc()).offset((page - 1) * page_size).limit(page_size))).all()

    items = [
        WarehouseListItem(
            id=str(r.Warehouse.id), code=r.Warehouse.code, name=r.Warehouse.name,
            address=r.Warehouse.address, latitude=float(r.lat), longitude=float(r.lon),
            is_active=r.Warehouse.is_active,
            staff_count=r.staff_count, open_orders=r.open_orders, active_routes=r.active_routes,
            created_at=r.Warehouse.created_at,
        )
        for r in rows
    ]
    return WarehouseListOut(
        items=items, total=total, page=page, page_size=page_size,
        counts=WarehouseCounts(all=counts_row.all, active=counts_row.active, inactive=counts_row.inactive),
    )


# ---------------------------------------------------------------------------
# GET /warehouses/{warehouse_id}
# ---------------------------------------------------------------------------


class WhStaffOut(BaseModel):
    user_id: str
    full_name: str
    email: Optional[str]
    roles: List[str]

    model_config = {"extra": "forbid"}


class WhActiveRouteOut(BaseModel):
    id: str
    driver_name: str
    status: str
    stops_total: int
    stops_done: int

    model_config = {"extra": "forbid"}


class WarehouseDetailOut(BaseModel):
    id: str
    code: str
    name: str
    address: str
    latitude: float
    longitude: float
    is_active: bool
    staff_count: int
    open_orders: int
    active_routes: int
    created_at: datetime
    staff: List[WhStaffOut]
    orders_by_status: Dict[str, int]
    active_route_list: List[WhActiveRouteOut]

    model_config = {"extra": "forbid"}


@router.get("/warehouses/{warehouse_id}", response_model=WarehouseDetailOut)
async def get_warehouse(
    warehouse_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> WarehouseDetailOut:
    try:
        wid = _uuid.UUID(warehouse_id)
    except ValueError:
        raise _422("Invalid UUID.", "warehouse_id")

    row = (await db.execute(
        select(
            Warehouse,
            text("ST_Y(location::geometry)").label("lat"),
            text("ST_X(location::geometry)").label("lon"),
        ).where(Warehouse.id == wid)
    )).first()

    if row is None:
        raise _404()
    wh, lat, lon = row.Warehouse, row.lat, row.lon

    staff_rows = (await db.execute(
        select(User)
        .options(selectinload(User.roles))
        .join(WarehouseStaff, WarehouseStaff.user_id == User.id)
        .where(WarehouseStaff.warehouse_id == wid)
    )).scalars().all()

    obs_rows = (await db.execute(
        select(Order.status, func.count().label("cnt"))
        .where(Order.warehouse_id == wid)
        .group_by(Order.status)
    )).all()
    orders_by_status: Dict[str, int] = {s.value: 0 for s in OrderStatus}
    for s, c in obs_rows:
        orders_by_status[s.value] = c

    open_orders_count = sum(
        orders_by_status.get(s, 0)
        for s in ("pending", "assigned", "out_for_delivery", "attempt_failed")
    )

    active_routes_rows = (await db.execute(
        select(Route, User.full_name.label("driver_name"))
        .join(User, User.id == Route.driver_id)
        .where(
            Route.warehouse_id == wid,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress]),
        )
    )).all()

    active_route_list = []
    for rt, dname in active_routes_rows:
        t = (await db.execute(select(func.count()).where(RouteStop.route_id == rt.id))).scalar_one()
        dn = (await db.execute(
            select(func.count()).where(
                RouteStop.route_id == rt.id,
                RouteStop.status.in_([StopStatus.delivered, StopStatus.failed, StopStatus.skipped]),
            )
        )).scalar_one()
        active_route_list.append(WhActiveRouteOut(
            id=str(rt.id), driver_name=dname, status=rt.status.value,
            stops_total=t, stops_done=dn,
        ))

    return WarehouseDetailOut(
        id=str(wh.id), code=wh.code, name=wh.name, address=wh.address,
        latitude=float(lat), longitude=float(lon), is_active=wh.is_active,
        staff_count=len(staff_rows), open_orders=open_orders_count,
        active_routes=len(active_route_list), created_at=wh.created_at,
        staff=[
            WhStaffOut(
                user_id=str(u.id), full_name=u.full_name,
                email=str(u.email) if u.email else None,
                roles=[r.role.value for r in u.roles],
            )
            for u in staff_rows
        ],
        orders_by_status=orders_by_status,
        active_route_list=active_route_list,
    )


# ---------------------------------------------------------------------------
# POST /warehouses  (create)
# ---------------------------------------------------------------------------


class CreateWarehouseBody(BaseModel):
    code: str = Field(..., max_length=12)
    name: str = Field(..., max_length=120)
    address: str = Field(..., max_length=300)
    latitude: float
    longitude: float

    model_config = {"extra": "forbid"}


@router.post("/warehouses", response_model=WarehouseListItem, status_code=201)
async def create_warehouse(
    request: Request,
    body: CreateWarehouseBody,
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> WarehouseListItem:
    try:
        code = validate_warehouse_code(body.code)
        validate_coordinates(body.latitude, body.longitude)
    except ValueError as e:
        raise _422(str(e), "code" if "code" in str(e) else "latitude")

    location_wkt = f"SRID=4326;POINT({body.longitude} {body.latitude})"

    wh = Warehouse(
        code=code, name=body.name, address=body.address,
        location=location_wkt,
    )
    db.add(wh)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        constraint = str(getattr(exc.orig, "constraint_name", "") or "") or str(exc)
        if "warehouses_code_key" in constraint or "uq" in constraint.lower() or "unique" in constraint.lower():
            raise _409(f"Warehouse code '{code}' already exists.", "warehouse_code_exists")
        raise _409("A conflict occurred creating the warehouse.", "conflict")

    await write_audit(
        db, actor=actor, action="warehouse.create",
        target_type="warehouse", target_id=wh.id, target_label=wh.code,
        ip=get_client_ip(request),
    )
    await db.commit()

    return WarehouseListItem(
        id=str(wh.id), code=wh.code, name=wh.name, address=wh.address,
        latitude=body.latitude, longitude=body.longitude,
        is_active=wh.is_active, staff_count=0, open_orders=0, active_routes=0,
        created_at=wh.created_at,
    )


# ---------------------------------------------------------------------------
# PATCH /warehouses/{warehouse_id}
# ---------------------------------------------------------------------------


class PatchWarehouseBody(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    address: Optional[str] = Field(None, max_length=300)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    code: Optional[str] = None  # Always rejected

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_patch(self) -> "PatchWarehouseBody":
        if self.code is not None:
            raise ValueError("code is immutable and cannot be changed.")
        has_lat = self.latitude is not None
        has_lon = self.longitude is not None
        if has_lat != has_lon:
            raise ValueError("latitude and longitude must be provided together.")
        if self.name is None and self.address is None and self.latitude is None:
            raise ValueError("At least one field required.")
        return self


@router.patch("/warehouses/{warehouse_id}", response_model=WarehouseListItem)
async def update_warehouse(
    request: Request,
    body: PatchWarehouseBody,
    warehouse_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> WarehouseListItem:
    try:
        wid = _uuid.UUID(warehouse_id)
    except ValueError:
        raise _422("Invalid UUID.", "warehouse_id")

    row = (await db.execute(
        select(
            Warehouse,
            text("ST_Y(location::geometry)").label("lat"),
            text("ST_X(location::geometry)").label("lon"),
        ).where(Warehouse.id == wid)
    )).first()
    if row is None:
        raise _404()

    wh, cur_lat, cur_lon = row.Warehouse, row.lat, row.lon
    before: Dict[str, Any] = {}
    after: Dict[str, Any] = {}

    if body.name is not None and body.name != wh.name:
        before["name"] = wh.name
        after["name"] = body.name
        wh.name = body.name

    if body.address is not None and body.address != wh.address:
        before["address"] = wh.address
        after["address"] = body.address
        wh.address = body.address

    if body.latitude is not None:
        try:
            validate_coordinates(body.latitude, body.longitude)
        except ValueError as e:
            raise _422(str(e))
        before["latitude"] = float(cur_lat)
        before["longitude"] = float(cur_lon)
        after["latitude"] = body.latitude
        after["longitude"] = body.longitude
        wh.location = f"SRID=4326;POINT({body.longitude} {body.latitude})"
        cur_lat, cur_lon = body.latitude, body.longitude

    wh.updated_at = datetime.now(timezone.utc)

    # Skip audit and commit when nothing actually changed
    if not before:
        staff_count = (await db.execute(select(func.count()).where(WarehouseStaff.warehouse_id == wid))).scalar_one()
        open_orders = (await db.execute(
            select(func.count()).where(
                Order.warehouse_id == wid,
                Order.status.in_([OrderStatus.pending, OrderStatus.assigned,
                                   OrderStatus.out_for_delivery, OrderStatus.attempt_failed])
            )
        )).scalar_one()
        active_routes = (await db.execute(
            select(func.count()).where(
                Route.warehouse_id == wid,
                Route.status.in_([RouteStatus.planned, RouteStatus.in_progress])
            )
        )).scalar_one()
        return WarehouseListItem(
            id=str(wh.id), code=wh.code, name=wh.name, address=wh.address,
            latitude=float(cur_lat), longitude=float(cur_lon), is_active=wh.is_active,
            staff_count=staff_count, open_orders=open_orders, active_routes=active_routes,
            created_at=wh.created_at,
        )

    await write_audit(
        db, actor=actor, action="warehouse.update",
        target_type="warehouse", target_id=wid, target_label=wh.code,
        details={"before": before, "after": after}, ip=get_client_ip(request),
    )
    await db.commit()

    staff_count = (await db.execute(select(func.count()).where(WarehouseStaff.warehouse_id == wid))).scalar_one()
    open_orders = (await db.execute(
        select(func.count()).where(
            Order.warehouse_id == wid,
            Order.status.in_([OrderStatus.pending, OrderStatus.assigned,
                               OrderStatus.out_for_delivery, OrderStatus.attempt_failed])
        )
    )).scalar_one()
    active_routes = (await db.execute(
        select(func.count()).where(
            Route.warehouse_id == wid,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress])
        )
    )).scalar_one()

    return WarehouseListItem(
        id=str(wh.id), code=wh.code, name=wh.name, address=wh.address,
        latitude=float(cur_lat), longitude=float(cur_lon), is_active=wh.is_active,
        staff_count=staff_count, open_orders=open_orders, active_routes=active_routes,
        created_at=wh.created_at,
    )


# ---------------------------------------------------------------------------
# POST /warehouses/{warehouse_id}/deactivate
# POST /warehouses/{warehouse_id}/reactivate
# ---------------------------------------------------------------------------


async def _wh_fetch_row(wid: _uuid.UUID, db):
    row = (await db.execute(
        select(
            Warehouse,
            text("ST_Y(location::geometry)").label("lat"),
            text("ST_X(location::geometry)").label("lon"),
        ).where(Warehouse.id == wid)
    )).first()
    return row


async def _wh_build_item(wh: Warehouse, lat, lon, wid: _uuid.UUID, db) -> WarehouseListItem:
    staff_count = (await db.execute(select(func.count()).where(WarehouseStaff.warehouse_id == wid))).scalar_one()
    open_orders = (await db.execute(
        select(func.count()).where(
            Order.warehouse_id == wid,
            Order.status.in_([OrderStatus.pending, OrderStatus.assigned,
                               OrderStatus.out_for_delivery, OrderStatus.attempt_failed])
        )
    )).scalar_one()
    active_routes = (await db.execute(
        select(func.count()).where(
            Route.warehouse_id == wid,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress])
        )
    )).scalar_one()
    return WarehouseListItem(
        id=str(wh.id), code=wh.code, name=wh.name, address=wh.address,
        latitude=float(lat), longitude=float(lon), is_active=wh.is_active,
        staff_count=staff_count, open_orders=open_orders, active_routes=active_routes,
        created_at=wh.created_at,
    )


@router.post("/warehouses/{warehouse_id}/deactivate", response_model=WarehouseListItem)
async def deactivate_warehouse(
    request: Request,
    warehouse_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> WarehouseListItem:
    try:
        wid = _uuid.UUID(warehouse_id)
    except ValueError:
        raise _422("Invalid UUID.", "warehouse_id")

    row = await _wh_fetch_row(wid, db)
    if row is None:
        raise _404()

    wh, lat, lon = row.Warehouse, row.lat, row.lon

    open_orders = (await db.execute(
        select(func.count()).where(
            Order.warehouse_id == wid,
            Order.status.in_([OrderStatus.pending, OrderStatus.assigned,
                               OrderStatus.out_for_delivery, OrderStatus.attempt_failed])
        )
    )).scalar_one()
    if open_orders > 0:
        raise _409(f"Warehouse has {open_orders} open order(s). Resolve them first.", "warehouse_has_open_orders")

    active_routes = (await db.execute(
        select(func.count()).where(
            Route.warehouse_id == wid,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress])
        )
    )).scalar_one()
    if active_routes > 0:
        raise _409(f"Warehouse has {active_routes} active route(s). Complete them first.", "warehouse_has_active_routes")

    if not wh.is_active:
        return await _wh_build_item(wh, lat, lon, wid, db)

    wh.is_active = False
    wh.updated_at = datetime.now(timezone.utc)
    await write_audit(db, actor=actor, action="warehouse.deactivate",
        target_type="warehouse", target_id=wid, target_label=wh.code, ip=get_client_ip(request))
    await db.commit()

    # TODO: Order-intake must reject orders for inactive warehouses.
    return await _wh_build_item(wh, lat, lon, wid, db)


@router.post("/warehouses/{warehouse_id}/reactivate", response_model=WarehouseListItem)
async def reactivate_warehouse(
    request: Request,
    warehouse_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> WarehouseListItem:
    try:
        wid = _uuid.UUID(warehouse_id)
    except ValueError:
        raise _422("Invalid UUID.", "warehouse_id")

    row = await _wh_fetch_row(wid, db)
    if row is None:
        raise _404()

    wh, lat, lon = row.Warehouse, row.lat, row.lon

    if wh.is_active:
        return await _wh_build_item(wh, lat, lon, wid, db)

    wh.is_active = True
    wh.updated_at = datetime.now(timezone.utc)
    await write_audit(db, actor=actor, action="warehouse.reactivate",
        target_type="warehouse", target_id=wid, target_label=wh.code, ip=get_client_ip(request))
    await db.commit()

    return await _wh_build_item(wh, lat, lon, wid, db)


# ---------------------------------------------------------------------------
# POST /warehouses/{warehouse_id}/staff
# DELETE /warehouses/{warehouse_id}/staff/{user_id}
# ---------------------------------------------------------------------------


class AddStaffBody(BaseModel):
    user_id: str

    model_config = {"extra": "forbid"}


class StaffActionOut(BaseModel):
    user_id: str
    warehouse_id: str
    added: bool

    model_config = {"extra": "forbid"}


@router.post("/warehouses/{warehouse_id}/staff", response_model=StaffActionOut)
async def add_warehouse_staff(
    request: Request,
    body: AddStaffBody,
    warehouse_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> StaffActionOut:
    try:
        wid = _uuid.UUID(warehouse_id)
        uid = _uuid.UUID(body.user_id)
    except ValueError:
        raise _422("Invalid UUID.")

    wh = await db.get(Warehouse, wid)
    if wh is None:
        raise _404("Warehouse not found.")

    u = await db.scalar(select(User).options(selectinload(User.roles)).where(User.id == uid))
    if u is None:
        raise _404("User not found.")

    if not u.is_active:
        raise _409("User account is not active.", "user_not_staff")

    role_values = {r.role for r in u.roles}
    if UserRole.dispatcher not in role_values and UserRole.fleet_manager not in role_values:
        raise _409("User does not hold dispatcher or fleet_manager role.", "user_not_staff")

    existing = await db.scalar(
        select(WarehouseStaff).where(
            WarehouseStaff.user_id == uid, WarehouseStaff.warehouse_id == wid
        )
    )
    if existing is not None:
        return StaffActionOut(user_id=str(uid), warehouse_id=str(wid), added=False)

    db.add(WarehouseStaff(user_id=uid, warehouse_id=wid))
    await write_audit(
        db, actor=actor, action="warehouse.staff_add",
        target_type="warehouse", target_id=wid, target_label=wh.code,
        details={"user_id": str(uid), "user_name": u.full_name},
        ip=get_client_ip(request),
    )
    await db.commit()
    return StaffActionOut(user_id=str(uid), warehouse_id=str(wid), added=True)


@router.delete("/warehouses/{warehouse_id}/staff/{user_id}", response_model=StaffActionOut)
async def remove_warehouse_staff(
    request: Request,
    warehouse_id: str = Path(...),
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> StaffActionOut:
    try:
        wid = _uuid.UUID(warehouse_id)
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.")

    wh = await db.get(Warehouse, wid)
    if wh is None:
        raise _404("Warehouse not found.")
    u = await db.get(User, uid)
    if u is None:
        raise _404("User not found.")

    result = await db.execute(
        delete(WarehouseStaff).where(
            WarehouseStaff.user_id == uid, WarehouseStaff.warehouse_id == wid
        )
    )
    if result.rowcount > 0:
        await write_audit(
            db, actor=actor, action="warehouse.staff_remove",
            target_type="warehouse", target_id=wid, target_label=wh.code,
            details={"user_id": str(uid), "user_name": u.full_name},
            ip=get_client_ip(request),
        )
    await db.commit()
    return StaffActionOut(user_id=str(uid), warehouse_id=str(wid), added=False)
