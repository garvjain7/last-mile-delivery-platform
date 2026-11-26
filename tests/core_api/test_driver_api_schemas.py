import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import Fernet
from pydantic import SecretStr
import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql
from starlette.responses import Response

from db_models.models import DriverPaymentMethodType
from services.core_api.app.config import config
from services.core_api.app.driver.finance import (
    mask_payment_method,
    payment_cipher,
    payment_method_details,
)
from services.core_api.app.driver.schemas import (
    AssignVehicleRequest,
    DriverProfilePatch,
    DriverRouteResponse,
    DriverScanValidationRequest,
    PaymentMethodCreate,
    RouteStopResponse,
)
from services.core_api.app.driver.router import get_driver_event_status
from services.core_api.app.driver.service import route_location_payload, route_payload


def test_driver_profile_patch_requires_a_nonblank_change():
    with pytest.raises(ValidationError):
        DriverProfilePatch()
    with pytest.raises(ValidationError):
        DriverProfilePatch(full_name="   ")

    payload = DriverProfilePatch(full_name="  A Driver  ")

    assert payload.full_name == "A Driver"


def test_vehicle_assignment_requires_exactly_one_identifier():
    with pytest.raises(ValidationError):
        AssignVehicleRequest()
    with pytest.raises(ValidationError):
        AssignVehicleRequest(vehicle_id=uuid4(), registration_number="KA 01 AB 1234")

    payload = AssignVehicleRequest(registration_number="KA 01 AB 1234")

    assert payload.registration_number == "KA 01 AB 1234"


def test_scan_validation_requires_order_for_delivery_stop_scan():
    with pytest.raises(ValidationError):
        DriverScanValidationRequest(
            tracking_token="tracking-token",
            scan_stage="stop",
        )

    payload = DriverScanValidationRequest(
        tracking_token="tracking-token",
        scan_stage="pickup",
    )

    assert payload.scan_stage == "pickup"
    assert payload.order_id is None


