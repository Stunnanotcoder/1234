from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app import texts, media
from app.navigation import Nav, Screen
from app.db.repo import Repo

router = Router()

PAGE_SIZE = 8


def register_screens(nav: Nav, repo: Repo):
    async def sculptures_home(chat_id: int, ctx: dict) -> Screen:
        kb = InlineKeyboardBuilder()
        kb.button(text="📚 Коллекции", callback_data="sculptures:collections:0")
        kb.button(text="✨ Новые работы", callback_data="sculptures:new:0")
        kb.button(text="🔥 Избранные", callback_data="sculptures:featured:0")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)
        return Screen(
            text=texts.SCULPTURES_HOME_TEXT,
            photo_file_id=media.PHOTO_SCULPTURES,
            inline=kb.as_markup(),
        )

    async def collections_page(chat_id: int, ctx: dict) -> Screen:
        offset = int(ctx["screen_id"].split(":")[1])
        items, total = await repo.list_collections(active_only=True, limit=PAGE_SIZE, offset=offset)

        kb = InlineKeyboardBuilder()
        if not items:
            kb.button(text="⬅️ Назад", callback_data="nav:back")
            kb.button(text="🏠 Главное меню", callback_data="menu:main")
            kb.adjust(2)
            return Screen(text=texts.COLLECTIONS_EMPTY_TEXT, inline=kb.as_markup())

        for c in items:
            kb.button(text=c["title"], callback_data=f"collection:{c['id']}:0")

        if offset > 0:
            kb.button(text="◀️", callback_data=f"sculptures:collections:{max(0, offset - PAGE_SIZE)}")
        if offset + PAGE_SIZE < total:
            kb.button(text="▶️", callback_data=f"sculptures:collections:{offset + PAGE_SIZE}")

        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)
        return Screen(text="Выберите коллекцию:", inline=kb.as_markup())

    # ✅ FIX: в пустой коллекции НЕ показываем "пока нет опубликованных..."
    async def collection_sculptures(chat_id: int, ctx: dict) -> Screen:
        _, collection_id, offset = ctx["screen_id"].split(":")
        collection_id = int(collection_id)
        offset = int(offset)

        col = await repo.get_collection(collection_id)
        items, total = await repo.list_sculptures_by_collection(collection_id, limit=PAGE_SIZE, offset=offset)

        kb = InlineKeyboardBuilder()

        title = col["title"] if col else "Коллекция"

        desc = ""
        if col and col.get("short_desc"):
            desc = (col["short_desc"] or "").strip()
            if desc == "-":
                desc = ""

        cover = col.get("cover_photo_file_id") if col else None

        header_parts = [title]
        if desc:
            header_parts.append(desc)
        header = "\n\n".join(header_parts)

        # --- ПУСТО: только header + обложка + кнопки ---
        if not items:
            kb.button(text="⬅️ Назад", callback_data="nav:back")
            kb.button(text="🏠 Главное меню", callback_data="menu:main")
            kb.adjust(2)
            return Screen(
                text=header,
                photo_file_id=cover,
                inline=kb.as_markup(),
            )

        # --- ЕСТЬ СКУЛЬПТУРЫ: список ---
        for s in items:
            kb.button(text=s["title"], callback_data=f"sculpture:{s['id']}:0")

        if offset > 0:
            kb.button(text="◀️", callback_data=f"collection:{collection_id}:{max(0, offset - PAGE_SIZE)}")
        if offset + PAGE_SIZE < total:
            kb.button(text="▶️", callback_data=f"collection:{collection_id}:{offset + PAGE_SIZE}")

        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)

        return Screen(
            text=f"{header}\n\nВыберите скульптуру:",
            photo_file_id=cover,
            inline=kb.as_markup(),
        )

    async def sculpture_card(chat_id: int, ctx: dict) -> Screen:
        _, sid, pidx = ctx["screen_id"].split(":")
        sid = int(sid)
        pidx = int(pidx)

        s = await repo.get_sculpture(sid)
        photos = await repo.list_sculpture_photos(sid)
        file_id = photos[pidx]["file_id"] if photos and 0 <= pidx < len(photos) else None

        status_map = {
            "in_expo": "В экспозиции",
            "available": "Доступно",
            "sold": "Продано",
            "on_request": "По запросу",
        }

        info = []
        info.append(s["title"])
        meta = []
        if s.get("artist"):
            meta.append(f"Автор: {s['artist']}")
        if s.get("material"):
            meta.append(f"Материал: {s['material']}")
        if s.get("year"):
            meta.append(f"Год: {s['year']}")
        if s.get("dimensions"):
            meta.append(f"Размер: {s['dimensions']}")
        meta.append(f"Статус: {status_map.get(s.get('status'), s.get('status'))}")
        info.append("\n".join(meta))
        if s.get("description_short"):
            info.append(s["description_short"])

        text = "\n\n".join(info)

        kb = InlineKeyboardBuilder()
        if photos and len(photos) > 1:
            next_idx = (pidx + 1) % len(photos)
            kb.button(text="🖼 Следующее фото", callback_data=f"sculpture_photo_next:{sid}:{next_idx}")

        u = await repo.get_user(chat_id)
        is_registered = bool(u and u.consent == 1 and u.name and u.email and u.role)

        if is_registered:
            kb.button(text="👤 Свяжитесь со мной", callback_data="invite:me")
            kb.button(text="🏙 Визит в городе", callback_data="invite:city")
        else:
            kb.button(text="👤 Свяжитесь со мной", callback_data="guest:need_register")
            kb.button(text="🏙 Визит в городе", callback_data="guest:need_register")

        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)

        return Screen(text=text, photo_file_id=file_id, inline=kb.as_markup())

    async def new_feed(chat_id: int, ctx: dict) -> Screen:
        offset = int(ctx["screen_id"].split(":")[1])
        items, total = await repo.list_new_sculptures(limit=1, offset=offset)

        kb = InlineKeyboardBuilder()
        if not items:
            kb.button(text="⬅️ Назад", callback_data="nav:back")
            kb.button(text="🏠 Главное меню", callback_data="menu:main")
            kb.adjust(2)
            return Screen(text="Пока нет новых работ.", inline=kb.as_markup())

        s = items[0]
        kb.button(text="Подробнее", callback_data=f"sculpture:{s['id']}:0")
        if offset + 1 < total:
            kb.button(text="Следующая", callback_data=f"sculptures:new:{offset+1}")
        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)

        text = f"Новая работа:\n{s['title']}"
        return Screen(text=text, inline=kb.as_markup())

    async def featured_feed(chat_id: int, ctx: dict) -> Screen:
        offset = int(ctx["screen_id"].split(":")[1])
        items, total = await repo.list_featured_sculptures(limit=1, offset=offset)

        kb = InlineKeyboardBuilder()
        if not items:
            kb.button(text="⬅️ Назад", callback_data="nav:back")
            kb.button(text="🏠 Главное меню", callback_data="menu:main")
            kb.adjust(2)
            return Screen(text="Пока нет избранных работ.", inline=kb.as_markup())

        s = items[0]
        kb.button(text="Подробнее", callback_data=f"sculpture:{s['id']}:0")
        if offset + 1 < total:
            kb.button(text="Следующая", callback_data=f"sculptures:featured:{offset+1}")
        kb.button(text="⬅️ Назад", callback_data="nav:back")
        kb.button(text="🏠 Главное меню", callback_data="menu:main")
        kb.adjust(1)

        text = f"Избранное:\n{s['title']}"
        return Screen(text=text, inline=kb.as_markup())

    nav.register("sculptures_home", sculptures_home)
    nav.register("sculptures_collections", collections_page)
    nav.register("collection", collection_sculptures)
    nav.register("sculpture", sculpture_card)
    nav.register("new", new_feed)
    nav.register("featured", featured_feed)


