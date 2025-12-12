# src/db.py
from __future__ import annotations

import enum
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from uuid import uuid4
import datetime as dt
from fastapi import HTTPException
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Integer,
    String,
    func,
    select,
    case,
)
from sqlalchemy.exc import OperationalError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Mapped, declarative_base, mapped_column
    # noqa
from sqlalchemy.sql.expression import text

from src.config import settings
from src.data.star_offers import StarOffer

# -------------------------------------------------------------------
# Базовая настройка
# -------------------------------------------------------------------

SUPER_ADMIN_ID = 707366569
DATABASE_URL = settings.DATABASE_URL

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

# -------------------------------------------------------------------
# Enum'ы
# -------------------------------------------------------------------


class PaymentStatus(str, enum.Enum):
    pending = "pending"
    success = "success"
    failed = "failed"


class StyleGender(str, enum.Enum):
    male = "male"
    female = "female"


class PhotoshootStatus(str, enum.Enum):
    success = "success"
    failed = "failed"


# -------------------------------------------------------------------
# Модели
# -------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    photoshoot_credits: Mapped[int] = mapped_column(Integer, default=0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    # Новый тип пользователя: «Реферал» (партнёр, который массово рефералит под вывод)
    is_referral: Mapped[bool] = mapped_column(Boolean, default=False)

    # Сколько всего денег принесла реферальная программа этому пользователю
    # (накопительный итог, не обязательно равен текущему балансу)
    referral_earned_rub: Mapped[int] = mapped_column(Integer, default=0)

    # телеграм-id пригласившего пользователя (рефералка)
    referrer_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
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
    telegram_charge_id: Mapped[Optional[str]] = mapped_column(
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


class StyleCategory(Base):
    __tablename__ = "style_categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Больше НЕ unique
    title: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(String(512))
    image_filename: Mapped[str] = mapped_column(String(128))
    gender: Mapped[StyleGender] = mapped_column(Enum(StyleGender))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class StylePrompt(Base):
    __tablename__ = "style_prompts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Больше НЕ unique
    title: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(String(512))
    prompt: Mapped[str] = mapped_column(String(2048))
    image_filename: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    category_id: Mapped[int] = mapped_column(Integer, index=True)
    gender: Mapped[StyleGender] = mapped_column(Enum(StyleGender), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class PhotoshootLog(Base):
    __tablename__ = "photoshoot_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    style_title: Mapped[str] = mapped_column(String(128))
    status: Mapped[PhotoshootStatus] = mapped_column(Enum(PhotoshootStatus))

    cost_rub: Mapped[int] = mapped_column(Integer, default=0)
    cost_credits: Mapped[int] = mapped_column(Integer, default=0)

    provider: Mapped[str] = mapped_column(String(64), default="comet")
    error_message: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # новое поле: сколько входных фото использовалось (1–3)
    input_photos_count: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


MAX_AVATARS_PER_USER = 3


class UserAvatar(Base):
    __tablename__ = "user_avatars"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    file_id: Mapped[str] = mapped_column(String(255))
    source_style_title: Mapped[Optional[str]] = mapped_column(
        String(128),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


# -------------------------------------------------------------------
# Миграции "в лоб"
# -------------------------------------------------------------------


async def run_manual_migrations() -> None:
    """
    Ручные ALTER TABLE для уже существующей БД.
    На свежей БД (после create_all) они спокойно проигнорируются.
    """
    async with engine.begin() as conn:
        # --- input_photos_count в photoshoot_logs ---
        try:
            await conn.execute(
                text(
                    "ALTER TABLE photoshoot_logs "
                    "ADD COLUMN input_photos_count INTEGER DEFAULT 1"
                )
            )
        except OperationalError as e:
            msg = str(e)
            # SQLite / Postgres / прочие варианты «колонка уже есть» или «таблицы нет»
            if (
                "no such table: photoshoot_logs" in msg
                or "duplicate column name: input_photos_count" in msg
                or 'column "input_photos_count" of relation "photoshoot_logs" already exists' in msg
            ):
                # таблица ещё не создана или колонка уже добавлена — игнорируем
                pass
            else:
                raise

        # --- новый флаг is_referral в таблице users ---
        try:
            await conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN is_referral BOOLEAN DEFAULT 0"
                )
            )
        except OperationalError as e:
            msg = str(e)
            if (
                "no such table: users" in msg
                or "duplicate column name: is_referral" in msg
                or 'column "is_referral" of relation "users" already exists' in msg
            ):
                # таблицы нет или колонка уже есть — игнорируем
                pass
            else:
                raise

        # --- поле referral_earned_rub в таблице users ---
        try:
            await conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN referral_earned_rub INTEGER DEFAULT 0"
                )
            )
        except OperationalError as e:
            msg = str(e)
            if (
                "no such table: users" in msg
                or "duplicate column name: referral_earned_rub" in msg
                or 'column "referral_earned_rub" of relation "users" already exists' in msg
            ):
                # таблицы нет или колонка уже есть — игнорируем
                pass
            else:
                raise

        # --- миграция: убрать UNIQUE(title) для style_categories и style_prompts в SQLite ---
        # На других СУБД (Postgres и т.п.) это место можно доработать отдельно при необходимости.
        dialect_name = conn.dialect.name

        if dialect_name == "sqlite":
            # 1) style_categories
            try:
                # создаём временную таблицу без UNIQUE(title)
                await conn.execute(
                    text(
                        """
                        CREATE TABLE style_categories_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title VARCHAR(128) NOT NULL,
                            description VARCHAR(512) NOT NULL,
                            image_filename VARCHAR(128) NOT NULL,
                            gender VARCHAR(16) NOT NULL,
                            sort_order INTEGER NOT NULL DEFAULT 0,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )

                # копируем данные из старой таблицы, если она есть
                await conn.execute(
                    text(
                        """
                        INSERT INTO style_categories_new (
                            id,
                            title,
                            description,
                            image_filename,
                            gender,
                            sort_order,
                            is_active,
                            created_at
                        )
                        SELECT
                            id,
                            title,
                            description,
                            image_filename,
                            gender,
                            sort_order,
                            is_active,
                            created_at
                        FROM style_categories
                        """
                    )
                )

                # удаляем старую таблицу и переименовываем новую
                await conn.execute(text("DROP TABLE style_categories"))
                await conn.execute(
                    text(
                        "ALTER TABLE style_categories_new RENAME TO style_categories"
                    )
                )
            except OperationalError as e:
                msg = str(e)
                # если таблицы нет либо миграция уже делалась, просто пропускаем
                if (
                    "no such table: style_categories" in msg
                    or "table style_categories_new already exists" in msg
                ):
                    pass
                else:
                    raise

            # 2) style_prompts
            try:
                # создаём временную таблицу без UNIQUE(title)
                await conn.execute(
                    text(
                        """
                        CREATE TABLE style_prompts_new (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            title VARCHAR(128) NOT NULL,
                            description VARCHAR(512) NOT NULL,
                            prompt VARCHAR(2048) NOT NULL,
                            image_filename VARCHAR(128),
                            category_id INTEGER NOT NULL,
                            gender VARCHAR(16) NOT NULL,
                            is_active BOOLEAN NOT NULL DEFAULT 1,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        )
                        """
                    )
                )

                # копируем данные из старой таблицы
                await conn.execute(
                    text(
                        """
                        INSERT INTO style_prompts_new (
                            id,
                            title,
                            description,
                            prompt,
                            image_filename,
                            category_id,
                            gender,
                            is_active,
                            created_at
                        )
                        SELECT
                            id,
                            title,
                            description,
                            prompt,
                            image_filename,
                            category_id,
                            gender,
                            is_active,
                            created_at
                        FROM style_prompts
                        """
                    )
                )

                # удаляем старую таблицу и переименовываем новую
                await conn.execute(text("DROP TABLE style_prompts"))
                await conn.execute(
                    text(
                        "ALTER TABLE style_prompts_new RENAME TO style_prompts"
                    )
                )
            except OperationalError as e:
                msg = str(e)
                if (
                    "no such table: style_prompts" in msg
                    or "table style_prompts_new already exists" in msg
                ):
                    pass
                else:
                    raise

        # сюда при желании можно вернуть твои старые миграции для других таблиц


async def init_db() -> None:
    """
    Создаём таблицы по моделям и применяем ручные миграции.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await run_manual_migrations()


# -------------------------------------------------------------------
# Пользователи / админы / рефералы
# -------------------------------------------------------------------


async def get_or_create_user(
    telegram_id: int,
    username: Optional[str] = None,
    referrer_telegram_id: Optional[int] = None,
) -> User:
    """
    Получаем пользователя по telegram_id, если нет — создаём.
    referrer_telegram_id учитывается только при создании.
    """
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
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
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None

        user.is_admin = is_admin
        await session.commit()
        await session.refresh(user)
        return user


async def set_user_referral_flag(telegram_id: int, is_referral: bool) -> Optional[User]:
    """
    Пометить пользователя как «Реферал» (или снять этот флаг).
    Использовать для партнёров, которые рефералят массово и выводят деньги через админку.
    """
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None

        user.is_referral = is_referral
        await session.commit()
        await session.refresh(user)
        return user


async def get_referral_users() -> list[User]:
    """
    Список всех пользователей, помеченных как рефералы (партнёры).
    """
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.is_referral == True)  # noqa: E712
        )
        return list(result.scalars().all())


