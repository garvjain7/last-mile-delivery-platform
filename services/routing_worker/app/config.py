# Configuration settings loader for Routing Worker service.
# Loads environment variables once per-service into a structured config object.

import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

class RoutingWorkerConfig(BaseModel):
    """Configuration properties for Routing Worker service."""
    database_url: str = os.getenv("DATABASE_URL", "")
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    osrm_url: str = os.getenv("OSRM_URL", "http://localhost:5000")
    vroom_url: str = os.getenv("VROOM_URL", "http://localhost:3000")

config = RoutingWorkerConfig()

if not config.database_url.strip():
    raise RuntimeError("DATABASE_URL is required for the Routing Worker service")
