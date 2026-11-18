"""Request and response schemas for driver self-service endpoints."""

import re
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator, model_validator


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
    order_status: str
    recipient_name: str
    recipient_phone: str
    delivery_address: str
    tracking_token: str
    planned_distance_m: Optional[int] = None
    window_earliest: Optional[str]
    window_latest: Optional[str]
    planned_arrival_at: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


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
    pickup_latitude: Optional[float] = None
    pickup_longitude: Optional[float] = None
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


class PaymentMethodCreate(BaseModel):
    method_type: Literal["upi", "bank_account"]
    upi_id: Optional[SecretStr] = None
    account_holder_name: Optional[SecretStr] = None
    account_number: Optional[SecretStr] = None
    ifsc_code: Optional[SecretStr] = None
    is_preferred: bool = False

    @model_validator(mode="after")
    def validate_method_details(self):
        if self.method_type == "upi":
            if self.account_holder_name or self.account_number or self.ifsc_code:
                raise ValueError("UPI methods must not include bank account fields.")
            if self.upi_id is None:
                raise ValueError("upi_id is required for a UPI method.")
            upi_id = self.upi_id.get_secret_value().strip()
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,255}@[A-Za-z0-9.-]{2,64}", upi_id):
                raise ValueError("upi_id is not a valid UPI handle.")
            self.upi_id = SecretStr(upi_id)
            return self

        if self.upi_id:
            raise ValueError("Bank account methods must not include a UPI handle.")
        if not all((self.account_holder_name, self.account_number, self.ifsc_code)):
            raise ValueError("Bank account methods require holder name, account number, and IFSC.")
        holder_name = self.account_holder_name.get_secret_value().strip()
        account_number = self.account_number.get_secret_value().strip()
        ifsc_code = self.ifsc_code.get_secret_value().strip().upper()
        if not holder_name or len(holder_name) > 200:
            raise ValueError("account_holder_name must contain 1 to 200 characters.")
        if not re.fullmatch(r"[0-9]{6,18}", account_number):
            raise ValueError("account_number must contain 6 to 18 digits.")
        if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", ifsc_code):
            raise ValueError("ifsc_code is not a valid IFSC code.")
        self.account_holder_name = SecretStr(holder_name)
        self.account_number = SecretStr(account_number)
        self.ifsc_code = SecretStr(ifsc_code)
        return self


class PaymentMethodResponse(BaseModel):
    method_id: UUID
    method_type: Literal["upi", "bank_account"]
    masked_details: str
    is_preferred: bool
    created_at: datetime


class DriverEarningTransactionResponse(BaseModel):
    transaction_id: UUID
    entry_type: str
    amount: Decimal
    currency: Literal["INR"]
    description: str
    order_id: Optional[UUID]
    created_at: datetime


class DriverEarningsResponse(BaseModel):
    currency: Literal["INR"]
    available_balance: Decimal
    base_pay: Decimal
    tips: Decimal
    bonuses: Decimal
    adjustments: Decimal
    total_earned: Decimal
    recent_transactions: list[DriverEarningTransactionResponse]


class DriverEarningsAdjustmentRequest(BaseModel):
    driver_id: UUID
    entry_type: Literal["tip", "bonus", "adjustment"]
    amount: Decimal = Field(max_digits=12, decimal_places=2)
    idempotency_key: UUID
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_adjustment(self):
        if not self.reason:
            raise ValueError("reason cannot be blank.")
        if self.amount == 0:
            raise ValueError("amount cannot be zero.")
        if self.entry_type in {"tip", "bonus"} and self.amount < 0:
            raise ValueError("tips and bonuses must be positive.")
        return self
