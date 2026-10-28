# FORMERLY ORDERS API — The single entry point for Merchants/Staff
# FastAPI application entrypoint for Core API service.

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded

from services.core_api.app.auth.router import router as auth_router
from services.core_api.app.orders.router import router as orders_router
from services.core_api.app.customer.router import router as customer_router
from services.core_api.app.tracking.router import limiter as tracking_limiter
from services.core_api.app.tracking.router import router as tracking_router
from services.core_api.app.staff.router import router as staff_router
from services.core_api.app.handoff.router import router as handoff_router
from services.core_api.app.home.router import router as home_router
from services.core_api.app.admin.deps import require_admin
from services.core_api.app.admin.security import csrf_check
from services.core_api.app.admin.routes import activity, drivers, merchants, orders, overview, users, warehouses
from services.core_api.app.panels import router as panels_router
from services.core_api.app.admin.security import ADMIN_SECURITY_HEADERS

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    from sqlalchemy import text
    from services.core_api.app.database.connection import engine

    connect_started = perf_counter()
    async with engine.connect() as connection:
        connect_ms = (perf_counter() - connect_started) * 1000
        query_started = perf_counter()
        await connection.execute(text("SELECT 1"))
        query_ms = (perf_counter() - query_started) * 1000
    logger.info("Postgres startup check connected in %.2f ms; SELECT 1 took %.2f ms", connect_ms, query_ms)
    yield


app = FastAPI(title="Core API Service", version="1.0.0", lifespan=lifespan)
app.state.limiter = tracking_limiter
frontend_dir = Path(__file__).resolve().parents[3] / "frontend"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": str(exc.detail), "code": "error"},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = []
    for error in exc.errors():
        location = error.get("loc", [])
        field = str(location[-1]) if location else "body"
        errors.append({"field": field, "message": error.get("msg", "Invalid value")})
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed.",
            "code": "validation_error",
            "errors": errors,
        },
    )


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please wait a moment.", "code": "rate_limited"},
    )


@app.middleware("http")
async def admin_security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    protected_panel_paths = ("/admin", "/merchant", "/dispatcher", "/fleet-manager", "/driver")
    if (path == "/api/admin" or path.startswith("/api/admin/")) or any(
        path == panel_path or path.startswith(panel_path + "/")
        for panel_path in protected_panel_paths
    ):
        for key, value in ADMIN_SECURITY_HEADERS.items():
            response.headers[key] = value
    if path == "/api/users" or path.startswith("/api/users/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# Keep public URLs mapped directly to their matching asset directories.
# Private panels use their authenticated handlers in panels.py.
app.mount("/static/shared/css", StaticFiles(directory=frontend_dir / "shared" / "css"), name="static-shared-css")
app.mount("/static/shared/js", StaticFiles(directory=frontend_dir / "shared" / "js"), name="static-shared-js")
app.mount("/static/home/css", StaticFiles(directory=frontend_dir / "public" / "home" / "css"), name="static-home-css")
app.mount("/static/home/js", StaticFiles(directory=frontend_dir / "public" / "home" / "js"), name="static-home-js")
app.mount("/static/login/js", StaticFiles(directory=frontend_dir / "public" / "login" / "js"), name="static-login-js")
app.mount("/static/register/js", StaticFiles(directory=frontend_dir / "public" / "register" / "js"), name="static-register-js")
app.mount("/static/reset-password/js", StaticFiles(directory=frontend_dir / "public" / "reset-password" / "js"), name="static-reset-password-js")
app.mount("/static/track/css", StaticFiles(directory=frontend_dir / "public" / "track" / "css"), name="static-track-css")
app.mount("/static/track/js", StaticFiles(directory=frontend_dir / "public" / "track" / "js"), name="static-track-js")


@app.get("/health", tags=["Health"])
async def health():
    """Lightweight liveness response; performs no dependency checks."""
    return {"service": "core-api", "status": "live"}


app.include_router(home_router, tags=["Home"])
app.include_router(tracking_router)
app.include_router(auth_router, prefix="/auth", tags=["Auth"])
app.include_router(orders_router, prefix="/orders", tags=["Orders"])
app.include_router(customer_router)
app.include_router(staff_router, prefix="/staff", tags=["Staff"])
app.include_router(handoff_router)
admin_router = APIRouter(
    prefix="/api/admin",
    dependencies=[Depends(require_admin), Depends(csrf_check)],
)
for route_module in (overview, drivers, users, merchants, warehouses, orders, activity):
    admin_router.include_router(route_module.router)
app.include_router(admin_router)
app.include_router(panels_router)

@app.get("/health/live")
async def health_live():
    """Liveness probe confirming the process is running without checking dependencies."""
    return {"status": "live"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe: checks Postgres (SELECT 1) and Redis (PING)."""
    from services.core_api.app.database.connection import async_session_factory
    from streaming.client import get_redis_client
    errors = []

    # Postgres check
    try:
        async with async_session_factory() as session:
            from sqlalchemy import text as _text
            await session.execute(_text("SELECT 1"))
    except Exception as exc:
        errors.append(f"postgres: {exc}")

    # Redis check
    try:
        redis = await get_redis_client()
        await redis.ping()
    except Exception as exc:
        errors.append(f"redis: {exc}")

    if errors:
        return JSONResponse(status_code=503, content={"status": "not_ready", "errors": errors})
    return {"status": "ready"}
