"""Driver earnings and encrypted payout-method self-service endpoints."""

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from db_models.models import (
    Driver,
    DriverEarning,
    DriverEarningType,
    DriverPaymentMethod,
    DriverPaymentMethodType,
    DriverWallet,
)
from services.core_api.app.config import config
from services.core_api.app.database.connection import get_db_session
from services.core_api.app.driver.dependencies import require_driver
from services.core_api.app.driver.schemas import (
    DriverEarningsAdjustmentRequest,
    DriverEarningsResponse,
    PaymentMethodCreate,
    PaymentMethodResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()
ZERO_MONEY = Decimal("0.00")


def payment_cipher() -> Fernet:
    key = config.payment_method_encryption_key.get_secret_value()
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment method encryption is not configured.",
        )
    try:
        return Fernet(key.encode("ascii"))
    except (UnicodeEncodeError, TypeError, ValueError) as exc:
        logger.error("Payment method encryption key is invalid.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payment method encryption is not configured correctly.",
        ) from exc


def payment_method_details(payload: PaymentMethodCreate) -> dict[str, str]:
    if payload.method_type == "upi":
        return {"upi_id": payload.upi_id.get_secret_value()}
    return {
        "account_holder_name": payload.account_holder_name.get_secret_value(),
        "account_number": payload.account_number.get_secret_value(),
        "ifsc_code": payload.ifsc_code.get_secret_value(),
    }


def mask_payment_method(method_type: DriverPaymentMethodType | str, details: dict[str, str]) -> str:
    value = method_type.value if isinstance(method_type, DriverPaymentMethodType) else method_type
    if value == "upi":
        local_part = details["upi_id"].split("@", 1)[0]
        return f"{local_part[0]}***@***" if local_part else "***@***"
    return f"Account ending {details['account_number'][-4:]}"


def payment_method_response(method: DriverPaymentMethod) -> dict:
    return {
        "method_id": method.id,
        "method_type": method.method_type.value,
        "masked_details": method.masked_details,
        "is_preferred": method.is_preferred,
        "created_at": method.created_at,
    }


async def ensure_wallet_locked(db: AsyncSession, driver_id: UUID) -> DriverWallet:
    await db.execute(
        insert(DriverWallet)
        .values(driver_id=driver_id)
        .on_conflict_do_nothing(index_elements=[DriverWallet.driver_id])
    )
    wallet = await db.scalar(
        select(DriverWallet)
        .where(DriverWallet.driver_id == driver_id)
        .with_for_update()
    )
    if wallet is None:
        raise RuntimeError(f"Could not initialize wallet for driver {driver_id}.")
    return wallet


async def create_trusted_adjustment(
    db: AsyncSession,
    payload: DriverEarningsAdjustmentRequest,
    actor_user_id: UUID,
) -> tuple[DriverEarning, Decimal, bool]:
    wallet = await ensure_wallet_locked(db, payload.driver_id)
    existing = await db.scalar(
        select(DriverEarning).where(
            DriverEarning.idempotency_key == payload.idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.driver_id != payload.driver_id
            or existing.entry_type.value != payload.entry_type
            or existing.amount != payload.amount
            or existing.description != f"Operations {payload.entry_type}: {payload.reason}"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Idempotency key was already used for a different adjustment.",
            )
        return existing, wallet.available_balance, False

    updated_balance = wallet.available_balance + payload.amount
    if updated_balance < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Adjustment would make the driver's available balance negative.",
        )
    wallet.updated_at = datetime.now(timezone.utc)
    earning = DriverEarning(
        driver_id=payload.driver_id,
        entry_type=DriverEarningType(payload.entry_type),
        amount=payload.amount,
        currency="INR",
        idempotency_key=payload.idempotency_key,
        actor_user_id=actor_user_id,
        description=f"Operations {payload.entry_type}: {payload.reason}",
    )
    wallet.available_balance = updated_balance
    db.add(earning)
    return earning, updated_balance, True


