"""Driver Gateway application assembly; database access belongs to Core API."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from services.driver_gateway.app.driver_api.router import (
    close_core_api_client,
    router as driver_api_router,
)
from services.driver_gateway.app.ingestion.router import router as ingestion_router
from services.driver_gateway.app.routes.frontend import (
    DRIVER_APP_DIR,
    FRONTEND_DIR,
    router as frontend_router,
)
from services.driver_gateway.app.routes.health import router as health_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Close shared upstream clients when the Gateway shuts down."""
    try:
        yield
    finally:
        await close_core_api_client()


app = FastAPI(title="Driver Gateway API", version="1.0.0", lifespan=lifespan)
app.mount(
    "/static/shared/js",
    StaticFiles(directory=FRONTEND_DIR / "shared" / "js"),
    name="shared-js",
)
for asset_type in ("css", "js"):
    app.mount(
        f"/static/driver-app/{asset_type}",
        StaticFiles(directory=DRIVER_APP_DIR / asset_type),
        name=f"driver-app-{asset_type}",
    )

app.include_router(frontend_router)
app.include_router(ingestion_router, prefix="/driver", tags=["Driver Ingestion"])
app.include_router(driver_api_router, tags=["Driver API"])
app.include_router(health_router)
