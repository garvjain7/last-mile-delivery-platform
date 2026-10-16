# LOW-LATENCY LIVE DASHBOARD SERVICE
# FastAPI application entrypoint for Control Tower live dashboard service.

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from services.control_tower.app.websockets.router import router as ws_router
from services.control_tower.app.consumers.telemetry_consumer import run_telemetry_consumer

app = FastAPI(title="Control Tower API", version="1.0.0")
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
app.mount(
    "/static/shared/js",
    StaticFiles(directory=FRONTEND_DIR / "shared" / "js"),
    name="shared-js",
)
for asset_type in ("css", "js"):
    app.mount(
        f"/static/control-tower/{asset_type}",
        StaticFiles(directory=FRONTEND_DIR / "control-tower" / asset_type),
        name=f"control-tower-{asset_type}",
    )


@app.get("/", include_in_schema=False)
async def control_tower_page():
    return FileResponse(FRONTEND_DIR / "control-tower" / "index.html")

app.include_router(ws_router, tags=["WebSockets & Dispatch"])

@app.on_event("startup")
async def startup_event():
    """Launch telemetry consumer loop in background on application startup."""
    asyncio.create_task(run_telemetry_consumer())

@app.get("/health/live")
async def health_live():
    """Liveness probe confirming the process is running without checking dependencies."""
    return {"status": "live"}

@app.get("/health/ready")
async def health_ready():
    """Readiness probe checking Redis connectivity (no Postgres checks)."""
    # TODO: Check Redis connection status
    return {"status": "ready"}
