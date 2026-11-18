import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from db_models.models import DriverEarningType
from services.core_api.app.driver.finance import create_trusted_adjustment
from services.core_api.app.driver.schemas import DriverEarningsAdjustmentRequest


class FakeSession:
    def __init__(self, scalar_values):
        self.scalar_values = iter(scalar_values)
        self.added = []

    async def execute(self, _statement):
        return None

    async def scalar(self, _statement):
        return next(self.scalar_values)

    def add(self, instance):
        self.added.append(instance)


def adjustment_payload(driver_id, idempotency_key, *, amount="2.50", entry_type="bonus"):
    return DriverEarningsAdjustmentRequest(
        driver_id=driver_id,
        entry_type=entry_type,
        amount=Decimal(amount),
        idempotency_key=idempotency_key,
        reason="holiday bonus",
    )


def test_trusted_adjustment_updates_wallet_and_ledger_together():
    driver_id = uuid4()
    idempotency_key = uuid4()
    previous_update = datetime.now(timezone.utc) - timedelta(minutes=1)
    wallet = SimpleNamespace(
        available_balance=Decimal("10.00"),
        updated_at=previous_update,
    )
    session = FakeSession([wallet, None])

    earning, balance, created = asyncio.run(
        create_trusted_adjustment(
            session,
            adjustment_payload(driver_id, idempotency_key),
            uuid4(),
        )
    )

    assert created is True
    assert balance == Decimal("12.50")
    assert wallet.available_balance == Decimal("12.50")
    assert wallet.updated_at > previous_update
    assert session.added == [earning]
    assert earning.entry_type is DriverEarningType.bonus
    assert earning.idempotency_key == idempotency_key
    assert earning.description == "Operations bonus: holiday bonus"


def test_trusted_adjustment_replay_does_not_credit_wallet_twice():
    driver_id = uuid4()
    idempotency_key = uuid4()
    wallet = SimpleNamespace(
        available_balance=Decimal("12.50"),
        updated_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    earning = SimpleNamespace(
        driver_id=driver_id,
        entry_type=DriverEarningType.bonus,
        amount=Decimal("2.50"),
        description="Operations bonus: holiday bonus",
    )
    session = FakeSession([wallet, earning])

    result, balance, created = asyncio.run(
        create_trusted_adjustment(
            session,
            adjustment_payload(driver_id, idempotency_key),
            uuid4(),
        )
    )

    assert result is earning
    assert balance == Decimal("12.50")
    assert created is False
    assert wallet.available_balance == Decimal("12.50")
    assert session.added == []


def test_trusted_adjustment_rejects_negative_wallet_balance():
    wallet = SimpleNamespace(
        available_balance=Decimal("1.00"),
        updated_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    session = FakeSession([wallet, None])

    with pytest.raises(HTTPException) as error_info:
        asyncio.run(
            create_trusted_adjustment(
                session,
                adjustment_payload(
                    uuid4(),
                    uuid4(),
                    amount="-2.00",
                    entry_type="adjustment",
                ),
                uuid4(),
            )
        )

    assert error_info.value.status_code == 422
    assert wallet.available_balance == Decimal("1.00")
    assert session.added == []
