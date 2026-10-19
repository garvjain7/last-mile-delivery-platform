# admin/routes/users.py  — §7.3 Users
from __future__ import annotations

import logging
import secrets
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import (
    Driver,
    DriverStatus,
    Merchant,
    MerchantMember,
    Order,
    OrderStatus,
    PasswordResetToken,
    RefreshToken,
    Route,
    RouteStatus,
    User,
    UserRole,
    UserRole_,
    Warehouse,
    WarehouseStaff,
)
from services.core_api.app.admin.audit import write_audit
from services.core_api.app.admin.common import (
    _404,
    _409,
    _422,
    _err,
    _get_user_or_404,
    _issue_invite_token,
    _lock_and_count_active_admins,
    _revoke_all_tokens,
    _step_up_check,
)
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.admin.emails import send_staff_invite
from services.core_api.app.admin.rules import (
    ASSIGNABLE_ROLES,
    USER_SORT_COLS,
    prepare_q,
    validate_dir,
    validate_sort,
)
from services.core_api.app.admin.security import get_client_ip
from services.core_api.app.auth.security import (
    generate_reset_token,
    hash_password,
    hash_reset_token,
)
from services.core_api.app.auth.service import acquire_email_cooldown, is_email_unique_violation
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class UserListItem(BaseModel):
    id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    roles: List[str]
    is_active: bool
    is_locked: bool
    locked_until: Optional[datetime]
    invited: bool
    last_login_at: Optional[datetime]
    created_at: datetime

    model_config = {"extra": "forbid"}


class UserCounts(BaseModel):
    all: int
    active: int
    inactive: int
    locked: int

    model_config = {"extra": "forbid"}


class UserListOut(BaseModel):
    items: List[UserListItem]
    total: int
    page: int
    page_size: int
    counts: UserCounts

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# GET /users
# ---------------------------------------------------------------------------


