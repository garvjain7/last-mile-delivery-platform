# admin/routes/activity.py  — §7.7 Activity (admin audit log)
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db_models.models import AdminAuditLog, User
from services.core_api.app.admin.common import _422
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.admin.rules import decode_cursor, encode_cursor
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ActivityActorOut(BaseModel):
    id: str
    full_name: str

    model_config = {"extra": "forbid"}


class ActivityItem(BaseModel):
    id: int
    occurred_at: datetime
    actor: Optional[ActivityActorOut]
    action: str
    target_type: str
    target_id: str
    target_label: str
    details: Dict[str, Any]

    model_config = {"extra": "forbid"}


class ActivityOut(BaseModel):
    items: List[ActivityItem]
    next_cursor: Optional[str]

    model_config = {"extra": "forbid"}


class ActivityFiltersOut(BaseModel):
    actions: List[str]
    actors: List[ActivityActorOut]
    target_types: List[str]

    model_config = {"extra": "forbid"}


# ---------------------------------------------------------------------------
# GET /activity/filters — options for the activity filter controls
# ---------------------------------------------------------------------------


@router.get("/activity/filters", response_model=ActivityFiltersOut)
async def activity_filters(
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ActivityFiltersOut:
    actions = list((await db.scalars(
        select(AdminAuditLog.action).distinct().order_by(AdminAuditLog.action)
    )).all())
    target_types = list((await db.scalars(
        select(AdminAuditLog.target_type).distinct().order_by(AdminAuditLog.target_type)
    )).all())
    actor_rows = (await db.execute(
        select(User.id, User.full_name)
        .join(AdminAuditLog, AdminAuditLog.actor_user_id == User.id)
        .distinct()
        .order_by(User.full_name, User.id)
    )).all()

    return ActivityFiltersOut(
        actions=actions,
        actors=[ActivityActorOut(id=str(row.id), full_name=row.full_name) for row in actor_rows],
        target_types=target_types,
    )


# ---------------------------------------------------------------------------
# GET /activity
# ---------------------------------------------------------------------------


@router.get("/activity", response_model=ActivityOut)
async def list_activity(
    action: Optional[str] = Query(None),
    actor_id: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    from_: Optional[datetime] = Query(None, alias="from"),
    to: Optional[datetime] = Query(None),
    limit: int = Query(25, ge=1, le=100),
    cursor: Optional[str] = Query(None),
    actor: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> ActivityOut:
    stmt = (
        select(AdminAuditLog, User.id.label("actor_user_id_val"), User.full_name.label("actor_name"))
        .outerjoin(User, User.id == AdminAuditLog.actor_user_id)
    )

    if action:
        stmt = stmt.where(AdminAuditLog.action == action)
    if actor_id:
        try:
            aid = _uuid.UUID(actor_id)
        except ValueError:
            raise _422("Invalid actor_id UUID.", "actor_id")
        stmt = stmt.where(AdminAuditLog.actor_user_id == aid)
    if target_type:
        stmt = stmt.where(AdminAuditLog.target_type == target_type)
    if from_:
        stmt = stmt.where(AdminAuditLog.occurred_at >= from_)
    if to:
        stmt = stmt.where(AdminAuditLog.occurred_at <= to)

    if cursor:
        try:
            cursor_ts, cursor_id = decode_cursor(cursor)
            stmt = stmt.where(
                or_(
                    AdminAuditLog.occurred_at < cursor_ts,
                    and_(AdminAuditLog.occurred_at == cursor_ts, AdminAuditLog.id < int(cursor_id)),
                )
            )
        except ValueError:
            raise _422("Invalid cursor.", "cursor")

    stmt = stmt.order_by(AdminAuditLog.occurred_at.desc(), AdminAuditLog.id.desc()).limit(limit + 1)
    rows = (await db.execute(stmt)).all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [
        ActivityItem(
            id=r.AdminAuditLog.id,
            occurred_at=r.AdminAuditLog.occurred_at,
            actor=ActivityActorOut(id=str(r.actor_user_id_val), full_name=r.actor_name)
            if r.actor_user_id_val else None,
            action=r.AdminAuditLog.action,
            target_type=r.AdminAuditLog.target_type,
            target_id=str(r.AdminAuditLog.target_id),
            target_label=r.AdminAuditLog.target_label,
            details=r.AdminAuditLog.details,
        )
        for r in rows
    ]

    next_cursor = None
    if has_more and rows:
        last = rows[-1].AdminAuditLog
        next_cursor = encode_cursor(last.occurred_at, str(last.id))

    return ActivityOut(items=items, next_cursor=next_cursor)
