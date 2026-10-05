# SQLAlchemy ORM models — mirrors schema.sql at the repository root exactly.
# schema.sql is the single source of truth. If this file disagrees with schema.sql,
# schema.sql wins and this file must be updated to match.
# Imported only by services/core_api and services/routing_worker.

import enum as python_enum
import uuid
from datetime import datetime
from typing import List, Optional

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import CITEXT, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


# ---------------------------------------------------------------------------
# Python enums — exact mirrors of Postgres ENUM types in schema.sql.
# ---------------------------------------------------------------------------

class UserRole(python_enum.Enum):
    customer      = "customer"
    merchant      = "merchant"
    dispatcher    = "dispatcher"
    driver        = "driver"
    fleet_manager = "fleet_manager"
    admin         = "admin"


class OrderStatus(python_enum.Enum):
    pending          = "pending"
    assigned         = "assigned"
    out_for_delivery = "out_for_delivery"
    delivered        = "delivered"
    attempt_failed   = "attempt_failed"
    returned         = "returned"
    cancelled        = "cancelled"


class VehicleType(python_enum.Enum):
    two_wheeler   = "two_wheeler"
    three_wheeler = "three_wheeler"
    van           = "van"
    light_truck   = "light_truck"


class DriverStatus(python_enum.Enum):
    """Driver onboarding lifecycle: pending → offline → available → on_route.
    rejected is terminal; the row is kept for audit."""
    pending   = "pending"
    offline   = "offline"
    available = "available"
    on_route  = "on_route"
    rejected  = "rejected"


class RouteStatus(python_enum.Enum):
    planned     = "planned"
    in_progress = "in_progress"
    completed   = "completed"
    cancelled   = "cancelled"


class StopStatus(python_enum.Enum):
    pending   = "pending"
    delivered = "delivered"
    failed    = "failed"
    skipped   = "skipped"


class FailureReason(python_enum.Enum):
    recipient_unavailable = "recipient_unavailable"
    wrong_address         = "wrong_address"
    refused               = "refused"
    other                 = "other"


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Auth tables
# ---------------------------------------------------------------------------

