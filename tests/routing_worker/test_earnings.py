from decimal import Decimal

from db_models.models import DriverEarningType
from services.routing_worker.app.earnings import calculate_delivery_earnings


def test_delivery_earnings_apply_distance_threshold_and_round_to_paise():
    at_threshold = calculate_delivery_earnings(Decimal("1.23"), 3000)
    just_over_threshold = calculate_delivery_earnings(Decimal("1.23"), 3010)

    assert at_threshold == [
        (
            DriverEarningType.base_pay,
            Decimal("4.50"),
            "Base pay: ₹4.50 per completed delivery",
        ),
        (
            DriverEarningType.weight_bonus,
            Decimal("0.25"),
            "Weight bonus: 1.230 kg × ₹0.20/kg = ₹0.25",
        ),
    ]
    assert just_over_threshold == [
        *at_threshold,
        (
            DriverEarningType.distance_bonus,
            Decimal("0.01"),
            "Distance bonus: max(0, 3.010 km − 3 km) × ₹0.50/km = ₹0.01",
        ),
    ]
