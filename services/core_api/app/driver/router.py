"""Authenticated driver self-service REST API."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from db_models.models import Driver, Route, RouteStatus, RouteStop, StopStatus, Vehicle
from services.core_api.app.database.connection import get_db_session
from services.core_api.app.driver.dependencies import require_driver
from services.core_api.app.driver.schemas import (
    AssignVehicleRequest,
    DriverProfilePatch,
    DriverProfileResponse,
    DriverRouteResponse,
    DriverScanValidationRequest,
    RouteAcceptanceResponse,
    VehicleResponse,
)
from services.core_api.app.driver.service import (
    accept_assigned_route,
    assign_vehicle,
    find_available_vehicles,
    is_unique_violation,
    list_driver_routes,
    normalize_registration_number,
    profile_payload,
    route_payload,
    update_driver_profile,
)

router = APIRouter()


@router.get("/profile", response_model=DriverProfileResponse)
async def get_profile(user=Depends(require_driver)):
    """Return the signed-in driver's editable profile and assigned vehicle."""
    return profile_payload(user)


@router.patch("/profile", response_model=DriverProfileResponse)
async def patch_profile(
    payload: DriverProfilePatch,
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    """Update full name and/or E.164 phone; status remains staff-managed."""
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("phone") is None and user.email is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A phone-only account must retain a phone number.",
        )
    try:
        await update_driver_profile(db, user, changes)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if is_unique_violation(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phone number is already in use.") from exc
        raise
    return profile_payload(user)


@router.get("/vehicles", response_model=list[VehicleResponse])
async def get_vehicles(
    search: Optional[str] = Query(default=None, min_length=1, max_length=100),
    limit: int = Query(default=25, ge=1, le=100),
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    """Search active, unassigned vehicles by registration number."""
    vehicles = await find_available_vehicles(db, user.id, search, limit)
    return [
        {
            "vehicle_id": vehicle.id,
            "type": vehicle.type.value,
            "registration_number": vehicle.registration_number,
            "max_weight_kg": float(vehicle.max_weight_kg),
            "max_volume_m3": float(vehicle.max_volume_m3),
        }
        for vehicle in vehicles
    ]


@router.put("/vehicle", response_model=DriverProfileResponse)
async def put_vehicle(
    payload: AssignVehicleRequest,
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    """Assign an active, unassigned vehicle identified by UUID or registration."""
    registration = normalize_registration_number(payload.registration_number)
    statement = select(Vehicle).where(Vehicle.is_active.is_(True))
    if payload.vehicle_id:
        statement = statement.where(Vehicle.id == payload.vehicle_id)
    else:
        statement = statement.where(func.upper(Vehicle.registration_number) == registration)
    vehicle = await db.scalar(statement.with_for_update())
    if vehicle is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Active vehicle not found.")

    current_assignment = await db.scalar(
        select(Driver).where(Driver.vehicle_id == vehicle.id, Driver.user_id != user.id)
    )
    if current_assignment is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle is already assigned.")

    try:
        await assign_vehicle(db, user.id, vehicle)
        await db.commit()
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except IntegrityError as exc:
        await db.rollback()
        if is_unique_violation(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Vehicle was assigned to another driver.") from exc
        raise

    user.driver_profile.vehicle = vehicle
    return profile_payload(user)


@router.get("/routes", response_model=list[DriverRouteResponse])
async def get_routes(
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    """List routes already assigned to this driver that are planned or in progress."""
    routes = await list_driver_routes(db, user.id)
    return [route_payload(route) for route in routes]


@router.post(
    "/routes/{route_id}/accept",
    response_model=RouteAcceptanceResponse,
    status_code=status.HTTP_200_OK,
)
async def post_accept_route(
    route_id: UUID,
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    """Start an assigned planned route; repeated acceptance is idempotent."""
    try:
        route, driver = await accept_assigned_route(db, user.id, route_id)
        await db.commit()
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except RuntimeError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return {"route": route_payload(route), "driver_status": driver.status.value}


@router.post("/routes/{route_id}/scan", status_code=status.HTTP_200_OK)
async def validate_driver_scan(
    route_id: UUID,
    payload: DriverScanValidationRequest,
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    """Verify a scanned parcel belongs to the driver's assigned active route."""
    statement = (
        select(RouteStop)
        .join(Route, RouteStop.route_id == Route.id)
        .where(
            Route.id == route_id,
            Route.driver_id == user.id,
            Route.status == RouteStatus.in_progress,
            RouteStop.status == StopStatus.pending,
            RouteStop.order.has(tracking_token=payload.tracking_token.strip()),
        )
    )
    if payload.order_id is not None:
        statement = statement.where(RouteStop.order_id == payload.order_id)
    stop = await db.scalar(statement)
    if stop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Parcel is not an open stop on this assigned route.",
        )
    return {
        "route_id": route_id,
        "order_id": stop.order_id,
        "sequence": stop.sequence,
        "scan_stage": payload.scan_stage,
        "verified": True,
    }


@router.post(
    "/routes/{route_id}/stops/{order_id}/pod-authorize",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def authorize_driver_pod(
    route_id: UUID,
    order_id: UUID,
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    """Authorize evidence upload for an open stop on the driver's active route."""
    stop = await db.scalar(
        select(RouteStop)
        .join(Route, RouteStop.route_id == Route.id)
        .where(
            Route.id == route_id,
            Route.driver_id == user.id,
            Route.status == RouteStatus.in_progress,
            RouteStop.order_id == order_id,
            RouteStop.status == StopStatus.pending,
        )
    )
    if stop is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Open stop not found on this driver's active route.",
        )
