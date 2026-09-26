# Configuration settings loader for Driver Gateway service.
# Loads environment variables once per-service into a structured config object.

import os
from pydantic import BaseModel

class DriverGatewayConfig(BaseModel):
    """Configuration properties for Driver Gateway service. Completely decoupled from Postgres."""
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    minio_access_key: str = os.getenv("MINIO_ROOT_USER", "minioadmin")
    minio_secret_key: str = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
    jwt_secret_key: str
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")

jwt_secret = os.getenv("JWT_SECRET_KEY")
if not jwt_secret:
    raise ValueError("JWT_SECRET_KEY environment variable is required and must not be empty.")

config = DriverGatewayConfig(jwt_secret_key=jwt_secret)
