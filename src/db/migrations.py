# src/db/migrations.py
from __future__ import annotations

from sqlalchemy.exc import OperationalError
from sqlalchemy.sql.expression import text

from .base import Base
from .session import engine


def _is_postgres(conn) -> bool:
    return conn.dialect.name == "postgresql"


async def _postgres_fix_sequences(conn) -> None:
    await conn.execute(
        text(
            """
DO $$
DECLARE
  r record;
  seq_name text;
  max_id bigint;
BEGIN
  FOR r IN
    SELECT * FROM (VALUES
      ('users', 'id'),
      ('star_payments', 'id'),
      ('style_categories', 'id'),
      ('style_prompts', 'id'),
      ('photoshoot_logs', 'id'),
      ('user_avatars', 'id'),
      ('user_stats', 'id')
    ) AS t(tbl, col)
  LOOP
    SELECT pg_get_serial_sequence(r.tbl, r.col) INTO seq_name;

    IF seq_name IS NOT NULL THEN
      EXECUTE format('SELECT COALESCE(MAX(%I), 1) FROM %I', r.col, r.tbl) INTO max_id;
      EXECUTE format('SELECT setval(%L, %s, true)', seq_name, max_id);
    END IF;
  END LOOP;
END $$;
            """
        )
    )


async def run_manual_migrations() -> None:
    async with engine.begin() as conn:
        if _is_postgres(conn):
            await conn.execute(
                text('ALTER TABLE photoshoot_logs ADD COLUMN IF NOT EXISTS input_photos_count INTEGER DEFAULT 1;')
            )
            await conn.execute(
                text('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_referral BOOLEAN DEFAULT FALSE;')
            )
            await conn.execute(
                text('ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_earned_rub INTEGER DEFAULT 0;')
            )
            await conn.execute(
                text('ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT;')
            )
        else:
            try:
                await conn.execute(text("ALTER TABLE photoshoot_logs ADD COLUMN input_photos_count INTEGER DEFAULT 1"))
            except OperationalError:
                pass
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN is_referral BOOLEAN DEFAULT 0"))
            except OperationalError:
                pass
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN referral_earned_rub INTEGER DEFAULT 0"))
            except OperationalError:
                pass
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN referrer_id BIGINT"))
            except OperationalError:
                pass

        if _is_postgres(conn):
            await _postgres_fix_sequences(conn)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await run_manual_migrations()