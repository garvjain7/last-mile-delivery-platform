"""
tests/admin/conftest.py
-----------------------
Shared pytest fixtures for admin backend tests.

Requirements:
  - Real Postgres built from schema.sql + db/migrations/2026_10_admin.sql (not SQLite, not mocks)
  - ENV=test so CSRF accepts http://testserver and security guards are relaxed
  - One admin user token available as `admin_token` fixture
  - One pending driver available as `pending_driver_id` fixture

The DATABASE_URL is read from .env (live Neon Postgres) exactly as the app does.
Tests clean up their own data (no transaction rollback — real INSERT + DELETE).
"""

import os
import sys
import asyncio
import uuid

# Ensure repo root is on sys.path so all absolute imports resolve
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# Force test environment before any config import
os.environ.setdefault("ENV", "test")
os.environ.setdefault("TRUSTED_PROXY_HOPS", "0")

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import select, text, delete

from dotenv import load_dotenv
load_dotenv()

from db_models.models import (
    AdminAuditLog, Driver, DriverStatus,
    Merchant, MerchantMember, User, UserRole, UserRole_,
    Warehouse, WarehouseStaff,
)
from db_models.engine import make_engine
from services.core_api.app.auth.security import create_access_token, hash_password
from services.core_api.app.main import app

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL.strip():
    raise RuntimeError("DATABASE_URL is required to run admin integration tests")

ADMIN_EMAIL = "seed_admin@test.internal"
ADMIN_PASSWORD = "AdminPass123!"

SEED_DRIVER_EMAIL = "seed_driver@test.internal"

# --------------------------------------------------------------------------
# Async engine fixture (session-scoped — one connection pool for all tests)
# --------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def db_engine():
    engine = make_engine(DATABASE_URL)
    yield engine
    asyncio.get_event_loop().run_until_complete(engine.dispose())


@pytest.fixture(scope="session")
def db_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)


# --------------------------------------------------------------------------
# Admin user JWT token (session-scoped — created once, reused)
# --------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def admin_user_id(db_factory) -> str:
    async with db_factory() as db:
        user = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert user is not None, (
            f"Seed admin {ADMIN_EMAIL!r} not found. "
            "Run 'python db/seed/create_admin.py' first."
        )
        return str(user.id)


@pytest_asyncio.fixture(scope="session")
async def admin_token(admin_user_id) -> str:
    return create_access_token(admin_user_id, ["admin"])


# --------------------------------------------------------------------------
# HTTPX async client connected to the real FastAPI app
# --------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def client(admin_token) -> AsyncClient:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "Content-Type": "application/json",
            "Origin": "http://testserver",
        },
    ) as ac:
        yield ac


# --------------------------------------------------------------------------
# Pending driver fixture (function-scoped — reset status between tests)
# --------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function")
async def pending_driver_id(db_factory) -> str:
    """Return the user_id of the seed pending driver; reset to 'pending' before test."""
    async with db_factory() as db:
        user = await db.scalar(select(User).where(User.email == SEED_DRIVER_EMAIL))
        assert user is not None, (
            f"Seed driver {SEED_DRIVER_EMAIL!r} not found. "
            "Run 'python db/seed/create_admin.py' first."
        )
        driver = await db.get(Driver, user.id)
        if driver is None:
            # Create driver row if missing
            driver = Driver(user_id=user.id, status=DriverStatus.pending)
            db.add(driver)
        else:
            driver.status = DriverStatus.pending
        await db.commit()
        return str(user.id)


# --------------------------------------------------------------------------
# Clean audit rows between tests (function-scoped)
# --------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="function", autouse=True)
async def clean_audit_for_test(db_factory):
    """Truncate admin_audit_log rows created during tests to keep the table clean."""
    yield
    # Note: admin_audit_log has immutable trigger (no DELETE/UPDATE).
    # We cannot truncate in real DB during tests — audit rows must be queried
    # using their occurred_at timestamp, not deleted.
    pass