@router.callback_query(F.data == "menu:sculptures")
async def open_sculptures_home(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "sculptures_home", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data.startswith("sculptures:collections:"))
async def open_collections(cb: CallbackQuery, nav: Nav):
    offset = cb.data.split(":")[2]
    await nav.show_screen(cb.bot, cb.from_user.id, f"sculptures_collections:{offset}", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data.startswith("collection:"))
async def open_collection(cb: CallbackQuery, nav: Nav):
    _, cid, offset = cb.data.split(":")
    await nav.show_screen(cb.bot, cb.from_user.id, f"collection:{cid}:{offset}", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data.startswith("sculpture:"))
async def open_sculpture(cb: CallbackQuery, nav: Nav):
    _, sid, pidx = cb.data.split(":")
    await nav.show_screen(cb.bot, cb.from_user.id, f"sculpture:{sid}:{pidx}", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data.startswith("sculpture_photo_next:"))
async def next_photo(cb: CallbackQuery, nav: Nav):
    _, sid, pidx = cb.data.split(":")
    await nav.show_screen(cb.bot, cb.from_user.id, f"sculpture:{sid}:{pidx}", push=False, remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data.startswith("sculptures:new:"))
async def new_feed(cb: CallbackQuery, nav: Nav):
    offset = cb.data.split(":")[2]
    await nav.show_screen(cb.bot, cb.from_user.id, f"new:{offset}", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data.startswith("sculptures:featured:"))
async def featured_feed(cb: CallbackQuery, nav: Nav):
    offset = cb.data.split(":")[2]
    await nav.show_screen(cb.bot, cb.from_user.id, f"featured:{offset}", remove_reply_keyboard=True)
    await cb.answer()


@router.callback_query(F.data == "guest:need_register")
async def guest_need_register(cb: CallbackQuery, nav: Nav):
    await nav.show_screen(cb.bot, cb.from_user.id, "settings:guest", remove_reply_keyboard=True)
    await cb.answer("Нужна регистрация")