def test_payment_method_validation_masks_and_encrypts_payout_details(monkeypatch):
    payload = PaymentMethodCreate(
        method_type="bank_account",
        account_holder_name="  A Driver ",
        account_number="001234567890",
        ifsc_code="abcd0123456",
    )
    details = payment_method_details(payload)
    monkeypatch.setattr(
        config,
        "payment_method_encryption_key",
        SecretStr(Fernet.generate_key().decode("ascii")),
    )
    encrypted = payment_cipher().encrypt(
        json.dumps(details, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    )

    assert details == {
        "account_holder_name": "A Driver",
        "account_number": "001234567890",
        "ifsc_code": "ABCD0123456",
    }
    assert mask_payment_method(DriverPaymentMethodType.bank_account, details) == "Account ending 7890"
    assert b"001234567890" not in encrypted
    assert json.loads(payment_cipher().decrypt(encrypted)) == details


def test_payment_method_validation_rejects_mismatched_or_invalid_details():
    with pytest.raises(ValidationError):
        PaymentMethodCreate(method_type="upi", upi_id="not-a-handle")
    with pytest.raises(ValidationError):
        PaymentMethodCreate(
            method_type="bank_account",
            account_holder_name="Driver",
            account_number="12AB",
            ifsc_code="ABCD0123456",
        )
    with pytest.raises(ValidationError):
        PaymentMethodCreate(method_type="upi", upi_id="driver@bank", account_number="123456")


def test_route_payload_orders_stops_and_uses_schema_fields():
    route_id = uuid4()
    first_order_id = uuid4()
    second_order_id = uuid4()
    planned_arrival = datetime(2026, 10, 22, 8, 30, tzinfo=timezone.utc)
    route = SimpleNamespace(
        id=route_id,
        status=SimpleNamespace(value="planned"),
        version=2,
        total_distance_m=4200,
        total_duration_s=900,
        warehouse_id=uuid4(),
        warehouse=SimpleNamespace(name="North Hub", address="Hub Road", code="NH-01"),
        vehicle_id=uuid4(),
        vehicle=SimpleNamespace(registration_number="KA 01 AB 1234"),
        stops=[
            SimpleNamespace(
                id=uuid4(),
                order_id=second_order_id,
                sequence=2,
                status=SimpleNamespace(value="pending"),
                order=SimpleNamespace(
                    status=SimpleNamespace(value="assigned"),
                    recipient_name="Second",
                    recipient_phone="+919876543210",
                    delivery_address="Second address",
                    tracking_token="tracking-second",
                    window_earliest=None,
                    window_latest=None,
                ),
                planned_arrival_at=planned_arrival,
            ),
            SimpleNamespace(
                id=uuid4(),
                order_id=first_order_id,
                sequence=1,
                status=SimpleNamespace(value="pending"),
                order=SimpleNamespace(
                    status=SimpleNamespace(value="out_for_delivery"),
                    recipient_name="First",
                    recipient_phone="+919876543211",
                    delivery_address="First address",
                    tracking_token="tracking-first",
                    window_earliest=planned_arrival,
                    window_latest=planned_arrival,
                ),
                planned_arrival_at=planned_arrival,
            ),
        ],
    )

    response = route_payload(
        route,
        {
            "pickup": {"latitude": 12.9, "longitude": 77.5},
            "stops": {
                route.stops[0].id: {"latitude": 12.91, "longitude": 77.51},
                route.stops[1].id: {"latitude": 12.92, "longitude": 77.52},
            },
        },
    )

    assert response["route_id"] == route_id
    assert response["status"] == "planned"
    assert [stop["order_id"] for stop in response["stops"]] == [first_order_id, second_order_id]
    assert response["pickup_code"] == "NH-01"
    assert response["stops"][0]["planned_arrival_at"] == planned_arrival.isoformat()
    assert response["stops"][0]["tracking_token"] == "tracking-first"
    assert response["stops"][0]["order_status"] == "out_for_delivery"
    assert response["stops"][0]["window_earliest"] == planned_arrival.isoformat()
    assert response["pickup_latitude"] == 12.9
    assert response["pickup_longitude"] == 77.5
    assert response["stops"][0]["latitude"] == 12.92
    assert response["stops"][0]["longitude"] == 77.52
    assert RouteStopResponse.model_validate(response["stops"][0]).order_status == "out_for_delivery"
    assert DriverRouteResponse.model_validate(response).pickup_latitude == 12.9


def test_route_location_payload_uses_pickup_and_planned_stop_points():
    route_id = uuid4()
    stop_id = uuid4()

    class Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

    class Database:
        statements = []
        results = [
            [(route_id, 12.9, 77.5)],
            [(route_id, stop_id, 12.91, 77.51)],
        ]

        async def execute(self, statement):
            self.statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return Result(self.results.pop(0))

    database = Database()
    locations = asyncio.run(route_location_payload(database, [route_id]))

    assert locations == {
        route_id: {
            "pickup": {"latitude": 12.9, "longitude": 77.5},
            "stops": {stop_id: {"latitude": 12.91, "longitude": 77.51}},
        }
    }
    assert "warehouses.location" in database.statements[0]
    assert "route_stops.planned_location" in database.statements[1]


def test_driver_event_status_is_scoped_and_includes_pending_events():
    driver_id = uuid4()
    committed_id, rejected_id, legacy_id, pending_id = uuid4(), uuid4(), uuid4(), uuid4()
    records = [
        SimpleNamespace(event_id=committed_id, driver_id=driver_id, status="committed", reject_reason=None),
        SimpleNamespace(event_id=rejected_id, driver_id=driver_id, status="rejected", reject_reason="stale route"),
        SimpleNamespace(event_id=legacy_id, driver_id=None, status=None, reject_reason=None),
    ]

    class ScalarRows:
        def all(self):
            return records

    class Database:
        statement = None

        async def scalars(self, statement):
            self.statement = statement
            return ScalarRows()

    database = Database()
    response = Response()
    result = asyncio.run(
        get_driver_event_status(
            response,
            [committed_id, rejected_id, legacy_id, pending_id],
            SimpleNamespace(id=driver_id),
            database,
        )
    )
    compiled = str(database.statement.compile(dialect=postgresql.dialect()))

    assert [event["status"] for event in result["events"]] == [
        "committed",
        "rejected",
        "pending",
        "pending",
    ]
    assert result["events"][1]["reject_reason"] == "stale route"
    assert "processed_events.driver_id" in compiled
    assert response.headers["cache-control"] == "no-store"
