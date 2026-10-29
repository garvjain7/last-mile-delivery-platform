from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from services.core_api.app.driver.schemas import (
    AssignVehicleRequest,
    DriverProfilePatch,
    DriverScanValidationRequest,
)
from services.core_api.app.driver.service import route_payload


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

    response = route_payload(route)

    assert response["route_id"] == route_id
    assert response["status"] == "planned"
    assert [stop["order_id"] for stop in response["stops"]] == [first_order_id, second_order_id]
    assert response["pickup_code"] == "NH-01"
    assert response["stops"][0]["planned_arrival_at"] == planned_arrival.isoformat()
    assert response["stops"][0]["tracking_token"] == "tracking-first"
    assert response["stops"][0]["window_earliest"] == planned_arrival.isoformat()
