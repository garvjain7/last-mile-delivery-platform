"""End-to-end Driver App persistence test for an isolated local stack.

Run Core API, Driver Gateway, and Routing Worker against the same disposable local
database, non-default Redis database, and JWT secret. Set DRIVER_E2E_DATABASE_URL,
DRIVER_E2E_REDIS_URL, DRIVER_E2E_CORE_API_URL, and DRIVER_E2E_GATEWAY_URL before
running this test. The database URL never falls back to DATABASE_URL from .env.
"""

from __future__ import annotations

import asyncio
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
import pytest
import redis.asyncio as redis
from dotenv import load_dotenv
from minio import Minio
from sqlalchemy import text
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


load_dotenv()

CORE_API_URL = os.getenv("DRIVER_E2E_CORE_API_URL", "http://127.0.0.1:8100").rstrip("/")
GATEWAY_URL = os.getenv("DRIVER_E2E_GATEWAY_URL", "http://127.0.0.1:8102").rstrip("/")
DATABASE_URL = os.getenv("DRIVER_E2E_DATABASE_URL", "")
REDIS_URL = os.getenv("DRIVER_E2E_REDIS_URL", "")
MINIO_ENDPOINT = os.getenv("DRIVER_E2E_MINIO_ENDPOINT", "127.0.0.1:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ROOT_USER", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
POD_BUCKET = "pod-photos"
POD_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDAT\x08\xd7c\xf8"
    b"\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND"
    b"\xaeB`\x82"
)


def _assert_isolated_targets() -> None:
    if not DATABASE_URL:
        pytest.fail(
            "Set DRIVER_E2E_DATABASE_URL to a disposable local E2E database; "
            "the test never falls back to DATABASE_URL from .env."
        )
    database = make_url(DATABASE_URL)
    if database.host not in LOCAL_HOSTS or "e2e" not in (database.database or "").lower():
        pytest.fail("DRIVER_E2E_DATABASE_URL must target a local database with 'e2e' in its name.")

    for label, base_url in (("Core API", CORE_API_URL), ("Driver Gateway", GATEWAY_URL)):
        if urlsplit(base_url).hostname not in LOCAL_HOSTS:
            pytest.fail(f"{label} URL must target a local test service.")

    if not REDIS_URL:
        pytest.fail("Set DRIVER_E2E_REDIS_URL to an isolated local Redis database.")
    redis_parts = urlsplit(REDIS_URL)
    redis_database = redis_parts.path.strip("/")
    if redis_parts.hostname not in LOCAL_HOSTS or not redis_database or redis_database == "0":
        pytest.fail("DRIVER_E2E_REDIS_URL must target a non-default local Redis database.")

    minio_host = MINIO_ENDPOINT.rsplit(":", 1)[0]
    if minio_host not in LOCAL_HOSTS:
        pytest.fail("DRIVER_E2E_MINIO_ENDPOINT must target local MinIO.")


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _seed_route(engine: AsyncEngine, email: str, run_id: str) -> dict[str, UUID | str]:
    vehicle_id = uuid4()
    merchant_id = uuid4()
    warehouse_id = uuid4()
    order_id = uuid4()
    route_id = uuid4()
    route_stop_id = uuid4()
    tracking_token = f"E2E-{run_id.upper()}"

    async with engine.begin() as connection:
        driver_id = await connection.scalar(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": email},
        )
        if driver_id is None:
            raise AssertionError("The test driver registered successfully but was not found in the E2E database.")

        await connection.execute(
            text(
                """
                INSERT INTO vehicles (id, type, registration_number, max_weight_kg, max_volume_m3)
                VALUES (:id, 'van', :registration, 1000, 10)
                """
            ),
            {"id": vehicle_id, "registration": f"E2E-{run_id[:12].upper()}"},
        )
        await connection.execute(
            text("UPDATE drivers SET vehicle_id = :vehicle_id, status = 'available' WHERE user_id = :driver_id"),
            {"vehicle_id": vehicle_id, "driver_id": driver_id},
        )
        await connection.execute(
            text(
                """
                INSERT INTO merchants (id, name)
                VALUES (:id, :name)
                """
            ),
            {"id": merchant_id, "name": f"Driver E2E {run_id}"},
        )
        await connection.execute(
            text(
                """
                INSERT INTO warehouses (id, code, name, address, location)
                VALUES (
                    :id, :code, :name, :address,
                    ST_SetSRID(ST_MakePoint(79.0882, 21.1458), 4326)::geography
                )
                """
            ),
            {
                "id": warehouse_id,
                "code": f"E2E-{run_id[:12].upper()}",
                "name": "E2E Test Hub",
                "address": "Local E2E test location",
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO orders (
                    id, merchant_id, merchant_order_ref, warehouse_id, status,
                    recipient_name, recipient_phone, delivery_address, delivery_location,
                    weight_kg, volume_m3, tracking_token
                )
                VALUES (
                    :id, :merchant_id, :order_ref, :warehouse_id, 'assigned',
                    'E2E Recipient', '+919876543210', 'Local E2E test address',
                    ST_SetSRID(ST_MakePoint(79.09, 21.15), 4326)::geography,
                    1, 0.01, :tracking_token
                )
                """
            ),
            {
                "id": order_id,
                "merchant_id": merchant_id,
                "order_ref": f"E2E-{run_id}",
                "warehouse_id": warehouse_id,
                "tracking_token": tracking_token,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO routes (id, warehouse_id, driver_id, vehicle_id, status)
                VALUES (:id, :warehouse_id, :driver_id, :vehicle_id, 'planned')
                """
            ),
            {
                "id": route_id,
                "warehouse_id": warehouse_id,
                "driver_id": driver_id,
                "vehicle_id": vehicle_id,
            },
        )
        await connection.execute(
            text(
                """
                INSERT INTO route_stops (
                    id, route_id, order_id, sequence, status, planned_location,
                    planned_distance_m, planned_arrival_at
                )
                VALUES (
                    :id, :route_id, :order_id, 1, 'pending',
                    ST_SetSRID(ST_MakePoint(79.09, 21.15), 4326)::geography,
                    1000, :arrival
                )
                """
            ),
            {
                "id": route_stop_id,
                "route_id": route_id,
                "order_id": order_id,
                "arrival": datetime.now(timezone.utc) + timedelta(hours=1),
            },
        )

    return {
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "merchant_id": merchant_id,
        "warehouse_id": warehouse_id,
        "order_id": order_id,
        "route_id": route_id,
        "route_stop_id": route_stop_id,
        "tracking_token": tracking_token,
    }


