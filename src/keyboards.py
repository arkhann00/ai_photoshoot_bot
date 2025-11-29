from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def get_start_keyboard() -> InlineKeyboardMarkup:

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать фотосессию ✨", callback_data="make_photo")],
            [InlineKeyboardButton(text="Баланс", callback_data="balance"), InlineKeyboardButton(text="Поддержка", callback_data="support")],
        ],
        resize_keyboard=True,
    )


def get_photoshoot_entry_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Перейти к альбому 📖")],
        ],
        resize_keyboard=True,
    )


def get_styles_keyboard() -> InlineKeyboardMarkup:
    left_inline_button = InlineKeyboardButton(
        text="⬅️",
        callback_data="previous",
    )
    right_inline_button = InlineKeyboardButton(
        text="➡️",
        callback_data="next",
    )
    make_photoshoot_button = InlineKeyboardButton(
        text="Сделать такую же",
        callback_data="make_photoshoot",
    )
    back_button = InlineKeyboardButton(
        text="« Назад",
        callback_data="back_to_main_menu",  # у тебя уже есть такой хендлер
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
    return InlineKeyboardMarkup(
        inline_keyboard=[
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
    back_inline_button = InlineKeyboardButton(
        text="« Назад к альбому",
        callback_data="back_to_album",
    )
    inline_keyboard_markup = InlineKeyboardMarkup(
        inline_keyboard=[[back_inline_button]],
    )
    return inline_keyboard_markup
