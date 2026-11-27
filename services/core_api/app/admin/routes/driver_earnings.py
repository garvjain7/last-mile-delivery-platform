"""Trusted administrative adjustments to a driver's earnings ledger."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db_models.models import Driver
from services.core_api.app.database.connection import get_db_session
from services.core_api.app.driver.finance import create_trusted_adjustment
from services.core_api.app.driver.schemas import DriverEarningsAdjustmentRequest

router = APIRouter()


@router.post("/earnings/adjustments", status_code=status.HTTP_201_CREATED)
async def post_earnings_adjustment(
    payload: DriverEarningsAdjustmentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db_session),
):
    driver = await db.get(Driver, payload.driver_id)
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver account not found.")
    earning, available_balance, created = await create_trusted_adjustment(
        db,
        payload,
        request.state.admin_user.id,
    )
    await db.commit()
    return {
        "transaction_id": earning.id,
        "driver_id": earning.driver_id,
        "entry_type": earning.entry_type.value,
        "amount": earning.amount,
        "currency": earning.currency,
        "available_balance": available_balance,
        "idempotent_replay": not created,
    }
