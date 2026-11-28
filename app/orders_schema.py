
import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class OrderCreate(BaseModel):
    merchant_id: str
    merchant_order_ref: str
    warehouse_id: str

    customer_id: Optional[str] = None

    recipient_name: str = Field(min_length=1)
    recipient_phone: str
    delivery_address: str = Field(min_length=1)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    window_earliest: Optional[datetime] = None
    window_latest: Optional[datetime] = None

    weight_kg: float = Field(gt=0)
    volume_m3: float = Field(gt=0)

    tracking_token: Optional[str] = None

    @field_validator("recipient_phone")
    @classmethod
    def validate_phone(cls, value):
        if not re.fullmatch(r"\+[1-9][0-9]{7,14}", value):
            raise ValueError(
                "Phone must start with country code, e.g. +919876543210"
            )
        return value

    @model_validator(mode="after")
    def validate_delivery_window(self):
        earliest = self.window_earliest
        latest = self.window_latest

        if (earliest is None) != (latest is None):
            raise ValueError(
                "window_earliest and window_latest must both be provided or both be null"
            )

        if earliest is not None and latest is not None and latest <= earliest:
            raise ValueError(
                "window_latest must be later than window_earliest"
            )

        return self