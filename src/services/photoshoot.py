# src/services/photoshoot.py

from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

import google.generativeai as genai
from aiogram import Bot
from aiogram.types import FSInputFile

from src.config import settings


logger = logging.getLogger(__name__)


# Конфигурируем Gemini один раз при импортe модуля
genai.configure(api_key=settings.GEMINI_API_KEY)

# Можно использовать быструю модель, которая умеет работать с изображениями
GEMINI_MODEL_NAME = "gemini-1.5-flash"


async def _download_telegram_photo(bot: Bot, file_id: str) -> bytes:
    """
    Скачивает файл из Telegram по file_id и возвращает байты.
    """
    tg_file = await bot.get_file(file_id)
    stream = await bot.download_file(tg_file.file_path)

    # stream может быть BytesIO или уже bytes
    if hasattr(stream, "read"):
        return stream.read()

    return stream


async def generate_photoshoot_image(
    style_title: str,
    user_photo_file_id: str,
    bot: Bot,
) -> FSInputFile:
    """
    1. Скачивает оригинальное селфи из Telegram.
    2. Отправляет в Gemini с промптом.
    3. Получает сгенерированную картинку.
    4. Сохраняет во временный файл и возвращает FSInputFile.
    """

    # 1. Скачиваем фото из Telegram
    try:
        original_photo_bytes = await _download_telegram_photo(bot, user_photo_file_id)
    except Exception as e:
        logger.exception("Ошибка при скачивании фото из Telegram: %s", e)
        raise RuntimeError("Не удалось скачать фото из Telegram") from e

    # 2. Формируем промпт
    prompt = (
        "Ты — нейросеть, которая профессионально обрабатывает портретные фотографии.\n"
        "Нужно превратить это селфи в фотосессию в стиле:\n"
        f"«{style_title}».\n\n"
        "Требования к результату:\n"
        "— сохранить лицо и основные черты пользователя;\n"
        "— сделать фон, освещение и обработку в указанном стиле;\n"
        "— итоговое изображение должно быть реалистичным, качественным, как из профессиональной фотостудии;\n"
        "— без надписей, логотипов и водяных знаков.\n"
    )

    # 3. Делаем запрос в Gemini
    try:
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)

        response = model.generate_content(
            [
                prompt,
                {
                    "mime_type": "image/jpeg",
                    "data": original_photo_bytes,
                },
            ],
            stream=False,
        )
    except Exception as e:
        logger.exception("Ошибка при запросе к Gemini: %s", e)
        raise RuntimeError("Сервис генерации фото сейчас недоступен") from e

    # 4. Достаём картинку из ответа
    image_bytes: Optional[bytes] = None

    try:
        # response.parts может содержать текст и изображения
        for part in response.parts:
            mime_type = getattr(part, "mime_type", "")
            if isinstance(mime_type, str) and mime_type.startswith("image/"):
                image_bytes = part.data
                break

        if not image_bytes:
            raise RuntimeError("Модель не вернула изображение")
    except Exception as e:
        logger.exception("Ошибка при обработке ответа Gemini: %s", e)
        raise RuntimeError("Не удалось обработать ответ от сервиса генерации") from e

    # 5. Сохраняем картинку во временный файл
    try:
        tmp_dir = tempfile.gettempdir()
        file_path = os.path.join(tmp_dir, f"photoshoot_{user_photo_file_id}.jpg")

        with open(file_path, "wb") as f:
            f.write(image_bytes)

        return FSInputFile(file_path)
    except Exception as e:
        logger.exception("Ошибка при сохранении сгенерированного фото: %s", e)
        raise RuntimeError("Не удалось сохранить сгенерированное фото") from e
