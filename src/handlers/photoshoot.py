# src/handlers/photoshoot.py

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup,
)
from src.paths import IMG_DIR
from src.states import MainStates
from src.data.styles import styles, PHOTOSHOOT_PRICE
from src.keyboards import (
    get_styles_keyboard,
    get_balance_keyboard,
    get_after_photoshoot_keyboard,
    get_back_to_album_keyboard,
    get_start_keyboard,
)
from src.db import log_photoshoot, PhotoshootStatus
from src.services.photoshoot import generate_photoshoot_image
from src.db import consume_photoshoot_credit_or_balance
from src.db import (get_style_by_offset,
    count_active_styles,)
from src.data.styles import PHOTOSHOOT_PRICE

router = Router()


@router.message(F.text == "Перейти к альбому 📖")
async def get_album(message: Message, state: FSMContext):
    await state.set_state(MainStates.making_photoshoot)

    total = await count_active_styles()
    if total == 0:
        await message.answer(
            "Стили ещё не настроены. Обратись, пожалуйста, к администратору."
        )
        return

    current_index = 0
    style = await get_style_by_offset(current_index)
    if style is None:
        await message.answer(
            "Не удалось загрузить стиль. Попробуй позже или обратись к администратору."
        )
        return

    await state.update_data(current_style_index=current_index)

    inline_keyboard_markup = get_styles_keyboard()

    await message.answer_photo(
        photo=FSInputFile(str(IMG_DIR / style.image_filename)),
        caption=f"<b>{style.title}</b>\n\n<i>{style.description}</i>",
        reply_markup=inline_keyboard_markup,
    )



@router.callback_query(F.data == "next")
async def next_style(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_index = data.get("current_style_index", 0)

    total = await count_active_styles()
    if total == 0:
        await callback.answer("Стили не найдены.")
        return

    # Если только один стиль — листать нечего
    if total == 1:
        await callback.answer("Пока доступен только один стиль 😊", show_alert=False)
        return

    new_index = (current_index + 1) % total
    await state.update_data(current_style_index=new_index)

    style = await get_style_by_offset(new_index)
    if style is None:
        await callback.answer("Не удалось загрузить стиль.")
        return

    inline_keyboard_markup = get_styles_keyboard()

    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(
                media=FSInputFile(str(IMG_DIR / style.image_filename)),
                caption=f"<b>{style.title}</b>\n\n<i>{style.description}</i>",
            ),
            reply_markup=inline_keyboard_markup,
        )
    except TelegramBadRequest as e:
        # Если контент реально не изменился — просто игнорируем
        if "message is not modified" in str(e):
            await callback.answer()
            return
        raise

    await callback.answer()



@router.callback_query(F.data == "previous")
async def previous_style(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_index = data.get("current_style_index", 0)

    total = await count_active_styles()
    if total == 0:
        await callback.answer("Стили не найдены.")
        return

    # Если только один стиль — листать нечего
    if total == 1:
        await callback.answer("Пока доступен только один стиль 😊", show_alert=False)
        return

    new_index = (current_index - 1) % total
    await state.update_data(current_style_index=new_index)

    style = await get_style_by_offset(new_index)
    if style is None:
        await callback.answer("Не удалось загрузить стиль.")
        return

    inline_keyboard_markup = get_styles_keyboard()

    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(
                media=FSInputFile(str(IMG_DIR / style.image_filename)),
                caption=f"<b>{style.title}</b>\n\n<i>{style.description}</i>",
            ),
            reply_markup=inline_keyboard_markup,
        )
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            await callback.answer()
            return
        raise

    await callback.answer()




