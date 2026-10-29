"""Public order intake endpoint."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from services.core_api.app.database.connection import get_db_session
from services.core_api.app.orders.service import create_order

router = APIRouter()


class CreateOrderRequest(BaseModel):
    seller_id: UUID
    recipient_name: str = Field(min_length=1, max_length=200)
    recipient_phone: str = Field(pattern=r"^\+[1-9][0-9]{7,14}$")
    delivery_address: str = Field(min_length=5, max_length=1000)
    weight_kg: float = Field(gt=0)
    volume_m3: float = Field(gt=0)
    window_earliest: datetime | None = None
    window_latest: datetime | None = None


def _response(order, created: bool) -> dict:
    return {
        "order_id": str(order.id),
        "tracking_token": order.tracking_token,
        "seller_id": str(order.merchant_id),
        "warehouse_id": str(order.warehouse_id) if order.warehouse_id else None,
        "status": order.status.value,
        "created_at": order.created_at,
        "created": created,
    }


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_guest_order(
    payload: CreateOrderRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """Create an unclaimed order for integrations that do not have a customer account."""
    order, created = await create_order(
        db,
        customer_id=None,
        seller_id=payload.seller_id,
        recipient_name=payload.recipient_name,
        recipient_phone=payload.recipient_phone,
        delivery_address=payload.delivery_address,
        weight_kg=payload.weight_kg,
        volume_m3=payload.volume_m3,
        window_earliest=payload.window_earliest,
        window_latest=payload.window_latest,
    )
    return _response(order, created)
