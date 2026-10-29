"""Authentication dependency for endpoints owned by the signed-in driver."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import Driver, User
from services.core_api.app.auth.security import decode_access_token
from services.core_api.app.database.connection import get_db_session


async def require_driver(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db_session),
) -> User:
    """Resolve an active driver from the existing cookie or bearer-token session."""

    token = (
        authorization.removeprefix("Bearer ")
        if authorization and authorization.startswith("Bearer ")
        else access_token
    )
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    try:
        claims = decode_access_token(token)
        user_id = uuid.UUID(claims.get("sub", ""))
    except (JWTError, ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token.") from exc

    user = await db.scalar(
        select(User)
        .options(
            selectinload(User.roles),
            selectinload(User.driver_profile).joinedload(Driver.vehicle),
        )
        .where(User.id == user_id)
    )
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Driver account is unavailable.")
    if user.locked_until is not None and user.locked_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Driver account is temporarily locked.")
    if "driver" not in {role.role.value for role in user.roles} or user.driver_profile is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="A driver account is required.")

    request.state.driver_user_id = str(user.id)
    return user
