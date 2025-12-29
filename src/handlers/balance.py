# src/handlers/balance.py

import json
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    SuccessfulPayment,
)
from src.db.repositories.users import ensure_user_is_referral
from src.constants import PHOTOSHOOT_PRICE
from src.db import (
    add_referral_earnings,
    change_user_balance,
    get_user_balance as db_get_user_balance,
    get_user_by_telegram_id,
)

router = Router()

ADM_GROUP_ID = -5075627878

# ✅ Чат для логов пополнений/ошибок
PAYMENTS_LOG_CHAT_ID = -5138363601

PAYMENT_PROVIDER_TOKEN = "390540012:LIVE:84036"

# ✅ Минимальная сумма пополнения
MIN_TOPUP_RUB = 99

# Тарифы (как отображаем пользователю)
PHOTO_PACK_PRICES_RUB: Dict[int, int] = {
    2: 99,
    3: 119,
    5: 149,
    10: 199,
    50: 749,   # ✅ NEW
}

# Пакеты пополнения: callback_data -> сумма_руб (СУММА ОПЛАТЫ)
TOPUP_OPTIONS: Dict[str, int] = {
    "topup_99": 99,
    "topup_119": 119,
    "topup_149": 149,
    "topup_199": 199,
    "topup_749": 749,  # ✅ NEW
}

# Сколько фотосессий выдаём за пакет
TOPUP_PACK_PHOTOS: Dict[str, int] = {
    "topup_99": 2,
    "topup_119": 3,
    "topup_149": 5,
    "topup_199": 10,
    "topup_749": 50,   # ✅ NEW
}

# ✅ Сколько рублей зачисляем на баланс за пакет
TOPUP_PACK_CREDIT_RUB: Dict[str, int] = {
    "topup_99": 99,  # 2 фотосессии, но зачисляем 99 ₽
    "topup_119": 3 * int(PHOTOSHOOT_PRICE),
    "topup_149": 5 * int(PHOTOSHOOT_PRICE),
    "topup_199": 10 * int(PHOTOSHOOT_PRICE),
    "topup_749": 50 * int(PHOTOSHOOT_PRICE),  # ✅ NEW (50 генераций)
}

TAX_SYSTEM_CODE = 1
VAT_CODE = 1
PAYMENT_MODE = "full_payment"
PAYMENT_SUBJECT = "service"

REF_TOPUP_PERCENT = 10  # 10% от суммы пополнения

def _calc_ref_topup_reward(paid_amount_rub: int) -> int:
    # 10% от оплаты, округляем до рубля
    return max(1, int(round(int(paid_amount_rub) * REF_TOPUP_PERCENT / 100)))


