from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from src.keyboards import back_to_main_menu_keyboard
from src.states import MainStates
from src.services.support_topics import get_or_create_support_thread
from src.db import get_support_user_id_by_thread

router = Router()

SUPPORT_CHAT_ID = -1003326572292

def successful_support_answer_keyboard():
    answer_button = InlineKeyboardButton(
        text="Ответить",
        callback_data="support",
    )
    back_button = InlineKeyboardButton(
        text="« Назад",
        callback_data="back_to_main_menu",
    )
    return InlineKeyboardMarkup(inline_keyboard=[[answer_button], [back_button]])

@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    # try:
    #     await callback.message.delete()
    # except Exception:
    #     pass

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

    thread_id, created_now = await get_or_create_support_thread(bot, user)

    if created_now:
        await bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            message_thread_id=thread_id,
            text=(
                "🆕 Тема поддержки создана\n"
                f"Имя: {user.full_name}\n"
                f"Username: @{user.username}" if user.username else f"ID: {user.id}"
            ),
        )

    # отправляем сообщение в тему
    if message.text:
        await bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            message_thread_id=thread_id,
            text=f"📩 Сообщение от пользователя:\n{message.text}",
        )
    else:
        await bot.send_message(
            chat_id=SUPPORT_CHAT_ID,
            message_thread_id=thread_id,
            text="📩 Сообщение от пользователя (вложение):",
        )
        await bot.copy_message(
            chat_id=SUPPORT_CHAT_ID,
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
async def handle_support_reply(message: Message):
    # только ответы из темы
    if not message.message_thread_id:
        return

    if message.from_user and message.from_user.is_bot:
        return

    user_id = await get_support_user_id_by_thread(int(message.message_thread_id))
    if not user_id:
        return

    bot = message.bot

    if message.text:
        await bot.send_message(
            chat_id=user_id,
            text=f"💬 Ответ поддержки:\n\n{message.text}",
            reply_markup=successful_support_answer_keyboard(),
        )
    else:
        await bot.send_message(
            chat_id=user_id,
            text="💬 Ответ поддержки:",
            reply_markup=successful_support_answer_keyboard(),
        )
        await bot.copy_message(
            chat_id=user_id,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
        )


