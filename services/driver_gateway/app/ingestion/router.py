"""Validate and publish driver events and upload authorized evidence."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Cookie, File, Form, Header, HTTPException, Request, UploadFile, status
import httpx
from pydantic import ValidationError
from redis.exceptions import RedisError
from minio.error import S3Error
from urllib3.exceptions import HTTPError as StorageHTTPError

from services.driver_gateway.app.config import config
from services.driver_gateway.app.driver_api.router import core_api_client
from services.driver_gateway.app.auth.jwt import verify_driver_jwt
from services.driver_gateway.app.storage.minio_client import MinIOStorageClient
from streaming.client import add_to_stream
from streaming.schemas.events import (
    DriverEvidenceCapturedEvent,
    DriverPackageScannedEvent,
    DriverPickupConfirmedEvent,
    DriverRouteStartedEvent,
    DriverTelemetryEvent,
)

logger = logging.getLogger(__name__)
router = APIRouter()
storage_client = MinIOStorageClient()
MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_driver_event(
    event: dict,
    authorization: str | None = Header(default=None),
    access_token: str | None = Cookie(default=None),
):
    """
    Ingest driver location pings or terminal status events and dump immediately to driver_events_stream.
    No database operations performed.
    """
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid driver token")
        token = authorization.removeprefix("Bearer ")
    else:
        token = access_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid driver token")
    claims = await verify_driver_jwt(token)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid driver token")

    driver_id = claims["driver_id"]
    requested_driver_id = event.get("driver_id")
    if requested_driver_id is not None and str(requested_driver_id) != driver_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event does not belong to the authenticated driver.",
        )
    try:
        event_type = event.get("event_type")
        if event_type == "route.started":
            validated = DriverRouteStartedEvent.model_validate({**event, "driver_id": driver_id})
        elif event_type == "package.scanned":
            validated = DriverPackageScannedEvent.model_validate({**event, "driver_id": driver_id})
        elif event_type == "pickup.confirmed":
            validated = DriverPickupConfirmedEvent.model_validate({**event, "driver_id": driver_id})
        else:
            validated = DriverTelemetryEvent.model_validate({**event, "driver_id": driver_id})
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_context=False),
        ) from exc

    await add_to_stream(
        "driver_events_stream",
        validated.model_dump(mode="json"),
    )
    return {"status": "accepted", "event_id": str(validated.event_id)}


@router.post("/pod", status_code=status.HTTP_202_ACCEPTED)
async def upload_driver_evidence(
    request: Request,
    event_id: UUID = Form(...),
    route_id: UUID = Form(...),
    order_id: UUID = Form(...),
    evidence_type: Literal["photo", "signature", "recipient_name"] = Form(...),
    purpose: Literal["pod", "exception"] = Form(...),
    recipient_name: str | None = Form(default=None, max_length=120),
    file: UploadFile | None = File(default=None),
    authorization: str | None = Header(default=None),
    access_token: str | None = Cookie(default=None),
):
    """Authorize, store, and publish driver evidence to MinIO and Redis."""
    if authorization:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid driver token")
        token = authorization.removeprefix("Bearer ")
    else:
        token = access_token
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid driver token")
    claims = await verify_driver_jwt(token)
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid driver token")

    name = recipient_name.strip() if recipient_name else None
    if evidence_type == "recipient_name":
        if not name:
            raise HTTPException(status_code=422, detail="Recipient name is required for this evidence type.")
        content_type = "application/json"
        data = json.dumps({"recipient_name": name}, ensure_ascii=False).encode("utf-8")
    else:
        if file is None:
            raise HTTPException(status_code=422, detail="A photo or signature file is required.")
        if file.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail="Evidence must be a JPEG, PNG, or WebP image.")
        data = await file.read(MAX_EVIDENCE_BYTES + 1)
        if not data:
            raise HTTPException(status_code=422, detail="Evidence file is empty.")
        if len(data) > MAX_EVIDENCE_BYTES:
            raise HTTPException(status_code=413, detail="Evidence files must be 5 MB or smaller.")
        content_type = file.content_type

    authorize_url = (
        f"{config.core_api_url}/driver/routes/{route_id}/stops/{order_id}/pod-authorize"
    )
    authorization_headers = {}
    for header_name in ("cookie", "authorization"):
        if header_name in request.headers:
            authorization_headers[header_name] = request.headers[header_name]
    try:
        upstream = await core_api_client.post(
            authorize_url,
            headers=authorization_headers,
            content=b"",
        )
    except httpx.TimeoutException as exc:
        logger.warning("Core API timed out authorizing driver evidence for route %s", route_id)
        raise HTTPException(status_code=504, detail="Could not authorize evidence upload.") from exc
    except httpx.RequestError as exc:
        logger.exception("Core API unavailable while authorizing driver evidence for route %s", route_id)
        raise HTTPException(status_code=502, detail="Could not authorize evidence upload.") from exc
    if upstream.status_code != status.HTTP_204_NO_CONTENT:
        detail = "Could not authorize evidence upload."
        try:
            response_body = upstream.json()
            if isinstance(response_body, dict) and isinstance(response_body.get("detail"), str):
                detail = response_body["detail"]
        except ValueError:
            logger.warning("Core API returned an unreadable evidence authorization response.")
        raise HTTPException(status_code=upstream.status_code, detail=detail)

    driver_id = UUID(claims["driver_id"])
    extension = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}.get(content_type, "json")
    object_key = (
        f"drivers/{driver_id}/routes/{route_id}/orders/{order_id}/"
        f"{event_id}.{extension}"
    )
    try:
        await asyncio.to_thread(
            storage_client.upload_evidence,
            object_key,
            data,
            content_type,
        )
        if name and evidence_type != "recipient_name":
            metadata_key = object_key.rsplit(".", 1)[0] + ".json"
            await asyncio.to_thread(
                storage_client.upload_evidence,
                metadata_key,
                json.dumps({"recipient_name": name}, ensure_ascii=False).encode("utf-8"),
                "application/json",
            )
        event = DriverEvidenceCapturedEvent(
            event_id=event_id,
            driver_id=driver_id,
            event_type="pod.captured" if purpose == "pod" else "delivery.exception.evidence",
            route_id=route_id,
            order_id=order_id,
            object_key=object_key,
            evidence_type=evidence_type,
            timestamp=datetime.now(timezone.utc),
        )
        await add_to_stream("driver_events_stream", event.model_dump(mode="json"))
    except (S3Error, StorageHTTPError, OSError, RedisError, ValueError) as exc:
        logger.exception(
            "Could not store or publish driver evidence for route %s order %s",
            route_id,
            order_id,
        )
        raise HTTPException(status_code=503, detail="Evidence could not be stored or queued.") from exc
    finally:
        if file is not None:
            await file.close()
    return {
        "status": "accepted",
        "event_id": str(event_id),
        "object_key": object_key,
        "persisted_with_order": False,
    }
