from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import re
import ssl
import tempfile
import time
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Sequence, Union, Dict, Any

import aiohttp
import certifi
from aiogram import Bot
from aiogram.types import FSInputFile

from src.config import settings

logger = logging.getLogger(__name__)

# Константы
APIYI_BASE_URL = "https://api.apiyi.com"
APIYI_MODEL_NAME_DEFAULT = "gemini-3-pro-image-preview"
DEFAULT_TIMEOUT_SECONDS = 120
MAX_INPUT_PHOTOS = 2  # Уменьшено для стабильности
MAX_GENERATION_RETRIES = 5  # Уменьшено количество попыток
RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 120.0
RETRY_BACKOFF_MULTIPLIER = 2.0

# Глобальные ограничители
_api_semaphore = None
_rate_limit_semaphore = None


class ImageSize(Enum):
    SIZE_1K = "1K"
    SIZE_2K = "2K"
    SIZE_4K = "4K"


class APIErrorType(Enum):
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    NETWORK = "network"
    AUTH = "auth"
    VALIDATION = "validation"


@dataclass
class APIRequestConfig:
    """Конфигурация запроса к API"""
    timeout: int = DEFAULT_TIMEOUT_SECONDS
    max_retries: int = MAX_GENERATION_RETRIES
    image_size: ImageSize = ImageSize.SIZE_2K  # По умолчанию 2K для стабильности
    max_concurrent: int = 3  # Максимум одновременных запросов
    use_safety_settings: bool = True


def _get_api_semaphore() -> asyncio.Semaphore:
    """Получение глобального семафора для ограничения запросов"""
    global _api_semaphore
    if _api_semaphore is None:
        max_concurrent = getattr(settings, "APIYI_MAX_CONCURRENT", 3)
        _api_semaphore = asyncio.Semaphore(max_concurrent)
    return _api_semaphore


def _get_rate_limit_semaphore() -> asyncio.Semaphore:
    """Семафор для ограничения запросов при rate limit"""
    global _rate_limit_semaphore
    if _rate_limit_semaphore is None:
        _rate_limit_semaphore = asyncio.Semaphore(1)
    return _rate_limit_semaphore


def _detect_mime_type(image_bytes: bytes) -> str:
    """Определение MIME-типа изображения"""
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    if image_bytes.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return "image/jpeg"


