from __future__ import annotations

from typing import List

from src.db import (
    SUPER_ADMIN_ID,
    get_or_create_user,
    set_user_admin_flag,
    is_user_admin_db,
    get_admin_users,
)


async def is_admin(user_id: int) -> bool:
    """
    Проверка: является ли пользователь админом.
    SUPER_ADMIN_ID всегда админ.
    Остальные — по полю is_admin в БД.
    """
    if user_id == SUPER_ADMIN_ID:
        return True
    return await is_user_admin_db(user_id)


async def add_admin(user_id: int, username: str | None = None):
    """
    Назначить пользователя админом.
    Если пользователя нет в БД — создаём.
    """
    user = await get_or_create_user(user_id, username)
    await set_user_admin_flag(user.telegram_id, True)
    return user


async def remove_admin(user_id: int):
    """
    Снять админа.
    Супер-админа снять нельзя.
    """
    if user_id == SUPER_ADMIN_ID:
        return None
    return await set_user_admin_flag(user_id, False)


async def get_admin_ids() -> List[int]:
    """
    Список ID админов, включая SUPER_ADMIN_ID.
    """
    admins = await get_admin_users()
    ids = [u.telegram_id for u in admins]
    if SUPER_ADMIN_ID not in ids:
        ids.append(SUPER_ADMIN_ID)
    return ids
