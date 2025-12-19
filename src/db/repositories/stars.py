# src/db/repositories/stars.py
from __future__ import annotations

from typing import Optional, Tuple
from uuid import uuid4

from sqlalchemy import select

from src.data.star_offers import StarOffer
from src.db.session import async_session
from src.db.models import StarPayment, User
from src.db.enums import PaymentStatus


async def create_star_payment(telegram_id: int, offer: StarOffer) -> StarPayment:
    payload = f"stars:{offer.code}:{uuid4().hex}"

    async with async_session() as session:
        payment = StarPayment(
            telegram_id=telegram_id,
            offer_code=offer.code,
            amount_stars=offer.amount_stars,
            credits=offer.credits,
            status=PaymentStatus.pending,
            payload=payload,
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        return payment


async def mark_star_payment_success(
    payload: str,
    telegram_charge_id: str,
    total_amount: int,
    currency: str,
) -> Optional[Tuple[User, StarPayment]]:
    if currency != "XTR":
        return None

    async with async_session() as session:
        result = await session.execute(select(StarPayment).where(StarPayment.payload == payload))
        payment: StarPayment | None = result.scalar_one_or_none()
        if payment is None:
            return None

        if payment.status == PaymentStatus.success:
            result_user = await session.execute(select(User).where(User.telegram_id == payment.telegram_id))
            user = result_user.scalar_one_or_none()
            return (user, payment) if user else None

        if total_amount != payment.amount_stars:
            payment.status = PaymentStatus.failed
            await session.commit()
            return None

        payment.status = PaymentStatus.success
        payment.telegram_charge_id = telegram_charge_id

        result_user = await session.execute(select(User).where(User.telegram_id == payment.telegram_id))
        user = result_user.scalar_one_or_none()

        if user is None:
            user = User(telegram_id=payment.telegram_id, balance=0, photoshoot_credits=0)
            session.add(user)
            await session.flush()

        user.photoshoot_credits += payment.credits

        await session.commit()
        await session.refresh(user)
        await session.refresh(payment)

        return user, payment