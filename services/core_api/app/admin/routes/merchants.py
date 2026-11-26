# admin/routes/merchants.py  — §7.4 Merchants
from __future__ import annotations

import logging
import re
import secrets
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import (
    Merchant,
    MerchantMember,
    Order,
    OrderStatus,
    User,
    UserRole,
    UserRole_,
)
from services.core_api.app.admin.audit import write_audit
from services.core_api.app.admin.common import (
    _404,
    _409,
    _422,
    _issue_invite_token,
)
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.admin.emails import (
    send_merchant_access_notify,
    send_merchant_owner_invite,
)
from services.core_api.app.admin.rules import (
    MERCHANT_SORT_COLS,
    prepare_q,
    validate_dir,
    validate_sort,
)
from services.core_api.app.admin.security import get_client_ip
from services.core_api.app.auth.security import hash_password
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class MerchantListItem(BaseModel):
    id: str
    name: str
    contact_email: Optional[str]
    contact_phone: Optional[str]
    is_active: bool
    member_count: int
    orders_total: int
    orders_30d: int
    created_at: datetime

    model_config = {"extra": "forbid"}


class MerchantCounts(BaseModel):
    all: int
    active: int
    inactive: int

    model_config = {"extra": "forbid"}


class MerchantListOut(BaseModel):
    items: List[MerchantListItem]
    total: int
    page: int
    page_size: int
    counts: MerchantCounts

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# GET /merchants
# ---------------------------------------------------------------------------


