# Stateless JWT validation for driver clients
# JWT authentication and verification helpers for driver client sessions.

from typing import Any, Dict, Optional

from jose import JWTError, jwt
from services.driver_gateway.app.config import config

async def verify_driver_jwt(token: str) -> Optional[Dict[str, Any]]:
    """
    Statelessly validate driver client JWT session token.
    Decoupled from Postgres — validates signature and claims only.
    """
    try:
        claims = jwt.decode(
            token,
            config.jwt_secret_key,
            algorithms=["HS256"],
        )
    except JWTError:
        return None

    roles = claims.get("roles")
    driver_id = claims.get("sub")
    if not isinstance(roles, list) or "driver" not in roles or not driver_id:
        return None
    return {**claims, "driver_id": driver_id}
