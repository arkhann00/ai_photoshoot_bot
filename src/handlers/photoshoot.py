# src/handlers/photoshoot.py

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
)

from states import MainStates
from data.styles import styles, PHOTOSHOOT_PRICE
from keyboards import (
    get_styles_keyboard,
    get_balance_keyboard,
    get_after_photoshoot_keyboard,
    get_back_to_album_keyboard,
    get_start_keyboard,
)
from services.photoshoot import generate_photoshoot_image
from db import charge_photoshoot


router = Router()


@router.message(F.text == "Перейти к альбому 📖")
async def get_album(message: Message, state: FSMContext):
    await state.set_state(MainStates.making_photoshoot)

    current_style = 0
    style = styles[current_style]

    await state.update_data(current_style=current_style)

    inline_keyboard_markup = get_styles_keyboard()

    await message.answer_photo(
        photo=FSInputFile(f"../img/{style['img']}"),
        caption=f"<b>{style['title']}</b>\n\n<i>{style['description']}</i>",
        reply_markup=inline_keyboard_markup,
    )


@router.callback_query(F.data == "next")
async def next_style(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_style = data.get("current_style", 0)

    current_style = (current_style + 1) % len(styles)
    await state.update_data(current_style=current_style)

    style = styles[current_style]
    inline_keyboard_markup = get_styles_keyboard()

    await callback.answer()
    await callback.message.edit_media(
        media=InputMediaPhoto(
            media=FSInputFile(f"../img/{style['img']}"),
            caption=f"<b>{style['title']}</b>\n\n<i>{style['description']}</i>",
        ),
        reply_markup=inline_keyboard_markup,
    )


@router.callback_query(F.data == "previous")
async def previous_style(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_style = data.get("current_style", 0)

    current_style = (current_style - 1) % len(styles)
    await state.update_data(current_style=current_style)

    style = styles[current_style]
    inline_keyboard_markup = get_styles_keyboard()

    await callback.answer()
    await callback.message.edit_media(
        media=InputMediaPhoto(
            media=FSInputFile(f"../img/{style['img']}"),
            caption=f"<b>{style['title']}</b>\n\n<i>{style['description']}</i>",
        ),
        reply_markup=inline_keyboard_markup,
    )


@router.callback_query(F.data == "make_photoshoot")
async def make_photoshoot_callback(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_style = data.get("current_style", 0)
    style = styles[current_style]

    await state.update_data(
        current_style=current_style,
        current_style_title=style["title"],
    )
    await state.set_state(MainStates.making_photoshoot_process)

    text = (
        f"Отлично! Выбран стиль «{style['title']}»\n\n"
        "Теперь пришли своё селфи:\n"
        "— лицо прямо,\n"
        "— хорошее освещение,\n"
        "— без фильтров и очков.\n\n"
        "Чем лучше фото — тем круче получится результат ✨"
    )

    await callback.answer()
    await callback.message.answer(text, reply_markup=get_back_to_album_keyboard())


@router.callback_query(F.data == "back_to_album")
async def back_to_album(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_style = data.get("current_style", 0)
    style = styles[current_style]

    inline_keyboard_markup = get_styles_keyboard()

    await state.set_state(MainStates.making_photoshoot)

    await callback.answer()
    await callback.message.answer_photo(
        photo=FSInputFile(f"../img/{style['img']}"),
        caption=f"<b>{style['title']}</b>\n\n<i>{style['description']}</i>",
        reply_markup=inline_keyboard_markup,
    )


@router.message(MainStates.making_photoshoot_process, F.photo)
async def handle_selfie(message: Message, state: FSMContext):
    data = await state.get_data()
    style_title = data.get("current_style_title", "выбранный стиль")

    user_photo = message.photo[-1]
    user_photo_file_id = user_photo.file_id

    await state.update_data(user_photo_file_id=user_photo_file_id)

    # 1. Проверяем и списываем баланс
    can_charge = await charge_photoshoot(
        telegram_id=message.from_user.id,
        price=PHOTOSHOOT_PRICE,
    )

    if not can_charge:
        await state.set_state(MainStates.making_photoshoot_failed)
        text = (
            "Недостаточно средств на балансе.\n"
            f"Стоимость одной фотосессии — <b>{PHOTOSHOOT_PRICE} ₽</b>.\n\n"
            "Пополнить баланс прямо сейчас?"
        )
        await message.answer(text, reply_markup=get_balance_keyboard())
        return

    await state.set_state(MainStates.making_photoshoot_success)

    # 2. Сообщаем о начале генерации
    await message.answer(
        f"Готовлю твою фотосессию в стиле «{style_title}»… ⏳\n"
        "Обычно это занимает 15–30 секунд.",
    )

    # 3. Показываем «загрузку» через chat action
    await message.bot.send_chat_action(
        chat_id=message.chat.id,
        action="upload_photo",
    )

    # 4. Вызываем Gemini с отловом ошибок
    try:
        generated_photo = await generate_photoshoot_image(
            style_title=style_title,
            user_photo_file_id=user_photo_file_id,
            bot=message.bot,
        )
    except Exception as e:
        # Логика на случай падения Gemini
        await state.set_state(MainStates.making_photoshoot_failed)
        await message.answer(
            "Упс… Что-то пошло не так при генерации фото 😔\n"
            "Сервис обработки временно недоступен.\n"
            "Попробуй, пожалуйста, ещё раз чуть позже.",
        )
        return

    # 5. Отправляем результат
    await message.answer_photo(
        photo=generated_photo,
        caption="Готово! Вот твоё фото в 4K качестве ✨",
    )

    await message.answer(
        "Создать ещё одну фотосессию?",
        reply_markup=get_after_photoshoot_keyboard(),
    )

    await state.set_state(MainStates.making_photoshoot_success)


@router.message(MainStates.making_photoshoot_process)
async def handle_not_photo(message: Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, пришли именно <b>фото</b> (селфи), "
        "не документ, не видео, не текст 🙏"
    )


@router.callback_query(F.data == "topup_balance")
async def topup_balance(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.answer(
        "Здесь позже появится экран пополнения баланса.\n"
        "Сейчас это техническое сообщение.",
    )


@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MainStates.start)
    await callback.answer()
    await callback.message.answer(
        "Возвращаю в главное меню. Выбери действие:",
        reply_markup=get_start_keyboard(),
    )


@router.callback_query(F.data == "create_another_photoshoot")
async def create_another_photoshoot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await get_album(callback.message, state)
