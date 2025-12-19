# src/db/repositories/users.py
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy import BigInteger
from sqlalchemy import delete  # noqa: F401 (оставлено для совместимости)
from sqlalchemy.orm import load_only

from src.db.session import async_session
from src.db.models import User


async def get_or_create_user(
    telegram_id: int,
    username: Optional[str] = None,
    referrer_telegram_id: Optional[int] = None,
) -> User:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        if user:
            changed = False
            if username is not None and user.username != username:
                user.username = username
                changed = True
            if changed:
                await session.commit()
            return user

        user = User(
            telegram_id=telegram_id,
            username=username,
            referrer_id=referrer_telegram_id,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def set_user_admin_flag(telegram_id: int, is_admin: bool) -> Optional[User]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        user.is_admin = is_admin
        await session.commit()
        await session.refresh(user)
        return user


async def set_user_referral_flag(telegram_id: int, is_referral: bool) -> Optional[User]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        user.is_referral = is_referral
        await session.commit()
        await session.refresh(user)
        return user


async def get_referral_users() -> list[User]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_referral == True))  # noqa: E712
        return list(result.scalars().all())


async def get_referrals_for_user(referrer_telegram_id: int) -> list[User]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.referrer_id == referrer_telegram_id))
        return list(result.scalars().all())


async def get_referrals_count(referrer_telegram_id: int) -> int:
    async with async_session() as session:
        count_value = await session.scalar(
            select(func.count()).select_from(User).where(User.referrer_id == referrer_telegram_id)
        )
        return int(count_value or 0)


async def add_referral_earnings(telegram_id: int, amount_rub: int) -> Optional[User]:
    if amount_rub <= 0:
        return None

    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None

        user.referral_earned_rub = (user.referral_earned_rub or 0) + amount_rub
        await session.commit()
        await session.refresh(user)
        return user


async def get_referral_summary(telegram_id: int) -> Tuple[int, int]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        total_earned = int(user.referral_earned_rub or 0) if user else 0

        referrals_count = await session.scalar(
            select(func.count()).select_from(User).where(User.referrer_id == telegram_id)
        )
        return total_earned, int(referrals_count or 0)


async def is_user_admin_db(telegram_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(User.is_admin).where(User.telegram_id == telegram_id))
        value = result.scalar_one_or_none()
        return bool(value)


async def get_admin_users() -> List[User]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_admin == True))  # noqa: E712
        return list(result.scalars().all())


async def get_user_by_telegram_id(telegram_id: int) -> User:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(telegram_id=telegram_id, balance=0, photoshoot_credits=0)
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user


async def get_user_balance(telegram_id: int) -> int:
    user = await get_user_by_telegram_id(telegram_id)
    return user.balance


async def consume_photoshoot_credit_or_balance(telegram_id: int, price_rub: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(telegram_id=telegram_id, balance=0, photoshoot_credits=0)
            session.add(user)
            await session.flush()

        if user.photoshoot_credits > 0:
            user.photoshoot_credits -= 1
            await session.commit()
            return True

        if user.balance >= price_rub:
            user.balance -= price_rub
            await session.commit()
            return True

        await session.rollback()
        return False


async def get_users_page(page: int = 0, page_size: int = 10) -> tuple[list[User], int]:
    offset = page * page_size
    async with async_session() as session:
        total = await session.scalar(select(func.count()).select_from(User))
        result = await session.execute(
            select(User).order_by(User.created_at.desc()).offset(offset).limit(page_size)
        )
        users = list(result.scalars().all())
    return users, int(total or 0)


async def search_users(query: str, limit: int = 20) -> list[User]:
    q = query.strip()
    async with async_session() as session:
        if q.isdigit():
            telegram_id = int(q)
            result = await session.execute(select(User).where(User.telegram_id == telegram_id))
            return list(result.scalars().all())

        if q.startswith("@"):
            q = q[1:]

        result = await session.execute(select(User).where(func.lower(User.username) == q.lower()).limit(limit))
        return list(result.scalars().all())


async def change_user_credits(telegram_id: int, delta: int) -> Optional[User]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None

        new_value = user.photoshoot_credits + delta
        if new_value < 0:
            new_value = 0

        user.photoshoot_credits = new_value
        await session.commit()
        await session.refresh(user)
        return user


async def change_user_balance(telegram_id: int, delta: int) -> Optional[User]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None

        new_balance = user.balance + delta
        if new_balance < 0:
            new_balance = 0

        user.balance = new_balance
        await session.commit()
        await session.refresh(user)
        return user