# src/scripts/migrate_sqlite_to_postgres.py
from __future__ import annotations

import asyncio
from typing import Any, Iterable, Type

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from src.config import settings
from src.db import Base, User, StarPayment, StyleCategory, StylePrompt, PhotoshootLog, UserAvatar, UserStats, SupportTopic


SQLITE_URL = "sqlite+aiosqlite:///./bot_data/bot.db"
POSTGRES_URL = settings.DATABASE_URL  # postgresql+asyncpg://...


def row_to_dict(obj: Any) -> dict[str, Any]:
    """
    Берём только реальные колонки, без _sa_instance_state и без relationship.
    Работает для SQLAlchemy Declarative моделей.
    """
    cols = obj.__table__.columns.keys()
    return {c: getattr(obj, c) for c in cols}


async def copy_table(
    sqlite_sess: AsyncSession,
    pg_sess: AsyncSession,
    model: Type[Base],
    chunk_size: int = 1000,
) -> None:
    # читаем все строки из sqlite
    result = await sqlite_sess.execute(select(model))
    rows = list(result.scalars().all())

    if not rows:
        return

    # вставляем чанками (чтобы не раздувать память и транзакции)
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i : i + chunk_size]
        pg_sess.add_all([model(**row_to_dict(r)) for r in chunk])
        await pg_sess.flush()


async def main() -> None:
    sqlite_engine = create_async_engine(SQLITE_URL, echo=False, future=True)
    pg_engine = create_async_engine(POSTGRES_URL, echo=False, future=True)

    sqlite_sm = async_sessionmaker(sqlite_engine, expire_on_commit=False, class_=AsyncSession)
    pg_sm = async_sessionmaker(pg_engine, expire_on_commit=False, class_=AsyncSession)

    # ВАЖНО: таблицы в Postgres должны существовать (через init_db()/alembic)
    # Если хочешь создать прямо тут:
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sqlite_sm() as sqlite_sess, pg_sm() as pg_sess:
        # одна транзакция на весь перенос (можно разбить, если хочешь)
        async with pg_sess.begin():
            # порядок важен, если есть связи по id
            await copy_table(sqlite_sess, pg_sess, User)
            await copy_table(sqlite_sess, pg_sess, UserStats)
            await copy_table(sqlite_sess, pg_sess, StarPayment)
            await copy_table(sqlite_sess, pg_sess, StyleCategory)
            await copy_table(sqlite_sess, pg_sess, StylePrompt)
            await copy_table(sqlite_sess, pg_sess, PhotoshootLog)
            await copy_table(sqlite_sess, pg_sess, UserAvatar)
            await copy_table(sqlite_sess, pg_sess, SupportTopic)

    await sqlite_engine.dispose()
    await pg_engine.dispose()
    print("✅ Migration finished successfully")


if __name__ == "__main__":
    asyncio.run(main())
