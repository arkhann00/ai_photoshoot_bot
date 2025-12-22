from __future__ import annotations

from typing import Optional, List, Tuple

from sqlalchemy import delete, select, update, desc
from sqlalchemy.exc import IntegrityError

from src.constants import PHOTOSHOOT_PRICE
from src.db.session import async_session
from src.db.models import PromoCode, PromoCodeRedemption, User


def _normalize_code(code: str) -> str:
    """
    Нормализуем промокод:
    - убираем пробелы по краям
    - приводим к верхнему регистру
    """
    return (code or "").strip().upper()


# -------------------------------------------------------------------
# CRUD для админ-эндпоинтов (по id) + поиск (по коду)
# -------------------------------------------------------------------

async def list_promo_codes(*, include_inactive: bool = True) -> List[PromoCode]:
    """
    Список промокодов для админки.
    include_inactive=True  -> все
    include_inactive=False -> только активные
    """
    async with async_session() as session:
        stmt = select(PromoCode)
        if not include_inactive:
            stmt = stmt.where(PromoCode.is_active == True)  # noqa: E712
        # если поля created_at нет — сортировка просто не сработает, но обычно оно есть
        if hasattr(PromoCode, "created_at"):
            stmt = stmt.order_by(desc(PromoCode.created_at))
        else:
            stmt = stmt.order_by(desc(PromoCode.id))

        res = await session.execute(stmt)
        return list(res.scalars().all())


async def get_promo_code_by_code(code: str) -> Optional[PromoCode]:
    """
    Возвращает промокод по текстовому коду (без требований к активности).
    Нужно админке / валидации.
    """
    normalized = _normalize_code(code)
    if not normalized:
        return None

    async with async_session() as session:
        stmt = select(PromoCode).where(PromoCode.code == normalized)
        res = await session.execute(stmt)
        return res.scalar_one_or_none()


async def set_promo_code_active(*, promo_id: int, is_active: bool) -> Optional[PromoCode]:
    """
    Включить/выключить промокод по promo_id.
    Возвращает обновлённый PromoCode или None, если не найден.
    """
    if not isinstance(promo_id, int) or promo_id <= 0:
        return None

    async with async_session() as session:
        promo = await session.get(PromoCode, promo_id)
        if promo is None:
            return None

        promo.is_active = bool(is_active)
        await session.commit()
        await session.refresh(promo)
        return promo


async def delete_promo_code(*, promo_id: int) -> bool:
    """
    Удаляет промокод по promo_id.
    Возвращает True, если удалили.
    """
    if not isinstance(promo_id, int) or promo_id <= 0:
        return False

    async with async_session() as session:
        stmt = delete(PromoCode).where(PromoCode.id == promo_id)
        res = await session.execute(stmt)
        await session.commit()
        return (res.rowcount or 0) > 0


# -------------------------------------------------------------------
# Создание (по коду) + функции для использования промокода (по коду)
# -------------------------------------------------------------------

async def create_promo_code(
    *,
    code: str,
    generations: int,
    is_active: bool = True,
) -> PromoCode:
    """
    Добавляет промокод в БД.
    Бросает ValueError при невалидных данных или если код уже существует.
    """
    normalized = _normalize_code(code)
    if not normalized:
        raise ValueError("Промокод не может быть пустым")
    if len(normalized) > 128:
        raise ValueError("Промокод слишком длинный (макс 128 символов)")
    if generations <= 0:
        raise ValueError("generations должен быть > 0")

    async with async_session() as session:
        promo = PromoCode(
            code=normalized,
            generations=int(generations),
            is_active=bool(is_active),
        )
        session.add(promo)

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise ValueError(f"Промокод '{normalized}' уже существует")

        await session.refresh(promo)
        return promo


async def get_promo_code_for_use(*, code: str) -> Optional[PromoCode]:
    """
    Проверка промокода "для использования":
    - существует
    - активен
    - generations > 0

    Возвращает PromoCode или None.
    """
    normalized = _normalize_code(code)
    if not normalized:
        return None

    async with async_session() as session:
        stmt = select(PromoCode).where(
            PromoCode.code == normalized,
            PromoCode.is_active == True,  # noqa: E712
            PromoCode.generations > 0,
        )
        res = await session.execute(stmt)
        return res.scalar_one_or_none()


