# FastAPI router for all auth endpoints.
# Thin HTTP layer: validates input, delegates to service.py, maps ValueError → HTTP errors.
# Sets httpOnly cookies for tokens.
#
# POST /auth/register/customer — customer self-service registration
# POST /auth/register/driver   — driver self-service registration
# POST /auth/login             — all roles
# POST /auth/refresh           — exchange refresh token for new token pair
# POST /auth/logout            — clear cookies
# POST /auth/forgot-password   — send reset link to email
# POST /auth/reset-password    — consume token, set new password
# GET  /auth/me                — token introspection (used by other services)

from typing import Optional
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import schemas
from app.auth import service
from app.database.connection import get_db_session
from app.config import config

router = APIRouter()

def _set_auth_cookies(response: Response, tokens: schemas._InternalTokenPair) -> None:
    """Helper to set access and refresh tokens as httpOnly cookies."""
    response.set_cookie(
        key="access_token",
        value=tokens.access_token,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        max_age=15 * 60, # 15 minutes
    )
    response.set_cookie(
        key="refresh_token",
        value=tokens.refresh_token,
        httponly=True,
        secure=config.cookie_secure,
        samesite="lax",
        max_age=7 * 24 * 60 * 60, # 7 days
    )

def _clear_auth_cookies(response: Response) -> None:
    """Helper to clear auth cookies on logout."""
    response.delete_cookie(key="access_token", secure=config.cookie_secure, httponly=True, samesite="lax")
    response.delete_cookie(key="refresh_token", secure=config.cookie_secure, httponly=True, samesite="lax")

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

@router.post(
    "/register/customer",
    response_model=schemas.SessionInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer account",
)
async def register_customer(
    payload: schemas.RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> schemas.SessionInfo:
    """Self-service registration for customers. Automatically logs them in."""
    try:
        tokens = await service.register_user(payload, "customer", db)
        _set_auth_cookies(response, tokens)
        return schemas.SessionInfo(
            user_id=tokens.user_id,
            roles=tokens.roles,
            redirect_to=tokens.redirect_to
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

@router.post(
    "/register/driver",
    response_model=schemas.SessionInfo,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new driver account",
)
async def register_driver(
    payload: schemas.RegisterRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> schemas.SessionInfo:
    """Self-service registration for drivers. Automatically logs them in."""
    try:
        tokens = await service.register_user(payload, "driver", db)
        _set_auth_cookies(response, tokens)
        return schemas.SessionInfo(
            user_id=tokens.user_id,
            roles=tokens.roles,
            redirect_to=tokens.redirect_to
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))


# ---------------------------------------------------------------------------
# Login & Logout
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=schemas.SessionInfo,
    summary="Log in with email or phone + password",
)
async def login(
    payload: schemas.LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db_session),
) -> schemas.SessionInfo:
    """Authenticate by email or phone + password. Sets httpOnly cookies."""
    try:
        tokens = await service.login_user(payload, db)
        _set_auth_cookies(response, tokens)
        return schemas.SessionInfo(
            user_id=tokens.user_id,
            roles=tokens.roles,
            redirect_to=tokens.redirect_to
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Log out by clearing auth cookies",
)
async def logout(response: Response) -> dict:
    """Clear access and refresh cookies."""
    _clear_auth_cookies(response)
    return {"detail": "Logged out successfully"}


# ---------------------------------------------------------------------------
# Token refresh
# ---------------------------------------------------------------------------

@router.post(
    "/refresh",
    response_model=schemas.SessionInfo,
    summary="Exchange a refresh token for a new token pair",
)
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> schemas.SessionInfo:
    """Rotate the refresh token. The raw token comes from the httpOnly refresh_token cookie."""
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token cookie.")
    try:
        tokens = await service.refresh_tokens(refresh_token, db)
        _set_auth_cookies(response, tokens)
        return schemas.SessionInfo(
            user_id=tokens.user_id,
            roles=tokens.roles,
            redirect_to=tokens.redirect_to
        )
    except ValueError as exc:
        _clear_auth_cookies(response)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


# ---------------------------------------------------------------------------
# Forgot & Reset password
# ---------------------------------------------------------------------------

@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password-reset link via email",
)
async def forgot_password(
    payload: schemas.ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Generate a one-time reset token and email a link."""
    try:
        await service.request_password_reset(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    return {"detail": "If an account with that identifier exists, a reset link has been sent."}


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    summary="Consume a reset token and set a new password",
)
async def reset_password(
    payload: schemas.ResetPasswordRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    """Verify the raw reset token, update the password, and revoke all active refresh tokens."""
    try:
        await service.reset_password(payload, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"detail": "Password updated successfully. Please log in again."}


# ---------------------------------------------------------------------------
# Token introspection — GET /auth/me
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=schemas.MeResponse,
    summary="Resolve user identity from access token",
)
async def me(
    authorization: Optional[str] = Header(None, description="Bearer <access_token>"),
    access_token: Optional[str] = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
) -> schemas.MeResponse:
    """Verify the JWT access token and return full user identity including roles.
    Accepts token from Authorization header (services) OR access_token cookie (browser)."""
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    elif access_token:
        token = access_token
        
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing access token in Header or Cookie",
        )
        
    try:
        return await service.get_current_user(token, db)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
