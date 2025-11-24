# src/handlers/payments_stars.py

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from data.star_offers import STAR_OFFERS, get_offer_by_code
from db import (
    create_star_payment,
    mark_star_payment_success,
    get_user_by_telegram_id,
)
from keyboards import get_start_keyboard  # если у тебя уже есть


router = Router()


# ---------- Клавиатура с пакетами Stars ----------

def get_stars_offers_keyboard() -> InlineKeyboardMarkup:
    buttons = []

    for offer in STAR_OFFERS:
        text = f"{offer.title} — {offer.amount_stars} ⭐"
        callback_data = f"buy_stars:{offer.code}"
        buttons.append(
            [InlineKeyboardButton(text=text, callback_data=callback_data)]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                text="Вернуться в главное меню",
                callback_data="back_to_main_menu",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ---------- Открываем выбор пакетов при "Пополнить баланс" ----------

@router.callback_query(F.data == "topup_balance")
async def topup_balance_menu(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Выбери пакет фотосессий, который хочешь купить через Telegram Stars:",
        reply_markup=get_stars_offers_keyboard(),
    )


# ---------- Покупка конкретного пакета ----------

@router.callback_query(F.data.startswith("buy_stars:"))
async def buy_stars_offer(callback: CallbackQuery):
    await callback.answer()

    code = callback.data.split(":", 1)[1]
    offer = get_offer_by_code(code)

    if offer is None:
        await callback.message.edit_text(
            "Это предложение больше недоступно. Попробуй другой пакет."
        )
        return

    # Создаём запись платежа в БД
    payment = await create_star_payment(
        telegram_id=callback.from_user.id,
        offer=offer,
    )

    prices = [
        LabeledPrice(
            label=offer.title,
            amount=offer.amount_stars,  # Stars — целое число
        )
    ]

    await callback.message.edit_text(
        f"Счёт на {offer.amount_stars} ⭐ за {offer.title}. "
        "После оплаты тебе будут начислены фотосессии."
    )

    await callback.message.bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=offer.title,
        description=offer.description,
        payload=payment.payload,
        provider_token="",      # для Stars — пустая строка
        currency="XTR",         # Telegram Stars
        prices=prices,
    )


# ---------- Pre-checkout (обязательный шаг) ----------

@router.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    # Здесь можно добавить доп. проверки (например, не отключен ли оффер)
    await pre_checkout_query.edit_text(ok=True)


# ---------- Успешный платёж ----------

@router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    sp = message.successful_payment

    payload = sp.invoice_payload
    total_amount = sp.total_amount
    currency = sp.currency
    telegram_charge_id = sp.telegram_payment_charge_id

    result = await mark_star_payment_success(
        payload=payload,
        telegram_charge_id=telegram_charge_id,
        total_amount=total_amount,
        currency=currency,
    )

    if result is None:
        await message.edit_text(
            "Оплата прошла, но мы не смогли сопоставить платёж с заказом. "
            "Напиши, пожалуйста, в поддержку: @ai_photo_help."
        )
        return

    user, payment = result

    await message.edit_text(
        "Оплата успешно получена! 🎉\n\n"
        f"Начислено фотосессий: {payment.credits}.\n"
        f"Теперь у тебя доступно: {user.photoshoot_credits} фотосессий."
    )


# ---------- Возврат в главное меню ----------

@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu(callback: CallbackQuery):
    from src.states import MainStates
    from aiogram.fsm.context import FSMContext

    state: FSMContext = callback.bot.dispatcher.fsm.get_context(
        bot=callback.bot,
        user_id=callback.from_user.id,
        chat_id=callback.message.chat.id,
    )

    await state.set_state(MainStates.start)
    await callback.answer()
    await callback.message.edit_text(
        "Возвращаю в главное меню. Выбери действие:",
        reply_markup=get_start_keyboard(),
    )
