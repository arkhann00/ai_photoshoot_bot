from __future__ import annotations

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from sqlalchemy import select

from src.db import async_session
from src.db.models import PromoCode

# Пытаемся использовать уже существующую функцию, если она есть в твоём проекте
try:
    # часто так и называется в твоём бэке
    from src.db import change_user_credits  # type: ignore
except Exception:  # pragma: no cover
    change_user_credits = None  # fallback сделаем ниже

# Подключаем стартовую клавиатуру (путь подстрой под свой проект, если отличается)
from src.keyboards import get_start_keyboard


router = Router()


class PromoCodeStates(StatesGroup):
    waiting_for_code = State()


def _promo_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="promo_code_cancel")]
        ]
    )


def _normalize_code(code: str) -> str:
    return (code or "").strip().upper()


async def _add_user_credits(telegram_id: int, delta: int) -> None:
    """
    Начисляет пользователю credits.
    1) Если в проекте есть change_user_credits — используем её.
    2) Иначе делаем прямое обновление через SQLAlchemy.
    """
    if delta <= 0:
        return

    if change_user_credits is not None:
        # ожидаем async функцию вида change_user_credits(telegram_id=..., delta=...)
        await change_user_credits(telegram_id=telegram_id, delta=delta)  # type: ignore
        return

    # Fallback: прямое обновление (если вдруг change_user_credits отсутствует)
    from sqlalchemy import update
    from src.db.models import User  # локальный импорт, чтобы не ломать импорты при другой структуре

    async with async_session() as session:
        stmt = (
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(photoshoot_credits=User.photoshoot_credits + int(delta))
        )
        await session.execute(stmt)
        await session.commit()


@router.callback_query(F.data == "promo_code")
async def promo_code_entrypoint(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoCodeStates.waiting_for_code)

    text = (
        "Введи промокод одним сообщением.\n\n"
        "Пример: `PROMO2025`\n\n"
        "Чтобы отменить — нажми «Отмена»."
    )

    if cb.message:
        await cb.message.answer(text, reply_markup=_promo_cancel_kb(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == "promo_code_cancel")
async def promo_code_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if cb.message:
        await cb.message.answer("Ок, отменил ввод промокода.", reply_markup=get_start_keyboard())
    await cb.answer()


@router.message(PromoCodeStates.waiting_for_code, F.text)
async def promo_code_process(message: Message, state: FSMContext) -> None:
    raw = message.text or ""
    if raw.strip().lower() in {"/cancel", "cancel", "отмена"}:
        await state.clear()
        await message.answer("Ок, отменил.", reply_markup=get_start_keyboard())
        return

    code = _normalize_code(raw)
    if not code:
        await message.answer("Промокод пустой. Введи код текстом или нажми «Отмена».", reply_markup=_promo_cancel_kb())
        return

    if len(code) > 128:
        await message.answer("Промокод слишком длинный. Проверь ввод и попробуй ещё раз.", reply_markup=_promo_cancel_kb())
        return

    # Атомарно проверяем и “сжигаем” промокод:
    # - существует
    # - активен
    # - generations > 0
    # - блокируем строку (FOR UPDATE), чтобы не списали два раза параллельно
    try:
        async with async_session() as session:
            stmt = (
                select(PromoCode)
                .where(
                    PromoCode.code == code,
                    PromoCode.is_active == True,  # noqa: E712
                    PromoCode.generations > 0,
                )
                .with_for_update()
            )
            promo: PromoCode | None = (await session.execute(stmt)).scalar_one_or_none()

            if promo is None:
                await message.answer(
                    "Промокод не найден или уже недействителен.\n"
                    "Проверь код и попробуй ещё раз.",
                    reply_markup=_promo_cancel_kb(),
                )
                return

            grant = int(promo.generations)

            # Логика “одноразового” промокода:
            # отдаём все generations пользователю и делаем промокод недействительным
            promo.generations = 0
            promo.is_active = False

            await session.commit()

        # начисляем пользователю кредиты
        tg_id = message.from_user.id if message.from_user else 0
        if tg_id <= 0:
            await message.answer("Не смог определить пользователя. Попробуй ещё раз позже.")
            return

        await _add_user_credits(tg_id, grant)

        await state.clear()
        await message.answer(
            f"✅ Промокод применён!\nНачислено фотосессий: {grant}",
            reply_markup=get_start_keyboard(),
        )

    except Exception:
        await message.answer(
            "Произошла ошибка при применении промокода. Попробуй позже или напиши в поддержку.",
            reply_markup=get_start_keyboard(),
        )
        await state.clear()


@router.message(PromoCodeStates.waiting_for_code)
async def promo_code_non_text(message: Message) -> None:
    await message.answer("Пришли промокод текстом (сообщением).", reply_markup=_promo_cancel_kb())

    from __future__ import annotations

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from sqlalchemy import select

from src.db import async_session
from src.db.models import PromoCode

# Пытаемся использовать уже существующую функцию, если она есть в твоём проекте
try:
    # часто так и называется в твоём бэке
    from src.db import change_user_credits  # type: ignore
except Exception:  # pragma: no cover
    change_user_credits = None  # fallback сделаем ниже

# Подключаем стартовую клавиатуру (путь подстрой под свой проект, если отличается)
from src.keyboards import get_start_keyboard


router = Router()


class PromoCodeStates(StatesGroup):
    waiting_for_code = State()


def _promo_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data="promo_code_cancel")]
        ]
    )


