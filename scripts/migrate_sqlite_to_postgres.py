import os
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select, text

# Импортируем модели и Base
from src.db import (
    Base,
    User,
    StarPayment,
    StyleCategory,
    StylePrompt,
    PhotoshootLog,
    UserAvatar,
    UserStats,
    SupportTopic,
)

SQLITE_URL = "sqlite+aiosqlite:///./bot_data/bot.db"
POSTGRES_URL = os.environ.get("DATABASE_URL", "")

TABLES_IN_ORDER = [
    "support_topics",
    "user_avatars",
    "photoshoot_logs",
    "star_payments",
    "style_prompts",
    "style_categories",
    "user_stats",
    "users",
]

SEQUENCES = [
    ("users", "id"),
    ("star_payments", "id"),
    ("style_categories", "id"),
    ("style_prompts", "id"),
    ("photoshoot_logs", "id"),
    ("user_avatars", "id"),
    ("user_stats", "id"),
]

async def copy_all(sqlite_sess: AsyncSession, pg_sess: AsyncSession):
    # читаем всё из sqlite
    users = (await sqlite_sess.execute(select(User))).scalars().all()
    payments = (await sqlite_sess.execute(select(StarPayment))).scalars().all()
    categories = (await sqlite_sess.execute(select(StyleCategory))).scalars().all()
    prompts = (await sqlite_sess.execute(select(StylePrompt))).scalars().all()
    logs = (await sqlite_sess.execute(select(PhotoshootLog))).scalars().all()
    avatars = (await sqlite_sess.execute(select(UserAvatar))).scalars().all()
    stats = (await sqlite_sess.execute(select(UserStats))).scalars().all()
    topics = (await sqlite_sess.execute(select(SupportTopic))).scalars().all()

    # переносим с сохранением id
    pg_sess.add_all([User(**u.__dict__) for u in users])
    pg_sess.add_all([StarPayment(**p.__dict__) for p in payments])
    pg_sess.add_all([StyleCategory(**c.__dict__) for c in categories])
    pg_sess.add_all([StylePrompt(**s.__dict__) for s in prompts])
    pg_sess.add_all([PhotoshootLog(**l.__dict__) for l in logs])
    pg_sess.add_all([UserAvatar(**a.__dict__) for a in avatars])
    pg_sess.add_all([UserStats(**st.__dict__) for st in stats])
    pg_sess.add_all([SupportTopic(**t.__dict__) for t in topics])

async def reset_sequences(pg_sess: AsyncSession):
    for table, col in SEQUENCES:
        await pg_sess.execute(
            text(
                f"""
                SELECT setval(
                    pg_get_serial_sequence('{table}', '{col}'),
                    COALESCE((SELECT MAX({col}) FROM {table}), 1),
                    true
                )
                """
            )
        )

async def main():
    if not POSTGRES_URL.startswith("postgresql+asyncpg://"):
        raise RuntimeError("DATABASE_URL должен быть postgresql+asyncpg://...")

    sqlite_engine = create_async_engine(SQLITE_URL, future=True)
    pg_engine = create_async_engine(POSTGRES_URL, future=True)

    SQLiteSession = async_sessionmaker(sqlite_engine, expire_on_commit=False, class_=AsyncSession)
    PGSession = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    # создаём таблицы в Postgres (если ещё не созданы)
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SQLiteSession() as sqlite_sess, PGSession() as pg_sess:
        # чистим Postgres (чтобы не было дублей)
        # TRUNCATE RESTART IDENTITY CASCADE — самый надёжный вариант
        for t in TABLES_IN_ORDER:
            await pg_sess.execute(text(f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE'))
        await pg_sess.commit()

        await copy_all(sqlite_sess, pg_sess)
        await pg_sess.commit()

        await reset_sequences(pg_sess)
        await pg_sess.commit()

    await sqlite_engine.dispose()
    await pg_engine.dispose()

    print("✅ Migration done: SQLite -> Postgres")

if __name__ == "__main__":
    asyncio.run(main())
