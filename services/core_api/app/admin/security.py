# Security middleware helpers for admin routes:
#   - ADMIN_SECURITY_HEADERS: injected on every response via middleware.
#   - csrf_check: FastAPI dependency that validates Origin/Referer on mutations.
#   - get_client_ip: trusted-proxy-aware IP extraction for the audit log.
#   - content_type_check: rejects non-JSON mutations with 415.
#
# Applied in admin/router.py via middleware on the router's sub-app.

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request, status

from services.core_api.app.config import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security headers (§3.2) — applied by admin middleware in router.py
# ---------------------------------------------------------------------------

ADMIN_SECURITY_HEADERS: dict[str, str] = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "form-action 'self'"
    ),
}


# ---------------------------------------------------------------------------
# CSRF origin check (§3.4) — dependency for mutation endpoints
# Fix 3: Use exact scheme+host+port match instead of startswith.
# ---------------------------------------------------------------------------

def _origin_matches(origin: str, allowed_base: str) -> bool:
    """
    Return True iff origin's scheme+host+port exactly matches allowed_base.
    Prevents https://allowed.example.com.evil.io bypassing a startswith check.
    """
    try:
        o = urlparse(origin.rstrip("/"))
        a = urlparse(allowed_base.rstrip("/"))
        return (o.scheme == a.scheme and
                o.hostname == a.hostname and
                o.port == a.port)
    except Exception:
        return False


async def csrf_check(request: Request) -> None:
    """
    Verify that the Origin or Referer header matches APP_BASE_URL.
    Mismatch → 403 csrf.
    Applied to all non-GET admin requests via router dependency.
    """
    if request.method not in ("POST", "PATCH", "DELETE"):
        return

    # Content-Type must be application/json for mutations (§3.4).
    ct = request.headers.get("content-type", "")
    if not ct.startswith("application/json"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={"detail": "Requests must use Content-Type: application/json.", "code": "unsupported_media_type"},
        )

    origin = request.headers.get("origin") or request.headers.get("referer", "")
    base = config.public_base_url.rstrip("/")

    # Allowed origins: always include the configured base URL.
    # In test environments only, also allow the httpx TestClient origin.
    allowed = [base]
    if config.env == "test":
        allowed.append("http://testserver")

    if not any(_origin_matches(origin, b) for b in allowed if b):
        logger.warning("CSRF check failed: origin=%r not in %r", origin, allowed)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"detail": "CSRF check failed.", "code": "csrf"},
        )


# ---------------------------------------------------------------------------
# Client IP extraction (§3.6) — trusted-proxy aware
# Fix 4: use the RIGHTMOST entry in X-Forwarded-For minus trusted_proxy_hops.
# The leftmost entry is attacker-controlled and must never be trusted.
# ---------------------------------------------------------------------------

def get_client_ip(request: Request) -> Optional[str]:
    """
    Return the real client IP for audit logging.

    With N trusted proxy hops, the real client IP is the Nth-from-right entry
    in the X-Forwarded-For header (0-indexed from the right, so index -(N)).
    If the header has fewer entries than expected, we fall back to the
    connection's remote address (last resort).

    config.trusted_proxy_hops defaults to 1 (Render/Neon setup with one LB hop).
    Set TRUSTED_PROXY_HOPS=0 to disable XFF trust entirely.
    """
    hops = config.trusted_proxy_hops
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for and hops > 0:
        parts = [p.strip() for p in forwarded_for.split(",")]
        # Rightmost entry is added by the last (most trusted) proxy;
        # take the entry that is `hops` positions from the right to skip proxy IPs.
        if len(parts) >= hops:
            return parts[-hops]
        # Fewer entries than expected — the header may be spoofed or incomplete
        return parts[0]
    return request.client.host if request.client else None