def _normalize_code(code: str) -> str:
    return (code or "").strip().upper()


async def _add_user_credits(telegram_id: int, delta: int) -> None:
    """
    Начисляет пользователю credits.
    1) Если в проекте есть change_user_credits — используем её.
    2) Иначе делаем прямое обновление через SQLAlchemy.
    """
    if delta <= 0:
        return

    if change_user_credits is not None:
        # ожидаем async функцию вида change_user_credits(telegram_id=..., delta=...)
        await change_user_credits(telegram_id=telegram_id, delta=delta)  # type: ignore
        return

    # Fallback: прямое обновление (если вдруг change_user_credits отсутствует)
    from sqlalchemy import update
    from src.db.models import User  # локальный импорт, чтобы не ломать импорты при другой структуре

    async with async_session() as session:
        stmt = (
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(photoshoot_credits=User.photoshoot_credits + int(delta))
        )
        await session.execute(stmt)
        await session.commit()


@router.callback_query(F.data == "promo_code")
async def promo_code_entrypoint(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(PromoCodeStates.waiting_for_code)

    text = (
        "Введи промокод одним сообщением.\n\n"
        "Пример: `PROMO2025`\n\n"
        "Чтобы отменить — нажми «Отмена»."
    )

    if cb.message:
        await cb.message.answer(text, reply_markup=_promo_cancel_kb(), parse_mode="Markdown")
    await cb.answer()


@router.callback_query(F.data == "promo_code_cancel")
async def promo_code_cancel(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    if cb.message:
        await cb.message.answer("Ок, отменил ввод промокода.", reply_markup=get_start_keyboard())
    await cb.answer()


@router.message(PromoCodeStates.waiting_for_code, F.text)
async def promo_code_process(message: Message, state: FSMContext) -> None:
    raw = message.text or ""
    if raw.strip().lower() in {"/cancel", "cancel", "отмена"}:
        await state.clear()
        await message.answer("Ок, отменил.", reply_markup=get_start_keyboard())
        return

    code = _normalize_code(raw)
    if not code:
        await message.answer("Промокод пустой. Введи код текстом или нажми «Отмена».", reply_markup=_promo_cancel_kb())
        return

    if len(code) > 128:
        await message.answer("Промокод слишком длинный. Проверь ввод и попробуй ещё раз.", reply_markup=_promo_cancel_kb())
        return

    # Атомарно проверяем и “сжигаем” промокод:
    # - существует
    # - активен
    # - generations > 0
    # - блокируем строку (FOR UPDATE), чтобы не списали два раза параллельно
    try:
        async with async_session() as session:
            stmt = (
                select(PromoCode)
                .where(
                    PromoCode.code == code,
                    PromoCode.is_active == True,  # noqa: E712
                    PromoCode.generations > 0,
                )
                .with_for_update()
            )
            promo: PromoCode | None = (await session.execute(stmt)).scalar_one_or_none()

            if promo is None:
                await message.answer(
                    "Промокод не найден или уже недействителен.\n"
                    "Проверь код и попробуй ещё раз.",
                    reply_markup=_promo_cancel_kb(),
                )
                return

            grant = int(promo.generations)

            # Логика “одноразового” промокода:
            # отдаём все generations пользователю и делаем промокод недействительным
            promo.generations = 0
            promo.is_active = False

            await session.commit()

        # начисляем пользователю кредиты
        tg_id = message.from_user.id if message.from_user else 0
        if tg_id <= 0:
            await message.answer("Не смог определить пользователя. Попробуй ещё раз позже.")
            return

        await _add_user_credits(tg_id, grant)

        await state.clear()
        await message.answer(
            f"✅ Промокод применён!\nНачислено фотосессий: {grant}",
            reply_markup=get_start_keyboard(),
        )

    except Exception:
        await message.answer(
            "Произошла ошибка при применении промокода. Попробуй позже или напиши в поддержку.",
            reply_markup=get_start_keyboard(),
        )
        await state.clear()


@router.message(PromoCodeStates.waiting_for_code)
async def promo_code_non_text(message: Message) -> None:
    await message.answer("Пришли промокод текстом (сообщением).", reply_markup=_promo_cancel_kb())