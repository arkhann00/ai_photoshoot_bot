# src/handlers/cabinet.py

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.db import get_user_avatars, delete_user_avatar, MAX_AVATARS_PER_USER
from src.keyboards import back_to_main_menu_keyboard

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
    except Exception:
        # Ничего не делаем, чтобы не уронить обработчик ЛК
        return


@router.callback_query(F.data == "personal_cabinet")
async def open_personal_cabinet(callback: CallbackQuery):
    """
    Личный кабинет: показываем аватары пользователя.
    """
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    avatars = await get_user_avatars(user_id)

    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        # Игнорируем ошибку удаления сообщения (например, уже удалено)
        pass

    # Лог в админский чат о входе в ЛК
    await send_admin_log(
        bot,
        (
            "👤 <b>Личный кабинет открыт</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}\n"
            f"Аватаров: {len(avatars)}/{MAX_AVATARS_PER_USER}"
        ),
    )

    if not avatars:
        await callback.message.answer(
            "У тебя пока нет аватаров.\n\n"
            "После следующей фотосессии ты сможешь нажать кнопку "
            "«Сделать это фото аватаром», чтобы сохранить лучшее фото.",
            reply_markup=back_to_main_menu_keyboard(),
        )

        await send_admin_log(
            bot,
            (
                "ℹ️ <b>Личный кабинет без аватаров</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}"
            ),
        )
        return

    await callback.message.answer(
        f"Твои аватары ({len(avatars)}/{MAX_AVATARS_PER_USER}):"
    )

    for avatar in avatars:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🗑 Удалить этот аватар",
                        callback_data=f"avatar_delete:{avatar.id}",
                    )
                ]
            ]
        )

        caption = "Аватар"
        if avatar.source_style_title:
            caption = f"Аватар из стиля «{avatar.source_style_title}»"

        try:
            await callback.message.answer_photo(
                photo=avatar.file_id,
                caption=caption,
                reply_markup=kb,
            )
        except Exception as e:
            # Логируем ошибку отправки аватара
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

    await callback.message.answer(
        text="Вернуться в главное меню?",
        reply_markup=back_to_main_menu_keyboard(),
    )


@router.callback_query(F.data.startswith("avatar_delete:"))
async def delete_avatar(callback: CallbackQuery):
    """
    Удаление конкретного аватара.
    """
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    try:
        avatar_id_str = callback.data.split(":", 1)[1]
        avatar_id = int(avatar_id_str)
    except Exception:
        await callback.answer("Некорректный ID аватара.", show_alert=True)

        await send_admin_log(
            bot,
            (
                "⚠️ <b>Некорректный ID аватара при удалении</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Сырой callback_data: <code>{callback.data}</code>"
            ),
        )
        return

    ok = await delete_user_avatar(user_id, avatar_id)
    if not ok:
        await callback.answer(
            "Не удалось удалить аватар. Возможно, он уже удалён.",
            show_alert=True,
        )

        await send_admin_log(
            bot,
            (
                "⚠️ <b>Не удалось удалить аватар</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"avatar_id: <code>{avatar_id}</code>\n"
                "Причина: delete_user_avatar вернул False"
            ),
        )
        return

    # Обновляем подпись под картинкой
    try:
        await callback.message.edit_caption(
            caption="Аватар удалён 🗑",
            reply_markup=None,
        )
    except Exception as e:
        # Логируем, если подпись не удалось изменить
        await send_admin_log(
            bot,
            (
                "⚠️ <b>Ошибка обновления подписи после удаления аватара</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"avatar_id: <code>{avatar_id}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )

    await callback.answer("Аватар удалён.", show_alert=False)

    # Лог успешного удаления
    await send_admin_log(
        bot,
        (
            "🗑 <b>Аватар удалён пользователем</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}\n"
            f"avatar_id: <code>{avatar_id}</code>"
        ),
    )
