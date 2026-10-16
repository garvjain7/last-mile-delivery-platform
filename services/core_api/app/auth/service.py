# Auth business logic: register, login, token refresh, forgot/reset password, token introspection.
# All Postgres operations go through SQLAlchemy async sessions from services.core_api.app.database.connection.
# No HTTP-layer concerns here — those live in router.py.

import asyncio
import uuid as uuid_mod
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import (
    Driver,
    PasswordResetToken,
    RefreshToken,
    User,
    UserRole_,
    UserRole,
)
from services.core_api.app.auth.email import send_reset_email
from services.core_api.app.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResetPasswordRequest,
    _InternalTokenPair,
)
from services.core_api.app.auth.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    generate_reset_token,
    hash_password,
    hash_refresh_token,
    hash_reset_token,
    redirect_for_roles,
    verify_password,
)


# ---------------------------------------------------------------------------
# Account lockout constants
# ---------------------------------------------------------------------------

MAX_FAILED_ATTEMPTS = 3
LOCKOUT_MINUTES = 5
INVALID_CREDENTIALS = "Invalid credentials."
DUMMY_PASSWORD_HASH = "$2b$12$Nr1NHZbz8q83IaUP3NsZAeshxCWU9MpI8KcN/9vgy06kUcFyer5aS"


# ---------------------------------------------------------------------------
# Shared helper: persist a new refresh token and return the full token pair.
# ---------------------------------------------------------------------------

async def _issue_tokens(user: User, db: AsyncSession) -> _InternalTokenPair:
    """Mint a new access + refresh token pair for user, persist the refresh token hash.
    Caller is responsible for committing the session."""
    roles = [r.role.value for r in user.roles]
    access_token = create_access_token(str(user.id), roles)

    raw_refresh, refresh_hash, refresh_expires = generate_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=refresh_expires,
        )
    )
    return _InternalTokenPair(
        access_token=access_token,
        refresh_token=raw_refresh,
        redirect_to=redirect_for_roles(roles),
        user_id=str(user.id),
        roles=roles,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

async def register_user(
    payload: RegisterRequest,
    role: str,
    db: AsyncSession,
) -> None:
    """Create a new account with the given role without issuing a session.

    role is passed by the router based on which endpoint was called —
    it is never supplied by the client directly.

    Customers:  users row + user_roles row.
    Drivers:    same, plus a drivers row (status=pending, awaiting admin approval).
    """
    if payload.email is None and payload.phone is None:
        raise ValueError("At least one of email or phone is required.")

    # Friendly uniqueness check before hitting the DB constraint.
    if payload.email:
        existing = await db.scalar(select(User).where(User.email == payload.email))
        if existing:
            raise ValueError("An account with this email already exists.")
    if payload.phone:
        existing = await db.scalar(select(User).where(User.phone == payload.phone))
        if existing:
            raise ValueError("An account with this phone number already exists.")

    user = User(
        email=payload.email,
        phone=payload.phone,
        password_hash=await asyncio.to_thread(hash_password, payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    await db.flush()  # populate user.id before inserting dependents

    role_enum = UserRole(role)
    db.add(UserRole_(user_id=user.id, role=role_enum))

    if role == "driver":
        # Driver profile starts as 'pending' — an admin must approve before they go active.
        db.add(Driver(user_id=user.id))

    await db.commit()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def login_user(payload: LoginRequest, db: AsyncSession) -> _InternalTokenPair:
    """Authenticate by email or phone + password.
    Enforces account lockout after MAX_FAILED_ATTEMPTS consecutive failures."""

    if payload.email is None and payload.phone is None:
        raise ValueError("Provide email or phone to log in.")

    # Load user with roles in one query.
    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(
            User.email == payload.email if payload.email else User.phone == payload.phone
        )
    )
    user: Optional[User] = await db.scalar(stmt)

    if user is None:
        await asyncio.to_thread(verify_password, payload.password, DUMMY_PASSWORD_HASH)
        raise ValueError(INVALID_CREDENTIALS)

    if not user.is_active:
        await asyncio.to_thread(verify_password, payload.password, user.password_hash)
        raise ValueError(INVALID_CREDENTIALS)

    # Lockout check.
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        await asyncio.to_thread(verify_password, payload.password, user.password_hash)
        raise ValueError(INVALID_CREDENTIALS)

    password_matches = await asyncio.to_thread(verify_password, payload.password, user.password_hash)
    if not password_matches:
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)
        await db.commit()
        raise ValueError(INVALID_CREDENTIALS)

    # Successful login — reset failure counter and record timestamp.
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)

    tokens = await _issue_tokens(user, db)
    await db.commit()
    return tokens


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