def _split_file_ids(user_photo_file_id: str) -> List[str]:
    """Разделение строки с file_id на список"""
    raw = (user_photo_file_id or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[\s,;|]+", raw) if p.strip()]
    return parts


def _normalize_input_file_ids(
    user_photo_file_id: Optional[str],
    user_photo_file_ids: Optional[Union[Sequence[str], str]],
) -> List[str]:
    """Нормализация входных file_id"""
    out: List[str] = []

    if user_photo_file_id:
        out.extend(_split_file_ids(user_photo_file_id))

    if user_photo_file_ids:
        if isinstance(user_photo_file_ids, str):
            out.extend(_split_file_ids(user_photo_file_ids))
        else:
            for x in user_photo_file_ids:
                if x and str(x).strip():
                    out.append(str(x).strip())

    seen = set()
    uniq: List[str] = []
    for fid in out:
        if fid in seen:
            continue
        seen.add(fid)
        uniq.append(fid)

    return uniq


def _safe_slug(value: str, max_len: int = 80) -> str:
    """Создание безопасного имени файла"""
    s = re.sub(r"[^0-9A-Za-z_-]+", "_", value).strip("_")
    if not s:
        s = "img"
    return s[:max_len]


async def _download_telegram_photo(bot: Bot, file_id: str) -> bytes:
    """Скачивание фото из Telegram"""
    try:
        tg_file = await bot.get_file(file_id)
        stream = await bot.download_file(tg_file.file_path)
        return stream.read() if hasattr(stream, "read") else stream
    except Exception as e:
        logger.error(f"Ошибка скачивания фото {file_id}: {e}")
        raise RuntimeError(f"Не удалось скачать фото: {e}")


def _build_prompt(style_title: str, style_prompt: Optional[str]) -> str:
    """Сборка промпта"""
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


def _calculate_retry_delay(attempt: int, error_type: APIErrorType = None) -> float:
    """Расчет задержки для повторной попытки"""
    if error_type == APIErrorType.RATE_LIMIT:
        # Для rate limit ждем дольше
        base_delay = min(30 * attempt, 300)  # До 5 минут
    elif error_type == APIErrorType.SERVER_ERROR:
        # Для серверных ошибок умеренная задержка
        base_delay = RETRY_BASE_DELAY_SECONDS * (RETRY_BACKOFF_MULTIPLIER ** (attempt - 1))
        base_delay = min(base_delay, 60)
    else:
        # Стандартный exponential backoff
        base_delay = RETRY_BASE_DELAY_SECONDS * (RETRY_BACKOFF_MULTIPLIER ** (attempt - 1))
    
    base_delay = min(base_delay, RETRY_MAX_DELAY_SECONDS)
    
    # Добавляем jitter (0-25%)
    jitter = random.uniform(0, base_delay * 0.25)
    delay = base_delay + jitter
    
    logger.debug(f"Задержка для попытки {attempt}: {delay:.1f} сек")
    return delay


def _create_safety_settings() -> List[Dict[str, str]]:
    """Создание настроек безопасности"""
    return [
        {
            "category": "HARM_CATEGORY_HARASSMENT",
            "threshold": "BLOCK_NONE"
        },
        {
            "category": "HARM_CATEGORY_HATE_SPEECH", 
            "threshold": "BLOCK_NONE"
        },
        {
            "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
            "threshold": "BLOCK_NONE"
        },
        {
            "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
            "threshold": "BLOCK_NONE"
        }
    ]


def _create_payload(parts: List[Dict], image_size: ImageSize, use_safety: bool = True) -> Dict[str, Any]:
    """Создание payload для запроса"""
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": "3:4",
                "imageSize": image_size.value,
            },
        },
    }
    
    if use_safety:
        payload["safetySettings"] = _create_safety_settings()
    
    return payload


async def _make_api_request(
    endpoint: str,
    payload: Dict,
    headers: Dict,
    config: APIRequestConfig,
    attempt: int,
    session: aiohttp.ClientSession
) -> Dict:
    """Выполнение запроса к API с обработкой ошибок"""
    start_time = time.time()
    
    try:
        async with session.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=config.timeout)
        ) as resp:
            
            response_time = time.time() - start_time
            resp_text = await resp.text()
            
            logger.debug(f"API ответ за {response_time:.2f} сек, статус: {resp.status}")
            
            # Обработка успешного ответа
            if resp.status == 200:
                try:
                    return await resp.json()
                except Exception as e:
                    logger.error(f"Ошибка парсинга JSON: {e}, текст ответа: {resp_text[:200]}")
                    raise RuntimeError("Некорректный ответ от сервера API")
            
            # Обработка rate limit (429)
            if resp.status == 429:
                retry_after = resp.headers.get("Retry-After", "60")
                try:
                    wait_time = float(retry_after)
                except ValueError:
                    wait_time = _calculate_retry_delay(attempt, APIErrorType.RATE_LIMIT)
                
                logger.warning(
                    f"Rate limit (попытка {attempt}/{config.max_retries}): "
                    f"status={resp.status}, waiting {wait_time:.1f} сек"
                )
                
                async with _get_rate_limit_semaphore():
                    await asyncio.sleep(wait_time)
                
                raise RuntimeError(f"Rate limit, пробуем снова")
            
            # Обработка server errors (500, 502, 503, 504)
            if resp.status in (500, 502, 503, 504):
                logger.warning(
                    f"Server error (попытка {attempt}/{config.max_retries}): "
                    f"status={resp.status}, response: {resp_text[:200]}"
                )
                raise RuntimeError(f"Серверная ошибка {resp.status}")
            
            # Обработка client errors (400, 401, 403, 404)
            if resp.status in (400, 401, 403, 404):
                error_info = resp_text[:200]
                logger.error(f"Client error: status={resp.status}, response: {error_info}")
                
                if resp.status == 401:
                    raise RuntimeError("Ошибка авторизации API. Проверьте ключ.")
                elif resp.status == 403:
                    raise RuntimeError("Доступ запрещен. Проверьте лимиты API.")
                elif resp.status == 400:
                    raise RuntimeError("Некорректный запрос к API.")
                else:
                    raise RuntimeError(f"Ошибка клиента: {resp.status}")
            
            # Обработка других статусов
            logger.error(f"Неизвестный статус {resp.status}: {resp_text[:200]}")
            raise RuntimeError(f"Неизвестная ошибка API: {resp.status}")
    
    except asyncio.TimeoutError:
        response_time = time.time() - start_time
        logger.warning(f"Timeout (попытка {attempt}): запрос занял {response_time:.1f} сек")
        raise RuntimeError(f"Таймаут запроса ({config.timeout} сек)")
    
    except aiohttp.ClientError as e:
        logger.error(f"Сетевая ошибка (попытка {attempt}): {e}")
        raise RuntimeError(f"Сетевая ошибка: {str(e)}")


