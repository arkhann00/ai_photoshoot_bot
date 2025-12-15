from __future__ import annotations

import base64
import logging
import os
import ssl
import struct
import tempfile
from typing import Optional, Sequence, Tuple

import aiohttp
import certifi
from aiogram import Bot
from aiogram.types import FSInputFile

from src.config import settings


logger = logging.getLogger(__name__)

COMET_BASE_URL = "https://api.cometapi.com"

# По скрину с 4K: используется gemini-3-pro-image-preview
DEFAULT_COMET_IMAGE_MODEL = "gemini-3-pro-image-preview"


def _get_comet_model_name() -> str:
    # Позволяет переопределить модель через settings, если у тебя там есть поле
    return getattr(settings, "COMET_IMAGE_MODEL_NAME", None) or DEFAULT_COMET_IMAGE_MODEL


def _get_comet_endpoint() -> str:
    model = _get_comet_model_name()
    return f"{COMET_BASE_URL}/v1beta/models/{model}:generateContent"


async def _download_telegram_photo(bot: Bot, file_id: str) -> bytes:
    """
    Скачивает фото из Telegram по file_id и возвращает байты.
    """
    tg_file = await bot.get_file(file_id)
    stream = await bot.download_file(tg_file.file_path)

    if hasattr(stream, "read"):
        return stream.read()

    return stream


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


def _parse_png_size(data: bytes) -> Optional[Tuple[int, int]]:
    # PNG: width/height лежат в IHDR (offset 16..24)
    if len(data) < 24:
        return None
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    try:
        w = struct.unpack(">I", data[16:20])[0]
        h = struct.unpack(">I", data[20:24])[0]
        if w > 0 and h > 0:
            return w, h
    except Exception:
        return None
    return None


def _parse_jpeg_size(data: bytes) -> Optional[Tuple[int, int]]:
    # JPEG: ищем SOF0/SOF2 и читаем размеры
    if len(data) < 4:
        return None
    if data[0:2] != b"\xFF\xD8":
        return None

    i = 2
    try:
        while i < len(data):
            # пропускаем padding FF
            while i < len(data) and data[i] == 0xFF:
                i += 1
            if i >= len(data):
                break

            marker = data[i]
            i += 1

            # маркеры без длины
            if marker in (0xD9, 0xDA):  # EOI, SOS
                break

            if i + 2 > len(data):
                break
            seg_len = struct.unpack(">H", data[i : i + 2])[0]
            if seg_len < 2:
                break

            # SOF0..SOF3, SOF5..SOF7, SOF9..SOF11, SOF13..SOF15
            if marker in (
                0xC0, 0xC1, 0xC2, 0xC3,
                0xC5, 0xC6, 0xC7,
                0xC9, 0xCA, 0xCB,
                0xCD, 0xCE, 0xCF,
            ):
                # внутри: [precision(1)] [height(2)] [width(2)] ...
                if i + 2 + 1 + 2 + 2 <= len(data):
                    h = struct.unpack(">H", data[i + 3 : i + 5])[0]
                    w = struct.unpack(">H", data[i + 5 : i + 7])[0]
                    if w > 0 and h > 0:
                        return w, h

            i += seg_len
    except Exception:
        return None

    return None


def _guess_aspect_ratio(image_bytes: bytes) -> str:
    """
    Поддерживаемые аспекты по скрину:
    1:1, 3:2, 2:3, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9
    """
    supported = [
        ("1:1", 1, 1),
        ("3:2", 3, 2),
        ("2:3", 2, 3),
        ("3:4", 3, 4),
        ("4:3", 4, 3),
        ("4:5", 4, 5),
        ("5:4", 5, 4),
        ("9:16", 9, 16),
        ("16:9", 16, 9),
        ("21:9", 21, 9),
    ]

    size = _parse_png_size(image_bytes) or _parse_jpeg_size(image_bytes)
    if not size:
        return "1:1"

    w, h = size
    if w <= 0 or h <= 0:
        return "1:1"

    r = w / h
    best_name = "1:1"
    best_diff = 10**9

    for name, aw, ah in supported:
        rr = aw / ah
        diff = abs(r - rr)
        if diff < best_diff:
            best_diff = diff
            best_name = name

    return best_name