class User(Base):
    """Universal identity record for every human in the system.
    Roles are stored separately in UserRole_, not as a column here."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email IS NOT NULL OR phone IS NOT NULL",
            name="users_has_identifier",
        ),
        CheckConstraint(
            "phone IS NULL OR phone ~ '^\\+[1-9][0-9]{7,14}$'",
            name="users_phone_format",
        ),
    )

    id:                 Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    email:              Mapped[Optional[str]]      = mapped_column(CITEXT, unique=True, nullable=True)
    phone:              Mapped[Optional[str]]      = mapped_column(Text, unique=True, nullable=True)
    password_hash:      Mapped[str]                = mapped_column(Text, nullable=False)
    full_name:          Mapped[str]                = mapped_column(Text, nullable=False)
    is_active:          Mapped[bool]               = mapped_column(Boolean, nullable=False, server_default="true")
    failed_login_count: Mapped[int]                = mapped_column(Integer, nullable=False, server_default="0")
    locked_until:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:         Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at:         Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    roles:              Mapped[List["UserRole_"]]          = relationship("UserRole_", foreign_keys="UserRole_.user_id", back_populates="user", cascade="all, delete-orphan")
    refresh_tokens:     Mapped[List["RefreshToken"]]       = relationship(back_populates="user", cascade="all, delete-orphan")
    reset_tokens:       Mapped[List["PasswordResetToken"]]  = relationship(back_populates="user", cascade="all, delete-orphan")
    driver_profile:     Mapped[Optional["Driver"]]         = relationship(back_populates="user")


class UserRole_(Base):
    """Junction table granting a role to a user.
    Named UserRole_ to avoid collision with the UserRole enum class."""

    __tablename__ = "user_roles"

    user_id:    Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role:       Mapped[UserRole]            = mapped_column(Enum(UserRole, name="user_role"), primary_key=True)
    granted_at: Mapped[datetime]            = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    user:       Mapped["User"] = relationship("User", foreign_keys=[user_id], back_populates="roles")


class RefreshToken(Base):
    """Stores the hash of an active refresh token. revoked_at=NULL means active."""

    __tablename__ = "refresh_tokens"

    id:         Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id:    Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str]                = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


class PasswordResetToken(Base):
    """Stores the hash of a password-reset token. used_at=NULL means unused."""

    __tablename__ = "password_reset_tokens"

    id:         Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    user_id:    Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str]                = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False)
    used_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="reset_tokens")


# ---------------------------------------------------------------------------
# Domain tables
# ---------------------------------------------------------------------------

class Merchant(Base):
    """An organisation that creates orders. Not a person — individuals are
    linked via MerchantMember."""

    __tablename__ = "merchants"
    __table_args__ = (
        CheckConstraint(
            "contact_phone IS NULL OR contact_phone ~ '^\\+[1-9][0-9]{7,14}$'",
            name="merchants_contact_phone_format",
        ),
    )

    id:            Mapped[uuid.UUID]     = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    name:          Mapped[str]           = mapped_column(Text, nullable=False)
    contact_email: Mapped[Optional[str]] = mapped_column(CITEXT, nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active:     Mapped[bool]          = mapped_column(Boolean, nullable=False, server_default="true")
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    members: Mapped[List["MerchantMember"]] = relationship(back_populates="merchant", cascade="all, delete-orphan")
    orders:  Mapped[List["Order"]]          = relationship(back_populates="merchant")


class Warehouse(Base):
    """Fulfillment warehouse. location is a PostGIS geography point (lon, lat, SRID 4326).
    The GiST index on location enables O(log n) KNN nearest-warehouse queries."""

    __tablename__ = "warehouses"

    id:         Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    code:       Mapped[str]       = mapped_column(Text, unique=True, nullable=False)
    name:       Mapped[str]       = mapped_column(Text, nullable=False)
    address:    Mapped[str]       = mapped_column(Text, nullable=False)
    location:   Mapped[object]    = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    is_active:  Mapped[bool]      = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    staff:  Mapped[List["WarehouseStaff"]] = relationship(back_populates="warehouse", cascade="all, delete-orphan")
    orders: Mapped[List["Order"]]          = relationship(back_populates="warehouse")
    routes: Mapped[List["Route"]]          = relationship(back_populates="warehouse")
    

class MerchantMember(Base):
    """Scopes a user to a merchant organisation."""

    __tablename__ = "merchant_members"

    user_id:     Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    merchant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("merchants.id", ondelete="CASCADE"), primary_key=True)
    created_at:  Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user:     Mapped["User"]     = relationship("User")
    merchant: Mapped["Merchant"] = relationship(back_populates="members")


class WarehouseStaff(Base):
    """Scopes a user (dispatcher / fleet manager) to a warehouse."""

    __tablename__ = "warehouse_staff"

    user_id:      Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id", ondelete="CASCADE"), primary_key=True)
    created_at:   Mapped[datetime]  = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user:      Mapped["User"]      = relationship("User")
    warehouse: Mapped["Warehouse"] = relationship(back_populates="staff")


class Vehicle(Base):
    """A physical delivery vehicle. Assigned to at most one driver at a time
    (enforced by the UNIQUE constraint on drivers.vehicle_id)."""

    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("max_weight_kg > 0", name="vehicles_max_weight_positive"),
        CheckConstraint("max_volume_m3 > 0", name="vehicles_max_volume_positive"),
    )

    id:                  Mapped[uuid.UUID]   = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    type:                Mapped[VehicleType] = mapped_column(Enum(VehicleType, name="vehicle_type"), nullable=False)
    registration_number: Mapped[str]         = mapped_column(Text, unique=True, nullable=False)
    max_weight_kg:       Mapped[float]       = mapped_column(Numeric(10, 3), nullable=False)
    max_volume_m3:       Mapped[float]       = mapped_column(Numeric(10, 4), nullable=False)
    is_active:           Mapped[bool]        = mapped_column(Boolean, nullable=False, server_default="true")
    created_at:          Mapped[datetime]    = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at:          Mapped[datetime]    = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    driver: Mapped[Optional["Driver"]] = relationship(back_populates="vehicle")
    routes: Mapped[List["Route"]]      = relationship(back_populates="vehicle")


class Driver(Base):
    """Driver profile extending a User record (1:1).
    PK is user_id — a driver IS a user, not a separate entity.
    status defaults to 'pending' (approval required before going active)."""

    __tablename__ = "drivers"

    user_id:    Mapped[uuid.UUID]           = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), primary_key=True)
    vehicle_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"), unique=True, nullable=True)
    status:     Mapped[DriverStatus]        = mapped_column(Enum(DriverStatus, name="driver_status"), nullable=False, server_default="pending")
    created_at: Mapped[datetime]            = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime]            = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    user:    Mapped["User"]              = relationship(back_populates="driver_profile")
    vehicle: Mapped[Optional["Vehicle"]] = relationship(back_populates="driver")
    routes:  Mapped[List["Route"]]       = relationship(back_populates="driver")


class Order(Base):
    """Delivery order. warehouse_id is assigned at creation via PostGIS KNN.
    delivery_location is a PostGIS geography point snapshot of the dropoff.
    customer_id is nullable — guest orders have no registered user."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("merchant_id", "merchant_order_ref", name="uq_orders_merchant_ref"),
        CheckConstraint(
            "recipient_phone ~ '^\\+[1-9][0-9]{7,14}$'",
            name="orders_recipient_phone_format",
        ),
        CheckConstraint(
            "(window_earliest IS NULL) = (window_latest IS NULL)",
            name="orders_window_both_or_neither",
        ),
        CheckConstraint(
            "window_latest > window_earliest",
            name="orders_window_valid",
        ),
        CheckConstraint("weight_kg > 0", name="orders_weight_positive"),
        CheckConstraint("volume_m3 > 0", name="orders_volume_positive"),
    )

    id:                 Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    merchant_id:        Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("merchants.id"), nullable=False)
    merchant_order_ref: Mapped[str]                = mapped_column(Text, nullable=False)
    warehouse_id:       Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    customer_id:        Mapped[Optional[uuid.UUID]]= mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    status:             Mapped[OrderStatus]        = mapped_column(Enum(OrderStatus, name="order_status"), nullable=False, server_default="pending")
    recipient_name:     Mapped[str]                = mapped_column(Text, nullable=False)
    recipient_phone:    Mapped[str]                = mapped_column(Text, nullable=False)
    delivery_address:   Mapped[str]                = mapped_column(Text, nullable=False)
    delivery_location:  Mapped[object]             = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    window_earliest:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    window_latest:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    weight_kg:          Mapped[float]              = mapped_column(Numeric(10, 3), nullable=False)
    volume_m3:          Mapped[float]              = mapped_column(Numeric(10, 4), nullable=False)
    tracking_token:     Mapped[str]                = mapped_column(Text, unique=True, nullable=False)
    created_at:         Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at:         Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    merchant:    Mapped["Merchant"]         = relationship(back_populates="orders")
    warehouse:   Mapped["Warehouse"]        = relationship(back_populates="orders")
    route_stops: Mapped[List["RouteStop"]]  = relationship(back_populates="order")
    events:      Mapped[List["OrderEvent"]] = relationship(back_populates="order")