async def generate_photoshoot_image(
    style_title: str,
    style_prompt: Optional[str] = None,
    user_photo_file_id: Optional[str] = None,
    bot: Optional[Bot] = None,
    user_photo_file_ids: Optional[Union[Sequence[str], str]] = None,
) -> FSInputFile:
    """
    Генерация фотосессии через APIYI с улучшенной обработкой ошибок.
    
    Args:
        style_title: Название стиля
        style_prompt: Кастомный промпт (опционально)
        user_photo_file_id: File_id фото или строка с несколькими file_id
        bot: Экземпляр бота Telegram
        user_photo_file_ids: Список или строка с file_id
        
    Returns:
        FSInputFile: Сгенерированное изображение
        
    Raises:
        RuntimeError: При ошибках генерации
    """
    
    # Валидация входных параметров
    if bot is None:
        raise RuntimeError("Параметр bot не передан в generate_photoshoot_image().")
    
    # Получение конфигурации API
    api_key = getattr(settings, "APIYI_API_KEY", None) or getattr(settings, "COMET_API_KEY", None)
    if not api_key:
        raise RuntimeError("API ключ не задан. Укажите settings.APIYI_API_KEY или settings.COMET_API_KEY.")
    
    model_name = getattr(settings, "APIYI_MODEL_NAME", None) or APIYI_MODEL_NAME_DEFAULT
    endpoint = f"{APIYI_BASE_URL}/v1beta/models/{model_name}:generateContent"
    
    # Конфигурация запроса
    config = APIRequestConfig(
        timeout=int(getattr(settings, "APIYI_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)),
        max_retries=int(getattr(settings, "APIYI_MAX_RETRIES", MAX_GENERATION_RETRIES)),
        image_size=ImageSize(getattr(settings, "APIYI_IMAGE_SIZE", "2K")),
        max_concurrent=int(getattr(settings, "APIYI_MAX_CONCURRENT", 3)),
        use_safety_settings=getattr(settings, "APIYI_USE_SAFETY", True)
    )
    
    # Нормализация входных file_id
    file_ids = _normalize_input_file_ids(
        user_photo_file_id=user_photo_file_id,
        user_photo_file_ids=user_photo_file_ids
    )
    
    if not file_ids:
        raise RuntimeError("Не передан file_id фото пользователя.")
    
    if len(file_ids) > MAX_INPUT_PHOTOS:
        logger.warning(f"Слишком много фото ({len(file_ids)}), ограничиваю до {MAX_INPUT_PHOTOS}")
        file_ids = file_ids[:MAX_INPUT_PHOTOS]
    
    # Скачивание фото из Telegram
    photos_bytes: List[bytes] = []
    for fid in file_ids:
        try:
            b = await _download_telegram_photo(bot, fid)
            photos_bytes.append(b)
            
            # Проверка размера фото
            if len(b) > 10 * 1024 * 1024:  # 10MB
                logger.warning(f"Фото {fid} слишком большое: {len(b)/1024/1024:.1f}MB")
        except Exception as e:
            logger.exception(f"Ошибка скачивания фото {fid}: {e}")
            raise RuntimeError(f"Не удалось скачать фото: {e}")
    
    # Подготовка промпта
    prompt_text = _build_prompt(style_title=style_title, style_prompt=style_prompt)
    
    # Сборка частей запроса
    parts = [{"text": prompt_text}]
    for b in photos_bytes:
        mime_type_in = _detect_mime_type(b)
        image_b64 = base64.b64encode(b).decode("utf-8")
        parts.append({
            "inline_data": {
                "mime_type": mime_type_in,
                "data": image_b64,
            }
        })
    
    # Создание payload
    current_image_size = config.image_size
    payload = _create_payload(parts, current_image_size, config.use_safety_settings)
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "PhotoshootBot/1.0"
    }
    
    # Подготовка SSL контекста
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    
    # Основной цикл с попытками
    last_error = None
    data = None
    
    # Используем семафор для ограничения одновременных запросов
    async with _get_api_semaphore():
        for attempt in range(1, config.max_retries + 1):
            logger.info(f"Попытка генерации {attempt}/{config.max_retries}")
            
            # Динамическое уменьшение размера при ошибках
            if attempt > 1 and current_image_size != ImageSize.SIZE_1K:
                if current_image_size == ImageSize.SIZE_4K:
                    current_image_size = ImageSize.SIZE_2K
                    logger.info(f"Уменьшаю размер изображения до {current_image_size.value}")
                    payload = _create_payload(parts, current_image_size, config.use_safety_settings)
                elif current_image_size == ImageSize.SIZE_2K:
                    current_image_size = ImageSize.SIZE_1K
                    logger.info(f"Уменьшаю размер изображения до {current_image_size.value}")
                    payload = _create_payload(parts, current_image_size, config.use_safety_settings)
            
            # Создание новой сессии для каждой попытки
            connector = aiohttp.TCPConnector(
                ssl=ssl_context,
                limit=10,
                ttl_dns_cache=300
            )
            
            try:
                async with aiohttp.ClientSession(
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(total=config.timeout)
                ) as session:
                    
                    data = await _make_api_request(
                        endpoint=endpoint,
                        payload=payload,
                        headers=headers,
                        config=config,
                        attempt=attempt,
                        session=session
                    )
                    
                    # Успешный запрос
                    logger.info(f"Успешная генерация на попытке {attempt}")
                    break
                    
            except RuntimeError as e:
                last_error = e
                error_msg = str(e)
                
                # Фатальные ошибки - не повторяем
                if any(fatal in error_msg.lower() for fatal in ["авторизации", "доступ запрещен", "некорректный запрос"]):
                    logger.error(f"Фатальная ошибка: {error_msg}")
                    raise e
                
                # Последняя попытка
                if attempt == config.max_retries:
                    logger.error(f"Все попытки исчерпаны. Последняя ошибка: {error_msg}")
                    raise RuntimeError(
                        f"Не удалось сгенерировать изображение после {config.max_retries} попыток. "
                        f"Попробуйте позже или выберите другой стиль."
                    )
                
                # Рассчет задержки для повторной попытки
                error_type = APIErrorType.SERVER_ERROR
                if "rate" in error_msg.lower():
                    error_type = APIErrorType.RATE_LIMIT
                elif "таймаут" in error_msg.lower() or "timeout" in error_msg.lower():
                    error_type = APIErrorType.TIMEOUT
                
                wait_time = _calculate_retry_delay(attempt, error_type)
                logger.info(f"Повтор через {wait_time:.1f} сек...")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                last_error = e
                logger.exception(f"Неожиданная ошибка на попытке {attempt}: {e}")
                
                if attempt == config.max_retries:
                    raise RuntimeError(
                        f"Неожиданная ошибка генерации. Попробуйте позже."
                    )
                
                wait_time = _calculate_retry_delay(attempt, APIErrorType.SERVER_ERROR)
                await asyncio.sleep(wait_time)
    
    # Обработка успешного ответа
    if not data:
        raise RuntimeError("Пустой ответ от API")
    
    # Извлечение изображения из ответа
    image_bytes = None
    mime_type_out = "image/jpeg"
    
    try:
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("API не вернул результатов генерации")
        
        # Берем первый кандидат
        candidate = candidates[0]
        
        # Проверка safety ratings
        if candidate.get("safetyRatings"):
            safety_issues = [
                rating for rating in candidate["safetyRatings"]
                if rating.get("probability") in ["HIGH", "MEDIUM"]
            ]
            if safety_issues:
                logger.warning(f"Обнаружены safety issues: {safety_issues}")
        
        # Извлечение изображения
        parts_out = candidate.get("content", {}).get("parts", [])
        for part in parts_out:
            if not isinstance(part, dict):
                continue
            
            inline_data = part.get("inlineData") or part.get("inline_data")
            if inline_data and isinstance(inline_data, dict):
                mime = inline_data.get("mimeType") or inline_data.get("mime_type")
                b64_data = inline_data.get("data")
                
                if b64_data:
                    mime_type_out = mime or mime_type_out
                    image_bytes = base64.b64decode(b64_data)
                    break
        
        if not image_bytes:
            raise RuntimeError("Не удалось извлечь изображение из ответа API")
        
        logger.info(f"Изображение получено: {len(image_bytes)} bytes, тип: {mime_type_out}")
        
    except Exception as e:
        logger.exception(f"Ошибка обработки ответа API: {e}")
        raise RuntimeError("Ошибка обработки сгенерированного изображения")
    
    # Сохранение во временный файл
    try:
        # Определение расширения
        ext_map = {
            "image/png": ".png",
            "image/webp": ".webp",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg"
        }
        ext = ext_map.get(mime_type_out.lower(), ".jpg")
        
        # Создание уникального имени файла
        timestamp = int(time.time())
        joined_ids = "_".join(file_ids[:2])  # Берем только первые 2 ID для читаемости
        slug = _safe_slug(joined_ids, 50)
        suffix = f"{len(file_ids)}p_{timestamp}"
        
        tmp_dir = tempfile.gettempdir()
        file_path = os.path.join(tmp_dir, f"photoshoot_{slug}_{suffix}{ext}")
        
        # Сохранение файла
        with open(file_path, "wb") as f:
            f.write(image_bytes)
        
        logger.info(f"Изображение сохранено: {file_path} ({len(image_bytes)/1024/1024:.1f} MB)")
        
        # Проверка существования файла
        if not os.path.exists(file_path):
            raise RuntimeError("Не удалось сохранить файл")
        
        return FSInputFile(file_path)
        
    except Exception as e:
        logger.exception(f"Ошибка сохранения изображения: {e}")
        
        # Очистка временных файлов при ошибке
        if 'file_path' in locals() and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        
        raise RuntimeError("Ошибка сохранения сгенерированного изображения")


# Опционально: функция для очистки старых временных файлов
async def cleanup_temp_files(max_age_hours: int = 24):
    """Очистка старых временных файлов"""
    try:
        tmp_dir = tempfile.gettempdir()
        now = time.time()
        removed = 0
        
        for filename in os.listdir(tmp_dir):
            if filename.startswith("photoshoot_"):
                filepath = os.path.join(tmp_dir, filename)
                try:
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > max_age_hours * 3600:
                        os.remove(filepath)
                        removed += 1
                except Exception as e:
                    logger.debug(f"Не удалось удалить {filename}: {e}")
        
        if removed > 0:
            logger.info(f"Очищено {removed} временных файлов")
            
    except Exception as e:
        logger.error(f"Ошибка очистки временных файлов: {e}")