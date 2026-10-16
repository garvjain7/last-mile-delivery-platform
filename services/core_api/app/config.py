# Configuration settings loader for Core API service.
# Loads environment variables once per-service into a structured config object.

import os
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()


class CoreAPIConfig(BaseModel):
    """Configuration properties for Core API service."""

    # --- Environment (controls security behaviour) ---
    # Set ENV=production on Render. Anything else is treated as non-production.
    env: str = os.getenv("ENV", "development")

    # --- Database ---
    database_url: str = os.getenv("DATABASE_URL", "")

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

    # --- Admin operations ---
    app_timezone: str = os.getenv("APP_TIMEZONE", "Asia/Kolkata")
    stale_pending_hours: int = int(os.getenv("STALE_PENDING_HOURS", "4"))

    # --- Cookies ---
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

    # --- Proxy trust (Fix 4: rightmost XFF hop) ---
    # Number of trusted reverse-proxy hops between the internet and this service.
    # On Render: 1 (Render's load balancer). In tests: 0 or 1 depending on setup.
    trusted_proxy_hops: int = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))


config = CoreAPIConfig()

if not config.database_url.strip():
    raise RuntimeError("DATABASE_URL is required for the Core API service")

# ---------------------------------------------------------------------------
# Fix 8: Startup deployment guard
# Refuse to start in production if JWT secret is default or cookies are insecure.
# ---------------------------------------------------------------------------
_DEFAULT_SECRET = "supersecretkey_change_in_production"

if config.env == "production":
    if config.jwt_secret_key == _DEFAULT_SECRET:
        raise RuntimeError(
            "FATAL: JWT_SECRET_KEY is the default value. "
            "Set a strong secret in the environment before starting in production."
        )
    if not config.cookie_secure:
        raise RuntimeError(
            "FATAL: COOKIE_SECURE must be true in production. "
            "Set COOKIE_SECURE=true in the environment."
        )
