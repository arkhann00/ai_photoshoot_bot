from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional, Tuple

from aiogram import Bot
from aiogram.types import User as TgUser

_STORAGE_PATH = Path("support_threads.json")
_LOCK = asyncio.Lock()


def _safe_topic_title(user: TgUser) -> str:
    username = (user.username or "").strip()
    name = (user.full_name or "").strip()

    if username:
        title = f"{name} (@{username}) (ID: {user.id})" if name else f"@{username} (ID: {user.id})"
    else:
        title = f"{name} (ID: {user.id})" if name else f"ID: {user.id}"

    # Telegram ограничивает название темы (обычно 1..128)
    title = title.replace("\n", " ").strip()
    if len(title) > 128:
        title = title[:125] + "..."
    return title


async def _load_map() -> dict:
    if not _STORAGE_PATH.exists():
        return {"users": {}, "threads": {}}
    data = await asyncio.to_thread(_STORAGE_PATH.read_text, encoding="utf-8")
    try:
        obj = json.loads(data)
    except Exception:
        return {"users": {}, "threads": {}}

    if not isinstance(obj, dict):
        return {"users": {}, "threads": {}}
    obj.setdefault("users", {})
    obj.setdefault("threads", {})
    return obj


async def _save_map(obj: dict) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2)
    await asyncio.to_thread(_STORAGE_PATH.write_text, text, encoding="utf-8")


async def get_thread_id_for_user(user_id: int) -> Optional[int]:
    async with _LOCK:
        obj = await _load_map()
        val = obj.get("users", {}).get(str(user_id))
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
        return None


async def get_user_id_for_thread(thread_id: int) -> Optional[int]:
    async with _LOCK:
        obj = await _load_map()
        val = obj.get("threads", {}).get(str(thread_id))
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
        return None


async def bind_user_thread(user_id: int, thread_id: int) -> None:
    async with _LOCK:
        obj = await _load_map()
        obj["users"][str(user_id)] = int(thread_id)
        obj["threads"][str(thread_id)] = int(user_id)
        await _save_map(obj)


async def get_or_create_forum_thread(bot: Bot, user: TgUser) -> Tuple[int, bool]:

    if SUPPORT_CHAT_ID == 0:
        raise RuntimeError("SUPPORT_CHAT_ID is not set")

    existing = await get_thread_id_for_user(user.id)
    if existing is not None:
        return existing, False

    title = _safe_topic_title(user)

    topic = await bot.create_forum_topic(
        chat_id=SUPPORT_CHAT_ID,
        name=title,
    )

    thread_id = int(topic.message_thread_id)
    await bind_user_thread(user.id, thread_id)
    return thread_id, True
