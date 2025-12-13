from __future__ import annotations

from typing import Optional

from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from sqlalchemy import select, func

from src.config import settings
from src.db import (
    get_or_create_user,
    get_user_by_telegram_id,
    get_style_prompt_by_id,
    async_session,
    User, get_user_avatar,
)
from src.states import MainStates
from src.keyboards import get_start_keyboard, back_to_main_menu_keyboard, get_avatar_choice_keyboard

router = Router()

ADM_GROUP_ID = -5075627878


def _get_webapp_url() -> str:
    return getattr(settings, "WEBAPP_URL", None) or "http://62.113.42.113:5111"


async def send_admin_log(bot, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=ADM_GROUP_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        return


async def get_referrals_count(referrer_telegram_id: int) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(func.count()).select_from(User).where(
                User.referrer_id == referrer_telegram_id
            )
        )
        return int(result.scalar_one_or_none() or 0)


def get_referral_partner_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💸 Запросить вывод средств", callback_data="referral_withdraw_request")],
            [InlineKeyboardButton(text="↔️ Перевести на баланс", callback_data="referral_transfer_to_balance")],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_to_main_menu")],
        ]
    )


def get_open_site_keyboard() -> InlineKeyboardMarkup:
    """
    Нужна только для кейсов, когда стиль не найден/выключен и надо отправить юзера на сайт.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🌐 Открыть каталог стилей", url=_get_webapp_url())],
            [InlineKeyboardButton(text="⬅️ Главное меню", callback_data="back_to_main_menu")],
        ]
    )


def _parse_start_payload(payload: str) -> tuple[Optional[int], Optional[int]]:
    """
    Возвращает (referrer_id, style_id_for_generation)

    Поддержка:
    - /start 123456789          -> referrer_id
    - /start webstyle_12        -> style_id
    - /start gen_12             -> style_id (на всякий случай)
    - /start gen:12             -> style_id (на всякий случай)
    - /start style_12           -> style_id (на всякий случай)
    """
    payload = (payload or "").strip()
    if not payload:
        return None, None

    if payload.startswith("webstyle_"):
        rest = payload[len("webstyle_"):]
        if rest.isdigit():
            return None, int(rest)

    if payload.startswith("gen_"):
        rest = payload[4:]
        if rest.isdigit():
            return None, int(rest)

    if payload.startswith("gen:"):
        rest = payload[4:]
        if rest.isdigit():
            return None, int(rest)

    if payload.startswith("style_"):
        rest = payload[6:]
        if rest.isdigit():
            return None, int(rest)

    if payload.isdigit():
        return int(payload), None

    return None, None

async def _enter_photoshoot_waiting_photo(
    message: Message,
    state: FSMContext,
    style_id: int,
) -> None:
    style = await get_style_prompt_by_id(style_id)
    if style is None or not getattr(style, "is_active", True):
        await state.set_state(MainStates.start)
        await message.answer(
            "Этот стиль не найден или выключен 😔\n\nОткрой каталог и выбери другой стиль.",
            reply_markup=get_open_site_keyboard(),
        )
        return

    # важно: чистим состояние и кладём текущий стиль
    await state.clear()
    await state.update_data(
        current_style_id=style.id,
        current_style_title=style.title,
        current_style_prompt=style.prompt,
        entry_source="website_deeplink",
    )

    # вместо прямого ожидания фото — показываем выбор аватара
    avatar = await get_user_avatar(message.from_user.id)
    await state.set_state(MainStates.choose_avatar_input)

    if avatar is None:
        text = (
            f"Выбран стиль «{style.title}» ✅\n\n"
            "У тебя пока нет аватара.\n"
            "Пришли фото — я сохраню его как твой аватар и буду использовать дальше."
        )
        await message.answer(
            text,
            reply_markup=get_avatar_choice_keyboard(has_avatar=False),
        )
    else:
        text = (
            f"Выбран стиль «{style.title}» ✅\n\n"
            "Как будем генерировать?\n"
            "— использовать твой текущий аватар\n"
            "— или загрузить новое фото (после генерации оно станет новым аватаром)"
        )
        await message.answer(
            text,
            reply_markup=get_avatar_choice_keyboard(has_avatar=True),
        )

    username = message.from_user.username or "—"
    await send_admin_log(
        message.bot,
        (
            "🌐 <b>Старт генерации с сайта</b>\n"
            f"Пользователь: <code>{message.from_user.id}</code> @{username}\n"
            f"Style ID: <code>{style.id}</code>\n"
            f"Style title: <b>{style.title}</b>\n"
            f"Аватар: {'есть' if avatar is not None else 'нет'}"
        ),
    )


@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext):
    bot = message.bot

    payload: Optional[str] = None
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            payload = parts[1]

    referrer_telegram_id, style_id_for_generation = _parse_start_payload(payload or "")

    if referrer_telegram_id == message.from_user.id:
        referrer_telegram_id = None

    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        referrer_telegram_id=referrer_telegram_id,
    )

    # Если пришёл с сайта с выбранным стилем — сразу ждём фото
    if style_id_for_generation is not None:
        await _enter_photoshoot_waiting_photo(message, state, style_id_for_generation)
        return

    # Обычный старт: ТОЛЬКО стартовый текст + стартовая клавиатура
    await state.set_state(MainStates.start)

    await message.answer(
        """📸 Добро пожаловать в Ai Photo-Studio!

Здесь твои снимки обретают новую жизнь — я превращу любую фотографию в стильный, выразительный и по-настоящему уникальный визуальный образ.

