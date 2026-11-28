
import json
from typing import Any

from redis.asyncio import Redis


class FleetStateManager:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client

    async def update_driver(
        self,
        driver_id: str,
        driver_data: dict[str, Any],
    ) -> None:
        key = f"fleet:driver:active:{driver_id}"

        await self.redis.hset(
            key,
            mapping={
                field: (
                    json.dumps(value)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                for field, value in driver_data.items()
                if value is not None
            },
        )

        await self.redis.sadd("fleet:drivers", driver_id)
        await self.redis.expire(key, 12 * 60 * 60)

    async def get_driver(self, driver_id: str) -> dict[str, str]:
        key = f"fleet:driver:active:{driver_id}"
        return await self.redis.hgetall(key)

    async def get_all_driver_ids(self) -> set[str]:
        return await self.redis.smembers("fleet:drivers")

    async def update_route(
        self,
        route_id: str,
        route_data: dict[str, Any],
    ) -> None:
        key = f"fleet:route:{route_id}"

        await self.redis.hset(
            key,
            mapping={
                field: (
                    json.dumps(value)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                for field, value in route_data.items()
                if value is not None
            },
        )

        await self.redis.sadd("fleet:routes:active", route_id)

    async def get_route(self, route_id: str) -> dict[str, str]:
        key = f"fleet:route:{route_id}"
        return await self.redis.hgetall(key)

    async def get_active_route_ids(self) -> set[str]:
        return await self.redis.smembers("fleet:routes:active")

    async def update_route_progress(
        self,
        route_id: str,
        progress_data: dict[str, Any],
    ) -> None:
        key = f"fleet:route:{route_id}"

        await self.redis.hset(
            key,
            mapping={
                field: (
                    json.dumps(value)
                    if isinstance(value, (dict, list))
                    else str(value)
                )
                for field, value in progress_data.items()
                if value is not None
            },
        )
