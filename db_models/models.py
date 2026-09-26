# SQLAlchemy ORM model definitions for PostgreSQL database tables.
# Single source of truth for Facility, Order, Driver, Vehicle, Route, RouteStop, DeliveryAttempt, and ProcessedEvent.

from datetime import datetime
from typing import Optional
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text

class Base(DeclarativeBase):
    pass

class Facility(Base):
    """Facility model representing fulfillment warehouse locations."""
    __tablename__ = "facility"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    # location: GEOGRAPHY POINT (PostGIS)
    location: Mapped[str] = mapped_column(String, nullable=False)

class Order(Base):
    """Order model representing delivery packages and dropoff details."""
    __tablename__ = "order"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    retailer_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    pickup_facility_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("facility.id"), nullable=True)
    dropoff_location: Mapped[str] = mapped_column(String, nullable=False)
    dropoff_raw_address: Mapped[str] = mapped_column(String, nullable=False)
    time_window: Mapped[str] = mapped_column(String, nullable=False)
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    volume_l: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Driver(Base):
    """Driver model representing fleet operators."""
    __tablename__ = "driver"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    current_location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    location_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class Vehicle(Base):
    """Vehicle model representing capacity and shift constraints."""
    __tablename__ = "vehicle"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    driver_id: Mapped[str] = mapped_column(String, ForeignKey("driver.id"), nullable=False)
    capacity_kg: Mapped[float] = mapped_column(Float, nullable=False)
    capacity_l: Mapped[float] = mapped_column(Float, nullable=False)
    shift_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    shift_end: Mapped[datetime] = mapped_column(DateTime, nullable=False)

class Route(Base):
    """Route model representing assigned sequence of stops for a vehicle."""
    __tablename__ = "route"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(String, ForeignKey("vehicle.id"), nullable=False)
    driver_id: Mapped[str] = mapped_column(String, ForeignKey("driver.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RouteStop(Base):
    """RouteStop model representing an individual stop in a route sequence."""
    __tablename__ = "route_stop"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    route_id: Mapped[str] = mapped_column(String, ForeignKey("route.id"), nullable=False)
    order_id: Mapped[str] = mapped_column(String, ForeignKey("order.id"), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    eta: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)

class DeliveryAttempt(Base):
    """DeliveryAttempt model representing terminal execution outcomes and proof of delivery."""
    __tablename__ = "delivery_attempt"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    order_id: Mapped[str] = mapped_column(String, ForeignKey("order.id"), nullable=False)
    route_id: Mapped[str] = mapped_column(String, ForeignKey("route.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String, nullable=False)
    pod_photo_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    failure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ProcessedEvent(Base):
    """ProcessedEvent model for client-generated UUID deduplication (idempotency)."""
    __tablename__ = "processed_event"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
