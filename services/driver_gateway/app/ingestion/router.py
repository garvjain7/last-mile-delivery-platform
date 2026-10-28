# Accepts pings, dumps immediately to driver_events_stream
# Router handling telemetry, stop status updates, and proof of delivery ingestion.

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import ValidationError

from services.driver_gateway.app.auth.jwt import verify_driver_jwt
from streaming.client import add_to_stream
from streaming.schemas.events import DriverRouteStartedEvent, DriverTelemetryEvent

router = APIRouter()

@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
async def ingest_driver_event(event: dict, authorization: str | None = Header(default=None)):
    """
    Ingest driver location pings or terminal status events and dump immediately to driver_events_stream.
    No database operations performed.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid driver token")
    claims = await verify_driver_jwt(authorization.removeprefix("Bearer "))
    if claims is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid driver token")

    driver_id = claims["driver_id"]
    try:
        if event.get("event_type") == "route.started":
            validated = DriverRouteStartedEvent.model_validate({**event, "driver_id": driver_id})
        else:
            validated = DriverTelemetryEvent.model_validate({**event, "driver_id": driver_id})
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.errors()) from exc

    await add_to_stream(
        "driver_events_stream",
        # Redis stream fields cannot be null; optional fields that are unset are left out.
        validated.model_dump(mode="json", exclude_none=True),
    )
    return {"status": "accepted", "event_id": validated.event_id}
