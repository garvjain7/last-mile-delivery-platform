from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

FRONTEND_DIR = Path(__file__).resolve().parents[4] / "frontend"

@router.get("/", summary="Serve the home page")
async def get_home():
    """Serves the main landing page of the platform."""
    home_page = FRONTEND_DIR / "home" / "index.html"
    if home_page.exists():
        return FileResponse(home_page)
    return {"detail": "Home page not found."}

@router.get("/login", summary="Serve the login page")
async def get_login():
    """Serves the login page."""
    login_page = FRONTEND_DIR / "login" / "index.html"
    if login_page.exists():
        return FileResponse(login_page)
    return {"detail": "Login page not found."}


@router.get("/register", summary="Serve the registration page")
async def get_register():
    """Serves the Core API registration page."""
    register_page = FRONTEND_DIR / "register" / "index.html"
    if register_page.exists():
        return FileResponse(register_page)
    return {"detail": "Registration page not found."}


@router.get("/reset-password", summary="Serve the password reset page")
async def get_reset_password():
    """Serves the password reset page."""
    reset_page = FRONTEND_DIR / "reset-password" / "index.html"
    if reset_page.exists():
        return FileResponse(reset_page)
    return {"detail": "Reset password page not found."}


@router.get("/track", summary="Serve the public parcel tracking page")
async def get_track():
    """Serves the public parcel tracking page (no auth required)."""
    track_page = FRONTEND_DIR / "track" / "index.html"
    if track_page.exists():
        return FileResponse(track_page)
    return {"detail": "Track page not found."}


@router.get("/workspaces/admin/operations", summary="Serve the admin operations workspace")
async def get_admin_workspace():
    return FileResponse(FRONTEND_DIR / "dashboards" / "admin" / "index.html")


@router.get("/workspaces/dispatcher/live-dispatch", summary="Serve the dispatcher live dispatch workspace")
async def get_dispatcher_workspace():
    return FileResponse(FRONTEND_DIR / "dashboards" / "dispatcher" / "index.html")


@router.get("/workspaces/fleet-manager/driver-operations", summary="Serve the fleet manager workspace")
async def get_fleet_manager_workspace():
    return FileResponse(FRONTEND_DIR / "dashboards" / "fleet-manager" / "index.html")


@router.get("/workspaces/merchant/order-intake", summary="Serve the merchant order workspace")
async def get_merchant_workspace():
    return FileResponse(FRONTEND_DIR / "dashboards" / "merchant" / "index.html")


@router.get("/workspaces/driver/active-route", summary="Serve the driver active route workspace")
async def get_driver_workspace():
    return FileResponse(FRONTEND_DIR / "dashboards" / "driver" / "index.html")


@router.get("/workspaces/customer/delivery-tracking", summary="Serve the customer tracking workspace")
async def get_customer_workspace():
    return FileResponse(FRONTEND_DIR / "dashboards" / "customer" / "index.html")
