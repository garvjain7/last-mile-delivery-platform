# Configuration settings loader for Control Tower service.
# Loads environment variables once per-service into a structured config object.

import os
from pydantic import BaseModel

class ControlTowerConfig(BaseModel):
    """Configuration properties for Control Tower service. No database configuration."""
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))

config = ControlTowerConfig()
