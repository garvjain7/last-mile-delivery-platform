# Hard definitions of order_stream, route_stream, driver_stream
# Strict Pydantic event envelope definitions per Redis Stream.

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

class OrderCreatedEvent(BaseModel):
    """Event envelope for a newly placed order before warehouse handoff."""
    event_id: str
    order_id: str
    merchant_id: str
    warehouse_id: Optional[str] = None
    dropoff_location: str
    dropoff_raw_address: str
    time_window: str
    weight_kg: float
    volume_m3: float
    created_at: str

class RoutePublishedEvent(BaseModel):
    """Event envelope for route_stream published by Routing Worker after VROOM solve."""
    event_id: str
    route_id: str
    vehicle_id: str
    driver_id: str
    driver_name: str
    vehicle_registration: str
    stops: List[Dict[str, Any]]
    created_at: str

class DriverTelemetryEvent(BaseModel):
    """Validated driver telemetry and terminal-event envelope for driver_events_stream."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    driver_id: UUID
    event_type: Literal[
        "driver.location.updated",
        "stop.arrived",
        "delivery.completed",
        "delivery.failed",
    ]
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    current_route_id: Optional[UUID] = None
    order_id: Optional[UUID] = None
    failure_reason: Optional[
        Literal["recipient_unavailable", "wrong_address", "refused", "other"]
    ] = None
    failure_notes: Optional[str] = Field(default=None, max_length=500)
    return_to_hub: bool = False
    timestamp: datetime

    @model_validator(mode="after")
    def validate_event_context(self):
        if self.event_type != "driver.location.updated" and self.current_route_id is None:
            raise ValueError("current_route_id is required for route events.")
        if self.event_type in {"stop.arrived", "delivery.completed", "delivery.failed"} and self.order_id is None:
            raise ValueError("order_id is required for stop events.")
        if self.event_type == "delivery.failed" and self.failure_reason is None:
            raise ValueError("failure_reason is required for failed deliveries.")
        if self.event_type != "delivery.failed" and self.failure_reason is not None:
            raise ValueError("failure_reason is only valid for failed deliveries.")
        if self.event_type != "delivery.failed" and (self.failure_notes or self.return_to_hub):
            raise ValueError("failure details are only valid for failed deliveries.")
        return self


class DriverRouteStartedEvent(BaseModel):
    """Event envelope for a driver starting an assigned route."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    route_id: UUID
    driver_id: UUID
    event_type: Literal["route.started"] = "route.started"
    timestamp: datetime


class DriverPackageScannedEvent(BaseModel):
    """Parcel scan event; Redis transport only under the current schema."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    driver_id: UUID
    event_type: Literal["package.scanned"] = "package.scanned"
    route_id: UUID
    order_id: UUID
    tracking_token: str = Field(min_length=1, max_length=200)
    scan_stage: Literal["pickup", "stop"]
    timestamp: datetime

    @model_validator(mode="after")
    def normalize_tracking_token(self):
        self.tracking_token = self.tracking_token.strip()
        if not self.tracking_token:
            raise ValueError("tracking_token cannot be blank.")
        return self


class DriverPickupConfirmedEvent(BaseModel):
    """Pickup confirmation for a fully scanned route manifest."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    driver_id: UUID
    event_type: Literal["pickup.confirmed"] = "pickup.confirmed"
    route_id: UUID
    scanned_order_ids: List[UUID] = Field(min_length=1)
    timestamp: datetime

    @model_validator(mode="after")
    def reject_duplicate_scans(self):
        if len(self.scanned_order_ids) != len(set(self.scanned_order_ids)):
            raise ValueError("scanned_order_ids must not contain duplicates.")
        return self


class DriverEvidenceCapturedEvent(BaseModel):
    """Evidence object uploaded to Gateway storage and announced to Redis."""

    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    driver_id: UUID
    event_type: Literal[
        "pod.captured",
        "delivery.exception.evidence",
    ]
    route_id: UUID
    order_id: UUID
    object_key: str = Field(min_length=1, max_length=500)
    evidence_type: Literal["photo", "signature", "recipient_name"]
    timestamp: datetime
