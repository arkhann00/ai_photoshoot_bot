from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    InputMediaPhoto,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
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
    get_photoshoot_entry_keyboard,
    back_to_main_menu_keyboard,
    get_gender_keyboard,
    get_categories_keyboard,
    get_categories_carousel_keyboard,
)
from src.services.photoshoot import generate_photoshoot_image, logger
from src.services.admins import is_admin

from src.db import (
    log_photoshoot,
    PhotoshootStatus,
    consume_photoshoot_credit_or_balance,
    get_style_by_offset,
    count_active_styles,
    get_user_avatars,
    create_user_avatar,
    MAX_AVATARS_PER_USER,
    get_style_prompt_by_id,
    get_styles_by_category_and_gender,
    StyleGender,
    get_all_style_categories,
    get_style_categories_for_gender,
)

router = Router()


async def _send_photo_with_fallback(
    callback: CallbackQuery,
    image_filename: str,
    caption: str,
    keyboard: InlineKeyboardMarkup,
) -> None:
    """
    Универсальный хелпер:
    - проверяет наличие файла;
    - пробует edit_media;
    - если не вышло — answer_photo;
    - если и это не вышло (IMAGE_PROCESS_FAILED и т.п.) — шлёт текст и не роняет бота.
    """
    image_path = IMG_DIR / image_filename
    logger.info("Пробую отправить изображение: %s", image_path)

    # Проверяем, что файл реально существует
    if not image_path.exists():
        logger.error("Файл картинки не найден: %s", image_path)
        await callback.message.answer(
            "Не удалось найти файл картинки для этого стиля. "
            "Попробуй выбрать другой стиль или обратись к администратору."
        )
        return

    file = FSInputFile(str(image_path))

    try:
        await callback.message.edit_media(
            media=InputMediaPhoto(
                media=file,
                caption=caption,
            ),
            reply_markup=keyboard,
        )
    except TelegramBadRequest as e:
        err_text = str(e)
        # Классический кейс "message is not modified" — просто игнорируем
        if "message is not modified" in err_text:
            logger.debug("message is not modified для %s", image_path)
            return

        logger.warning(
            "edit_media не удался для %s (%s), пробую отправить новое фото",
            image_path,
            err_text,
        )
        try:
            await callback.message.answer_photo(
                photo=file,
                caption=caption,
                reply_markup=keyboard,
            )
        except TelegramBadRequest as e2:
            # Вот здесь как раз всплывает IMAGE_PROCESS_FAILED
            logger.error(
                "answer_photo тоже упал для %s: %s",
                image_path,
                e2,
            )
            await callback.message.answer(
                "Не удалось отправить картинку 😔\n"
                "Похоже, файл повреждён или Telegram не смог его обработать.\n"
                "Попробуй выбрать другой стиль или категорию."
            )