def _format_dt(dt: Optional[datetime]) -> str:
    """
    Дата для логов. Если dt нет — берём текущее UTC.
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    # компактно и стабильно
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _format_user(telegram_id: int, username: Optional[str]) -> str:
    u = (username or "—").strip()
    if u and not u.startswith("@") and u != "—":
        u = f"@{u}"
    if u == "@—":
        u = "—"
    return f"{telegram_id} {u}".strip()


async def send_admin_log(bot: Bot, text: str) -> None:
        return


async def send_payment_log(
    bot: Bot,
    *,
    telegram_id: int,
    username: Optional[str],
    dt: Optional[datetime],
    amount_rub: int,
    error: Optional[str] = None,
) -> None:
    """
    Логи пополнений/ошибок в отдельный чат.
    Формат:
      <юзер> - <дата> - <сумма>
      <юзер> - <дата> - <сумма> - ERROR: ...
    """
    try:
        user_str = _format_user(int(telegram_id), username)
        date_str = _format_dt(dt)
        base = f"{user_str} - {date_str} - {int(amount_rub)} ₽"
        if error:
            # обрезаем, чтобы не улетать в километровые логи
            err = str(error).replace("\n", " ").strip()
            if len(err) > 400:
                err = err[:400] + "…"
            base = f"{base} - ERROR: {err}"
        await bot.send_message(chat_id=PAYMENTS_LOG_CHAT_ID, text=base)
    except Exception:
        # никогда не валим оплату/инвойсы из-за логов
        return


# =====================================================================
# Вспомогательные функции (через БД)
# =====================================================================

async def get_balance_rub(telegram_id: int) -> int:
    balance = await db_get_user_balance(telegram_id)
    return int(balance or 0)


async def add_to_balance_rub(telegram_id: int, amount_rub: int) -> int:
    await get_user_by_telegram_id(telegram_id)
    user = await change_user_balance(telegram_id, amount_rub)
    if user is None:
        return await get_balance_rub(telegram_id)
    return int(user.balance or 0)


async def format_balance_message(telegram_id: int) -> str:
    balance_rub = await get_balance_rub(telegram_id)
    return f"Доступное количество генераций: {int(balance_rub / 49)}"


def get_balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Пополнить: 2 фото — 99 ₽", callback_data="topup_99")],
            [InlineKeyboardButton(text="Пополнить: 3 фото — 119 ₽", callback_data="topup_119")],
            [InlineKeyboardButton(text="Пополнить: 5 фото — 149 ₽", callback_data="topup_149")],
            [InlineKeyboardButton(text="Пополнить: 10 фото — 199 ₽", callback_data="topup_199")],
            [InlineKeyboardButton(text="Пополнить: 50 фото — 749 ₽", callback_data="topup_749")],  # ✅ NEW
            [InlineKeyboardButton(text="Промокод", callback_data="promo_code")],
            [InlineKeyboardButton(text="Главное меню", callback_data="back_to_main_menu")],
        ]
    )


def get_after_success_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Создать фотосессию ✨", callback_data="make_photo")],
            [InlineKeyboardButton(text="Главное меню", callback_data="back_to_main_menu")],
        ]
    )


def get_payment_error_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Попробовать ещё раз", callback_data="balance")],
            [InlineKeyboardButton(text="Главное меню", callback_data="back_to_main_menu")],
        ]
    )


def build_provider_data(description: str, amount_rub: int) -> str:
    value = f"{amount_rub:.2f}"

    receipt = {
        "receipt": {
            "items": [
                {
                    "description": description[:128],
                    "quantity": "1.00",
                    "amount": {"value": value, "currency": "RUB"},
                    "vat_code": VAT_CODE,
                    "payment_mode": PAYMENT_MODE,
                    "payment_subject": PAYMENT_SUBJECT,
                }
            ],
            "tax_system_code": TAX_SYSTEM_CODE,
        }
    }

    return json.dumps(receipt, ensure_ascii=False)


def _resolve_pack_from_payload(payload: str, paid_amount_rub: int) -> Tuple[Optional[str], int, int]:
    """
    Возвращает (option_key, photos_count, credit_amount_rub).
    payload ожидаем в формате:
      balance_topup:topup_99
    Фолбэк: пытаемся сопоставить по paid_amount_rub.
    """
    option_key: Optional[str] = None
    photos_count = 0
    credit_amount_rub = paid_amount_rub

    if payload.startswith("balance_topup:"):
        rest = payload.split(":", 1)[1].strip()
        if rest in TOPUP_OPTIONS:
            option_key = rest

    if option_key is None:
        for k, pay in TOPUP_OPTIONS.items():
            if int(pay) == int(paid_amount_rub):
                option_key = k
                break

    if option_key is not None:
        photos_count = int(TOPUP_PACK_PHOTOS.get(option_key, 0))
        credit_amount_rub = int(TOPUP_PACK_CREDIT_RUB.get(option_key, paid_amount_rub))

    return option_key, photos_count, credit_amount_rub


# =====================================================================
# Быстрое пополнение (оставлено для совместимости)
# =====================================================================

async def send_quick_topup_invoice_49(callback: CallbackQuery) -> None:
    """
    ⚠️ Имя оставлено для совместимости.
    Отправляет инвойс на пакет 99 ₽ (2 фото),
    и зачисляет на баланс 99 ₽ (как ты попросил).
    """
    bot = callback.bot
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"

    option_key = "topup_99"
    pay_amount_rub = TOPUP_OPTIONS[option_key]
    photos_count = TOPUP_PACK_PHOTOS[option_key]
    credit_amount_rub = TOPUP_PACK_CREDIT_RUB[option_key]

    prices = [
        LabeledPrice(
            label=f"Пополнение: {photos_count} фото",
            amount=pay_amount_rub * 100,
        )
    ]

    payload = f"balance_topup:{option_key}"

    provider_data = build_provider_data(
        description=f"Пополнение (пакет {photos_count} фото)",
        amount_rub=pay_amount_rub,
    )

    try:
        await bot.send_invoice(
            chat_id=user_id,
            title="Пополнение баланса",
            description=(
                "Пополнение баланса аккаунта.\n"
                f"Вы платите {pay_amount_rub} ₽, "
                f"на баланс будет зачислено {credit_amount_rub} ₽ "
                f"({photos_count} фотосессии)."
            ),
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency="RUB",
            prices=prices,
            payload=payload,
            start_parameter="balance_topup",
            need_email=True,
            send_email_to_provider=True,
            need_phone_number=False,
            send_phone_number_to_provider=False,
            need_shipping_address=False,
            is_flexible=False,
            max_tip_amount=0,
            provider_data=provider_data,
        )

        if callback.message and callback.message.chat.id != user_id:
            await callback.message.answer("Я отправил оплату тебе в личные сообщения с ботом ✅")

        await send_admin_log(
            bot,
            (
                f"⚡️ <b>Quick topup invoice ({pay_amount_rub} ₽) отправлен</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Пакет: <code>{option_key}</code>\n"
                f"payload: <code>{payload}</code>"
            ),
        )

    except (TelegramForbiddenError, TelegramBadRequest, Exception) as e:
        # ✅ лог ошибки в отдельный чат
        await send_payment_log(
            bot,
            telegram_id=user_id,
            username=username,
            dt=getattr(callback.message, "date", None),
            amount_rub=pay_amount_rub,
            error=str(e),
        )

        # админ-лог оставим
        await send_admin_log(
            bot,
            (
                "🔴 <b>Quick topup: ошибка при отправке invoice</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )

        await callback.message.answer(
            "Не удалось открыть оплату 😔\nПопробуй ещё раз или выбери другую сумму.",
            reply_markup=get_payment_error_keyboard(),
        )


# =====================================================================
# Вход в раздел «Баланс»
# =====================================================================

@router.callback_query(F.data == "balance")
async def open_balance(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id

    text = await format_balance_message(telegram_id)
    await callback.message.edit_text(text, reply_markup=get_balance_keyboard())
    await callback.answer()

    # ❌ НЕ логируем "заход в баланс" (ни в админ-чат, ни в чат платежей)


# =====================================================================
# Выбор готового пакета пополнения
# =====================================================================

@router.callback_query(F.data.in_(tuple(TOPUP_OPTIONS.keys())))
async def choose_topup_package(callback: CallbackQuery) -> None:
    await callback.answer()

    option_key = callback.data
    pay_amount_rub = TOPUP_OPTIONS.get(option_key)
    if not pay_amount_rub:
        await callback.message.answer(
            "Не удалось определить сумму пополнения. Открой «Баланс» и попробуй ещё раз.",
            reply_markup=get_payment_error_keyboard(),
        )
        return

    photos_count = int(TOPUP_PACK_PHOTOS.get(option_key, 0))
    credit_amount_rub = int(TOPUP_PACK_CREDIT_RUB.get(option_key, pay_amount_rub))

    prices = [
        LabeledPrice(
            label=f"Пополнение: {photos_count} фото",
            amount=pay_amount_rub * 100,
        )
    ]

    payload = f"balance_topup:{option_key}"

    provider_data = build_provider_data(
        description=f"Пополнение (пакет {photos_count} фото)",
        amount_rub=pay_amount_rub,
    )

    user_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    try:
        await bot.send_invoice(
            chat_id=user_id,
            title="Пополнение баланса",
            description=(
                "Пополнение баланса аккаунта.\n"
                f"Вы платите {pay_amount_rub} ₽, "
                f"на баланс будет зачислено {credit_amount_rub} ₽ "
                f"({photos_count} фотосессии)."
            ),
            provider_token=PAYMENT_PROVIDER_TOKEN,
            currency="RUB",
            prices=prices,
            payload=payload,
            start_parameter="balance_topup",
            need_email=True,
            send_email_to_provider=True,
            need_phone_number=False,
            send_phone_number_to_provider=False,
            need_shipping_address=False,
            is_flexible=False,
            max_tip_amount=0,
            provider_data=provider_data,
        )

        if callback.message and callback.message.chat.id != user_id:
            await callback.message.answer("Я отправил оплату тебе в личные сообщения с ботом ✅")

        await send_admin_log(
            bot,
            (
                "💳 <b>Отправлен invoice на пополнение</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Пакет: <code>{option_key}</code>\n"
                f"Оплата: <b>{pay_amount_rub} ₽</b>\n"
                f"Зачисление: <b>{credit_amount_rub} ₽</b>\n"
                f"payload: <code>{payload}</code>"
            ),
        )

    except (TelegramForbiddenError, TelegramBadRequest, Exception) as e:
        # ✅ лог ошибки в отдельный чат
        await send_payment_log(
            bot,
            telegram_id=user_id,
            username=username,
            dt=getattr(callback.message, "date", None),
            amount_rub=pay_amount_rub,
            error=str(e),
        )

        await send_admin_log(
            bot,
            (
                "🔴 <b>Ошибка при отправке invoice</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Пакет: <code>{option_key}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )

        await callback.message.answer(
            "Не удалось открыть оплату 😔\nПопробуй ещё раз или выбери другую сумму.",
            reply_markup=get_payment_error_keyboard(),
        )


# =====================================================================
# Pre Checkout
# =====================================================================

@router.pre_checkout_query()
async def process_pre_checkout(
    pre_checkout_query: PreCheckoutQuery,
    bot: Bot,
) -> None:
    payload = pre_checkout_query.invoice_payload
    total_amount = pre_checkout_query.total_amount
    user = pre_checkout_query.from_user
    username = user.username or "—"
    user_id = user.id

    paid_amount_rub = int(total_amount // 100)

    # payload не наш — отклоняем и логируем как ошибку
    if not payload.startswith("balance_topup:"):
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Платёж не прошёл.\nПопробуй ещё раз или выбери другую сумму.",
        )

        await send_payment_log(
            bot,
            telegram_id=user_id,
            username=username,
            dt=datetime.now(timezone.utc),
            amount_rub=paid_amount_rub,
            error=f"Invalid payload: {payload}",
        )
        return

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


# =====================================================================
# Успешный платёж
# =====================================================================

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message) -> None:
    payment: SuccessfulPayment = message.successful_payment
    payload = payment.invoice_payload

    if not payload.startswith("balance_topup:"):
        return

    paid_amount_rub = int(payment.total_amount // 100)

    telegram_id = message.from_user.id
    username = message.from_user.username or "—"
    bot = message.bot

    try:
        option_key, photos_count, credited_amount_rub = _resolve_pack_from_payload(payload, paid_amount_rub)
        new_balance = await add_to_balance_rub(telegram_id, credited_amount_rub)

        # ✅ Лог успешного пополнения в отдельный чат
        await send_payment_log(
            bot,
            telegram_id=telegram_id,
            username=username,
            dt=getattr(message, "date", None),
            amount_rub=paid_amount_rub,
            error=None,
        )

        user_db = await get_user_by_telegram_id(telegram_id)
        referrer_id = getattr(user_db, "referrer_id", None)

        # ✅ Реферальное начисление: 10% от суммы оплаты пригласившему
        if referrer_id and int(referrer_id) != int(telegram_id):
            reward = _calc_ref_topup_reward(paid_amount_rub)

            # начисляем в referral_earned_rub
            await add_referral_earnings(int(referrer_id), int(reward))

            # пригласивший становится is_referral=true
            try:
                await ensure_user_is_referral(int(referrer_id))
            except Exception:
                pass

            # сообщение пригласившему (оплатившему — ничего не говорим)
            try:
                ref_msg = (
                    "💸 Реферальное начисление!\n\n"
                    f"Твой реферал пополнил баланс на <b>{paid_amount_rub} ₽</b>.\n"
                    f"Тебе начислено: <b>{reward} ₽</b> — это <b>{REF_TOPUP_PERCENT}%</b> от суммы ✅"
                )
                await bot.send_message(chat_id=int(referrer_id), text=ref_msg, parse_mode="HTML")
            except (TelegramForbiddenError, TelegramBadRequest):
                pass
            except Exception:
                pass

            await send_admin_log(
                bot,
                (
                    "🤝 <b>Реферальное начисление с пополнения</b>\n"
                    f"Оплата: <b>{paid_amount_rub} ₽</b>\n"
                    f"Процент: <b>{REF_TOPUP_PERCENT}%</b>\n"
                    f"Начислено пригласителю: <b>{reward} ₽</b>"
                ),
            )

        text = (
            "Оплата прошла успешно!\n"
            f"Вы оплатили: {paid_amount_rub} ₽.\n"
            f"Текущий баланс: {int(new_balance / 49)} фото"
        )
        await message.answer(text, reply_markup=get_after_success_keyboard())

        await send_admin_log(
            bot,
            (
                "✅ <b>Успешное пополнение баланса</b>\n"
                f"Пользователь: <code>{telegram_id}</code> @{username}\n"
                f"Пакет: <code>{option_key or 'unknown'}</code>\n"
                f"Оплачено: <b>{paid_amount_rub} ₽</b>\n"
                f"Зачислено на баланс: <b>{credited_amount_rub} ₽</b>\n"
                f"Новый баланс: <b>{new_balance} ₽</b>\n"
                f"payload: <code>{payload}</code>\n"
                f"telegram_payment_charge_id: <code>{payment.telegram_payment_charge_id}</code>\n"
                f"provider_payment_charge_id: <code>{payment.provider_payment_charge_id}</code>"
            ),
        )

    except Exception as e:
        # ✅ лог ошибки в отдельный чат
        await send_payment_log(
            bot,
            telegram_id=telegram_id,
            username=username,
            dt=getattr(message, "date", None),
            amount_rub=paid_amount_rub,
            error=str(e),
        )

        # и в админ-чат (как раньше)
        await send_admin_log(
            bot,
            (
                "🔴 <b>Ошибка обработки successful_payment</b>\n"
                f"Пользователь: <code>{telegram_id}</code> @{username}\n"
                f"Оплата: <b>{paid_amount_rub} ₽</b>\n"
                f"payload: <code>{payload}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )


# =====================================================================
# Сообщение «платёж не прошёл»
# =====================================================================

@router.callback_query(F.data == "payment_failed_show_message")
async def payment_failed_message(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    await callback.message.answer(
        "Платёж не прошёл.\nПопробуй ещё раз или выбери другую сумму.",
        reply_markup=get_payment_error_keyboard(),
    )
    await callback.answer()

    # Здесь суммы нет, но это тоже ошибка UX — залогируем как 0 ₽
    await send_payment_log(
        bot,
        telegram_id=user_id,
        username=username,
        dt=getattr(callback.message, "date", None),
        amount_rub=0,
        error="payment_failed_show_message",
    )

    await send_admin_log(
        bot,
        (
            "❌ <b>Пользователь увидел сообщение о неуспешном платеже</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}"
        ),
    )