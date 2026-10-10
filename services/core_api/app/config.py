# Configuration settings loader for Core API service.
# Loads environment variables once per-service into a structured config object.

import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class CoreAPIConfig(BaseModel):
    """Configuration properties for Core API service."""

    # --- Database ---
    database_url: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/lastMileDB")
    postgres_pool_size: int = int(os.getenv("POSTGRES_POOL_SIZE", "2"))
    postgres_max_overflow: int = int(os.getenv("POSTGRES_MAX_OVERFLOW", "3"))

    # --- Redis ---
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379")

    # --- Geocoding ---
    nominatim_url: str = os.getenv("NOMINATIM_URL", "http://localhost:8080")

    # --- JWT (access tokens) ---
    jwt_secret_key: str = os.getenv("JWT_SECRET_KEY", "supersecretkey_change_in_production")
    jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "HS256")

    # --- SMTP (password reset emails) ---
    # SMTP_USER and SMTP_PASSWORD should be app passwords set in the environment.
    smtp_host: str = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")

    # --- Public base URL (used to construct password-reset links in emails) ---
    public_base_url: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    # --- Cookies ---
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"


config = CoreAPIConfig()