@router.get("/earnings", response_model=DriverEarningsResponse)
async def get_driver_earnings(
    limit: int = Query(default=20, ge=1, le=50),
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    wallet = await db.get(DriverWallet, user.id)
    grouped = await db.execute(
        select(DriverEarning.entry_type, func.sum(DriverEarning.amount))
        .where(DriverEarning.driver_id == user.id)
        .group_by(DriverEarning.entry_type)
    )
    totals = {entry_type.value: amount for entry_type, amount in grouped.all()}
    base_pay = totals.get("base_pay", ZERO_MONEY)
    tips = totals.get("tip", ZERO_MONEY)
    bonuses = sum(
        (totals.get(name, ZERO_MONEY) for name in ("distance_bonus", "weight_bonus", "bonus")),
        ZERO_MONEY,
    )
    adjustments = totals.get("adjustment", ZERO_MONEY)
    total_earned = base_pay + tips + bonuses + adjustments
    earnings = await db.scalars(
        select(DriverEarning)
        .where(DriverEarning.driver_id == user.id)
        .order_by(DriverEarning.created_at.desc(), DriverEarning.id.desc())
        .limit(limit)
    )
    return {
        "currency": "INR",
        "available_balance": wallet.available_balance if wallet else ZERO_MONEY,
        "base_pay": base_pay,
        "tips": tips,
        "bonuses": bonuses,
        "adjustments": adjustments,
        "total_earned": total_earned,
        "recent_transactions": [
            {
                "transaction_id": earning.id,
                "entry_type": earning.entry_type.value,
                "amount": earning.amount,
                "currency": earning.currency,
                "description": earning.description,
                "order_id": earning.order_id,
                "created_at": earning.created_at,
            }
            for earning in earnings
        ],
    }


@router.get("/payment-methods", response_model=list[PaymentMethodResponse])
async def list_driver_payment_methods(
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    methods = await db.scalars(
        select(DriverPaymentMethod)
        .where(DriverPaymentMethod.driver_id == user.id)
        .order_by(DriverPaymentMethod.is_preferred.desc(), DriverPaymentMethod.created_at.desc())
    )
    return [payment_method_response(method) for method in methods]


@router.post(
    "/payment-methods",
    response_model=PaymentMethodResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_driver_payment_method(
    payload: PaymentMethodCreate,
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    cipher = payment_cipher()
    details = payment_method_details(payload)
    encrypted_details = cipher.encrypt(
        json.dumps(details, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).decode("ascii")
    driver = await db.scalar(
        select(Driver).where(Driver.user_id == user.id).with_for_update()
    )
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver account not found.")
    methods = list(
        (
            await db.scalars(
                select(DriverPaymentMethod)
                .where(DriverPaymentMethod.driver_id == user.id)
                .with_for_update()
            )
        ).all()
    )
    preferred = payload.is_preferred or not any(method.is_preferred for method in methods)
    if preferred:
        now = datetime.now(timezone.utc)
        for method in methods:
            if method.is_preferred:
                method.is_preferred = False
                method.updated_at = now
    method = DriverPaymentMethod(
        driver_id=user.id,
        method_type=DriverPaymentMethodType(payload.method_type),
        encrypted_details=encrypted_details,
        masked_details=mask_payment_method(payload.method_type, details),
        is_preferred=preferred,
    )
    db.add(method)
    await db.commit()
    await db.refresh(method)
    return payment_method_response(method)


@router.put(
    "/payment-methods/{method_id}/preferred",
    response_model=PaymentMethodResponse,
)
async def select_preferred_payment_method(
    method_id: UUID,
    user=Depends(require_driver),
    db: AsyncSession = Depends(get_db_session),
):
    driver = await db.scalar(
        select(Driver).where(Driver.user_id == user.id).with_for_update()
    )
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver account not found.")
    method = await db.scalar(
        select(DriverPaymentMethod)
        .where(
            DriverPaymentMethod.id == method_id,
            DriverPaymentMethod.driver_id == user.id,
        )
        .with_for_update()
    )
    if method is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment method not found.")
    methods = await db.scalars(
        select(DriverPaymentMethod)
        .where(DriverPaymentMethod.driver_id == user.id)
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    for existing_method in methods:
        is_preferred = existing_method.id == method_id
        if existing_method.is_preferred != is_preferred:
            existing_method.is_preferred = is_preferred
            existing_method.updated_at = now
    await db.commit()
    await db.refresh(method)
    return payment_method_response(method)
