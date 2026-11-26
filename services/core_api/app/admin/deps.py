# Admin auth dependency: require_admin.
#
# Attach at router level:
#   router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_admin)])
#
# On every request it:
#   1. Resolves the session from the access_token cookie (never trusts JWT claims alone
#      for role check — always re-reads user_roles from the DB).
#   2. Checks is_active and lock state.
#   3. Checks that user_roles contains 'admin'.
#   4. Returns the User ORM object so handlers can use it as the audit actor.
#
# 401 is returned as {"detail": "...", "code": "unauthenticated"}.
# 403 is returned as {"detail": "...", "code": "forbidden"}.

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import User, UserRole, UserRole_
from services.core_api.app.auth.security import decode_access_token
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error helpers (§5.4 shape)
# ---------------------------------------------------------------------------

from limits import parse as parse_limit
from slowapi import Limiter
from slowapi.util import get_remote_address

admin_limiter = Limiter(key_func=lambda req: getattr(req.state, "admin_user_id", get_remote_address(req)))

_LIMIT_GET = parse_limit("120/minute")
_LIMIT_MUTATE = parse_limit("30/minute")
_LIMIT_INVITE = parse_limit("10/hour")
_LIMIT_STEP_UP = parse_limit("5/15minute")  # Fix 10: step-up password attempt limit


def _check_admin_rate_limit(request: Request, user_id: str) -> None:
    """Enforce §3.6 rate limits keyed on authenticated user id."""
    method = request.method
    path = request.url.path

    # Invite, resend-invite, send-reset: 10/hour/user
    if (path == "/api/admin/users" and method == "POST") or \
       path.endswith("/send-reset") or \
       path.endswith("/resend-invite"):
        limit_key = f"admin:{user_id}:invite"
        if not admin_limiter.limiter.hit(_LIMIT_INVITE, limit_key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"detail": "Too many requests. Please wait a moment.", "code": "rate_limited"},
            )
        return

    # Step-up (password-sensitive) actions: 5/15min/user (Fix 10)
    if path.endswith("/roles") or path.endswith("/revoke"):
        limit_key = f"admin:{user_id}:step_up"
        if not admin_limiter.limiter.hit(_LIMIT_STEP_UP, limit_key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"detail": "Too many step-up attempts. Please wait 15 minutes.", "code": "rate_limited"},
            )
        return

    # Admin GET endpoints: 120/min/user
    if method in ("GET", "HEAD"):
        limit_key = f"admin:{user_id}:get"
        if not admin_limiter.limiter.hit(_LIMIT_GET, limit_key):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"detail": "Too many requests. Please wait a moment.", "code": "rate_limited"},
            )
        return

    # Mutations: 30/min/user
    limit_key = f"admin:{user_id}:mutate"
    if not admin_limiter.limiter.hit(_LIMIT_MUTATE, limit_key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"detail": "Too many requests. Please wait a moment.", "code": "rate_limited"},
        )


def _401(msg: str = "Authentication required.") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"detail": msg, "code": "unauthenticated"},
    )


def _403(msg: str = "Forbidden.", code: str = "forbidden") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"detail": msg, "code": code},
    )


# ---------------------------------------------------------------------------
# require_admin dependency
# ---------------------------------------------------------------------------

async def require_admin(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """
    Authenticate session and enforce admin role.

    1. Decode JWT from the access_token cookie.
    2. Re-load user + roles from the DB (never trust JWT claims for authz).
    3. Enforce is_active and lock state.
    4. Enforce admin role.
    5. Enforce rate limits (§3.6).
    6. Return the User object (actor) for use by handlers.
    """
    # Also accept Bearer header for API clients / tests.
    token: Optional[str] = access_token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.removeprefix("Bearer ")

    if not token:
        raise _401("No session token.")

    try:
        payload = decode_access_token(token)
    except JWTError:
        raise _401("Invalid or expired token.")

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise _401("Malformed token.")

    import uuid as _uuid
    try:
        user_uuid = _uuid.UUID(user_id_str)
    except ValueError:
        raise _401("Malformed token subject.")

    # Always re-read from DB — never trust JWT claims for authorization.
    stmt = (
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == user_uuid)
    )
    user: Optional[User] = await db.scalar(stmt)

    if user is None:
        raise _401("Account not found.")

    if not user.is_active:
        raise _401("Account is deactivated.")

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        raise _401("Account is temporarily locked.")

    role_values = {r.role for r in user.roles}
    if UserRole.admin not in role_values:
        raise _403("Admin role required.")

    request.state.admin_user = user
    request.state.admin_user_id = str(user.id)
    _check_admin_rate_limit(request, str(user.id))
    return user
