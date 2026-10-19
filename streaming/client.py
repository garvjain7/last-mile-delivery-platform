# NATIVE REDIS STREAM STRUCTURE
# Unified async connection pool wrapper for redis.asyncio (supports Render Key-Value Valkey 8 & Redis 6/7)

import os
from typing import Optional
import redis.asyncio as redis

# Global connection pool instance
_redis_client: Optional[redis.Redis] = None

async def get_redis_client() -> redis.Redis:
    """
    Get or initialize the shared async Redis client pool.
    Fully compatible with Render Key-Value (Valkey 8) and standard Redis.
    Connects via REDIS_URL environment variable (supports rediss:// or redis://).
    """
    global _redis_client
    if _redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        _redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0
        )
    return _redis_client

async def close_redis_client() -> None:
    """Close the shared Redis client pool."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None

async def add_to_stream(stream_name: str, fields: dict) -> str:
    """
    Publish an event to a Redis Stream, retaining approximately 10,000 entries.
    """
    client = await get_redis_client()
    return await client.xadd(stream_name, fields, maxlen=10_000, approximate=True)
