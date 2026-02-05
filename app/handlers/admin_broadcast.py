from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app import texts
from app.db.repo import Repo

router = Router()


class Broadcast(StatesGroup):
    audience = State()
    post = State()
    add_link = State()
    link_text = State()
    link_url = State()


def _is_admin(user_id: int, admin_ids: set[int]) -> bool:
    return user_id in admin_ids


async def _send_broadcast(
    bot: Bot,
    repo: Repo,
    audience: str,
    src_chat_id: int,
    src_msg_id: int,
    link_text: str | None,
    link_url: str | None,
):
    q = "SELECT telegram_id FROM users WHERE consent=1 AND notify_enabled=1"
    params: list = []
    if audience != "all":
        q += " AND role=?"
        params.append(audience)

    cur = await repo._c().execute(q, params)
    rows = await cur.fetchall()
    user_ids = [r["telegram_id"] for r in rows]

    kb = InlineKeyboardBuilder()
    if link_text and link_url:
        kb.button(text=link_text, url=link_url)
    kb.button(text="🏠 Главное меню", callback_data="menu:main")
    kb.adjust(1)
    markup = kb.as_markup()

    ok = 0
    fail = 0
    for uid in user_ids:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=src_chat_id,
                message_id=src_msg_id,
                reply_markup=markup,
            )
            ok += 1
        except Exception:
            fail += 1
            continue
    return ok, fail


@router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, admin_ids: set[int], state: FSMContext):
    if not _is_admin(message.from_user.id, admin_ids):
        return
    await state.set_state(Broadcast.audience)
    kb = InlineKeyboardBuilder()
    for a in ["all", "collector", "dealer", "author", "interest"]:
        kb.button(text=a, callback_data=f"bc:aud:{a}")
    kb.adjust(2)
    await message.answer(texts.BROADCAST_AUDIENCE_TEXT, reply_markup=kb.as_markup())


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_from_panel(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _is_admin(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    await state.set_state(Broadcast.audience)
    kb = InlineKeyboardBuilder()
    for a in ["all", "collector", "dealer", "author", "interest"]:
        kb.button(text=a, callback_data=f"bc:aud:{a}")
    kb.adjust(2)
    await cb.bot.send_message(cb.from_user.id, texts.BROADCAST_AUDIENCE_TEXT, reply_markup=kb.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("bc:aud:"))
async def bc_audience(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _is_admin(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    aud = cb.data.split(":")[2]
    await state.update_data(audience=aud)
    await state.set_state(Broadcast.post)
    await cb.bot.send_message(cb.from_user.id, texts.BROADCAST_SEND_PROMPT)
    await cb.answer()


@router.message(Broadcast.post)
async def bc_post(message: Message, admin_ids: set[int], state: FSMContext):
    if not _is_admin(message.from_user.id, admin_ids):
        return
    await state.update_data(src_chat_id=message.chat.id, src_msg_id=message.message_id)
    await state.set_state(Broadcast.add_link)
    kb = InlineKeyboardBuilder()
    kb.button(text="Да", callback_data="bc:link:yes")
    kb.button(text="Нет", callback_data="bc:link:no")
    kb.adjust(2)
    await message.answer(texts.BROADCAST_ADD_LINK_Q, reply_markup=kb.as_markup())


@router.callback_query(F.data == "bc:link:no")
async def bc_no_link(cb: CallbackQuery, admin_ids: set[int], state: FSMContext, repo: Repo):
    if not _is_admin(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    data = await state.get_data()
    ok, fail = await _send_broadcast(
        cb.bot, repo,
        data["audience"],
        data["src_chat_id"], data["src_msg_id"],
        None, None
    )
    await state.clear()
    await cb.bot.send_message(cb.from_user.id, f"{texts.BROADCAST_DONE_TEXT}\nУспешно: {ok} / Ошибок: {fail}")
    await cb.answer()


@router.callback_query(F.data == "bc:link:yes")
async def bc_yes_link(cb: CallbackQuery, admin_ids: set[int], state: FSMContext):
    if not _is_admin(cb.from_user.id, admin_ids):
        await cb.answer()
        return
    await state.set_state(Broadcast.link_text)
    await cb.bot.send_message(cb.from_user.id, texts.BROADCAST_LINK_TEXT_Q)
    await cb.answer()


@router.message(Broadcast.link_text)
async def bc_link_text(message: Message, admin_ids: set[int], state: FSMContext):
    if not _is_admin(message.from_user.id, admin_ids):
        return
    t = (message.text or "").strip()
    if not t or len(t) > 40:
        await message.answer("Текст кнопки должен быть 1–40 символов.")
        return
    await state.update_data(link_text=t)
    await state.set_state(Broadcast.link_url)
    await message.answer(texts.BROADCAST_LINK_URL_Q)


@router.message(Broadcast.link_url)
async def bc_link_url(message: Message, admin_ids: set[int], state: FSMContext, repo: Repo):
    if not _is_admin(message.from_user.id, admin_ids):
        return
    url = (message.text or "").strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        await message.answer("URL должен начинаться с http:// или https://")
        return
    data = await state.get_data()
    ok, fail = await _send_broadcast(
        message.bot, repo,
        data["audience"],
        data["src_chat_id"], data["src_msg_id"],
        data.get("link_text"), url
    )
    await state.clear()
    await message.answer(f"{texts.BROADCAST_DONE_TEXT}\nУспешно: {ok} / Ошибок: {fail}")
