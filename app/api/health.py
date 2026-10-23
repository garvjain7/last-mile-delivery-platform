
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.redis_client import redis_client

router = APIRouter()


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "control-tower",
    }


@router.get("/health/ready")
async def readiness_check():
    try:
        await redis_client.ping()
        return {
            "status": "ready",
            "service": "control-tower",
            "redis": "connected",
        }
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "service": "control-tower",
                "redis": "disconnected",
            },
        )
