"""Shared order timeline construction for private and public tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

from db_models.models import Order, OrderEvent

STATUS_LABELS = {
    "placed": "The seller is preparing your parcel",
    "sent": "On its way to our delivery hub",
    "pending": "At our hub, being scheduled",
    "assigned": "Scheduled for delivery",
    "out_for_delivery": "Out for delivery",
    "delivered": "Delivered",
    "attempt_failed": "Delivery attempt unsuccessful",
    "returned": "Returned to the seller",
    "cancelled": "Cancelled",
}

_RAIL = (
    ("placed", "Seller preparing"),
    ("sent", "Sent to hub"),
    ("pending", "At our hub"),
    ("assigned", "Scheduled"),
    ("out_for_delivery", "Out for delivery"),
    ("delivered", "Delivered"),
    ("returned", "Complete"),
)
_RAIL_INDEX = {
    "placed": 0,
    "sent": 1,
    "pending": 2,
    "assigned": 3,
    "out_for_delivery": 4,
    "attempt_failed": 4,
    "delivered": 5,
    "returned": 6,
    "cancelled": 0,
}
_FORWARD_STATUSES = ("placed", "sent", "pending", "assigned", "out_for_delivery", "delivered")


def build_timeline(order: Order, events: Iterable[OrderEvent]) -> dict[str, list[dict[str, Any]]]:
    """Build event history and a lifecycle rail from persisted statuses."""
    ordered_events = sorted(events, key=lambda event: (event.occurred_at, event.id))
    current_status = order.status.value
    current_event = (
        ordered_events[-1]
        if ordered_events and ordered_events[-1].to_status.value == current_status
        else None
    )

    steps: list[dict[str, Any]] = []
    for event in ordered_events:
        status = event.to_status.value
        is_current = event is current_event
        steps.append({
            "status": status,
            "label": STATUS_LABELS.get(status, status.replace("_", " ").title()),
            "at": event.occurred_at.isoformat(),
            "state": "current" if is_current else "done",
        })

    if not steps:
        steps.append({
            "status": current_status,
            "label": STATUS_LABELS.get(current_status, current_status.replace("_", " ").title()),
            "at": order.created_at.isoformat() if order.created_at else None,
            "state": "current",
        })
    elif current_event is None:
        steps.append({
            "status": current_status,
            "label": STATUS_LABELS.get(current_status, current_status.replace("_", " ").title()),
            "at": order.updated_at.isoformat() if order.updated_at else None,
            "state": "current",
        })

    if current_status in _FORWARD_STATUSES:
        current_index_in_flow = _FORWARD_STATUSES.index(current_status)
        for upcoming_status in _FORWARD_STATUSES[current_index_in_flow + 1:]:
            steps.append({
                "status": upcoming_status,
                "label": STATUS_LABELS[upcoming_status],
                "at": None,
                "state": "upcoming",
            })

    current_index = _RAIL_INDEX.get(current_status, 0)
    rail = []
    for index, (status, label) in enumerate(_RAIL):
        state = "done" if index < current_index else "current" if index == current_index else "upcoming"
        if current_status in {"attempt_failed", "cancelled"} and index == current_index:
            state = "current"
        rail.append({"status": status, "label": label, "state": state})

    return {"steps": steps, "rail": rail}
