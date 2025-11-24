from __future__ import annotations

from typing import List

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from src.states import AdminStates
from src.db import (
    get_users_page,
    search_users,
    change_user_credits,
    get_user_by_telegram_id,
    change_user_balance,          # добавили
    get_photoshoot_report,        # добавили
    get_payments_report,          # добавили
    create_style_prompt,
get_admin_users,

)
from aiogram.filters import Command

from src.services.admins import (
    is_admin,
    add_admin,
    remove_admin,
    get_admin_ids,
)
from src.db import SUPER_ADMIN_ID


router = Router()

ADMIN_IDS = [707366569]



def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 Пользователи",
                    callback_data="admin_users:0",
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Отчёт (7 дней)",
                    callback_data="admin_report_7d",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔍 Поиск пользователя",
                    callback_data="admin_search",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧩 Добавить стиль",
                    callback_data="admin_style_add",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔐 Сменить API ключ",
                    callback_data="admin_change_api_key",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Выйти из админ-панели",
                    callback_data="admin_exit",
                )
            ],
        ]
    )



def get_user_manage_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ 1 фотосессию",
                    callback_data=f"admin_user_add_credit:{telegram_id}",
                ),
                InlineKeyboardButton(
                    text="➖ 1 фотосессию",
                    callback_data=f"admin_user_sub_credit:{telegram_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➕ 100 ₽",
                    callback_data=f"admin_user_add_balance_100:{telegram_id}",
                ),
                InlineKeyboardButton(
                    text="➖ 100 ₽",
                    callback_data=f"admin_user_sub_balance_100:{telegram_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ В админ-меню",
                    callback_data="admin_menu",
                )
            ],
        ]
    )

def get_users_page_keyboard(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data=f"admin_users:{page - 1}",
            )
        )
    if has_next:
        nav_row.append(
            InlineKeyboardButton(
                text="Вперёд ➡️",
                callback_data=f"admin_users:{page + 1}",
            )
        )
    if nav_row:
        buttons.append(nav_row)

    buttons.append(
        [
            InlineKeyboardButton(
                text="⬅️ В админ-меню",
                callback_data="admin_menu",
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_user_manage_keyboard(telegram_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="➕ 1 фотосессию",
                    callback_data=f"admin_user_add_credit:{telegram_id}",
                ),
                InlineKeyboardButton(
                    text="➖ 1 фотосессию",
                    callback_data=f"admin_user_sub_credit:{telegram_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ В админ-меню",
                    callback_data="admin_menu",
                )
            ],
        ]
    )


def format_user_line(user) -> str:
    username = f"@{user.username}" if user.username else "—"
    return (
        f"👤 <b>{user.telegram_id}</b> {username}\n"
        f"   Баланс: {user.balance} ₽, фотосессий: {user.photoshoot_credits}"
    )


# ---------- Команда /admin ----------

