# src/db.py

from __future__ import annotations

from datetime import datetime

from aiogram.types import User as TgUser
from sqlalchemy import BigInteger, String, Integer, DateTime, func, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base, Mapped, mapped_column


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


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


async def init_db() -> None:
    """
    Вызываем один раз при старте бота.
    Создаёт таблицы, если их ещё нет.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(tg_user: TgUser) -> User:
    """
    Возвращает пользователя из БД.
    Если его нет — создаёт с балансом 0.
    """
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
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user


async def get_user_balance(telegram_id: int) -> int:
    """
    Возвращает баланс пользователя.
    Если пользователя ещё нет — создаёт с балансом 0.
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
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user.balance


async def charge_photoshoot(telegram_id: int, price: int) -> bool:
    """
    Списывает стоимость фотосессии с баланса.
    Если денег не хватает — ничего не списывает, возвращает False.
    Если хватает — списывает, возвращает True.
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
            )
            session.add(user)
            await session.flush()

        if user.balance < price:
            await session.rollback()
            return False

        user.balance -= price
        await session.commit()
        return True


async def add_balance(telegram_id: int, amount: int) -> int:
    """
    Увеличивает баланс пользователя на amount рублей.
    Возвращает новый баланс.
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
            )
            session.add(user)
            await session.flush()

        user.balance += amount
        await session.commit()
        await session.refresh(user)
        return user.balance
