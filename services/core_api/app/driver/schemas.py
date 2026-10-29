"""Request and response schemas for driver self-service endpoints."""

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


class DriverProfilePatch(BaseModel):
    """Editable user-owned profile fields; driver status is staff-managed."""

    full_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    phone: Optional[str] = Field(default=None, pattern=r"^\+[1-9][0-9]{7,14}$")

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one profile field to update.")
        if "full_name" in self.model_fields_set and not self.full_name:
            raise ValueError("full_name cannot be blank.")
        return self


class DriverProfileResponse(BaseModel):
    user_id: UUID
    full_name: str
    email: Optional[EmailStr]
    phone: Optional[str]
    status: str
    vehicle: Optional[dict]


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: UUID
    type: str
    registration_number: str
    max_weight_kg: float
    max_volume_m3: float


class AssignVehicleRequest(BaseModel):
    vehicle_id: Optional[UUID] = None
    registration_number: Optional[str] = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def require_vehicle_identifier(self):
        if (self.vehicle_id is None) == (self.registration_number is None):
            raise ValueError("Provide exactly one of vehicle_id or registration_number.")
        return self


class RouteStopResponse(BaseModel):
    route_stop_id: UUID
    order_id: UUID
    sequence: int
    status: str
    recipient_name: str
    recipient_phone: str
    delivery_address: str
    tracking_token: str
    window_earliest: Optional[str]
    window_latest: Optional[str]
    planned_arrival_at: str


class DriverRouteResponse(BaseModel):
    route_id: UUID
    status: str
    version: int
    total_distance_m: Optional[int]
    total_duration_s: Optional[int]
    warehouse_id: UUID
    pickup_name: str
    pickup_address: str
    pickup_code: str
    vehicle_id: UUID
    vehicle_registration: str
    stops: list[RouteStopResponse]


class RouteAcceptanceResponse(BaseModel):
    route: DriverRouteResponse
    driver_status: str


class DriverScanValidationRequest(BaseModel):
    tracking_token: str = Field(min_length=1, max_length=200)
    scan_stage: Literal["pickup", "stop"]
    order_id: Optional[UUID] = None

    @field_validator("tracking_token")
    @classmethod
    def normalize_tracking_token(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("tracking_token cannot be blank.")
        return token

    @model_validator(mode="after")
    def require_order_for_stop_scan(self):
        if self.scan_stage == "stop" and self.order_id is None:
            raise ValueError("order_id is required for a stop scan.")
        return self
