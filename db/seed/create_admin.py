#!/usr/bin/env python3
"""
db/seed/create_admin.py
-----------------------
Seeds the test/dev database with one admin user and minimal domain fixtures
(one warehouse, one merchant) required by admin backend tests.

Run from repo root:
    python db/seed/create_admin.py

Environment: reads DATABASE_URL from .env or environment.
"""

import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import select, text

from db_models.models import User, UserRole, UserRole_, Warehouse, Merchant, Driver, DriverStatus
from db_models.engine import make_engine
from services.core_api.app.auth.security import hash_password

DATABASE_URL = os.getenv("DATABASE_URL", "")
if not DATABASE_URL.strip():
    raise RuntimeError("DATABASE_URL is required to seed the database")

ADMIN_EMAIL = "seed_admin@test.internal"
ADMIN_PASSWORD = "AdminPass123!"
ADMIN_FULL_NAME = "Seed Admin"

WAREHOUSE_CODE = "SEED-WH01"
WAREHOUSE_NAME = "Seed Warehouse"

MERCHANT_NAME = "Seed Merchant Co."


async def seed(db: AsyncSession) -> None:
    # ------------------------------------------------------------------ admin
    existing = await db.scalar(select(User).where(User.email == ADMIN_EMAIL))
    if existing is None:
        admin = User(
            email=ADMIN_EMAIL,
            password_hash=hash_password(ADMIN_PASSWORD),
            full_name=ADMIN_FULL_NAME,
            is_active=True,
        )
        db.add(admin)
        await db.flush()
        db.add(UserRole_(user_id=admin.id, role=UserRole.admin, granted_by=admin.id))
        print(f"Created admin user  id={admin.id}  email={ADMIN_EMAIL}")
    else:
        print(f"Admin user already exists  email={ADMIN_EMAIL}")

    # -------------------------------------------------------------- warehouse
    wh = await db.scalar(select(Warehouse).where(Warehouse.code == WAREHOUSE_CODE))
    if wh is None:
        wh = Warehouse(
            code=WAREHOUSE_CODE,
            name=WAREHOUSE_NAME,
            address="1 Seed Street, Testtown",
            location="SRID=4326;POINT(77.0 28.0)",
        )
        db.add(wh)
        print(f"Created warehouse  code={WAREHOUSE_CODE}")
    else:
        print(f"Warehouse already exists  code={WAREHOUSE_CODE}")

    # --------------------------------------------------------------- merchant
    m = await db.scalar(select(Merchant).where(Merchant.name == MERCHANT_NAME))
    if m is None:
        m = Merchant(name=MERCHANT_NAME, is_active=True)
        db.add(m)
        print(f"Created merchant  name={MERCHANT_NAME}")
    else:
        print(f"Merchant already exists  name={MERCHANT_NAME}")

    # ----------------------------------------------------------------- driver
    # Create a seed driver user (pending status) used by driver-action tests
    driver_email = "seed_driver@test.internal"
    duser = await db.scalar(select(User).where(User.email == driver_email))
    if duser is None:
        duser = User(
            email=driver_email,
            password_hash=hash_password("DriverPass123!"),
            full_name="Seed Driver",
            is_active=True,
        )
        db.add(duser)
        await db.flush()
        db.add(UserRole_(user_id=duser.id, role=UserRole.driver, granted_by=duser.id))
        db.add(Driver(user_id=duser.id, status=DriverStatus.pending))
        print(f"Created driver user  id={duser.id}  email={driver_email}")
    else:
        print(f"Driver user already exists  email={driver_email}")

    await db.commit()
    print("Seed complete.")


async def main() -> None:
    engine = make_engine(DATABASE_URL)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        await seed(session)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
