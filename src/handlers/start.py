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
    User,
    get_user_avatar,
)
from src.db.repositories.users import add_photoshoot_topups
from src.states import MainStates
from src.keyboards import (
    get_start_keyboard,
    back_to_main_menu_keyboard,
    get_avatar_choice_keyboard,
)
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from src.db.repositories.users import (
    ensure_user_is_referral,
    grant_referral_click_bonus_if_needed,
)
router = Router()

ADM_GROUP_ID = -5075627878

CHANNEL_USERNAME = "photo_ai_studio"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram import Bot

async def notify_referrer_about_click(
    bot: Bot,
    *,
    referrer_id: int,
    new_user_id: int,
    new_username: str,
    reward_rub: int,
) -> None:
    try:
        u = (new_username or "—").strip()
        if u and not u.startswith("@") and u != "—":
            u = f"@{u}"
        if u == "@—":
            u = "—"

        text = (
            "👥 По твоей реферальной ссылке пришёл новый пользователь!\n\n"
            f"Друг: <code>{new_user_id}</code> {u}\n"
            f"Бонус за переход: <b>+{reward_rub} ₽</b> ✅"
        )

        await bot.send_message(
            chat_id=referrer_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except (TelegramForbiddenError, TelegramBadRequest):
        return
    except Exception:
        return
        
from typing import Optional
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

async def _notify_referrer_new_referral(
    bot: Bot,
    *,
    referrer_id: int,
    new_user_id: int,
    new_username: str,
) -> None:
    try:
        u = (new_username or "—").strip()
        if u and not u.startswith("@") and u != "—":
            u = f"@{u}"
        if u == "@—":
            u = "—"

        text = (
            "👥 У тебя новый реферал!\n\n"
            f"Пользователь: <code>{new_user_id}</code> {u}"
        )

        await bot.send_message(
            chat_id=referrer_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except (TelegramForbiddenError, TelegramBadRequest):
        return
    except Exception:
        return

def _get_webapp_url() -> str:
    return getattr(settings, "WEBAPP_URL", None) or "https://aiphotostudio.ru/"


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
    
def _format_referral_screen_text(*, link: str, referrals_count: int, earned_rub: int) -> str:
    return (
        "💰 <b>Зарабатывай с Ai Photo-Studio</b>\n\n"
        "Хочешь получать деньги просто за то, что рассказываешь о нашем сервисе?\n\n"
        "Теперь ты можешь стать нашим амбассадором 🤝\n\n"
        "<b>Делись своей ссылкой</b> с друзьями или снимай рилсы, выкладывай посты и сторис с отметкой 🎥\n\n"
        "Когда кто-то по твоей ссылке купит тариф — ты получишь <b>10%</b> от оплаты.\n\n"
        "<b>Выплаты от 1000₽!</b>\n\n"
        f"👥 Приглашено пользователей: <b>{int(referrals_count)}</b>\n"
        f"💳 Заработано: <b>{int(earned_rub)} ₽</b>\n\n"
        "🔗 <b>Ваша реферальная ссылка:</b>\n"
        f"<code>{link}</code>\n\n"
        "Отправляй её друзьям, в чаты, сторис или канал — и получай доход."
    )


async def get_referrals_count(referrer_telegram_id: int) -> int:
    async with async_session() as session:
        result = await session.execute(
            select(func.count()).select_from(User).where(
                User.referrer_id == referrer_telegram_id
            )
        )
        return int(result.scalar_one_or_none() or 0)

async def _get_existing_referrer_id(telegram_id: int) -> Optional[int]:
    async with async_session() as session:
        res = await session.execute(
            select(User.referrer_id).where(User.telegram_id == telegram_id)
        )
        return res.scalar_one_or_none()

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


def get_subscribe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔔 Открыть канал", url=CHANNEL_URL)],
            [InlineKeyboardButton(text="✅ Я подписался — проверить", callback_data="check_sub")],
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


async def _send_avatar_choice_prompt(
    message: Message,
    *,
    avatar,
    text: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    """
    Если аватар существует — отправляем его как фото с caption + кнопками.
    Если аватара нет — отправляем обычный текст с кнопками.
    """
    if avatar is not None and getattr(avatar, "file_id", None):
        await message.answer_photo(
            photo=avatar.file_id,
            caption=text,
            reply_markup=keyboard,
        )
        return

    await message.answer(
        text,
        reply_markup=keyboard,
    )


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
        keyboard = get_avatar_choice_keyboard(has_avatar=False)
        await _send_avatar_choice_prompt(
            message,
            avatar=None,
            text=text,
            keyboard=keyboard,
        )
    else:
        text = (
            f"Выбран стиль «{style.title}» ✅\n\n"
            "Как будем генерировать?\n"
            "— использовать твой текущий аватар\n"
            "— или загрузить новое фото (после генерации оно станет новым аватаром)"
        )
        keyboard = get_avatar_choice_keyboard(has_avatar=True)
        await _send_avatar_choice_prompt(
            message,
            avatar=avatar,
            text=text,
            keyboard=keyboard,
        )

    username = message.from_user.username or "—"
    

from src.db.repositories.users import ensure_user_is_referral

@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext):
    bot = message.bot

    payload: Optional[str] = None
    if message.text:
        parts = message.text.split(maxsplit=1)
        if len(parts) == 2:
            payload = parts[1]

    referrer_telegram_id, style_id_for_generation = _parse_start_payload(payload or "")

    # защита от саморефералки
    if referrer_telegram_id == message.from_user.id:
        referrer_telegram_id = None

    # важно: понять, был ли уже закреплён реферер раньше
    existing_referrer_id = await _get_existing_referrer_id(message.from_user.id)

    # создаём/обновляем пользователя + закрепляем referrer_id только если он ещё пустой
    user = await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        referrer_telegram_id=referrer_telegram_id,
    )

    # ---- проверка подписки (как у тебя было) ----
    is_member = False
    try:
        member = await bot.get_chat_member(f"@{CHANNEL_USERNAME}", message.from_user.id)
        if getattr(member, "status", None) in ("creator", "administrator", "member"):
            is_member = True
    except Exception:
        is_member = False

    if not is_member:
        await message.answer(
            f"Чтобы продолжить, подпишитесь на канал @{CHANNEL_USERNAME} и нажмите кнопку 'Я подписался — проверить'.",
            reply_markup=get_subscribe_keyboard(),
        )
        return

    # Если пришёл с сайта с выбранным стилем — показываем выбор аватара/фото
    if style_id_for_generation is not None:
        await _enter_photoshoot_waiting_photo(message, state, style_id_for_generation)
        return

    # Обычный старт
    await state.set_state(MainStates.start)
    await message.answer(
        """📸 Добро пожаловать в Ai Photo-Studio!

Здесь твои снимки обретают новую жизнь — я превращу любую фотографию в стильный, выразительный и по-настоящему уникальный визуальный образ.

Нажми «Создать фотосессию ✨» и выбери стиль на сайте 😉""",
        reply_markup=get_start_keyboard(),
    )

    # ---- РЕФЕРАЛКА: только закрепление + уведомление, без начислений и без логов ----
    # Срабатывает только если:
    # - есть referrer_telegram_id
    # - у пользователя раньше НЕ было referrer_id
    if referrer_telegram_id is not None and existing_referrer_id is None:
        # (опционально) убедимся, что реферер существует в БД
        await get_user_by_telegram_id(referrer_telegram_id)

        # только пригласитель становится is_referral=True
        await ensure_user_is_referral(referrer_telegram_id)

        # уведомление пригласителю в личку
        new_user_id = message.from_user.id
        new_username = message.from_user.username or "—"
        await _notify_referrer_new_referral(
            bot,
            referrer_id=int(referrer_telegram_id),
            new_user_id=int(new_user_id),
            new_username=new_username,
        )

@router.message(Command("ref"))
async def referral_link_command(message: Message):
    me = await message.bot.get_me()
    bot_username = me.username

    if not bot_username:
        await message.answer("Не удалось получить username бота. Обратись к администратору.")
        return

    link = f"https://t.me/{bot_username}?start={message.from_user.id}"

    referrals_count = await get_referrals_count(message.from_user.id)
    user = await get_user_by_telegram_id(message.from_user.id)
    earned_rub = int(getattr(user, "referral_earned_rub", 0) or 0)

    text = _format_referral_screen_text(
        link=link,
        referrals_count=referrals_count,
        earned_rub=earned_rub,
    )

    await message.answer(
        text,
        reply_markup=get_referral_partner_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

@router.callback_query(F.data == "referral_link")
async def referral_link_button(callback: CallbackQuery):
    await callback.answer()

    me = await callback.bot.get_me()
    bot_username = me.username

    if not bot_username:
        await callback.message.edit_text("Не удалось получить username бота. Обратись к администратору.")
        return

    link = f"https://t.me/{bot_username}?start={callback.from_user.id}"

    referrals_count = await get_referrals_count(callback.from_user.id)
    user = await get_user_by_telegram_id(callback.from_user.id)
    earned_rub = int(getattr(user, "referral_earned_rub", 0) or 0)

    text = _format_referral_screen_text(
        link=link,
        referrals_count=referrals_count,
        earned_rub=earned_rub,
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_referral_partner_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

@router.callback_query(F.data == "check_sub")
async def check_subscription(callback: CallbackQuery):
    await callback.answer()

    bot = callback.bot
    is_member = False
    try:
        member = await bot.get_chat_member(f"@{CHANNEL_USERNAME}", callback.from_user.id)
        if getattr(member, "status", None) in ("creator", "administrator", "member"):
            is_member = True
    except Exception:
        is_member = False

    if not is_member:
        await callback.message.answer(
            "Пока не вижу подписки. Подпишись на канал и нажми кнопку снова.",
            reply_markup=get_subscribe_keyboard(),
        )
        return

    # Пользователь подписан — начисляем 2 генерации и отправляем в главное меню
    try:
        await add_photoshoot_topups(callback.from_user.id, 2)
    except Exception:
        # не критично, продолжим без падения
        pass

    await callback.message.answer(
        "Спасибо за подписку! Тебе начислены 2 генерации — добро пожаловать в главное меню.",
        reply_markup=get_start_keyboard(),
    )


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
    

@router.callback_query(F.data == "usage_terms")
async def usage_terms(callback: CallbackQuery):
    
    user_agreement_button = InlineKeyboardButton (
        text="Пользовательское соглашение",
        url="https://docs.google.com/document/d/1CuXqGLTqOWnrSoMjSyQlNJdJUvgqa3ZnOa79wZ-hEYQ/edit?tab=t.0#heading=h.rwknewalurb"
    )
    
    public_offer_button = InlineKeyboardButton (
        text="Публичная оферта",
        url="https://docs.google.com/document/d/1Ga3TLmxNl7pBMN_XN9-W264TKAff0701E_wo5wuYMBg/edit?usp=drivesdk"
    )
    
    processing_policy_button = InlineKeyboardButton (
        text="Политика обработки",
        url="https://docs.google.com/document/d/1TylXB5os57I1wDI3CxL6YxaEaSiR4v1AIiiODvin7Rs/edit?usp=drivesdk"
    )
    
    back_button = InlineKeyboardButton(
        text="« Назад",
        callback_data="back_to_main_menu",
    )
    
    callback.answer()
    callback.message.answer(text="Пользуясь данным сервисом, Вы соглашаетесь:", reply_markup=InlineKeyboardMarkup(
        [[user_agreement_button]],
        [[public_offer_button]],
        [[processing_policy_button]],
        [[back_button]]
    ))

@router.message(F.chat.type.in_({"group", "supergroup"}), F.text == "/chat_id")
async def show_group_id(message: Message):
    await message.answer(f"ID этого чата: {message.chat.id}")

