# src/services/photoshoot_webapp.py

from __future__ import annotations

import base64
import logging
import os
import ssl
import tempfile
from typing import Optional

import aiohttp
import certifi
from aiogram.types import FSInputFile  # можно не использовать, если возвращаем путь/URL

from src.config import settings
from src.services.photoshoot import _build_prompt  # переиспользуем существующий


logger = logging.getLogger(__name__)

COMET_BASE_URL = "https://api.cometapi.com"
COMET_MODEL_NAME = "gemini-3-pro-image"
COMET_ENDPOINT = f"{COMET_BASE_URL}/v1beta/models/{COMET_MODEL_NAME}:generateContent"


async def generate_photoshoot_image_from_bytes(
    style_title: str,
    style_prompt: Optional[str],
    image_bytes: bytes,
) -> str:
    """
    Генерация фотосессии для WebApp.

    Возвращает путь к сохраненному файлу (на диске сервера).
    """
    api_key = settings.COMET_API_KEY
    if not api_key:
        raise RuntimeError("COMET_API_KEY не задан в конфиге.")

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
            "responseModalities": ["IMAGE"],
        },
    }

    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
        "Accept": "*/*",
    }

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

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
                logger.error(
                    "CometAI error: status=%s body=%s",
                    resp.status,
                    resp_text,
                )
                raise RuntimeError("Сервис генерации сейчас недоступен.")

    image_bytes_out: Optional[bytes] = None
    mime_type: str = "image/jpeg"

    try:
        candidates = data.get("candidates") or []
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
            image_bytes_out = base64.b64decode(b64_data)
            break

        if not image_bytes_out:
            raise RuntimeError("Не удалось получить изображение из ответа CometAI")
    except Exception as e:
        logger.exception("Ошибка при разборе ответа CometAI: %s", e)
        raise RuntimeError("Ошибка при обработке ответа сервиса") from e

    tmp_dir = tempfile.gettempdir()
    ext = ".jpg"
    if "png" in mime_type:
        ext = ".png"
    elif "webp" in mime_type:
        ext = ".webp"

    file_path = os.path.join(
        tmp_dir,
        f"photoshoot_webapp_{os.getpid()}_{os.urandom(4).hex()}{ext}",
    )
    with open(file_path, "wb") as f:
        f.write(image_bytes_out)

    return file_path