@router.get("/users", response_model=UserListOut)
async def list_users(
    q: Optional[str] = Query(None, max_length=100),
    role: Optional[str] = Query(None),
    status: Optional[Literal["all", "active", "inactive", "locked"]] = Query("all"),
    sort: str = Query("created_at"),
    dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> UserListOut:
    try:
        validate_sort(sort, USER_SORT_COLS)
        validate_dir(dir)
    except ValueError as e:
        raise _422(str(e))

    now = datetime.now(timezone.utc)

    counts_q = select(
        func.count().label("all"),
        func.count().filter(User.is_active == True).label("active"),
        func.count().filter(User.is_active == False).label("inactive"),
        func.count().filter(User.locked_until.isnot(None), User.locked_until > now).label("locked"),
    ).select_from(User)
    counts_row = (await db.execute(counts_q)).one()

    base = select(User).options(selectinload(User.roles))

    q_pat = prepare_q(q)
    if q_pat:
        base = base.where(
            or_(User.full_name.ilike(q_pat), User.email.ilike(q_pat), User.phone.ilike(q_pat))
        )

    if role:
        try:
            role_enum = UserRole(role)
        except ValueError:
            raise _422(f"Unknown role: {role!r}", "role")
        base = base.join(UserRole_, UserRole_.user_id == User.id).where(UserRole_.role == role_enum)

    if status == "active":
        base = base.where(User.is_active == True)
    elif status == "inactive":
        base = base.where(User.is_active == False)
    elif status == "locked":
        base = base.where(User.locked_until.isnot(None), User.locked_until > now)

    sort_col_map = {
        "created_at": User.created_at,
        "full_name": User.full_name,
        "last_login_at": User.last_login_at,
    }
    sort_col = sort_col_map[sort]
    order_expr = sort_col.asc() if dir == "asc" else sort_col.desc()

    total_row = await db.execute(select(func.count()).select_from(base.subquery()))
    total = total_row.scalar_one()

    users = (await db.execute(
        base.order_by(order_expr, User.id.asc()).offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()

    # Fix 7: Eliminate N+1 — fetch invite counts for all users in one query
    user_ids = [u.id for u in users]
    invite_counts: dict = {}
    if user_ids:
        inv_rows = (await db.execute(
            select(PasswordResetToken.user_id, func.count().label("cnt"))
            .where(
                PasswordResetToken.user_id.in_(user_ids),
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
            .group_by(PasswordResetToken.user_id)
        )).all()
        invite_counts = {row.user_id: row.cnt for row in inv_rows}

    items = []
    for u in users:
        inv_count = invite_counts.get(u.id, 0)
        invited = (u.last_login_at is None) and (inv_count > 0)
        is_locked = bool(u.locked_until and u.locked_until > now)
        items.append(UserListItem(
            id=str(u.id),
            full_name=u.full_name,
            email=str(u.email) if u.email else None,
            phone=u.phone,
            roles=[r.role.value for r in u.roles],
            is_active=u.is_active,
            is_locked=is_locked,
            locked_until=u.locked_until,
            invited=invited,
            last_login_at=u.last_login_at,
            created_at=u.created_at,
        ))

    return UserListOut(
        items=items, total=total, page=page, page_size=page_size,
        counts=UserCounts(
            all=counts_row.all, active=counts_row.active,
            inactive=counts_row.inactive, locked=counts_row.locked,
        ),
    )


# ---------------------------------------------------------------------------
# GET /users/{user_id}
# ---------------------------------------------------------------------------


class RoleGrantedInfo(BaseModel):
    role: str
    granted_at: datetime
    granted_by_name: Optional[str]

    model_config = {"extra": "forbid"}


class UserWarehouseInfo(BaseModel):
    id: str
    code: str
    name: str

    model_config = {"extra": "forbid"}


class UserMerchantInfo(BaseModel):
    id: str
    name: str

    model_config = {"extra": "forbid"}


class UserDetailOut(BaseModel):
    id: str
    full_name: str
    email: Optional[str]
    phone: Optional[str]
    roles: List[RoleGrantedInfo]
    is_active: bool
    is_locked: bool
    locked_until: Optional[datetime]
    invited: bool
    last_login_at: Optional[datetime]
    created_at: datetime
    warehouses: List[UserWarehouseInfo]
    merchants: List[UserMerchantInfo]
    driver_status: Optional[str]
    active_sessions: int

    model_config = {"extra": "forbid"}


@router.get("/users/{user_id}", response_model=UserDetailOut)
async def get_user(
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> UserDetailOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    now = datetime.now(timezone.utc)
    u = await db.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == uid)
    )
    if u is None:
        raise _404()

    grantor_ids = {r.granted_by for r in u.roles if r.granted_by}
    grantors = {}
    if grantor_ids:
        grantor_rows = (await db.execute(
            select(User.id, User.full_name).where(User.id.in_(grantor_ids))
        )).all()
        grantors = {row.id: row.full_name for row in grantor_rows}
    role_infos = [
        RoleGrantedInfo(
            role=r.role.value,
            granted_at=r.granted_at,
            granted_by_name=grantors.get(r.granted_by),
        )
        for r in u.roles
    ]

    wh_rows = (await db.execute(
        select(Warehouse).join(WarehouseStaff, WarehouseStaff.warehouse_id == Warehouse.id)
        .where(WarehouseStaff.user_id == uid)
    )).scalars().all()

    m_rows = (await db.execute(
        select(Merchant).join(MerchantMember, MerchantMember.merchant_id == Merchant.id)
        .where(MerchantMember.user_id == uid)
    )).scalars().all()

    driver = await db.scalar(select(Driver).where(Driver.user_id == uid))
    driver_status = driver.status.value if driver else None

    active_sessions = (await db.execute(
        select(func.count()).where(
            RefreshToken.user_id == uid,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
    )).scalar_one()

    inv_count = (await db.execute(
        select(func.count()).where(
            PasswordResetToken.user_id == uid,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )).scalar_one()
    invited = (u.last_login_at is None) and (inv_count > 0)
    is_locked = bool(u.locked_until and u.locked_until > now)

    return UserDetailOut(
        id=str(u.id),
        full_name=u.full_name,
        email=str(u.email) if u.email else None,
        phone=u.phone,
        roles=role_infos,
        is_active=u.is_active,
        is_locked=is_locked,
        locked_until=u.locked_until,
        invited=invited,
        last_login_at=u.last_login_at,
        created_at=u.created_at,
        warehouses=[UserWarehouseInfo(id=str(w.id), code=w.code, name=w.name) for w in wh_rows],
        merchants=[UserMerchantInfo(id=str(m.id), name=m.name) for m in m_rows],
        driver_status=driver_status,
        active_sessions=active_sessions,
    )


# ---------------------------------------------------------------------------
# POST /users  (invite)
# ---------------------------------------------------------------------------


class InviteUserBody(BaseModel):
    full_name: str = Field(..., max_length=200)
    email: EmailStr
    role: Literal["dispatcher", "fleet_manager", "admin"]
    warehouse_ids: Optional[List[str]] = None
    current_password: Optional[str] = None  # required iff role=admin

    model_config = {"extra": "forbid"}


class InviteUserOut(BaseModel):
    user: UserListItem
    invite_sent: bool

    model_config = {"extra": "forbid"}


@router.post("/users", response_model=InviteUserOut, status_code=201)
async def invite_user(
    request: Request,
    body: InviteUserBody,
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> InviteUserOut:
    if body.role == "admin":
        _step_up_check(actor, body.current_password, "grant the admin role")

    warehouse_ids: List[_uuid.UUID] = []
    if body.role in ("dispatcher", "fleet_manager") and body.warehouse_ids:
        for wid_str in body.warehouse_ids:
            try:
                warehouse_ids.append(_uuid.UUID(wid_str))
            except ValueError:
                raise _422(f"Invalid warehouse UUID: {wid_str}", "warehouse_ids")

    now = datetime.now(timezone.utc)

    existing = await db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(status_code=409, detail={"error": "email_taken"})

    for wid in warehouse_ids:
        wh = await db.scalar(select(Warehouse).where(Warehouse.id == wid, Warehouse.is_active == True))
        if wh is None:
            raise _422(f"Warehouse {wid} not found or inactive.", "warehouse_ids")

    unusable_hash = hash_password(secrets.token_urlsafe(32))
    user = User(
        email=body.email,
        password_hash=unusable_hash,
        full_name=body.full_name,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        if is_email_unique_violation(exc):
            raise HTTPException(status_code=409, detail={"error": "email_taken"}) from exc
        raise

    role_enum = UserRole(body.role)
    db.add(UserRole_(user_id=user.id, role=role_enum, granted_by=actor.id))

    # NOTE: A dispatcher/fleet_manager with zero warehouse_staff rows has no warehouse access.
    for wid in warehouse_ids:
        db.add(WarehouseStaff(user_id=user.id, warehouse_id=wid))

    raw_token = await _issue_invite_token(user, db)

    await write_audit(
        db, actor=actor, action="user.invite",
        target_type="user", target_id=user.id,
        target_label=user.full_name,
        details={"role": body.role, "warehouse_ids": [str(w) for w in warehouse_ids]},
        ip=get_client_ip(request),
    )
    await db.commit()

    invite_sent = False
    try:
        invite_sent = await send_staff_invite(
            to_address=str(user.email),
            full_name=user.full_name,
            role=body.role,
            reset_token=raw_token,
        )
    except Exception:
        logger.exception("invite email failed for user %s", user.id)

    await db.refresh(user, ["roles"])
    is_locked = bool(user.locked_until and user.locked_until > now)
    return InviteUserOut(
        user=UserListItem(
            id=str(user.id), full_name=user.full_name,
            email=str(user.email) if user.email else None,
            phone=user.phone, roles=[body.role],
            is_active=user.is_active, is_locked=is_locked,
            locked_until=user.locked_until, invited=True,
            last_login_at=None, created_at=user.created_at,
        ),
        invite_sent=invite_sent,
    )


# ---------------------------------------------------------------------------
# POST /users/{user_id}/deactivate
# ---------------------------------------------------------------------------


class SimpleUserOut(BaseModel):
    id: str
    full_name: str
    is_active: bool

    model_config = {"extra": "forbid"}


@router.post("/users/{user_id}/deactivate", response_model=SimpleUserOut)
async def deactivate_user(
    request: Request,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> SimpleUserOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    if uid == actor.id:
        raise _409("You cannot deactivate your own account.", "self_action_blocked")

    u = await _get_user_or_404(uid, db)

    role_values = {r.role for r in u.roles}
    if UserRole.admin in role_values:
        count = await _lock_and_count_active_admins(db)
        if count <= 1:
            raise _409("Cannot deactivate the last active admin.", "last_admin")

    driver = await db.scalar(select(Driver).where(Driver.user_id == uid))
    if driver:
        active_route = await db.scalar(
            select(Route).where(
                Route.driver_id == uid,
                Route.status.in_([RouteStatus.planned, RouteStatus.in_progress]),
            )
        )
        if active_route:
            raise _409("Driver has an active route.", "driver_has_active_route")

        if driver.status == DriverStatus.available:
            await db.execute(
                update(Driver)
                .where(Driver.user_id == uid)
                .values(status=DriverStatus.offline, updated_at=datetime.now(timezone.utc))
            )

    if not u.is_active:
        return SimpleUserOut(id=str(u.id), full_name=u.full_name, is_active=u.is_active)

    u.is_active = False
    u.updated_at = datetime.now(timezone.utc)
    await _revoke_all_tokens(u, db)

    await write_audit(
        db, actor=actor, action="user.deactivate",
        target_type="user", target_id=uid, target_label=u.full_name,
        ip=get_client_ip(request),
    )
    await db.commit()
    return SimpleUserOut(id=str(u.id), full_name=u.full_name, is_active=False)


# ---------------------------------------------------------------------------
# POST /users/{user_id}/reactivate
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/reactivate", response_model=SimpleUserOut)
async def reactivate_user(
    request: Request,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> SimpleUserOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    u = await _get_user_or_404(uid, db)

    if u.is_active:
        return SimpleUserOut(id=str(u.id), full_name=u.full_name, is_active=True)

    u.is_active = True
    u.updated_at = datetime.now(timezone.utc)

    await write_audit(
        db, actor=actor, action="user.reactivate",
        target_type="user", target_id=uid, target_label=u.full_name,
        ip=get_client_ip(request),
    )
    await db.commit()
    return SimpleUserOut(id=str(u.id), full_name=u.full_name, is_active=True)


# ---------------------------------------------------------------------------
# POST /users/{user_id}/unlock
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/unlock", response_model=SimpleUserOut)
async def unlock_user(
    request: Request,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> SimpleUserOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    u = await _get_user_or_404(uid, db)
    u.failed_login_count = 0
    u.locked_until = None
    u.updated_at = datetime.now(timezone.utc)

    await write_audit(
        db, actor=actor, action="user.unlock",
        target_type="user", target_id=uid, target_label=u.full_name,
        ip=get_client_ip(request),
    )
    await db.commit()
    return SimpleUserOut(id=str(u.id), full_name=u.full_name, is_active=u.is_active)


# ---------------------------------------------------------------------------
# POST /users/{user_id}/revoke-sessions
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/revoke-sessions", response_model=SimpleUserOut)
async def revoke_sessions(
    request: Request,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> SimpleUserOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    if uid == actor.id:
        raise _409("You cannot revoke your own sessions via the console.", "self_action_blocked")

    u = await _get_user_or_404(uid, db)
    await _revoke_all_tokens(u, db)

    await write_audit(
        db, actor=actor, action="user.revoke_sessions",
        target_type="user", target_id=uid, target_label=u.full_name,
        ip=get_client_ip(request),
    )
    await db.commit()
    return SimpleUserOut(id=str(u.id), full_name=u.full_name, is_active=u.is_active)


# ---------------------------------------------------------------------------
# POST /users/{user_id}/send-reset
# ---------------------------------------------------------------------------


class SendResetOut(BaseModel):
    sent: bool

    model_config = {"extra": "forbid"}


@router.post("/users/{user_id}/send-reset", response_model=SendResetOut)
async def send_reset(
    request: Request,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> SendResetOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    u = await _get_user_or_404(uid, db)
    if not u.is_active:
        raise _err(400, "User is not active.", "invalid_state")

    if not await acquire_email_cooldown("admin-reset", uid):
        raise HTTPException(status_code=429, detail="Email cooldown active.", headers={"Retry-After": "60"})

    now = datetime.now(timezone.utc)
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == uid, PasswordResetToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw, token_hash, expires_at = generate_reset_token()
    db.add(PasswordResetToken(user_id=uid, token_hash=hash_reset_token(raw), expires_at=expires_at))

    await write_audit(
        db, actor=actor, action="user.send_reset",
        target_type="user", target_id=uid, target_label=u.full_name,
        ip=get_client_ip(request),
    )
    await db.commit()

    sent = False
    if u.email:
        from services.core_api.app.auth.email import send_reset_email
        try:
            await send_reset_email(to_address=str(u.email), reset_token=raw)
            sent = True
        except Exception:
            logger.exception("send_reset email failed for user %s", uid)

    return SendResetOut(sent=sent)


# ---------------------------------------------------------------------------
# POST /users/{user_id}/resend-invite
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/resend-invite", response_model=InviteUserOut)
async def resend_invite(
    request: Request,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> InviteUserOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    now = datetime.now(timezone.utc)
    u = await db.scalar(select(User).options(selectinload(User.roles)).where(User.id == uid))
    if u is None:
        raise _404()

    inv_count = (await db.execute(
        select(func.count()).where(
            PasswordResetToken.user_id == uid,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )).scalar_one()
    if u.last_login_at is not None or inv_count == 0:
        raise _409("User is not in invited state.", "invalid_state")

    if not await acquire_email_cooldown("admin-invite", uid):
        raise HTTPException(status_code=429, detail="Email cooldown active.", headers={"Retry-After": "60"})

    raw_token = await _issue_invite_token(u, db)

    await write_audit(
        db, actor=actor, action="user.resend_invite",
        target_type="user", target_id=uid, target_label=u.full_name,
        ip=get_client_ip(request),
    )
    await db.commit()

    invite_sent = False
    role_val = u.roles[0].role.value if u.roles else "dispatcher"
    if u.email:
        try:
            invite_sent = await send_staff_invite(
                to_address=str(u.email), full_name=u.full_name,
                role=role_val, reset_token=raw_token,
            )
        except Exception:
            logger.exception("resend_invite email failed for %s", uid)

    is_locked = bool(u.locked_until and u.locked_until > now)
    return InviteUserOut(
        user=UserListItem(
            id=str(u.id), full_name=u.full_name,
            email=str(u.email) if u.email else None,
            phone=u.phone, roles=[r.role.value for r in u.roles],
            is_active=u.is_active, is_locked=is_locked,
            locked_until=u.locked_until, invited=True,
            last_login_at=None, created_at=u.created_at,
        ),
        invite_sent=invite_sent,
    )


# ---------------------------------------------------------------------------
# POST /users/{user_id}/roles  (grant)
# ---------------------------------------------------------------------------


class RoleBody(BaseModel):
    role: Literal["dispatcher", "fleet_manager", "admin"]
    current_password: Optional[str] = None  # required iff role=admin

    model_config = {"extra": "forbid"}


class RoleOut(BaseModel):
    role: str
    granted: bool

    model_config = {"extra": "forbid"}


@router.post("/users/{user_id}/roles", response_model=RoleOut)
async def grant_role(
    request: Request,
    body: RoleBody,
    user_id: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> RoleOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    if body.role == "admin":
        _step_up_check(actor, body.current_password, "grant the admin role")

    u = await _get_user_or_404(uid, db)
    role_enum = UserRole(body.role)

    existing_role = await db.scalar(
        select(UserRole_).where(UserRole_.user_id == uid, UserRole_.role == role_enum)
    )
    if existing_role is not None:
        return RoleOut(role=body.role, granted=False)

    db.add(UserRole_(user_id=uid, role=role_enum, granted_by=actor.id))
    await write_audit(
        db, actor=actor, action="user.role_grant",
        target_type="user", target_id=uid, target_label=u.full_name,
        details={"role": body.role}, ip=get_client_ip(request),
    )
    await db.commit()
    return RoleOut(role=body.role, granted=True)


# ---------------------------------------------------------------------------
# POST /users/{user_id}/roles/{role}/revoke
# ---------------------------------------------------------------------------


class RevokeRoleBody(BaseModel):
    current_password: Optional[str] = None  # required iff revoking admin

    model_config = {"extra": "forbid"}


@router.post("/users/{user_id}/roles/{role}/revoke", response_model=RoleOut)
async def revoke_role(
    request: Request,
    body: RevokeRoleBody,
    user_id: str = Path(...),
    role: str = Path(...),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> RoleOut:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise _422("Invalid UUID.", "user_id")

    if role not in ASSIGNABLE_ROLES:
        raise _409(f"Role '{role}' cannot be managed via the console.", "role_not_assignable")

    if role == "admin":
        _step_up_check(actor, body.current_password, "revoke the admin role")

    if uid == actor.id and role == "admin":
        raise _409("You cannot revoke your own admin role.", "self_action_blocked")

    u = await _get_user_or_404(uid, db)
    role_enum = UserRole(role)

    if role == "admin":
        count = await _lock_and_count_active_admins(db)
        if count <= 1:
            raise _409("Cannot revoke the last active admin role.", "last_admin")

    result = await db.execute(
        delete(UserRole_).where(UserRole_.user_id == uid, UserRole_.role == role_enum)
    )
    if result.rowcount == 0:
        return RoleOut(role=role, granted=False)

    # Remove warehouse_staff rows if last staff role was revoked (§7.3)
    remaining_staff_roles = await db.scalars(
        select(UserRole_).where(
            UserRole_.user_id == uid,
            UserRole_.role.in_([UserRole.dispatcher, UserRole.fleet_manager]),
        )
    )
    if not remaining_staff_roles.all():
        await db.execute(delete(WarehouseStaff).where(WarehouseStaff.user_id == uid))

    await write_audit(
        db, actor=actor, action="user.role_revoke",
        target_type="user", target_id=uid, target_label=u.full_name,
        details={"role": role}, ip=get_client_ip(request),
    )
    await db.commit()
    return RoleOut(role=role, granted=False)