async def get_referrals_for_user(referrer_telegram_id: int) -> list[User]:
    """
    Все пользователи, которых привёл данный referrer (referrer_id = referrer_telegram_id).
    """
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.referrer_id == referrer_telegram_id)
        )
        return list(result.scalars().all())


async def get_referrals_count(referrer_telegram_id: int) -> int:
    """
    Сколько людей всего зарегистрировалось по реферальной ссылке данного пользователя.
    """
    async with async_session() as session:
        count_value = await session.scalar(
            select(func.count()).select_from(User).where(
                User.referrer_id == referrer_telegram_id
            )
        )
        return int(count_value or 0)


async def add_referral_earnings(telegram_id: int, amount_rub: int) -> Optional[User]:
    """
    Учитываем, что пользователю начислено amount_rub по реферальной программе.
    Это НЕ меняет баланс, а только накапливает статистику referral_earned_rub.
    Используй вместе с change_user_balance(...) в момент начисления бонуса.
    """
    if amount_rub <= 0:
        return None

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None

        user.referral_earned_rub = (user.referral_earned_rub or 0) + amount_rub
        await session.commit()
        await session.refresh(user)
        return user


async def get_referral_summary(telegram_id: int) -> Tuple[int, int]:
    """
    Сводка рефералки по пользователю:
    - total_earned: сколько всего рублей принесла реферальная программа.
    - total_referrals: сколько людей пришло по его ссылке.
    """
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        total_earned = 0
        if user is not None and user.referral_earned_rub is not None:
            total_earned = int(user.referral_earned_rub)

        referrals_count = await session.scalar(
            select(func.count()).select_from(User).where(
                User.referrer_id == telegram_id
            )
        )
        return total_earned, int(referrals_count or 0)


