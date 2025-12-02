import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from src.config import settings
from src.db import init_db
from src.handlers import (
    start_router,
    photoshoot_router,
    support_router,
    balance_router,
    admin_router,
    payments_stars_router,
    cabinet_router
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main() -> None:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    # Подключаем роутеры
    dp.include_router(start_router)
    dp.include_router(photoshoot_router)
    dp.include_router(support_router)
    dp.include_router(balance_router)
    dp.include_router(admin_router)
    dp.include_router(payments_stars_router)
    dp.include_router(cabinet_router)

    # Инициализация БД (создание таблиц и т.п.)
    await init_db()

    # Запуск поллинга
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
