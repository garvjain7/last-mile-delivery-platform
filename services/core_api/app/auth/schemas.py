# Pydantic request/response schemas for auth endpoints.
# Field names are verbatim schema.sql column names — no camelCase aliases.

import re
from typing import List, Optional

from pydantic import BaseModel, EmailStr, field_validator


# ---------------------------------------------------------------------------
# Registration — role is NOT a field here.
# Which endpoint you call determines the role:
#   POST /auth/register/customer  → role = "customer"
#   POST /auth/register/driver    → role = "driver"
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    """Registration payload. Exactly one of email or phone is required."""

    full_name: str
    password: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None  # E.164 format: +[1-9][0-9]{7,14}

    @field_validator("phone")
    @classmethod
    def phone_e164(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not re.match(r"^\+[1-9][0-9]{7,14}$", v):
            raise ValueError("phone must be in E.164 format e.g. +919876543210")
        return v

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


# ---------------------------------------------------------------------------
# Internal token carrier — never sent to the browser as JSON.
# The router extracts the token strings from here and writes them to
# httpOnly cookies. The browser never sees the raw token values.
# ---------------------------------------------------------------------------

class _InternalTokenPair(BaseModel):
    access_token: str
    refresh_token: str
    redirect_to: str
    user_id: str
    roles: List[str]


# ---------------------------------------------------------------------------
# SessionInfo — what the browser receives in the response body after
# register / login / refresh. Tokens are NOT here; they are in httpOnly cookies.
# ---------------------------------------------------------------------------

class SessionInfo(BaseModel):
    """Browser-facing session payload. Tokens travel only in httpOnly cookies."""

    user_id: str
    roles: List[str]
    # Advisory: frontend should navigate here after login/register.
    redirect_to: str


# ---------------------------------------------------------------------------
# Login (all roles)
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    """Login by email or phone + password. Exactly one identifier required."""

    password: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------

class ForgotPasswordRequest(BaseModel):
    """User supplies their email or phone to receive a reset token link."""

    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    """User supplies the raw token from the email link and their new password."""

    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("new_password must be at least 8 characters")
        return v


# ---------------------------------------------------------------------------
# Me (token introspection — used by other services via Authorization header,
# and by the browser via the access_token httpOnly cookie)
# ---------------------------------------------------------------------------

class MeResponse(BaseModel):
    """Returned by GET /auth/me.

    Browser clients: request arrives with the access_token cookie.
    Other services (driver-gateway, control-tower): pass Authorization: Bearer <token>.
    Either way, the response is the same resolved identity."""

    user_id: str
    email: Optional[str]
    phone: Optional[str]
    full_name: str
    roles: List[str]
    redirect_to: str
