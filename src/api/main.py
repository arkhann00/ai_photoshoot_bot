# src/api/main.py
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Optional, List
from urllib.parse import parse_qsl

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    Header,
    UploadFile,
    File,
    Form,
    Query,
    Request,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from src.config import settings
from src.paths import IMG_DIR
from src.data.styles import PHOTOSHOOT_PRICE
from src.services.web_photoshoot import generate_photoshoot_image_from_bytes
from src.api import admin_styles
from src.db.repositories.promo_codes import (
    create_promo_code,
    list_promo_codes,
    set_promo_code_active,
    delete_promo_code,
    get_promo_code_by_code,
)
from src.db.repositories.users import (get_all_users, clear_user_balance)
from src.db import (
    async_session,
    get_or_create_user,
    get_all_style_prompts,
    get_style_prompt_by_id,
    get_users_page,
    search_users,
    change_user_credits,
    change_user_balance,
    get_photoshoot_report,
    get_payments_report,
    log_photoshoot,
    PhotoshootStatus,
    delete_style_prompt,
    get_user_avatars,
    delete_user_avatar,
    get_all_style_categories,
    get_styles_by_category_and_gender,
    get_style_categories_for_gender,
    StyleGender,
    create_style_category,
    create_style_prompt,
    StyleCategory,
    StylePrompt,
    consume_photoshoot_credit_or_balance,
    get_style_category_by_id,
    get_all_user_stats,
    get_admin_users,
    set_user_admin_flag,
    set_user_referral_flag,
    User,
    clear_users_statistics,
)

# -------------------------------------------------------------------
# Общая настройка приложения
# -------------------------------------------------------------------

app = FastAPI(
    title="AI Photoshoot API",
    version="1.0.0",
    description="HTTP API для бота ИИ-фотосессий и мини-аппы.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://62.113.42.113:5173",
        "http://localhost:5173",
        "https://aiphotostudio.ru",
        "https://www.aiphotostudio.ru",
        "https://admin.aiphotostudio.ru",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/static/img",
    StaticFiles(directory=str(IMG_DIR)),
    name="styles_images",
)

# В dev-режиме можно принудительно сделать всех админами
DEBUG_FORCE_ADMIN = True

PUBLIC_API_BASE_URL = "https://api.aiphotostudio.ru"

# -------------------------------------------------------------------
# Модели / схемы
# -------------------------------------------------------------------


class TelegramWebAppUser(BaseModel):
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    language_code: Optional[str] = None
    is_premium: Optional[bool] = None


class CurrentUser(BaseModel):
    telegram_id: int
    username: Optional[str]
    is_admin: bool
    balance: int
    photoshoot_credits: int


class MeResponse(BaseModel):
    telegram_id: int
    username: Optional[str]
    balance: int
    photoshoot_credits: int
    is_admin: bool
    referral_url: Optional[str]


class AvatarResponse(BaseModel):
    id: int
    file_id: str
    source_style_title: Optional[str]


class StyleCategoryResponse(BaseModel):
    id: int
    title: str
    description: str
    image_filename: str
    image_url: str
    is_active: bool
    gender: str


class StyleResponse(BaseModel):
    id: int
    title: str
    description: str
    prompt: str
    image_filename: Optional[str] = None
    image_url: Optional[str] = None
    is_active: bool
    category_id: int
    gender: str
    is_new: bool
    usage_count: int = 0


class PhotoshootResponse(BaseModel):
    style_id: int
    style_title: str
    cost_rub: int
    used_credits: bool


class AdminUserResponse(BaseModel):
    telegram_id: int
    username: Optional[str]
    balance: int
    photoshoot_credits: int
    is_admin: bool
    created_at: Optional[str] = None


class AdminUsersPageResponse(BaseModel):
    page: int
    page_size: int
    total: int
    items: List[AdminUserResponse]


class ChangeValueRequest(BaseModel):
    delta: int


class AdminFlagRequest(BaseModel):
    is_admin: bool


class AdminReferralFlagRequest(BaseModel):
    telegram_id: Optional[int] = None
    username: Optional[str] = None
    is_referral: bool


class AdminReportPhotosResponse(BaseModel):
    days: int
    total: int
    success: int
    failed: int
    sum_cost_rub: int
    sum_cost_credits: int


class AdminReportPaymentsResponse(BaseModel):
    days: int
    total: int
    sum_stars: int
    sum_credits: int


class AdminReportResponse(BaseModel):
    photos: AdminReportPhotosResponse
    payments: AdminReportPaymentsResponse


class AdminUserStats(BaseModel):
    telegram_id: int
    username: Optional[str]
    spent_rub: int
    photos_success: int
    photos_failed: int
    last_photoshoot_at: Optional[str]


class AdminReferralResponse(BaseModel):
    telegram_id: int
    username: Optional[str]
    referrals_count: int
    earned_rub: int


