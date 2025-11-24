# src/handlers/start.py

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.states import MainStates
from src.keyboards import get_start_keyboard, get_photoshoot_entry_keyboard
from src.db import get_or_create_user


router = Router()


@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext):
    await state.set_state(MainStates.start)

    await get_or_create_user(message.from_user)

    await message.answer(
        "Привет! Я делаю профессиональные фотосессии из обычного селфи.\n\n"
        "Выбери любой стиль и получи фото как у моделей за 2 минуты:\n"
        "Vogue • Victoria’s Secret • Dubai • Аниме • Лингери и ещё несколько стилей.\n\n"
        "Нажми кнопку ниже и начнём ✨",
        reply_markup=get_start_keyboard(),
    )


@router.message(F.text == "Создать фотосессию ✨")
async def make_photoshoot(message: Message, state: FSMContext):
    await state.set_state(MainStates.making_photoshoot)

    await message.answer(
        "Выбери стиль своей будущей фотосессии ✨\n\n"
        "Более 20 профессиональных направлений в 4K-качестве.",
        reply_markup=get_photoshoot_entry_keyboard(),
    )