async def is_promo_code_active(*, code: str) -> bool:
    """
    Быстрая проверка активности промокода для UI/валидации.
    True = можно использовать (активен и generations > 0).
    """
    promo = await get_promo_code_for_use(code=code)
    return promo is not None


# -------------------------------------------------------------------
# Утилиты "по коду" (удобно для бота/скриптов), не мешают админке
# -------------------------------------------------------------------

async def set_promo_code_active_by_code(*, code: str, is_active: bool) -> bool:
    """
    Включает/выключает промокод по текстовому коду.
    Возвращает True, если найден и обновлён.
    """
    normalized = _normalize_code(code)
    if not normalized:
        return False

    async with async_session() as session:
        stmt = (
            update(PromoCode)
            .where(PromoCode.code == normalized)
            .values(is_active=bool(is_active))
            .execution_options(synchronize_session="fetch")
        )
        res = await session.execute(stmt)
        await session.commit()
        return (res.rowcount or 0) > 0


async def activate_promo_code(*, code: str) -> bool:
    return await set_promo_code_active_by_code(code=code, is_active=True)


async def deactivate_promo_code(*, code: str) -> bool:
    return await set_promo_code_active_by_code(code=code, is_active=False)


async def delete_promo_code_by_code(*, code: str) -> bool:
    """
    Удаляет промокод по текстовому коду.
    Возвращает True, если удалили.
    """
    normalized = _normalize_code(code)
    if not normalized:
        return False

    async with async_session() as session:
        stmt = delete(PromoCode).where(PromoCode.code == normalized)
        res = await session.execute(stmt)
        await session.commit()
        return (res.rowcount or 0) > 0


async def redeem_promo_code_for_user(*, telegram_id: int, code: str) -> Tuple[str, int, int]:
    """
    Применение промокода пользователем.

    Возвращает:
    - ("ok", grant_generations, new_balance)
    - ("already_used", 0, current_balance)
    - ("invalid", 0, current_balance)
    """
    normalized = _normalize_code(code)
    if not normalized or telegram_id <= 0:
        # баланс неизвестен -> 0
        return "invalid", 0, 0

    async with async_session() as session:
        # На invalid/used тоже хотим вернуть текущий баланс
        async def _get_balance() -> int:
            bal = await session.scalar(
                select(User.balance).where(User.telegram_id == int(telegram_id))
            )
            return int(bal or 0)

        try:
            async with session.begin():
                # 1) блокируем промокод
                promo_stmt = (
                    select(PromoCode)
                    .where(
                        PromoCode.code == normalized,
                        PromoCode.is_active == True,  # noqa: E712
                        PromoCode.generations > 0,
                    )
                    .with_for_update()
                )
                promo: Optional[PromoCode] = (await session.execute(promo_stmt)).scalar_one_or_none()
                if promo is None:
                    # промокод невалиден — вернём текущий баланс
                    return "invalid", 0, await _get_balance()

                grant_generations = int(promo.generations)
                credit_rub = int(PHOTOSHOOT_PRICE) * grant_generations

                # 2) гарантируем, что пользователь существует + блокируем
                user_stmt = (
                    select(User)
                    .where(User.telegram_id == int(telegram_id))
                    .with_for_update()
                )
                user: Optional[User] = (await session.execute(user_stmt)).scalar_one_or_none()
                if user is None:
                    user = User(telegram_id=int(telegram_id), balance=0, photoshoot_credits=0)
                    session.add(user)
                    await session.flush()

                # 3) фиксируем использование промокода (UNIQUE(promo_code_id, telegram_id))
                redemption = PromoCodeRedemption(
                    promo_code_id=int(promo.id),
                    telegram_id=int(telegram_id),
                    granted_generations=grant_generations,
                )
                session.add(redemption)

                # 4) начисляем на баланс
                await session.execute(
                    update(User)
                    .where(User.telegram_id == int(telegram_id))
                    .values(balance=User.balance + credit_rub)
                )

            # после commit читаем новый баланс (вне session.begin уже можно)
            new_balance = await session.scalar(
                select(User.balance).where(User.telegram_id == int(telegram_id))
            )
            return "ok", grant_generations, int(new_balance or 0)

        except IntegrityError:
            await session.rollback()
            # уже использовал — вернём текущий баланс
            return "already_used", 0, await _get_balance()