# Configuration settings loader for Core API service.
# Loads environment variables once per-service into a structured config object.

import os
from pydantic import BaseModel

class CoreAPIConfig(BaseModel):
    """Configuration properties for Core API service."""
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/lastMileDB")
    postgres_pool_size: int = int(os.getenv("POSTGRES_POOL_SIZE", "2"))
    postgres_max_overflow: int = int(os.getenv("POSTGRES_MAX_OVERFLOW", "3"))
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    nominatim_url: str = os.getenv("NOMINATIM_URL", "http://localhost:8080")

config = CoreAPIConfig()
