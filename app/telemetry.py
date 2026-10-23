
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.base import Base


class Telemetry(Base):
    __tablename__ = "telemetry"

    telemetry_id = Column(Integer, primary_key=True, autoincrement=True)

    driver_id = Column(
        String,
        ForeignKey("drivers.driver_id"),
        nullable=False
    )

    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    speed = Column(Float, nullable=True)

    timestamp = Column(
        DateTime,
        server_default=func.now(),
        nullable=False
    )
