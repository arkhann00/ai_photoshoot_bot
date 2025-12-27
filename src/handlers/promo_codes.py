# src/db/repositories/promo_codes.py
from __future__ import annotations

from typing import Tuple

from sqlalchemy import select, func
from sqlalchemy.exc import SQLAlchemyError

from src.constants import PHOTOSHOOT_PRICE
from src.db.session import async_session
from src.db.models import User, PromoCode, PromoCodeRedemption  # <-- подстрой имена моделей под свои


async def redeem_promo_code_for_user(telegram_id: int, code: str) -> Tuple[str, int, int]:
    """
    Возвращает: (status, grant, new_balance)
      status:
        - "invalid"        промокод не найден / неактивен
        - "already_used"   этот пользователь уже применял
        - "ok"             успешно применён
      grant: сколько генераций выдали по промокоду
      new_balance: новый баланс пользователя (₽)

    ВАЖНО: после ПЕРВОГО успешного применения промокод деактивируется глобально.
    """

    code_norm = (code or "").strip().upper()
    if not code_norm:
        return "invalid", 0, 0

    async with async_session() as session:
        try:
            # 1) Лочим промокод строкой (защита от одновременного применения двумя юзерами)
            promo: PromoCode | None = (
                await session.scalar(
                    select(PromoCode)
                    .where(func.upper(PromoCode.code) == code_norm)
                    .with_for_update()
                )
            )

            # Баланс нужен для ответов (даже если промо невалидно)
            user: User | None = await session.scalar(
                select(User).where(User.telegram_id == telegram_id).with_for_update()
            )
            if user is None:
                user = User(telegram_id=telegram_id, balance=0, photoshoot_credits=0)
                session.add(user)
                await session.flush()

            if promo is None:
                await session.rollback()
                return "invalid", 0, int(user.balance or 0)

            # 2) Если этот пользователь уже применял — возвращаем already_used
            already = await session.scalar(
                select(func.count())
                .select_from(PromoCodeRedemption)
                .where(
                    PromoCodeRedemption.promo_code_id == promo.id,
                    PromoCodeRedemption.telegram_id == telegram_id,
                )
            )
            if int(already or 0) > 0:
                await session.rollback()
                return "already_used", int(getattr(promo, "grant", 0) or 0), int(user.balance or 0)

            # 3) Если промокод уже выключен — для новых пользователей он "invalid"
            if not bool(getattr(promo, "is_active", False)):
                await session.rollback()
                return "invalid", 0, int(user.balance or 0)

            # 4) Начисляем
            grant = int(getattr(promo, "grant", 0) or 0)
            if grant <= 0:
                # бессмысленный промокод — тоже считаем невалидным
                await session.rollback()
                return "invalid", 0, int(user.balance or 0)

            credited_rub = int(PHOTOSHOOT_PRICE) * grant
            user.balance = int(user.balance or 0) + credited_rub

            # 5) Фиксируем факт использования
            session.add(
                PromoCodeRedemption(
                    promo_code_id=promo.id,
                    telegram_id=telegram_id,
                )
            )

            # ✅ 6) Ключевое: деактивируем промокод сразу после первого успешного применения
            promo.is_active = False

            await session.commit()
            return "ok", grant, int(user.balance or 0)

        except SQLAlchemyError:
            await session.rollback()
            # в случае ошибки БД лучше не "дарить" промокод
            return "invalid", 0, 0
        except Exception:
            await session.rollback()
            return "invalid", 0, 0