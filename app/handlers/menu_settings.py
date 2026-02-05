from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app import texts, media
from app.navigation import Nav, Screen
from app.db.repo import Repo

router = Router()


class Settings(StatesGroup):
    name = State()
    email = State()
    delete_confirm_1 = State()
    delete_confirm_2 = State()


def register_screens(nav: Nav, repo: Repo):
    async def guest_settings(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Пройти регистрацию", callback_data="guest:register")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)
        return Screen(text=texts.SETTINGS_GUEST_TEXT, photo_file_id=media.PHOTO_SETTINGS, inline=kb.as_markup())

    async def registered_settings(chat_id: int, ctx: dict) -> Screen:
        u = await repo.get_user(chat_id)
        assert u
        profile = (
            f"{texts.SETTINGS_PROFILE_HEADER}\n\n"
            f"Имя: {u.name or '—'}\n"
            f"Email: {u.email or '—'}\n"
            f"Роль: {u.role or '—'}\n"
            f"Телефон: {u.phone or '—'}\n"
            f"Город: {u.city or '—'}\n"
            f"Рассылка: {'Вкл' if u.notify_enabled else 'Выкл'}"
        )

        kb = InlineKeyboardBuilder()
        kb.button(text="✏️ Изменить имя", callback_data="settings:name")
        kb.button(text="✉️ Изменить почту", callback_data="settings:email")
        kb.button(text="🔔 Рассылка: Вкл/Выкл", callback_data="settings:toggle_notify")
        kb.button(text="🗑 Удалить аккаунт", callback_data="settings:delete")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)
        return Screen(text=profile, photo_file_id=media.PHOTO_SETTINGS, inline=kb.as_markup())

    nav.register("settings:guest", guest_settings)
    nav.register("settings:registered", registered_settings)


async def _is_registered(repo: Repo, telegram_id: int) -> bool:
    u = await repo.get_user(telegram_id)
    return bool(u and u.consent == 1 and u.name and u.email and u.role)


@router.callback_query(F.data == "menu:settings")
async def open_settings(cb: CallbackQuery, repo: Repo, nav: Nav, state: FSMContext):
    await state.clear()
    if await _is_registered(repo, cb.from_user.id):
        await nav.show_screen(cb.bot, cb.from_user.id, "settings:registered", remove_reply_keyboard=True)
    else:
        await nav.show_screen(cb.bot, cb.from_user.id, "settings:guest", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "menu:guest_settings")
async def open_guest_settings(cb: CallbackQuery, nav: Nav, state: FSMContext):
    await state.clear()
    await nav.show_screen(cb.bot, cb.from_user.id, "settings:guest", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "guest:register")
async def guest_register(cb: CallbackQuery, nav: Nav, state: FSMContext):
    await state.clear()
    await nav.show_screen(cb.bot, cb.from_user.id, "consent", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "settings:toggle_notify")
async def toggle_notify(cb: CallbackQuery, repo: Repo, nav: Nav):
    await repo.toggle_notify(cb.from_user.id)
    await nav.show_screen(cb.bot, cb.from_user.id, "settings:registered", push=False, remove_reply_keyboard=True)
    await cb.answer("Готово")


@router.callback_query(F.data == "settings:name")
async def change_name(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Settings.name)
    await cb.bot.send_message(cb.from_user.id, "Введите новое имя (до 50 символов):")
    await cb.answer()


@router.message(Settings.name)
async def change_name_input(message: Message, repo: Repo, nav: Nav, state: FSMContext):
    name = (message.text or "").strip()
    if not name or len(name) > 50:
        await message.answer("Имя должно быть непустым и до 50 символов.")
        return
    await repo.update_profile(message.from_user.id, name=name)
    await state.clear()
    await nav.show_screen(message.bot, message.from_user.id, "settings:registered", remove_reply_keyboard=True)


@router.callback_query(F.data == "settings:email")
async def change_email(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Settings.email)
    await cb.bot.send_message(cb.from_user.id, "Введите новый email:")
    await cb.answer()


@router.message(Settings.email)
async def change_email_input(message: Message, repo: Repo, nav: Nav, state: FSMContext):
    email = (message.text or "").strip()
    if "@" not in email or len(email) > 120:
        await message.answer("Email выглядит неверно. Попробуйте ещё раз.")
        return
    await repo.update_profile(message.from_user.id, email=email)
    await state.clear()
    await nav.show_screen(message.bot, message.from_user.id, "settings:registered", remove_reply_keyboard=True)


@router.callback_query(F.data == "settings:delete")
async def delete_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Settings.delete_confirm_1)
    kb = InlineKeyboardBuilder()
    kb.button(text="Да, удалить", callback_data="settings:delete:yes1")
    kb.button(text="Нет", callback_data="menu:main")
    kb.adjust(2)
    await cb.bot.send_message(cb.from_user.id, texts.SETTINGS_DELETE_CONFIRM_1, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "settings:delete:yes1")
async def delete_yes1(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Settings.delete_confirm_2)
    kb = InlineKeyboardBuilder()
    kb.button(text="Удалить навсегда", callback_data="settings:delete:yes2")
    kb.button(text="Отмена", callback_data="menu:main")
    kb.adjust(2)
    await cb.bot.send_message(cb.from_user.id, texts.SETTINGS_DELETE_CONFIRM_2, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data == "settings:delete:yes2")
async def delete_yes2(cb: CallbackQuery, repo: Repo, nav: Nav, state: FSMContext):
    await repo.delete_user(cb.from_user.id)
    await state.clear()
    nav.clear(cb.from_user.id)
    await cb.bot.send_message(cb.from_user.id, "Аккаунт удалён.")
    await nav.show_screen(cb.bot, cb.from_user.id, "welcome", remove_reply_keyboard=True)
    await cb.answer()
