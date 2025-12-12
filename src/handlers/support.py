from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery

from src.keyboards import back_to_main_menu_keyboard
from src.states import MainStates
from src.config import settings
from src.services.support_topics import get_or_create_forum_thread, get_user_id_for_thread

router = Router()

SUPPORT_CHAT_ID = -1003326572292

@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception:
        pass

    await state.set_state(MainStates.send_supoort_message)
    await callback.message.answer(
        "Напиши сообщение, мы его отправим в поддержку и в ближайшее время тебе ответят",
        reply_markup=back_to_main_menu_keyboard(),
    )


@router.message(MainStates.send_supoort_message)
async def send_support_message(message: Message, state: FSMContext):
    bot = message.bot
    user = message.from_user
    if user is None:
        await message.answer("Не удалось определить пользователя.")
        return

    # 1) получаем/создаём тему под пользователя
    thread_id, created_now = await get_or_create_forum_thread(bot, user)

    # 2) если тема только что создана — отправим “шапку”
    if created_now:
        username = f"@{user.username}" if user.username else "—"
        await bot.send_message(
            chat_id=settings.SUPPORT_CHAT_ID,
            message_thread_id=thread_id,
            text=(
                "🆕 Создана тема пользователя\n"
                f"Имя: {user.full_name}\n"
                f"Username: {username}\n"
                f"ID: {user.id}"
            ),
        )

    # 3) отправляем сообщение пользователя в тему (копируем контент)
    if message.text:
        await bot.send_message(
            chat_id=settings.SUPPORT_CHAT_ID,
            message_thread_id=thread_id,
            text=f"📩 Сообщение:\n{message.text}",
        )
    else:
        # фото/видео/документ/voice/etc — копируем как есть
        await bot.send_message(
            chat_id=settings.SUPPORT_CHAT_ID,
            message_thread_id=thread_id,
            text="📩 Сообщение (вложение):",
        )
        await bot.copy_message(
            chat_id=settings.SUPPORT_CHAT_ID,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            message_thread_id=thread_id,
        )

    await message.answer(
        "Мы передали твоё сообщение поддержке.\nЯ напишу тебе ответ.",
        reply_markup=back_to_main_menu_keyboard(),
    )
    await state.clear()

@router.message(F.chat.id == SUPPORT_CHAT_ID)
async def handle_support_group_reply(message: Message):
    # игнорируем сообщения не из темы
    if not message.message_thread_id:
        return

    # игнорируем ботов (в т.ч. самого бота)
    if message.from_user and message.from_user.is_bot:
        return

    thread_id = int(message.message_thread_id)
    user_id = await get_user_id_for_thread(thread_id)
    if not user_id:
        return

    bot = message.bot

    # Ответ саппорта -> пользователю
    if message.text:
        await bot.send_message(
            chat_id=user_id,
            text=f"💬 Ответ поддержки:\n{message.text}",
            reply_markup=back_to_main_menu_keyboard(),
        )
    else:
        await bot.send_message(
            chat_id=user_id,
            text="💬 Ответ поддержки:",
            reply_markup=back_to_main_menu_keyboard(),
        )
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )
