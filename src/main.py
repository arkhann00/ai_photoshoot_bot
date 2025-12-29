import asyncio
import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from src.db.session import engine
from src.config import settings
from src.db import init_db
from src.handlers import (
    start_router,
    photoshoot_router,
    support_router,
    balance_router,
    admin_router,
    payments_stars_router,
    cabinet_router,
    promo_codes_router
)
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

from src.db.repositories.users import is_user_admin_db, iter_all_user_ids


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

async def on_shutdown():
    await engine.dispose()

main_router = Router()
    
@main_router.message(Command("broadcast"))
async def admin_broadcast(message: Message):
    """
    Использование:
      /broadcast Текст сообщения всем пользователям

    Только админы (User.is_admin == True).
    """
    sender_id = message.from_user.id

    # проверка админа
    if not await is_user_admin_db(sender_id):
        await message.answer("⛔️ Команда доступна только администраторам.")
        return

    text = (message.text or "").split(maxsplit=1)
    if len(text) < 2 or not text[1].strip():
        await message.answer(
            "Использование:\n"
            "/broadcast <сообщение>\n\n"
            "Пример:\n"
            "/broadcast Привет! Добавили новые стили 🔥"
        )
        return

    broadcast_text = text[1].strip()

    bot = message.bot
    ok = 0
    fail = 0

    status_msg = await message.answer("📣 Начинаю рассылку…")

    async for uid in iter_all_user_ids(batch_size=1000):
        try:
            await bot.send_message(chat_id=int(uid), text=broadcast_text)
            ok += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            # пользователь заблокировал бота / чат недоступен / etc
            fail += 1
        except Exception:
            fail += 1

    await status_msg.edit_text(
        "✅ Рассылка завершена.\n"
        f"Отправлено: {ok}\n"
        f"Ошибок: {fail}"
    )


async def main() -> None:
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()

    # Подключаем роутеры
    dp.include_router(main_router)
    dp.include_router(start_router)
    dp.include_router(photoshoot_router)
    dp.include_router(support_router)
    dp.include_router(balance_router)
    dp.include_router(admin_router)
    dp.include_router(payments_stars_router)
    dp.include_router(cabinet_router)
    dp.include_router(promo_codes_router)
    
    dp.shutdown.register(on_shutdown)

    # Инициализация БД (создание таблиц и т.п.)
    await init_db()

    # Запуск поллинга
    await dp.start_polling(bot)
    


if __name__ == "__main__":
    asyncio.run(main())
