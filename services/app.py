"""Unified single-process runtime for the last-mile delivery platform.

`services/app.py` is the gateway and process owner. It imports each service's
`main.py`; each service `main.py` imports that service's routers.

Gateway-owned routes:

- `/` serves the home page.
- `/health/live` and `/health/ready` report unified process health.

Service-owned routes:

- Core API keeps auth/login/register/session flows plus orders and staff routes.
- Driver Gateway keeps driver ingestion routes.
- Control Tower keeps live dashboard, rescue, and WebSocket routes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from fastapi import Cookie, Depends, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount
from sqlalchemy.ext.asyncio import AsyncSession

from services.control_tower.app.consumers.telemetry_consumer import run_telemetry_consumer
from services.control_tower.app.main import app as control_tower_app
from services.core_api.app.main import app as core_api_app
from services.core_api.app.database.connection import get_db_session
from services.core_api.app.panels import PANEL_ROOT, serve_panel, serve_panel_asset
from services.driver_gateway.app.main import app as driver_gateway_app
from services.routing_worker.app.main import main as start_routing_worker
from services.simulator.app.main import main as start_simulator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("unified-app")


async def _run_background_task(name: str, awaitable: Awaitable[None]) -> None:
    try:
        await awaitable
    except asyncio.CancelledError:
        logger.info("Stopped %s background task.", name)
        raise
    except Exception:
        logger.exception("%s background task failed.", name)
        raise


@asynccontextmanager
async def lifespan(_: FastAPI):
    background_tasks = {
        "routing-worker": asyncio.create_task(
            _run_background_task("routing-worker", start_routing_worker())
        ),
        "control-tower-telemetry": asyncio.create_task(
            _run_background_task("control-tower-telemetry", run_telemetry_consumer())
        ),
        "simulator": asyncio.create_task(
            _run_background_task("simulator", start_simulator())
        ),
    }
    app.state.background_tasks = background_tasks
    try:
        yield
    finally:
        for task in background_tasks.values():
            task.cancel()
        await asyncio.gather(*background_tasks.values(), return_exceptions=True)


app = FastAPI(
    title="Last-Mile Delivery Platform",
    version="1.0.0",
    lifespan=lifespan,
)

FRONTEND_DIR = ROOT_DIR / "frontend" / "public"

app.mount(
    "/static/status/css",
    StaticFiles(directory=FRONTEND_DIR / "status" / "css"),
    name="status-css",
)
app.mount(
    "/static/status/js",
    StaticFiles(directory=FRONTEND_DIR / "status" / "js"),
    name="status-js",
)


@app.get("/", include_in_schema=False)
async def home():
    """Serve the public home page from the unified gateway."""
    return FileResponse(FRONTEND_DIR / "home" / "index.html")


@app.get("/status", include_in_schema=False)
async def status_page():
    """Serve the platform status page; it does not poll services in the background."""
    return FileResponse(FRONTEND_DIR / "status" / "index.html")


def _task_status(task: asyncio.Task | None) -> tuple[str, str]:
    if task is None:
        return "inactive", "The process has not started this task."
    if task.cancelled():
        return "inactive", "The task was stopped."
    if not task.done():
        return "active", "The background task is running in this process."
    error = task.exception()
    if error is not None:
        return "failed", f"The task exited with {type(error).__name__}."
    return "inactive", "The task exited; it is not running."


def _mounted_status(child_app: FastAPI) -> tuple[str, str]:
    mount = next(
        (route for route in app.routes if isinstance(route, Mount) and route.app is child_app),
        None,
    )
    if mount is None:
        return "inactive", "This service is not mounted in the running application."
    return "active", f"Serving in this process at {mount.path or '/'}"


async def _dependency_status(name: str) -> dict[str, str]:
    try:
        if name == "Postgres":
            from sqlalchemy import text
            from services.core_api.app.database.connection import engine

            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        else:
            from streaming.client import get_redis_client

            await (await get_redis_client()).ping()
        return {"name": name, "status": "active", "detail": "Connection check succeeded."}
    except Exception:
        return {"name": name, "status": "inactive", "detail": "Connection check failed."}


@app.get("/status/data", include_in_schema=False)
async def status_data():
    """Return a point-in-time snapshot from live mounts, task states, and dependencies."""
    tasks = getattr(app.state, "background_tasks", {})
    services = []
    for name, child_app in (
        ("Core API", core_api_app),
        ("Control Tower", control_tower_app),
        ("Driver Gateway", driver_gateway_app),
    ):
        state, detail = _mounted_status(child_app)
        services.append({"name": name, "status": state, "detail": detail})
    for task_name, display_name in (
        ("routing-worker", "Routing Worker"),
        ("control-tower-telemetry", "Control Tower Telemetry"),
        ("simulator", "Simulator"),
    ):
        state, detail = _task_status(tasks.get(task_name))
        services.append({"name": display_name, "status": state, "detail": detail})
    postgres, redis = await asyncio.gather(
        _dependency_status("Postgres"),
        _dependency_status("Redis"),
    )
    services.extend((postgres, redis))
    return {"checked_at": datetime.now(timezone.utc).isoformat(), "services": services}


@app.get("/health/live")
async def health_live():
    """Liveness probe for the unified process."""
    return {"status": "live"}


@app.get("/health")
async def health():
    """Lightweight liveness response; performs no dependency checks."""
    return {"service": "platform-gateway", "status": "live"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe for the unified process."""
    return {"status": "ready"}


# Mount service apps after gateway-owned routes. Core API stays mounted at `/`
# so `/login`, `/auth/*`, `/orders/*`, `/staff/*`, and `/static/*` continue to
# be handled by Core API and its routers.
app.mount("/control-tower", control_tower_app)


@app.get("/driver", include_in_schema=False)
async def driver_panel(
    request: Request,
    access_token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
):
    """Route the exact panel path before the Driver Gateway's `/driver/*` mount."""
    return await serve_panel("driver", PANEL_ROOT / "driver" / "index.html", request, access_token, db)


@app.get("/driver/assets/{asset_path:path}", include_in_schema=False)
async def driver_panel_asset(
    asset_path: str,
    request: Request,
    access_token: str | None = Cookie(None),
    db: AsyncSession = Depends(get_db_session),
):
    return await serve_panel_asset("driver", asset_path, request, access_token, db)


app.mount("/driver", driver_gateway_app)
app.mount("/", core_api_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
