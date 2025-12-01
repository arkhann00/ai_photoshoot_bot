from __future__ import annotations

from typing import Any, Dict, List, Optional

import os
from pathlib import Path
from uuid import uuid4

from fastapi import (
    FastAPI,
    Depends,
    Header,
    HTTPException,
    UploadFile,
    File,
    Form,
    Query,
)
from fastapi.responses import JSONResponse

from sqlalchemy import select

from src.db import (
    async_session,
    User,
    StylePrompt,
    PhotoshootStatus,
    create_style_prompt,
    get_photoshoot_report,
    get_payments_report,
    log_photoshoot,
)
from src.paths import IMG_DIR
from src.webapp_auth import parse_telegram_init_data
from src.services.photoshoot_webapp import generate_photoshoot_image_from_bytes


app = FastAPI(title="Photoshoot Bot WebApp API")


# -------------------------------------------------------------------
# Общие зависимости: текущий пользователь и админ
# -------------------------------------------------------------------


async def get_current_user(
    x_telegram_init_data: str = Header(alias="X-Telegram-Init-Data"),
) -> User:
    """
    Достаём данные пользователя из initData Telegram WebApp и создаём/находим его в БД.
    """
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="Missing X-Telegram-Init-Data header")

    parsed = parse_telegram_init_data(x_telegram_init_data)
    tg_user: Dict[str, Any] = parsed["user"]

    telegram_id = tg_user["id"]
    username = tg_user.get("username")

    from src.db import get_or_create_user

    user = await get_or_create_user(telegram_id=telegram_id, username=username)
    return user


async def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """
    Проверка, что пользователь админ.
    Если нет — возвращаем 403.
    """
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


# -------------------------------------------------------------------
# Health-check, чтобы проверить, что бэк вообще жив
# -------------------------------------------------------------------


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# -------------------------------------------------------------------
# /api/me — информация о текущем пользователе
# -------------------------------------------------------------------


@app.get("/api/me")
async def api_me(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return {
        "telegram_id": user.telegram_id,
        "username": user.username,
        "balance": user.balance,
        "photoshoot_credits": user.photoshoot_credits,
        "is_admin": user.is_admin,
    }


# -------------------------------------------------------------------
# Загрузка картинки для стиля из WebApp
# -------------------------------------------------------------------


@app.post("/api/styles/upload-image")
async def api_upload_style_image(
    file: UploadFile = File(...),
    admin: User = Depends(get_current_admin),
) -> Dict[str, str]:
    """
    Загрузка картинки для стиля из мини-аппа.
    Принимает multipart/form-data с полем "file".
    Возвращает имя файла, который потом нужно указать в image_filename.
    """
    content_type = file.content_type or ""

    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Можно загружать только файлы изображений",
        )

    original_filename = file.filename or ""
    ext_from_name = Path(original_filename).suffix.lower()

    allowed_exts = [".jpg", ".jpeg", ".png", ".webp"]
    if ext_from_name not in allowed_exts:
        # Если расширение не из списка — принудительно делаем .jpg
        ext_from_name = ".jpg"

    unique_name = f"style_{uuid4().hex}{ext_from_name}"
    full_path = IMG_DIR / unique_name

    os.makedirs(IMG_DIR, exist_ok=True)

    file_bytes = await file.read()

    with open(full_path, "wb") as f:
        f.write(file_bytes)

    return {"image_filename": unique_name}


# -------------------------------------------------------------------
# Стили: список / создание / обновление / удаление
# -------------------------------------------------------------------


