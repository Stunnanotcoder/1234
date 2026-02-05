import re

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app import texts, media
from app.navigation import Nav, Screen
from app.db.repo import Repo

router = Router()

PHONE_RE = re.compile(r"^[\d\+\-\(\)\s]{7,25}$")


class DesignerApply(StatesGroup):
    wait_contact = State()
    wait_manual = State()


def _is_registered(u) -> bool:
    return bool(u and u.consent == 1 and u.name and u.email and u.role)


def _t(name: str, fallback: str) -> str:
    return getattr(texts, name, fallback)


def _p(name: str, fallback: str = "PLACEHOLDER") -> str:
    return getattr(media, name, fallback)


def _admin_msg(cb: CallbackQuery, u, phone: str) -> str:
    name = getattr(u, "name", None) or "—"
    email = getattr(u, "email", None) or "—"
    role = getattr(u, "role", None) or "—"
    username = f"@{cb.from_user.username}" if cb.from_user.username else "—"

    return (
        "🎨 <b>Заявка на сотрудничество (дизайнер)</b>\n\n"
        f"<b>Имя:</b> {name}\n"
        f"<b>Email:</b> {email}\n"
        f"<b>Роль:</b> {role}\n"
        f"<b>Телефон:</b> {phone}\n"
        f"<b>Username:</b> {username}\n"
        f"<b>Профиль:</b> tg://user?id={cb.from_user.id}"
    )


async def _send_to_admins(bot, admin_ids: set[int], text: str) -> None:
    for aid in admin_ids:
        try:
            await bot.send_message(aid, text, disable_web_page_preview=True)
        except Exception:
            pass


def register_screens(nav: Nav, repo: Repo):
    async def screen_designer(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="🤝 Сотрудничать", callback_data="designer:apply")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)

        text = _t(
            "DESIGNER_TEXT",
            (
                "<b>Дизайнеры и архитекторы</b>\n\n"
                "Если вы работаете с частными или коммерческими интерьерами, мы открыты к партнёрству.\n"
                "FORM & BRONZE предоставляет материалы, условия и поддержку для интеграции скульптур в проекты.\n\n"
                "Ознакомьтесь с <a href=\"https://example.com\">документами</a>.\n\n"
                "Нажмите «Сотрудничать» — и мы свяжемся с вами."
            ),
        )

        return Screen(
            text=text,
            photo_file_id=_p("PHOTO_DESIGNER", _p("PHOTO_MENU", "PLACEHOLDER")),
            inline=kb.as_markup(),
            disable_web_page_preview=True,
        )

    async def screen_need_phone(chat_id: int, ctx: dict) -> Screen:
        # reply-клавиатура с request_contact
        reply_kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]],
            resize_keyboard=True,
            one_time_keyboard=True,
        )

        inline = InlineKeyboardBuilder()
        inline.button(text="✍️ Ввести номер вручную", callback_data="designer:phone_manual")
        inline.button(text="⬅️ Назад", callback_data="nav:back")
        inline.button(text="🏠 Главное меню", callback_data="menu:main")
        inline.adjust(1)

        return Screen(
            text="Чтобы мы могли связаться с вами, пожалуйста, оставьте номер телефона.",
            photo_file_id=_p("PHOTO_DESIGNER", _p("PHOTO_MENU", "PLACEHOLDER")),
            inline=inline.as_markup(),
            reply=reply_kb,
            reply_prompt="Нажмите кнопку ниже, чтобы отправить номер:",
            disable_web_page_preview=True,
        )

    async def screen_phone_manual(chat_id: int, ctx: dict) -> Screen:
        inline = InlineKeyboardBuilder()
        inline.button(text="⬅️ Назад", callback_data="nav:back")
        inline.button(text="🏠 Главное меню", callback_data="menu:main")
        inline.adjust(1)

        return Screen(
            text="Введите номер телефона текстом (например: +7 999 123-45-67).",
            photo_file_id=_p("PHOTO_DESIGNER", _p("PHOTO_MENU", "PLACEHOLDER")),
            inline=inline.as_markup(),
            disable_web_page_preview=True,
        )

    nav.register("designer", screen_designer)
    nav.register("designer:need_phone", screen_need_phone)
    nav.register("designer:phone_manual", screen_phone_manual)