@router.callback_query(F.data == "make_photo")
async def make_photoshoot_entry(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(MainStates.choose_gender)

    await callback.answer()

    await callback.message.edit_text(
        "Кого будем фоткать? 😊\n\nВыбери пол:",
        reply_markup=get_gender_keyboard(),
    )


@router.callback_query(F.data == "gender_female")
async def choose_gender_female(callback: CallbackQuery, state: FSMContext):
    await _handle_gender_choice(callback, state, StyleGender.female)


@router.callback_query(F.data == "gender_male")
async def choose_gender_male(callback: CallbackQuery, state: FSMContext):
    await _handle_gender_choice(callback, state, StyleGender.male)


async def _handle_gender_choice(
    callback: CallbackQuery,
    state: FSMContext,
    gender: StyleGender,
):
    categories = await get_style_categories_for_gender(gender)
    if not categories:
        await callback.message.edit_text(
            "Для этого пола ещё нет категорий стилей.\n"
            "Обратись, пожалуйста, к администратору.",
            reply_markup=get_start_keyboard(),
        )
        await callback.answer()
        return

    category_ids = [c.id for c in categories]
    current_index = 0
    current_category = categories[current_index]

    await state.update_data(
        current_gender=gender.value,
        category_ids=category_ids,
        current_category_index=current_index,
    )
    await state.set_state(MainStates.choose_category)

    keyboard = get_categories_carousel_keyboard()
    caption = (
        f"<b>{current_category.title}</b>\n\n"
        f"<i>{current_category.description}</i>"
    )

    await _send_photo_with_fallback(
        callback=callback,
        image_filename=current_category.image_filename,
        caption=caption,
        keyboard=keyboard,
    )

    await callback.answer()


async def _show_current_category(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category_ids: list[int] = data.get("category_ids") or []
    current_index = data.get("current_category_index", 0)

    if not category_ids:
        await callback.answer("Категории не найдены.")
        return

    from src.db import get_style_category_by_id

    if current_index < 0 or current_index >= len(category_ids):
        current_index = 0

    category_id = category_ids[current_index]
    category = await get_style_category_by_id(category_id)
    if category is None:
        await callback.answer("Не удалось загрузить категорию.")
        return

    await state.update_data(current_category_index=current_index)

    keyboard = get_categories_carousel_keyboard()
    caption = f"<b>{category.title}</b>\n\n<i>{category.description}</i>"

    await _send_photo_with_fallback(
        callback=callback,
        image_filename=category.image_filename,
        caption=caption,
        keyboard=keyboard,
    )

    await callback.answer()


@router.callback_query(F.data == "cat_next")
async def cat_next(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category_ids: list[int] = data.get("category_ids") or []
    current_index = data.get("current_category_index", 0)

    if not category_ids:
        await callback.answer("Категории не найдены.")
        return

    total = len(category_ids)
    new_index = (current_index + 1) % total

    await state.update_data(current_category_index=new_index)
    await _show_current_category(callback, state)


@router.callback_query(F.data == "cat_previous")
async def cat_previous(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    category_ids: list[int] = data.get("category_ids") or []
    current_index = data.get("current_category_index", 0)

    if not category_ids:
        await callback.answer("Категории не найдены.")
        return

    total = len(category_ids)
    new_index = (current_index - 1) % total

    await state.update_data(current_category_index=new_index)
    await _show_current_category(callback, state)


@router.callback_query(F.data == "back_to_gender")
async def back_to_gender(callback: CallbackQuery, state: FSMContext):
    # Возвращаемся в состояние выбора пола
    await state.set_state(MainStates.choose_gender)

    text = "Кого будем фоткать? 😊\n\nВыбери пол:"



    try:
        await callback.message.delete()
        # Если текущее сообщение текстовое — попробуем отредактировать его
        await callback.message.answer(
            text,
            reply_markup=get_gender_keyboard(),
        )
    except TelegramBadRequest as e:
        err = str(e)
        # Если это фотосообщение / нет текста — просто шлём новое сообщение
        if "there is no text in the message to edit" in err or "message can't be edited" in err:
            await callback.message.answer(
                text,
                reply_markup=get_gender_keyboard(),
            )
        else:
            # Любую другую ошибку важно не проглатывать, чтобы не скрыть баг
            raise

    await callback.answer()



@router.callback_query(F.data == "cat_select")
async def cat_select(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    category_ids: list[int] = data.get("category_ids") or []
    current_index = data.get("current_category_index", 0)
    gender_str = data.get("current_gender")

    if not category_ids or gender_str is None:
        await callback.answer("Сначала выбери пол и категорию.")
        return

    try:
        gender = StyleGender(gender_str)
    except Exception:
        await callback.answer("Некорректный пол.")
        return

    if current_index < 0 or current_index >= len(category_ids):
        current_index = 0

    category_id = category_ids[current_index]

    styles = await get_styles_by_category_and_gender(
        category_id=category_id,
        gender=gender,
    )

    if not styles:
        await callback.answer(
            "В этой категории нет стилей для выбранного пола.",
            show_alert=True,
        )
        return

    style_ids = [s.id for s in styles]
    style_index = 0
    style = styles[style_index]

    await state.update_data(
        current_category_id=category_id,
        style_ids=style_ids,
        current_style_index=style_index,
        current_style_title=style.title,
        current_style_prompt=style.prompt,
    )
    await state.set_state(MainStates.choose_style)

    keyboard = get_styles_keyboard()
    caption = f"<b>{style.title}</b>\n\n<i>{style.description}</i>"


    await _send_photo_with_fallback(
        callback=callback,
        image_filename=style.image_filename,
        caption=caption,
        keyboard=keyboard,
    )

    await callback.answer()


@router.callback_query(F.data == "style_next")
async def style_next(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style_ids: list[int] = data.get("style_ids") or []
    current_index = data.get("current_style_index", 0)

    if not style_ids:
        await callback.answer("Стили не найдены.")
        return

    total = len(style_ids)
    if total == 1:
        await callback.answer("Пока доступен только один стиль 😊")
        return

    new_index = (current_index + 1) % total
    style_id = style_ids[new_index]
    style = await get_style_prompt_by_id(style_id)
    if style is None:
        await callback.answer("Не удалось загрузить стиль.")
        return

    await state.update_data(
        current_style_index=new_index,
        current_style_title=style.title,
        current_style_prompt=style.prompt,
    )

    keyboard = get_styles_keyboard()
    caption = f"<b>{style.title}</b>\n\n<i>{style.description}</i>"

    await _send_photo_with_fallback(
        callback=callback,
        image_filename=style.image_filename,
        caption=caption,
        keyboard=keyboard,
    )

    await callback.answer()


@router.callback_query(F.data == "style_previous")
async def style_previous(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style_ids: list[int] = data.get("style_ids") or []
    current_index = data.get("current_style_index", 0)

    if not style_ids:
        await callback.answer("Стили не найдены.")
        return

    total = len(style_ids)
    if total == 1:
        await callback.answer("Пока доступен только один стиль 😊")
        return

    new_index = (current_index - 1) % total
    style_id = style_ids[new_index]
    style = await get_style_prompt_by_id(style_id)
    if style is None:
        await callback.answer("Не удалось загрузить стиль.")
        return

    await state.update_data(
        current_style_index=new_index,
        current_style_title=style.title,
        current_style_prompt=style.prompt,
    )

    keyboard = get_styles_keyboard()
    caption = f"<b>{style.title}</b>\n\n<i>{style.description}</i>"

    await _send_photo_with_fallback(
        callback=callback,
        image_filename=style.image_filename,
        caption=caption,
        keyboard=keyboard,
    )

    await callback.answer()


@router.callback_query(F.data == "back_to_categories_carousel")
async def back_to_categories_carousel(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MainStates.choose_category)
    await _show_current_category(callback, state)


@router.callback_query(F.data.startswith("style_category:"))
async def choose_category(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    gender_str = data.get("current_gender")
    if not gender_str:
        await callback.answer("Сначала выбери пол.")
        return

    try:
        gender = StyleGender(gender_str)
    except Exception:
        await callback.answer("Некорректный пол в состоянии, попробуй заново.")
        await state.set_state(MainStates.choose_gender)
        await callback.message.edit_text(
            "Кого будем фоткать?",
            reply_markup=get_gender_keyboard(),
        )
        return

    try:
        category_id_str = callback.data.split(":", 1)[1]
        category_id = int(category_id_str)
    except Exception:
        await callback.answer("Некорректная категория.")
        return

    styles = await get_styles_by_category_and_gender(
        category_id=category_id,
        gender=gender,
    )

    if not styles:
        await callback.answer(
            "В этой категории пока нет стилей для выбранного пола.",
            show_alert=True,
        )
        return

    style_ids = [s.id for s in styles]
    current_index = 0
    current_style = styles[current_index]

    await state.update_data(
        current_category_id=category_id,
        current_gender=gender.value,
        style_ids=style_ids,
        current_style_index=current_index,
        current_style_title=current_style.title,
        current_style_prompt=current_style.prompt,
    )

    await state.set_state(MainStates.choose_style)

    caption = (
        f"<b>{current_style.title}</b>\n\n<i>{current_style.description}</i>"
    )

    await _send_photo_with_fallback(
        callback=callback,
        image_filename=current_style.image_filename,
        caption=caption,
        keyboard=get_styles_keyboard(),
    )

    await callback.answer()

@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    gender_str = data.get("current_gender")
    if not gender_str:
        await safe_callback_answer(callback)
        await callback.message.edit_text(
            "Кого будем фоткать?",
            reply_markup=get_gender_keyboard(),
        )
        await state.set_state(MainStates.choose_gender)
        return

    categories = await get_all_style_categories(include_inactive=False)
    if not categories:
        await callback.message.edit_text(
            "Категории стилей ещё не созданы.",
            reply_markup=get_start_keyboard(),
        )
        await safe_callback_answer(callback)
        return

    await state.set_state(MainStates.choose_category)
    await callback.message.edit_text(
        "Выбери категорию стиля:",
        reply_markup=get_categories_keyboard(categories),
    )
    await safe_callback_answer(callback)



@router.callback_query(F.data == "next")
async def next_style(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style_ids: list[int] = data.get("style_ids") or []
    current_index = data.get("current_style_index", 0)

    if not style_ids:
        await callback.answer("Стили не найдены для этой категории.")
        return

    total = len(style_ids)
    if total == 1:
        await callback.answer("Пока доступен только один стиль 😊", show_alert=False)
        return

    new_index = (current_index + 1) % total
    style_id = style_ids[new_index]
    style = await get_style_prompt_by_id(style_id)
    if style is None:
        await callback.answer("Не удалось загрузить стиль.")
        return

    await state.update_data(
        current_style_index=new_index,
        current_style_title=style.title,
        current_style_prompt=style.prompt,
    )

    inline_keyboard_markup = get_styles_keyboard()
    caption = f"<b>{style.title}</b>\n\n<i>{style.description}</i>"

    await _send_photo_with_fallback(
        callback=callback,
        image_filename=style.image_filename,
        caption=caption,
        keyboard=inline_keyboard_markup,
    )

    await callback.answer()


@router.callback_query(F.data == "previous")
async def previous_style(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style_ids: list[int] = data.get("style_ids") or []
    current_index = data.get("current_style_index", 0)

    if not style_ids:
        await callback.answer("Стили не найдены для этой категории.")
        return

    total = len(style_ids)
    if total == 1:
        await callback.answer("Пока доступен только один стиль 😊", show_alert=False)
        return

    new_index = (current_index - 1) % total
    style_id = style_ids[new_index]
    style = await get_style_prompt_by_id(style_id)
    if style is None:
        await callback.answer("Не удалось загрузить стиль.")
        return

    await state.update_data(
        current_style_index=new_index,
        current_style_title=style.title,
        current_style_prompt=style.prompt,
    )

    inline_keyboard_markup = get_styles_keyboard()
    caption = f"<b>{style.title}</b>\n\n<i>{style.description}</i>"

    await _send_photo_with_fallback(
        callback=callback,
        image_filename=style.image_filename,
        caption=caption,
        keyboard=inline_keyboard_markup,
    )

    await callback.answer()


@router.callback_query(F.data == "make_photoshoot")
async def make_photoshoot(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style_title = data.get("current_style_title")
    style_prompt = data.get("current_style_prompt")

    if not style_title or not style_prompt:
        await callback.answer("Не удалось определить текущий стиль.")
        return

    await state.set_state(MainStates.making_photoshoot_process)

    back_inline_button = InlineKeyboardButton(
        text="« Назад к стилям",
        callback_data="back_to_categories",
    )
    inline_keyboard_markup = InlineKeyboardMarkup(
        inline_keyboard=[[back_inline_button]]
    )

    text = (
        f"Отлично! Выбран стиль «{style_title}»\n\n"
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


def get_insufficient_balance_keyboard() -> InlineKeyboardMarkup:
    """
    Кнопки:
    - Пополнить баланс (ведёт в раздел Баланс)
    - Вернуться в главное меню
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить баланс",
                    callback_data="open_balance",
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


@router.message(MainStates.making_photoshoot_process, F.photo)
async def handle_selfie(message: Message, state: FSMContext):
    data = await state.get_data()
    style_title = data.get("current_style_title", "выбранный стиль")
    style_prompt = data.get("current_style_prompt")

    # Если генерация уже идёт — не запускаем ещё одну
    if data.get("is_generating"):
        await message.answer(
            "Я уже готовлю твою фотосессию по этому запросу 🙌\n"
            "Дождись, пожалуйста, результата."
        )
        return

    user_photo = message.photo[-1]
    user_photo_file_id = user_photo.file_id

    await state.update_data(
        user_photo_file_id=user_photo_file_id,
        is_generating=True,
    )

    # Проверяем, админ ли пользователь
    user_is_admin = await is_admin(message.from_user.id)

    # 1. Пытаемся списать кредит или деньги с баланса из БД (ТОЛЬКО для не-админов)
    if not user_is_admin:
        can_pay = await consume_photoshoot_credit_or_balance(
            telegram_id=message.from_user.id,
            price_rub=PHOTOSHOOT_PRICE,
        )

        # 2. Если баланс / кредиты не хватает — показываем экран из макета
        if not can_pay:
            await state.update_data(is_generating=False)
            await state.set_state(MainStates.making_photoshoot_failed)
            text = (
                "Недостаточно средств на балансе.\n"
                f"Стоимость одной фотосессии — <b>{PHOTOSHOOT_PRICE} ₽</b>.\n\n"
                "Пополнить баланс прямо сейчас?"
            )
            await message.answer(
                text,
                reply_markup=get_insufficient_balance_keyboard(),
            )
            return

    # 3. Баланс ок (или пользователь админ), запускаем генерацию
    await state.set_state(MainStates.making_photoshoot_success)

    await message.answer(
        f"Готовлю твою фотосессию в стиле «{style_title}»… ⏳\n"
        "Обычно это занимает 15–30 секунд.",
    )

    await message.bot.send_chat_action(
        chat_id=message.chat.id,
        action="upload_photo",
    )

    # для логов: админ = 0 рублей, обычный пользователь = PHOTOSHOOT_PRICE
    log_cost_rub = 0 if user_is_admin else PHOTOSHOOT_PRICE

    try:
        generated_photo = await generate_photoshoot_image(
            style_title=style_title,
            style_prompt=style_prompt,
            user_photo_file_ids=user_photo_file_id,  # <-- правильное имя аргумента
            bot=message.bot,
        )

        # Логируем успешную фотосессию
        await log_photoshoot(
            telegram_id=message.from_user.id,
            style_title=style_title,
            status=PhotoshootStatus.success,
            cost_rub=log_cost_rub,
            cost_credits=0,
            provider="comet_gemini_2_5_flash",
        )

    except Exception as e:
        # Логируем неудачу
        await log_photoshoot(
            telegram_id=message.from_user.id,
            style_title=style_title,
            status=PhotoshootStatus.failed,
            cost_rub=log_cost_rub,
            cost_credits=0,
            provider="comet_gemini_2_5_flash",
            error_message=str(e),
        )

        await state.update_data(is_generating=False)
        await state.set_state(MainStates.making_photoshoot_failed)
        await message.answer(
            "Упс… Что-то пошло не так при генерации фото 😔\n"
            "Сервис обработки временно недоступен.\n"
            "Попробуй, пожалуйста, ещё раз чуть позже.",
        )
        return

    # 4. Отправляем результат и сохраняем file_id последнего фото в state
    sent_message = await message.answer_document(
        document=generated_photo,
        caption="Готово! Вот твоё фото в 4K качестве ✨",
    )

    if sent_message.photo:
        generated_file_id = sent_message.photo[-1].file_id
        await state.update_data(
            last_generated_file_id=generated_file_id,
            last_generated_style_title=style_title,
        )

    await state.update_data(is_generating=False)

    await message.answer(
        "Что дальше?",
        reply_markup=get_after_photoshoot_keyboard(),
    )

from aiogram.exceptions import TelegramBadRequest

async def safe_callback_answer(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        msg = str(e)
        # Игнорируем только "query is too old..."
        if "query is too old and response timeout expired" in msg or "query ID is invalid" in msg:
            logger.warning("Пропускаю устаревший callback: %s", msg)
        else:
            raise



@router.message(MainStates.making_photoshoot_process)
async def handle_not_photo(message: Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, пришли именно <b>фото</b> (селфи), "
        "не документ, не видео, не текст 🙏"
    )


@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MainStates.start)
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "Привет! Я делаю профессиональные фотосессии из обычного селфи\n"
        "\nВыбери любой стиль и получи фото как у моделей за 2 минуты\n"
        "Vogue • Victoria’s Secret • Dubai • Аниме • Лингери и ещё 7 стилей\n"
        "Нажми кнопку ниже и начнём ✨",
        reply_markup=get_start_keyboard(),
    )


@router.callback_query(F.data == "create_another_photoshoot")
async def create_another_photoshoot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    # await get_album(callback.message, state)


@router.callback_query(F.data == "make_avatar")
async def make_avatar_from_last(callback: CallbackQuery, state: FSMContext):
    """
    Делаем аватаром последнее сгенерированное фото.
    Берём file_id из FSM (last_generated_file_id).
    """
    data = await state.get_data()
    file_id = data.get("last_generated_file_id")
    style_title = data.get("last_generated_style_title") or data.get("current_style_title")

    if not file_id:
        await callback.answer(
            "Не удалось найти последнее сгенерированное фото. "
            "Сначала сделай фотосессию.",
            show_alert=True,
        )
        return

    # Проверяем лимит аватаров
    avatars = await get_user_avatars(callback.from_user.id)
    if len(avatars) >= MAX_AVATARS_PER_USER:
        await callback.answer(
            "У тебя уже 3 аватара. Удали один в личном кабинете, чтобы добавить новый.",
            show_alert=True,
        )
        return

    avatar = await create_user_avatar(
        telegram_id=callback.from_user.id,
        file_id=file_id,
        source_style_title=style_title,
    )

    if avatar is None:
        # На всякий случай, если что-то пошло не так
        await callback.answer(
            "Не удалось сохранить аватар. Попробуй позже.",
            show_alert=True,
        )
        return

    await callback.answer("Аватар сохранён ✅", show_alert=False)
    await callback.message.answer(
        f"Супер! Это фото сохранено как твой аватар. "
        f"Всего аватаров: {len(avatars) + 1}/{MAX_AVATARS_PER_USER}.\n\n"
        "Посмотреть и удалить аватары можно в разделе «Личный кабинет»."
    )