class StyleCategoryWithStylesResponse(StyleCategoryResponse):
    styles: List[StyleResponse]


class CatalogStyleResponse(BaseModel):
    id: int
    title: str
    description: str
    prompt: str
    image_filename: Optional[str] = None
    image_url: str
    is_active: bool
    category_id: int
    gender: str
    is_new: bool
    usage_count: int = 0


class CatalogCategoryResponse(BaseModel):
    id: int
    title: str
    description: str
    image_filename: str
    image_url: str
    is_active: bool
    gender: str
    styles: List[CatalogStyleResponse]


class CatalogResponse(BaseModel):
    gender: str
    categories: List[CatalogCategoryResponse]


class AdminClearStatsRequest(BaseModel):
    confirm: str
    clear_logs: bool = True


class PromoCodeResponse(BaseModel):
    id: int
    code: str
    is_active: bool
    generations: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class AdminPromoCodeCreateRequest(BaseModel):
    code: str
    generations: int = 1
    is_active: bool = True


class AdminPromoCodeSetActiveRequest(BaseModel):
    is_active: bool


# -------------------------------------------------------------------
# Telegram initData
# -------------------------------------------------------------------

from fastapi.responses import FileResponse

@app.get("/api/images/{filename}")
async def get_image(filename: str):
    path = IMG_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(path)


def _img_url(request: Request, filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    base = PUBLIC_API_BASE_URL.rstrip("/")
    return f"{base}/static/img/{filename}"


def _parse_init_data(init_data: str) -> dict:
    pairs = parse_qsl(init_data, strict_parsing=True)
    return {k: v for k, v in pairs}


def _verify_telegram_init_data(init_data: str) -> TelegramWebAppUser:
    if not init_data:
        raise HTTPException(status_code=401, detail="Missing init_data")

    data = _parse_init_data(init_data)

    received_hash = data.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Missing hash in init_data")

    data_check_string_parts = []
    for key in sorted(data.keys()):
        value = data[key]
        data_check_string_parts.append(f"{key}={value}")
    data_check_string = "\n".join(data_check_string_parts)

    secret_key = hashlib.sha256(settings.BOT_TOKEN.encode("utf-8")).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="Invalid init_data hash")

    user_json = data.get("user")
    if not user_json:
        raise HTTPException(status_code=401, detail="No user field in init_data")

    try:
        user_dict = json.loads(user_json)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid user JSON in init_data")

    try:
        tg_user = TelegramWebAppUser(**user_dict)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid user data in init_data")

    return tg_user


# -------------------------------------------------------------------
# Текущий пользователь и проверка админа
# -------------------------------------------------------------------


async def get_current_user(
    x_telegram_init_data: Optional[str] = Header(default=None, alias="X-Telegram-Init-Data"),
    x_debug_user_id: Optional[int] = Header(default=None, alias="X-Debug-User-Id"),
) -> CurrentUser:
    if x_telegram_init_data:
        tg_user = _verify_telegram_init_data(x_telegram_init_data)
        telegram_id = tg_user.id
        username = tg_user.username
    else:
        if x_debug_user_id is not None:
            telegram_id = x_debug_user_id
            username = None
        else:
            telegram_id = 707366569
            username = "dev_user"

    user = await get_or_create_user(telegram_id=telegram_id, username=username)

    is_admin_flag = bool(getattr(user, "is_admin", False))
    if DEBUG_FORCE_ADMIN:
        is_admin_flag = True

    return CurrentUser(
        telegram_id=user.telegram_id,
        username=user.username,
        is_admin=is_admin_flag,
        balance=user.balance,
        photoshoot_credits=user.photoshoot_credits,
    )


def ensure_admin(user: CurrentUser) -> None:
    if DEBUG_FORCE_ADMIN:
        return
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")


# -------------------------------------------------------------------
# Служебный эндпоинт
# -------------------------------------------------------------------


@app.get("/api/health")
async def health_check() -> dict:
    return {"status": "ok"}


# -------------------------------------------------------------------
# Профиль пользователя и аватары
# -------------------------------------------------------------------


@app.get("/api/me", response_model=MeResponse)
async def get_me(user: CurrentUser = Depends(get_current_user)) -> MeResponse:
    bot_username = settings.BOT_USERNAME
    referral_url: Optional[str] = None
    if bot_username:
        referral_url = f"https://t.me/{bot_username}?start={user.telegram_id}"

    return MeResponse(
        telegram_id=user.telegram_id,
        username=user.username,
        balance=user.balance,
        photoshoot_credits=user.photoshoot_credits,
        is_admin=user.is_admin,
        referral_url=referral_url,
    )


@app.get("/api/me/avatars", response_model=List[AvatarResponse])
async def list_user_avatars(user: CurrentUser = Depends(get_current_user)) -> List[AvatarResponse]:
    avatars = await get_user_avatars(user.telegram_id)
    return [
        AvatarResponse(id=a.id, file_id=a.file_id, source_style_title=a.source_style_title)
        for a in avatars
    ]


