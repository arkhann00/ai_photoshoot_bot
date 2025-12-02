from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from src.keyboards import back_to_main_menu_keyboard
from src.states import MainStates


router = Router()


@router.callback_query(F.data == "support")
async def support(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.delete()
    except:
        pass
    await state.set_state(MainStates.support)
    await callback.message.answer(
        "Нужна помощь?\n\n"
        "Пиши нам → @ai_photo_help\n"
        "Отвечаем 24/7, обычно в течение 3–10 минут.\n\n"
        "Или напиши вопрос прямо здесь — передадим оператору.",
        reply_markup=back_to_main_menu_keyboard()
    )
