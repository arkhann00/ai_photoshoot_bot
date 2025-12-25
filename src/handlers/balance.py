# src/handlers/balance.py

import json
from typing import Dict, Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    SuccessfulPayment,
)

# Импортируем функции работы с пользователями и балансом из БД
from src.db import (
    add_referral_earnings,
    change_user_balance,
    get_user_balance as db_get_user_balance,
    get_user_by_telegram_id,
)

router = Router()

ADM_GROUP_ID = -5075627878

PAYMENT_PROVIDER_TOKEN = "390540012:LIVE:84036"

# ✅ Минимальная сумма пополнения (из-за ограничения Telegram/провайдера)
MIN_TOPUP_RUB = 99

# Тарифы генерации по количеству фото (шт -> ₽)
PHOTO_PACK_PRICES_RUB: Dict[int, int] = {
    1: 49,
    2: 80,
    3: 100,
    5: 125,
    10: 200,
}

# Пакеты пополнения: callback_data -> сумма_руб (и платёж, и зачисление)
TOPUP_OPTIONS: Dict[str, int] = {
    "topup_99": 99,
    "topup_100": 100,
    "topup_125": 125,
    "topup_200": 200,
}

TAX_SYSTEM_CODE = 1
VAT_CODE = 1
PAYMENT_MODE = "full_payment"
PAYMENT_SUBJECT = "service"


class TopupStates(StatesGroup):
    waiting_for_custom_amount = State()


async def send_admin_log(bot: Bot, text: str) -> None:
    try:
        await bot.send_message(
            chat_id=ADM_GROUP_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
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

    tariffs = "\n".join(
        f"• {cnt} фото — {price} ₽"
        for cnt, price in sorted(PHOTO_PACK_PRICES_RUB.items(), key=lambda x: x[0])
    )

    return (
        f"Ваш баланс: {balance_rub} ₽\n\n"
        "Тарифы:\n"
        f"{tariffs}\n"
    )


def get_balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text="Минимальное пополнение — 99 ₽",
                callback_data="topup_99"
            )],
            [InlineKeyboardButton(text="Пополнить: 3 фото — 100 ₽", callback_data="topup_100")],
            [InlineKeyboardButton(text="Пополнить: 5 фото — 125 ₽", callback_data="topup_125")],
            [InlineKeyboardButton(text="Пополнить: 10 фото — 200 ₽", callback_data="topup_200")],
            [InlineKeyboardButton(text="Другая сумма", callback_data="topup_custom")],
            [InlineKeyboardButton(text="Промокод", callback_data="promo_code")],
            [InlineKeyboardButton(text="Главное меню", callback_data="back_to_main_menu")],
        ]
    )


