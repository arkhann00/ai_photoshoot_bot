# src/handlers/start.py

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.states import MainStates
from src.keyboards import get_start_keyboard, get_photoshoot_entry_keyboard
from src.db import get_or_create_user


router = Router()


# src/handlers/start.py

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.db import get_or_create_user
from src.states import MainStates
from src.keyboards import get_start_keyboard  # если есть

router = Router()


@router.message(CommandStart())
async def command_start(message: Message, state: FSMContext):
    # создаём/обновляем пользователя в БД
    await get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
    )

    await state.set_state(MainStates.start)

    await message.answer(
        "Привет! Я делаю профессиональные фотосессии из обычного селфи\n"
        "\nВыбери любой стиль и получи фото как у моделей за 2 минуты\n"
        "Vogue • Victoria’s Secret • Dubai • Аниме • Лингери и ещё 7 стилей\n"
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
