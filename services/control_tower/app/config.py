# Configuration settings loader for Control Tower service.
# Loads environment variables once per-service into a structured config object.

import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

class ControlTowerConfig(BaseModel):
    """Configuration properties for Control Tower service. No database configuration."""
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")

config = ControlTowerConfig()
