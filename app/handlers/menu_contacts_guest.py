from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts, media
from app.navigation import Nav, Screen
from app.db.repo import Repo

router = Router()


def register_screens(nav: Nav, repo: Repo):
    async def screen_guest_contacts(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="📞 Телефон галереи", callback_data="contacts:phone")
        kb.button(text="✉️ Email галереи", callback_data="contacts:email")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)
        return Screen(text=texts.GUEST_CONTACTS_TEXT, photo_file_id=media.PHOTO_CONTACTS_CARD, inline=kb.as_markup())

    async def screen_phone(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(2)
        return Screen(text=texts.GUEST_PHONE_TEXT, inline=kb.as_markup())

    async def screen_email(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(2)
        return Screen(text=texts.GUEST_EMAIL_TEXT, inline=kb.as_markup())

    nav.register("guest_contacts", screen_guest_contacts)
    nav.register("contacts_phone", screen_phone)
    nav.register("contacts_email", screen_email)


@router.callback_query(F.data == "menu:guest_contacts")
async def open_guest_contacts(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "guest_contacts", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "contacts:phone")
async def open_phone(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "contacts_phone", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "contacts:email")
async def open_email(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "contacts_email", remove_reply_keyboard=True)
    await cb.answer()