@router.callback_query(F.data == "menu:designer")
async def open_designer(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "designer", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "designer:apply")
async def designer_apply(cb: CallbackQuery, repo: Repo, nav: Nav, state: FSMContext):
    # гарантируем строку юзера
    if hasattr(repo, "ensure_user_row"):
        await repo.ensure_user_row(cb.from_user.id)

    u = await repo.get_user(cb.from_user.id)

    # гость -> регистрация
    if not _is_registered(u):
        await nav.show_screen(cb.bot, cb.from_user.id, "settings:guest", remove_reply_keyboard=True)
        await cb.answer("Для заявки нужна регистрация", show_alert=True)
        return

    phone = getattr(u, "phone", None)

    # нет телефона -> просим телефон обязательно
    if not phone:
        await state.set_state(DesignerApply.wait_contact)
        await nav.show_screen(cb.bot, cb.from_user.id, "designer:need_phone", remove_reply_keyboard=False)
        await cb.answer()
        return

    # телефон уже есть -> фиксируем и шлём
    try:
        if hasattr(repo, "set_designer_interest"):
            await repo.set_designer_interest(cb.from_user.id, True)
    except Exception:
        pass

    # админам + пользователю
    # admin_ids тут не переданы, поэтому уведомление делаем отдельным хэндлером после получения телефона.
    thanks = _t("DESIGNER_THANKS_TEXT", "Спасибо! Заявка принята. Мы свяжемся с вами в ближайшее время.")
    await cb.bot.send_message(cb.from_user.id, thanks, disable_web_page_preview=True)
    await cb.answer("Заявка отправлена ✅")


@router.callback_query(F.data == "designer:phone_manual")
async def designer_phone_manual(cb: CallbackQuery, nav: Nav, state: FSMContext):
    await state.set_state(DesignerApply.wait_manual)
    await nav.show_screen(cb.bot, cb.from_user.id, "designer:phone_manual", remove_reply_keyboard=True)
    await cb.answer()


@router.message(DesignerApply.wait_contact, F.contact)
async def designer_got_contact(
    message: Message,
    repo: Repo,
    nav: Nav,
    state: FSMContext,
    admin_ids: set[int],
):
    phone = message.contact.phone_number if message.contact else None
    if not phone:
        await message.answer("Не удалось прочитать номер. Попробуйте ещё раз или введите вручную.")
        return

    await repo.update_profile(message.from_user.id, phone=phone)

    try:
        if hasattr(repo, "set_designer_interest"):
            await repo.set_designer_interest(message.from_user.id, True)
    except Exception:
        pass

    u = await repo.get_user(message.from_user.id)
    # уведомляем админов
    tmp_cb = type("Tmp", (), {"from_user": message.from_user})()
    # аккуратно соберём текст без костылей с CallbackQuery:
    admin_text = (
        "🎨 <b>Заявка на сотрудничество (дизайнер)</b>\n\n"
        f"<b>Имя:</b> {getattr(u, 'name', None) or '—'}\n"
        f"<b>Email:</b> {getattr(u, 'email', None) or '—'}\n"
        f"<b>Роль:</b> {getattr(u, 'role', None) or '—'}\n"
        f"<b>Телефон:</b> {phone}\n"
        f"<b>Username:</b> {(f'@{message.from_user.username}' if message.from_user.username else '—')}\n"
        f"<b>Профиль:</b> tg://user?id={message.from_user.id}"
    )
    await _send_to_admins(message.bot, admin_ids, admin_text)

    await state.clear()
    thanks = _t("DESIGNER_THANKS_TEXT", "Спасибо! Заявка принята. Мы свяжемся с вами в ближайшее время.")
    await nav.show_screen(message.bot, message.from_user.id, "designer", remove_reply_keyboard=True)
    await message.answer(thanks, disable_web_page_preview=True)


@router.message(DesignerApply.wait_manual)
async def designer_got_manual_phone(
    message: Message,
    repo: Repo,
    nav: Nav,
    state: FSMContext,
    admin_ids: set[int],
):
    if not message.text:
        await message.answer("Введите номер текстом (например: +7 999 123-45-67).")
        return

    raw = message.text.strip()
    if not PHONE_RE.match(raw):
        await message.answer("Похоже, номер введён некорректно. Пример: +7 999 123-45-67")
        return

    await repo.update_profile(message.from_user.id, phone=raw)

    try:
        if hasattr(repo, "set_designer_interest"):
            await repo.set_designer_interest(message.from_user.id, True)
    except Exception:
        pass

    u = await repo.get_user(message.from_user.id)
    admin_text = (
        "🎨 <b>Заявка на сотрудничество (дизайнер)</b>\n\n"
        f"<b>Имя:</b> {getattr(u, 'name', None) or '—'}\n"
        f"<b>Email:</b> {getattr(u, 'email', None) or '—'}\n"
        f"<b>Роль:</b> {getattr(u, 'role', None) or '—'}\n"
        f"<b>Телефон:</b> {raw}\n"
        f"<b>Username:</b> {(f'@{message.from_user.username}' if message.from_user.username else '—')}\n"
        f"<b>Профиль:</b> tg://user?id={message.from_user.id}"
    )
    await _send_to_admins(message.bot, admin_ids, admin_text)

    await state.clear()
    thanks = _t("DESIGNER_THANKS_TEXT", "Спасибо! Заявка принята. Мы свяжемся с вами в ближайшее время.")
    await nav.show_screen(message.bot, message.from_user.id, "designer", remove_reply_keyboard=True)
    await message.answer(thanks, disable_web_page_preview=True)
