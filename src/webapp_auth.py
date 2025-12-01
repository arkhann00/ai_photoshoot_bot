# src/webapp_auth.py

import hashlib
import hmac
import json
import urllib.parse
from typing import Any, Dict

from fastapi import HTTPException, status

from src.config import settings


def parse_telegram_init_data(init_data: str) -> Dict[str, Any]:
    """
    Парсит и проверяет initData из Telegram WebApp.
    Возвращает dict с полями (в т.ч. "user").
    """
    if not init_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="initData is empty",
        )

    parsed = urllib.parse.parse_qs(init_data, keep_blank_values=True)

    # hash от Telegram
    hash_from_telegram = parsed.get("hash", [""])[0]

    # Собираем data_check_string из всех пар, кроме hash
    data_check_pairs = []
    for key, values in parsed.items():
        if key == "hash":
            continue
        # берём первое значение
        value = values[0]
        data_check_pairs.append(f"{key}={value}")

    data_check_pairs.sort()
    data_check_string = "\n".join(data_check_pairs)

    # Секретный ключ: HMAC-SHA256(bot_token)
    secret_key = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode("utf-8")).digest()
    hmac_hash = hmac.new(
        secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if hmac_hash != hash_from_telegram:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid initData hash",
        )

    # Если всё ок — восстанавливаем user
    user_json = parsed.get("user", [""])[0]
    try:
        user_data = json.loads(user_json)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user JSON in initData",
        )

    result: Dict[str, Any] = {
        "user": user_data,
    }

    # Можно также положить сюда другие поля из initData при желании
    return result

