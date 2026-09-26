# Hard definitions of order_stream, route_stream, driver_stream
# Strict Pydantic event envelope definitions per Redis Stream.

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class OrderCreatedEvent(BaseModel):
    """Event envelope for orders_stream when a new order is ingested and assigned a facility."""
    event_id: str
    order_id: str
    retailer_id: str
    pickup_facility_id: str
    dropoff_location: str
    dropoff_raw_address: str
    time_window: str
    weight_kg: float
    volume_l: float
    created_at: str

class RoutePublishedEvent(BaseModel):
    """Event envelope for route_stream published by Routing Worker after VROOM solve."""
    event_id: str
    route_id: str
    vehicle_id: str
    driver_id: str
    stops: List[Dict[str, Any]]
    created_at: str

class DriverTelemetryEvent(BaseModel):
    """Event envelope for driver_events_stream (location updates, arrivals, completed, failed)."""
    event_id: str
    driver_id: str
    event_type: str  # e.g., 'driver.location.updated', 'stop.arrived', 'delivery.completed', 'delivery.failed'
    latitude: float
    longitude: float
    current_route_id: Optional[str] = None
    order_id: Optional[str] = None
    pod_photo_url: Optional[str] = None
    failure_reason: Optional[str] = None
    timestamp: str
