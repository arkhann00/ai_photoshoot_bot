from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from states import MainStates


router = Router()


@router.message(F.text == "Поддержка")
async def support(message: Message, state: FSMContext):
    await state.set_state(MainStates.support)
    await message.answer(
        "Нужна помощь?\n\n"
        "Пиши нам → @ai_photo_help\n"
        "Отвечаем 24/7, обычно в течение 3–10 минут.\n\n"
        "Или напиши вопрос прямо здесь — передадим оператору."
    )
