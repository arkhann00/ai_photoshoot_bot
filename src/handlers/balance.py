# src/handlers/balance.py


import json
import math
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
from src.keyboards import get_start_keyboard


router = Router()


ADM_GROUP_ID = -5075627878


# ✅ Чат для логов пополнений/ошибок
PAYMENTS_LOG_CHAT_ID = -5138363601


# ✅ Провайдер для RUB оплат (ЮKassa/CloudPayments и т.п.)
PAYMENT_PROVIDER_TOKEN = "390540012:LIVE:84036"


# ✅ Курс: сколько ₽ мы считаем за 1 ⭐ (для пересчёта пакетов)
# Меняй только это значение, чтобы обновить цены в звёздах.
RUB_PER_STAR = 3.0


# ✅ Минимальная сумма пополнения
MIN_TOPUP_RUB = 99


# Тарифы (как отображаем пользователю)
PHOTO_PACK_PRICES_RUB: Dict[int, int] = {
    2: 99,
    3: 119,
    5: 149,
    10: 199,
    50: 749,  # ✅ NEW
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
    "topup_749": 50,  # ✅ NEW
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


def rub_to_stars(amount_rub: int) -> int:
    # Чтобы не сделать "дешевле" при дробном курсе — округляем вверх
    return max(1, int(math.ceil(int(amount_rub) / float(RUB_PER_STAR))))


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
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _format_user(telegram_id: int, username: Optional[str]) -> str:
    u = (username or "—").strip()
    if u and not u.startswith("@") and u != "—":
        u = f"@{u}"
    if u == "@—":
        u = "—"
    return f"{telegram_id} {u}".strip()


async def send_admin_log(bot: Bot, text: str) -> None:
    # (у тебя сейчас отключено)
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
    amount_rub — "номинал пакета" в рублях (и для RUB и для XTR),
    чтобы не плодить отдельную логику в БД.
    """
    try:
        user_str = _format_user(int(telegram_id), username)
        date_str = _format_dt(dt)
        base = f"{user_str} - {date_str} - {int(amount_rub)} ₽"
        if error:
            err = str(error).replace("\n", " ").strip()
            if len(err) > 400:
                err = err[:400] + "…"
            base = f"{base} - ERROR: {err}"
        await bot.send_message(chat_id=PAYMENTS_LOG_CHAT_ID, text=base)
    except Exception:
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


def get_balance_keyboard(currency: str = "RUB") -> InlineKeyboardMarkup:
    """
    currency: "RUB" или "XTR"
    По умолчанию — XTR (Stars).
    """
    rows = []

    for option_key, pay_amount_rub in TOPUP_OPTIONS.items():
        photos_count = int(TOPUP_PACK_PHOTOS.get(option_key, 0))

        if currency == "RUB":
            text = f"Пополнить: {photos_count} фото — {pay_amount_rub} ₽"
            cb = f"topup:RUB:{option_key}"
        else:
            stars = rub_to_stars(pay_amount_rub)
            text = f"Пополнить: {photos_count} фото — {stars} ⭐"
            cb = f"topup:XTR:{option_key}"

        rows.append([InlineKeyboardButton(text=text, callback_data=cb)])

    rows.append([InlineKeyboardButton(text="Промокод", callback_data="promo_code")])

    # ✅ переключатель валюты
    if currency == "RUB":
        rows.append([InlineKeyboardButton(text="Валюта: ₽ (переключить на ⭐)", callback_data="balance_currency:XTR")])
    else:
        rows.append([InlineKeyboardButton(text="Валюта: ⭐ (переключить на ₽)", callback_data="balance_currency:RUB")])

    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="back_to_main_menu")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def parse_topup_payload(payload: str) -> tuple[Optional[str], Optional[str]]:
    """
    Поддерживаем 3 формата:
      1) balance_topup:topup_99                 (старый)
      2) balance_topup:RUB:topup_99
      3) balance_topup:XTR:topup_99
    """
    if not payload.startswith("balance_topup:"):
        return None, None

    rest = payload.split(":", 1)[1].strip()

    # старый формат
    if rest in TOPUP_OPTIONS:
        return "RUB", rest

    parts = payload.split(":")
    if len(parts) != 3:
        return None, None

    _, currency, option_key = parts
    if currency not in ("RUB", "XTR"):
        return None, None
    if option_key not in TOPUP_OPTIONS:
        return None, None

    return currency, option_key


def _resolve_pack_from_payload(payload: str, paid_amount_rub: int) -> Tuple[Optional[str], int, int]:
    """
    Возвращает (option_key, photos_count, credit_amount_rub).

    payload ожидаем:
      - старый: balance_topup:topup_99
      - новый:  balance_topup:RUB:topup_99 / balance_topup:XTR:topup_99

    Фолбэк: сопоставление по paid_amount_rub (номинал пакета в рублях)
    """
    option_key: Optional[str] = None
    photos_count = 0
    credit_amount_rub = paid_amount_rub

    currency, opt = parse_topup_payload(payload)
    if opt in TOPUP_OPTIONS:
        option_key = opt

    if option_key is None:
        for k, pay in TOPUP_OPTIONS.items():
            if int(pay) == int(paid_amount_rub):
                option_key = k
                break

    if option_key is not None:
        photos_count = int(TOPUP_PACK_PHOTOS.get(option_key, 0))
        credit_amount_rub = int(TOPUP_PACK_CREDIT_RUB.get(option_key, paid_amount_rub))

    return option_key, photos_count, credit_amount_rub


def parse_topup_cb(data: str) -> tuple[Optional[str], Optional[str]]:
    """
    Новый callback:
      topup:RUB:topup_99
      topup:XTR:topup_99
    """
    if not data.startswith("topup:"):
        return None, None
    parts = data.split(":")
    if len(parts) != 3:
        return None, None
    _, currency, option_key = parts
    if currency not in ("RUB", "XTR"):
        return None, None
    if option_key not in TOPUP_OPTIONS:
        return None, None
    return currency, option_key


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

    payload = f"balance_topup:RUB:{option_key}"

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

    # ✅ по умолчанию показываем Stars (можно переключить на ₽)
    await callback.message.edit_text(text, reply_markup=get_balance_keyboard("RUB"))
    await callback.answer()


@router.callback_query(F.data.startswith("balance_currency:"))
async def balance_currency_toggle(callback: CallbackQuery) -> None:
    _, currency = callback.data.split(":", 1)  # "RUB" / "XTR"
    telegram_id = callback.from_user.id
    text = await format_balance_message(telegram_id)

    await callback.message.edit_text(text, reply_markup=get_balance_keyboard(currency))
    await callback.answer()


# =====================================================================
# Выбор готового пакета пополнения (НОВЫЙ callback)
# =====================================================================


@router.callback_query(F.data.startswith("topup:"))
async def choose_topup_package_new(callback: CallbackQuery) -> None:
    await callback.answer()

    currency, option_key = parse_topup_cb(callback.data)
    if not currency or not option_key:
        await callback.message.answer(
            "Не удалось определить пакет. Открой «Баланс» и попробуй ещё раз.",
            reply_markup=get_payment_error_keyboard(),
        )
        return

    await _send_invoice_for_option(callback=callback, currency=currency, option_key=option_key)


# =====================================================================
# Выбор готового пакета пополнения (СТАРЫЙ callback: topup_99)
# Оставляем, чтобы ничего не сломать, если где-то в проекте остались старые кнопки.
# =====================================================================


@router.callback_query(F.data.in_(tuple(TOPUP_OPTIONS.keys())))
async def choose_topup_package_legacy(callback: CallbackQuery) -> None:
    await callback.answer()
    option_key = callback.data
    await _send_invoice_for_option(callback=callback, currency="RUB", option_key=option_key)


async def _send_invoice_for_option(*, callback: CallbackQuery, currency: str, option_key: str) -> None:
    pay_amount_rub = int(TOPUP_OPTIONS.get(option_key, 0))
    if not pay_amount_rub:
        await callback.message.answer(
            "Не удалось определить сумму пополнения. Открой «Баланс» и попробуй ещё раз.",
            reply_markup=get_payment_error_keyboard(),
        )
        return

    photos_count = int(TOPUP_PACK_PHOTOS.get(option_key, 0))
    credit_amount_rub = int(TOPUP_PACK_CREDIT_RUB.get(option_key, pay_amount_rub))

    user_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    payload = f"balance_topup:{currency}:{option_key}"

    try:
        if currency == "RUB":
            prices = [
                LabeledPrice(
                    label=f"Пополнение: {photos_count} фото",
                    amount=pay_amount_rub * 100,
                )
            ]

            provider_data = build_provider_data(
                description=f"Пополнение (пакет {photos_count} фото)",
                amount_rub=pay_amount_rub,
            )

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

        else:
            stars_amount = rub_to_stars(pay_amount_rub)

            prices = [
                LabeledPrice(
                    label=f"{photos_count} фото",
                    amount=stars_amount,  # для XTR amount = количество звёзд
                )
            ]

            await bot.send_invoice(
                chat_id=user_id,
                title="Пополнение баланса",
                description=(
                    "Пополнение баланса аккаунта.\n"
                    f"Оплата: {stars_amount} ⭐ (эквивалент пакета {pay_amount_rub} ₽).\n"
                    f"На баланс будет зачислено {credit_amount_rub} ₽ ({photos_count} фотосессии)."
                ),
                provider_token="",  # Stars
                currency="XTR",
                prices=prices,
                payload=payload,
                start_parameter="balance_topup",
                max_tip_amount=0,
            )

        if callback.message and callback.message.chat.id != user_id:
            await callback.message.answer("Я отправил оплату тебе в личные сообщения с ботом ✅")

        await send_admin_log(
            bot,
            (
                "💳 <b>Отправлен invoice на пополнение</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Валюта: <b>{'RUB' if currency == 'RUB' else 'XTR'}</b>\n"
                f"Пакет: <code>{option_key}</code>\n"
                f"Номинал пакета: <b>{pay_amount_rub} ₽</b>\n"
                f"Зачисление: <b>{credit_amount_rub} ₽</b>\n"
                f"payload: <code>{payload}</code>"
            ),
        )

    except (TelegramForbiddenError, TelegramBadRequest, Exception) as e:
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
                f"Валюта: <b>{currency}</b>\n"
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
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery, bot: Bot) -> None:
    payload = pre_checkout_query.invoice_payload
    total_amount = int(pre_checkout_query.total_amount)

    user = pre_checkout_query.from_user
    username = user.username or "—"
    user_id = user.id

    currency, option_key = parse_topup_payload(payload)

    if not currency or not option_key:
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
            amount_rub=0,
            error=f"Invalid payload: {payload}",
        )
        return

    pay_amount_rub = int(TOPUP_OPTIONS[option_key])

    # ✅ Валидация валюты и суммы (важно, чтобы не принимать подменённые invoices)
    if currency == "RUB":
        if pre_checkout_query.currency != "RUB":
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Неверная валюта.")
            return
        expected_total = pay_amount_rub * 100
        if total_amount != expected_total:
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Неверная сумма.")
            return
    else:
        if pre_checkout_query.currency != "XTR":
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Неверная валюта.")
            return
        expected_total = rub_to_stars(pay_amount_rub)
        if total_amount != expected_total:
            await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message="Неверная сумма.")
            return

    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)


# =====================================================================
# Успешный платёж
# =====================================================================


@router.message(F.successful_payment)
async def successful_payment_handler(message: Message) -> None:
    payment: SuccessfulPayment = message.successful_payment
    payload = payment.invoice_payload

    currency, option_key = parse_topup_payload(payload)
    if not currency or not option_key:
        return

    telegram_id = message.from_user.id
    username = message.from_user.username or "—"
    bot = message.bot

    pay_amount_rub = int(TOPUP_OPTIONS[option_key])
    paid_amount_rub_for_logs = pay_amount_rub  # единая логика для БД/рефералов

    try:
        # ✅ Валидация фактической оплаты
        if currency == "RUB":
            if payment.currency != "RUB":
                return
            if int(payment.total_amount) != int(pay_amount_rub * 100):
                return
        else:
            if payment.currency != "XTR":
                return
            if int(payment.total_amount) != int(rub_to_stars(pay_amount_rub)):
                return

        # пакет/начисление
        _, photos_count, credited_amount_rub = _resolve_pack_from_payload(payload, paid_amount_rub_for_logs)

        new_balance = await add_to_balance_rub(telegram_id, credited_amount_rub)

        # ✅ Лог успешного пополнения в отдельный чат
        await send_payment_log(
            bot,
            telegram_id=telegram_id,
            username=username,
            dt=getattr(message, "date", None),
            amount_rub=paid_amount_rub_for_logs,
            error=None,
        )

        user_db = await get_user_by_telegram_id(telegram_id)
        referrer_id = getattr(user_db, "referrer_id", None)

        # ✅ Реферальное начисление: 10% от суммы "номинала пакета" в рублях
        if referrer_id and int(referrer_id) != int(telegram_id):
            reward = _calc_ref_topup_reward(paid_amount_rub_for_logs)

            await add_referral_earnings(int(referrer_id), int(reward))

            try:
                await ensure_user_is_referral(int(referrer_id))
            except Exception:
                pass

            # ✅ ИСПРАВЛЕНИЕ: убрали await перед username и вынесли переменную за пределы try-except
            current_username = message.from_user.username or "Неизвестный"

            try:
                ref_msg = (
                    "💸 Реферальное начисление!\n\n"
                    f"Твой реферал {current_username} пополнил баланс на <b>{paid_amount_rub_for_logs} ₽</b>.\n"
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
                    f"🤝 <b>Реферальное начисление с пополнения от {current_username}</b>\n"
                    f"Номинал пакета: <b>{paid_amount_rub_for_logs} ₽</b>\n"
                    f"Процент: <b>{REF_TOPUP_PERCENT}%</b>\n"
                    f"Начислено пригласителю: <b>{reward} ₽</b>"
                ),
            )

        text = (
            "Оплата прошла успешно!\n"
            f"Пакет: {photos_count} фото.\n"
            f"Текущий баланс: {int(new_balance / 49)} фото"
        )
        await message.answer(text, reply_markup=get_start_keyboard())

        await send_admin_log(
            bot,
            (
                "✅ <b>Успешное пополнение баланса</b>\n"
                f"Пользователь: <code>{telegram_id}</code> @{username}\n"
                f"Валюта: <b>{payment.currency}</b>\n"
                f"Пакет: <code>{option_key or 'unknown'}</code>\n"
                f"Номинал пакета: <b>{paid_amount_rub_for_logs} ₽</b>\n"
                f"Зачислено на баланс: <b>{credited_amount_rub} ₽</b>\n"
                f"Новый баланс: <b>{new_balance} ₽</b>\n"
                f"payload: <code>{payload}</code>\n"
                f"telegram_payment_charge_id: <code>{payment.telegram_payment_charge_id}</code>\n"
                f"provider_payment_charge_id: <code>{payment.provider_payment_charge_id}</code>"
            ),
        )

    except Exception as e:
        await send_payment_log(
            bot,
            telegram_id=telegram_id,
            username=username,
            dt=getattr(message, "date", None),
            amount_rub=paid_amount_rub_for_logs,
            error=str(e),
        )

        await send_admin_log(
            bot,
            (
                "🔴 <b>Ошибка обработки successful_payment</b>\n"
                f"Пользователь: <code>{telegram_id}</code> @{username}\n"
                f"Номинал пакета: <b>{paid_amount_rub_for_logs} ₽</b>\n"
                f"payload: <code>{payload}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )
        raise


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


# =====================================================================
# Paysupport (для продакшена Stars)
# =====================================================================


@router.message(F.text == "/paysupport")
async def paysupport(message: Message) -> None:
    await message.answer(
        "Поддержка по оплатам:\n"
        "Если возникла проблема — напиши сюда и опиши ситуацию (дата/сумма/что нажимал).\n"
        "Мы разберёмся и поможем."
    )
