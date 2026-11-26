"""Build and persist warehouse delivery routes solved by OSRM and VROOM."""

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID, uuid4

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKTElement
from sqlalchemy import cast, exists, func, select

from db_models.models import (
    Driver,
    DriverStatus,
    Order,
    OrderEvent,
    OrderStatus,
    Route,
    RouteStatus,
    RouteStop,
    StopStatus,
    User,
    Vehicle,
    Warehouse,
)
from services.routing_worker.app.database.connection import async_session_factory
from services.routing_worker.app.engines.osrm import OSRMClient
from services.routing_worker.app.engines.vroom import VROOMClient
from streaming.schemas.events import RoutePublishedEvent

logger = logging.getLogger(__name__)
ORDERABLE_STATUSES = (OrderStatus.placed, OrderStatus.sent, OrderStatus.pending)
ACTIVE_ROUTE_STATUSES = (RouteStatus.planned, RouteStatus.in_progress)
WEIGHT_UNIT_SCALE = Decimal("1000")
VOLUME_UNIT_SCALE = Decimal("10000")


@dataclass(frozen=True)
class PlanningOrder:
    order_id: UUID
    status: OrderStatus
    longitude: float
    latitude: float
    weight_kg: Decimal
    volume_m3: Decimal
    window_earliest: datetime | None
    window_latest: datetime | None
    tracking_token: str


@dataclass(frozen=True)
class PlanningVehicle:
    driver_id: UUID
    driver_name: str
    vehicle_id: UUID
    vehicle_registration: str
    max_weight_kg: Decimal
    max_volume_m3: Decimal


class RoutePlanChanged(Exception):
    """The database snapshot changed while a route was being solved."""


class InvalidOrderEvent(Exception):
    """An order stream event does not match its stored order."""


def _scaled_capacity(value: Decimal, scale: Decimal) -> int:
    return int((value * scale).to_integral_value(rounding=ROUND_HALF_UP))


def build_vroom_problem(
    orders: list[PlanningOrder],
    vehicles: list[PlanningVehicle],
    durations: list[list[int]],
    distances: list[list[int]],
    planning_started_at: datetime,
) -> tuple[dict[str, Any], dict[int, UUID]]:
    jobs = []
    job_order_ids = {}
    for location_index, order in enumerate(orders, start=1):
        job_id = location_index
        job = {
            "id": job_id,
            "location_index": location_index,
            "delivery": [
                _scaled_capacity(order.weight_kg, WEIGHT_UNIT_SCALE),
                _scaled_capacity(order.volume_m3, VOLUME_UNIT_SCALE),
            ],
        }
        if order.window_earliest and order.window_latest:
            if order.window_latest < planning_started_at:
                continue
            earliest = max(
                0,
                int((order.window_earliest - planning_started_at).total_seconds()),
            )
            latest = int((order.window_latest - planning_started_at).total_seconds())
            if earliest > latest:
                continue
            job["time_windows"] = [[earliest, latest]]
        jobs.append(job)
        job_order_ids[job_id] = order.order_id

    problem_vehicles = [
        {
            "id": index,
            "profile": "car",
            "start_index": 0,
            "end_index": 0,
            "capacity": [
                _scaled_capacity(vehicle.max_weight_kg, WEIGHT_UNIT_SCALE),
                _scaled_capacity(vehicle.max_volume_m3, VOLUME_UNIT_SCALE),
            ],
            "description": vehicle.vehicle_registration,
        }
        for index, vehicle in enumerate(vehicles, start=1)
    ]
    problem = {
        "jobs": jobs,
        "vehicles": problem_vehicles,
        "matrices": {
            "car": {
                "durations": durations,
                "distances": distances,
            }
        },
    }
    return problem, job_order_ids


