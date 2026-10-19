# Public parcel tracking endpoint — no auth required.
# Looks up orders by tracking_token. Returns a customer-safe, structured
# delivery status response for the tracking UI.
#
# Per-IP rate limit: 30 requests / minute (via slowapi).
# Same 404 JSON for any unknown or invalid code (no enumeration leak).

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import Merchant, Order, OrderEvent, OrderStatus
from services.core_api.app.database.connection import get_db_session

logger = logging.getLogger(__name__)

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class TrackingStep(BaseModel):
    label: str
    time: Optional[str] = None
    state: str  # done | now | next | failed
    note: Optional[str] = None


class TrackingDetail(BaseModel):
    label: str
    value: str


class TrackingResponse(BaseModel):
    code: str
    status: str
    tone: str          # ok | warn | bad
    eta_text: str
    steps: List[TrackingStep]
    details: List[TrackingDetail]


# ---------------------------------------------------------------------------
# Step pipeline — five canonical delivery milestones derived from OrderStatus
# ---------------------------------------------------------------------------

# Ordered pipeline of visible delivery stages.
_PIPELINE = ["Confirmed", "Picked", "Loaded", "Transit", "Delivered"]

# Map every OrderStatus enum value to:
#   (pipeline_index_of_current_step, is_terminal_failure)
# Pipeline index -1 means "no step is current" (e.g. cancelled before any step).
_STATUS_MAP: dict[OrderStatus, tuple[int, bool]] = {
    OrderStatus.placed:           (0, False),   # Confirmed
    OrderStatus.sent:             (1, False),   # Picked
    OrderStatus.pending:          (2, False),   # Loaded at the hub
    OrderStatus.assigned:         (2, False),   # Still at the hub, scheduled
    OrderStatus.out_for_delivery: (3, False),   # Transit
    OrderStatus.delivered:        (4, False),   # Delivered
    OrderStatus.attempt_failed:   (3, True),
    OrderStatus.returned:         (3, True),
    OrderStatus.cancelled:        (0, True),
}

# Display labels for status chip
_STATUS_LABELS: dict[OrderStatus, str] = {
    OrderStatus.placed:           "Order confirmed",
    OrderStatus.sent:             "On its way to the delivery hub",
    OrderStatus.pending:          "At the delivery hub",
    OrderStatus.assigned:         "Scheduled for delivery",
    OrderStatus.out_for_delivery: "Out for delivery",
    OrderStatus.delivered:        "Delivered",
    OrderStatus.attempt_failed:   "Delivery attempted",
    OrderStatus.returned:         "Returned to sender",
    OrderStatus.cancelled:        "Cancelled",
}

_TONE: dict[OrderStatus, str] = {
    OrderStatus.placed:           "ok",
    OrderStatus.sent:             "ok",
    OrderStatus.pending:          "ok",
    OrderStatus.assigned:         "ok",
    OrderStatus.out_for_delivery: "ok",
    OrderStatus.delivered:        "ok",
    OrderStatus.attempt_failed:   "warn",
    OrderStatus.returned:         "bad",
    OrderStatus.cancelled:        "bad",
}

_ETA_TEXT: dict[OrderStatus, str] = {
    OrderStatus.placed:           "The seller is preparing your parcel.",
    OrderStatus.sent:             "The seller has sent your parcel to the delivery hub.",
    OrderStatus.pending:          "Your parcel has arrived at the delivery hub and is being scheduled.",
    OrderStatus.assigned:         "Your parcel is scheduled for delivery.",
    OrderStatus.out_for_delivery: "Your parcel is out for delivery today.",
    OrderStatus.delivered:        "Your parcel has been delivered.",
    OrderStatus.attempt_failed:   "We attempted delivery but couldn't complete it. We'll try again or contact you.",
    OrderStatus.returned:         "Your parcel is being returned to the sender.",
    OrderStatus.cancelled:        "This order has been cancelled.",
}


