# src/db/repositories/stats.py
from __future__ import annotations

from sqlalchemy import delete, select

from src.db.session import async_session
from src.db.models import PhotoshootLog, UserStats


async def get_or_create_user_stats(telegram_id: int) -> UserStats:
    async with async_session() as session:
        result = await session.execute(select(UserStats).where(UserStats.telegram_id == telegram_id))
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
    async with async_session() as session:
        result = await session.execute(select(UserStats).order_by(UserStats.spent_rub.desc()))
        return list(result.scalars().all())


async def clear_users_statistics(clear_photoshoot_logs: bool = True) -> dict:
    async with async_session() as session:
        deleted_logs = 0
        if clear_photoshoot_logs:
            res_logs = await session.execute(delete(PhotoshootLog))
            deleted_logs = int(res_logs.rowcount or 0)

        res_stats = await session.execute(delete(UserStats))
        deleted_stats = int(res_stats.rowcount or 0)

        await session.commit()

        return {
            "deleted_user_stats": deleted_stats,
            "deleted_photoshoot_logs": deleted_logs,
        }