@app.get("/api/styles")
async def api_list_styles(
    user: User = Depends(get_current_user),
    include_inactive: bool = Query(False),
) -> List[Dict[str, Any]]:
    """
    Список стилей.
    Обычным пользователям отдаём только активные.
    Админ при include_inactive=true получает все.
    """
    async with async_session() as session:
        stmt = select(StylePrompt)
        if not (user.is_admin and include_inactive):
            stmt = stmt.where(StylePrompt.is_active == True)  # noqa: E712

        stmt = stmt.order_by(StylePrompt.id.asc())
        result = await session.execute(stmt)
        styles: List[StylePrompt] = list(result.scalars().all())

    return [
        {
            "id": s.id,
            "title": s.title,
            "description": s.description,
            "prompt": s.prompt,
            "image_filename": s.image_filename,
            "is_active": s.is_active,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in styles
    ]


from pydantic import BaseModel


class StyleCreate(BaseModel):
    title: str
    description: str
    prompt: str
    image_filename: str
    is_active: bool = True


@app.post("/api/styles")
async def api_create_style(
    payload: StyleCreate,
    admin: User = Depends(get_current_admin),
) -> Dict[str, Any]:
    style = await create_style_prompt(
        title=payload.title,
        description=payload.description,
        prompt=payload.prompt,
        image_filename=payload.image_filename,
    )

    # при необходимости можно сразу обновить is_active
    if style.is_active != payload.is_active:
        async with async_session() as session:
            db_style = await session.get(StylePrompt, style.id)
            if db_style:
                db_style.is_active = payload.is_active
                await session.commit()
                await session.refresh(db_style)
                style = db_style

    return {
        "id": style.id,
        "title": style.title,
        "description": style.description,
        "prompt": style.prompt,
        "image_filename": style.image_filename,
        "is_active": style.is_active,
    }


class StyleUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    image_filename: Optional[str] = None
    is_active: Optional[bool] = None


@app.put("/api/styles/{style_id}")
async def api_update_style(
    style_id: int,
    payload: StyleUpdate,
    admin: User = Depends(get_current_admin),
) -> Dict[str, Any]:
    async with async_session() as session:
        style = await session.get(StylePrompt, style_id)
        if style is None:
            raise HTTPException(status_code=404, detail="Style not found")

        if payload.title is not None:
            style.title = payload.title
        if payload.description is not None:
            style.description = payload.description
        if payload.prompt is not None:
            style.prompt = payload.prompt
        if payload.image_filename is not None:
            style.image_filename = payload.image_filename
        if payload.is_active is not None:
            style.is_active = payload.is_active

        await session.commit()
        await session.refresh(style)

    return {
        "id": style.id,
        "title": style.title,
        "description": style.description,
        "prompt": style.prompt,
        "image_filename": style.image_filename,
        "is_active": style.is_active,
    }


@app.delete("/api/styles/{style_id}")
async def api_delete_style(
    style_id: int,
    admin: User = Depends(get_current_admin),
) -> Dict[str, bool]:
    async with async_session() as session:
        style = await session.get(StylePrompt, style_id)
        if style is None:
            raise HTTPException(status_code=404, detail="Style not found")

        await session.delete(style)
        await session.commit()

    return {"ok": True}


# -------------------------------------------------------------------
# Отчёт для админки
# -------------------------------------------------------------------


@app.get("/api/admin/report")
async def api_admin_report(
    days: int = 7,
    admin: User = Depends(get_current_admin),
) -> Dict[str, Any]:
    photos = await get_photoshoot_report(days=days)
    payments = await get_payments_report(days=days)

    return {
        "photoshoots": photos,
        "payments": payments,
    }


# -------------------------------------------------------------------
# Генерация фотосессии из WebApp
# -------------------------------------------------------------------


@app.post("/api/photoshoots/generate")
async def api_generate_photoshoot(
    style_id: int = Form(...),
    photo: UploadFile = File(...),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Генерация фотосессии из WebApp:
    - style_id
    - загруженное фото
    """
    async with async_session() as session:
        style = await session.get(StylePrompt, style_id)
        if style is None or not style.is_active:
            raise HTTPException(
                status_code=400,
                detail="Style not found or inactive",
            )

    image_bytes = await photo.read()

    try:
        file_path = await generate_photoshoot_image_from_bytes(
            style_title=style.title,
            style_prompt=style.prompt,
            image_bytes=image_bytes,
        )

        await log_photoshoot(
            telegram_id=user.telegram_id,
            style_title=style.title,
            status=PhotoshootStatus.success,
            cost_rub=0,
            cost_credits=0,
            provider="comet_gemini_3_pro_webapp",
        )
    except Exception as e:
        await log_photoshoot(
            telegram_id=user.telegram_id,
            style_title=style.title,
            status=PhotoshootStatus.failed,
            cost_rub=0,
            cost_credits=0,
            provider="comet_gemini_3_pro_webapp",
            error_message=str(e),
        )
        raise HTTPException(
            status_code=500,
            detail="Ошибка генерации изображения",
        ) from e

    # TODO: лучше отдавать именно URL (например, /generated/...)
    return {"file_path": file_path}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.webapp_api:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
