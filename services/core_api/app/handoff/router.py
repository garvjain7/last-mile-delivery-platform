"""
Merchant hand-off and hub receipt (docs/end-to-end-system-flow.md steps 3-4).

    POST /api/merchant/orders/{order_id}/send     placed -> sent
         Merchant presses Send; the nearest ACTIVE warehouse whose service
         radius covers the drop-off is chosen with a PostGIS KNN (<->) query.
    POST /api/hub/orders/{order_id}/receive       sent -> pending
         Staff of that warehouse confirm the parcel arrived.
    GET  /api/merchant/orders?status=placed       the merchant's own orders
    GET  /api/driver/route                        the signed-in rider's route and stops

Each status change and its order_events row commit in one transaction.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import User, UserRole
from services.core_api.app.admin.security import csrf_check
from services.core_api.app.auth.security import decode_access_token
from services.core_api.app.database.connection import get_db_session

router = APIRouter(tags=["Hand-off"])


def require_role(role: UserRole):
    """Dependency: an active, unlocked user holding `role` (re-read from the DB)."""

    async def dependency(
        request: Request,
        access_token: Optional[str] = Cookie(None),
        db: AsyncSession = Depends(get_db_session),
    ) -> User:
        token = access_token
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header.removeprefix("Bearer ")
        if not token:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No session token.")
        try:
            user_id = uuid.UUID(decode_access_token(token)["sub"])
        except (JWTError, KeyError, ValueError):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token.")
        user = await db.scalar(select(User).options(selectinload(User.roles)).where(User.id == user_id))
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not available.")
        if role not in {r.role for r in user.roles}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"{role.value} role required.")
        return user

    return dependency


async def _locked_order(db: AsyncSession, order_id: uuid.UUID):
    row = (await db.execute(text("""
        SELECT id, merchant_id, warehouse_id, status::text AS status
        FROM orders WHERE id = :id FOR UPDATE"""), {"id": order_id})).mappings().first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found.")
    return row


async def _record(db, order_id, from_status, to_status, actor_id):
    await db.execute(text("""
        INSERT INTO order_events (order_id, from_status, to_status, actor_user_id)
        VALUES (:o, CAST(:f AS order_status), CAST(:t AS order_status), :a)"""),
        {"o": order_id, "f": from_status, "t": to_status, "a": actor_id})


@router.get("/api/merchant/orders")
async def list_merchant_orders(
    status_filter: str = "placed",
    merchant: User = Depends(require_role(UserRole.merchant)),
    db: AsyncSession = Depends(get_db_session),
):
    rows = (await db.execute(text("""
        SELECT o.id, o.merchant_order_ref, o.tracking_token, o.status::text AS status, o.delivery_address, o.created_at
        FROM orders o JOIN merchant_members mm ON mm.merchant_id = o.merchant_id AND mm.user_id = :u
        WHERE o.status::text = :s ORDER BY o.created_at DESC LIMIT 100"""),
        {"u": merchant.id, "s": status_filter})).mappings().all()
    return {"orders": [dict(r, id=str(r["id"])) for r in rows]}


@router.post("/api/merchant/orders/{order_id}/send", dependencies=[Depends(csrf_check)])
async def send_order(
    order_id: uuid.UUID,
    merchant: User = Depends(require_role(UserRole.merchant)),
    db: AsyncSession = Depends(get_db_session),
):
    order = await _locked_order(db, order_id)
    member = await db.scalar(text(
        "SELECT 1 FROM merchant_members WHERE user_id = :u AND merchant_id = :m"),
        {"u": merchant.id, "m": order["merchant_id"]})
    if not member:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found.")
    if order["status"] != "placed":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Order is {order['status']}, not placed.")
    hub = (await db.execute(text("""
        SELECT w.id, w.code, w.name, ST_Distance(w.location, o.delivery_location) AS distance_m
        FROM warehouses w, orders o
        WHERE o.id = :id AND w.is_active
          AND (w.service_radius_m IS NULL OR ST_DWithin(w.location, o.delivery_location, w.service_radius_m))
        ORDER BY w.location <-> o.delivery_location LIMIT 1"""), {"id": order_id})).mappings().first()
    if hub is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "No active warehouse serves this address; the order stays placed.")
    await db.execute(text("UPDATE orders SET status = 'sent', warehouse_id = :w, updated_at = now() WHERE id = :id"),
                     {"w": hub["id"], "id": order_id})
    await _record(db, order_id, "placed", "sent", merchant.id)
    await db.commit()
    return {"order_id": str(order_id), "status": "sent",
            "warehouse": {"id": str(hub["id"]), "code": hub["code"], "name": hub["name"],
                          "distance_m": round(hub["distance_m"])}}


@router.post("/api/hub/orders/{order_id}/receive", dependencies=[Depends(csrf_check)])
async def receive_order(
    order_id: uuid.UUID,
    staff: User = Depends(require_role(UserRole.dispatcher)),
    db: AsyncSession = Depends(get_db_session),
):
    order = await _locked_order(db, order_id)
    works_there = await db.scalar(text(
        "SELECT 1 FROM warehouse_staff WHERE user_id = :u AND warehouse_id = :w"),
        {"u": staff.id, "w": order["warehouse_id"]})
    if not works_there:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This parcel is not for your warehouse.")
    if order["status"] != "sent":
        raise HTTPException(status.HTTP_409_CONFLICT, f"Order is {order['status']}, not sent.")
    await db.execute(text("UPDATE orders SET status = 'pending', updated_at = now() WHERE id = :id"), {"id": order_id})
    await _record(db, order_id, "sent", "pending", staff.id)
    await db.commit()
    return {"order_id": str(order_id), "status": "pending"}


@router.get("/api/driver/route")
async def my_route(
    driver: User = Depends(require_role(UserRole.driver)),
    db: AsyncSession = Depends(get_db_session),
):
    """The signed-in rider's planned or in-progress route with its stops in order."""
    route = (await db.execute(text("""
        SELECT r.id, r.status::text AS status, w.code AS warehouse_code
        FROM routes r JOIN warehouses w ON w.id = r.warehouse_id
        WHERE r.driver_id = :d AND r.status IN ('planned', 'in_progress')
        ORDER BY r.created_at DESC LIMIT 1"""), {"d": driver.id})).mappings().first()
    if route is None:
        return {"route": None}
    stops = (await db.execute(text("""
        SELECT s.sequence, s.status::text AS status, s.order_id, o.tracking_token, o.merchant_order_ref,
               o.delivery_address, ST_Y(s.planned_location::geometry) AS lat, ST_X(s.planned_location::geometry) AS lon,
               s.planned_arrival_at
        FROM route_stops s JOIN orders o ON o.id = s.order_id
        WHERE s.route_id = :r ORDER BY s.sequence"""), {"r": route["id"]})).mappings().all()
    return {"route": {"id": str(route["id"]), "status": route["status"], "warehouse_code": route["warehouse_code"],
                      "stops": [dict(s, order_id=str(s["order_id"])) for s in stops]}}
