"""Order intake, address geocoding and stream publication."""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import datetime

import httpx
from fastapi import HTTPException
from geoalchemy2.elements import WKTElement
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db_models.models import Merchant, Order, OrderEvent, OrderStatus
from services.core_api.app.config import config
from streaming.client import add_to_stream
from streaming.schemas.events import OrderCreatedEvent

logger = logging.getLogger(__name__)


async def geocode_address(address: str) -> tuple[float, float]:
    """Resolve a customer-supplied address through the configured Nominatim API."""
    base_url = config.nominatim_url.rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="Address lookup is unavailable")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            response = await client.get(
                f"{base_url}/search",
                params={"q": address, "format": "jsonv2", "limit": 1},
                headers={"User-Agent": "LastMileDeliveryPlatform/1.0"},
            )
            response.raise_for_status()
            results = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Nominatim address lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail="Address lookup failed") from exc
    if not results:
        raise HTTPException(status_code=422, detail="Delivery address could not be located")
    try:
        return float(results[0]["lon"]), float(results[0]["lat"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Address lookup returned an invalid location") from exc


async def reverse_geocode(longitude: float, latitude: float) -> str:
    """Resolve coordinates to a display address through the configured Nominatim API."""
    base_url = config.nominatim_url.rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="Address lookup is unavailable")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0)) as client:
            response = await client.get(
                f"{base_url}/reverse",
                params={"lat": latitude, "lon": longitude, "format": "jsonv2"},
                headers={"User-Agent": "LastMileDeliveryPlatform/1.0"},
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Nominatim reverse lookup failed: %s", exc)
        raise HTTPException(status_code=502, detail="Address lookup failed") from exc
    address = result.get("display_name") if isinstance(result, dict) else None
    if not address:
        raise HTTPException(status_code=422, detail="No address was found at these coordinates")
    return address


def _tracking_token() -> str:
    return "".join(secrets.choice(string.ascii_uppercase) for _ in range(10))


async def create_order(
    db: AsyncSession,
    *,
    customer_id: uuid.UUID | None,
    seller_id: uuid.UUID,
    recipient_name: str,
    recipient_phone: str,
    delivery_address: str,
    weight_kg: float,
    volume_m3: float,
    idempotency_key: str | None = None,
    window_earliest: datetime | None = None,
    window_latest: datetime | None = None,
) -> tuple[Order, bool]:
    """Create an order and its initial event atomically; return it and whether created."""
    if (window_earliest is None) != (window_latest is None):
        raise HTTPException(status_code=422, detail="Both delivery window values are required together")
    if window_earliest is not None and window_latest <= window_earliest:
        raise HTTPException(status_code=422, detail="Delivery window end must be after its start")

    longitude, latitude = await geocode_address(delivery_address)
    delivery_location = WKTElement(f"POINT({longitude} {latitude})", srid=4326)
    if db.in_transaction():
        await db.rollback()

    try:
        async with db.begin():
            merchant = await db.scalar(
                select(Merchant).where(Merchant.id == seller_id, Merchant.is_active.is_(True))
            )
            if merchant is None:
                raise HTTPException(status_code=422, detail="Seller is not available")

            if customer_id is not None and idempotency_key is not None:
                existing = await db.scalar(select(Order).where(
                    Order.customer_id == customer_id,
                    Order.idempotency_key == idempotency_key,
                ))
                if existing is not None:
                    return existing, False

            tracking_token = _tracking_token()
            order = Order(
                merchant_id=seller_id,
                merchant_order_ref=tracking_token,
                warehouse_id=None,
                customer_id=customer_id,
                idempotency_key=idempotency_key,
                status=OrderStatus.placed,
                recipient_name=recipient_name,
                recipient_phone=recipient_phone,
                delivery_address=delivery_address,
                delivery_location=delivery_location,
                window_earliest=window_earliest,
                window_latest=window_latest,
                weight_kg=weight_kg,
                volume_m3=volume_m3,
                tracking_token=tracking_token,
            )
            db.add(order)
            await db.flush()
            db.add(OrderEvent(
                order_id=order.id,
                from_status=None,
                to_status=OrderStatus.placed,
                actor_user_id=customer_id,
            ))
        created = True
    except IntegrityError as exc:
        if customer_id is None or idempotency_key is None:
            raise
        constraint_name = getattr(exc.orig, "constraint_name", None) or getattr(
            getattr(exc.orig, "diag", None), "constraint_name", None
        )
        if constraint_name != "uq_orders_customer_idempotency_key":
            raise
        await db.rollback()
        existing = await db.scalar(select(Order).where(
            Order.customer_id == customer_id,
            Order.idempotency_key == idempotency_key,
        ))
        if existing is None:
            raise
        return existing, False

    if created:
        window = (
            f"{window_earliest.isoformat()}/{window_latest.isoformat()}"
            if window_earliest is not None and window_latest is not None
            else ""
        )
        event = OrderCreatedEvent(
            event_id=str(uuid.uuid4()),
            order_id=str(order.id),
            merchant_id=str(order.merchant_id),
            warehouse_id=str(order.warehouse_id) if order.warehouse_id else None,
            dropoff_location=f"POINT({longitude} {latitude})",
            dropoff_raw_address=delivery_address,
            time_window=window,
            weight_kg=weight_kg,
            volume_m3=volume_m3,
            created_at=order.created_at.isoformat(),
        )
        try:
            await add_to_stream("orders_stream", event.model_dump(mode="json"))
        except Exception:
            logger.exception("Order %s committed but publishing order.created failed", order.id)
    return order, created
