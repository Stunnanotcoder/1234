import re

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts, media
from app.db.repo import Repo
from app.navigation import Nav, Screen

router = Router()

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class Reg(StatesGroup):
    name = State()
    email = State()
    role = State()


def register_screens(nav: Nav, repo: Repo):
    async def screen_welcome(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="✨ Познакомиться", callback_data="start:meet")
        kb.adjust(1)
        return Screen(
            text=texts.WELCOME_TEXT,
            photo_file_id=media.PHOTO_WELCOME,
            inline=kb.as_markup(),
        )

    async def screen_consent(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="📄 Подробнее", callback_data="consent:more")
        kb.button(text="✅ Даю согласие", callback_data="consent:yes")
        kb.button(text="❌ Отказ", callback_data="consent:no")
        kb.adjust(1)
        return Screen(
            text=texts.CONSENT_TEXT,
            photo_file_id=media.PHOTO_CONSENT,
            inline=kb.as_markup(),
        )

    async def screen_consent_more(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="✅ Даю согласие", callback_data="consent:yes")
        kb.button(text="❌ Отказ", callback_data="consent:no")
        kb.adjust(1)
        return Screen(
            text=texts.CONSENT_MORE_TEXT,
            photo_file_id=media.PHOTO_CONSENT,
            inline=kb.as_markup(),
        )

    async def screen_consent_denied(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="🔄 Начать заново", callback_data="start:restart")
        kb.button(text="👀 Открыть меню без регистрации", callback_data="menu:guest")
        kb.adjust(1)
        return Screen(text=texts.CONSENT_DENIED_TEXT, inline=kb.as_markup())

    async def screen_name_ask(chat_id: int, ctx: dict) -> Screen:
        return Screen(text=texts.NAME_ASK_TEXT, photo_file_id=media.PHOTO_NAME)

    async def screen_email_ask(chat_id: int, ctx: dict) -> Screen:
        return Screen(text=texts.EMAIL_ASK_TEXT, photo_file_id=media.PHOTO_EMAIL)

    async def screen_role_ask(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="💼 Коллекционер", callback_data="role:collector")
        kb.button(text="🤝 Арт-диллер / Представитель", callback_data="role:dealer")
        kb.button(text="🗿 Автор", callback_data="role:author")
        kb.button(text="👀 Просто интересуюсь", callback_data="role:interest")
        kb.adjust(1)
        return Screen(
            text=texts.ROLE_ASK_TEXT,
            photo_file_id=media.PHOTO_ROLE,
            inline=kb.as_markup(),
        )

    nav.register("welcome", screen_welcome)
    nav.register("consent", screen_consent)
    nav.register("consent_more", screen_consent_more)
    nav.register("consent_denied", screen_consent_denied)
    nav.register("name_ask", screen_name_ask)
    nav.register("email_ask", screen_email_ask)
    nav.register("role_ask", screen_role_ask)


def _is_registered(u) -> bool:
    return bool(u and u.consent == 1 and u.name and u.email and u.role)


async def _open_start_screen(message: Message, repo: Repo, nav: Nav, state: FSMContext) -> None:
    """Единая логика /start (на случай если Telegram пришлёт необычный формат)."""
    await state.clear()
    telegram_id = message.from_user.id

    await repo.ensure_user_row(telegram_id)
    u = await repo.get_user(telegram_id)

    nav.clear(telegram_id)
    if _is_registered(u):
        await nav.show_screen(message.bot, telegram_id, "menu:registered", remove_reply_keyboard=True)
    else:
        await nav.show_screen(message.bot, telegram_id, "welcome", remove_reply_keyboard=True)


@router.message(CommandStart())
async def cmd_start(message: Message, repo: Repo, nav: Nav, state: FSMContext):
    await _open_start_screen(message, repo, nav, state)


# На всякий случай ловим /start как текст (если где-то фильтры команд “съедаются”)
@router.message(F.text.startswith("/start"))
async def cmd_start_text(message: Message, repo: Repo, nav: Nav, state: FSMContext):
    await _open_start_screen(message, repo, nav, state)


@router.callback_query(F.data == "start:meet")
async def start_meet(cb: CallbackQuery, repo: Repo, nav: Nav, state: FSMContext):
    await state.clear()
    await repo.ensure_user_row(cb.from_user.id)
    await nav.show_screen(cb.bot, cb.from_user.id, "consent", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "start:restart")
async def start_restart(cb: CallbackQuery, repo: Repo, nav: Nav, state: FSMContext):
    await state.clear()
    await repo.set_consent(cb.from_user.id, consent=False, enable_notify=False)
    nav.clear(cb.from_user.id)
    await nav.show_screen(cb.bot, cb.from_user.id, "welcome", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "consent:more")
async def consent_more(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "consent_more", replace_top=True)
    await cb.answer()


@router.callback_query(F.data == "consent:yes")
async def consent_yes(cb: CallbackQuery, repo: Repo, nav: Nav, state: FSMContext):
    await repo.set_consent(cb.from_user.id, consent=True, enable_notify=True)
    await state.set_state(Reg.name)
    await nav.show_screen(cb.bot, cb.from_user.id, "name_ask")
    await cb.answer()


@router.callback_query(F.data == "consent:no")
async def consent_no(cb: CallbackQuery, nav: Nav, state: FSMContext):
    await state.clear()
    await nav.show_screen(cb.bot, cb.from_user.id, "consent_denied", replace_top=True)
    await cb.answer()


@router.message(Reg.name)
async def reg_name(message: Message, repo: Repo, nav: Nav, state: FSMContext):
    if not message.text:
        await message.answer("Пожалуйста, отправьте имя текстом (до 50 символов).")
        return

    name = message.text.strip()
    if not name or len(name) > 50:
        await message.answer("Имя должно быть непустым и до 50 символов. Попробуйте ещё раз.")
        return

    await repo.update_profile(message.from_user.id, name=name)
    await state.set_state(Reg.email)
    await nav.show_screen(message.bot, message.from_user.id, "email_ask")


@router.message(Reg.email)
async def reg_email(message: Message, repo: Repo, nav: Nav, state: FSMContext):
    if not message.text:
        await message.answer(texts.EMAIL_INVALID_TEXT)
        return

    email = message.text.strip()
    if not EMAIL_RE.match(email):
        await message.answer(texts.EMAIL_INVALID_TEXT)
        return

    await repo.update_profile(message.from_user.id, email=email)
    await state.set_state(Reg.role)
    await nav.show_screen(message.bot, message.from_user.id, "role_ask")


@router.callback_query(F.data.startswith("role:"))
async def reg_role(cb: CallbackQuery, repo: Repo, nav: Nav, state: FSMContext):
    role = cb.data.split(":", 1)[1]
    await repo.update_profile(cb.from_user.id, role=role)
    await state.clear()
    await nav.show_screen(cb.bot, cb.from_user.id, "menu:registered", remove_reply_keyboard=True)
    await cb.answer()
