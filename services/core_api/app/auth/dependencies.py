"""Authentication dependencies shared by customer-owned API routes and pages."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import User
from services.core_api.app.auth.security import decode_access_token
from services.core_api.app.database.connection import get_db_session


async def resolve_self_customer(
    user_id: Optional[uuid.UUID],
    token: Optional[str],
    db: AsyncSession,
) -> Optional[User]:
    """Resolve an active customer whose id matches the token subject and optional path id."""
    if not token:
        return None
    try:
        claims = decode_access_token(token)
        token_user_id = uuid.UUID(claims.get("sub", ""))
    except (JWTError, ValueError, TypeError, AttributeError):
        return None

    if user_id is not None and token_user_id != user_id:
        return None

    user = await db.scalar(
        select(User).options(selectinload(User.roles)).where(User.id == token_user_id)
    )
    if user is None or not user.is_active:
        return None
    if user.locked_until is not None and user.locked_until > datetime.now(timezone.utc):
        return None
    if "customer" not in {role.role.value for role in user.roles}:
        return None
    return user


async def require_self_customer(
    user_id: uuid.UUID,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None, description="Bearer <access_token>"),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Require that the caller is the active customer named by the URL, else return 404."""
    token = authorization.removeprefix("Bearer ") if authorization and authorization.startswith("Bearer ") else access_token
    user = await resolve_self_customer(user_id, token, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    request.state.customer_user_id = str(user.id)
    return user
