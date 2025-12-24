from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from src.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,   # главное: проверять коннект перед выдачей из пула
    pool_recycle=1800,    # пересоздавать коннекты раз в 30 минут (можно 600–3600)
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
)

async_session = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)