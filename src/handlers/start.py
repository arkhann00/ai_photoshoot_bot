# src/handlers/start.py

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from src.db import get_or_create_user
from src.states import MainStates
from src.keyboards import get_start_keyboard, back_to_main_menu_keyboard

router = Router()


@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext):
    # создаём/обновляем пользователя в БД
    await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        # сюда можно добавить referrer_telegram_id, если уже сделал реферальную связку
        # referrer_telegram_id=...
    )

    await state.set_state(MainStates.start)

    await message.answer(
        """📸 Добро пожаловать в Ai Photo-Studio!
        \n\nЗдесь твои снимки обретают новую жизнь — я превращу любую фотографию в стильный, выразительный и по-настоящему уникальный визуальный образ. 
        \n\nВыбирай категорию и смело начинай — создадим что-то впечатляющее 😉""",
        reply_markup=get_start_keyboard(),
    )


@router.message(Command("ref"))
async def referral_link_command(message: Message):
    """
    Команда /ref — отдаём реферальную ссылку.
    """
    me = await message.bot.get_me()
    bot_username = me.username

    if not bot_username:
        await message.answer(
            "Не удалось получить username бота. Обратись к администратору."
        )
        return

    link = f"https://t.me/{bot_username}?start={message.from_user.id}"

    await message.answer(
        "Вот твоя реферальная ссылка:\n"
        f"{link}\n\n"
        "Отправь её друзьям — ты будешь получать 10% от всех их пополнений на свой баланс."
    )


@router.callback_query(F.data == "referral_link")
async def referral_link_button(callback: CallbackQuery):
    """
    Обработка нажатия на кнопку 'Реферальная ссылка' в главном меню.
    """
    await callback.answer()

    me = await callback.bot.get_me()
    bot_username = me.username

    if not bot_username:
        await callback.message.edit_text(
            "Не удалось получить username бота. Обратись к администратору."
        )
        return

    link = f"https://t.me/{bot_username}?start={callback.from_user.id}"

    await callback.message.edit_text(
        "Вот твоя реферальная ссылка:\n"
        f"{link}\n\n"
        "Отправь её друзьям — ты будешь получать 10% от всех их пополнений на свой баланс.", reply_markup=back_to_main_menu_keyboard()
    )
