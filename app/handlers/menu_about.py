from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts, media
from app.navigation import Nav, Screen
from app.db.repo import Repo

router = Router()


def register_screens(nav: Nav, repo: Repo):
    async def screen_about(chat_id: int, ctx: dict) -> Screen:
        # ВАЖНО: ABOUT без “Назад”
        kb = InlineKeyboardBuilder()
        kb.button(text="👥 Авторы", callback_data="about:authors")
        kb.button(text="📜 История галереи", callback_data="about:history")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)
        return Screen(
            text=texts.ABOUT_TEXT,
            photo_file_id=media.PHOTO_ABOUT,
            inline=kb.as_markup(),
        )

    async def screen_authors(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(2)
        return Screen(
            text=texts.AUTHORS_TEXT,
            video_file_id=getattr(media, "VIDEO_ABOUT_AUTHORS", "PLACEHOLDER"),
            inline=kb.as_markup(),
        )

    async def screen_history(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(2)
        return Screen(
            text=texts.HISTORY_TEXT,
            photo_file_id=media.PHOTO_ABOUT_HISTORY,
            inline=kb.as_markup(),
            disable_web_page_preview=True,
        )

    nav.register("about", screen_about)
    nav.register("about:authors", screen_authors)
    nav.register("about:history", screen_history)


@router.callback_query(F.data == "menu:about")
async def open_about(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "about", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "about:authors")
async def open_authors(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "about:authors", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "about:history")
async def open_history(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "about:history", remove_reply_keyboard=True)
    await cb.answer()
