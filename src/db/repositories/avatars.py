# src/db/repositories/avatars.py
from __future__ import annotations

from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.sql.expression import text

from src.db.session import async_session
from src.db.models import UserAvatar


async def get_user_avatar(telegram_id: int) -> Optional[UserAvatar]:
    async with async_session() as session:
        result = await session.execute(
            select(UserAvatar)
            .where(UserAvatar.telegram_id == telegram_id)
            .order_by(UserAvatar.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


async def get_user_avatars(telegram_id: int) -> list[UserAvatar]:
    avatar = await get_user_avatar(telegram_id)
    return [avatar] if avatar else []


async def set_user_avatar(
    telegram_id: int,
    file_id: str,
    source_style_title: Optional[str] = None,
) -> UserAvatar:
    async with async_session() as session:
        await session.execute(delete(UserAvatar).where(UserAvatar.telegram_id == telegram_id))

        avatar = UserAvatar(
            telegram_id=telegram_id,
            file_id=file_id,
            source_style_title=source_style_title,
        )
        session.add(avatar)
        await session.commit()
        await session.refresh(avatar)
        return avatar


async def create_user_avatar(
    telegram_id: int,
    file_id: str,
    source_style_title: Optional[str] = None,
) -> Optional[UserAvatar]:
    async with async_session() as session:
        await session.execute(
            text("DELETE FROM user_avatars WHERE telegram_id = :tg_id"),
            {"tg_id": telegram_id},
        )

        avatar = UserAvatar(
            telegram_id=telegram_id,
            file_id=file_id,
            source_style_title=source_style_title,
        )
        session.add(avatar)
        await session.commit()
        await session.refresh(avatar)
        return avatar


async def delete_user_avatar(telegram_id: int) -> bool:
    async with async_session() as session:
        res = await session.execute(delete(UserAvatar).where(UserAvatar.telegram_id == telegram_id))
        await session.commit()
        return bool(res.rowcount and res.rowcount > 0)