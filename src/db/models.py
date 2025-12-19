# src/db/models.py
from __future__ import annotations

import datetime as dt
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    Integer,
    String,
    func, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .enums import PaymentStatus, PhotoshootStatus, StyleGender


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    balance: Mapped[int] = mapped_column(Integer, default=0)
    photoshoot_credits: Mapped[int] = mapped_column(Integer, default=0)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    is_referral: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_earned_rub: Mapped[int] = mapped_column(Integer, default=0)

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

    payload: Mapped[str] = mapped_column(String(128), unique=True)
    telegram_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

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


from sqlalchemy import Text  # добавь

class StylePrompt(Base):
    __tablename__ = "style_prompts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(String(512))
    prompt: Mapped[str] = mapped_column(String(2048))
    image_filename: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    category_id: Mapped[int] = mapped_column(Integer, index=True)
    gender: Mapped[StyleGender] = mapped_column(Enum(StyleGender), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # ✅ НОВОЕ: пометка "новый стиль" (ставит админ)
    is_new: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )

    # ✅ НОВОЕ: счётчик использований
    usage_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )

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

    input_photos_count: Mapped[int] = mapped_column(Integer, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class UserAvatar(Base):
    __tablename__ = "user_avatars"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    file_id: Mapped[str] = mapped_column(String(255))
    source_style_title: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )


class UserStats(Base):
    __tablename__ = "user_stats"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True, unique=True)

    spent_rub: Mapped[int] = mapped_column(Integer, default=0)
    photos_success: Mapped[int] = mapped_column(Integer, default=0)
    photos_failed: Mapped[int] = mapped_column(Integer, default=0)

    last_photoshoot_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class SupportTopic(Base):
    __tablename__ = "support_topics"

    telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    thread_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )