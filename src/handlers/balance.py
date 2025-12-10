# src/handlers/balance.py

import asyncio
import json
from typing import Dict

from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    SuccessfulPayment,
    ContentType,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Импортируем функции работы с пользователями и балансом из БД
from src.db import (
    get_user_balance as db_get_user_balance,
    get_user_by_telegram_id,
    change_user_balance,
)

router = Router()

# Токен платёжного провайдера (Юкасса через BotFather)
# Для теста можно подставить TEST-токен, для прода — LIVE-токен
PAYMENT_PROVIDER_TOKEN = "390540012:LIVE:84036"

# Цена одной фотосессии в рублях
PHOTOSESSION_PRICE_RUB = 50

# Пакеты пополнения: callback_data -> сумма_руб (и платёж, и зачисление)
TOPUP_OPTIONS: Dict[str, int] = {
    "topup_350": 350,
    "topup_1000": 1000,
    "topup_2000": 2000,
}

# Налоговая система для чеков (уточни в ЛК ЮKassa при необходимости)
# 1 — ОСН, 2 — УСН доход, 3 — УСН доход-расход, 4 — ЕНВД, 5 — ЕСХН, 6 — ПСН
TAX_SYSTEM_CODE = 1

# Ставка НДС для чека (уточни под себя)
# 1 — НДС 0%, 2 — НДС 10%, 3 — НДС 20%, 4 — НДС 10/110, 5 — НДС 20/120, 6 — без НДС
VAT_CODE = 1

# Предмет и способ оплаты в чеке
PAYMENT_MODE = "full_payment"      # полный расчёт
PAYMENT_SUBJECT = "service"        # услуга (цифровой сервис)


class TopupStates(StatesGroup):
    waiting_for_custom_amount = State()


# =====================================================================
# Вспомогательные функции (через БД)
# =====================================================================

async def get_balance_rub(telegram_id: int) -> int:
    """
    Получить баланс пользователя из БД.
    Функция db_get_user_balance внутри сама создаёт пользователя при необходимости.
    """
    balance = await db_get_user_balance(telegram_id)
    return int(balance or 0)


async def add_to_balance_rub(telegram_id: int, amount_rub: int) -> int:
    """
    Начислить пользователю amount_rub рублей на баланс.
    Возвращает новый баланс.
    """
    # Гарантируем, что пользователь существует
    await get_user_by_telegram_id(telegram_id)

    user = await change_user_balance(telegram_id, amount_rub)
    if user is None:
        # На всякий случай считаем ещё раз из БД
        return await get_balance_rub(telegram_id)
    return int(user.balance or 0)


def calc_photosessions_left(balance_rub: int) -> int:
    if PHOTOSESSION_PRICE_RUB <= 0:
        return 0
    return balance_rub // PHOTOSESSION_PRICE_RUB


async def format_balance_message(telegram_id: int) -> str:
    balance_rub = await get_balance_rub(telegram_id)
    sessions_left = calc_photosessions_left(balance_rub)

    return (
        f"Ваш баланс: {balance_rub} ₽\n"
        f"Доступно фотосессий по {PHOTOSESSION_PRICE_RUB} ₽: {sessions_left}\n\n"
        "Выберите сумму пополнения или введите свою:\n\n"
        "• 350 ₽\n"
        "• 1 000 ₽\n"
        "• 2 000 ₽"
    )


def get_balance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить на 350 ₽",
                    callback_data="topup_350",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Пополнить на 1 000 ₽",
                    callback_data="topup_1000",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Пополнить на 2 000 ₽",
                    callback_data="topup_2000",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Другая сумма",
                    callback_data="topup_custom",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )


def get_after_success_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать фотосессию ✨",
                    callback_data="create_photosession",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )


def get_payment_error_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Попробовать ещё раз",
                    callback_data="balance",  # вызываем open_balance
                )
            ],
            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="back_to_main_menu",
                )
            ],
        ]
    )


def build_provider_data(description: str, amount_rub: int) -> str:
    """
    Сформировать provider_data с чеком для ЮKassa.

    ВАЖНО:
    - amount в инвойсе в копейках,
    - amount.value в чеке в рублях (строкой).
    """
    receipt = {
        "receipt": {
            "items": [
                {
                    "description": description[:128],  # ограничение Telegram/YooKassa
                    "quantity": 1,
                    "amount": {
                        "value": f"{amount_rub:.2f}",  # рубли, строкой
                        "currency": "RUB",
                    },
                    "vat_code": VAT_CODE,
                    "payment_mode": PAYMENT_MODE,
                    "payment_subject": PAYMENT_SUBJECT,
                }
            ],
            "tax_system_code": TAX_SYSTEM_CODE,
        }
    }
    # Telegram ждёт provider_data как JSON-строку
    return json.dumps(receipt, ensure_ascii=False)


# =====================================================================
# Вход в раздел «Баланс»
# =====================================================================

