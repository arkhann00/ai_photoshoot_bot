from __future__ import annotations

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
)

from src.db import (
    get_user_avatar,
    create_user_avatar,
    delete_user_avatar,
)
from src.keyboards import back_to_main_menu_keyboard
from src.states import MainStates

router = Router()

ADM_GROUP_ID = -5075627878


async def send_admin_log(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=ADM_GROUP_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        return


def get_cabinet_keyboard(has_avatar: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    rows.append(
        [
            InlineKeyboardButton(
                text="📷 Изменить аватар" if has_avatar else "➕ Добавить аватар",
                callback_data="cabinet_set_avatar",
            )
        ]
    )

    if has_avatar:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🗑 Удалить аватар",
                    callback_data="cabinet_delete_avatar",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="« Назад",
                callback_data="back_to_main_menu",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_cabinet(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    avatar = await get_user_avatar(user_id)
    has_avatar = avatar is not None

    await send_admin_log(
        bot,
        (
            "👤 <b>Личный кабинет открыт</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}\n"
            f"Аватар: {'есть' if has_avatar else 'нет'}"
        ),
    )

    # Основной экран ЛК
    if not has_avatar:
        await callback.message.answer(
            "👤 <b>Личный кабинет</b>\n\n"
            "Аватар ещё не задан.\n"
            "Нажми «Добавить аватар» и пришли фото — оно будет использоваться для генераций.",
            reply_markup=get_cabinet_keyboard(has_avatar=False),
        )
        return

    caption = "👤 <b>Твой аватар</b>\n\n"
    if avatar.source_style_title:
        caption += f"Источник: <i>{avatar.source_style_title}</i>\n"

    try:
        await callback.message.answer_photo(
            photo=avatar.file_id,
            caption=caption,
            parse_mode="HTML",
            reply_markup=get_cabinet_keyboard(has_avatar=True),
        )
    except Exception as e:
        await callback.message.answer(
            "👤 <b>Твой аватар</b>\n\n"
            "Не смог показать фото (Telegram не принял file_id), но аватар в базе есть.\n"
            "Нажми «Изменить аватар» и загрузи новое фото.",
            parse_mode="HTML",
            reply_markup=get_cabinet_keyboard(has_avatar=True),
        )

        await send_admin_log(
            bot,
            (
                "🔴 <b>Ошибка отправки аватара в ЛК</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"avatar_id: <code>{avatar.id}</code>\n"
                f"file_id: <code>{avatar.file_id}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )


@router.callback_query(F.data == "personal_cabinet")
async def open_personal_cabinet(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()  # чтобы кабинет не конфликтовал с генерацией

    try:
        await callback.message.delete()
    except Exception:
        pass

    await callback.message.answer(
        "Открываю личный кабинет…",
        reply_markup=back_to_main_menu_keyboard(),
    )

    await _render_cabinet(callback)


@router.callback_query(F.data == "cabinet_set_avatar")
async def cabinet_set_avatar(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(MainStates.cabinet_waiting_avatar)

    await callback.message.answer(
        "📷 Пришли фото, которое станет твоим аватаром.\n\n"
        "Это фото будет использоваться для генераций по умолчанию.",
        reply_markup=back_to_main_menu_keyboard(),
    )


@router.message(MainStates.cabinet_waiting_avatar, F.photo)
async def cabinet_receive_avatar_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    username = message.from_user.username or "—"
    bot = message.bot

    file_id = message.photo[-1].file_id

    # UPSERT: удалит старый и создаст новый
    avatar = await create_user_avatar(
        telegram_id=user_id,
        file_id=file_id,
        source_style_title="cabinet_upload",
    )

    await state.clear()

    await message.answer("✅ Аватар обновлён!", reply_markup=back_to_main_menu_keyboard())

    await send_admin_log(
        bot,
        (
            "🟢 <b>Аватар обновлён из ЛК</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}\n"
            f"avatar_id: <code>{avatar.id if avatar else '—'}</code>"
        ),
    )


@router.message(MainStates.cabinet_waiting_avatar)
async def cabinet_waiting_avatar_not_photo(message: Message):
    await message.answer(
        "Пожалуйста, пришли именно <b>фото</b> (не файл-документ и не видео) 🙏",
        parse_mode="HTML",
        reply_markup=back_to_main_menu_keyboard(),
    )

@router.callback_query(F.data == "cabinet_delete_avatar")
async def cabinet_delete_avatar(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    await callback.answer()

    ok = await delete_user_avatar(user_id)  # ← ВАЖНО: без avatar_id
    await state.clear()

    if not ok:
        await callback.message.answer(
            "Не удалось удалить аватар. Возможно, его уже нет.",
            reply_markup=back_to_main_menu_keyboard(),
        )
        await send_admin_log(
            bot,
            (
                "⚠️ <b>Не удалось удалить аватар</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}"
            ),
        )
        return

    await callback.message.answer(
        "🗑 Аватар удалён.\n\nТеперь при первой генерации новое фото снова станет твоим аватаром.",
        reply_markup=back_to_main_menu_keyboard(),
    )

    await send_admin_log(
        bot,
        (
            "🗑 <b>Аватар удалён пользователем</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}"
        ),
    )
