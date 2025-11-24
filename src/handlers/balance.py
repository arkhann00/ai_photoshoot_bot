# src/handlers/balance.py

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.states import MainStates
from src.db import get_user_balance
from src.data.styles import PHOTOSHOOT_PRICE
from src.keyboards import get_balance_keyboard


router = Router()


@router.message(F.text == "Баланс")
async def balance(message: Message, state: FSMContext):
    await state.set_state(MainStates.balance)

    user_balance = await get_user_balance(message.from_user.id)
    photos_left = 0
    if PHOTOSHOOT_PRICE > 0:
        photos_left = user_balance // PHOTOSHOOT_PRICE

    text = (
        f"Ваш баланс: {user_balance} ₽ "
        f"(остаток примерно на {photos_left} фотосессий)\n\n"
        "Пополни баланс и получи бонусы:\n"
        "290 ₽ → 350 ₽ на счёт (+20 %)\n"
        "790 ₽ → 1000 ₽ на счёт (+26 %)\n"
        "1 490 ₽ → 2000 ₽ на счёт (+34 %)\n\n"
        "Или воспользуйся оплатой через Telegram Stars ⭐ "
        "— нажми «Пополнить баланс», чтобы выбрать пакет."
    )

    await message.answer(
        text,
        reply_markup=get_balance_keyboard(),  # вот тут добавили кнопки
    )