async def _cleanup_seed(engine: AsyncEngine, records: dict[str, UUID | str]) -> None:
    if not records:
        return
    driver_id = records.get("driver_id")
    order_id = records.get("order_id")
    route_id = records.get("route_id")
    vehicle_id = records.get("vehicle_id")
    warehouse_id = records.get("warehouse_id")
    merchant_id = records.get("merchant_id")

    async with engine.begin() as connection:
        if driver_id is not None:
            await connection.execute(
                text(
                    """
                    DELETE FROM processed_events
                    WHERE driver_id = :driver_id OR route_id = :route_id
                    """
                ),
                {"driver_id": driver_id, "route_id": route_id},
            )
            await connection.execute(
                text("DELETE FROM driver_earnings WHERE driver_id = :driver_id"),
                {"driver_id": driver_id},
            )
            await connection.execute(
                text("DELETE FROM driver_wallets WHERE driver_id = :driver_id"),
                {"driver_id": driver_id},
            )
        if order_id is not None:
            for table in (
                "order_events",
                "delivery_attempts",
                "delivery_exceptions",
                "delivery_proof",
                "package_scans",
            ):
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE order_id = :order_id"),
                    {"order_id": order_id},
                )
        if route_id is not None:
            await connection.execute(
                text("DELETE FROM routes WHERE id = :route_id"),
                {"route_id": route_id},
            )
        if order_id is not None:
            await connection.execute(
                text("DELETE FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            )
        if driver_id is not None:
            await connection.execute(
                text("DELETE FROM drivers WHERE user_id = :driver_id"),
                {"driver_id": driver_id},
            )
        if vehicle_id is not None:
            await connection.execute(
                text("DELETE FROM vehicles WHERE id = :vehicle_id"),
                {"vehicle_id": vehicle_id},
            )
        if warehouse_id is not None:
            await connection.execute(
                text("DELETE FROM warehouses WHERE id = :warehouse_id"),
                {"warehouse_id": warehouse_id},
            )
        if merchant_id is not None:
            await connection.execute(
                text("DELETE FROM merchants WHERE id = :merchant_id"),
                {"merchant_id": merchant_id},
            )
        if driver_id is not None:
            await connection.execute(
                text("DELETE FROM users WHERE id = :driver_id"),
                {"driver_id": driver_id},
            )


async def _wait_for_test_events(engine: AsyncEngine, event_ids: list[UUID]) -> None:
    deadline = asyncio.get_running_loop().time() + 20
    while True:
        async with engine.connect() as connection:
            statuses = [
                await connection.scalar(
                    text("SELECT status FROM processed_events WHERE event_id = :event_id"),
                    {"event_id": event_id},
                )
                for event_id in event_ids
            ]
        if all(status in {"committed", "rejected"} for status in statuses):
            return
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("Accepted E2E events did not settle; refusing to delete their route records.")
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_driver_e2e_delivery_persists_to_existing_tables() -> None:
    _assert_isolated_targets()
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    minio_client = Minio(
        MINIO_ENDPOINT,
        access_key=MINIO_ACCESS_KEY,
        secret_key=MINIO_SECRET_KEY,
        secure=False,
    )
    records: dict[str, UUID | str] = {}
    event_ids: dict[str, UUID] = {}
    accepted_event_ids: list[UUID] = []
    pod_object_key: str | None = None
    email = f"driver-e2e-{uuid4().hex}@example.com"
    password = secrets.token_urlsafe(24)
    run_id = uuid4().hex

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            for table in ("delivery_proof", "package_scans", "processed_events"):
                exists = await connection.scalar(
                    text("SELECT to_regclass(:table_name) IS NOT NULL"),
                    {"table_name": f"public.{table}"},
                )
                assert exists, f"Required consolidated table {table!r} is missing from the isolated E2E database."

        await redis_client.ping()
        assert await redis_client.xlen("driver_events_stream") == 0, (
            "The isolated E2E Redis database already contains driver events; "
            "use an empty non-default Redis database."
        )
        if not await asyncio.to_thread(minio_client.bucket_exists, POD_BUCKET):
            await asyncio.to_thread(minio_client.make_bucket, POD_BUCKET)

        async with httpx.AsyncClient(timeout=20.0) as client:
            core_health = await client.get(f"{CORE_API_URL}/health")
            assert core_health.status_code == 200, f"Core API is unavailable: {core_health.text}"
            gateway_ready = await client.get(f"{GATEWAY_URL}/health/ready")
            assert gateway_ready.status_code == 200, f"Gateway is not ready: {gateway_ready.text}"

            registration = await client.post(
                f"{CORE_API_URL}/auth/register/driver",
                json={
                    "full_name": f"Driver E2E {run_id}",
                    "email": email,
                    "password": password,
                },
            )
            assert registration.status_code == 201, (
                f"Test driver registration failed: HTTP {registration.status_code} {registration.text}"
            )
            async with engine.connect() as connection:
                registered_driver_id = await connection.scalar(
                    text("SELECT id FROM users WHERE email = :email"),
                    {"email": email},
                )
            assert registered_driver_id is not None, "Registration did not persist to the isolated E2E database."
            records["driver_id"] = registered_driver_id

            login = await client.post(
                f"{CORE_API_URL}/auth/login",
                json={"email": email, "password": password},
            )
            assert login.status_code == 200, f"Test driver login failed: {login.text}"
            driver_id = UUID(login.json()["user_id"])
            records.update(await _seed_route(engine, email, run_id))
            assert records["driver_id"] == driver_id

            routes_response = await client.get(f"{GATEWAY_URL}/driver/routes")
            assert routes_response.status_code == 200, (
                f"Gateway route fetch failed: HTTP {routes_response.status_code} {routes_response.text}"
            )
            route_id = records["route_id"]
            order_id = records["order_id"]
            route = next(
                (item for item in routes_response.json() if item["route_id"] == str(route_id)),
                None,
            )
            assert route is not None, "The seeded route was not returned by the Driver Gateway."
            assert len(route["stops"]) == 1

            started = await client.post(f"{GATEWAY_URL}/driver/routes/{route_id}/accept")
            assert started.status_code == 200, f"Route start failed: {started.text}"

            def event_id(name: str) -> UUID:
                value = uuid4()
                event_ids[name] = value
                return value

            route_started_id = event_id("route.started")
            route_started = await client.post(
                f"{GATEWAY_URL}/driver/events",
                json={
                    "event_id": str(route_started_id),
                    "driver_id": str(driver_id),
                    "event_type": "route.started",
                    "route_id": str(route_id),
                    "timestamp": _timestamp(),
                },
            )
            assert route_started.status_code == 202, f"Route-start event was not accepted: {route_started.text}"
            accepted_event_ids.append(route_started_id)

            scan_validation = await client.post(
                f"{GATEWAY_URL}/driver/routes/{route_id}/scan",
                json={
                    "tracking_token": records["tracking_token"],
                    "scan_stage": "pickup",
                    "order_id": str(order_id),
                },
            )
            assert scan_validation.status_code == 200, f"Pickup scan validation failed: {scan_validation.text}"

            package_scan_id = event_id("package.scanned")
            package_scan = await client.post(
                f"{GATEWAY_URL}/driver/events",
                json={
                    "event_id": str(package_scan_id),
                    "driver_id": str(driver_id),
                    "event_type": "package.scanned",
                    "route_id": str(route_id),
                    "order_id": str(order_id),
                    "tracking_token": records["tracking_token"],
                    "scan_stage": "pickup",
                    "timestamp": _timestamp(),
                },
            )
            assert package_scan.status_code == 202, f"Package scan was not accepted: {package_scan.text}"
            accepted_event_ids.append(package_scan_id)

            pickup_id = event_id("pickup.confirmed")
            pickup = await client.post(
                f"{GATEWAY_URL}/driver/events",
                json={
                    "event_id": str(pickup_id),
                    "driver_id": str(driver_id),
                    "event_type": "pickup.confirmed",
                    "route_id": str(route_id),
                    "scanned_order_ids": [str(order_id)],
                    "timestamp": _timestamp(),
                },
            )
            assert pickup.status_code == 202, f"Pickup confirmation was not accepted: {pickup.text}"
            accepted_event_ids.append(pickup_id)

            arrival_id = event_id("stop.arrived")
            arrival = await client.post(
                f"{GATEWAY_URL}/driver/events",
                json={
                    "event_id": str(arrival_id),
                    "driver_id": str(driver_id),
                    "event_type": "stop.arrived",
                    "current_route_id": str(route_id),
                    "order_id": str(order_id),
                    "latitude": 21.1458,
                    "longitude": 79.09,
                    "timestamp": _timestamp(),
                },
            )
            assert arrival.status_code == 202, f"Stop-arrival event was not accepted: {arrival.text}"
            accepted_event_ids.append(arrival_id)

            pod_id = event_id("pod.captured")
            pod_object_key = (
                f"drivers/{driver_id}/routes/{route_id}/orders/{order_id}/{pod_id}.png"
            )
            pod = await client.post(
                f"{GATEWAY_URL}/driver/pod",
                data={
                    "event_id": str(pod_id),
                    "route_id": str(route_id),
                    "order_id": str(order_id),
                    "evidence_type": "photo",
                    "purpose": "pod",
                },
                files={"file": ("pod.png", POD_PNG, "image/png")},
            )
            assert pod.status_code == 202, f"POD upload was not accepted: {pod.text}"
            accepted_event_ids.append(pod_id)
            assert pod.json()["object_key"] == pod_object_key

            completion_id = event_id("delivery.completed")
            completion = await client.post(
                f"{GATEWAY_URL}/driver/events",
                json={
                    "event_id": str(completion_id),
                    "driver_id": str(driver_id),
                    "event_type": "delivery.completed",
                    "current_route_id": str(route_id),
                    "order_id": str(order_id),
                    "latitude": 21.1458,
                    "longitude": 79.09,
                    "timestamp": _timestamp(),
                },
            )
            assert completion.status_code == 202, f"Delivery completion was not accepted: {completion.text}"
            accepted_event_ids.append(completion_id)

            deadline = asyncio.get_running_loop().time() + 90
            while True:
                status_response = await client.get(
                    f"{GATEWAY_URL}/driver/events/status",
                    params=[("event_id", str(value)) for value in event_ids.values()],
                )
                assert status_response.status_code == 200, (
                    f"Gateway event-status polling failed: "
                    f"HTTP {status_response.status_code} {status_response.text}"
                )
                status_items = status_response.json()["events"]
                assert {item["event_id"] for item in status_items} == {
                    str(value) for value in event_ids.values()
                }
                rejected = [item for item in status_items if item["status"] == "rejected"]
                assert not rejected, f"Worker rejected driver events: {rejected}"
                if status_items and all(item["status"] == "committed" for item in status_items):
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    pytest.fail(f"Driver events did not commit before timeout: {status_items}")
                await asyncio.sleep(0.25)

        async with engine.connect() as connection:
            order_status = await connection.scalar(
                text("SELECT status::text FROM orders WHERE id = :order_id"),
                {"order_id": order_id},
            )
            stop_row = (
                await connection.execute(
                    text(
                        """
                        SELECT status::text, completed_at
                        FROM route_stops
                        WHERE id = :route_stop_id
                        """
                    ),
                    {"route_stop_id": records["route_stop_id"]},
                )
            ).one()
            proof_row = (
                await connection.execute(
                    text(
                        """
                        SELECT object_key, proof_type
                        FROM delivery_proof
                        WHERE route_stop_id = :route_stop_id
                          AND order_id = :order_id
                          AND driver_id = :driver_id
                          AND proof_type = 'photo'
                        ORDER BY captured_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "route_stop_id": records["route_stop_id"],
                        "order_id": order_id,
                        "driver_id": records["driver_id"],
                    },
                )
            ).one_or_none()
            scan_types = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT event_type
                            FROM package_scans
                            WHERE route_stop_id = :route_stop_id
                            """
                        ),
                        {"route_stop_id": records["route_stop_id"]},
                    )
                ).scalars()
            )
            receipts = {}
            for submitted_id in event_ids.values():
                receipts[str(submitted_id)] = await connection.scalar(
                    text("SELECT status FROM processed_events WHERE event_id = :event_id"),
                    {"event_id": submitted_id},
                )
            delivered_events = await connection.scalar(
                text(
                    """
                    SELECT COUNT(*)
                    FROM order_events
                    WHERE order_id = :order_id AND to_status::text = 'delivered'
                    """
                ),
                {"order_id": order_id},
            )

        assert order_status == "delivered"
        assert stop_row.status == "delivered" and stop_row.completed_at is not None
        assert proof_row is not None and proof_row.object_key == pod_object_key
        assert {"package.scanned", "pickup.confirmed"} <= scan_types
        assert set(receipts.values()) == {"committed"}
        assert delivered_events >= 1

        await asyncio.to_thread(minio_client.stat_object, POD_BUCKET, proof_row.object_key)
        print(
            "Driver E2E passed: route accepted, pickup/scan/POD/delivery committed, "
            "and persistence assertions passed against the isolated local database."
        )
    finally:
        if pod_object_key:
            await asyncio.to_thread(minio_client.remove_object, POD_BUCKET, pod_object_key)
        if records:
            await _wait_for_test_events(engine, accepted_event_ids)
            await _cleanup_seed(engine, records)
        await redis_client.aclose()
        await engine.dispose()
