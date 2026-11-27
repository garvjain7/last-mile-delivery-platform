"""Ledger credits for completed driver deliveries."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db_models.models import DriverEarning, DriverEarningType, DriverWallet

BASE_PAY_INR = Decimal("4.50")
DISTANCE_BONUS_PER_KM_INR = Decimal("0.50")
DISTANCE_BONUS_THRESHOLD_M = 3000
WEIGHT_BONUS_PER_KG_INR = Decimal("0.20")
MONEY_QUANTUM = Decimal("0.01")


def calculate_delivery_earnings(
    weight_kg: Decimal,
    planned_distance_m: int,
) -> list[tuple[DriverEarningType, Decimal, str]]:
    """Return itemized INR credits using the configured prototype delivery formula."""
    weight_bonus = (Decimal(weight_kg) * WEIGHT_BONUS_PER_KG_INR).quantize(
        MONEY_QUANTUM,
        rounding=ROUND_HALF_UP,
    )
    extra_distance_m = max(0, planned_distance_m - DISTANCE_BONUS_THRESHOLD_M)
    distance_bonus = (
        Decimal(extra_distance_m)
        / Decimal(1000)
        * DISTANCE_BONUS_PER_KM_INR
    ).quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    entries = [
        (
            DriverEarningType.base_pay,
            BASE_PAY_INR,
            f"Base pay: ₹{BASE_PAY_INR:.2f} per completed delivery",
        ),
        (
            DriverEarningType.weight_bonus,
            weight_bonus,
            f"Weight bonus: {weight_kg:.3f} kg × ₹{WEIGHT_BONUS_PER_KG_INR:.2f}/kg "
            f"= ₹{weight_bonus:.2f}",
        ),
    ]
    if distance_bonus:
        distance_km = Decimal(planned_distance_m) / Decimal(1000)
        entries.append(
            (
                DriverEarningType.distance_bonus,
                distance_bonus,
                f"Distance bonus: max(0, {distance_km:.3f} km − "
                f"{DISTANCE_BONUS_THRESHOLD_M / 1000:g} km) × "
                f"₹{DISTANCE_BONUS_PER_KM_INR:.2f}/km = ₹{distance_bonus:.2f}",
            )
        )
    return [(entry_type, amount, description) for entry_type, amount, description in entries if amount]


async def post_delivery_earnings(
    session: AsyncSession,
    *,
    driver_id: UUID,
    route_id: UUID,
    route_stop_id: UUID,
    order_id: UUID,
    source_event_id: UUID,
    weight_kg: Decimal,
    planned_distance_m: int,
    actor_user_id: UUID,
) -> None:
    entries = calculate_delivery_earnings(weight_kg, planned_distance_m)
    await session.execute(
        insert(DriverWallet)
        .values(driver_id=driver_id)
        .on_conflict_do_nothing(index_elements=[DriverWallet.driver_id])
    )
    wallet = await session.scalar(
        select(DriverWallet)
        .where(DriverWallet.driver_id == driver_id)
        .with_for_update()
    )
    if wallet is None:
        raise RuntimeError(f"Could not initialize wallet for driver {driver_id}.")
    total_credit = sum((amount for _, amount, _ in entries), Decimal("0.00"))
    wallet.available_balance += total_credit
    wallet.updated_at = datetime.now(timezone.utc)
    for entry_type, amount, description in entries:
        session.add(
            DriverEarning(
                driver_id=driver_id,
                route_id=route_id,
                route_stop_id=route_stop_id,
                order_id=order_id,
                entry_type=entry_type,
                amount=amount,
                currency="INR",
                source_event_id=source_event_id,
                actor_user_id=actor_user_id,
                description=description,
            )
        )
