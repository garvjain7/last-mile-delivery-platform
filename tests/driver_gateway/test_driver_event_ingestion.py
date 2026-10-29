import asyncio
from io import BytesIO
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.requests import Request

from services.driver_gateway.app.ingestion import router as ingestion
from streaming.schemas.events import DriverPickupConfirmedEvent


def telemetry_payload(event_type="driver.location.updated"):
    return {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "latitude": 12.9716,
        "longitude": 77.5946,
        "timestamp": "2026-10-22T04:00:00Z",
    }


def test_ingestion_accepts_driver_session_cookie_and_uses_verified_identity(monkeypatch):
    driver_id = str(uuid4())
    published = []

    async def verify_token(token):
        assert token == "cookie-token"
        return {"driver_id": driver_id}

    async def add_to_stream(stream, fields):
        published.append((stream, fields))
        return "1-0"

    monkeypatch.setattr(ingestion, "verify_driver_jwt", verify_token)
    monkeypatch.setattr(ingestion, "add_to_stream", add_to_stream)

    result = asyncio.run(
        ingestion.ingest_driver_event(
            telemetry_payload(),
            authorization=None,
            access_token="cookie-token",
        )
    )

    assert result == {
        "status": "accepted",
        "event_id": str(published[0][1]["event_id"]),
    }
    assert published[0][0] == "driver_events_stream"
    assert published[0][1]["driver_id"] == driver_id


def test_ingestion_rejects_unsupported_event_type(monkeypatch):
    async def verify_token(_token):
        return {"driver_id": str(uuid4())}

    async def add_to_stream(_stream, _fields):
        pytest.fail("Invalid events must not be published.")

    monkeypatch.setattr(ingestion, "verify_driver_jwt", verify_token)
    monkeypatch.setattr(ingestion, "add_to_stream", add_to_stream)
    payload = telemetry_payload("pickup.scanned")

    with pytest.raises(HTTPException) as error_info:
        asyncio.run(
            ingestion.ingest_driver_event(
                payload,
                authorization="Bearer bearer-token",
                access_token=None,
            )
        )

    assert error_info.value.status_code == 422


def test_ingestion_rejects_out_of_range_coordinates(monkeypatch):
    async def verify_token(_token):
        return {"driver_id": str(uuid4())}

    monkeypatch.setattr(ingestion, "verify_driver_jwt", verify_token)
    payload = telemetry_payload()
    payload["latitude"] = 95

    with pytest.raises(HTTPException) as error_info:
        asyncio.run(
            ingestion.ingest_driver_event(
                payload,
                authorization="Bearer bearer-token",
                access_token=None,
            )
        )

    assert error_info.value.status_code == 422


def test_ingestion_rejects_events_bound_to_another_driver(monkeypatch):
    async def verify_token(_token):
        return {"driver_id": str(uuid4())}

    monkeypatch.setattr(ingestion, "verify_driver_jwt", verify_token)
    payload = telemetry_payload()
    payload["driver_id"] = str(uuid4())

    with pytest.raises(HTTPException) as error_info:
        asyncio.run(
            ingestion.ingest_driver_event(
                payload,
                authorization="Bearer bearer-token",
                access_token=None,
            )
        )

    assert error_info.value.status_code == 403


@pytest.mark.parametrize(
    ("event_type", "specific_fields"),
    [
        ("package.scanned", {
            "route_id": str(uuid4()),
            "order_id": str(uuid4()),
            "tracking_token": "TRACK00001",
            "scan_stage": "pickup",
        }),
        ("pickup.confirmed", {"route_id": str(uuid4()), "scanned_order_ids": [str(uuid4())]}),
    ],
)
def test_ingestion_accepts_route_scanning_events(monkeypatch, event_type, specific_fields):
    driver_id = str(uuid4())
    published = []

    async def verify_token(_token):
        return {"driver_id": driver_id}

    async def add_to_stream(stream, fields):
        published.append((stream, fields))
        return "1-0"

    monkeypatch.setattr(ingestion, "verify_driver_jwt", verify_token)
    monkeypatch.setattr(ingestion, "add_to_stream", add_to_stream)
    payload = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "timestamp": "2026-10-22T04:00:00Z",
        **specific_fields,
    }

    result = asyncio.run(
        ingestion.ingest_driver_event(
            payload,
            authorization=None,
            access_token="cookie-token",
        )
    )

    assert result["status"] == "accepted"
    assert published[0][0] == "driver_events_stream"
    assert published[0][1]["driver_id"] == driver_id


def test_pickup_confirmation_rejects_duplicate_order_scans():
    order_id = str(uuid4())

    with pytest.raises(ValidationError):
        DriverPickupConfirmedEvent(
            event_id=uuid4(),
            driver_id=uuid4(),
            route_id=uuid4(),
            scanned_order_ids=[order_id, order_id],
            timestamp="2026-10-22T04:00:00Z",
        )


def test_scanned_parcel_token_is_trimmed_and_required():
    from streaming.schemas.events import DriverPackageScannedEvent

    event = DriverPackageScannedEvent(
        event_id=uuid4(),
        driver_id=uuid4(),
        route_id=uuid4(),
        order_id=uuid4(),
        tracking_token="  TRACK00001  ",
        scan_stage="pickup",
        timestamp="2026-10-22T04:00:00Z",
    )

    assert event.tracking_token == "TRACK00001"


def test_pod_upload_authorizes_route_stores_private_object_and_publishes_event(monkeypatch):
    driver_id = uuid4()
    route_id = uuid4()
    order_id = uuid4()
    event_id = uuid4()
    uploaded_objects = []
    published = []

    class FakeCoreAPIClient:
        async def post(self, url, **kwargs):
            assert url.endswith(f"/driver/routes/{route_id}/stops/{order_id}/pod-authorize")
            assert kwargs["headers"]["cookie"] == "access_token=cookie-token"
            return httpx.Response(204)

    class FakeStorage:
        def upload_evidence(self, object_key, data, content_type):
            uploaded_objects.append((object_key, data, content_type))
            return object_key

    async def verify_token(token):
        assert token == "cookie-token"
        return {"driver_id": str(driver_id)}

    async def add_to_stream(stream, fields):
        published.append((stream, fields))
        return "1-0"

    monkeypatch.setattr(ingestion, "core_api_client", FakeCoreAPIClient())
    monkeypatch.setattr(ingestion, "storage_client", FakeStorage())
    monkeypatch.setattr(ingestion, "verify_driver_jwt", verify_token)
    monkeypatch.setattr(ingestion, "add_to_stream", add_to_stream)
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/driver/pod",
            "raw_path": b"/driver/pod",
            "query_string": b"",
            "headers": [(b"cookie", b"access_token=cookie-token")],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
    )
    photo = UploadFile(
        filename="proof.png",
        file=BytesIO(b"png-bytes"),
        headers=Headers({"content-type": "image/png"}),
    )

    result = asyncio.run(
        ingestion.upload_driver_evidence(
            request=request,
            event_id=event_id,
            route_id=route_id,
            order_id=order_id,
            evidence_type="photo",
            purpose="pod",
            recipient_name="Recipient",
            file=photo,
            authorization=None,
            access_token="cookie-token",
        )
    )

    assert result["persisted_with_order"] is False
    assert uploaded_objects[0][0].endswith(f"/{event_id}.png")
    assert uploaded_objects[0][1:] == (b"png-bytes", "image/png")
    assert published[0][0] == "driver_events_stream"
    assert published[0][1]["event_type"] == "pod.captured"
    assert published[0][1]["object_key"] == uploaded_objects[0][0]
