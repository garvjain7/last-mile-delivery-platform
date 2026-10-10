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
from pathlib import Path
from typing import Awaitable

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.control_tower.app.consumers.telemetry_consumer import run_telemetry_consumer
from services.control_tower.app.main import app as control_tower_app
from services.core_api.app.main import app as core_api_app
from services.driver_gateway.app.main import app as driver_gateway_app
from services.routing_worker.app.main import start_consumer as start_routing_worker
from services.simulator.app.main import start_simulator

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
    background_tasks = [
        asyncio.create_task(
            _run_background_task("routing-worker", start_routing_worker())
        ),
        asyncio.create_task(
            _run_background_task("control-tower-telemetry", run_telemetry_consumer())
        ),
        asyncio.create_task(
            _run_background_task("simulator", start_simulator())
        ),
    ]
    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        await asyncio.gather(*background_tasks, return_exceptions=True)


app = FastAPI(
    title="Last-Mile Delivery Platform",
    version="1.0.0",
    lifespan=lifespan,
)

FRONTEND_DIR = ROOT_DIR / "frontend"


@app.get("/", include_in_schema=False)
async def home():
    """Serve the public home page from the unified gateway."""
    return FileResponse(FRONTEND_DIR / "home" / "index.html")


@app.get("/health/live")
async def health_live():
    """Liveness probe for the unified process."""
    return {"status": "live"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe for the unified process."""
    return {"status": "ready"}


# Static frontend directories are exposed at stable root-relative paths so HTML
# can reference assets as `/shared/...`, `/home/...`, and `/driver-app/...`.
app.mount("/shared", StaticFiles(directory=FRONTEND_DIR / "shared"), name="shared")
app.mount("/home", StaticFiles(directory=FRONTEND_DIR / "home"), name="home")
app.mount("/login/css", StaticFiles(directory=FRONTEND_DIR / "login" / "css"), name="login-css")
app.mount("/login/js", StaticFiles(directory=FRONTEND_DIR / "login" / "js"), name="login-js")
app.mount("/register/css", StaticFiles(directory=FRONTEND_DIR / "register" / "css"), name="register-css")
app.mount("/register/js", StaticFiles(directory=FRONTEND_DIR / "register" / "js"), name="register-js")
app.mount("/track/css", StaticFiles(directory=FRONTEND_DIR / "track" / "css"), name="track-css")
app.mount("/track/js", StaticFiles(directory=FRONTEND_DIR / "track" / "js"), name="track-js")
app.mount(
    "/dashboards",
    StaticFiles(directory=FRONTEND_DIR / "dashboards"),
    name="dashboards",
)
app.mount(
    "/driver-app",
    StaticFiles(directory=FRONTEND_DIR / "driver-app", html=True),
    name="driver-app",
)


# Mount service apps after gateway-owned routes. Core API stays mounted at `/`
# so `/login`, `/auth/*`, `/orders/*`, `/staff/*`, and `/static/*` continue to
# be handled by Core API and its routers.
app.mount("/control-tower", control_tower_app)
app.mount("/driver", driver_gateway_app)
app.mount("/", core_api_app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
