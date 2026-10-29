"""Database-gated role panels served from the private frontend tree."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Cookie, Depends, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db_models.models import User
from services.core_api.app.admin.security import ADMIN_SECURITY_HEADERS
from services.core_api.app.auth.security import decode_access_token
from services.core_api.app.auth.dependencies import resolve_self_customer
from services.core_api.app.database.connection import get_db_session

router = APIRouter()
PANEL_ROOT = Path(__file__).resolve().parents[3] / "frontend" / "core-api"
ADMIN_PAGE_FILES = {
    "overview": "index.html",
    "drivers": "drivers.html",
    "users": "users.html",
    "merchants": "merchants.html",
    "warehouses": "warehouses.html",
    "orders": "orders.html",
    "activity": "activity.html",
}


async def serve_panel(
    role: str,
    file: Path,
    request: Request,
    access_token: Optional[str],
    db: AsyncSession,
) -> Response:
    """Serve one role panel after resolving the active user and roles from Postgres."""
    if not access_token:
        return RedirectResponse(
            url=f"/login?next={quote(request.url.path, safe='/')}",
            status_code=302,
            headers=ADMIN_SECURITY_HEADERS,
        )

    try:
        payload = decode_access_token(access_token)
        user_id = uuid.UUID(payload.get("sub", ""))
    except (JWTError, ValueError, TypeError, AttributeError):
        return RedirectResponse(
            url=f"/login?next={quote(request.url.path, safe='/')}",
            status_code=302,
            headers=ADMIN_SECURITY_HEADERS,
        )

    user = await db.scalar(
        select(User)
        .options(selectinload(User.roles))
        .where(User.id == user_id)
    )
    if user is None or not user.is_active:
        return RedirectResponse(
            url=f"/login?next={quote(request.url.path, safe='/')}",
            status_code=302,
            headers=ADMIN_SECURITY_HEADERS,
        )

    now = datetime.now(timezone.utc)
    if user.locked_until is not None and user.locked_until > now:
        return RedirectResponse(
            url=f"/login?next={quote(request.url.path, safe='/')}",
            status_code=302,
            headers=ADMIN_SECURITY_HEADERS,
        )

    roles = {user_role.role.value for user_role in user.roles}
    if role not in roles:
        return PlainTextResponse("Access denied", status_code=403, headers=ADMIN_SECURITY_HEADERS)

    if not file.is_file():
        return Response(status_code=404, headers=ADMIN_SECURITY_HEADERS)
    return FileResponse(file, headers=ADMIN_SECURITY_HEADERS)


async def serve_panel_asset(
    role: str,
    asset_path: str,
    request: Request,
    access_token: Optional[str],
    db: AsyncSession,
) -> Response:
    asset_root = (PANEL_ROOT / role.replace("_", "-")).resolve()
    if asset_path == "css/panel.css":
        asset_root = (PANEL_ROOT / "shared").resolve()
    asset_file = (asset_root / asset_path).resolve()
    try:
        asset_file.relative_to(asset_root)
    except ValueError:
        return Response(status_code=404, headers=ADMIN_SECURITY_HEADERS)
    return await serve_panel(role, asset_file, request, access_token, db)


async def serve_customer_panel(
    file: Path,
    request: Request,
    access_token: Optional[str],
    db: AsyncSession,
    user_id: Optional[str] = None,
) -> Response:
    """Serve a customer page or asset only to the matching active customer."""
    if not access_token:
        return RedirectResponse(
            url=f"/login?next={quote(request.url.path, safe='/')}",
            status_code=302,
            headers=ADMIN_SECURITY_HEADERS,
        )
    try:
        decode_access_token(access_token)
        path_user_id = uuid.UUID(user_id) if user_id is not None else None
    except (JWTError, ValueError, TypeError, AttributeError):
        return RedirectResponse(
            url=f"/login?next={quote(request.url.path, safe='/')}",
            status_code=302,
            headers=ADMIN_SECURITY_HEADERS,
        )
    customer = await resolve_self_customer(path_user_id, access_token, db)
    if customer is None:
        return Response(status_code=404, headers=ADMIN_SECURITY_HEADERS)
    if not file.is_file():
        return Response(status_code=404, headers=ADMIN_SECURITY_HEADERS)
    return FileResponse(file, headers=ADMIN_SECURITY_HEADERS)


@router.get("/users/assets/{asset_path:path}", include_in_schema=False)
async def customer_panel_asset(
    asset_path: str,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    customer_root = (PANEL_ROOT / "customer").resolve()
    asset_file = (customer_root / asset_path).resolve()
    try:
        asset_file.relative_to(customer_root)
    except ValueError:
        return Response(status_code=404, headers=ADMIN_SECURITY_HEADERS)
    return await serve_customer_panel(asset_file, request, access_token, db)


@router.get("/users/{user_id}/orders/{order_id}", include_in_schema=False)
async def customer_order_page(
    user_id: str,
    order_id: str,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_customer_panel(PANEL_ROOT / "customer" / "order.html", request, access_token, db, user_id)


@router.get("/users/{user_id}/orders", include_in_schema=False)
async def customer_orders_page(
    user_id: str,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_customer_panel(PANEL_ROOT / "customer" / "orders.html", request, access_token, db, user_id)


@router.get("/users/{user_id}/request", include_in_schema=False)
async def customer_request_page(
    user_id: str,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_customer_panel(PANEL_ROOT / "customer" / "request.html", request, access_token, db, user_id)


@router.get("/users/{user_id}", include_in_schema=False)
async def customer_home_page(
    user_id: str,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_customer_panel(PANEL_ROOT / "customer" / "index.html", request, access_token, db, user_id)


@router.get("/admin/assets/{asset_path:path}", include_in_schema=False)
async def admin_panel_asset(
    asset_path: str,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_panel_asset("admin", asset_path, request, access_token, db)


@router.get("/admin", include_in_schema=False)
async def admin_panel(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_panel("admin", PANEL_ROOT / "admin" / ADMIN_PAGE_FILES["overview"], request, access_token, db)


@router.get("/admin/{page_name}", include_in_schema=False)
async def admin_subpage(
    page_name: str,
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    filename = ADMIN_PAGE_FILES.get(page_name)
    if filename is None or page_name == "overview":
        return Response(status_code=404, headers=ADMIN_SECURITY_HEADERS)
    return await serve_panel("admin", PANEL_ROOT / "admin" / filename, request, access_token, db)


@router.get("/merchant/assets/{asset_path:path}", include_in_schema=False)
async def merchant_panel_asset(asset_path: str, request: Request, access_token: Optional[str] = Cookie(None), db: AsyncSession = Depends(get_db_session)) -> Response:
    return await serve_panel_asset("merchant", asset_path, request, access_token, db)


@router.get("/merchant", include_in_schema=False)
async def merchant_panel(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_panel("merchant", PANEL_ROOT / "merchant" / "index.html", request, access_token, db)


@router.get("/dispatcher", include_in_schema=False)
async def dispatcher_panel(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_panel("dispatcher", PANEL_ROOT / "dispatcher" / "index.html", request, access_token, db)


@router.get("/dispatcher/assets/{asset_path:path}", include_in_schema=False)
async def dispatcher_panel_asset(asset_path: str, request: Request, access_token: Optional[str] = Cookie(None), db: AsyncSession = Depends(get_db_session)) -> Response:
    return await serve_panel_asset("dispatcher", asset_path, request, access_token, db)


@router.get("/fleet-manager", include_in_schema=False)
async def fleet_manager_panel(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_panel("fleet_manager", PANEL_ROOT / "fleet-manager" / "index.html", request, access_token, db)


@router.get("/fleet-manager/assets/{asset_path:path}", include_in_schema=False)
async def fleet_manager_panel_asset(asset_path: str, request: Request, access_token: Optional[str] = Cookie(None), db: AsyncSession = Depends(get_db_session)) -> Response:
    return await serve_panel_asset("fleet_manager", asset_path, request, access_token, db)


@router.get("/driver", include_in_schema=False)
async def driver_panel(
    request: Request,
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> Response:
    return await serve_panel("driver", PANEL_ROOT / "driver" / "index.html", request, access_token, db)


@router.get("/driver/assets/{asset_path:path}", include_in_schema=False)
async def driver_panel_asset(asset_path: str, request: Request, access_token: Optional[str] = Cookie(None), db: AsyncSession = Depends(get_db_session)) -> Response:
    return await serve_panel_asset("driver", asset_path, request, access_token, db)
