from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import ssl
import tempfile
from typing import Optional, List, Sequence, Union

import aiohttp
import certifi
from aiogram import Bot
from aiogram.types import FSInputFile

from src.config import settings


logger = logging.getLogger(__name__)

# Провайдер (APIYI)
APIYI_BASE_URL = "https://api.apiyi.com"

# Модель по умолчанию: поддержка 1K/2K/4K (обычно)
APIYI_MODEL_NAME_DEFAULT = "gemini-3-pro-image-preview"

# 4K может занимать дольше
DEFAULT_TIMEOUT_SECONDS = 800

# Ограничение по твоему требованию
MAX_INPUT_PHOTOS = 3

MAX_GENERATION_RETRIES = 10
RETRY_DELAY_SECONDS = 1  # можно 1-10 сек, чтобы не долбить API без пауз


def _detect_mime_type(image_bytes: bytes) -> str:
    """
    Простейшее определение mime-типа по сигнатуре файла.
    """
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return "image/jpeg"


def _split_file_ids(user_photo_file_id: str) -> List[str]:
    """
    Позволяет передавать 1..3 file_id одной строкой:
    - "id1"
    - "id1,id2"
    - "id1 id2 id3"
    - "id1\nid2\nid3"
    - "id1;id2|id3"
    """
    raw = (user_photo_file_id or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[\s,;|]+", raw) if p.strip()]
    return parts


def _normalize_input_file_ids(
    user_photo_file_id: Optional[str],
    user_photo_file_ids: Optional[Union[Sequence[str], str]],
) -> List[str]:
    """
    Приводит вход к списку file_id, поддерживает:
    - user_photo_file_id: str (один или "id1 id2")
    - user_photo_file_ids: list[str] / tuple[str] / str
    """
    out: List[str] = []

    # 1) старый параметр (строка с разделителями)
    if user_photo_file_id:
        out.extend(_split_file_ids(user_photo_file_id))

    # 2) новый параметр (список или строка)
    if user_photo_file_ids:
        if isinstance(user_photo_file_ids, str):
            out.extend(_split_file_ids(user_photo_file_ids))
        else:
            for x in user_photo_file_ids:
                if x and str(x).strip():
                    out.append(str(x).strip())

    # дедуп, сохраняя порядок
    seen = set()
    uniq: List[str] = []
    for fid in out:
        if fid in seen:
            continue
        seen.add(fid)
        uniq.append(fid)

    return uniq


def _safe_slug(value: str, max_len: int = 80) -> str:
    """
    Безопасный кусок для имени файла (temp).
    """
    s = re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_")
    if not s:
        s = "img"
    return s[:max_len]


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
    Формируем итоговый текст промпта.
    Если есть кастомный prompt для стиля — используем его,
    иначе собираем базовый вариант по названию стиля.
    """
    if style_prompt:
        return style_prompt

    return (
        "Преврати это(эти) селфи в профессиональную фотосессию.\n"
        f"Стиль: «{style_title}».\n"
        "Сохрани черты лица пользователя и идентичность на всех вариантах, "
        "сделай свет, фон и обработку в указанном стиле, "
        "без надписей и логотипов, качественное реалистичное изображение.\n"
        "Если прислано несколько фото, используй их как референсы одного и того же человека, "
        "чтобы улучшить сходство и детализацию."
    )


async def generate_photoshoot_image(
    style_title: str,
    style_prompt: Optional[str] = None,
    user_photo_file_id: Optional[str] = None,
    bot: Optional[Bot] = None,
    user_photo_file_ids: Optional[Union[Sequence[str], str]] = None,
) -> FSInputFile:
    """
    Генерация фотосессии через APIYI (Google-формат generateContent).

    Совместимость по входу:
    - Можно передавать ОДНО фото через user_photo_file_id="id"
    - Можно передавать 1..3 фото через user_photo_file_id="id1 id2"
    - Можно передавать список 1..3 фото через user_photo_file_ids=[id1, id2, id3]
    - Можно передавать строку через user_photo_file_ids="id1,id2"

    Запрашиваем 4K в ответ (если модель/тариф поддерживают).
    """

    if bot is None:
        raise RuntimeError("Параметр bot не передан в generate_photoshoot_image().")

    # Совместимость: ключ можно хранить в COMET_API_KEY (как раньше),
    # либо завести отдельный APIYI_API_KEY.
    api_key = getattr(settings, "APIYI_API_KEY", None) or getattr(settings, "COMET_API_KEY", None)
    if not api_key:
        raise RuntimeError("API ключ не задан. Укажи settings.APIYI_API_KEY или settings.COMET_API_KEY.")

    model_name = getattr(settings, "APIYI_MODEL_NAME", None) or APIYI_MODEL_NAME_DEFAULT
    endpoint = f"{APIYI_BASE_URL}/v1beta/models/{model_name}:generateContent"

    timeout_seconds = int(getattr(settings, "APIYI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))

    # 0) Разбираем вход: 1..3 file_id
    file_ids = _normalize_input_file_ids(user_photo_file_id=user_photo_file_id, user_photo_file_ids=user_photo_file_ids)
    if not file_ids:
        raise RuntimeError("Не передан file_id фото пользователя (user_photo_file_id/user_photo_file_ids).")
    if len(file_ids) > MAX_INPUT_PHOTOS:
        file_ids = file_ids[:MAX_INPUT_PHOTOS]

    # 1) Скачиваем 1..3 фото из Telegram
    photos_bytes: List[bytes] = []
    try:
        for fid in file_ids:
            b = await _download_telegram_photo(bot, fid)
            photos_bytes.append(b)
    except Exception as e:
        logger.exception("Ошибка при скачивании фото из Telegram: %s", e)
        raise RuntimeError("Не удалось скачать фото из Telegram") from e

    prompt_text = _build_prompt(style_title=style_title, style_prompt=style_prompt)

    # 2) Собираем parts: сначала текст, затем 1..3 inline_data
    parts = [{"text": prompt_text}]
    for b in photos_bytes:
        mime_type_in = _detect_mime_type(b)
        image_b64 = base64.b64encode(b).decode("utf-8")
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime_type_in,
                    "data": image_b64,
                }
            }
        )

    # 3) Просим 4K (важно: модель должна поддерживать 4K)
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": "3:4",
                "imageSize": "4K",
            },
        },
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }

    # SSL
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context)

    data = None
    resp_text = ""

        # 4) Запрос (10 попыток)
    last_exc: Exception | None = None
    last_resp_text: str = ""
    last_data = None

    # если хочешь "ждать сколько угодно" — отключаем таймаут
    # (если в settings задано число > 0 — можно оставить число)
    timeout: aiohttp.ClientTimeout | int
    if timeout_seconds <= 0:
        timeout = aiohttp.ClientTimeout(total=None, connect=None, sock_read=None, sock_connect=None)
    else:
        timeout = timeout_seconds

    for attempt in range(1, MAX_GENERATION_RETRIES + 1):
        data = None
        resp_text = ""

        try:
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=timeout,
                ) as resp:
                    resp_text = await resp.text()
                    try:
                        data = await resp.json()
                    except Exception:
                        data = None

                    # Неуспешный HTTP статус
                    if resp.status != 200:
                        error_code = None
                        error_message = None
                        if isinstance(data, dict):
                            err = data.get("error") or {}
                            error_code = err.get("code")
                            error_message = err.get("message")

                        logger.error(
                            "APIYI ошибка (attempt %s/%s): status=%s, code=%s, message=%s, body=%s",
                            attempt, MAX_GENERATION_RETRIES,
                            resp.status, error_code, error_message, resp_text,
                        )

                        # Эти ошибки бессмысленно ретраить (обычно)
                        if error_message and ("imageSize" in error_message or "4K" in error_message):
                            raise RuntimeError(
                                "Сервис отклонил запрос 4K (imageSize=4K). "
                                "Проверь модель/тариф или попробуй модель, которая поддерживает 4K."
                            )

                        if resp.status in (401, 403):
                            raise RuntimeError(
                                "Сервис генерации отклонил запрос (ключ/квота/доступ). "
                                "Проверь API ключ и лимиты."
                            )

                        # Остальное — считаем временной ошибкой и ретраим
                        raise RuntimeError(f"APIYI вернул статус {resp.status}")

            # если дошли сюда — HTTP 200 и JSON (или хотя бы resp_text) получены
            last_resp_text = resp_text
            last_data = data
            break

        except asyncio.CancelledError:
            # если приложение закрывается — не ретраим
            raise

        except Exception as e:
            last_exc = e
            last_resp_text = resp_text
            last_data = data

            # если это “фатальная” ошибка — не гоняем 10 раз
            msg = str(e)
            if "отклонил запрос 4K" in msg or "ключ/квота/доступ" in msg:
                logger.exception("Фатальная ошибка, ретраи не помогут: %s", e)
                raise

            logger.exception(
                "Ошибка при запросе к APIYI (attempt %s/%s): %s",
                attempt, MAX_GENERATION_RETRIES, e,
            )

            if attempt >= MAX_GENERATION_RETRIES:
                raise RuntimeError(f"Не удалось сгенерировать изображение после {MAX_GENERATION_RETRIES} попыток: {e}") from e

    # после цикла используем last_data/last_resp_text
    data = last_data
    resp_text = last_resp_text

    # 5) Достаём картинку
    image_bytes: Optional[bytes] = None
    mime_type_out: str = "image/jpeg"

    try:
        if not isinstance(data, dict):
            logger.error("Некорректный ответ (не JSON). body=%s", resp_text)
            raise RuntimeError("Сервис вернул некорректный ответ")

        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Сервис не вернул кандидатов изображения")

        parts_out = candidates[0].get("content", {}).get("parts", [])
        if not isinstance(parts_out, list):
            parts_out = []

        for part in parts_out:
            if not isinstance(part, dict):
                continue

            inline_data = part.get("inlineData") or part.get("inline_data")
            if not inline_data or not isinstance(inline_data, dict):
                continue

            mime = inline_data.get("mimeType") or inline_data.get("mime_type")
            b64_data = inline_data.get("data")
            if not b64_data:
                continue

            mime_type_out = mime or mime_type_out
            image_bytes = base64.b64decode(b64_data)
            break

        if not image_bytes:
            raise RuntimeError("Не удалось получить изображение из ответа сервиса")
    except Exception as e:
        logger.exception("Ошибка при разборе ответа APIYI: %s", e)
        raise RuntimeError("Ошибка при обработке ответа сервиса генерации") from e

    # 6) Сохраняем во временный файл
    try:
        tmp_dir = tempfile.gettempdir()
        ext = ".jpg"
        if "png" in mime_type_out:
            ext = ".png"
        elif "webp" in mime_type_out:
            ext = ".webp"

        # безопасное имя
        joined_ids = "_".join(file_ids)
        slug = _safe_slug(joined_ids)

        suffix = f"{len(file_ids)}p"
        file_path = os.path.join(tmp_dir, f"photoshoot_{slug}_{suffix}{ext}")

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return FSInputFile(file_path)
    except Exception as e:
        logger.exception("Ошибка при сохранении сгенерированного фото: %s", e)
        raise RuntimeError("Не удалось сохранить сгенерированное фото") from e