@app.delete("/api/me/avatars/{avatar_id}")
async def delete_user_avatar_endpoint(
    avatar_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    ok = await delete_user_avatar(user.telegram_id, avatar_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Аватар не найден или уже удалён")
    return JSONResponse({"status": "ok"})


# -------------------------------------------------------------------
# Генерация фотосессии из веб-аппы
# -------------------------------------------------------------------


@app.post("/api/photoshoots/generate")
async def generate_photoshoot_from_upload(
    style_id: int = Form(...),
    photo: UploadFile = File(...),
    user: CurrentUser = Depends(get_current_user),
):
    style = await get_style_prompt_by_id(style_id)
    if style is None or (not style.is_active):
        raise HTTPException(status_code=404, detail="Стиль не найден или неактивен")

    photo_bytes = await photo.read()
    if not photo_bytes:
        raise HTTPException(status_code=400, detail="Файл изображения пустой")

    cost_rub = 0
    used_credits = False

    if not user.is_admin:
        can_pay = await consume_photoshoot_credit_or_balance(
            telegram_id=user.telegram_id,
            price_rub=PHOTOSHOOT_PRICE,
        )
        if not can_pay:
            raise HTTPException(
                status_code=402,
                detail=(
                    "Недостаточно средств: ни фотосессий, ни рублёвого баланса. "
                    f"Текущая цена: {PHOTOSHOOT_PRICE} ₽."
                ),
            )
        cost_rub = PHOTOSHOOT_PRICE
        used_credits = False

    try:
        generated_bytes, mime_type = await generate_photoshoot_image_from_bytes(
            style_title=style.title,
            style_prompt=style.prompt,
            image_bytes=photo_bytes,
        )
        await log_photoshoot(
            telegram_id=user.telegram_id,
            style_title=style.title,
            status=PhotoshootStatus.success,
            cost_rub=cost_rub,
            cost_credits=0,
            provider="comet_gemini_3_pro_image",
            error_message=None,
        )
    except Exception as e:
        await log_photoshoot(
            telegram_id=user.telegram_id,
            style_title=style.title,
            status=PhotoshootStatus.failed,
            cost_rub=cost_rub,
            cost_credits=0,
            provider="comet_gemini_3_pro_image",
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail="Ошибка при генерации фотосессии. Попробуй позже.")

    return Response(content=generated_bytes, media_type=mime_type or "image/jpeg")


# -------------------------------------------------------------------
# Пользователи — админка
# -------------------------------------------------------------------



async def admin_list_users(
    page: int = Query(0, ge=0),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
) -> AdminUsersPageResponse:
    ensure_admin(user)
    users, total = await get_users_page(page=page, page_size=page_size)

    items: List[AdminUserResponse] = []
    for u in users:
        created_at_str = u.created_at.isoformat() if getattr(u, "created_at", None) is not None else None
        items.append(
            AdminUserResponse(
                telegram_id=u.telegram_id,
                username=u.username,
                balance=u.balance,
                photoshoot_credits=u.photoshoot_credits,
                is_admin=getattr(u, "is_admin", False),
                created_at=created_at_str,
            )
        )

    return AdminUsersPageResponse(page=page, page_size=page_size, total=total, items=items)


@app.get("/api/admin/users/search", response_model=List[AdminUserResponse])
async def admin_search_users(
    q: str = Query(..., min_length=1),
    user: CurrentUser = Depends(get_current_user),
) -> List[AdminUserResponse]:
    ensure_admin(user)
    users = await search_users(q)

    result: List[AdminUserResponse] = []
    for u in users:
        created_at_str = u.created_at.isoformat() if getattr(u, "created_at", None) is not None else None
        result.append(
            AdminUserResponse(
                telegram_id=u.telegram_id,
                username=u.username,
                balance=u.balance,
                photoshoot_credits=u.photoshoot_credits,
                is_admin=getattr(u, "is_admin", False),
                created_at=created_at_str,
            )
        )
    return result


@app.get("/api/admin/users/all", response_model=List[AdminUserResponse])
async def admin_get_all_users(user: CurrentUser = Depends(get_current_user)) -> List[AdminUserResponse]:
    ensure_admin(user)

    users = await get_all_users()

    result: List[AdminUserResponse] = []
    for u in users:
        created_at_str = u.created_at.isoformat() if getattr(u, "created_at", None) is not None else None
        result.append(
            AdminUserResponse(
                telegram_id=u.telegram_id,
                username=u.username,
                balance=int(u.balance or 0),
                photoshoot_credits=int(u.photoshoot_credits or 0),
                is_admin=bool(getattr(u, "is_admin", False)),
                created_at=created_at_str,
            )
        )

    return result


@app.post("/api/admin/users/{telegram_id}/balance/clear", response_model=AdminUserResponse)
async def admin_clear_user_balance(
    telegram_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> AdminUserResponse:
    ensure_admin(user)

    updated = await clear_user_balance(telegram_id=telegram_id)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    created_at_str = updated.created_at.isoformat() if getattr(updated, "created_at", None) is not None else None
    return AdminUserResponse(
        telegram_id=updated.telegram_id,
        username=updated.username,
        balance=updated.balance,
        photoshoot_credits=updated.photoshoot_credits,
        is_admin=getattr(updated, "is_admin", False),
        created_at=created_at_str,
    )


@app.post("/api/admin/users/{telegram_id}/credits", response_model=AdminUserResponse)
async def admin_change_user_credits(
    telegram_id: int,
    body: ChangeValueRequest,
    user: CurrentUser = Depends(get_current_user),
) -> AdminUserResponse:
    ensure_admin(user)

    updated = await change_user_credits(telegram_id=telegram_id, delta=body.delta)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    created_at_str = updated.created_at.isoformat() if getattr(updated, "created_at", None) is not None else None
    return AdminUserResponse(
        telegram_id=updated.telegram_id,
        username=updated.username,
        balance=updated.balance,
        photoshoot_credits=updated.photoshoot_credits,
        is_admin=getattr(updated, "is_admin", False),
        created_at=created_at_str,
    )


@app.post("/api/admin/users/{telegram_id}/balance", response_model=AdminUserResponse)
async def admin_change_user_balance(
    telegram_id: int,
    body: ChangeValueRequest,
    user: CurrentUser = Depends(get_current_user),
) -> AdminUserResponse:
    ensure_admin(user)

    updated = await change_user_balance(telegram_id=telegram_id, delta=body.delta)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    created_at_str = updated.created_at.isoformat() if getattr(updated, "created_at", None) is not None else None
    return AdminUserResponse(
        telegram_id=updated.telegram_id,
        username=updated.username,
        balance=updated.balance,
        photoshoot_credits=updated.photoshoot_credits,
        is_admin=getattr(updated, "is_admin", False),
        created_at=created_at_str,
    )

# src/api/main.py

from typing import List

@app.get("/api/admin/users/search", response_model=List[AdminUserResponse])
async def admin_search_users_endpoint(
    q: str = Query(..., min_length=1),
    limit: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
) -> List[AdminUserResponse]:
    ensure_admin(user)

    users = await search_users(q, limit=limit)

    result: List[AdminUserResponse] = []
    for u in users:
        created_at_str = u.created_at.isoformat() if getattr(u, "created_at", None) else None
        result.append(
            AdminUserResponse(
                telegram_id=u.telegram_id,
                username=u.username,
                balance=int(u.balance or 0),
                photoshoot_credits=int(u.photoshoot_credits or 0),
                is_admin=bool(getattr(u, "is_admin", False)),
                created_at=created_at_str,
            )
        )

    return result

@app.get("/api/admin/report", response_model=AdminReportResponse)
async def admin_report(
    days: int = Query(7, ge=1, le=365),
    user: CurrentUser = Depends(get_current_user),
) -> AdminReportResponse:
    ensure_admin(user)

    photos = await get_photoshoot_report(days=days)
    payments = await get_payments_report(days=days)

    return AdminReportResponse(
        photos=AdminReportPhotosResponse(
            days=photos["days"],
            total=photos["total"],
            success=photos["success"],
            failed=photos["failed"],
            sum_cost_rub=photos["sum_cost_rub"],
            sum_cost_credits=photos["sum_cost_credits"],
        ),
        payments=AdminReportPaymentsResponse(
            days=payments["days"],
            total=payments["total"],
            sum_stars=payments["sum_stars"],
            sum_credits=payments["sum_credits"],
        ),
    )


# -------------------------------------------------------------------
# Категории и стили — публичное API для фронта
# -------------------------------------------------------------------


@app.get("/api/style-categories", response_model=List[StyleCategoryResponse])
async def api_style_categories(
    request: Request,
    gender: Optional[str] = Query(default=None),
) -> List[StyleCategoryResponse]:
    if gender is None:
        categories = await get_all_style_categories(include_inactive=False)
    else:
        try:
            gender_enum = StyleGender(gender)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid gender (use: male/female)")
        categories = await get_style_categories_for_gender(gender_enum)

    return [
        StyleCategoryResponse(
            id=c.id,
            title=c.title,
            description=c.description,
            image_filename=c.image_filename,
            image_url=_img_url(request, c.image_filename) or "",
            is_active=c.is_active,
            gender=c.gender.value,
        )
        for c in categories
    ]


@app.get("/api/styles", response_model=List[StyleResponse])
async def api_styles(
    request: Request,
    category_id: int = Query(..., ge=1),
    gender: str = Query(...),
) -> List[StyleResponse]:
    try:
        gender_enum = StyleGender(gender)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid gender (use: male/female)")

    styles = await get_styles_by_category_and_gender(category_id=category_id, gender=gender_enum)

    return [
        StyleResponse(
            id=s.id,
            title=s.title,
            description=s.description,
            prompt=s.prompt,
            image_filename=s.image_filename,
            image_url=_img_url(request, s.image_filename),
            is_active=s.is_active,
            category_id=s.category_id,
            gender=s.gender.value,
            is_new=bool(getattr(s, "is_new", False)),
            usage_count=int(getattr(s, "usage_count", 0) or 0),
        )
        for s in styles
    ]


@app.get("/api/catalog", response_model=CatalogResponse)
async def api_catalog(
    request: Request,
    gender: str = Query(default="male"),
) -> CatalogResponse:
    try:
        gender_enum = StyleGender(gender)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid gender. Use male or female")

    categories = await get_style_categories_for_gender(gender_enum)

    result_categories: List[CatalogCategoryResponse] = []
    for c in categories:
        styles = await get_styles_by_category_and_gender(category_id=c.id, gender=gender_enum)

        cat_image_url = _img_url(request, c.image_filename) or ""

        styles_out: List[CatalogStyleResponse] = []
        for s in styles:
            styles_out.append(
                CatalogStyleResponse(
                    id=s.id,
                    title=s.title,
                    description=s.description,
                    prompt=s.prompt,
                    image_filename=s.image_filename,
                    image_url=_img_url(request, s.image_filename) or "",
                    is_active=s.is_active,
                    category_id=s.category_id,
                    gender=s.gender.value,
                    is_new=bool(getattr(s, "is_new", False)),
                    usage_count=int(getattr(s, "usage_count", 0) or 0),
                )
            )

        result_categories.append(
            CatalogCategoryResponse(
                id=c.id,
                title=c.title,
                description=c.description,
                image_filename=c.image_filename,
                image_url=cat_image_url,
                is_active=c.is_active,
                gender=c.gender.value,
                styles=styles_out,
            )
        )

    return CatalogResponse(gender=gender_enum.value, categories=result_categories)


# -------------------------------------------------------------------
# Категории и стили — админка
# -------------------------------------------------------------------


@app.get("/api/admin/style-categories", response_model=List[StyleCategoryResponse])
async def admin_list_style_categories(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> List[StyleCategoryResponse]:
    ensure_admin(user)
    categories = await get_all_style_categories(include_inactive=True)

    return [
        StyleCategoryResponse(
            id=c.id,
            title=c.title,
            description=c.description,
            image_filename=c.image_filename,
            image_url=_img_url(request, c.image_filename) or "",
            is_active=c.is_active,
            gender=c.gender.value,
        )
        for c in categories
    ]


@app.post("/api/admin/style-categories", response_model=StyleCategoryResponse)
async def admin_create_style_category_endpoint(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    gender: str = Form(...),
    image: UploadFile | None = File(None),
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(get_current_user),
) -> StyleCategoryResponse:
    ensure_admin(user)

    try:
        gender_enum = StyleGender(gender)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid gender")

    upload = image or file
    if upload is None:
        raise HTTPException(status_code=400, detail="Image file is required")

    image_filename = await admin_styles.save_uploaded_image(upload, prefix="category")

    category = await create_style_category(
        title=title,
        description=description,
        image_filename=image_filename,
        gender=gender_enum,
        is_active=True,
    )

    return StyleCategoryResponse(
        id=category.id,
        title=category.title,
        description=category.description,
        image_filename=category.image_filename,
        image_url=_img_url(request, category.image_filename) or "",
        is_active=category.is_active,
        gender=category.gender.value,
    )


@app.put("/api/admin/style-categories/{category_id}", response_model=StyleCategoryResponse)
async def admin_update_style_category_endpoint(
    request: Request,
    category_id: int,
    title: str | None = Form(None),
    description: str | None = Form(None),
    gender: str | None = Form(None),
    image: UploadFile | None = File(None),
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(get_current_user),
) -> StyleCategoryResponse:
    ensure_admin(user)

    async with async_session() as session:
        db_category = await session.get(StyleCategory, category_id)
        if db_category is None:
            raise HTTPException(status_code=404, detail="Category not found")

        if title is not None:
            db_category.title = title
        if description is not None:
            db_category.description = description
        if gender is not None:
            try:
                gender_enum = StyleGender(gender)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid gender")
            db_category.gender = gender_enum

        upload = image or file
        if upload is not None:
            image_filename = await admin_styles.save_uploaded_image(upload, prefix="category")
            db_category.image_filename = image_filename

        await session.commit()
        await session.refresh(db_category)

    return StyleCategoryResponse(
        id=db_category.id,
        title=db_category.title,
        description=db_category.description,
        image_filename=db_category.image_filename,
        image_url=_img_url(request, db_category.image_filename) or "",
        is_active=db_category.is_active,
        gender=db_category.gender.value,
    )


@app.get("/api/admin/styles", response_model=List[StyleResponse])
async def admin_list_styles(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> List[StyleResponse]:
    ensure_admin(user)
    styles = await get_all_style_prompts(include_inactive=True)

    result: List[StyleResponse] = []
    for s in styles:
        result.append(
            StyleResponse(
                id=s.id,
                title=s.title,
                description=s.description,
                prompt=s.prompt,
                image_filename=s.image_filename,
                image_url=_img_url(request, s.image_filename),
                is_active=s.is_active,
                category_id=s.category_id,
                gender=s.gender.value,
                is_new=bool(getattr(s, "is_new", False)),
                usage_count=int(getattr(s, "usage_count", 0) or 0),
            )
        )
    return result


@app.post("/api/admin/styles", response_model=StyleResponse)
async def admin_create_style_endpoint(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    prompt: str = Form(""),
    category_id: int = Form(...),
    is_new: bool = Form(False),
    new: Optional[bool] = Form(None),
    image: UploadFile | None = File(None),
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(get_current_user),
) -> StyleResponse:
    ensure_admin(user)

    effective_is_new = bool(new) if new is not None else bool(is_new)

    category = await get_style_category_by_id(category_id)
    if category is None:
        raise HTTPException(status_code=400, detail="Category not found")

    upload = image or file
    if upload is None:
        raise HTTPException(status_code=400, detail="Image file is required")

    image_filename = await admin_styles.save_uploaded_image(upload, prefix="style")

    style = await create_style_prompt(
        title=title,
        description=description,
        prompt=prompt,
        image_filename=image_filename,
        category_id=category_id,
    )

    # выставляем is_new
    async with async_session() as session:
        db_style = await session.get(StylePrompt, style.id)
        if db_style is not None and hasattr(db_style, "is_new"):
            db_style.is_new = effective_is_new
            await session.commit()
            await session.refresh(db_style)
            style = db_style

    return StyleResponse(
        id=style.id,
        title=style.title,
        description=style.description,
        prompt=style.prompt,
        image_filename=style.image_filename,
        image_url=_img_url(request, style.image_filename),
        is_active=style.is_active,
        category_id=style.category_id,
        gender=style.gender.value,
        is_new=bool(getattr(style, "is_new", False)),
        usage_count=int(getattr(style, "usage_count", 0) or 0),
    )


@app.put("/api/admin/styles/{style_id}", response_model=StyleResponse)
async def admin_update_style_endpoint(
    request: Request,
    style_id: int,
    title: str = Form(...),
    description: str = Form(""),
    prompt: str = Form(""),
    category_id: int = Form(...),
    is_new: Optional[bool] = Form(None),
    new: Optional[bool] = Form(None),
    image: UploadFile | None = File(None),
    file: UploadFile | None = File(None),
    user: CurrentUser = Depends(get_current_user),
) -> StyleResponse:
    ensure_admin(user)

    effective_is_new: Optional[bool] = None
    if new is not None:
        effective_is_new = bool(new)
    elif is_new is not None:
        effective_is_new = bool(is_new)

    async with async_session() as session:
        db_style = await session.get(StylePrompt, style_id)
        if db_style is None:
            raise HTTPException(status_code=404, detail="Style not found")

        res = await session.execute(select(StyleCategory).where(StyleCategory.id == category_id))
        category = res.scalar_one_or_none()
        if category is None:
            raise HTTPException(status_code=400, detail="Category not found")

        db_style.title = title
        db_style.description = description
        db_style.prompt = prompt
        db_style.category_id = category.id
        db_style.gender = category.gender

        if effective_is_new is not None and hasattr(db_style, "is_new"):
            db_style.is_new = effective_is_new

        upload = image or file
        if upload is not None:
            image_filename = await admin_styles.save_uploaded_image(upload, prefix="style")
            db_style.image_filename = image_filename

        await session.commit()
        await session.refresh(db_style)

    return StyleResponse(
        id=db_style.id,
        title=db_style.title,
        description=db_style.description,
        prompt=db_style.prompt,
        image_filename=db_style.image_filename,
        image_url=_img_url(request, db_style.image_filename),
        is_active=db_style.is_active,
        category_id=db_style.category_id,
        gender=db_style.gender.value,
        is_new=bool(getattr(db_style, "is_new", False)),
        usage_count=int(getattr(db_style, "usage_count", 0) or 0),
    )


@app.delete("/api/admin/styles/{style_id}")
async def admin_delete_style(
    style_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    ensure_admin(user)

    ok = await delete_style_prompt(style_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Стиль не найден")
    return JSONResponse({"status": "ok"})


# -------------------------------------------------------------------
# Пользовательская статистика / админы / рефералы
# -------------------------------------------------------------------


@app.get("/api/admin/users/stats", response_model=List[AdminUserStats])
async def admin_users_stats(user: CurrentUser = Depends(get_current_user)) -> List[AdminUserStats]:
    ensure_admin(user)
    stats_rows = await get_all_user_stats()

    result: List[AdminUserStats] = []
    async with async_session() as session:
        for stats in stats_rows:
            res_user = await session.execute(select(User).where(User.telegram_id == stats.telegram_id))
            user_obj = res_user.scalar_one_or_none()
            username = user_obj.username if user_obj is not None else None

            last_at_str: Optional[str] = None
            if getattr(stats, "last_photoshoot_at", None) is not None:
                last_at_str = stats.last_photoshoot_at.isoformat()

            result.append(
                AdminUserStats(
                    telegram_id=stats.telegram_id,
                    username=username,
                    spent_rub=stats.spent_rub,
                    photos_success=stats.photos_success,
                    photos_failed=stats.photos_failed,
                    last_photoshoot_at=last_at_str,
                )
            )

    return result


@app.post("/api/admin/users/stats/clear")
async def admin_clear_users_stats(
    body: AdminClearStatsRequest,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    ensure_admin(user)

    if body.confirm != "CLEAR":
        raise HTTPException(status_code=400, detail="Confirmation required")

    result = await clear_users_statistics(clear_photoshoot_logs=bool(body.clear_logs))
    return JSONResponse({"status": "ok", **result})


@app.get("/api/admin/admins", response_model=List[AdminUserResponse])
async def admin_get_admins(user: CurrentUser = Depends(get_current_user)) -> List[AdminUserResponse]:
    ensure_admin(user)

    admins = await get_admin_users()

    result: List[AdminUserResponse] = []
    for u in admins:
        created_at_str = u.created_at.isoformat() if getattr(u, "created_at", None) is not None else None
        result.append(
            AdminUserResponse(
                telegram_id=u.telegram_id,
                username=u.username,
                balance=u.balance,
                photoshoot_credits=u.photoshoot_credits,
                is_admin=getattr(u, "is_admin", False),
                created_at=created_at_str,
            )
        )

    return result


@app.post("/api/admin/users/{telegram_id}/admin-flag", response_model=AdminUserResponse)
async def admin_set_admin_flag_endpoint(
    telegram_id: int,
    body: AdminFlagRequest,
    user: CurrentUser = Depends(get_current_user),
) -> AdminUserResponse:
    ensure_admin(user)

    updated = await set_user_admin_flag(telegram_id=telegram_id, is_admin=body.is_admin)
    if updated is None:
        raise HTTPException(status_code=404, detail="User not found")

    created_at_str = updated.created_at.isoformat() if getattr(updated, "created_at", None) is not None else None
    return AdminUserResponse(
        telegram_id=updated.telegram_id,
        username=updated.username,
        balance=updated.balance,
        photoshoot_credits=updated.photoshoot_credits,
        is_admin=getattr(updated, "is_admin", False),
        created_at=created_at_str,
    )


@app.post("/api/admin/users/referral-flag", response_model=AdminUserResponse)
async def admin_set_referral_flag_endpoint(
    body: AdminReferralFlagRequest,
    user: CurrentUser = Depends(get_current_user),
) -> AdminUserResponse:
    ensure_admin(user)

    if body.telegram_id is None or body.telegram_id <= 0:
        raise HTTPException(status_code=400, detail="telegram_id должен быть положительным числом")

    db_user = await get_or_create_user(telegram_id=body.telegram_id, username=None)

    updated = await set_user_referral_flag(
        telegram_id=db_user.telegram_id,
        is_referral=body.is_referral,
    )
    if updated is None:
        raise HTTPException(status_code=500, detail="Не удалось обновить флаг реферала")

    created_at_str = updated.created_at.isoformat() if getattr(updated, "created_at", None) is not None else None
    return AdminUserResponse(
        telegram_id=updated.telegram_id,
        username=updated.username,
        balance=updated.balance,
        photoshoot_credits=updated.photoshoot_credits,
        is_admin=getattr(updated, "is_admin", False),
        created_at=created_at_str,
    )


@app.get("/api/admin/referrals", response_model=List[AdminReferralResponse])
async def admin_get_referrals_endpoint(
    user: CurrentUser = Depends(get_current_user),
) -> List[AdminReferralResponse]:
    ensure_admin(user)

    RefUser = aliased(User)

    ref_counts_subq = (
        select(
            User.referrer_id.label("referrer_id"),
            func.count(User.id).label("referrals_count"),
        )
        .where(User.referrer_id.is_not(None))
        .group_by(User.referrer_id)
        .subquery()
    )

    stmt = (
        select(
            RefUser.telegram_id.label("telegram_id"),
            RefUser.username.label("username"),
            RefUser.referral_earned_rub.label("earned_rub"),
            func.coalesce(ref_counts_subq.c.referrals_count, 0).label("referrals_count"),
        )
        .where(RefUser.is_referral == True)  # noqa: E712
        .outerjoin(ref_counts_subq, ref_counts_subq.c.referrer_id == RefUser.telegram_id)
        .order_by(RefUser.referral_earned_rub.desc(), RefUser.created_at.desc())
    )

    async with async_session() as session:
        rows = (await session.execute(stmt)).all()

    return [
        AdminReferralResponse(
            telegram_id=int(r._mapping["telegram_id"]),
            username=r._mapping["username"],
            referrals_count=int(r._mapping["referrals_count"] or 0),
            earned_rub=int(r._mapping["earned_rub"] or 0),
        )
        for r in rows
    ]


# -------------------------------------------------------------------
# Промокоды — админка
# -------------------------------------------------------------------


@app.get("/api/admin/promo-codes", response_model=List[PromoCodeResponse])
async def admin_list_promo_codes(
    user: CurrentUser = Depends(get_current_user),
) -> List[PromoCodeResponse]:
    ensure_admin(user)

    rows = await list_promo_codes(include_inactive=True)

    result: List[PromoCodeResponse] = []
    for r in rows:
        created_at_str = r.created_at.isoformat() if getattr(r, "created_at", None) else None
        updated_at_str = r.updated_at.isoformat() if getattr(r, "updated_at", None) else None
        result.append(
            PromoCodeResponse(
                id=int(r.id),
                code=str(r.code),
                is_active=bool(r.is_active),
                generations=int(r.generations),
                created_at=created_at_str,
                updated_at=updated_at_str,
            )
        )
    return result


@app.post("/api/admin/promo-codes", response_model=PromoCodeResponse)
async def admin_create_promo_code(
    body: AdminPromoCodeCreateRequest,
    user: CurrentUser = Depends(get_current_user),
) -> PromoCodeResponse:
    ensure_admin(user)

    code = (body.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="code is required")
    if len(code) > 128:
        raise HTTPException(status_code=400, detail="code is too long (max 128)")
    if body.generations <= 0:
        raise HTTPException(status_code=400, detail="generations must be > 0")

    try:
        promo = await create_promo_code(
            code=code,
            generations=int(body.generations),
            is_active=bool(body.is_active),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to create promo code")

    created_at_str = promo.created_at.isoformat() if getattr(promo, "created_at", None) else None
    updated_at_str = promo.updated_at.isoformat() if getattr(promo, "updated_at", None) else None

    return PromoCodeResponse(
        id=int(promo.id),
        code=str(promo.code),
        is_active=bool(promo.is_active),
        generations=int(promo.generations),
        created_at=created_at_str,
        updated_at=updated_at_str,
    )


@app.post("/api/admin/promo-codes/{promo_id}/active", response_model=PromoCodeResponse)
async def admin_set_promo_code_active(
    promo_id: int,
    body: AdminPromoCodeSetActiveRequest,
    user: CurrentUser = Depends(get_current_user),
) -> PromoCodeResponse:
    ensure_admin(user)

    if promo_id <= 0:
        raise HTTPException(status_code=400, detail="promo_id must be positive")

    updated = await set_promo_code_active(promo_id=promo_id, is_active=bool(body.is_active))
    if updated is None:
        raise HTTPException(status_code=404, detail="Promo code not found")

    created_at_str = updated.created_at.isoformat() if getattr(updated, "created_at", None) else None
    updated_at_str = updated.updated_at.isoformat() if getattr(updated, "updated_at", None) else None

    return PromoCodeResponse(
        id=int(updated.id),
        code=str(updated.code),
        is_active=bool(updated.is_active),
        generations=int(updated.generations),
        created_at=created_at_str,
        updated_at=updated_at_str,
    )


@app.delete("/api/admin/promo-codes/{promo_id}")
async def admin_delete_promo_code(
    promo_id: int,
    user: CurrentUser = Depends(get_current_user),
) -> JSONResponse:
    ensure_admin(user)

    if promo_id <= 0:
        raise HTTPException(status_code=400, detail="promo_id must be positive")

    ok = await delete_promo_code(promo_id=promo_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Promo code not found")

    return JSONResponse({"status": "ok"})


@app.get("/api/admin/promo-codes/by-code", response_model=PromoCodeResponse)
async def admin_get_promo_by_code(
    code: str = Query(..., min_length=1, max_length=128),
    user: CurrentUser = Depends(get_current_user),
) -> PromoCodeResponse:
    ensure_admin(user)

    promo = await get_promo_code_by_code(code.strip())
    if promo is None:
        raise HTTPException(status_code=404, detail="Promo code not found")

    created_at_str = promo.created_at.isoformat() if getattr(promo, "created_at", None) else None
    updated_at_str = promo.updated_at.isoformat() if getattr(promo, "updated_at", None) else None

    return PromoCodeResponse(
        id=int(promo.id),
        code=str(promo.code),
        is_active=bool(promo.is_active),
        generations=int(promo.generations),
        created_at=created_at_str,
        updated_at=updated_at_str,
    )