async def refresh_tokens(raw_refresh_token: str, db: AsyncSession) -> _InternalTokenPair:
    """Exchange a valid refresh token for a new access + refresh pair (rotation).
    The raw token comes from the httpOnly refresh_token cookie — never from JSON body.
    """
    token_hash = hash_refresh_token(raw_refresh_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    stored: Optional[RefreshToken] = await db.scalar(stmt)
    if stored is None:
        raise ValueError("Refresh token is invalid or expired.")

    now = datetime.now(timezone.utc)
    if stored.revoked_at is not None:
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == stored.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.commit()
        raise ValueError("Refresh token is invalid or expired.")
    if stored.expires_at <= now:
        raise ValueError("Refresh token is invalid or expired.")

    # Revoke the old token immediately (single-use rotation).
    stored.revoked_at = now

    # Re-load user + roles.
    user_stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == stored.user_id)
    )
    user: Optional[User] = await db.scalar(user_stmt)
    if user is None or not user.is_active or (user.locked_until is not None and user.locked_until > now):
        await db.commit()
        raise ValueError("Refresh token is invalid or expired.")

    tokens = await _issue_tokens(user, db)
    await db.commit()
    return tokens


# ---------------------------------------------------------------------------
# Forgot password — sends reset link via email
# ---------------------------------------------------------------------------

async def request_password_reset(payload: ForgotPasswordRequest, db: AsyncSession) -> None:
    """Generate a reset token and email a link to the user.

    Always returns without error even if the email/phone is not found —
    this prevents user enumeration. The email send is awaited so SMTP errors
    surface as 500 rather than being silently dropped.
    """
    if payload.email is None and payload.phone is None:
        raise ValueError("Provide email or phone.")

    stmt = select(User).where(
        User.email == payload.email if payload.email else User.phone == payload.phone
    )
    user: Optional[User] = await db.scalar(stmt)

    if user is None or not user.is_active:
        # Silently succeed — don't reveal whether the account exists.
        return

    # Invalidate any existing unused reset tokens for this user.
    existing_stmt = select(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used_at.is_(None),
    )
    existing_tokens = (await db.scalars(existing_stmt)).all()
    for t in existing_tokens:
        t.used_at = datetime.now(timezone.utc)

    raw_token, token_hash, expires_at = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.commit()

    # Email requires an address — if the user only has a phone, we cannot email them.
    # TODO: SMS reset channel for phone-only accounts (deferred).
    if user.email:
        await send_reset_email(to_address=str(user.email), reset_token=raw_token)


# ---------------------------------------------------------------------------
# Reset password — consume token, set new password
# ---------------------------------------------------------------------------

async def reset_password(payload: ResetPasswordRequest, db: AsyncSession) -> None:
    """Verify the raw token, hash and store the new password, mark token used."""

    token_hash = hash_reset_token(payload.token)
    stmt = (
        select(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(timezone.utc),
        )
    )
    stored: Optional[PasswordResetToken] = await db.scalar(stmt)
    if stored is None:
        raise ValueError("Reset token is invalid or expired.")

    user: Optional[User] = await db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise ValueError("Account not found or disabled.")

    user.password_hash = await asyncio.to_thread(hash_password, payload.new_password)
    user.failed_login_count = 0
    user.locked_until = None
    stored.used_at = datetime.now(timezone.utc)

    # Revoke all active refresh tokens — forces re-login on all devices after password change.
    active_refresh_stmt = select(RefreshToken).where(
        RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None),
    )
    active_tokens = (await db.scalars(active_refresh_stmt)).all()
    for rt in active_tokens:
        rt.revoked_at = datetime.now(timezone.utc)

    await db.commit()


# ---------------------------------------------------------------------------
# Token introspection — GET /auth/me
# ---------------------------------------------------------------------------

async def get_current_user(token: str, db: AsyncSession) -> MeResponse:
    """Decode the access token, load the user, return identity + roles.

    Called by browser clients (token arrives in httpOnly cookie) and by other
    services (driver-gateway, control-tower) passing Authorization: Bearer <token>.
    """
    try:
        payload = decode_access_token(token)
    except JWTError:
        raise ValueError("Access token is invalid or expired.")

    user_id = payload.get("sub")
    if not user_id:
        raise ValueError("Malformed token: missing subject.")

    stmt = (
        select(User)
        .options(selectinload(User.roles), selectinload(User.driver_profile))
        .where(User.id == uuid_mod.UUID(user_id))
    )
    user: Optional[User] = await db.scalar(stmt)
    if user is None or not user.is_active:
        raise ValueError("User not found or account disabled.")

    roles = [r.role.value for r in user.roles]
    return MeResponse(
        user_id=str(user.id),
        email=str(user.email) if user.email else None,
        phone=user.phone,
        full_name=user.full_name,
        roles=roles,
        redirect_to=redirect_for_roles(roles),
        driver_status=(user.driver_profile.status.value if user.driver_profile else None),
    )
