"""Small, shared validation and cursor helpers for admin routes."""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime
from typing import Iterable


ASSIGNABLE_ROLES = frozenset({"dispatcher", "fleet_manager", "admin"})
DRIVER_SORT_COLS = frozenset({"created_at", "full_name", "status", "last_login_at"})
USER_SORT_COLS = frozenset({"created_at", "full_name", "email", "last_login_at"})
MERCHANT_SORT_COLS = frozenset({"name", "created_at", "orders_total"})
WAREHOUSE_SORT_COLS = frozenset({"code", "name", "created_at", "open_orders"})

_TRACKING_TOKEN = re.compile(r"^[A-Z]{10}$")
_PHONE = re.compile(r"^\+[1-9][0-9]{7,14}$")
_WAREHOUSE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,11}$")

def prepare_q(value: str | None) -> str | None:
    """Trim and escape a substring query for SQL ILIKE; short queries are ignored."""
    if value is None:
        return None
    query = value.strip()[:100]
    if len(query) < 2:
        return None
    return "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"

def validate_sort(sort: str, allowed: Iterable[str]) -> str:
    if sort not in allowed:
        raise ValueError("Unknown sort field.")
    return sort

def validate_dir(direction: str) -> str:
    if direction not in {"asc", "desc"}:
        raise ValueError("Sort direction must be 'asc' or 'desc'.")
    return direction

def validate_warehouse_code(code: str) -> str:
    value = code.strip().upper()
    if not _WAREHOUSE_CODE.fullmatch(value):
        raise ValueError("Warehouse code must be 2-12 uppercase letters, digits, '_' or '-'.")
    return value

def validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90):
        raise ValueError("Latitude must be between -90 and 90.")
    if not (-180 <= longitude <= 180):
        raise ValueError("Longitude must be between -180 and 180.")

def classify_q(value: str) -> str | None:
    query = value.strip()
    if _TRACKING_TOKEN.fullmatch(query.upper()):
        return "tracking_token"
    if _PHONE.fullmatch(query):
        return "phone"
    return None

def encode_cursor(timestamp: datetime, identifier: str | int) -> str:
    payload = json.dumps([timestamp.isoformat(), str(identifier)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")

def decode_cursor(cursor: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        timestamp, identifier = json.loads(raw)
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None or not isinstance(identifier, str):
            raise ValueError
        return parsed, identifier
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid cursor.") from exc

def driver_verify_transition(status: str) -> str:
    if status not in {"pending", "rejected"}:
        raise ValueError("Driver can only be verified from pending or rejected status.")
    return "offline"

def driver_reject_transition(status: str) -> str:
    if status != "pending":
        raise ValueError("Driver can only be rejected from pending status.")
    return "rejected"