async def _load_planning_snapshot(warehouse_id: UUID, trigger_order_id: UUID):
    point_type = Geometry(geometry_type="POINT", srid=4326)
    async with async_session_factory() as session:
        trigger_order = await session.get(Order, trigger_order_id)
        if trigger_order is None:
            return None, [], [], True, []
        if trigger_order.warehouse_id != warehouse_id:
            raise InvalidOrderEvent("Order event warehouse does not match the stored order.")
        existing_route_id = await session.scalar(
            select(RouteStop.route_id).where(RouteStop.order_id == trigger_order_id)
        )
        if existing_route_id is not None:
            route_event = await _load_route_event(session, existing_route_id)
            return None, [], [], True, [route_event] if route_event else []
        if trigger_order.status not in ORDERABLE_STATUSES:
            return None, [], [], True, []

        warehouse_row = (
            await session.execute(
                select(
                    Warehouse.id,
                    func.ST_X(cast(Warehouse.location, point_type)),
                    func.ST_Y(cast(Warehouse.location, point_type)),
                ).where(Warehouse.id == warehouse_id, Warehouse.is_active.is_(True))
            )
        ).one_or_none()
        if warehouse_row is None:
            raise ValueError(f"Active warehouse {warehouse_id} was not found.")
        warehouse_coordinates = (float(warehouse_row[1]), float(warehouse_row[2]))

        order_point = cast(Order.delivery_location, point_type)
        routed_orders = await session.execute(
            select(
                Order.id,
                Order.status,
                func.ST_X(order_point),
                func.ST_Y(order_point),
                Order.weight_kg,
                Order.volume_m3,
                Order.window_earliest,
                Order.window_latest,
                Order.tracking_token,
            )
            .where(
                Order.warehouse_id == warehouse_id,
                Order.status.in_(ORDERABLE_STATUSES),
                ~exists(select(RouteStop.id).where(RouteStop.order_id == Order.id)),
            )
            .order_by(Order.created_at, Order.id)
        )
        orders = [
            PlanningOrder(
                order_id=row[0],
                status=row[1],
                longitude=float(row[2]),
                latitude=float(row[3]),
                weight_kg=Decimal(row[4]),
                volume_m3=Decimal(row[5]),
                window_earliest=row[6],
                window_latest=row[7],
                tracking_token=row[8],
            )
            for row in routed_orders.all()
        ]
        active_route = exists(
            select(Route.id).where(
                Route.driver_id == Driver.user_id,
                Route.status.in_(ACTIVE_ROUTE_STATUSES),
            )
        )
        available_vehicles = await session.execute(
            select(
                Driver.user_id,
                User.full_name,
                Vehicle.id,
                Vehicle.registration_number,
                Vehicle.max_weight_kg,
                Vehicle.max_volume_m3,
            )
            .join(User, User.id == Driver.user_id)
            .join(Vehicle, Vehicle.id == Driver.vehicle_id)
            .where(
                Driver.status == DriverStatus.available,
                Vehicle.is_active.is_(True),
                ~active_route,
            )
            .order_by(Driver.created_at, Driver.user_id)
        )
        vehicles = [
            PlanningVehicle(
                driver_id=row[0],
                driver_name=row[1],
                vehicle_id=row[2],
                vehicle_registration=row[3],
                max_weight_kg=Decimal(row[4]),
                max_volume_m3=Decimal(row[5]),
            )
            for row in available_vehicles.all()
        ]
    return warehouse_coordinates, orders, vehicles, False, []


async def _load_route_event(session, route_id: UUID) -> dict | None:
    route_row = (
        await session.execute(
            select(
                Route.id,
                Route.vehicle_id,
                Route.driver_id,
                User.full_name,
                Vehicle.registration_number,
                Route.created_at,
            )
            .join(Driver, Driver.user_id == Route.driver_id)
            .join(User, User.id == Driver.user_id)
            .join(Vehicle, Vehicle.id == Route.vehicle_id)
            .where(Route.id == route_id)
        )
    ).one_or_none()
    if route_row is None:
        return None
    stop_rows = await session.execute(
        select(
            RouteStop.id,
            RouteStop.order_id,
            RouteStop.sequence,
            RouteStop.status,
            RouteStop.planned_arrival_at,
            RouteStop.planned_distance_m,
            Order.tracking_token,
        )
        .join(Order, Order.id == RouteStop.order_id)
        .where(RouteStop.route_id == route_id)
        .order_by(RouteStop.sequence)
    )
    event = RoutePublishedEvent(
        event_id=str(route_row.id),
        route_id=str(route_row.id),
        vehicle_id=str(route_row.vehicle_id),
        driver_id=str(route_row.driver_id),
        driver_name=route_row.full_name,
        vehicle_registration=route_row.registration_number,
        stops=[
            {
                "route_stop_id": str(stop.id),
                "order_id": str(stop.order_id),
                "sequence": stop.sequence,
                "status": stop.status.value,
                "planned_arrival_at": stop.planned_arrival_at.isoformat(),
                "planned_distance_m": stop.planned_distance_m,
                "tracking_token": stop.tracking_token,
            }
            for stop in stop_rows.all()
        ],
        created_at=route_row.created_at.isoformat(),
    )
    return event.model_dump(mode="json")


