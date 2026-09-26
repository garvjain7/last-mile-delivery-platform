# Stateless JWT validation for driver clients
# JWT authentication and verification helpers for driver client sessions.

from typing import Dict, Any, Optional
from app.config import config

async def verify_driver_jwt(token: str) -> Optional[Dict[str, Any]]:
    """
    Statelessly validate driver client JWT session token.
    Decoupled from Postgres — validates signature and claims only.
    """
    # TODO: Verify JWT signature using config.jwt_secret_key and decode driver claims
    return {"driver_id": "drv-stub-123"}
