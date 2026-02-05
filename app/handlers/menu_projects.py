from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts, media
from app.navigation import Nav, Screen
from app.db.repo import Repo

router = Router()


def register_screens(nav: Nav, repo: Repo):
    async def screen_projects(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="Golf. Game as Art", callback_data="projects:1")
        kb.button(text="Балет", callback_data="projects:2")
        kb.button(text="Две грани творчества", callback_data="projects:3")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)
        return Screen(text=texts.PROJECTS_TEXT, photo_file_id=media.PHOTO_PROJECTS, inline=kb.as_markup())

    async def project_n(chat_id: int, ctx: dict) -> Screen:
        n = int(ctx["screen_id"].split(":")[1])
        kb = InlineKeyboardBuilder()
        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(2)

        photo = {1: media.PHOTO_PROJECT_1, 2: media.PHOTO_PROJECT_2, 3: media.PHOTO_PROJECT_3}.get(n)
        text = {1: texts.TEXT_PROJECT_1, 2: texts.TEXT_PROJECT_2, 3: texts.TEXT_PROJECT_3}.get(n, "Проект (placeholder)")
        return Screen(text=text, photo_file_id=photo, inline=kb.as_markup())

    nav.register("projects", screen_projects)
    nav.register("project", project_n)


@router.callback_query(F.data == "menu:projects")
async def open_projects(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "projects", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data.startswith("projects:"))
async def open_project(cb: CallbackQuery, nav: Nav):
    n = cb.data.split(":")[1]
    await nav.show_screen(cb.bot, cb.from_user.id, f"project:{n}", remove_reply_keyboard=True)
    await cb.answer()