async def plan_warehouse_routes(
    warehouse_id: UUID,
    trigger_order_id: UUID,
) -> tuple[bool, list[dict]]:
    """Solve pending orders at a warehouse and persist assigned routes atomically."""
    snapshot = await _load_planning_snapshot(warehouse_id, trigger_order_id)
    warehouse_coordinates, orders, vehicles, already_processed, existing_events = snapshot
    if already_processed:
        return True, existing_events
    if not orders or not vehicles:
        return False, []

    planning_started_at = datetime.now(timezone.utc)
    coordinates = [warehouse_coordinates] + [
        (order.longitude, order.latitude) for order in orders
    ]
    matrix = await OSRMClient().get_table_matrix(coordinates)
    problem, job_order_ids = build_vroom_problem(
        orders,
        vehicles,
        matrix["durations"],
        matrix["distances"],
        planning_started_at,
    )
    if not problem["jobs"]:
        return False, []
    solution = await VROOMClient().solve_cvrptw(problem)
    vehicle_by_solver_id = {
        index: vehicle for index, vehicle in enumerate(vehicles, start=1)
    }
    order_by_id = {order.order_id: order for order in orders}
    assigned_routes = []
    for route_solution in solution["routes"]:
        vehicle = vehicle_by_solver_id.get(route_solution.get("vehicle"))
        if vehicle is None:
            raise RuntimeError("VROOM returned a route for an unknown vehicle.")
        steps = []
        for step in route_solution["steps"]:
            if step.get("type") != "job":
                continue
            job_id = step.get("job", step.get("id"))
            order_id = job_order_ids.get(job_id)
            distance_m = step.get("distance")
            arrival = step.get("arrival")
            if order_id is None:
                raise RuntimeError("VROOM returned a job that was not in the submitted plan.")
            if not isinstance(distance_m, (int, float)) or not math.isfinite(distance_m) or distance_m < 0:
                raise RuntimeError("VROOM did not return a valid routed distance for a delivery leg.")
            if not isinstance(arrival, (int, float)) or not math.isfinite(arrival) or arrival < 0:
                raise RuntimeError("VROOM did not return a valid planned arrival for a delivery.")
            steps.append(
                {
                    "order_id": order_id,
                    "planned_distance_m": int(math.ceil(distance_m)),
                    "planned_arrival_at": planning_started_at + timedelta(seconds=int(arrival)),
                }
            )
        if steps:
            assigned_routes.append((route_solution, vehicle, steps))
    if not assigned_routes:
        return False, []

    route_events = []
    async with async_session_factory() as session:
        async with session.begin():
            warehouse = await session.scalar(
                select(Warehouse)
                .where(Warehouse.id == warehouse_id, Warehouse.is_active.is_(True))
                .with_for_update()
            )
            if warehouse is None:
                raise RoutePlanChanged("Warehouse is no longer active.")
            for route_solution, vehicle_plan, steps in assigned_routes:
                driver = await session.scalar(
                    select(Driver)
                    .where(
                        Driver.user_id == vehicle_plan.driver_id,
                        Driver.status == DriverStatus.available,
                        Driver.vehicle_id == vehicle_plan.vehicle_id,
                    )
                    .with_for_update()
                )
                if driver is None:
                    raise RoutePlanChanged("A selected driver is no longer available.")
                active_route_id = await session.scalar(
                    select(Route.id).where(
                        Route.driver_id == driver.user_id,
                        Route.status.in_(ACTIVE_ROUTE_STATUSES),
                    )
                )
                if active_route_id is not None:
                    raise RoutePlanChanged("A selected driver already has an active route.")
                vehicle = await session.get(Vehicle, vehicle_plan.vehicle_id)
                if vehicle is None or not vehicle.is_active:
                    raise RoutePlanChanged("A selected vehicle is no longer active.")

                route_order_ids = [step["order_id"] for step in steps]
                locked_orders = await session.scalars(
                    select(Order)
                    .where(
                        Order.id.in_(route_order_ids),
                        Order.warehouse_id == warehouse_id,
                        Order.status.in_(ORDERABLE_STATUSES),
                        ~exists(select(RouteStop.id).where(RouteStop.order_id == Order.id)),
                    )
                    .with_for_update()
                )
                route_orders = {order.id: order for order in locked_orders}
                if set(route_orders) != set(route_order_ids):
                    raise RoutePlanChanged("A planned delivery changed before its route was saved.")

                route_distance_m = route_solution.get("distance")
                if not isinstance(route_distance_m, (int, float)) or not math.isfinite(route_distance_m) or route_distance_m < 0:
                    raise RuntimeError("VROOM did not return a valid route distance.")
                duration_s = route_solution.get("duration")
                if not isinstance(duration_s, (int, float)) or not math.isfinite(duration_s) or duration_s < 0:
                    raise RuntimeError("VROOM did not return a valid route duration.")
                route = Route(
                    warehouse_id=warehouse_id,
                    driver_id=driver.user_id,
                    vehicle_id=vehicle.id,
                    status=RouteStatus.planned,
                    total_distance_m=int(math.ceil(route_distance_m)),
                    total_duration_s=int(math.ceil(duration_s)),
                    created_at=planning_started_at,
                    updated_at=planning_started_at,
                )
                session.add(route)
                await session.flush()
                route_stop_events = []
                for sequence, planned_step in enumerate(steps, start=1):
                    order = route_orders[planned_step["order_id"]]
                    stop = RouteStop(
                        id=uuid4(),
                        route_id=route.id,
                        order_id=order.id,
                        sequence=sequence,
                        status=StopStatus.pending,
                        planned_location=WKTElement(
                            f"POINT({order_by_id[order.id].longitude} {order_by_id[order.id].latitude})",
                            srid=4326,
                        ),
                        planned_distance_m=planned_step["planned_distance_m"],
                        planned_arrival_at=planned_step["planned_arrival_at"],
                        created_at=planning_started_at,
                        updated_at=planning_started_at,
                    )
                    session.add(stop)
                    route_stop_events.append(
                        {
                            "route_stop_id": str(stop.id),
                            "order_id": str(order.id),
                            "sequence": sequence,
                            "status": StopStatus.pending.value,
                            "planned_arrival_at": planned_step["planned_arrival_at"].isoformat(),
                            "planned_distance_m": planned_step["planned_distance_m"],
                            "tracking_token": order_by_id[order.id].tracking_token,
                        }
                    )
                    previous_status = order.status
                    order.status = OrderStatus.assigned
                    order.updated_at = planning_started_at
                    session.add(
                        OrderEvent(
                            order_id=order.id,
                            from_status=previous_status,
                            to_status=OrderStatus.assigned,
                            route_stop_id=stop.id,
                            actor_user_id=None,
                            occurred_at=planning_started_at,
                        )
                    )
                await session.flush()
                event = RoutePublishedEvent(
                    event_id=str(route.id),
                    route_id=str(route.id),
                    vehicle_id=str(vehicle.id),
                    driver_id=str(driver.user_id),
                    driver_name=vehicle_plan.driver_name,
                    vehicle_registration=vehicle.registration_number,
                    stops=route_stop_events,
                    created_at=route.created_at.isoformat(),
                )
                route_events.append(event.model_dump(mode="json"))

    assigned_order_ids = {
        UUID(stop["order_id"])
        for event in route_events
        for stop in event["stops"]
    }
    return trigger_order_id in assigned_order_ids, route_events
