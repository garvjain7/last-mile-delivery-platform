
from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Numeric,
    Text,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, ENUM
from sqlalchemy.sql import func
from geoalchemy2 import Geography

from app.base import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.uuid_generate_v4()
    )

    merchant_id = Column(
        UUID(as_uuid=True),
        ForeignKey("merchants.id"),
        nullable=False
    )

    merchant_order_ref = Column(Text, nullable=False)

    warehouse_id = Column(
        UUID(as_uuid=True),
        ForeignKey("warehouses.id"),
        nullable=False
    )

    customer_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True
    )

    status = Column(
        ENUM(
            "pending",
            "assigned",
            "out_for_delivery",
            "delivered",
            "attempt_failed",
            "returned",
            "cancelled",
            name="order_status",
            create_type=False
        ),
        nullable=False,
        server_default="pending"
    )

    recipient_name = Column(Text, nullable=False)
    recipient_phone = Column(Text, nullable=False)
    delivery_address = Column(Text, nullable=False)

    delivery_location = Column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False
    )

    window_earliest = Column(DateTime(timezone=True), nullable=True)
    window_latest = Column(DateTime(timezone=True), nullable=True)

    weight_kg = Column(Numeric(10, 3), nullable=False)
    volume_m3 = Column(Numeric(10, 4), nullable=False)

    tracking_token = Column(Text, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now()
    )

    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint("weight_kg > 0", name="ck_orders_weight_positive"),
        CheckConstraint("volume_m3 > 0", name="ck_orders_volume_positive"),
        CheckConstraint(
            "(window_earliest IS NULL) = (window_latest IS NULL)",
            name="ck_orders_window_both_or_neither",
        ),
        CheckConstraint(
            "window_latest > window_earliest",
            name="ck_orders_window_order",
        ),
        UniqueConstraint(
            "merchant_id",
            "merchant_order_ref",
            name="orders_merchant_id_merchant_order_ref_key",
        ),
        UniqueConstraint("tracking_token", name="orders_tracking_token_key"),
    )