import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import load_config
from app.db.repo import Repo
from app.navigation import Nav, Screen
from app import texts, media

from app.handlers import (
    start_onboarding,
    menu_about,
    menu_projects,
    menu_contacts_guest,
    menu_invite_main,
    menu_settings,
    sculptures_catalog,
    menu_designer,      # ✅ дизайнер
    admin_broadcast,
    admin_content,
    admin_fileid,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("form_bronze_bot")


def build_main_menu_kb(registered: bool):
    kb = InlineKeyboardBuilder()

    kb.button(text="🏺 Наши скульптуры", callback_data="menu:sculptures")
    kb.button(text="🏛 О галерее", callback_data="menu:about")
    kb.button(text="⭐ Спецпроекты", callback_data="menu:projects")
    kb.button(text="🎨 Дизайнер", callback_data="menu:designer")

    if registered:
        kb.button(text="👤 Пригласите главного", callback_data="menu:invite_main")
        kb.button(text="⚙️ Настройки", callback_data="menu:settings")
    else:
        kb.button(text="📇 Контакты", callback_data="menu:guest_contacts")
        kb.button(text="⚙️ Настройки", callback_data="menu:guest_settings")

    kb.adjust(1)
    return kb.as_markup()


def register_core_screens(nav: Nav):
    async def menu_registered(chat_id: int, ctx: dict) -> Screen:
        return Screen(
            text=texts.MENU_REGISTERED_TEXT,
            photo_file_id=getattr(media, "PHOTO_MENU", None),
            inline=build_main_menu_kb(registered=True),
        )

    async def menu_guest(chat_id: int, ctx: dict) -> Screen:
        return Screen(
            text=texts.MENU_GUEST_TEXT,
            photo_file_id=getattr(media, "PHOTO_MENU", None),
            inline=build_main_menu_kb(registered=False),
        )

    nav.register("menu:registered", menu_registered)
    nav.register("menu:guest", menu_guest)


async def is_registered(repo: Repo, telegram_id: int) -> bool:
    u = await repo.get_user(telegram_id)
    return bool(u and u.consent == 1 and u.name and u.email and u.role)


async def main():
    cfg = load_config()

    bot = Bot(token=cfg.bot_token)
    dp = Dispatcher(storage=MemoryStorage())

    repo = Repo(cfg.db_path)
    await repo.connect()
    await repo.init_schema("app/db/schema.sql")

    nav = Nav()

    # screens
    start_onboarding.register_screens(nav, repo)
    register_core_screens(nav)
    menu_about.register_screens(nav, repo)
    menu_projects.register_screens(nav, repo)
    menu_contacts_guest.register_screens(nav, repo)
    menu_invite_main.register_screens(nav, repo)
    menu_settings.register_screens(nav, repo)
    sculptures_catalog.register_screens(nav, repo)
    menu_designer.register_screens(nav, repo)

    # routers
    dp.include_router(start_onboarding.router)
    dp.include_router(menu_about.router)
    dp.include_router(menu_projects.router)
    dp.include_router(menu_contacts_guest.router)
    dp.include_router(menu_invite_main.router)
    dp.include_router(menu_settings.router)
    dp.include_router(sculptures_catalog.router)
    dp.include_router(menu_designer.router)
    dp.include_router(admin_broadcast.router)
    dp.include_router(admin_content.router)
    dp.include_router(admin_fileid.router)

    # ----- admin panel (/admin) + stats -----
    @dp.message(F.text == "/admin")
    async def admin_panel(message: Message, admin_ids: set[int]):
        if message.from_user.id not in admin_ids:
            return
        kb = InlineKeyboardBuilder()
        kb.button(text="➕ Добавить коллекцию", callback_data="admin:add_collection")
        kb.button(text="➕ Добавить скульптуру", callback_data="admin:add_sculpture")
        kb.button(text="📣 Рассылка", callback_data="admin:broadcast")
        kb.button(text="📊 Статистика", callback_data="admin:stats")
        kb.adjust(1)
        await message.answer(texts.ADMIN_PANEL_TEXT, reply_markup=kb.as_markup())

    @dp.callback_query(F.data == "admin:stats")
    async def admin_stats(cb: CallbackQuery, admin_ids: set[int], repo: Repo):
        if cb.from_user.id not in admin_ids:
            await cb.answer()
            return
        st = await repo.stats()
        await cb.bot.send_message(
            cb.from_user.id,
            f"Статистика:\nUsers: {st['users']}\nNotify enabled: {st['notify']}\nVisit requests NEW: {st['visit_new']}",
        )
        await cb.answer()

    # ------ Global callbacks: main/back ------
    @dp.callback_query(F.data == "menu:main")
    async def go_main(cb: CallbackQuery, repo: Repo, nav: Nav):
        nav.clear(cb.from_user.id)
        screen = "menu:registered" if await is_registered(repo, cb.from_user.id) else "menu:guest"
        await nav.show_screen(cb.bot, cb.from_user.id, screen, remove_reply_keyboard=True)
        await cb.answer()

    @dp.callback_query(F.data == "menu:guest")
    async def go_guest(cb: CallbackQuery, nav: Nav):
        nav.clear(cb.from_user.id)
        await nav.show_screen(cb.bot, cb.from_user.id, "menu:guest", remove_reply_keyboard=True)
        await cb.answer()

    @dp.callback_query(F.data == "nav:back")
    async def nav_back(cb: CallbackQuery, repo: Repo, nav: Nav):
        fallback = "menu:registered" if await is_registered(repo, cb.from_user.id) else "menu:guest"
        await nav.back(cb.bot, cb.from_user.id, fallback_screen=fallback)
        await cb.answer()

    # ------ fallback: random text ТОЛЬКО вне FSM и НЕ команды ------
    @dp.message(StateFilter(None), ~F.text.startswith("/"))
    async def fallback_text(message: Message):
        kb = InlineKeyboardBuilder()
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        await message.answer(texts.OPEN_MENU_FALLBACK_TEXT, reply_markup=kb.as_markup())

    try:
        await dp.start_polling(bot, repo=repo, nav=nav, admin_ids=cfg.admin_ids)
    finally:
        await repo.close()


if __name__ == "__main__":
    asyncio.run(main())
