"""Database operations for driver profile, vehicle, and assigned route APIs."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from db_models.models import (
    Driver,
    DriverStatus,
    Route,
    RouteStatus,
    RouteStop,
    User,
    Vehicle,
    Warehouse,
)


def vehicle_payload(vehicle: Optional[Vehicle]) -> Optional[dict]:
    if vehicle is None:
        return None
    return {
        "vehicle_id": vehicle.id,
        "type": vehicle.type.value,
        "registration_number": vehicle.registration_number,
        "max_weight_kg": float(vehicle.max_weight_kg),
        "max_volume_m3": float(vehicle.max_volume_m3),
    }


def profile_payload(user: User) -> dict:
    return {
        "user_id": user.id,
        "full_name": user.full_name,
        "email": str(user.email) if user.email else None,
        "phone": user.phone,
        "status": user.driver_profile.status.value,
        "vehicle": vehicle_payload(user.driver_profile.vehicle),
    }


def route_payload(route: Route, locations: Optional[dict] = None) -> dict:
    stops = sorted(route.stops, key=lambda stop: stop.sequence)
    route_locations = locations or {}
    pickup_location = route_locations.get("pickup", {})
    stop_locations = route_locations.get("stops", {})
    return {
        "route_id": route.id,
        "status": route.status.value,
        "version": route.version,
        "total_distance_m": route.total_distance_m,
        "total_duration_s": route.total_duration_s,
        "warehouse_id": route.warehouse_id,
        "pickup_name": route.warehouse.name,
        "pickup_address": route.warehouse.address,
        "pickup_code": route.warehouse.code,
        "pickup_latitude": pickup_location.get("latitude"),
        "pickup_longitude": pickup_location.get("longitude"),
        "vehicle_id": route.vehicle_id,
        "vehicle_registration": route.vehicle.registration_number,
        "stops": [
            {
                "route_stop_id": stop.id,
                "order_id": stop.order_id,
                "sequence": stop.sequence,
                "status": stop.status.value,
                "order_status": stop.order.status.value,
                "recipient_name": stop.order.recipient_name,
                "recipient_phone": stop.order.recipient_phone,
                "delivery_address": stop.order.delivery_address,
                "tracking_token": stop.order.tracking_token,
                "planned_distance_m": getattr(stop, "planned_distance_m", None),
                "window_earliest": (
                    stop.order.window_earliest.isoformat()
                    if stop.order.window_earliest
                    else None
                ),
                "window_latest": (
                    stop.order.window_latest.isoformat()
                    if stop.order.window_latest
                    else None
                ),
                "planned_arrival_at": stop.planned_arrival_at.isoformat(),
                "latitude": stop_locations.get(stop.id, {}).get("latitude"),
                "longitude": stop_locations.get(stop.id, {}).get("longitude"),
            }
            for stop in stops
        ],
    }


async def route_location_payload(db: AsyncSession, route_ids: list[uuid.UUID]) -> dict:
    if not route_ids:
        return {}

    point_type = Geometry(geometry_type="POINT", srid=4326)
    warehouse_point = cast(Warehouse.location, point_type)
    warehouse_result = await db.execute(
        select(
            Route.id,
            func.ST_Y(warehouse_point).label("latitude"),
            func.ST_X(warehouse_point).label("longitude"),
        )
        .join(Warehouse, Route.warehouse_id == Warehouse.id)
        .where(Route.id.in_(route_ids))
    )
    locations = {
        route_id: {
            "pickup": {
                "latitude": float(latitude),
                "longitude": float(longitude),
            },
            "stops": {},
        }
        for route_id, latitude, longitude in warehouse_result.all()
    }

    stop_point = cast(RouteStop.planned_location, point_type)
    stop_result = await db.execute(
        select(
            RouteStop.route_id,
            RouteStop.id,
            func.ST_Y(stop_point).label("latitude"),
            func.ST_X(stop_point).label("longitude"),
        ).where(RouteStop.route_id.in_(route_ids))
    )
    for route_id, stop_id, latitude, longitude in stop_result.all():
        locations.setdefault(route_id, {"pickup": {}, "stops": {}})["stops"][stop_id] = {
            "latitude": float(latitude),
            "longitude": float(longitude),
        }
    return locations


def route_load_options():
    return (
        joinedload(Route.warehouse),
        joinedload(Route.vehicle),
        selectinload(Route.stops).joinedload(RouteStop.order),
    )


async def list_driver_routes(db: AsyncSession, driver_id: uuid.UUID) -> list[Route]:
    result = await db.scalars(
        select(Route)
        .options(*route_load_options())
        .where(
            Route.driver_id == driver_id,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress]),
        )
        .order_by(Route.created_at.desc())
    )
    return list(result.unique().all())


async def get_driver_route(
    db: AsyncSession,
    driver_id: uuid.UUID,
    route_id: uuid.UUID,
) -> Optional[Route]:
    return await db.scalar(
        select(Route)
        .options(*route_load_options())
        .where(Route.id == route_id, Route.driver_id == driver_id)
    )


async def find_available_vehicles(
    db: AsyncSession,
    driver_id: uuid.UUID,
    search: Optional[str],
    limit: int,
) -> list[Vehicle]:
    statement = (
        select(Vehicle)
        .outerjoin(Driver, Driver.vehicle_id == Vehicle.id)
        .where(
            Vehicle.is_active.is_(True),
            or_(Driver.user_id.is_(None), Driver.user_id == driver_id),
        )
        .order_by(Vehicle.registration_number)
        .limit(limit)
    )
    if search:
        statement = statement.where(Vehicle.registration_number.ilike(f"%{search.strip()}%"))
    result = await db.scalars(statement)
    return list(result.all())


async def assign_vehicle(
    db: AsyncSession,
    driver_id: uuid.UUID,
    vehicle: Vehicle,
) -> None:
    driver = await db.scalar(
        select(Driver).where(Driver.user_id == driver_id).with_for_update()
    )
    if driver is None:
        raise LookupError("Driver profile not found.")
    if driver.status == DriverStatus.on_route:
        raise RuntimeError("Vehicle cannot be changed while a route is in progress.")
    active_route = await db.scalar(
        select(Route.id).where(
            Route.driver_id == driver_id,
            Route.status.in_([RouteStatus.planned, RouteStatus.in_progress]),
        ).limit(1)
    )
    if active_route is not None:
        raise RuntimeError("Vehicle cannot be changed while an active route is assigned.")
    driver.vehicle_id = vehicle.id
    driver.updated_at = datetime.now(timezone.utc)


async def accept_assigned_route(
    db: AsyncSession,
    driver_id: uuid.UUID,
    route_id: uuid.UUID,
) -> tuple[Route, Driver]:
    driver = await db.scalar(
        select(Driver).where(Driver.user_id == driver_id).with_for_update()
    )
    if driver is None:
        raise LookupError("Driver profile not found.")

    route = await db.scalar(
        select(Route)
        .where(Route.id == route_id, Route.driver_id == driver_id)
        .with_for_update()
    )
    if route is None:
        raise LookupError("Route not found.")

    if route.status == RouteStatus.in_progress and driver.status == DriverStatus.on_route:
        pass
    elif route.status != RouteStatus.planned:
        raise RuntimeError("Only an assigned planned route can be accepted.")
    elif driver.status != DriverStatus.available:
        raise RuntimeError("Driver must be available before starting a route.")
    elif driver.vehicle_id != route.vehicle_id:
        raise RuntimeError("Assigned vehicle does not match this route's vehicle.")
    else:
        now = datetime.now(timezone.utc)
        route.status = RouteStatus.in_progress
        route.started_at = now
        route.updated_at = now
        driver.status = DriverStatus.on_route
        driver.updated_at = now

    await db.flush()
    loaded_route = await get_driver_route(db, driver_id, route_id)
    if loaded_route is None:
        raise LookupError("Route not found.")
    return loaded_route, driver


async def update_driver_profile(
    db: AsyncSession,
    user: User,
    fields: dict,
) -> None:
    for field, value in fields.items():
        if field in {"full_name", "phone"}:
            setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()


def normalize_registration_number(value: Optional[str]) -> Optional[str]:
    return value.strip().upper() if value else None


def is_unique_violation(error: IntegrityError) -> bool:
    sqlstate = getattr(error.orig, "sqlstate", None) or getattr(error.orig, "pgcode", None)
    constraint = getattr(error.orig, "constraint_name", None)
    return sqlstate == "23505" or constraint in {"users_phone_key", "drivers_vehicle_id_key"}
