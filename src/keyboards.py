from __future__ import annotations

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton, WebAppInfo,
)

from src.config import settings
from src.db import StyleCategory

CHANNEL_USERNAME = "photo_ai_studio"
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME}"


def _get_webapp_url() -> str:
    # берём из settings, если есть, иначе дефолт
    return getattr(settings, "WEBAPP_URL", None) or "https://aiphotostudio.ru/"


def get_start_keyboard() -> InlineKeyboardMarkup:
    """
    Главная клавиатура (inline) с кнопками:
    - Создать фотосессию (переход на сайт)
    - Баланс
    - Поддержка
    - Реферальная ссылка
    - Личный кабинет
    """
    web_url = _get_webapp_url()

    make_photoshoot_button = InlineKeyboardButton(
        text="Создать фотосессию ✨",
        web_app=WebAppInfo(url=web_url),  # ВАЖНО: обычный переход на сайт, НЕ WebAppInfo
    )
    balance_button = InlineKeyboardButton(
        text="Баланс 💵",
        callback_data="balance",
    )
    support_button = InlineKeyboardButton(
        text="Поддержка 🤝",
        callback_data="support",
    )
    referral_button = InlineKeyboardButton(
        text="Пригласи друга - заработай 💸",
        callback_data="referral_link",
    )
    cabinet_button = InlineKeyboardButton(
        text="Личный кабинет 👤",
        callback_data="personal_cabinet",
    )

    promo_button = InlineKeyboardButton(
        text="Промокод 🔤",
        callback_data="promo_code",
    )
    
    chanal_link = InlineKeyboardButton (
        text="Наш канал 🔥",
        url=CHANNEL_URL,
    )
    
    usage_terms_button = InlineKeyboardButton (
        text="Условия пользования 📄",
        callback_data="usage_terms"
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_photoshoot_button],
            [balance_button],
            [support_button],
            [referral_button],
            [cabinet_button],
            [chanal_link],
            [usage_terms_button]
        ],
    )


def back_to_main_menu_keyboard() -> InlineKeyboardMarkup:
    back_button = InlineKeyboardButton(
        text="« Назад",
        callback_data="back_to_main_menu",
    )
    return InlineKeyboardMarkup(inline_keyboard=[[back_button]])


def get_photoshoot_entry_keyboard() -> ReplyKeyboardMarkup:
    """
    Клавиатура для входа в альбом (reply-клавиатура).
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Перейти к альбому 📖")]],
        resize_keyboard=True,
    )


def get_styles_keyboard() -> InlineKeyboardMarkup:
    left_inline_button = InlineKeyboardButton(
        text="⬅️",
        callback_data="style_previous",
    )
    right_inline_button = InlineKeyboardButton(
        text="➡️",
        callback_data="style_next",
    )
    make_photoshoot_button = InlineKeyboardButton(
        text="Сделать такую же",
        callback_data="make_photoshoot",
    )
    back_button = InlineKeyboardButton(
        text="« Назад к категориям",
        callback_data="back_to_categories_carousel",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [left_inline_button, right_inline_button],
            [make_photoshoot_button],
            [back_button],
        ]
    )


def get_balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пополнить баланс", callback_data="topup_balance")],
            [InlineKeyboardButton(text="Вернуться в главное меню", callback_data="back_to_main_menu")],
        ]
    )


def get_after_photoshoot_keyboard() -> InlineKeyboardMarkup:
    web_url = _get_webapp_url()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать ещё одну фотосессию", web_app=WebAppInfo(url=web_url))],
            [InlineKeyboardButton(text="Вернуться в главное меню", callback_data="back_to_main_menu")],
        ]
    )


def get_back_to_album_keyboard() -> InlineKeyboardMarkup:
    web_url = _get_webapp_url()
    back_inline_button = InlineKeyboardButton(
        text="« Назад к альбому",
        web_app=WebAppInfo(url=web_url),
    )
    return InlineKeyboardMarkup(inline_keyboard=[[back_inline_button]])


def get_gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👨 Мужской", callback_data="gender_male")],
            [InlineKeyboardButton(text="👩 Женский", callback_data="gender_female")],
            [InlineKeyboardButton(text="« Назад", callback_data="back_to_main_menu")],
        ]
    )


def get_categories_carousel_keyboard() -> InlineKeyboardMarkup:
    left_button = InlineKeyboardButton(text="⬅️", callback_data="cat_previous")
    right_button = InlineKeyboardButton(text="➡️", callback_data="cat_next")
    select_button = InlineKeyboardButton(text="Выбрать категорию", callback_data="cat_select")
    back_button = InlineKeyboardButton(text="« Назад", callback_data="back_to_gender")

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [left_button, right_button],
            [select_button],
            [back_button],
        ]
    )


def get_error_generating_keyboard() -> InlineKeyboardMarkup:
    web_url = _get_webapp_url()
    choose_gender = InlineKeyboardButton(text="Попробовать ещё раз", web_app=WebAppInfo(url=web_url))
    main_menu = InlineKeyboardButton(text="Главное меню", callback_data="back_to_main_menu")
    return InlineKeyboardMarkup(inline_keyboard=[[choose_gender], [main_menu]])


def get_categories_keyboard(categories: list[StyleCategory]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for cat in categories:
        rows.append(
            [InlineKeyboardButton(text=cat.title, callback_data=f"style_category:{cat.id}")]
        )

    rows.append([InlineKeyboardButton(text="« Назад", callback_data="make_photo")])

    return InlineKeyboardMarkup(inline_keyboard=rows)

def get_avatar_choice_keyboard(has_avatar: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if has_avatar:
        rows.append(
            [
                InlineKeyboardButton(
                    text="✅ Использовать аватар",
                    callback_data="use_avatar",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="📷 Загрузить новое фото",
                callback_data="upload_new_photo",
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="« Назад к стилям",
                callback_data="back_to_main_menu",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)
