# src/handlers/balance.py

import json
from typing import Dict

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    PreCheckoutQuery,
    SuccessfulPayment,
)
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Импортируем функции работы с пользователями и балансом из БД
from src.db import (
    get_user_balance as db_get_user_balance,
    get_user_by_telegram_id,
    change_user_balance, add_referral_earnings,
)

router = Router()

ADM_GROUP_ID = -5075627878

# Токен платёжного провайдера (Юкасса через BotFather)
# Для теста можно подставить TEST-токен, для прода — LIVE-токен
PAYMENT_PROVIDER_TOKEN = "390540012:LIVE:84036"

# Цена одной фотосессии в рублях
PHOTOSESSION_PRICE_RUB = 49

# Пакеты пополнения: callback_data -> сумма_руб (и платёж, и зачисление)
TOPUP_OPTIONS: Dict[str, int] = {
    "topup_49": 49,
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


async def send_admin_log(bot: Bot, text: str) -> None:
    """
    Отправка красиво оформленного лога в админский чат.
    Не роняет бота, если чат недоступен.
    """
    try:
        await bot.send_message(
            chat_id=ADM_GROUP_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        # Логирование не должно ломать основной поток
        return


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
                    text="Промокод",
                    callback_data="promo_code"
                )
            ],

            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="back_to_main_menu",
                )
            ]
        ]
    )

async def send_quick_topup_invoice_49(callback: CallbackQuery) -> None:
    """
    Специальная быстрая оплата на 49 ₽ для сценария "нехватка средств".
    Всегда отправляет invoice в ЛС пользователю (bot.send_invoice),
    чтобы не зависеть от чата/топика, где была нажата кнопка.
    """
    bot = callback.bot
    user_id = callback.from_user.id
    username = callback.from_user.username or "—"

    pay_amount_rub = 49
    credit_amount_rub = 49

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
        # Отправляем инвойс в личку пользователя
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

        # Если кнопку нажали не в личке — подскажем, где появилась оплата
        if callback.message and callback.message.chat.id != user_id:
            await callback.message.answer("Я отправил оплату тебе в личные сообщения с ботом ✅")

        await send_admin_log(
            bot,
            (
                "⚡️ <b>Quick topup invoice (49 ₽) отправлен</b>\n"
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
            [
                InlineKeyboardButton(
                    text="Создать фотосессию ✨",
                    callback_data="make_photo",
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
# =====================================================================ё

@router.callback_query(F.data == "balance")
async def open_balance(callback: CallbackQuery) -> None:
    """
    Пользователь нажал кнопку «Баланс» в главном меню.
    Показываем текущий баланс из БД и варианты пополнения.
    """
    telegram_id = callback.from_user.id
    username = callback.from_user.username or "—"
    bot = callback.bot

    text = await format_balance_message(telegram_id)
    current_balance = await get_balance_rub(telegram_id)

    await callback.message.edit_text(
        text,
        reply_markup=get_balance_keyboard(),
    )
    await callback.answer()

    # Лог в админский чат
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
    await callback.answer()  # сразу, чтобы не "крутилось"

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
        # ✅ ВАЖНО: всегда шлём инвойс в ЛИЧКУ пользователю
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

        # Если кнопку нажали НЕ в личке — можно подсказать где искать оплату
        if callback.message and callback.message.chat.id != user_id:
            await callback.message.answer("Я отправил оплату тебе в личные сообщения с ботом ✅")

    except TelegramForbiddenError as e:
        # Бот не может написать пользователю в личку (не нажимал /start)
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
        # Тут будет реальная причина от Telegram (и её нужно видеть)
        await send_admin_log(
            bot,
            (
                "🔴 <b>Ошибка TelegramBadRequest при отправке invoice</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"Тариф: <code>{option_key}</code>\n"
                f"Сумма: <b>{pay_amount_rub} ₽</b>\n"
                f"provider_data: <code>{provider_data}</code>\n"
                f"Ошибка: <code>{e}</code>"
            ),
        )
        await callback.message.answer(
            "Не удалось открыть оплату 😔\n"
            "Попробуй ещё раз или выбери другую сумму.",
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
            "Не удалось открыть оплату 😔\n"
            "Попробуй ещё раз или выбери другую сумму.",
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
        "Введи сумму пополнения в рублях (от 100 до 10 000), только число.\n\n"
        "Например: 500"
    )
    await state.set_state(TopupStates.waiting_for_custom_amount)
    await callback.answer()

    # Логируем переход к вводу произвольной суммы
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

    raw = message.text.replace(" ", "")
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
    if amount_rub < 100 or amount_rub > 10_000:
        await message.answer("Сумма должна быть от 100 до 10 000 ₽. Попробуй ещё раз.")

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

    # Логируем создание инвойса с произвольной суммой
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
    """
    Обязательный шаг для платежей Telegram:
    на каждый PreCheckoutQuery нужно ответить answerPreCheckoutQuery.
    """
    payload = pre_checkout_query.invoice_payload
    total_amount = pre_checkout_query.total_amount
    currency = pre_checkout_query.currency
    user = pre_checkout_query.from_user
    username = user.username or "—"
    user_id = user.id

    order_info = pre_checkout_query.order_info
    email = None
    phone_number = None
    shipping_address = None

    if order_info is not None:
        email = getattr(order_info, "email", None)
        phone_number = getattr(order_info, "phone_number", None)
        shipping_address = getattr(order_info, "shipping_address", None)

    # Логируем pre-checkout (по сути "чек до подтверждения")
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
            error_message=(
                "Платёж не прошёл.\n"
                "Попробуй ещё раз или выбери другую сумму."
            ),
        )

        # Логируем отказ pre-checkout
        await send_admin_log(
            bot,
            (
                "❌ <b>PreCheckout отклонён: некорректный payload</b>\n"
                f"Пользователь: <code>{user_id}</code> @{username}\n"
                f"payload: <code>{payload}</code>\n"
                f"Сумма (total_amount): <b>{total_amount}</b> ({amount_rub:.2f} {currency})"
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

    # Обрабатываем только пополнение баланса
    if not payload.startswith("balance_topup"):
        return

    credited_amount_rub = payment.total_amount // 100

    telegram_id = message.from_user.id
    username = message.from_user.username or "—"
    bot = message.bot

    new_balance = await add_to_balance_rub(telegram_id, credited_amount_rub)

    # ✅ Реферальный процент с пополнения (пример: 5%)
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

    await message.answer(
        text,
        reply_markup=get_after_success_keyboard(),
    )

    # Лог успешного пополнения "как в чеке"
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
        "Платёж не прошёл.\n"
        "Попробуй ещё раз или выбери другую сумму.",
        reply_markup=get_payment_error_keyboard(),
    )
    await callback.answer()

    # Логируем факт показа сообщения о неуспешном платеже
    await send_admin_log(
        bot,
        (
            "❌ <b>Пользователь увидел сообщение о неуспешном платеже</b>\n"
            f"Пользователь: <code>{user_id}</code> @{username}"
        ),
    )