@router.get("/merchants", response_model=MerchantListOut)
async def list_merchants(
    q: Optional[str] = Query(None, max_length=100),
    status: Optional[Literal["all", "active", "inactive"]] = Query("all"),
    sort: str = Query("name"),
    dir: str = Query("asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> MerchantListOut:
    try:
        validate_sort(sort, MERCHANT_SORT_COLS)
        validate_dir(dir)
    except ValueError as e:
        raise _422(str(e))

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    counts_row = (await db.execute(
        select(
            func.count().label("all"),
            func.count().filter(Merchant.is_active == True).label("active"),
            func.count().filter(Merchant.is_active == False).label("inactive"),
        ).select_from(Merchant)
    )).one()

    member_subq = (
        select(func.count()).where(MerchantMember.merchant_id == Merchant.id)
        .correlate(Merchant).scalar_subquery()
    )
    total_orders_subq = (
        select(func.count()).where(Order.merchant_id == Merchant.id)
        .correlate(Merchant).scalar_subquery()
    )
    orders_30d_subq = (
        select(func.count())
        .where(Order.merchant_id == Merchant.id, Order.created_at >= thirty_days_ago)
        .correlate(Merchant).scalar_subquery()
    )

    base = select(
        Merchant,
        member_subq.label("member_count"),
        total_orders_subq.label("orders_total"),
        orders_30d_subq.label("orders_30d"),
    )

    q_pat = prepare_q(q)
    if q_pat:
        base = base.where(
            or_(Merchant.name.ilike(q_pat), Merchant.contact_email.ilike(q_pat))
        )

    if status == "active":
        base = base.where(Merchant.is_active == True)
    elif status == "inactive":
        base = base.where(Merchant.is_active == False)

    sort_col_map = {
        "name": Merchant.name,
        "created_at": Merchant.created_at,
        "orders_total": total_orders_subq,
    }
    sort_col = sort_col_map[sort]
    order_expr = sort_col.asc() if dir == "asc" else sort_col.desc()

    total_row = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_row.scalar_one()

    rows = (await db.execute(base.order_by(order_expr, Merchant.id.asc()).offset((page - 1) * page_size).limit(page_size))).all()

    items = [
        MerchantListItem(
            id=str(r.Merchant.id), name=r.Merchant.name,
            contact_email=str(r.Merchant.contact_email) if r.Merchant.contact_email else None,
            contact_phone=r.Merchant.contact_phone,
            is_active=r.Merchant.is_active,
            member_count=r.member_count, orders_total=r.orders_total, orders_30d=r.orders_30d,
            created_at=r.Merchant.created_at,
        )
        for r in rows
    ]
    return MerchantListOut(
        items=items, total=total, page=page, page_size=page_size,
        counts=MerchantCounts(all=counts_row.all, active=counts_row.active, inactive=counts_row.inactive),
    )


# ---------------------------------------------------------------------------
# GET /merchants/{merchant_id}
# ---------------------------------------------------------------------------


class MerchantMemberOut(BaseModel):
    user_id: str
    full_name: str
    email: Optional[str]
    account_active: bool

    model_config = {"extra": "forbid"}


class MerchantRecentOrder(BaseModel):
    tracking_token: str
    merchant_order_ref: str
    status: str
    created_at: datetime

    model_config = {"extra": "forbid"}


class MerchantDetailOut(BaseModel):
    id: str
    name: str
    contact_email: Optional[str]
    contact_phone: Optional[str]
    is_active: bool
    member_count: int
    orders_total: int
    orders_30d: int
    created_at: datetime
    members: List[MerchantMemberOut]
    orders_by_status: Dict[str, int]
    recent_orders: List[MerchantRecentOrder]

    model_config = {"extra": "forbid"}


@router.get("/merchants/{merchant_id}", response_model=MerchantDetailOut)
async def get_merchant(
    merchant_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> MerchantDetailOut:
    try:
        mid = _uuid.UUID(merchant_id)
    except ValueError:
        raise _422("Invalid UUID.", "merchant_id")

    m = await db.get(Merchant, mid)
    if m is None:
        raise _404()

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    member_rows = (await db.execute(
        select(User).join(MerchantMember, MerchantMember.user_id == User.id)
        .where(MerchantMember.merchant_id == mid)
    )).scalars().all()

    obs_rows = (await db.execute(
        select(Order.status, func.count().label("cnt"))
        .where(Order.merchant_id == mid)
        .group_by(Order.status)
    )).all()
    orders_by_status: Dict[str, int] = {s.value: 0 for s in OrderStatus}
    for s, c in obs_rows:
        orders_by_status[s.value] = c

    total_orders = sum(orders_by_status.values())
    orders_30d = (await db.execute(
        select(func.count()).where(Order.merchant_id == mid, Order.created_at >= thirty_days_ago)
    )).scalar_one()

    recent_orders = (await db.execute(
        select(Order).where(Order.merchant_id == mid)
        .order_by(Order.created_at.desc()).limit(10)
    )).scalars().all()

    return MerchantDetailOut(
        id=str(m.id), name=m.name,
        contact_email=str(m.contact_email) if m.contact_email else None,
        contact_phone=m.contact_phone,
        is_active=m.is_active,
        member_count=len(member_rows),
        orders_total=total_orders, orders_30d=orders_30d,
        created_at=m.created_at,
        members=[
            MerchantMemberOut(
                user_id=str(u.id), full_name=u.full_name,
                email=str(u.email) if u.email else None,
                account_active=u.is_active,
            )
            for u in member_rows
        ],
        orders_by_status=orders_by_status,
        recent_orders=[
            MerchantRecentOrder(
                tracking_token=o.tracking_token,
                merchant_order_ref=o.merchant_order_ref,
                status=o.status.value, created_at=o.created_at,
            )
            for o in recent_orders
        ],
    )


# ---------------------------------------------------------------------------
# POST /merchants  (create)
# ---------------------------------------------------------------------------


class CreateMerchantBody(BaseModel):
    name: str = Field(..., max_length=200)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=20)
    owner_email: EmailStr
    owner_full_name: str = Field(..., max_length=200)

    model_config = {"extra": "forbid"}

    @field_validator("contact_phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^\+[1-9][0-9]{7,14}$", v):
            raise ValueError("contact_phone must be E.164 format (e.g. +12125551234)")
        return v


class OwnerInfo(BaseModel):
    user_id: str
    created: bool

    model_config = {"extra": "forbid"}


class CreateMerchantOut(BaseModel):
    merchant: MerchantListItem
    owner: OwnerInfo
    invite_sent: bool

    model_config = {"extra": "forbid"}


@router.post("/merchants", response_model=CreateMerchantOut, status_code=201)
async def create_merchant(
    request: Request,
    body: CreateMerchantBody,
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> CreateMerchantOut:
    m = Merchant(
        name=body.name,
        contact_email=body.contact_email,
        contact_phone=body.contact_phone,
    )
    db.add(m)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        constraint = str(getattr(exc.orig, "constraint_name", "") or "") or str(exc)
        if "uq_merchants_name_ci" in constraint or "merchants_name" in constraint:
            raise _409(f"A merchant named '{body.name}' already exists.", "name_exists")
        if "merchants_contact_phone_format" in constraint:
            raise _422("contact_phone must be E.164 format.", "contact_phone")
        raise _409("A conflict occurred creating the merchant.", "conflict")

    owner_user = await db.scalar(select(User).options(selectinload(User.roles)).where(User.email == body.owner_email))
    user_created = False
    raw_invite_token: Optional[str] = None

    if owner_user is None:
        unusable_hash = hash_password(secrets.token_urlsafe(32))
        owner_user = User(
            email=body.owner_email,
            password_hash=unusable_hash,
            full_name=body.owner_full_name,
        )
        db.add(owner_user)
        await db.flush()
        user_created = True
    else:
        if not owner_user.is_active:
            raise _409("The owner account is deactivated.", "owner_inactive")

    existing_role = await db.scalar(
        select(UserRole_).where(
            UserRole_.user_id == owner_user.id,
            UserRole_.role == UserRole.merchant,
        )
    )
    if existing_role is None:
        db.add(UserRole_(user_id=owner_user.id, role=UserRole.merchant, granted_by=actor.id))

    existing_member = await db.scalar(
        select(MerchantMember).where(
            MerchantMember.user_id == owner_user.id,
            MerchantMember.merchant_id == m.id,
        )
    )
    if existing_member is None:
        db.add(MerchantMember(user_id=owner_user.id, merchant_id=m.id))

    if user_created:
        raw_invite_token = await _issue_invite_token(owner_user, db)

    await write_audit(
        db, actor=actor, action="merchant.create",
        target_type="merchant", target_id=m.id, target_label=m.name,
        ip=get_client_ip(request),
    )
    await db.commit()

    invite_sent = False
    if user_created and raw_invite_token and owner_user.email:
        try:
            invite_sent = await send_merchant_owner_invite(
                to_address=str(owner_user.email),
                full_name=owner_user.full_name,
                merchant_name=body.name,
                reset_token=raw_invite_token,
            )
        except Exception:
            logger.exception("merchant owner invite email failed")
    elif not user_created and owner_user.email:
        try:
            await send_merchant_access_notify(
                to_address=str(owner_user.email),
                full_name=owner_user.full_name,
                merchant_name=body.name,
            )
        except Exception:
            logger.exception("merchant access notify email failed")

    return CreateMerchantOut(
        merchant=MerchantListItem(
            id=str(m.id), name=m.name,
            contact_email=str(m.contact_email) if m.contact_email else None,
            contact_phone=m.contact_phone,
            is_active=m.is_active, member_count=1,
            orders_total=0, orders_30d=0, created_at=m.created_at,
        ),
        owner=OwnerInfo(user_id=str(owner_user.id), created=user_created),
        invite_sent=invite_sent,
    )


# ---------------------------------------------------------------------------
# PATCH /merchants/{merchant_id}
# ---------------------------------------------------------------------------


class PatchMerchantBody(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    contact_email: Optional[EmailStr] = None
    contact_phone: Optional[str] = Field(None, max_length=20)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def at_least_one_field(self) -> "PatchMerchantBody":
        if self.name is None and self.contact_email is None and self.contact_phone is None:
            raise ValueError("At least one field required.")
        return self

    @field_validator("contact_phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not re.match(r"^\+[1-9][0-9]{7,14}$", v):
            raise ValueError("contact_phone must be E.164 format (e.g. +12125551234)")
        return v


@router.patch("/merchants/{merchant_id}", response_model=MerchantListItem)
async def update_merchant(
    request: Request,
    body: PatchMerchantBody,
    merchant_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> MerchantListItem:
    try:
        mid = _uuid.UUID(merchant_id)
    except ValueError:
        raise _422("Invalid UUID.", "merchant_id")

    m = await db.get(Merchant, mid)
    if m is None:
        raise _404()

    before: Dict[str, Any] = {}
    after: Dict[str, Any] = {}

    if body.name is not None and body.name != m.name:
        before["name"] = m.name
        after["name"] = body.name
        m.name = body.name

    if body.contact_email is not None and str(body.contact_email) != str(m.contact_email or ""):
        before["contact_email"] = str(m.contact_email) if m.contact_email else None
        after["contact_email"] = str(body.contact_email)
        m.contact_email = str(body.contact_email)

    if body.contact_phone is not None and body.contact_phone != m.contact_phone:
        before["contact_phone"] = m.contact_phone
        after["contact_phone"] = body.contact_phone
        m.contact_phone = body.contact_phone

    m.updated_at = datetime.now(timezone.utc)

    # Skip audit and commit when nothing actually changed
    if not before:
        return MerchantListItem(
            id=str(m.id), name=m.name,
            contact_email=str(m.contact_email) if m.contact_email else None,
            contact_phone=m.contact_phone,
            is_active=m.is_active, member_count=0,
            orders_total=0, orders_30d=0, created_at=m.created_at,
        )

    await write_audit(
        db, actor=actor, action="merchant.update",
        target_type="merchant", target_id=mid, target_label=m.name,
        details={"before": before, "after": after},
        ip=get_client_ip(request),
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        constraint = str(getattr(exc.orig, "constraint_name", "") or "") or str(exc)
        if "uq_merchants_name_ci" in constraint or "merchants_name" in constraint:
            raise _409(f"A merchant named '{body.name}' already exists.", "name_exists")
        if "merchants_contact_phone_format" in constraint:
            raise _422("contact_phone must be E.164 format.", "contact_phone")
        raise _409("A conflict occurred updating the merchant.", "conflict")

    total_orders = (await db.execute(select(func.count()).where(Order.merchant_id == mid))).scalar_one()
    member_count = (await db.execute(select(func.count()).where(MerchantMember.merchant_id == mid))).scalar_one()
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    orders_30d = (await db.execute(
        select(func.count()).where(Order.merchant_id == mid, Order.created_at >= thirty_days_ago)
    )).scalar_one()

    return MerchantListItem(
        id=str(m.id), name=m.name,
        contact_email=str(m.contact_email) if m.contact_email else None,
        contact_phone=m.contact_phone,
        is_active=m.is_active, member_count=member_count,
        orders_total=total_orders, orders_30d=orders_30d, created_at=m.created_at,
    )


# ---------------------------------------------------------------------------
# POST /merchants/{merchant_id}/deactivate
# POST /merchants/{merchant_id}/reactivate
# ---------------------------------------------------------------------------


def _merchant_list_item(m: Merchant, mc: int, total: int, thirty: int) -> MerchantListItem:
    return MerchantListItem(
        id=str(m.id), name=m.name,
        contact_email=str(m.contact_email) if m.contact_email else None,
        contact_phone=m.contact_phone,
        is_active=m.is_active, member_count=mc,
        orders_total=total, orders_30d=thirty, created_at=m.created_at,
    )


async def _merchant_stats(mid: _uuid.UUID, db: AsyncSession):
    """Return (total_orders, member_count, orders_30d) for a merchant."""
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    total = (await db.execute(select(func.count()).where(Order.merchant_id == mid))).scalar_one()
    mc = (await db.execute(select(func.count()).where(MerchantMember.merchant_id == mid))).scalar_one()
    thirty = (await db.execute(
        select(func.count()).where(Order.merchant_id == mid, Order.created_at >= thirty_days_ago)
    )).scalar_one()
    return total, mc, thirty


@router.post("/merchants/{merchant_id}/deactivate", response_model=MerchantListItem)
async def deactivate_merchant(
    request: Request,
    merchant_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> MerchantListItem:
    try:
        mid = _uuid.UUID(merchant_id)
    except ValueError:
        raise _422("Invalid UUID.", "merchant_id")

    m = await db.get(Merchant, mid)
    if m is None:
        raise _404()

    total, mc, thirty = await _merchant_stats(mid, db)

    if not m.is_active:
        return _merchant_list_item(m, mc, total, thirty)

    m.is_active = False
    m.updated_at = datetime.now(timezone.utc)
    await write_audit(db, actor=actor, action="merchant.deactivate",
        target_type="merchant", target_id=mid, target_label=m.name, ip=get_client_ip(request))
    await db.commit()

    # TODO: Order-intake must reject orders for inactive merchants.
    total, mc, thirty = await _merchant_stats(mid, db)
    return _merchant_list_item(m, mc, total, thirty)


@router.post("/merchants/{merchant_id}/reactivate", response_model=MerchantListItem)
async def reactivate_merchant(
    request: Request,
    merchant_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> MerchantListItem:
    try:
        mid = _uuid.UUID(merchant_id)
    except ValueError:
        raise _422("Invalid UUID.", "merchant_id")

    m = await db.get(Merchant, mid)
    if m is None:
        raise _404()

    total, mc, thirty = await _merchant_stats(mid, db)

    if m.is_active:
        return _merchant_list_item(m, mc, total, thirty)

    m.is_active = True
    m.updated_at = datetime.now(timezone.utc)
    await write_audit(db, actor=actor, action="merchant.reactivate",
        target_type="merchant", target_id=mid, target_label=m.name, ip=get_client_ip(request))
    await db.commit()

    total, mc, thirty = await _merchant_stats(mid, db)
    return _merchant_list_item(m, mc, total, thirty)
