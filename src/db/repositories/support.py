# src/db/repositories/support.py
from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.db.session import async_session
from src.db.models import SupportTopic


async def get_support_thread_id(telegram_id: int) -> Optional[int]:
    async with async_session() as session:
        obj = await session.get(SupportTopic, telegram_id)
        return int(obj.thread_id) if obj else None


async def get_support_user_id_by_thread(thread_id: int) -> Optional[int]:
    async with async_session() as session:
        res = await session.execute(select(SupportTopic.telegram_id).where(SupportTopic.thread_id == thread_id))
        val = res.scalar_one_or_none()
        return int(val) if val is not None else None


async def bind_support_thread(telegram_id: int, thread_id: int) -> None:
    async with async_session() as session:
        session.add(SupportTopic(telegram_id=telegram_id, thread_id=thread_id))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()