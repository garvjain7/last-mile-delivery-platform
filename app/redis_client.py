
from redis.asyncio import Redis

from app.config import REDIS_URL


redis_client = Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=10,
    socket_timeout=15,
    health_check_interval=30,
)


async def close_redis_connection() -> None:
    await redis_client.aclose()