async def generate_photoshoot_image(
    style_title: str,
    style_prompt: Optional[str],
    user_photo_file_ids: Sequence[str] | str | None = None,
    bot: Bot | None = None,
    # алиас для обратной совместимости (чтобы старые вызовы не падали)
    user_photo_file_id: str | None = None,
) -> FSInputFile:
    """
    Генерация фотосессии через CometAI.

    ВАЖНО: для 4K по документации нужен generationConfig.imageConfig.imageSize="4K"
    и пример использует модель gemini-3-pro-image-preview.
    """

    if bot is None:
        raise RuntimeError("Не передан bot в generate_photoshoot_image(...)")

    api_key = settings.COMET_API_KEY
    if not api_key:
        raise RuntimeError("COMET_API_KEY не задан в конфиге (settings.COMET_API_KEY).")

    # если передали старый аргумент — конвертим в новый
    if user_photo_file_ids is None and user_photo_file_id:
        user_photo_file_ids = user_photo_file_id

    if isinstance(user_photo_file_ids, str):
        file_ids_list = [user_photo_file_ids]
    else:
        file_ids_list = list(user_photo_file_ids or [])

    if not file_ids_list:
        raise RuntimeError("Не передано ни одного фото для генерации фотосессии.")

    if len(file_ids_list) > 3:
        raise RuntimeError("Можно использовать не более трёх фотографий для фотосессии.")

    # 1) Скачиваем входные фото
    photo_bytes_list: list[bytes] = []
    for file_id in file_ids_list:
        try:
            b = await _download_telegram_photo(bot, file_id)
        except Exception as e:
            logger.exception("Ошибка при скачивании фото из Telegram (file_id=%s): %s", file_id, e)
            raise RuntimeError("Не удалось скачать одно из фото из Telegram") from e
        photo_bytes_list.append(b)

    # 2) Определяем aspectRatio по первому фото (без Pillow)
    aspect_ratio = _guess_aspect_ratio(photo_bytes_list[0])

    # 3) Base64
    image_b64_list: list[str] = [base64.b64encode(b).decode("utf-8") for b in photo_bytes_list]

    prompt_text = _build_prompt(style_title=style_title, style_prompt=style_prompt)

    parts: list[dict] = [{"text": prompt_text}]
    for image_b64 in image_b64_list:
        parts.append(
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": image_b64,
                }
            }
        )

    # 4) ВАЖНО: 4K — через imageConfig.imageSize = "4K"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": parts,
            }
        ],
        "generationConfig": {
            # Можно оставить ["TEXT","IMAGE"], но чтобы не словить text-only — форсим IMAGE
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
                "imageSize": "4K",
            },
        },
    }

    # В доке встречаются оба способа. Шлём оба — API спокойно это переваривает.
    headers = {
        "Authorization": api_key,
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "*/*",
    }

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    endpoint = _get_comet_endpoint()

    # 5) Запрос
    data = None
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=300,
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
                        "CometAI вернул ошибку: status=%s, code=%s, message=%s, body=%s",
                        resp.status,
                        error_code,
                        error_message,
                        resp_text,
                    )

                    if resp.status == 403 and error_code == "insufficient_user_quota":
                        raise RuntimeError(
                            "На стороне сервиса генерации закончился оплаченный лимит. "
                            "Скоро всё починим — попробуй зайти позже 🙏"
                        )

                    raise RuntimeError("Сервис генерации фото сейчас недоступен. Попробуй позже.")
    except Exception as e:
        logger.exception("Ошибка при запросе к CometAI: %s", e)
        raise RuntimeError(str(e)) from e

    # 6) Разбор ответа (inlineData / inline_data)
    image_bytes: Optional[bytes] = None
    mime_type: str = "image/jpeg"

    try:
        if not isinstance(data, dict):
            raise RuntimeError("Ответ сервиса не в формате JSON")

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Сервис не вернул candidates")

        parts_response = candidates[0].get("content", {}).get("parts", []) or []
        for part in parts_response:
            inline_data = part.get("inlineData") or part.get("inline_data")
            if not inline_data:
                continue

            mime = inline_data.get("mimeType") or inline_data.get("mime_type")
            b64_data = inline_data.get("data")
            if not b64_data:
                continue

            mime_type = mime or mime_type
            image_bytes = base64.b64decode(b64_data)
            break

        if not image_bytes:
            raise RuntimeError("Не удалось получить изображение из ответа CometAI")
    except Exception as e:
        logger.exception("Ошибка при разборе ответа CometAI: %s", e)
        raise RuntimeError("Ошибка при обработке ответа сервиса генерации") from e

    # 7) Сохраняем
    try:
        tmp_dir = tempfile.gettempdir()

        ext = ".jpg"
        if "png" in (mime_type or "").lower():
            ext = ".png"
        elif "webp" in (mime_type or "").lower():
            ext = ".webp"

        file_id_for_name = file_ids_list[0]
        file_path = os.path.join(tmp_dir, f"photoshoot_{file_id_for_name}{ext}")

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return FSInputFile(file_path)
    except Exception as e:
        logger.exception("Ошибка при сохранении сгенерированного фото: %s", e)
        raise RuntimeError("Не удалось сохранить сгенерированное фото") from e
