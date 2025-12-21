# src/db/__init__.py
from __future__ import annotations

from src.constants import SUPER_ADMIN_ID, MAX_AVATARS_PER_USER
from .session import engine, async_session
from .base import Base
from .enums import PaymentStatus, StyleGender, PhotoshootStatus
from .models import (
    User,
    StarPayment,
    StyleCategory,
    StylePrompt,
    PhotoshootLog,
    UserAvatar,
    UserStats,
    SupportTopic,
)
from .migrations import init_db, run_manual_migrations

from .repositories.users import (
    get_or_create_user,
    set_user_admin_flag,
    set_user_referral_flag,
    get_referral_users,
    get_referrals_for_user,
    get_referrals_count,
    add_referral_earnings,
    get_referral_summary,
    is_user_admin_db,
    get_admin_users,
    get_user_by_telegram_id,
    get_user_balance,
    consume_photoshoot_credit_or_balance,
    get_users_page,
    search_users,
    change_user_credits,
    change_user_balance,
)

from .repositories.stars import (
    create_star_payment,
    mark_star_payment_success,
)

from .repositories.photoshoots import (
    log_photoshoot,
    get_photoshoot_report,
    get_payments_report,
)

from .repositories.avatars import (
    get_user_avatar,
    get_user_avatars,
    set_user_avatar,
    create_user_avatar,
    delete_user_avatar,
)

from .repositories.styles import (
    count_active_styles,
    get_style_by_offset,
    get_style_prompt_by_id,
    get_all_style_prompts,
    delete_style_prompt,
    create_style_category,
    get_style_category_by_id,
    get_style_categories_for_gender,
    get_all_style_categories,
    create_style_prompt,
    get_styles_for_category,
    get_styles_by_category_and_gender,
    get_styles_for_category_ids,
    get_styles_for_category_ids_and_gender,
)

from .repositories.stats import (
    get_or_create_user_stats,
    get_all_user_stats,
    clear_users_statistics,
)

from .repositories.support import (
    get_support_thread_id,
    get_support_user_id_by_thread,
    bind_support_thread,
)

__all__ = [
    # constants
    "SUPER_ADMIN_ID",
    "MAX_AVATARS_PER_USER",
    # engine/session/base
    "engine",
    "async_session",
    "Base",
    # enums
    "PaymentStatus",
    "StyleGender",
    "PhotoshootStatus",
    # models
    "User",
    "StarPayment",
    "StyleCategory",
    "StylePrompt",
    "PhotoshootLog",
    "UserAvatar",
    "UserStats",
    "SupportTopic",
    # migrations
    "init_db",
    "run_manual_migrations",
    # users
    "get_or_create_user",
    "set_user_admin_flag",
    "set_user_referral_flag",
    "get_referral_users",
    "get_referrals_for_user",
    "get_referrals_count",
    "add_referral_earnings",
    "get_referral_summary",
    "is_user_admin_db",
    "get_admin_users",
    "get_user_by_telegram_id",
    "get_user_balance",
    "consume_photoshoot_credit_or_balance",
    "get_users_page",
    "search_users",
    "change_user_credits",
    "change_user_balance",
    # stars
    "create_star_payment",
    "mark_star_payment_success",
    # photoshoots/reports
    "log_photoshoot",
    "get_photoshoot_report",
    "get_payments_report",
    # avatars
    "get_user_avatar",
    "get_user_avatars",
    "set_user_avatar",
    "create_user_avatar",
    "delete_user_avatar",
    # styles
    "count_active_styles",
    "get_style_by_offset",
    "get_style_prompt_by_id",
    "get_all_style_prompts",
    "delete_style_prompt",
    "create_style_category",
    "get_style_category_by_id",
    "get_style_categories_for_gender",
    "get_all_style_categories",
    "create_style_prompt",
    "get_styles_for_category",
    "get_styles_by_category_and_gender",
    "get_styles_for_category_ids",
    "get_styles_for_category_ids_and_gender",
    # stats
    "get_or_create_user_stats",
    "get_all_user_stats",
    "clear_users_statistics",
    # support
    "get_support_thread_id",
    "get_support_user_id_by_thread",
    "bind_support_thread",
]