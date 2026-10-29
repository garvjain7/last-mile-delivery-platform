"""Authenticated staff operations for system-wide order visibility and recovery."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db_models.models import OrderStatus
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.admin.security import csrf_check
from services.core_api.app.database.connection import get_db_session
from services.core_api.app.staff.service import (
    OrderNotEligibleError,
    OrderNotFoundError,
    OrderStreamPublishError,
    list_staff_orders,
    republish_stale_placed_order,
)

router = APIRouter(dependencies=[Depends(require_admin)])


class StaffOrderItem(BaseModel):
    order_id: UUID
    merchant_order_ref: str
    tracking_token: str
    merchant_id: UUID
    merchant_name: str
    warehouse_id: Optional[UUID]
    warehouse_code: Optional[str]
    status: str
    recipient_name: str
    recipient_phone: str
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "forbid"}


class UnstickOrderResponse(BaseModel):
    order_id: UUID
    status: str
    order_status: str

    model_config = {"extra": "forbid"}


@router.get("/orders", response_model=list[StaffOrderItem])
async def list_all_orders(
    q: Optional[str] = Query(default=None, max_length=100),
    order_status: Optional[list[OrderStatus]] = Query(default=None, alias="status"),
    merchant_id: Optional[UUID] = Query(default=None),
    warehouse_id: Optional[UUID] = Query(default=None),
    created_from: Optional[datetime] = Query(default=None, alias="from"),
    created_to: Optional[datetime] = Query(default=None, alias="to"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> list[StaffOrderItem]:
    """List orders with optional status, merchant, warehouse, date, and text filters."""
    if created_from is not None and created_from.tzinfo is None:
        raise HTTPException(status_code=422, detail="'from' must include a timezone.")
    if created_to is not None and created_to.tzinfo is None:
        raise HTTPException(status_code=422, detail="'to' must include a timezone.")
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(status_code=422, detail="'from' must be earlier than or equal to 'to'.")

    rows = await list_staff_orders(
        db,
        q=q,
        statuses=order_status,
        merchant_id=merchant_id,
        warehouse_id=warehouse_id,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
    )
    return [
        StaffOrderItem(
            order_id=order.id,
            merchant_order_ref=order.merchant_order_ref,
            tracking_token=order.tracking_token,
            merchant_id=order.merchant_id,
            merchant_name=merchant.name,
            warehouse_id=warehouse.id if warehouse else None,
            warehouse_code=warehouse.code if warehouse else None,
            status=order.status.value,
            recipient_name=order.recipient_name,
            recipient_phone=order.recipient_phone,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )
        for order, merchant, warehouse in rows
    ]


@router.post(
    "/orders/{order_id}/unstick",
    response_model=UnstickOrderResponse,
    dependencies=[Depends(csrf_check)],
)
async def unstick_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> UnstickOrderResponse:
    """Re-publish an eligible stale placed order without changing its status."""
    try:
        await republish_stale_placed_order(db, order_id)
    except OrderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except OrderNotEligibleError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OrderStreamPublishError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Order could not be published to the routing stream.",
        ) from exc

    return UnstickOrderResponse(
        order_id=order_id,
        status="republished",
        order_status=OrderStatus.placed.value,
    )
