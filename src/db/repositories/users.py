# src/db/repositories/users.py
from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy import BigInteger
from sqlalchemy import delete  # noqa: F401 (оставлено для совместимости)
from sqlalchemy.orm import load_only

from src.db.session import async_session
from src.db.models import User
from src.constants import PHOTOSHOOT_PRICE


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

            # ✅ ВАЖНО: если реферер пришёл позже — привязываем, но только 1 раз
            if (
                referrer_telegram_id is not None
                and referrer_telegram_id != telegram_id
                and user.referrer_id is None
            ):
                user.referrer_id = referrer_telegram_id
                changed = True

            if changed:
                await session.commit()
                await session.refresh(user)

            return user

        user = User(
            telegram_id=telegram_id,
            username=username,
            referrer_id=referrer_telegram_id if (referrer_telegram_id != telegram_id) else None,
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


async def search_users(query: str, limit: int = 50) -> list[User]:
    """
    Поиск пользователей по:
    - telegram_id (если ввели число) — точное совпадение
    - username (частичное совпадение, case-insensitive), можно вводить с @
    - если строка содержит цифры (но не чисто число) — попробуем также искать по telegram_id как подстроке
    """
    q_raw = (query or "").strip()
    if not q_raw:
        return []

    q = q_raw
    if q.startswith("@"):
        q = q[1:].strip()

    async with async_session() as session:
        # 1) Чисто число => ищем по telegram_id
        if q.isdigit():
            telegram_id = int(q)
            res = await session.execute(
                select(User)
                .where(User.telegram_id == telegram_id)
                .limit(limit)
            )
            return list(res.scalars().all())

        q_lower = q.lower()

        conditions = []

        # 2) username частично (case-insensitive)
        # func.lower(User.username) вернет NULL для NULL-ов — это ок
        conditions.append(func.lower(User.username).like(f"%{q_lower}%"))

        # 3) если есть цифры — добавим поиск по telegram_id как строке (опционально, но удобно)
        if any(ch.isdigit() for ch in q):
            conditions.append(cast(User.telegram_id, String).like(f"%{q}%"))

        stmt = (
            select(User)
            .where(or_(*conditions))
            .order_by(User.created_at.desc())
            .limit(limit)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())

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


async def add_photoshoot_topups(telegram_id: int, generations: int) -> Optional[User]:
    """
    Добавляет на баланс пользователя сумму, равную `generations * PHOTOSHOOT_PRICE`.
    Возвращает обновлённого `User` или `None` если `generations` <= 0.
    """
    if generations <= 0:
        return None

    total_amount = int(PHOTOSHOOT_PRICE) * int(generations)
    # Убедимся, что пользователь существует (создастся, если отсутствует)
    await get_user_by_telegram_id(telegram_id)
    return await change_user_balance(telegram_id, total_amount)


async def clear_user_balance(telegram_id: int) -> Optional[User]:
    """
    Обнуляет баланс пользователя (устанавливает в 0).
    Если пользователя нет — создаёт профиль с нулевым балансом.
    Возвращает обновлённый объект `User`.
    """
    async with async_session() as session:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()

        if user is None:
            user = User(telegram_id=telegram_id, balance=0, photoshoot_credits=0)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user


        

        user.balance = 0
        await session.commit()
        await session.refresh(user)
        return user
    
async def get_all_users() -> list[User]:
            """Возвращает список всех пользователей из таблицы users."""
            async with async_session() as session:
                result = await session.execute(select(User))
                return list(result.scalars().all())
            
from sqlalchemy import select
from src.db.models import User
from src.db.session import async_session

async def iter_all_user_ids(batch_size: int = 1000):
    """
    Асинхронный генератор telegram_id всех пользователей батчами.
    """
    offset = 0
    while True:
        async with async_session() as session:
            res = await session.execute(
                select(User.telegram_id).order_by(User.id.asc()).offset(offset).limit(batch_size)
            )
            ids = [int(x) for x in res.scalars().all()]
        if not ids:
            break
        for uid in ids:
            yield uid
        offset += batch_size