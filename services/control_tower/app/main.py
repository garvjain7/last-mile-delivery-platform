# LOW-LATENCY LIVE DASHBOARD SERVICE
# FastAPI application entrypoint for Control Tower live dashboard service.

import asyncio
from fastapi import FastAPI
from app.websockets.router import router as ws_router
from app.consumers.telemetry_consumer import run_telemetry_consumer

app = FastAPI(title="Control Tower API", version="1.0.0")

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
