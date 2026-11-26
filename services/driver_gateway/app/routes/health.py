"""Driver Gateway liveness and readiness endpoints."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, status
from minio.error import MinioException, S3Error
from redis.exceptions import RedisError
from urllib3.exceptions import HTTPError as StorageHTTPError

from services.driver_gateway.app.storage.minio_client import MinIOStorageClient
from streaming.client import get_redis_client

logger = logging.getLogger(__name__)
router = APIRouter()
storage_client = MinIOStorageClient()


@router.get("/health/live")
async def health_live():
    """Report process liveness without checking dependencies."""
    return {"status": "live"}


@router.get("/health/ready")
async def health_ready():
    """Check that Redis and the configured MinIO evidence bucket are reachable."""
    dependencies = {"redis": "ready", "minio": "ready"}
    try:
        redis_client = await get_redis_client()
        if not await redis_client.ping():
            dependencies["redis"] = "unavailable"
    except RedisError:
        logger.exception("Redis readiness check failed.")
        dependencies["redis"] = "unavailable"

    try:
        bucket_exists = await asyncio.to_thread(
            storage_client.client.bucket_exists,
            storage_client.bucket_name,
        )
        if not bucket_exists:
            dependencies["minio"] = "unavailable"
    except (MinioException, S3Error, StorageHTTPError, OSError):
        logger.exception("MinIO readiness check failed.")
        dependencies["minio"] = "unavailable"

    if "unavailable" in dependencies.values():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "dependencies": dependencies},
        )
    return {"status": "ready", "dependencies": dependencies}