Нажми «Создать фотосессию ✨» и выбери стиль на сайте 😉""",
        reply_markup=get_start_keyboard(),
    )

    # Лог в админский чат, если рефералка
    if referrer_telegram_id is not None:
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
    me = await message.bot.get_me()
    bot_username = me.username

    if not bot_username:
        await message.answer("Не удалось получить username бота. Обратись к администратору.")
        return

    link = f"https://t.me/{bot_username}?start={message.from_user.id}"

    user = await get_user_by_telegram_id(message.from_user.id)
    is_referral_partner = bool(getattr(user, "is_referral", False))

    if not is_referral_partner:
        await message.answer(
            "Вот твоя реферальная ссылка:\n"
            f"{link}\n\n"
            "Отправь её друзьям — за каждую их успешную фотосессию "
            "ты будешь получать <b>5 ₽</b> на свой баланс."
        )
        return

    referrals_count = await get_referrals_count(user.telegram_id)
    referral_balance = int(getattr(user, "referral_earned_rub", 0))

    text = (
        "Вот твоя реферальная ссылка:\n"
        f"{link}\n\n"
        "Отправь её друзьям — за каждую их успешную фотосессию "
        "ты будешь получать <b>5 ₽</b> на свой баланс.\n\n"
        f"Количество рефералов: <b>{referrals_count}</b>\n"
        f"Ваш реферальный баланс: <b>{referral_balance} ₽</b>"
    )

    await message.answer(text, reply_markup=get_referral_partner_keyboard())


@router.callback_query(F.data == "referral_link")
async def referral_link_button(callback: CallbackQuery):
    await callback.answer()

    me = await callback.bot.get_me()
    bot_username = me.username

    if not bot_username:
        await callback.message.edit_text("Не удалось получить username бота. Обратись к администратору.")
        return

    link = f"https://t.me/{bot_username}?start={callback.from_user.id}"

    user = await get_user_by_telegram_id(callback.from_user.id)
    is_referral_partner = bool(getattr(user, "is_referral", False))

    if not is_referral_partner:
        await callback.message.edit_text(
            "Вот твоя реферальная ссылка:\n"
            f"{link}\n\n"
            "Отправь её друзьям — за каждую их успешную фотосессию "
            "ты будешь получать <b>5 ₽</b> на свой баланс.",
            reply_markup=back_to_main_menu_keyboard(),
        )
        return

    referrals_count = await get_referrals_count(user.telegram_id)
    referral_balance = int(getattr(user, "referral_earned_rub", 0))

    text = (
        "Вот твоя реферальная ссылка:\n"
        f"{link}\n\n"
        "Отправь её друзьям — за каждую их успешную фотосессию "
        "ты будешь получать <b>5 ₽</b> на свой баланс.\n\n"
        f"Количество рефералов: <b>{referrals_count}</b>\n"
        f"Ваш реферальный баланс: <b>{referral_balance} ₽</b>"
    )

    await callback.message.edit_text(text, reply_markup=get_referral_partner_keyboard())


@router.callback_query(F.data == "referral_transfer_to_balance")
async def referral_transfer_to_balance(callback: CallbackQuery):
    await callback.answer()

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == callback.from_user.id)
        )
        user: User | None = result.scalar_one_or_none()

        if user is None:
            await callback.message.answer("Не удалось найти твой профиль. Обратись к администратору.")
            return

        if not getattr(user, "is_referral", False):
            await callback.message.answer("Эта функция доступна только для реферальных партнёров.")
            return

        amount = int(getattr(user, "referral_earned_rub", 0) or 0)
        if amount <= 0:
            await callback.message.answer("У тебя пока нет средств для перевода на баланс.")
            return

        user.balance = int(user.balance or 0) + amount
        user.referral_earned_rub = 0
        await session.commit()
        new_balance = int(user.balance or 0)

    await callback.message.answer(
        f"✅ {amount} ₽ перенесены с реферального баланса на основной.\n"
        f"Текущий баланс: {new_balance} ₽."
    )


@router.callback_query(F.data == "referral_withdraw_request")
async def referral_withdraw_request(callback: CallbackQuery):
    await callback.answer()

    user = await get_user_by_telegram_id(callback.from_user.id)
    if not getattr(user, "is_referral", False):
        await callback.message.answer("Запрос на вывод доступен только для реферальных партнёров.")
        return

    referrals_count = await get_referrals_count(user.telegram_id)
    referral_balance = int(getattr(user, "referral_earned_rub", 0))
    username = callback.from_user.username or "—"
    full_name = callback.from_user.full_name or "—"

    admin_text = (
        "📤 <b>Запрос на вывод реферальных средств</b>\n"
        f"Пользователь: <code>{user.telegram_id}</code> @{username}\n"
        f"Имя в Telegram: {full_name}\n"
        f"Количество рефералов: <b>{referrals_count}</b>\n"
        f"Реферальный баланс: <b>{referral_balance} ₽</b>\n"
        f"Текущий баланс в боте: <b>{int(user.balance or 0)} ₽</b>\n\n"
        "Пользователь запросил вывод реферальных средств в реальные деньги."
    )

    await send_admin_log(callback.bot, admin_text)

    await callback.message.answer(
        "Твой запрос на вывод реферальных средств отправлен администратору.\n"
        "С тобой свяжутся, как только его обработают.",
        reply_markup=back_to_main_menu_keyboard(),
    )


@router.message(F.chat.type.in_({"group", "supergroup"}), F.text == "/chat_id")
async def show_group_id(message: Message):
    await message.answer(f"ID этого чата: {message.chat.id}")
