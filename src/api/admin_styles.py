# src/api/admin_styles.py
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from src.paths import IMG_DIR

ALLOWED_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/webp"}


async def save_uploaded_image(upload: UploadFile, prefix: str) -> str:
    """
    Аккуратно сохраняем загруженную картинку.
    Поддерживаем только JPEG/PNG/WEBP.
    Возвращаем имя файла (без пути).
    """
    contents = await upload.read()
    if not contents:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Файл картинки пустой.",
        )

    mime = upload.content_type or ""
    if mime not in ALLOWED_IMAGE_MIME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Поддерживаются только JPEG/PNG/WEBP. "
                "Экспортируй фото из телефона в JPG/PNG и загрузи ещё раз."
            ),
        )

    original_name = upload.filename or ""
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTS:
        ext = ".jpg"

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{prefix}_{uuid4().hex}{ext}"
    full_path = IMG_DIR / filename

    with open(full_path, "wb") as f:
        f.write(contents)
    print("FILE NAME: ", filename)
    return filename