@router.message(F.text == "/admin")
async def admin_start(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    await state.set_state(AdminStates.admin_menu)

    await message.answer(
        "👑 Добро пожаловать в админ-панель.\n\n"
        "Выбери раздел:",
        reply_markup=get_admin_main_keyboard(),
    )


# ---------- Главное меню админа ----------

@router.callback_query(F.data == "admin_menu")
async def admin_menu(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    await state.set_state(AdminStates.admin_menu)

    await callback.message.edit_text(
        "👑 Админ-панель.\n\nВыбери раздел:",
        reply_markup=get_admin_main_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_exit")
async def admin_exit(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    await state.clear()
    await callback.message.edit_text("Вы вышли из админ-панели.")
    await callback.answer()


# ---------- Список пользователей (постранично) ----------

@router.callback_query(F.data.startswith("admin_users:"))
async def admin_users_list(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    await state.set_state(AdminStates.admin_menu)

    try:
        page_str = callback.data.split(":", 1)[1]
        page = int(page_str)
    except Exception:
        page = 0

    if page < 0:
        page = 0

    page_size = 10
    users, total = await get_users_page(page=page, page_size=page_size)

    if not users:
        text = "Пользователи не найдены."
        keyboard = get_admin_main_keyboard()
    else:
        lines: list[str] = []
        lines.append(f"📋 Список пользователей (страница {page + 1})\n")
        for user in users:
            lines.append(format_user_line(user))
        lines.append(f"\nВсего пользователей: {total}")

        text = "\n".join(lines)

        has_prev = page > 0
        has_next = (page + 1) * page_size < total

        keyboard = get_users_page_keyboard(page=page, has_prev=has_prev, has_next=has_next)

    await callback.message.edit_text(
        text,
        reply_markup=keyboard,
    )
    await callback.answer()


# ---------- Поиск пользователя ----------

@router.callback_query(F.data == "admin_search")
async def admin_search(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    await state.set_state(AdminStates.search_user)

    await callback.message.edit_text(
        "🔍 Введите @username или Telegram ID пользователя для поиска:",
    )
    await callback.answer()


@router.message(AdminStates.search_user)
async def admin_search_input(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    query = message.text.strip()
    users = await search_users(query)

    if not users:
        await message.answer("Ничего не найдено. Попробуйте другой username или ID.")
        await state.set_state(AdminStates.admin_menu)
        await message.answer(
            "👑 Админ-панель.\n\nВыбери раздел:",
            reply_markup=get_admin_main_keyboard(),
        )
        return

    if len(users) == 1:
        user = users[0]
        text = "🔍 Найден пользователь:\n\n" + format_user_line(user)
        await message.answer(
            text,
            reply_markup=get_user_manage_keyboard(user.telegram_id),
        )
    else:
        lines: list[str] = []
        lines.append("🔍 Найдено несколько пользователей:\n")
        for user in users:
            lines.append(format_user_line(user))

        await message.answer("\n".join(lines))

    await state.set_state(AdminStates.admin_menu)
    await message.answer(
        "👑 Админ-панель.\n\nВыбери раздел:",
        reply_markup=get_admin_main_keyboard(),
    )


# ---------- Управление фотосессиями пользователя (credits) ----------

@router.callback_query(F.data.startswith("admin_user_add_credit:"))
async def admin_add_credit(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    try:
        telegram_id_str = callback.data.split(":", 1)[1]
        telegram_id = int(telegram_id_str)
    except Exception:
        await callback.answer("Некорректный ID.")
        return

    user = await change_user_credits(telegram_id=telegram_id, delta=1)
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    text = "✅ Добавлена 1 фотосессия.\n\n" + format_user_line(user)

    await callback.message.edit_text(
        text,
        reply_markup=get_user_manage_keyboard(user.telegram_id),
    )
    await callback.answer("Фотосессия добавлена.")


@router.callback_query(F.data.startswith("admin_user_sub_credit:"))
async def admin_sub_credit(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    try:
        telegram_id_str = callback.data.split(":", 1)[1]
        telegram_id = int(telegram_id_str)
    except Exception:
        await callback.answer("Некорректный ID.")
        return

    user = await change_user_credits(telegram_id=telegram_id, delta=-1)
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    text = "✅ Удалена 1 фотосессия (если была).\n\n" + format_user_line(user)

    await callback.message.edit_text(
        text,
        reply_markup=get_user_manage_keyboard(user.telegram_id),
    )
    await callback.answer("Фотосессия списана.")

@router.callback_query(F.data.startswith("admin_user_add_balance_100:"))
async def admin_add_balance_100(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    try:
        telegram_id_str = callback.data.split(":", 1)[1]
        telegram_id = int(telegram_id_str)
    except Exception:
        await callback.answer("Некорректный ID.")
        return

    user = await change_user_balance(telegram_id=telegram_id, delta=100)
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    text = "✅ Добавлено 100 ₽ на баланс.\n\n" + format_user_line(user)

    await callback.message.edit_text(
        text,
        reply_markup=get_user_manage_keyboard(user.telegram_id),
    )
    await callback.answer("Баланс пополнен на 100 ₽.")


@router.callback_query(F.data.startswith("admin_user_sub_balance_100:"))
async def admin_sub_balance_100(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    try:
        telegram_id_str = callback.data.split(":", 1)[1]
        telegram_id = int(telegram_id_str)
    except Exception:
        await callback.answer("Некорректный ID.")
        return

    user = await change_user_balance(telegram_id=telegram_id, delta=-100)
    if user is None:
        await callback.answer("Пользователь не найден.")
        return

    text = "✅ Списано 100 ₽ с баланса (если было).\n\n" + format_user_line(user)

    await callback.message.edit_text(
        text,
        reply_markup=get_user_manage_keyboard(user.telegram_id),
    )
    await callback.answer("Баланс уменьшен на 100 ₽.")

@router.callback_query(F.data == "admin_report_7d")
async def admin_report_7d(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    photos_report = await get_photoshoot_report(days=7)
    payments_report = await get_payments_report(days=7)

    text = (
        "📊 Отчёт за последние 7 дней\n\n"
        "🖼 Фотосессии:\n"
        f"• Всего: {photos_report['total']}\n"
        f"• Успешных: {photos_report['success']}\n"
        f"• Ошибок: {photos_report['failed']}\n"
        f"• Суммарная стоимость (руб): {photos_report['sum_cost_rub']} ₽\n"
        f"• Списано фотосессий (credits): {photos_report['sum_cost_credits']}\n\n"
        "💰 Пополнения (Stars):\n"
        f"• Успешных платежей: {payments_report['total']}\n"
        f"• Сумма Stars: {payments_report['sum_stars']} ⭐\n"
        f"• Начислено фотосессий: {payments_report['sum_credits']}\n"
    )

    await callback.message.edit_text(
        text,
        reply_markup=get_admin_main_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_style_add")
async def admin_style_add_start(callback: CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id):
        await callback.answer()
        return

    await state.set_state(AdminStates.add_style_title)
    await state.update_data(
        new_style_title=None,
        new_style_description=None,
        new_style_prompt=None,
        new_style_image=None,
    )

    await callback.message.edit_text(
        "🧩 Добавление нового стиля\n\n"
        "Шаг 1/4 — Введи <b>название стиля</b>.\n\n"
    )
    await callback.answer()

@router.message(AdminStates.add_style_title)
async def admin_style_add_title(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    title = message.text.strip()
    if not title:
        await message.answer("Название не может быть пустым. Введи название ещё раз.")
        return

    await state.update_data(new_style_title=title)
    await state.set_state(AdminStates.add_style_description)

    await message.answer(
        "Шаг 2/4 — Введи <b>описание стиля</b>.\n\n"
    )

@router.message(AdminStates.add_style_description)
async def admin_style_add_description(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    description = message.text.strip()
    if not description:
        await message.answer("Описание не может быть пустым. Введи описание ещё раз.")
        return

    await state.update_data(new_style_description=description)
    await state.set_state(AdminStates.add_style_prompt)

    await message.answer(
        "Шаг 3/4 — Введи <b>prompt для ИИ</b>.\n\n"
    )

@router.message(AdminStates.add_style_prompt)
async def admin_style_add_prompt(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    prompt = message.text.strip()
    if not prompt:
        await message.answer("Prompt не может быть пустым. Введи prompt ещё раз.")
        return

    await state.update_data(new_style_prompt=prompt)
    await state.set_state(AdminStates.add_style_image)

    await message.answer(
        "Шаг 4/4 — Выбери картинку для альбома.\n\n"
        "Сейчас можно использовать уже существующие файлы 1–5.\n"
        "Введи номер от 1 до 5.\n\n"
        "Например: <b>1</b>",
    )

@router.message(AdminStates.add_style_image)
async def admin_style_add_image(message: Message, state: FSMContext):
    if not await is_admin(message.from_user.id):
        return

    # Проверяем, что вообще есть текст
    if message.text is None:
        await message.answer(
            "Пожалуйста, пришли <b>номер картинки</b> от 1 до 5 (не имеет значение какую цифру вводить)"
        )
        return

    raw = message.text.strip()

    # Если админ сразу ввёл имя файла – ок
    if raw.endswith(".jpeg") or raw.endswith(".jpg") or raw.endswith(".png") or raw.endswith(".webp"):
        image_filename = raw
    else:
        # ожидаем номер 1–5
        if not raw.isdigit():
            await message.answer(
                "Ожидаю номер картинки от 1 до 5 (или имя файла, например <code>1.jpeg</code>). "
                "Попробуй ещё раз."
            )
            return

        num = int(raw)
        if num < 1 or num > 5:
            await message.answer(
                "Номер должен быть от 1 до 5. Попробуй ещё раз."
            )
            return

        image_filename = f"{num}.jpeg"

    data = await state.get_data()
    title = data.get("new_style_title")
    description = data.get("new_style_description")
    prompt = data.get("new_style_prompt")

    # финальная страховка
    if not title or not description or not prompt:
        await message.answer(
            "Что-то пошло не так с сохранением данных. Попробуй ещё раз добавить стиль."
        )
        await state.set_state(AdminStates.admin_menu)
        await message.answer(
            "👑 Админ-панель.\n\nВыбери раздел:",
            reply_markup=get_admin_main_keyboard(),
        )
        return

    # создаём стиль в БД
    try:
        style = await create_style_prompt(
            title=title,
            description=description,
            prompt=prompt,
            image_filename=image_filename,
        )
    except Exception as e:
        await message.answer(
            "❌ Не удалось сохранить стиль в базе данных.\n"
            f"Техническая ошибка: <code>{e}</code>"
        )
        await state.set_state(AdminStates.admin_menu)
        await message.answer(
            "👑 Админ-панель.\n\nВыбери раздел:",
            reply_markup=get_admin_main_keyboard(),
        )
        return

    await state.set_state(AdminStates.admin_menu)

    await message.answer(
        "✅ Новый стиль успешно создан!\n\n"
        f"<b>{style.title}</b>\n\n"
        f"{style.description}\n\n"
        f"Файл картинки: <code>{style.image_filename}</code>",
    )

    await message.answer(
        "👑 Админ-панель.\n\nВыбери раздел:",
        reply_markup=get_admin_main_keyboard(),
    )

@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message):
    """
    Команда для назначения админа.
    Использование: /add_admin 123456789
    Доступна только действующим админам.
    """
    if not await is_admin(message.from_user.id):
        # Молча игнорируем, чтобы не палить наличие команды
        return

    if message.text is None:
        await message.answer("Нужно указать ID: /add_admin 123456789")
        return

    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /add_admin 123456789")
        return

    target_id = int(parts[1])

    user = await add_admin(
        user_id=target_id,
        username=None,
    )

    await message.answer(
        "✅ Пользователь назначен админом.\n\n"
        f"ID: <code>{user.telegram_id}</code>\n"
        f"Username: @{user.username if user.username else '—'}"
    )

@router.message(Command("remove_admin"))
async def cmd_remove_admin(message: Message):
    """
    Команда для снятия админа.
    Использование: /remove_admin 123456789
    Супер-админа 707366569 снять нельзя.
    """
    if not await is_admin(message.from_user.id):
        return

    if message.text is None:
        await message.answer("Нужно указать ID: /remove_admin 123456789")
        return

    parts = message.text.strip().split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /remove_admin 123456789")
        return

    target_id = int(parts[1])

    if target_id == SUPER_ADMIN_ID:
        await message.answer(
            "❌ Нельзя снять супер-админа."
        )
        return

    res = await remove_admin(target_id)
    if res is None:
        await message.answer(
            f"ID <code>{target_id}</code> не найден в базе пользователей, "
            "или это супер-админ."
        )
        return

    await message.answer(
        f"✅ Пользователь с ID <code>{target_id}</code> больше не админ."
    )
@router.message(Command("admins"))
async def cmd_admins_list(message: Message):
    """
    Показывает список админов (ID).
    Доступно только админам.
    """
    if not await is_admin(message.from_user.id):
        return

    ids = await get_admin_ids()
    ids_str = ", ".join(str(x) for x in ids)

    await message.answer(
        "👑 Текущие админы (ID):\n"
        f"{ids_str}"
    )
