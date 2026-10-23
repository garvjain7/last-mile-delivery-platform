

import uuid

from sqlalchemy import Column, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from app.base import Base


class Driver(Base):
    __tablename__ = "drivers"

    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        primary_key=True,
        nullable=False
    )

    vehicle_id = Column(
        UUID(as_uuid=True),
        ForeignKey("vehicles.id"),
        unique=True,
        nullable=True
    )

    status = Column(
        "status",
        # Existing PostgreSQL enum created by schema.sql
        # Use the database's existing enum type.
        __import__("sqlalchemy").Enum(
            "pending",
            "offline",
            "available",
            "on_route",
            "rejected",
            name="driver_status",
            create_type=False
        ),
        nullable=False,
        server_default="pending"
    )

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
