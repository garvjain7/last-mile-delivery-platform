# admin/common.py
#
# Shared helpers, error builders, and private utilities used by all admin route
# modules.  Nothing in this file imports from any route module — that would
# create a circular dependency.

from __future__ import annotations

import asyncio
import logging
import secrets
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import (
    PasswordResetToken,
    RefreshToken,
    User,
    UserRole,
    UserRole_,
)
from services.core_api.app.auth.security import (
    generate_reset_token,
    hash_reset_token,
    verify_password,
)

logger = logging.getLogger(__name__)

RESET_TOKEN_TTL_HOURS = 72  # invite tokens live longer than standard 1-hour resets

# ---------------------------------------------------------------------------
# Error helpers (§5.4)
# ---------------------------------------------------------------------------


def _err(http: int, detail: str, code: str, extra: Optional[Dict] = None) -> HTTPException:
    body: Dict[str, Any] = {"detail": detail, "code": code}
    if extra:
        body.update(extra)
    return HTTPException(status_code=http, detail=body)


def _404(detail: str = "Not found.") -> HTTPException:
    return _err(404, detail, "not_found")


def _409(detail: str, code: str, extra: Optional[Dict] = None) -> HTTPException:
    return _err(409, detail, code, extra)


def _422(detail: str, field: Optional[str] = None) -> HTTPException:
    body: Dict[str, Any] = {"detail": detail, "code": "validation_error"}
    if field:
        body["errors"] = [{"field": field, "message": detail}]
    return HTTPException(status_code=422, detail=body)


# ---------------------------------------------------------------------------
# Auth / privilege helpers
# ---------------------------------------------------------------------------


def _step_up_check(actor: User, current_password: Optional[str], required_for: str) -> None:
    """§3.5: verify acting admin's own password for sensitive role changes."""
    if current_password is None:
        raise _err(403, f"Your current password is required to {required_for}.",
                   "reauth_required")
    if not verify_password(current_password, actor.password_hash):
        raise _err(403, "Current password is incorrect.", "reauth_failed")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


async def _get_user_or_404(user_id: _uuid.UUID, db: AsyncSession) -> User:
    user = await db.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == user_id)
    )
    if user is None:
        raise _404()
    return user


async def _issue_invite_token(user: User, db: AsyncSession) -> str:
    """Invalidate previous unused tokens, issue a 72-hour token, return raw token."""
    now = datetime.now(timezone.utc)
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )
    raw, _token_hash, _expires_at = generate_reset_token()
    expires_at = now + timedelta(hours=RESET_TOKEN_TTL_HOURS)
    db.add(PasswordResetToken(
        user_id=user.id,
        token_hash=hash_reset_token(raw),
        expires_at=expires_at,
    ))
    return raw


async def _revoke_all_tokens(user: User, db: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


async def _lock_and_count_active_admins(db: AsyncSession) -> int:
    """Lock active-admin user and role rows, then count them (§3.10).

    PostgreSQL does not allow ``FOR UPDATE`` on an aggregate query. Locking
    the qualifying user and role rows serializes both deactivation and role
    revocation attempts. The count is taken from rows returned by that query.
    """
    result = await db.execute(
        select(User.id)
        .select_from(UserRole_)
        .join(User, User.id == UserRole_.user_id)
        .where(
            UserRole_.role == UserRole.admin,
            User.is_active == True,
        )
        .order_by(User.id)
        .with_for_update(of=[User, UserRole_])
    )
    return len(result.scalars().all())
