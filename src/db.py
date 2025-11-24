# src/db.py

from __future__ import annotations

import enum
from datetime import datetime, timedelta
from uuid import uuid4
from typing import Optional, Tuple
from typing import List
from sqlalchemy import select, func
from aiogram.types import User as TgUser
from sqlalchemy import (
    BigInteger,
    String,
    Integer,
    DateTime,
    Enum,
    func,
    select,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, Mapped, mapped_column

from data.star_offers import StarOffer


DATABASE_URL = "sqlite+aiosqlite:///./bot.db"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
)

async_session = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)

Base = declarative_base()


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    success = "success"
    failed = "failed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Рубли — если всё-таки оставишь рублёвый баланс
    balance: Mapped[int] = mapped_column(Integer, default=0)

    # Кредиты фотосессий, которые покупаются через Stars
    photoshoot_credits: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class StarPayment(Base):
    """
    Платёж через Telegram Stars за фотосессии.
    """

    __tablename__ = "star_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)

    offer_code: Mapped[str] = mapped_column(String(64))
    amount_stars: Mapped[int] = mapped_column(Integer)
    credits: Mapped[int] = mapped_column(Integer)

    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus),
        default=PaymentStatus.pending,
    )

    # payload, который мы передаём в инвойс
    payload: Mapped[str] = mapped_column(String(128), unique=True)

    # id транзакции Telegram, пригодится для рефандов
    telegram_charge_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


# ---------- Инициализация БД ----------

async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ---------- Работа с пользователями ----------

async def get_or_create_user(tg_user: TgUser) -> User:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == tg_user.id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
                balance=0,
                photoshoot_credits=0,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user


async def get_user_by_telegram_id(telegram_id: int) -> User:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                balance=0,
                photoshoot_credits=0,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user


async def get_user_balance(telegram_id: int) -> int:
    user = await get_user_by_telegram_id(telegram_id)
    return user.balance


# ---------- Потребление фотосессий (кредиты/рубли) ----------

async def consume_photoshoot_credit_or_balance(
    telegram_id: int,
    price_rub: int,
) -> bool:
    """
    Сначала пробуем списать 1 кредит фотосессии.
    Если нет кредитов — пробуем списать price_rub с рублёвого баланса.
    Если не получилось — возвращаем False.
    """
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=telegram_id,
                balance=0,
                photoshoot_credits=0,
            )
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


# ---------- Платежи через Stars ----------

async def create_star_payment(
    telegram_id: int,
    offer: StarOffer,
) -> StarPayment:
    """
    Создаём запись платежа и генерируем payload.
    """
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
    """
    Помечаем платёж как успешный, начисляем кредиты пользователю.
    Если что-то не сходится — возвращаем None.
    """
    if currency != "XTR":
        return None

    async with async_session() as session:
        result = await session.execute(
            select(StarPayment).where(StarPayment.payload == payload)
        )
        payment: StarPayment | None = result.scalar_one_or_none()

        if payment is None:
            return None

        if payment.status == PaymentStatus.success:
            # Уже обработан, повторно не трогаем
            result_user = await session.execute(
                select(User).where(User.telegram_id == payment.telegram_id)
            )
            user = result_user.scalar_one_or_none()
            return (user, payment) if user else None

        # Проверяем сумму
        if total_amount != payment.amount_stars:
            payment.status = PaymentStatus.failed
            await session.commit()
            return None

        payment.status = PaymentStatus.success
        payment.telegram_charge_id = telegram_charge_id

        result_user = await session.execute(
            select(User).where(User.telegram_id == payment.telegram_id)
        )
        user = result_user.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=payment.telegram_id,
                balance=0,
                photoshoot_credits=0,
            )
            session.add(user)
            await session.flush()

        user.photoshoot_credits += payment.credits

        await session.commit()
        await session.refresh(user)
        await session.refresh(payment)

        return user, payment

