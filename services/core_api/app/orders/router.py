# Ingests orders, fires PostGIS KNN, appends to orders_stream
# Router handling order ingestion and PostGIS nearest-facility assignment.

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter()

class CreateOrderRequest(BaseModel):
    """Payload schema for order creation request."""
    retailer_id: str
    dropoff_raw_address: str
    time_window: str
    weight_kg: float
    volume_l: float

class CreateOrderResponse(BaseModel):
    """Response schema following order creation and facility assignment."""
    order_id: str
    pickup_facility_id: str
    status: str

@router.post("/", response_model=CreateOrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(payload: CreateOrderRequest):
    """
    Ingest order, geocode address via Nominatim, assign nearest facility via PostGIS KNN (<->),
    persist order to Postgres, and publish order.created event to orders_stream.
    """
    # TODO: Geocode dropoff address via Nominatim (httpx AsyncClient with timeout)
    # TODO: Execute PostGIS KNN (<->) query to find nearest pickup_facility_id
    # TODO: Persist order record in Postgres via db-models
    # TODO: Publish order.created event to orders_stream with MAXLEN ~ 50000
    return CreateOrderResponse(
        order_id="ord-stub-123",
        pickup_facility_id="fac-stub-456",
        status="created"
    )
