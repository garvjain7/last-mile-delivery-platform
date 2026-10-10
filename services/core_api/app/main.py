# FORMERLY ORDERS API — The single entry point for Merchants/Staff
# FastAPI application entrypoint for Core API service.

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from services.core_api.app.auth.router import router as auth_router
from services.core_api.app.orders.router import router as orders_router
from services.core_api.app.staff.router import router as staff_router
from services.core_api.app.home.router import router as home_router
from services.core_api.app.tracking.router import router as tracking_router
from services.core_api.app.tracking.router import limiter as tracking_limiter

app = FastAPI(title="Core API Service", version="1.0.0")

# Attach slowapi limiter state so the rate-limit decorator can resolve it.
app.state.limiter = tracking_limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount frontend directory for static assets (CSS, JS, Images)
frontend_dir = Path(__file__).resolve().parents[3] / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

app.include_router(home_router, tags=["Home"])
app.include_router(tracking_router, tags=["Tracking"])
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(orders_router, prefix="/orders", tags=["Orders"])
app.include_router(staff_router, prefix="/staff", tags=["Staff"])

@app.get("/health/live")
async def health_live():
    """Liveness probe confirming the process is running without checking dependencies."""
    return {"status": "live"}

@app.get("/health/ready")
async def health_ready():
    """Readiness probe checking Postgres and Redis connectivity."""
    # TODO: Verify Postgres and Redis connection health
    return {"status": "ready"}
