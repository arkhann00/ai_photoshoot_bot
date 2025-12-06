from __future__ import annotations

import base64
import logging
import ssl
from typing import Optional, Tuple

import aiohttp
import certifi

from src.config import settings


logger = logging.getLogger(__name__)

COMET_BASE_URL = "https://api.cometapi.com"
COMET_MODEL_NAME = "gemini-3-pro-image"
COMET_ENDPOINT = f"{COMET_BASE_URL}/v1beta/models/{COMET_MODEL_NAME}:generateContent"


def _build_prompt(style_title: str, style_prompt: Optional[str]) -> str:
    """
    Формируем итоговый текст промпта для CometAI.
    Если есть кастомный prompt для стиля — используем его,
    иначе собираем базовый вариант по названию стиля.
    """
    if style_prompt:
        return style_prompt

    return (
        "Преврати это селфи в профессиональную фотосессию.\n"
        f"Стиль: «{style_title}».\n"
        "Сохрани черты лица пользователя, сделай свет, фон и обработку в указанном стиле, "
        "без надписей и логотипов, качественное реалистичное изображение."
    )


async def generate_photoshoot_image_from_bytes(
    style_title: str,
    style_prompt: Optional[str],
    image_bytes: bytes,
) -> Tuple[bytes, str]:
    """
    Генерация фотосессии через CometAI по байтам исходного изображения.
    Возвращает (image_bytes, mime_type).
    """

    api_key = settings.COMET_API_KEY
    if not api_key:
        raise RuntimeError("COMET_API_KEY не задан в конфиге (settings.COMET_API_KEY).")

    # 1. Кодируем исходное фото в Base64
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    prompt_text = _build_prompt(style_title=style_title, style_prompt=style_prompt)

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt_text},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_b64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "responseModalities": [
                "IMAGE",
            ]
        },
    }

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "*/*",
    }

    # SSL-контекст
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                COMET_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=120,
            ) as resp:
                resp_text = await resp.text()

                try:
                    data = await resp.json()
                except Exception:
                    data = None

                if resp.status != 200:
                    error_code = None
                    error_message = None
                    if isinstance(data, dict):
                        err = data.get("error") or {}
                        error_code = err.get("code")
                        error_message = err.get("message")

                    logger.error(
                        "CometAI вернул ошибку: status=%s, body=%s",
                        resp.status,
                        resp_text,
                    )

                    if resp.status == 403 and error_code == "insufficient_user_quota":
                        raise RuntimeError(
                            "На стороне сервиса генерации закончился оплаченный лимит. "
                            "Скоро всё починим — попробуй зайти позже 🙏"
                        )

                    raise RuntimeError(
                        f"Сервис генерации фото сейчас недоступен. Попробуй позже. "
                        f"(status={resp.status}, message={error_message})"
                    )
    except Exception as e:
        logger.exception("Ошибка при запросе к CometAI: %s", e)
        raise RuntimeError(str(e)) from e

    # Разбираем ответ и достаём картинку
    result_image_bytes: Optional[bytes] = None
    mime_type: str = "image/jpeg"

    try:
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Сервис не вернул кандидатов изображения")

        parts = candidates[0].get("content", {}).get("parts", [])

        for part in parts:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not inline_data:
                continue

            mime = inline_data.get("mimeType") or inline_data.get("mime_type")
            b64_data = inline_data.get("data")
            if not b64_data:
                continue

            mime_type = mime or mime_type
            result_image_bytes = base64.b64decode(b64_data)
            break

        if not result_image_bytes:
            raise RuntimeError("Не удалось получить изображение из ответа CometAI")
    except Exception as e:
        logger.exception("Ошибка при разборе ответа CometAI: %s", e)
        raise RuntimeError("Ошибка при обработке ответа сервиса генерации") from e

    return result_image_bytes, mime_type
