
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.orders import router as orders_router
from app.api.drivers import router as drivers_router
from app.api.routes import router as routes_router
from app.redis_client import redis_client, close_redis_connection
from app.api.dashboard import router as dashboard_router
from app.api import route_state
from app.api import driver_state
from app.api import rescue

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Check Redis connection when the application starts
    await redis_client.ping()

    try:
        yield
    finally:
        # Close Redis connection when the application stops
        await close_redis_connection()


app = FastAPI(
    title="Last Mile Delivery Control Tower",
    description="API for monitoring last-mile delivery operations",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(health_router)
app.include_router(orders_router)
app.include_router(drivers_router)
app.include_router(routes_router)
app.include_router(dashboard_router)
app.include_router(route_state.router)
app.include_router(driver_state.router)
app.include_router(rescue.router)