@router.callback_query(F.data == "make_photoshoot")
async def make_photoshoot(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_index = data.get("current_style_index", 0)

    style = await get_style_by_offset(current_index)
    if style is None:
        await callback.answer("Не удалось загрузить стиль.")
        return

    await state.update_data(
        current_style_index=current_index,
        current_style_title=style.title,
        current_style_prompt=style.prompt,
    )
    await state.set_state(MainStates.making_photoshoot_process)

    back_inline_button = InlineKeyboardButton(text="Назад", callback_data="next")
    inline_keyboard_markup = InlineKeyboardMarkup(
        inline_keyboard=[[back_inline_button]]
    )

    text = (
        f"Отлично! Выбран стиль «{style.title}»\n\n"
        "Теперь пришли своё селфи:\n"
        "— лицо прямо,\n"
        "— хорошее освещение,\n"
        "— без фильтров и очков.\n\n"
        "Чем лучше фото — тем круче получится результат ✨"
    )

    await callback.answer()
    await callback.message.answer(text, reply_markup=inline_keyboard_markup)


@router.callback_query(F.data == "back_to_album")
async def back_to_album(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_style = data.get("current_style", 0)
    style = styles[current_style]

    inline_keyboard_markup = get_styles_keyboard()

    await state.set_state(MainStates.making_photoshoot)

    await callback.answer()
    await callback.message.answer_photo(
        photo=FSInputFile(str(IMG_DIR / style["img"])),
        caption=f"<b>{style['title']}</b>\n\n<i>{style['description']}</i>",
        reply_markup=inline_keyboard_markup,
    )


@router.message(MainStates.making_photoshoot_process, F.photo)
async def handle_selfie(message: Message, state: FSMContext):
    data = await state.get_data()
    style_title = data.get("current_style_title", "выбранный стиль")
    style_prompt = data.get("current_style_prompt")  # новый параметр

    user_photo = message.photo[-1]
    user_photo_file_id = user_photo.file_id

    await state.update_data(user_photo_file_id=user_photo_file_id)

    # списание кредита/баланса как раньше
    can_pay = await consume_photoshoot_credit_or_balance(
        telegram_id=message.from_user.id,
        price_rub=PHOTOSHOOT_PRICE,
    )

    if False:
        await state.set_state(MainStates.making_photoshoot_failed)
        text = (
            "Недостаточно средств для создания фотосессии.\n"
            f"Стоимость одной фотосессии — <b>{PHOTOSHOOT_PRICE} ₽</b> "
            "или заранее оплаченный слот через Stars.\n\n"
            "Пополнить баланс прямо сейчас?"
        )
        await message.answer(text, reply_markup=get_balance_keyboard())
        return

    await state.set_state(MainStates.making_photoshoot_success)

    await message.answer(
        f"Готовлю твою фотосессию в стиле «{style_title}»… ⏳\n"
        "Обычно это занимает 15–30 секунд.",
    )

    await message.bot.send_chat_action(
        chat_id=message.chat.id,
        action="upload_photo",
    )

    try:
        generated_photo = await generate_photoshoot_image(
            style_title=style_title,
            style_prompt=style_prompt,
            user_photo_file_id=user_photo_file_id,
            bot=message.bot,
        )
    except Exception as e:
        # Можно ещё залогировать e, но пользователю даём аккуратное сообщение
        await state.set_state(MainStates.making_photoshoot_failed)
        await message.answer(
            "Упс… Что-то пошло не так при генерации фото 😔\n"
            "Сервис обработки временно недоступен.\n"
            "Попробуй, пожалуйста, ещё раз чуть позже.",
        )
        return

    await message.answer_photo(
        photo=generated_photo,
        caption="Готово! Вот твоё фото в 4K качестве ✨",
    )

    await message.answer(
        "Создать ещё одну фотосессию?",
        reply_markup=get_after_photoshoot_keyboard(),
    )

    await state.set_state(MainStates.making_photoshoot_success)
    try:
        generated_photo = await generate_photoshoot_image(
            style_title=style_title,
            style_prompt=style_prompt,
            user_photo_file_id=user_photo_file_id,
            bot=message.bot,
        )

        # Логируем успешную фотосессию
        await log_photoshoot(
            telegram_id=message.from_user.id,
            style_title=style_title,
            status=PhotoshootStatus.success,
            cost_rub=0,  # пока не списываем деньги
            cost_credits=0,  # и кредиты тоже
            provider="comet_gemini_2_5_flash",
        )

    except Exception as e:
        # Логируем неудачу
        await log_photoshoot(
            telegram_id=message.from_user.id,
            style_title=style_title,
            status=PhotoshootStatus.failed,
            cost_rub=0,
            cost_credits=0,
            provider="comet_gemini_2_5_flash",
            error_message=str(e),
        )

        await state.set_state(MainStates.making_photoshoot_failed)
        await message.answer(
            "Упс… Что-то пошло не так при генерации фото 😔\n"
            "Сервис обработки временно недоступен.\n"
            "Попробуй, пожалуйста, ещё раз чуть позже.",
        )
        return


@router.message(MainStates.making_photoshoot_process)
async def handle_not_photo(message: Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, пришли именно <b>фото</b> (селфи), "
        "не документ, не видео, не текст 🙏"
    )


# @router.callback_query(F.data == "topup_balance")
# async def topup_balance(callback: CallbackQuery, state: FSMContext):
#     await callback.answer()
#     await callback.message.answer(
#         "Здесь позже появится экран пополнения баланса.\n"
#         "Сейчас это техническое сообщение.",
#     )


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