class Route(Base):
    """A planned sequence of delivery stops assigned to one driver + vehicle.
    version is used for optimistic concurrency control on rescue re-routes.
    The partial unique index uq_routes_driver_active (in schema.sql) ensures
    a driver can have at most one planned or in_progress route at a time."""

    __tablename__ = "routes"
    __table_args__ = (
        CheckConstraint("version > 0", name="routes_version_positive"),
        CheckConstraint("total_distance_m >= 0", name="routes_distance_non_negative"),
        CheckConstraint("total_duration_s >= 0", name="routes_duration_non_negative"),
    )

    id:               Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    warehouse_id:     Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False)
    driver_id:        Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("drivers.user_id"), nullable=False)
    vehicle_id:       Mapped[uuid.UUID]          = mapped_column(UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False)
    status:           Mapped[RouteStatus]        = mapped_column(Enum(RouteStatus, name="route_status"), nullable=False, server_default="planned")
    version:          Mapped[int]                = mapped_column(Integer, nullable=False, server_default="1")
    total_distance_m: Mapped[Optional[int]]      = mapped_column(Integer, nullable=True)
    total_duration_s: Mapped[Optional[int]]      = mapped_column(Integer, nullable=True)
    started_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:       Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at:       Mapped[datetime]           = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    warehouse: Mapped["Warehouse"]       = relationship(back_populates="routes")
    driver:    Mapped["Driver"]          = relationship(back_populates="routes")
    vehicle:   Mapped["Vehicle"]         = relationship(back_populates="routes")
    stops:     Mapped[List["RouteStop"]] = relationship(back_populates="route", cascade="all, delete-orphan")


