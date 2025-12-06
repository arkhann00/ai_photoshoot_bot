# src/keyboards.py

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

def get_start_keyboard() -> InlineKeyboardMarkup:
    """
    Главная клавиатура (inline) с кнопками:
    - Создать фотосессию
    - Баланс
    - Поддержка
    - Реферальная ссылка
    - Личный кабинет
    """
    make_photoshoot_button = InlineKeyboardButton(
        text="Создать фотосессию ✨",
        callback_data="make_photo",
    )
    balance_button = InlineKeyboardButton(
        text="Баланс",
        callback_data="balance",
    )
    support_button = InlineKeyboardButton(
        text="Поддержка",
        callback_data="support",
    )
    referral_button = InlineKeyboardButton(
        text="Реферальная ссылка",
        callback_data="referral_link",
    )
    cabinet_button = InlineKeyboardButton(
        text="👤 Личный кабинет",
        callback_data="personal_cabinet",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [make_photoshoot_button],
            [balance_button, support_button],
            [referral_button, cabinet_button],
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
        keyboard=[
            [KeyboardButton(text="Перейти к альбому 📖")],
        ],
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

    inline_keyboard_markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [left_inline_button, right_inline_button],
            [make_photoshoot_button],
            [back_button],
        ]
    )
    return inline_keyboard_markup



def get_balance_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура под экраном Баланса:
    - Пополнить баланс
    - Вернуться в главное меню
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить баланс",
                    callback_data="topup_balance",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Вернуться в главное меню",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )


def get_after_photoshoot_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура после успешной фотосессии:
    - Сделать это фото аватаром
    - Создать ещё одну фотосессию
    - Вернуться в главное меню
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сделать это фото аватаром",
                    callback_data="make_avatar",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Создать ещё одну фотосессию",
                    callback_data="create_another_photoshoot",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Вернуться в главное меню",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )

def get_back_to_album_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопка "Назад к альбому".
    """
    back_inline_button = InlineKeyboardButton(
        text="« Назад к альбому",
        callback_data="back_to_album",
    )
    inline_keyboard_markup = InlineKeyboardMarkup(
        inline_keyboard=[[back_inline_button]],
    )
    return inline_keyboard_markup

from src.db import StyleCategory

def get_gender_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👩 Женский",
                    callback_data="gender_female",
                )
            ],
            [
                InlineKeyboardButton(
                    text="👨 Мужской",
                    callback_data="gender_male",
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )

def get_categories_carousel_keyboard() -> InlineKeyboardMarkup:
    left_button = InlineKeyboardButton(
        text="⬅️",
        callback_data="cat_previous",
    )
    right_button = InlineKeyboardButton(
        text="➡️",
        callback_data="cat_next",
    )
    select_button = InlineKeyboardButton(
        text="Выбрать категорию",
        callback_data="cat_select",
    )
    back_button = InlineKeyboardButton(
        text="« Назад",
        callback_data="back_to_gender",
    )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [left_button, right_button],
            [select_button],
            [back_button],
        ]
    )


def get_categories_keyboard(categories: list[StyleCategory]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for cat in categories:
        rows.append(
            [
                InlineKeyboardButton(
                    text=cat.title,
                    callback_data=f"style_category:{cat.id}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="« Назад",
                callback_data="make_photo",  # вернёмся к выбору пола
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)