async def is_user_admin_db(telegram_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(User.is_admin).where(User.telegram_id == telegram_id)
        )
        value = result.scalar_one_or_none()
        return bool(value)


async def get_admin_users() -> List[User]:
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.is_admin == True)  # noqa: E712
        )
        return list(result.scalars().all())


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

        # 1) Пытаемся списать КРЕДИТ
        if user.photoshoot_credits > 0:
            user.photoshoot_credits -= 1
            await session.commit()
            return True

        # 2) Пытаемся списать РУБЛИ
        if user.balance >= price_rub:
            user.balance -= price_rub
            await session.commit()
            return True

        # 3) Ничего списать не удалось
        await session.rollback()
        return False


async def get_users_page(page: int = 0, page_size: int = 10) -> tuple[list[User], int]:
    offset = page * page_size

    async with async_session() as session:
        total = await session.scalar(select(func.count()).select_from(User))

        result = await session.execute(
            select(User)
            .order_by(User.created_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        users = list(result.scalars().all())

    return users, int(total or 0)


async def search_users(query: str, limit: int = 20) -> list[User]:
    q = query.strip()

    async with async_session() as session:
        if q.isdigit():
            telegram_id = int(q)
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            return list(result.scalars().all())

        if q.startswith("@"):
            q = q[1:]

        result = await session.execute(
            select(User).where(func.lower(User.username) == q.lower())
        )
        return list(result.scalars().all())


async def change_user_credits(telegram_id: int, delta: int) -> Optional[User]:
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


async def change_user_balance(telegram_id: int, delta: int) -> Optional[User]:
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


# -------------------------------------------------------------------
# Платежи Stars
# -------------------------------------------------------------------


async def create_star_payment(
    telegram_id: int,
    offer: StarOffer,
) -> StarPayment:
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
        result = await session.execute(
            select(StarPayment).where(StarPayment.payload == payload)
        )
        payment: StarPayment | None = result.scalar_one_or_none()
        if payment is None:
            return None

        if payment.status == PaymentStatus.success:
            result_user = await session.execute(
                select(User).where(User.telegram_id == payment.telegram_id)
            )
            user = result_user.scalar_one_or_none()
            return (user, payment) if user else None

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


# -------------------------------------------------------------------
# Логи фотосессий и отчёты
# -------------------------------------------------------------------


async def log_photoshoot(
    telegram_id: int,
    style_title: str,
    status: PhotoshootStatus,
    cost_rub: int = 0,
    cost_credits: int = 0,
    provider: str = "comet_gemini_2_5_flash",
    error_message: Optional[str] = None,
    input_photos_count: int = 1,
) -> PhotoshootLog:
    async with async_session() as session:
        # 1. Лог в таблицу photoshoot_logs
        log = PhotoshootLog(
            telegram_id=telegram_id,
            style_title=style_title,
            status=status,
            cost_rub=cost_rub,
            cost_credits=cost_credits,
            provider=provider,
            error_message=error_message,
            input_photos_count=input_photos_count,
        )
        session.add(log)

        # 2. Обновляем агрегированную статистику в user_stats
        result = await session.execute(
            select(UserStats).where(UserStats.telegram_id == telegram_id)
        )
        stats: UserStats | None = result.scalar_one_or_none()

        if stats is None:
            stats = UserStats(
                telegram_id=telegram_id,
                spent_rub=0,
                photos_success=0,
                photos_failed=0,
                last_photoshoot_at=None,
            )
            session.add(stats)

        # увеличиваем суммы
        if status == PhotoshootStatus.success:
            stats.photos_success += 1
            stats.spent_rub += max(cost_rub, 0)
        else:
            stats.photos_failed += 1

        stats.last_photoshoot_at = datetime.utcnow()

        await session.commit()
        await session.refresh(log)
        return log


async def get_photoshoot_report(days: int = 7) -> dict:
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


# -------------------------------------------------------------------
# Аватары
# -------------------------------------------------------------------


async def get_user_avatars(telegram_id: int) -> list[UserAvatar]:
    async with async_session() as session:
        result = await session.execute(
            select(UserAvatar)
            .where(UserAvatar.telegram_id == telegram_id)
            .order_by(UserAvatar.created_at.asc())
        )
        return list(result.scalars().all())


async def create_user_avatar(
    telegram_id: int,
    file_id: str,
    source_style_title: Optional[str] = None,
) -> Optional[UserAvatar]:
    async with async_session() as session:
        count = await session.scalar(
            select(func.count()).select_from(UserAvatar).where(
                UserAvatar.telegram_id == telegram_id
            )
        )
        if (count or 0) >= MAX_AVATARS_PER_USER:
            return None

        avatar = UserAvatar(
            telegram_id=telegram_id,
            file_id=file_id,
            source_style_title=source_style_title,
        )
        session.add(avatar)
        await session.commit()
        await session.refresh(avatar)
        return avatar


async def delete_user_avatar(telegram_id: int, avatar_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(UserAvatar).where(
                UserAvatar.id == avatar_id,
                UserAvatar.telegram_id == telegram_id,
            )
        )
        avatar = result.scalar_one_or_none()
        if avatar is None:
            return False

        await session.delete(avatar)
        await session.commit()
        return True


# -------------------------------------------------------------------
# Стили / категории
# -------------------------------------------------------------------


async def count_active_styles() -> int:
    async with async_session() as session:
        total = await session.scalar(
            select(func.count()).select_from(StylePrompt).where(
                StylePrompt.is_active == True  # noqa: E712
            )
        )
        return int(total or 0)


async def get_style_by_offset(offset: int) -> Optional[StylePrompt]:
    async with async_session() as session:
        result = await session.execute(
            select(StylePrompt)
            .where(StylePrompt.is_active == True)  # noqa: E712
            .order_by(StylePrompt.id.asc())
            .offset(offset)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_style_prompt_by_id(style_id: int) -> Optional[StylePrompt]:
    async with async_session() as session:
        style = await session.get(StylePrompt, style_id)
        return style


async def get_all_style_prompts(include_inactive: bool = True) -> list[StylePrompt]:
    async with async_session() as session:
        stmt = select(StylePrompt)
        if not include_inactive:
            stmt = stmt.where(StylePrompt.is_active == True)  # noqa: E712
        stmt = stmt.order_by(StylePrompt.category_id.asc(), StylePrompt.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def delete_style_prompt(style_id: int) -> bool:
    async with async_session() as session:
        style = await session.get(StylePrompt, style_id)
        if style is None:
            return False

        await session.delete(style)
        await session.commit()
        return True


async def create_style_category(
    title: str,
    description: str,
    image_filename: str,
    gender: StyleGender,
    is_active: bool = True,
) -> StyleCategory:
    async with async_session() as session:
        category = StyleCategory(
            title=title,
            description=description,
            image_filename=image_filename,
            gender=gender,
            is_active=is_active,
        )
        session.add(category)
        await session.commit()
        await session.refresh(category)
        return category


async def get_style_category_by_id(category_id: int) -> Optional[StyleCategory]:
    async with async_session() as session:
        category = await session.get(StyleCategory, category_id)
        return category


async def get_style_categories_for_gender(gender: StyleGender) -> list[StyleCategory]:
    async with async_session() as session:
        result = await session.execute(
            select(StyleCategory)
            .where(
                StyleCategory.gender == gender,
                StyleCategory.is_active == True,  # noqa: E712
            )
            .order_by(StyleCategory.id.asc())
        )
        return list(result.scalars().all())


async def get_all_style_categories(include_inactive: bool = False) -> list[StyleCategory]:
    async with async_session() as session:
        stmt = select(StyleCategory)
        if not include_inactive:
            stmt = stmt.where(StyleCategory.is_active == True)  # noqa: E712
        stmt = stmt.order_by(StyleCategory.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def create_style_prompt(
    title: str,
    description: str,
    prompt: str,
    image_filename: str,
    category_id: int,
) -> StylePrompt:
    """
    Создаёт новый стиль. Пол берём из категории.
    """
    async with async_session() as session:
        result = await session.execute(
            select(StyleCategory).where(StyleCategory.id == category_id)
        )
        category = result.scalar_one_or_none()
        if category is None:
            raise ValueError(f"StyleCategory with id={category_id} not found")

        style = StylePrompt(
            title=title,
            description=description,
            prompt=prompt,
            image_filename=image_filename,
            category_id=category.id,
            gender=category.gender,
        )
        session.add(style)
        await session.commit()
        await session.refresh(style)
        return style


async def get_styles_for_category(category_id: int) -> list[StylePrompt]:
    async with async_session() as session:
        result = await session.execute(
            select(StylePrompt)
            .where(
                StylePrompt.category_id == category_id,
                StylePrompt.is_active == True,  # noqa: E712
            )
            .order_by(StylePrompt.id.asc())
        )
        return list(result.scalars().all())


async def get_styles_by_category_and_gender(
    category_id: int,
    gender: StyleGender,
) -> list[StylePrompt]:
    async with async_session() as session:
        stmt = (
            select(StylePrompt)
            .where(
                StylePrompt.is_active == True,  # noqa: E712
                StylePrompt.category_id == category_id,
                StylePrompt.gender == gender,
            )
            .order_by(StylePrompt.id.asc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


class UserStats(Base):
    __tablename__ = "user_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, unique=True)

    # Сколько рублей списали за все успешные фотосессии
    spent_rub: Mapped[int] = mapped_column(Integer, default=0)

    # Кол-во успешных и заваленных фотосессий
    photos_success: Mapped[int] = mapped_column(Integer, default=0)
    photos_failed: Mapped[int] = mapped_column(Integer, default=0)

    # Когда последний раз была фотосессия (успешная или неуспешная)
    last_photoshoot_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


async def get_or_create_user_stats(telegram_id: int) -> UserStats:
    """
    Возвращает строку статистики пользователя, если нет — создаёт с нуля.
    """
    async with async_session() as session:
        result = await session.execute(
            select(UserStats).where(UserStats.telegram_id == telegram_id)
        )
        stats = result.scalar_one_or_none()

        if stats:
            return stats

        stats = UserStats(
            telegram_id=telegram_id,
            spent_rub=0,
            photos_success=0,
            photos_failed=0,
        )
        session.add(stats)
        await session.commit()
        await session.refresh(stats)
        return stats


async def get_all_user_stats() -> list[UserStats]:
    """
    Возвращает агрегированную статистику по всем пользователям.
    """
    async with async_session() as session:
        result = await session.execute(
            select(UserStats).order_by(UserStats.spent_rub.desc())
        )
        return list(result.scalars().all())


class SupportTopic(Base):
    __tablename__ = "support_topics"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
async def get_support_thread_id(telegram_id: int) -> Optional[int]:
    async with async_session() as session:
        obj = await session.get(SupportTopic, telegram_id)
        return int(obj.thread_id) if obj else None


async def get_support_user_id_by_thread(thread_id: int) -> Optional[int]:
    async with async_session() as session:
        res = await session.execute(
            select(SupportTopic.telegram_id).where(SupportTopic.thread_id == thread_id)
        )
        val = res.scalar_one_or_none()
        return int(val) if val is not None else None


async def bind_support_thread(telegram_id: int, thread_id: int) -> None:
    async with async_session() as session:
        session.add(SupportTopic(telegram_id=telegram_id, thread_id=thread_id))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            # кто-то уже записал — ок