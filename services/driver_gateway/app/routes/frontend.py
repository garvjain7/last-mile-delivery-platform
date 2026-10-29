"""Serve the driver PWA shell and static assets."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()
FRONTEND_DIR = Path(__file__).resolve().parents[4] / "frontend"
DRIVER_APP_DIR = FRONTEND_DIR / "driver-app"


@router.get("/", include_in_schema=False)
async def driver_app_page():
    return FileResponse(DRIVER_APP_DIR / "index.html")


@router.get("/driver-app-sw.js", include_in_schema=False)
async def driver_app_service_worker():
    return FileResponse(
        DRIVER_APP_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@router.get("/driver-app-manifest.webmanifest", include_in_schema=False)
async def driver_app_manifest():
    return FileResponse(
        DRIVER_APP_DIR / "manifest.webmanifest",
        media_type="application/manifest+json",
    )
