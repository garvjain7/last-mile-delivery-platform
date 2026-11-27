from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from db_models.models import OrderStatus
from services.routing_worker.app.engines.route_planner import (
    PlanningOrder,
    PlanningVehicle,
    build_vroom_problem,
)


def test_vroom_problem_maps_order_leg_to_distance_matrix_and_capacity_units():
    planning_started_at = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
    order_id = uuid4()
    order = PlanningOrder(
        order_id=order_id,
        status=OrderStatus.placed,
        longitude=77.6,
        latitude=12.9,
        weight_kg=Decimal("2.345"),
        volume_m3=Decimal("0.0456"),
        window_earliest=planning_started_at + timedelta(minutes=5),
        window_latest=planning_started_at + timedelta(minutes=30),
        tracking_token="tracking-token",
    )
    vehicle = PlanningVehicle(
        driver_id=uuid4(),
        driver_name="Driver",
        vehicle_id=uuid4(),
        vehicle_registration="KA 01 AB 1234",
        max_weight_kg=Decimal("10.000"),
        max_volume_m3=Decimal("0.1000"),
    )
    durations = [[0, 100], [120, 0]]
    distances = [[0, 1500], [1800, 0]]

    problem, job_order_ids = build_vroom_problem(
        [order],
        [vehicle],
        durations,
        distances,
        planning_started_at,
    )

    assert problem["jobs"] == [
        {
            "id": 1,
            "location_index": 1,
            "delivery": [2345, 456],
            "time_windows": [[300, 1800]],
        }
    ]
    assert problem["vehicles"][0]["capacity"] == [10000, 1000]
    assert problem["vehicles"][0]["start_index"] == 0
    assert problem["vehicles"][0]["end_index"] == 0
    assert problem["matrices"]["car"]["durations"] == durations
    assert problem["matrices"]["car"]["distances"] == distances
    assert job_order_ids == {1: order_id}
