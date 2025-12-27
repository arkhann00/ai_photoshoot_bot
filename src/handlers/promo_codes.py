from __future__ import annotations

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

from src.constants import PHOTOSHOOT_PRICE
from src.keyboards import get_start_keyboard
from src.db.repositories.promo_codes import redeem_promo_code_for_user
from src.handlers.balance import get_balance_keyboard

router = Router()


class PromoCodeStates(StatesGroup):
    waiting_for_code = State()


def _promo_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Отмена", callback_data="promo_code_cancel")]]
    )


def _normalize_code(code: str) -> str:
    return (code or "").strip().upper()


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
    tg_id = message.from_user.id if message.from_user else 0
    if tg_id <= 0:
        await message.answer("Не смог определить пользователя. Попробуй позже.")
        return

    code = _normalize_code(message.text or "")
    if not code:
        await message.answer("Промокод пустой. Введи код текстом.", reply_markup=_promo_cancel_kb())
        return

    status, grant, new_balance = await redeem_promo_code_for_user(telegram_id=tg_id, code=code)

    if status == "invalid":
        await message.answer(
            "Промокод не найден или недействителен.",
            reply_markup=_promo_cancel_kb(),
        )
        return

    if status == "already_used":
        await message.answer(
            f"Ты уже использовал этот промокод.\n"
            f"Текущий баланс: {new_balance} ₽",
            reply_markup=get_start_keyboard(),
        )
        await state.clear()
        return

    credited_rub = int(PHOTOSHOOT_PRICE) * int(grant)
    await message.answer(
        f"✅ Промокод применён!\n"
        f"Начислено: {grant} генераций (= {credited_rub} ₽ на баланс).\n"
        f"Текущий баланс: {new_balance} ₽",
        reply_markup=get_start_keyboard(),
    )
    await state.clear()


@router.message(PromoCodeStates.waiting_for_code)
async def promo_code_non_text(message: Message) -> None:
    await message.answer("Пришли промокод текстом (сообщением).", reply_markup=_promo_cancel_kb())