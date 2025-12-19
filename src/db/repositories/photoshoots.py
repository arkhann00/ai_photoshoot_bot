# src/db/repositories/photoshoots.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import func, select

from src.db.session import async_session
from src.db.models import PhotoshootLog, StarPayment, UserStats
from src.db.enums import PhotoshootStatus, PaymentStatus


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

        result = await session.execute(select(UserStats).where(UserStats.telegram_id == telegram_id))
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
            select(func.count()).select_from(PhotoshootLog).where(PhotoshootLog.created_at >= since)
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
            select(func.coalesce(func.sum(PhotoshootLog.cost_rub), 0)).where(PhotoshootLog.created_at >= since)
        ) or 0

        sum_cost_credits = await session.scalar(
            select(func.coalesce(func.sum(PhotoshootLog.cost_credits), 0)).where(PhotoshootLog.created_at >= since)
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