async def get_users_page(page: int = 0, page_size: int = 10) -> tuple[list[User], int]:
    """
    Возвращает список пользователей для страницы админки и общее количество пользователей.
    page       — номер страницы (0, 1, 2, ...)
    page_size  — сколько пользователей на странице
    """
    offset = page * page_size

    async with async_session() as session:
        # Сначала считаем общее количество
        total = await session.scalar(
            select(func.count()).select_from(User)
        )

        result = await session.execute(
            select(User)
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        users = list(result.scalars().all())

    return users, int(total or 0)


async def search_users(query: str, limit: int = 20) -> list[User]:
    """
    Поиск пользователей по username (@name) или telegram_id (число).
    """
    q = query.strip()

    async with async_session() as session:
        # Поиск по ID
        if q.isdigit():
            telegram_id = int(q)
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return list(result.scalars().all())

        # Поиск по username
        if q.startswith("@"):
            q = q[1:]

        # username может быть None, поэтому фильтруем аккуратно
        result = await session.execute(
            select(User).where(func.lower(User.username) == q.lower())
        )
        return list(result.scalars().all())


async def change_user_credits(telegram_id: int, delta: int) -> User | None:
    """
    Увеличивает или уменьшает количество фотосессий (photoshoot_credits)
    у пользователя на delta. Не даёт уйти в минус.
    Возвращает обновлённого пользователя или None, если не нашли.
    """
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
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

class PhotoshootStatus(str, enum.Enum):
    success = "success"
    failed = "failed"


class PhotoshootLog(Base):
    __tablename__ = "photoshoot_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    style_title: Mapped[str] = mapped_column(String(128))
    status: Mapped[PhotoshootStatus] = mapped_column(Enum(PhotoshootStatus))

    # Сколько списали — в рублях и в кредитах (если не списываем, можно писать 0)
    cost_rub: Mapped[int] = mapped_column(Integer, default=0)
    cost_credits: Mapped[int] = mapped_column(Integer, default=0)

    provider: Mapped[str] = mapped_column(String(64), default="comet")
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

async def log_photoshoot(
    telegram_id: int,
    style_title: str,
    status: PhotoshootStatus,
    cost_rub: int = 0,
    cost_credits: int = 0,
    provider: str = "comet_gemini_2_5_flash",
    error_message: str | None = None,
) -> PhotoshootLog:
    async with async_session() as session:
        log = PhotoshootLog(
            telegram_id=telegram_id,
            style_title=style_title,
            status=status,
            cost_rub=cost_rub,
            cost_credits=cost_credits,
            provider=provider,
            error_message=error_message,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log


async def get_photoshoot_report(days: int = 7) -> dict:
    """
    Простой отчёт по фотосессиям за последние N дней.
    """
    since = datetime.utcnow() - timedelta(days=days)

    async with async_session() as session:
        total = await session.scalar(
            select(func.count()).select_from(PhotoshootLog).where(
                PhotoshootLog.created_at >= since
            )
        ) or 0

        success = await session.scalar(
            select(func.count()).select_from(PhotoshootLog).where(
                PhotoshootLog.created_at >= since,
                PhotoshootLog.status == PhotoshootStatus.success,
            )
        ) or 0

        failed = await session.scalar(
            select(func.count()).select_from(PhotoshootLog).where(
                PhotoshootLog.created_at >= since,
                PhotoshootLog.status == PhotoshootStatus.failed,
            )
        ) or 0

        sum_cost_rub = await session.scalar(
            select(func.coalesce(func.sum(PhotoshootLog.cost_rub), 0)).where(
                PhotoshootLog.created_at >= since
            )
        ) or 0

        sum_cost_credits = await session.scalar(
            select(func.coalesce(func.sum(PhotoshootLog.cost_credits), 0)).where(
                PhotoshootLog.created_at >= since
            )
        ) or 0

    return {
        "days": days,
        "total": int(total),
        "success": int(success),
        "failed": int(failed),
        "sum_cost_rub": int(sum_cost_rub),
        "sum_cost_credits": int(sum_cost_credits),
    }

async def get_payments_report(days: int = 7) -> dict:
    """
    Отчёт по пополнениям (StarPayment) за последние N дней.
    """
    since = datetime.utcnow() - timedelta(days=days)

    async with async_session() as session:
        total = await session.scalar(
            select(func.count()).select_from(StarPayment).where(
                StarPayment.created_at >= since,
                StarPayment.status == PaymentStatus.success,
            )
        ) or 0

        sum_stars = await session.scalar(
            select(func.coalesce(func.sum(StarPayment.amount_stars), 0)).where(
                StarPayment.created_at >= since,
                StarPayment.status == PaymentStatus.success,
            )
        ) or 0

        sum_credits = await session.scalar(
            select(func.coalesce(func.sum(StarPayment.credits), 0)).where(
                StarPayment.created_at >= since,
                StarPayment.status == PaymentStatus.success,
            )
        ) or 0

    return {
        "days": days,
        "total": int(total),
        "sum_stars": int(sum_stars),
        "sum_credits": int(sum_credits),
    }

async def change_user_balance(telegram_id: int, delta: int) -> User | None:
    """
    Увеличивает или уменьшает баланс пользователя на delta рублей.
    Не даёт уйти в минус.
    """
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
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
