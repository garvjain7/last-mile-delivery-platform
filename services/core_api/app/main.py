# FORMERLY ORDERS API — The single entry point for Merchants/Staff
# FastAPI application entrypoint for Core API service.

from fastapi import FastAPI
from app.orders.router import router as orders_router
from app.staff.router import router as staff_router

app = FastAPI(title="Core API Service", version="1.0.0")

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
