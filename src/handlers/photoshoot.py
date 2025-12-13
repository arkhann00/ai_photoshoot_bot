# src/handlers/photoshoot.py
from typing import Optional

from aiogram import Router, F, Bot
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

from src.handlers.balance import send_quick_topup_invoice_49
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
    get_error_generating_keyboard, get_avatar_choice_keyboard,
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
    get_user_by_telegram_id,
    change_user_balance,
    add_referral_earnings, get_user_avatar, set_user_avatar,
)

router = Router()

ADM_GROUP_ID = -5075627878


async def send_admin_log(bot: Bot, text: str) -> None:
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
    except Exception as e:
        logger.error("Не удалось отправить лог в админский чат: %s", e)


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

        await send_admin_log(
            callback.message.bot,
            (
                "⚠️ <b>Ошибка отправки превью стиля</b>\n"
                f"Пользователь: <code>{callback.from_user.id}</code>\n"
                f"Файл не найден: <code>{image_path}</code>"
            ),
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

            await send_admin_log(
                callback.message.bot,
                (
                    "🔴 <b>Ошибка отправки превью стиля</b>\n"
                    f"Пользователь: <code>{callback.from_user.id}</code>\n"
                    f"Файл: <code>{image_path}</code>\n"
                    f"Ошибка Telegram: <code>{e2}</code>"
                ),
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

    avatar = await get_user_avatar(callback.from_user.id)

    await state.set_state(MainStates.choose_avatar_input)
    await callback.answer()

    if avatar is None:
        text = (
            f"Выбран стиль «{style_title}» ✅\n\n"
            "У тебя пока нет аватара.\n"
            "Пришли фото — я сохраню его как твой аватар и буду использовать дальше."
        )
        await callback.message.answer(
            text,
            reply_markup=get_avatar_choice_keyboard(has_avatar=False),
        )
    else:
        text = (
            f"Выбран стиль «{style_title}» ✅\n\n"
            "Как будем генерировать?\n"
            "— использовать твой текущий аватар\n"
            "— или загрузить новое фото (после генерации оно станет новым аватаром)"
        )
        await callback.message.answer(
            text,
            reply_markup=get_avatar_choice_keyboard(has_avatar=True),
        )

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
    - Пополнить на 49 ₽ (создаёт инвойс на 49 ₽)
    - Другие варианты пополнения (открывает экран Баланса)
    - Вернуться в главное меню
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить на 49 ₽",
                    callback_data="quick_topup_49",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Другие варианты пополнения",
                    callback_data="balance",
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

async def _run_generation(
    *,
    bot: Bot,
    chat_id: int,
    user_id: int,
    username: str,
    state: FSMContext,
    style_title: str,
    style_prompt: str,
    input_photo_file_id: str,
    user_is_admin: bool,
    log_cost_rub: int,
    update_avatar_after_success: bool,
    new_avatar_file_id: Optional[str],
) -> None:
    await state.set_state(MainStates.making_photoshoot_success)

    await bot.send_message(
        chat_id=chat_id,
        text=(
            f"Готовлю твою фотосессию в стиле «{style_title}»… ⏳\n"
            "Обычно это занимает 15–30 секунд."
        ),
    )

    await bot.send_chat_action(chat_id=chat_id, action="upload_photo")

    try:
        generated_photo = await generate_photoshoot_image(
            style_title=style_title,
            style_prompt=style_prompt,
            user_photo_file_ids=input_photo_file_id,
            bot=bot,
        )

        await log_photoshoot(
            telegram_id=user_id,
            style_title=style_title,
            status=PhotoshootStatus.success,
            cost_rub=log_cost_rub,
            cost_credits=0,
            provider="comet_gemini_2_5_flash",
            input_photos_count=1,
        )

        await send_admin_log(
            bot,
            (
                "🟢 <b>Успешная генерация фотосессии</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Стиль: {style_title}\n"
                f"Списано: {log_cost_rub} ₽\n"
                f"Админ: {'да' if user_is_admin else 'нет'}"
            ),
        )

        # после УСПЕШНОЙ генерации — обновляем аватар (если нужно)
        if update_avatar_after_success and new_avatar_file_id:
            await set_user_avatar(
                telegram_id=user_id,
                file_id=new_avatar_file_id,
                source_style_title=f"avatar_after_success:{style_title}",
            )


    except Exception as e:
        await log_photoshoot(
            telegram_id=user_id,
            style_title=style_title,
            status=PhotoshootStatus.failed,
            cost_rub=log_cost_rub,
            cost_credits=0,
            provider="comet_gemini_2_5_flash",
            error_message=str(e),
            input_photos_count=1,
        )

        await send_admin_log(
            bot,
            (
                "🔴 <b>Ошибка генерации фотосессии</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Стиль: {style_title}\n"
                f"Стоимость: {log_cost_rub} ₽\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )

        await state.update_data(is_generating=False)
        await state.set_state(MainStates.making_photoshoot_failed)
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "Упс… Что-то пошло не так при генерации фото 😔\n"
                "Сервис обработки временно недоступен.\n"
                "Попробуй, пожалуйста, ещё раз чуть позже."
            ),
            reply_markup=get_error_generating_keyboard(),
        )
        return

    # отправка результата
    photo_msg = await bot.send_photo(chat_id=chat_id, photo=generated_photo)

    photo_file_id = photo_msg.photo[-1].file_id
    await state.update_data(
        last_generated_file_id=photo_file_id,
        last_generated_style_title=style_title,
        is_generating=False,
        avatar_update_mode=None,
    )

    await bot.send_document(
        chat_id=chat_id,
        document=generated_photo,
        caption="Готово! Вот твоё фото ✨",
    )

    await bot.send_message(
        chat_id=chat_id,
        text="Что дальше?",
        reply_markup=get_after_photoshoot_keyboard(),
    )


@router.callback_query(F.data == "upload_new_photo")
async def upload_new_photo(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style_title = data.get("current_style_title")
    style_prompt = data.get("current_style_prompt")

    if not style_title or not style_prompt:
        await callback.answer("Не удалось определить стиль.")
        return

    avatar = await get_user_avatar(callback.from_user.id)

    # если аватар есть — будем менять его ПОСЛЕ успешной генерации
    if avatar is not None:
        await state.update_data(avatar_update_mode="replace_after_success")
        text = (
            f"Ок! Стиль «{style_title}» ✅\n\n"
            "Пришли новое фото.\n"
            "Я сгенерирую результат и после успешной генерации это фото станет твоим новым аватаром ✨"
        )
    else:
        # аватара нет — первое загруженное фото становится аватаром
        await state.update_data(avatar_update_mode="set_if_missing")
        text = (
            f"Ок! Стиль «{style_title}» ✅\n\n"
            "Пришли фото — я сохраню его как твой аватар и использую для генераций."
        )

    await state.set_state(MainStates.making_photoshoot_process)
    await callback.answer()
    await callback.message.answer(text, reply_markup=back_to_main_menu_keyboard())


@router.callback_query(F.data == "use_avatar")
async def use_avatar(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    style_title = data.get("current_style_title")
    style_prompt = data.get("current_style_prompt")

    if not style_title or not style_prompt:
        await callback.answer("Не удалось определить стиль.")
        return

    if data.get("is_generating"):
        await callback.answer("Генерация уже идёт, подожди 🙌", show_alert=True)
        return

    avatar = await get_user_avatar(callback.from_user.id)
    if avatar is None:
        await callback.answer("У тебя ещё нет аватара. Загрузи фото.", show_alert=True)
        await callback.message.answer(
            "Пришли фото — оно станет твоим аватаром.",
            reply_markup=get_avatar_choice_keyboard(has_avatar=False),
        )
        return

    await state.update_data(is_generating=True)

    user_is_admin = await is_admin(callback.from_user.id)

    if not user_is_admin:
        can_pay = await consume_photoshoot_credit_or_balance(
            telegram_id=callback.from_user.id,
            price_rub=PHOTOSHOOT_PRICE,
        )
        if not can_pay:
            await state.update_data(is_generating=False)
            await state.set_state(MainStates.making_photoshoot_failed)
            text = (
                "Недостаточно средств на балансе.\n"
                f"Стоимость одной фотосессии — <b>{PHOTOSHOOT_PRICE} ₽</b>.\n\n"
                "Пополнить баланс прямо сейчас?"
            )
            await callback.message.answer(text, reply_markup=get_insufficient_balance_keyboard())
            await callback.answer()
            return

    log_cost_rub = 0 if user_is_admin else PHOTOSHOOT_PRICE
    username = callback.from_user.username or "—"

    await callback.answer()

    await _run_generation(
        bot=callback.bot,
        chat_id=callback.message.chat.id,
        user_id=callback.from_user.id,
        username=username,
        state=state,
        style_title=style_title,
        style_prompt=style_prompt,
        input_photo_file_id=avatar.file_id,
        user_is_admin=user_is_admin,
        log_cost_rub=log_cost_rub,
        update_avatar_after_success=False,
        new_avatar_file_id=None,
    )


@router.message(MainStates.making_photoshoot_process, F.photo)
async def handle_selfie(message: Message, state: FSMContext):
    data = await state.get_data()
    style_title = data.get("current_style_title", "выбранный стиль")
    style_prompt = data.get("current_style_prompt")

    if not style_prompt:
        await message.answer("Не найден prompt стиля. Открой каталог и выбери стиль заново 🙏")
        return

    if data.get("is_generating"):
        await message.answer(
            "Я уже готовлю твою фотосессию по этому запросу 🙌\n"
            "Дождись, пожалуйста, результата."
        )
        return

    user_photo_file_id = message.photo[-1].file_id

    await state.update_data(
        user_photo_file_id=user_photo_file_id,
        is_generating=True,
    )

    user_is_admin = await is_admin(message.from_user.id)

    if not user_is_admin:
        can_pay = await consume_photoshoot_credit_or_balance(
            telegram_id=message.from_user.id,
            price_rub=PHOTOSHOOT_PRICE,
        )
        if not can_pay:
            await state.update_data(is_generating=False)
            await state.set_state(MainStates.making_photoshoot_failed)
            text = (
                "Недостаточно средств на балансе.\n"
                f"Стоимость одной фотосессии — <b>{PHOTOSHOOT_PRICE} ₽</b>.\n\n"
                "Пополнить баланс прямо сейчас?"
            )
            await message.answer(text, reply_markup=get_insufficient_balance_keyboard())
            return
    avatar_update_mode = data.get("avatar_update_mode")
    current_avatar = await get_user_avatar(message.from_user.id)

    update_avatar_after_success = False
    new_avatar_file_id: Optional[str] = None

    if current_avatar is None:
        # аватара нет -> первое фото становится аватаром СРАЗУ
        await set_user_avatar(
            telegram_id=message.from_user.id,
            file_id=user_photo_file_id,
            source_style_title=f"avatar_first_upload:{style_title}",
        )
    else:
        # аватар есть -> меняем только если пользователь выбрал "загрузить новое фото"
        if avatar_update_mode == "replace_after_success":
            update_avatar_after_success = True
            new_avatar_file_id = user_photo_file_id

    log_cost_rub = 0 if user_is_admin else PHOTOSHOOT_PRICE
    username = message.from_user.username or "—"

    await _run_generation(
        bot=message.bot,
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        username=username,
        state=state,
        style_title=style_title,
        style_prompt=style_prompt,
        input_photo_file_id=user_photo_file_id,
        user_is_admin=user_is_admin,
        log_cost_rub=log_cost_rub,
        update_avatar_after_success=update_avatar_after_success,
        new_avatar_file_id=new_avatar_file_id,
    )


@router.callback_query(F.data == "quick_topup_49")
async def quick_topup_49_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    await send_quick_topup_invoice_49(callback)


from aiogram.exceptions import TelegramBadRequest as AiogramTelegramBadRequest


async def safe_callback_answer(callback: CallbackQuery) -> None:
    try:
        await callback.answer()
    except AiogramTelegramBadRequest as e:
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
        """📸 Добро пожаловать в Ai Photo-Studio!
        \n\nЗдесь твои снимки обретают новую жизнь — я превращу любую фотографию в стильный, выразительный и по-настоящему уникальный визуальный образ. 
        \n\nВыбирай категорию и смело начинай — создадим что-то впечатляющее 😉""",
        reply_markup=get_start_keyboard(),
    )


@router.callback_query(F.data == "create_another_photoshoot")
async def create_another_photoshoot(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    # await get_album(callback.message, state)