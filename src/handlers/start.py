# src/handlers/start.py

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from sqlalchemy import select, func  # для подсчёта рефералов

from src.db import (
    get_or_create_user,
    get_user_by_telegram_id,
    async_session,
    User,
)
from src.states import MainStates
from src.keyboards import get_start_keyboard, back_to_main_menu_keyboard

router = Router()

ADM_GROUP_ID = -5075627878


async def send_admin_log(bot, text: str) -> None:
    """
    Отправка красиво оформленного лога в админский чат.
    Не роняет бота, если чат недоступен.
    """
    try:
        await bot.send_message(
            chat_id=ADM_GROUP_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        # Логирование не должно ломать основной поток
        return


async def get_referrals_count(referrer_telegram_id: int) -> int:
    """
    Считает, сколько пользователей в БД имеют referrer_id = referrer_telegram_id.
    """
    async with async_session() as session:
        result = await session.execute(
            select(func.count()).select_from(User).where(
                User.referrer_id == referrer_telegram_id
            )
        )
        return int(result.scalar_one_or_none() or 0)


@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext):
    bot = message.bot

    # Пытаемся вытащить реферальный ID из /start payload
    # /start <referrer_telegram_id>
    referrer_telegram_id: int | None = None

    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            payload = parts[1]
            if payload.isdigit():
                possible_ref_id = int(payload)
                # Не даём юзеру быть своим же реферером
                if possible_ref_id != message.from_user.id:
                    referrer_telegram_id = possible_ref_id

    # создаём/обновляем пользователя в БД
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        referrer_telegram_id=referrer_telegram_id,
    )

    await state.set_state(MainStates.start)

    await message.answer(
        """📸 Добро пожаловать в Ai Photo-Studio!
        \n\nЗдесь твои снимки обретают новую жизнь — я превращу любую фотографию в стильный, выразительный и по-настоящему уникальный визуальный образ. 
        \n\nВыбирай категорию и смело начинай — создадим что-то впечатляющее 😉""",
        reply_markup=get_start_keyboard(),
    )

    # Если пользователь пришёл по реферальной ссылке — шлём лог в админ-группу
    if referrer_telegram_id is not None:
        # Получаем инфу о реферере (создаст запись, если её ещё нет)
        referrer_user = await get_user_by_telegram_id(referrer_telegram_id)

        referred_count = await get_referrals_count(referrer_telegram_id)

        new_user_id = user.telegram_id
        new_username = message.from_user.username or "—"

        ref_username = referrer_user.username or "—"

        await send_admin_log(
            bot,
            (
                "👥 <b>Новый переход по реферальной ссылке</b>\n"
                f"Новый пользователь: <code>{new_user_id}</code> @{new_username}\n"
                f"Пригласитель: <code>{referrer_telegram_id}</code> @{ref_username}\n"
                f"Всего рефералов у пригласителя: <b>{referred_count}</b>"
            ),
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
        "Отправь её друзьям — за каждую их успешную фотосессию "
        "ты будешь получать <b>5 ₽</b> на свой баланс."
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
        "Отправь её друзьям — за каждую их успешную фотосессию "
        "ты будешь получать <b>5 ₽</b> на свой баланс.",
        reply_markup=back_to_main_menu_keyboard(),
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text == "/chat_id")
async def show_group_id(message: Message):
    chat_id = message.chat.id
    await message.answer(f"ID этого чата: {chat_id}")
