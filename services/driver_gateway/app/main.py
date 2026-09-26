# THE SECURE DMZ EDGE — COMPLETELY DECOUPLED FROM POSTGRES
# FastAPI application entrypoint for Driver Gateway service.

from fastapi import FastAPI
from app.ingestion.router import router as ingestion_router

app = FastAPI(title="Driver Gateway API", version="1.0.0")

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
