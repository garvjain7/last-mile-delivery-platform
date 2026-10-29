from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

FRONTEND_DIR = Path(__file__).resolve().parents[4] / "frontend"
PUBLIC_DIR = FRONTEND_DIR / "public"

@router.get("/", summary="Serve the home page")
async def get_home():
    """Serves the main landing page of the platform."""
    return FileResponse(PUBLIC_DIR / "home" / "index.html")

@router.get("/login", summary="Serve the login page")
async def get_login():
    """Serves the login page."""
    return FileResponse(PUBLIC_DIR / "login" / "index.html")


@router.get("/register", summary="Serve the registration page")
async def get_register():
    """Serves the Core API registration page."""
    return FileResponse(PUBLIC_DIR / "register" / "index.html")


@router.get("/reset-password", summary="Serve the password reset page")
async def get_reset_password():
    """Serves the password reset page."""
    return FileResponse(PUBLIC_DIR / "reset-password" / "index.html")


@router.get("/track", summary="Serve the public parcel tracking page")
async def get_track():
    """Serves the public parcel tracking page (no auth required)."""
    return FileResponse(PUBLIC_DIR / "track" / "index.html")
