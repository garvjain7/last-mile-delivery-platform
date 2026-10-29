# THE SECURE DMZ EDGE — COMPLETELY DECOUPLED FROM POSTGRES
# FastAPI application entrypoint for Driver Gateway service.

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from services.driver_gateway.app.ingestion.router import router as ingestion_router

app = FastAPI(title="Driver Gateway API", version="1.0.0")
FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend"
app.mount(
    "/static/shared/js",
    StaticFiles(directory=FRONTEND_DIR / "shared" / "js"),
    name="shared-js",
)
for asset_type in ("css", "js"):
    app.mount(
        f"/static/driver-app/{asset_type}",
        StaticFiles(directory=FRONTEND_DIR / "driver-app" / asset_type),
        name=f"driver-app-{asset_type}",
    )


@app.get("/", include_in_schema=False)
async def driver_app_page():
    return FileResponse(FRONTEND_DIR / "driver-app" / "index.html")

app.include_router(ingestion_router, prefix="/driver", tags=["Driver Ingestion"])

@app.get("/health/live")
async def health_live():
    """Liveness probe confirming the process is running without checking dependencies."""
    return {"status": "live"}

@app.get("/health/ready")
async def health_ready():
    """Readiness probe checking Redis and MinIO connectivity (no Postgres access)."""
    # TODO: Check Redis and MinIO storage connection health
    return {"status": "ready"}