class RouteStop(Base):
    """One stop in a route's ordered delivery sequence.
    planned_location is a snapshot of orders.delivery_location at planning time —
    it does not change if the order's address is updated after routing.
    sequence uniqueness is DEFERRABLE to allow full re-sequencing in one transaction."""

    __tablename__ = "route_stops"
    __table_args__ = (
        UniqueConstraint("route_id", "order_id", name="uq_route_stops_route_order"),
        UniqueConstraint("route_id", "sequence", name="uq_route_stops_sequence", deferrable=True, initially="DEFERRED"),
        CheckConstraint("sequence > 0", name="route_stops_sequence_positive"),
        CheckConstraint(
            "(status = 'failed') = (failure_reason IS NOT NULL)",
            name="route_stops_failure_reason_consistent",
        ),
        CheckConstraint(
            "(status IN ('delivered', 'failed')) = (completed_at IS NOT NULL)",
            name="route_stops_completed_at_consistent",
        ),
    )

    id:                 Mapped[uuid.UUID]                = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    route_id:           Mapped[uuid.UUID]                = mapped_column(UUID(as_uuid=True), ForeignKey("routes.id", ondelete="CASCADE"), nullable=False)
    order_id:           Mapped[uuid.UUID]                = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    sequence:           Mapped[int]                      = mapped_column(Integer, nullable=False)
    status:             Mapped[StopStatus]               = mapped_column(Enum(StopStatus, name="stop_status"), nullable=False, server_default="pending")
    failure_reason:     Mapped[Optional[FailureReason]]   = mapped_column(Enum(FailureReason, name="failure_reason"), nullable=True)
    planned_location:   Mapped[object]                   = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    planned_arrival_at: Mapped[datetime]                 = mapped_column(DateTime(timezone=True), nullable=False)
    arrived_at:         Mapped[Optional[datetime]]       = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at:       Mapped[Optional[datetime]]       = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:         Mapped[datetime]                 = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at:         Mapped[datetime]                 = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    route: Mapped["Route"] = relationship(back_populates="stops")
    order: Mapped["Order"] = relationship(back_populates="route_stops")


class OrderEvent(Base):
    """Append-only audit log of every order status transition.
    id is a bigint identity (sequential, not UUID) — optimal for a high-write log.
    actor_user_id=NULL means a system-generated transition (e.g. from routing worker)."""

    __tablename__ = "order_events"
    __table_args__ = (
        CheckConstraint(
            "from_status IS DISTINCT FROM to_status",
            name="order_events_distinct_status",
        ),
    )

    id:            Mapped[int]                    = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    order_id:      Mapped[uuid.UUID]              = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    from_status:   Mapped[Optional[OrderStatus]]  = mapped_column(Enum(OrderStatus, name="order_status"), nullable=True)
    to_status:     Mapped[OrderStatus]            = mapped_column(Enum(OrderStatus, name="order_status"), nullable=False)
    route_stop_id: Mapped[Optional[uuid.UUID]]    = mapped_column(UUID(as_uuid=True), ForeignKey("route_stops.id"), nullable=True)
    actor_user_id: Mapped[Optional[uuid.UUID]]    = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    occurred_at:   Mapped[datetime]               = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    order: Mapped["Order"] = relationship(back_populates="events")
