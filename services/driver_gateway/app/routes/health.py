"""Driver Gateway liveness and readiness endpoints."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health/live")
async def health_live():
    """Report process liveness without checking dependencies."""
    return {"status": "live"}


@router.get("/health/ready")
async def health_ready():
    """Report Gateway readiness; dependency checks are not implemented yet."""
    # TODO: Check Redis and MinIO storage connection health
    return {"status": "ready"}
