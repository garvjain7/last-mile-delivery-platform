import asyncio

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError

from services.driver_gateway.app.routes import health


class FakeRedis:
    def __init__(self, available):
        self.available = available

    async def ping(self):
        if not self.available:
            raise RedisError("unavailable")
        return True


class FakeMinIOClient:
    def __init__(self, bucket_available):
        self.bucket_available = bucket_available

    def bucket_exists(self, bucket_name):
        assert bucket_name == "pod-photos"
        return self.bucket_available


class FakeStorage:
    bucket_name = "pod-photos"

    def __init__(self, bucket_available):
        self.client = FakeMinIOClient(bucket_available)


@pytest.mark.parametrize(
    ("redis_available", "bucket_available"),
    [(True, True), (False, True), (True, False), (False, False)],
)
def test_readiness_checks_redis_and_minio(monkeypatch, redis_available, bucket_available):
    async def get_client():
        return FakeRedis(redis_available)

    monkeypatch.setattr(health, "get_redis_client", get_client)
    monkeypatch.setattr(health, "storage_client", FakeStorage(bucket_available))

    if redis_available and bucket_available:
        result = asyncio.run(health.health_ready())
        assert result == {
            "status": "ready",
            "dependencies": {"redis": "ready", "minio": "ready"},
        }
    else:
        with pytest.raises(HTTPException) as error_info:
            asyncio.run(health.health_ready())
        assert error_info.value.status_code == 503
        assert error_info.value.detail["dependencies"]["redis"] == (
            "ready" if redis_available else "unavailable"
        )
        assert error_info.value.detail["dependencies"]["minio"] == (
            "ready" if bucket_available else "unavailable"
        )