def _build_steps(
    order_status: OrderStatus,
    events: list[OrderEvent],
    order_created_at: Optional[datetime] = None,
) -> List[TrackingStep]:
    """Build the established five-step public pipeline from internal states."""
    current_idx, is_failure = _STATUS_MAP[order_status]
    status_to_pipeline: dict[OrderStatus, int] = {
        OrderStatus.placed: 0,
        OrderStatus.sent: 1,
        OrderStatus.pending: 2,
        OrderStatus.assigned: 2,
        OrderStatus.out_for_delivery: 3,
        OrderStatus.delivered: 4,
        OrderStatus.attempt_failed: 3,
        OrderStatus.returned: 3,
        OrderStatus.cancelled: 0,
    }
    timestamp_by_idx: dict[int, datetime] = {}
    for event in events:
        idx = status_to_pipeline.get(event.to_status)
        if idx is not None and idx not in timestamp_by_idx:
            timestamp_by_idx[idx] = event.occurred_at
    if 0 not in timestamp_by_idx and order_created_at is not None:
        timestamp_by_idx[0] = order_created_at

    steps: List[TrackingStep] = []
    for index, label in enumerate(_PIPELINE):
        if index < current_idx:
            state = "done"
        elif index == current_idx:
            state = "failed" if is_failure else "now"
        else:
            state = "next"

        occurred_at = timestamp_by_idx.get(index)
        time_text = None
        if occurred_at is not None:
            hour = occurred_at.strftime("%I").lstrip("0") or "12"
            time_text = (
                f"{occurred_at.day} {occurred_at.strftime('%b')}, "
                f"{hour}:{occurred_at.strftime('%M')} {occurred_at.strftime('%p').lower()}"
            )

        note = None
        if state == "failed" and order_status == OrderStatus.attempt_failed:
            note = "We couldn't complete the delivery."
        elif state == "failed" and order_status == OrderStatus.returned:
            note = "Parcel is being returned to sender."
        elif state == "failed" and order_status == OrderStatus.cancelled:
            note = "Order was cancelled."
        steps.append(TrackingStep(label=label, time=time_text, state=state, note=note))
    return steps


def _format_window(window_earliest: Optional[datetime], window_latest: Optional[datetime]) -> Optional[str]:
    """Return a human-readable delivery window string, or None."""
    if not window_earliest or not window_latest:
        return None
    def _fmt_time(dt: datetime) -> str:
        hour = dt.strftime("%I").lstrip("0") or "12"
        minute = dt.strftime("%M")
        ampm = dt.strftime("%p").lower()
        return f"{hour}:{minute} {ampm}"
    start = _fmt_time(window_earliest)
    end = _fmt_time(window_latest)
    date = f"{window_earliest.day} {window_earliest.strftime('%b %Y')}"
    return f"{date}, {start}–{end}"


def _safe_area(delivery_address: str) -> str:
    """Extract area/city/pincode from a full address without exposing the street."""
    # Addresses are free-text. We take the last 2–3 comma-separated parts as
    # the publicly-safe portion (area, city, pincode).
    parts = [p.strip() for p in delivery_address.split(",") if p.strip()]
    if len(parts) >= 3:
        return ", ".join(parts[-3:])
    if len(parts) == 2:
        return ", ".join(parts[-2:])
    # Only one part — could be entirely a street; return generic placeholder.
    return "—"


_TRACKING_CODE_REGEX = re.compile(r"^[A-Z]{10}$")


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get(
    "/api/track/{code}",
    response_model=TrackingResponse,
    summary="Public parcel tracking",
    tags=["Tracking"],
)
@limiter.limit("30/minute")
async def track_parcel(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_db_session),
) -> TrackingResponse:
    """
    Public, unauthenticated endpoint to look up a parcel by tracking token.

    Returns a structured tracking payload for the customer-facing UI.
    Returns 404 for any unknown or invalid code (no enumeration differences).
    Rate-limited to 30 requests/minute per IP.
    """
    code = code.strip().upper()
    if not _TRACKING_CODE_REGEX.match(code):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracking code not found.",
        )

    # Single query: order + merchant + events (ordered ascending for timeline).
    stmt = (
        select(Order)
        .where(Order.tracking_token == code)
        .options(
            selectinload(Order.merchant),
            selectinload(Order.events),
        )
    )
    try:
        result = await db.execute(stmt)
    except Exception:
        logger.exception("DB error during tracking lookup for code=%s", code)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error. Please try again.",
        )

    order: Optional[Order] = result.scalar_one_or_none()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tracking code not found.",
        )

    merchant: Merchant = order.merchant
    events: list[OrderEvent] = sorted(order.events, key=lambda e: (e.occurred_at, e.id))

    # Build steps
    steps = _build_steps(order.status, events, order_created_at=order.created_at)

    # Build customer-safe details list
    details: List[TrackingDetail] = []

    if merchant.name:
        details.append(TrackingDetail(label="Sent by", value=merchant.name))

    if order.merchant_order_ref:
        details.append(TrackingDetail(label="Seller's order number", value=order.merchant_order_ref))

    if order.created_at:
        placed_str = f"{order.created_at.day} {order.created_at.strftime('%b %Y')}"
        details.append(TrackingDetail(label="Order placed", value=placed_str))

    safe_area = _safe_area(order.delivery_address)
    details.append(TrackingDetail(label="Delivering to", value=safe_area))

    # Packages: volume_m3 and weight_kg are present on every order.
    # We don't have a package count column — use weight as a proxy label.
    details.append(TrackingDetail(
        label="Weight",
        value=f"{float(order.weight_kg):.2f} kg",
    ))

    window_str = _format_window(order.window_earliest, order.window_latest)
    if window_str:
        details.append(TrackingDetail(label="Delivery window", value=window_str))

    return TrackingResponse(
        code=code,
        status=_STATUS_LABELS[order.status],
        tone=_TONE[order.status],
        eta_text=_ETA_TEXT[order.status],
        steps=steps,
        details=details,
    )