@router.callback_query(F.data == "balance")
async def open_balance(callback: CallbackQuery) -> None:
    """
    Пользователь нажал кнопку «Баланс» в главном меню.
    Показываем текущий баланс из БД и варианты пополнения.
    """
    telegram_id = callback.from_user.id
    text = await format_balance_message(telegram_id)

    await callback.message.edit_text(
        text,
        reply_markup=get_balance_keyboard(),
    )
    await callback.answer()


# =====================================================================
# Выбор готового пакета пополнения
# =====================================================================

@router.callback_query(F.data.in_(set(TOPUP_OPTIONS.keys())))
async def choose_topup_package(callback: CallbackQuery) -> None:
    """
    Пользователь выбрал пакет пополнения (350, 1000 или 2000 ₽).
    Отправляем инвойс на оплату.
    """
    option_key = callback.data
    pay_amount_rub = TOPUP_OPTIONS[option_key]
    credit_amount_rub = pay_amount_rub  # пополняем 1 к 1

    prices = [
        LabeledPrice(
            label=f"Пополнение баланса на {credit_amount_rub} ₽",
            amount=pay_amount_rub * 100,  # amount в копейках
        )
    ]

    payload = f"balance_topup:{pay_amount_rub}"

    provider_data = build_provider_data(
        description=f"Пополнение баланса на {credit_amount_rub} ₽",
        amount_rub=pay_amount_rub,
    )

    await callback.message.answer_invoice(
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
        # важные флаги для чека через ЮKassa (способ 2 из письма поддержки)
        need_email=True,
        send_email_to_provider=True,
        need_phone_number=False,
        send_phone_number_to_provider=False,
        need_shipping_address=False,
        is_flexible=False,
        max_tip_amount=0,
        provider_data=provider_data,
    )

    await callback.answer()


# =====================================================================
# Другая сумма
# =====================================================================

@router.callback_query(F.data == "topup_custom")
async def topup_custom_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text(
        "Введи сумму пополнения в рублях (от 100 до 10 000), только число.\n\n"
        "Например: 500"
    )
    await state.set_state(TopupStates.waiting_for_custom_amount)
    await callback.answer()


@router.message(TopupStates.waiting_for_custom_amount)
async def topup_custom_amount(message: Message, state: FSMContext) -> None:
    raw = message.text.replace(" ", "")
    if not raw.isdigit():
        await message.answer("Пожалуйста, отправь сумму цифрами, например: 500")
        return

    amount_rub = int(raw)
    if amount_rub < 100 or amount_rub > 10_000:
        await message.answer("Сумма должна быть от 100 до 10 000 ₽. Попробуй ещё раз.")
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


# =====================================================================
# Pre Checkout
# =====================================================================

@router.pre_checkout_query()
async def process_pre_checkout(
    pre_checkout_query: PreCheckoutQuery,
    bot: Bot,
) -> None:
    """
    Обязательный шаг для платежей Telegram:
    на каждый PreCheckoutQuery нужно ответить answerPreCheckoutQuery.
    """
    payload = pre_checkout_query.invoice_payload

    print("=== PRE CHECKOUT ===")
    print("payload:", payload)
    print("total_amount:", pre_checkout_query.total_amount)
    print("currency:", pre_checkout_query.currency)

    if not payload.startswith("balance_topup"):
        await bot.answer_pre_checkout_query(
            pre_checkout_query.id,
            ok=False,
            error_message=(
                "Платёж не прошёл.\n"
                "Попробуй ещё раз или выбери другую сумму."
            ),
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

    print("=== SUCCESSFUL PAYMENT ===")
    print("payload:", payload)
    print("total_amount:", payment.total_amount)
    print("currency:", payment.currency)
    print("telegram_charge_id:", payment.telegram_payment_charge_id)
    print("provider_charge_id:", payment.provider_payment_charge_id)

    # Обрабатываем только пополнение баланса
    if not payload.startswith("balance_topup"):
        return

    credited_amount_rub = payment.total_amount // 100

    telegram_id = message.from_user.id
    new_balance = await add_to_balance_rub(telegram_id, credited_amount_rub)

    text = (
        "Оплата прошла успешно!\n"
        f"На баланс зачислено {credited_amount_rub} ₽.\n\n"
        "Теперь можно создавать фотосессии ✨\n\n"
        f"Текущий баланс: {new_balance} ₽"
    )

    await message.answer(
        text,
        reply_markup=get_after_success_keyboard(),
    )


# =====================================================================
# Сообщение «платёж не прошёл»
# =====================================================================

@router.callback_query(F.data == "payment_failed_show_message")
async def payment_failed_message(callback: CallbackQuery) -> None:
    await callback.message.answer(
        "Платёж не прошёл.\n"
        "Попробуй ещё раз или выбери другую сумму.",
        reply_markup=get_payment_error_keyboard(),
    )
    await callback.answer()
