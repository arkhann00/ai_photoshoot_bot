# src/handlers/cabinet.py

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.db import get_user_avatars, delete_user_avatar, MAX_AVATARS_PER_USER
from src.keyboards import back_to_main_menu_keyboard

router = Router()


@router.callback_query(F.data == "personal_cabinet")
async def open_personal_cabinet(callback: CallbackQuery):
    """
    Личный кабинет: показываем аватары пользователя.
    """
    avatars = await get_user_avatars(callback.from_user.id)

    await callback.answer()
    try:
        await callback.message.delete()
    except Exception as e:
        pass

    if not avatars:
        await callback.message.answer(
            "У тебя пока нет аватаров.\n\n"
            "После следующей фотосессии ты сможешь нажать кнопку "
            "«Сделать это фото аватаром», чтобы сохранить лучшее фото.",
            reply_markup=back_to_main_menu_keyboard()
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

        await callback.message.answer_photo(
            photo=avatar.file_id,
            caption=caption,
            reply_markup=kb,
        )


@router.callback_query(F.data.startswith("avatar_delete:"))
async def delete_avatar(callback: CallbackQuery):
    """
    Удаление конкретного аватара.
    """
    try:
        avatar_id_str = callback.data.split(":", 1)[1]
        avatar_id = int(avatar_id_str)
    except Exception:
        await callback.answer("Некорректный ID аватара.", show_alert=True)
        return

    ok = await delete_user_avatar(callback.from_user.id, avatar_id)
    if not ok:
        await callback.answer(
            "Не удалось удалить аватар. Возможно, он уже удалён.",
            show_alert=True,
        )
        return

    # Обновляем подпись под картинкой
    try:
        await callback.message.edit_caption(
            caption="Аватар удалён 🗑",
            reply_markup=None,
        )
    except Exception:
        # если не получилось — просто игнорируем
        pass

    await callback.answer("Аватар удалён.", show_alert=False)
