# JWT and password hashing utilities shared across auth service functions.
# All token creation, verification, and hashing lives here to keep it testable
# without importing FastAPI or SQLAlchemy.

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import bcrypt
from jose import JWTError, jwt

from app.config import config


# ---------------------------------------------------------------------------
# Password hashing (bcrypt)
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of plain. The salt is embedded in the returned string."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time comparison via bcrypt."""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT access tokens (short-lived, 15 min)
# ---------------------------------------------------------------------------

ACCESS_TOKEN_TTL = timedelta(minutes=15)


def create_access_token(user_id: str, roles: List[str]) -> str:
    """Mint a signed JWT carrying user_id and roles.
    Other services validate this token by calling GET /auth/me — they never
    touch the JWT secret themselves."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "roles": roles,
        "iat": now,
        "exp": now + ACCESS_TOKEN_TTL,
    }
    return jwt.encode(payload, config.jwt_secret_key, algorithm=config.jwt_algorithm)


def decode_access_token(token: str) -> Dict:
    """Decode and verify a JWT. Raises JWTError on invalid/expired token."""
    return jwt.decode(token, config.jwt_secret_key, algorithms=[config.jwt_algorithm])


# ---------------------------------------------------------------------------
# Refresh tokens (opaque random, 30 days)
# ---------------------------------------------------------------------------

REFRESH_TOKEN_TTL = timedelta(days=30)


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Return (raw_token, sha256_hash, expires_at).
    Only the hash is stored in Postgres. The raw token is sent to the client once."""
    raw = secrets.token_urlsafe(64)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + REFRESH_TOKEN_TTL
    return raw, token_hash, expires_at


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Password reset tokens (opaque random, 1 hour)
# ---------------------------------------------------------------------------

RESET_TOKEN_TTL = timedelta(hours=1)


def generate_reset_token() -> tuple[str, str, datetime]:
    """Return (raw_token, sha256_hash, expires_at).
    The raw token is embedded in the reset link sent via email.
    Only the hash is stored in Postgres."""
    raw = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw.encode()).hexdigest()
    expires_at = datetime.now(timezone.utc) + RESET_TOKEN_TTL
    return raw, token_hash, expires_at


def hash_reset_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Role → redirect mapping
# ---------------------------------------------------------------------------

# Priority order: highest-privilege role wins when a user holds multiple roles.
_ROLE_PRIORITY = ["admin", "dispatcher", "fleet_manager", "merchant", "driver", "customer"]

# Where each role lands after login. Endpoints are canonical future paths —
# frontend enforces these, backend only sends the advisory string.
_ROLE_REDIRECT: Dict[str, str] = {
    "admin":         "/staff/orders",
    "dispatcher":    "/control-tower",
    "fleet_manager": "/fleet/drivers",
    "merchant":      "/orders",
    "driver":        "/driver/route/active",
    "customer":      "/orders/my",
}


def redirect_for_roles(roles: List[str]) -> str:
    """Return the redirect path for the highest-priority role in the list."""
    for role in _ROLE_PRIORITY:
        if role in roles:
            return _ROLE_REDIRECT[role]
    # Fallback — should not happen if every user has at least one role.
    return "/"
