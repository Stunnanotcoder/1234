from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app.db.repo import Repo, utcnow_iso

router = Router()


class AddCollection(StatesGroup):
    title = State()
    short_desc = State()
    cover = State()
    sort_order = State()


class AddSculpture(StatesGroup):
    choose_collection = State()
    photos = State()
    title = State()
    artist = State()
    material = State()
    year = State()
    dimensions = State()
    desc_short = State()
    status = State()
    ask_new = State()
    ask_featured = State()
    ask_broadcast = State()


STATUSES = ["in_expo", "available", "sold", "on_request"]


def _admin_only(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids



@router.callback_query(F.data == "admin:add_collection")
async def start_add_collection(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _admin_only(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    await state.set_state(AddCollection.title)
    await cb.bot.send_message(cb.from_user.id, "Введите название коллекции:")
    await cb.answer()


@router.message(AddCollection.title)
async def add_collection_title(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    t = (message.text or "").strip()
    if not t or len(t) > 80:
        await message.answer("Название 1–80 символов.")
        return
    await state.update_data(title=t)
    await state.set_state(AddCollection.short_desc)
    await message.answer("Введите short_desc (или '-' чтобы пропустить):")


@router.message(AddCollection.short_desc)
async def add_collection_desc(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    d = (message.text or "").strip()
    if d == "-":
        d = None
    await state.update_data(short_desc=d)
    await state.set_state(AddCollection.cover)
    await message.answer("Пришлите обложку (фото) или '-' чтобы пропустить:")


@router.message(AddCollection.cover)
async def add_collection_cover(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    cover = None
    if message.text and message.text.strip() == "-":
        cover = None
    elif message.photo:
        cover = message.photo[-1].file_id
    else:
        await message.answer("Пришлите фото или '-'")
        return
    await state.update_data(cover=cover)
    await state.set_state(AddCollection.sort_order)
    await message.answer("Введите sort_order (целое число, например 0):")


@router.message(AddCollection.sort_order)
async def add_collection_sort(message: Message, repo: Repo, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    raw = (message.text or "").strip()
    try:
        so = int(raw)
    except ValueError:
        await message.answer("Нужно целое число.")
        return
    data = await state.get_data()
    cid = await repo.add_collection(
        title=data["title"],
        short_desc=data.get("short_desc"),
        cover_file_id=data.get("cover"),
        sort_order=so,
    )
    await state.clear()
    await message.answer(f"Коллекция добавлена. ID={cid}")


@router.callback_query(F.data == "admin:add_sculpture")
async def start_add_sculpture(cb: CallbackQuery, repo: Repo, admin_ids: set[int], state: FSMContext):
    if not _admin_only(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    items, _ = await repo.list_collections(active_only=False, limit=50, offset=0)
    if not items:
        await cb.bot.send_message(cb.from_user.id, "Нет коллекций. Сначала добавь коллекцию.")
        await cb.answer()
        return
    kb = InlineKeyboardBuilder()
    for c in items:
        kb.button(text=c["title"], callback_data=f"adm:sc:col:{c['id']}")
    kb.adjust(1)
    await state.set_state(AddSculpture.choose_collection)
    await cb.bot.send_message(cb.from_user.id, "Выберите коллекцию:", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:sc:col:"))
async def choose_collection(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _admin_only(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    cid = int(cb.data.split(":")[3])
    await state.update_data(collection_id=cid, photos=[])
    await state.set_state(AddSculpture.photos)
    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Готово", callback_data="adm:sc:photos_done")
    await cb.bot.send_message(cb.from_user.id, "Отправьте 1–6 фото по одному. Затем нажмите ✅ Готово.", reply_markup=kb.as_markup())
    await cb.answer()


@router.message(AddSculpture.photos)
async def collect_photos(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    if not message.photo:
        await message.answer("Нужно фото. Отправь фото или нажми ✅ Готово.")
        return
    data = await state.get_data()
    photos = data.get("photos", [])
    if len(photos) >= 6:
        await message.answer("Максимум 6 фото. Нажми ✅ Готово.")
        return
    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"Ок, фото добавлено ({len(photos)}/6).")


@router.callback_query(F.data == "adm:sc:photos_done")
async def photos_done(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _admin_only(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    data = await state.get_data()
    if not data.get("photos"):
        await cb.bot.send_message(cb.from_user.id, "Нужно минимум 1 фото.")
        await cb.answer()
        return
    await state.set_state(AddSculpture.title)
    await cb.bot.send_message(cb.from_user.id, "Введите title скульптуры:")
    await cb.answer()


@router.message(AddSculpture.title)
async def sc_title(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    t = (message.text or "").strip()
    if not t or len(t) > 120:
        await message.answer("Title 1–120 символов.")
        return
    await state.update_data(title=t)
    await state.set_state(AddSculpture.artist)
    await message.answer("Введите artist (или '-' чтобы пропустить):")


@router.message(AddSculpture.artist)
async def sc_artist(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    v = (message.text or "").strip()
    await state.update_data(artist=None if v == "-" else v)
    await state.set_state(AddSculpture.material)
    await message.answer("Введите material (или '-' чтобы пропустить):")


@router.message(AddSculpture.material)
async def sc_material(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    v = (message.text or "").strip()
    await state.update_data(material=None if v == "-" else v)
    await state.set_state(AddSculpture.year)
    await message.answer("Введите year (или '-' чтобы пропустить):")


@router.message(AddSculpture.year)
async def sc_year(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    v = (message.text or "").strip()
    await state.update_data(year=None if v == "-" else v)
    await state.set_state(AddSculpture.dimensions)
    await message.answer("Введите dimensions (или '-' чтобы пропустить):")


@router.message(AddSculpture.dimensions)
async def sc_dimensions(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    v = (message.text or "").strip()
    await state.update_data(dimensions=None if v == "-" else v)
    await state.set_state(AddSculpture.desc_short)
    await message.answer("Введите description_short (или '-' чтобы пропустить):")


@router.message(AddSculpture.desc_short)
async def sc_desc_short(message: Message, admin_ids: set[int], state: FSMContext):
    if not _admin_only(message.from_user.id, admin_ids):
        return
    v = (message.text or "").strip()
    await state.update_data(description_short=None if v == "-" else v)
    await state.set_state(AddSculpture.status)
    kb = InlineKeyboardBuilder()
    for s in STATUSES:
        kb.button(text=s, callback_data=f"adm:sc:status:{s}")
    kb.adjust(2)
    await message.answer("Выберите status:", reply_markup=kb.as_markup())


@router.callback_query(F.data.startswith("adm:sc:status:"))
async def sc_status(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _admin_only(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    status = cb.data.split(":")[3]
    await state.update_data(status=status)

    kb = InlineKeyboardBuilder()
    kb.button(text="Да", callback_data="adm:sc:new:yes")
    kb.button(text="Нет", callback_data="adm:sc:new:no")
    kb.adjust(2)

    await state.set_state(AddSculpture.ask_new)
    await cb.bot.send_message(cb.from_user.id, "Отметить как новинку? (published_at=now)", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:sc:new:"))
async def sc_new(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _admin_only(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    yes = cb.data.endswith("yes")
    await state.update_data(published_at=utcnow_iso() if yes else None)

    kb = InlineKeyboardBuilder()
    kb.button(text="Да", callback_data="adm:sc:feat:yes")
    kb.button(text="Нет", callback_data="adm:sc:feat:no")
    kb.adjust(2)

    await state.set_state(AddSculpture.ask_featured)
    await cb.bot.send_message(cb.from_user.id, "Добавить в избранное? (is_featured)", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:sc:feat:"))
async def sc_feat(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _admin_only(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    yes = cb.data.endswith("yes")
    await state.update_data(is_featured=1 if yes else 0)

    kb = InlineKeyboardBuilder()
    kb.button(text="Да", callback_data="adm:sc:bc:yes")
    kb.button(text="Нет", callback_data="adm:sc:bc:no")
    kb.adjust(2)

    await state.set_state(AddSculpture.ask_broadcast)
    await cb.bot.send_message(cb.from_user.id, "Разослать подписчикам? (notify_enabled=1)", reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("adm:sc:bc:"))
async def sc_finish(cb: CallbackQuery, repo: Repo, admin_ids: set[int], state: FSMContext):
    if not _admin_only(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    do_bc = cb.data.endswith("yes")
    data = await state.get_data()

    sid = await repo.add_sculpture(
        collection_id=int(data["collection_id"]),
        title=data["title"],
        artist=data.get("artist"),
        material=data.get("material"),
        year=data.get("year"),
        dimensions=data.get("dimensions"),
        description_short=data.get("description_short"),
        status=data.get("status", "in_expo"),
        is_featured=data.get("is_featured", 0),
        published_at=data.get("published_at"),
        description_full=None,
    )

    for i, fid in enumerate(data["photos"]):
        await repo.add_sculpture_photo(sid, fid, i)

    await state.clear()
    await cb.bot.send_message(cb.from_user.id, f"Скульптура добавлена. ID={sid}")

    if do_bc:
        # простая рассылка: фото1 + title
        from app.handlers.admin_broadcast import _send_broadcast
        tmp = await cb.bot.send_photo(cb.from_user.id, photo=data["photos"][0], caption=f"Новая работа:\n{data['title']}")
        ok, fail = await _send_broadcast(cb.bot, repo, "all", cb.from_user.id, tmp.message_id, None, None)
        await cb.bot.send_message(cb.from_user.id, f"Разослано подписчикам. Успешно: {ok} / Ошибок: {fail}")

    await cb.answer()