async def send_quick_topup_invoice_49(callback: CallbackQuery) -> None:
    """
    ⚠️ Имя оставлено для совместимости с остальным кодом,
    но фактически минимальный quick topup теперь 50 ₽.
    """
    bot = callback.bot
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"

    pay_amount_rub = MIN_TOPUP_RUB
    credit_amount_rub = MIN_TOPUP_RUB

    prices = [
        LabeledPrice(
            label=f"Пополнение баланса на {credit_amount_rub} ₽",
            amount=pay_amount_rub * 100,
        )
    ]

    payload = f"balance_topup:{pay_amount_rub}"

    provider_data = build_provider_data(
        description=f"Пополнение баланса на {credit_amount_rub} ₽",
        amount_rub=pay_amount_rub,
    )

    try:
        await bot.send_invoice(
            chat_id=user_id,
            title="Пополнение баланса",
            description=(
                "Пополнение баланса аккаунта.\n"
                f"Вы платите {pay_amount_rub} ₽, "
                f"на баланс будет зачислено {credit_amount_rub} ₽."
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
                f"payload: <code>{payload}</code>"
            ),
        )

    except TelegramForbiddenError as e:
        await send_admin_log(
            bot,
            (
                "🔴 <b>Quick topup: Forbidden (бот не может написать в ЛС)</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )
        await callback.message.answer(
            "Чтобы оплатить, открой бота в личных сообщениях и нажми /start, затем повтори попытку.",
            reply_markup=get_payment_error_keyboard(),
        )

    except TelegramBadRequest as e:
        await send_admin_log(
            bot,
            (
                "🔴 <b>Quick topup: TelegramBadRequest при отправке invoice</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Ошибка: <code>{e}</code>\n"
                f"provider_data: <code>{provider_data}</code>"
            ),
        )
        await callback.message.answer(
            "Не удалось открыть оплату 😔\nПопробуй ещё раз или выбери другую сумму.",
            reply_markup=get_payment_error_keyboard(),
        )

    except Exception as e:
        await send_admin_log(
            bot,
            (
                "🔴 <b>Quick topup: неизвестная ошибка</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )
        await callback.message.answer(
            "Не удалось открыть оплату 😔\nПопробуй ещё раз или выбери другую сумму.",
            reply_markup=get_payment_error_keyboard(),
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
                    "quantity": "1.00",  # ✅ строкой
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


# =====================================================================
# Вход в раздел «Баланс»
# =====================================================================

@router.callback_query(F.data == "balance")
async def open_balance(callback: CallbackQuery) -> None:
    telegram_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    text = await format_balance_message(telegram_id)
    current_balance = await get_balance_rub(telegram_id)

    await callback.message.edit_text(text, reply_markup=get_balance_keyboard())
    await callback.answer()

    await send_admin_log(
        bot,
        (
            "💼 <b>Открыт раздел «Баланс»</b>\n"
            f"Пользователь: <code>{telegram_id}</code> @{username}\n"
            f"Текущий баланс: <b>{current_balance} ₽</b>"
        ),
    )


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

    credit_amount_rub = pay_amount_rub

    prices = [
        LabeledPrice(
            label=f"Пополнение баланса на {credit_amount_rub} ₽",
            amount=pay_amount_rub * 100,
        )
    ]

    payload = f"balance_topup:{pay_amount_rub}"

    provider_data = build_provider_data(
        description=f"Пополнение баланса на {credit_amount_rub} ₽",
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
                f"на баланс будет зачислено {credit_amount_rub} ₽."
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
                f"Тариф-кнопка: <code>{option_key}</code>\n"
                f"Сумма к оплате: <b>{pay_amount_rub} ₽</b>\n"
                f"payload: <code>{payload}</code>"
            ),
        )

    except TelegramForbiddenError as e:
        await send_admin_log(
            bot,
            (
                "🔴 <b>Не удалось отправить invoice в личку (Forbidden)</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Тариф: <code>{option_key}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )
        await callback.message.answer(
            "Чтобы оплатить, открой бота в личных сообщениях и нажми «Баланс» → выбери сумму.\n"
            "Если бот ещё не открыт — нажми /start в личке.",
            reply_markup=get_payment_error_keyboard(),
        )

    except TelegramBadRequest as e:
        await send_admin_log(
            bot,
            (
                "🔴 <b>TelegramBadRequest при отправке invoice</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Тариф: <code>{option_key}</code>\n"
                f"Сумма: <b>{pay_amount_rub} ₽</b>\n"
                f"provider_data: <code>{provider_data}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )
        await callback.message.answer(
            "Не удалось открыть оплату 😔\nПопробуй ещё раз или выбери другую сумму.",
            reply_markup=get_payment_error_keyboard(),
        )

    except Exception as e:
        await send_admin_log(
            bot,
            (
                "🔴 <b>Неизвестная ошибка при отправке invoice</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Тариф: <code>{option_key}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )
        await callback.message.answer(
            "Не удалось открыть оплату 😔\nПопробуй ещё раз или выбери другую сумму.",
            reply_markup=get_payment_error_keyboard(),
        )


# =====================================================================
# Другая сумма
# =====================================================================

@router.callback_query(F.data == "topup_custom")
async def topup_custom_start(callback: CallbackQuery, state: FSMContext) -> None:
    bot = callback.bot
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"

    await callback.message.edit_text(
        f"Введи сумму пополнения в рублях (от {MIN_TOPUP_RUB} до 10 000), только число.\n\n"
        "Например: 500"
    )
    await state.set_state(TopupStates.waiting_for_custom_amount)
    await callback.answer()

    await send_admin_log(
        bot,
        (
            "📝 <b>Пользователь выбирает произвольную сумму пополнения</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}"
        ),
    )


@router.message(TopupStates.waiting_for_custom_amount)
async def topup_custom_amount(message: Message, state: FSMContext) -> None:
    bot = message.bot
    user_id = message.from_user.id
    username = message.from_user.username or "—"

    raw = (message.text or "").replace(" ", "")
    if not raw.isdigit():
        await message.answer("Пожалуйста, отправь сумму цифрами, например: 500")
        await send_admin_log(
            bot,
            (
                "⚠️ <b>Некорректный ввод суммы пополнения</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Введено: <code>{message.text}</code>"
            ),
        )
        return

    amount_rub = int(raw)
    if amount_rub < MIN_TOPUP_RUB or amount_rub > 10_000:
        await message.answer(f"Сумма должна быть от {MIN_TOPUP_RUB} до 10 000 ₽. Попробуй ещё раз.")
        await send_admin_log(
            bot,
            (
                "⚠️ <b>Сумма пополнения вне допустимого диапазона</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Запрошенная сумма: <b>{amount_rub} ₽</b>"
            ),
        )
        return

    credit_amount_rub = amount_rub

    prices = [
        LabeledPrice(
            label=f"Пополнение баланса на {credit_amount_rub} ₽",
            amount=amount_rub * 100,
        )
    ]

    payload = f"balance_topup_custom:{amount_rub}"

    provider_data = build_provider_data(
        description=f"Пополнение баланса на {credit_amount_rub} ₽",
        amount_rub=amount_rub,
    )

    await message.answer_invoice(
        title="Пополнение баланса",
        description=(
            "Пополнение баланса аккаунта.\n"
            f"Вы платите {amount_rub} ₽, "
            f"на баланс будет зачислено {credit_amount_rub} ₽."
        ),
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="RUB",
        prices=prices,
        payload=payload,
        start_parameter="balance_topup_custom",
        need_email=True,
        send_email_to_provider=True,
        need_phone_number=False,
        send_phone_number_to_provider=False,
        need_shipping_address=False,
        is_flexible=False,
        max_tip_amount=0,
        provider_data=provider_data,
    )

    await state.clear()

    await send_admin_log(
        bot,
        (
            "💳 <b>Создан инвойс с произвольной суммой пополнения</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}\n"
            f"Сумма к оплате (invoice): <b>{amount_rub} ₽</b>\n"
            f"Будет зачислено на баланс: <b>{credit_amount_rub} ₽</b>\n"
            "Тип: <code>custom</code>\n"
            f"payload: <code>{payload}</code>\n"
            f"provider_data: <code>{provider_data}</code>"
        ),
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
    currency = pre_checkout_query.currency
    user = pre_checkout_query.from_user
    username = user.username or "—"
    user_id = user.id

    order_info = pre_checkout_query.order_info
    email: Optional[str] = None
    phone_number: Optional[str] = None
    shipping_address = None

    if order_info is not None:
        email = getattr(order_info, "email", None)
        phone_number = getattr(order_info, "phone_number", None)
        shipping_address = getattr(order_info, "shipping_address", None)

    amount_rub = total_amount / 100.0

    await send_admin_log(
        bot,
        (
            "🧾 <b>PreCheckout по пополнению баланса</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}\n"
            f"Сумма (total_amount): <b>{total_amount}</b> (≈ {amount_rub:.2f} {currency})\n"
            f"Валюта: <b>{currency}</b>\n"
            f"payload: <code>{payload}</code>\n"
            f"email: <code>{email or '—'}</code>\n"
            f"phone_number: <code>{phone_number or '—'}</code>\n"
            f"shipping_address: <code>{str(shipping_address) if shipping_address else '—'}</code>"
        ),
    )

    if not payload.startswith("balance_topup"):
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message="Платёж не прошёл.\nПопробуй ещё раз или выбери другую сумму.",
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

    if not payload.startswith("balance_topup"):
        return

    credited_amount_rub = payment.total_amount // 100

    telegram_id = message.from_user.id
    username = message.from_user.username or "—"
    bot = message.bot

    new_balance = await add_to_balance_rub(telegram_id, credited_amount_rub)

    REF_TOPUP_PERCENT = 5

    user_db = await get_user_by_telegram_id(telegram_id)
    referrer_id = getattr(user_db, "referrer_id", None)

    if referrer_id:
        reward = int(credited_amount_rub * REF_TOPUP_PERCENT / 100)
        if reward > 0:
            await add_referral_earnings(int(referrer_id), reward)

            await send_admin_log(
                bot,
                (
                    "🤝 <b>Реферальное начисление с пополнения</b>\n"
                    f"Реферал: <code>{telegram_id}</code> @{username}\n"
                    f"Пригласитель: <code>{referrer_id}</code>\n"
                    f"Пополнение: <b>{credited_amount_rub} ₽</b>\n"
                    f"Начислено пригласителю: <b>{reward} ₽</b>"
                ),
            )

    text = (
        "Оплата прошла успешно!\n"
        f"На баланс зачислено {credited_amount_rub} ₽.\n\n"
        "Теперь можно создавать фотосессии ✨\n\n"
        f"Текущий баланс: {new_balance} ₽"
    )

    await message.answer(text, reply_markup=get_after_success_keyboard())

    total_amount_rub = payment.total_amount / 100.0

    await send_admin_log(
        bot,
        (
            "✅ <b>Успешное пополнение баланса</b>\n"
            f"Пользователь: <code>{telegram_id}</code> @{username}\n"
            f"Сумма платежа (total_amount): <b>{payment.total_amount}</b> "
            f"(≈ {total_amount_rub:.2f} {payment.currency})\n"
            f"Зачислено на баланс: <b>{credited_amount_rub} ₽</b>\n"
            f"Новый баланс пользователя: <b>{new_balance} ₽</b>\n"
            f"payload: <code>{payload}</code>\n"
            f"telegram_payment_charge_id: <code>{payment.telegram_payment_charge_id}</code>\n"
            f"provider_payment_charge_id: <code>{payment.provider_payment_charge_id}</code>"
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

    await send_admin_log(
        bot,
        (
            "❌ <b>Пользователь увидел сообщение о неуспешном платеже</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}"
        ),
    )