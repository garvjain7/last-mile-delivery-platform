# Configuration settings loader for Routing Worker service.
# Loads environment variables once per-service into a structured config object.

import os
from typing import Optional
from pydantic import BaseModel

class RoutingWorkerConfig(BaseModel):
    """Configuration properties for Routing Worker service."""
    postgres_user: str = os.getenv("POSTGRES_USER", "postgres")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    postgres_db: str = os.getenv("POSTGRES_DB", "lastMileDB")
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_pool_size: int = int(os.getenv("POSTGRES_POOL_SIZE", "10"))
    postgres_max_overflow: int = int(os.getenv("POSTGRES_MAX_OVERFLOW", "20"))
    postgres_command_timeout: float = float(os.getenv("POSTGRES_COMMAND_TIMEOUT", "5.0"))
    database_url: Optional[str] = os.getenv("DATABASE_URL")
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    osrm_url: str = os.getenv("OSRM_URL", "http://localhost:5000")
    osrm_connect_timeout: float = float(os.getenv("OSRM_CONNECT_TIMEOUT", "3.0"))
    osrm_read_timeout: float = float(os.getenv("OSRM_READ_TIMEOUT", "10.0"))
    osrm_write_timeout: float = float(os.getenv("OSRM_WRITE_TIMEOUT", "5.0"))
    vroom_url: str = os.getenv("VROOM_URL", "http://localhost:3000")
    vroom_connect_timeout: float = float(os.getenv("VROOM_CONNECT_TIMEOUT", "3.0"))
    vroom_read_timeout: float = float(os.getenv("VROOM_READ_TIMEOUT", "15.0"))
    vroom_write_timeout: float = float(os.getenv("VROOM_WRITE_TIMEOUT", "5.0"))

config = RoutingWorkerConfig()
