# FORMERLY ORDERS API — The single entry point for Merchants/Staff
# FastAPI application entrypoint for Core API service.

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import os

from app.auth.router import router as auth_router
from app.orders.router import router as orders_router
from app.staff.router import router as staff_router
from app.home.router import router as home_router

app = FastAPI(title="Core API Service", version="1.0.0")

# Mount frontend directory for static assets (CSS, JS, Images)
frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../../frontend"))
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

app.include_router(home_router, tags=["Home"])
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
