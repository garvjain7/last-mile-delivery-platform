"""Shared Redis Streams client and field encoding helpers."""

import json
import os
from collections.abc import Mapping
from typing import Any, Optional
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
            socket_timeout=15.0,
            socket_connect_timeout=5.0
        )
    return _redis_client

async def close_redis_client() -> None:
    """Close the shared Redis client pool."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None

async def add_to_stream(stream_name: str, fields: Mapping[str, Any]) -> str:
    """
    Publish an event to a Redis Stream, retaining approximately 50,000 entries.
    """
    client = await get_redis_client()
    encoded_fields = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            encoded_fields[key] = str(value).lower()
        elif isinstance(value, (dict, list)):
            encoded_fields[key] = json.dumps(value, separators=(",", ":"))
        elif isinstance(value, (str, int, float, bytes)):
            encoded_fields[key] = value
        else:
            raise TypeError(
                f"Unsupported Redis stream field type for {key!r}: {type(value).__name__}"
            )
    return await client.xadd(
        stream_name,
        encoded_fields,
        maxlen=50_000,
        approximate=True,
    )


def decode_stream_fields(
    fields: Mapping[bytes | str, bytes | str],
) -> dict[str, str]:
    """Normalize Redis stream fields from bytes or decoded string responses."""
    return {
        key.decode() if isinstance(key, bytes) else key:
        value.decode() if isinstance(value, bytes) else value
        for key, value in fields.items()
    }
