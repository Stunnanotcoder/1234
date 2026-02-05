# bot.py
import os
import asyncio
import logging
import re 
from pathlib import Path

import aiosqlite
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile
)

# ---------- НАСТРОЙКИ ----------
dotenv_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path)
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
if not BOT_TOKEN:
    raise SystemExit("Не найден BOT_TOKEN в .env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
log = logging.getLogger("form_and_bronze_bot")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()

DB_PATH = (Path(__file__).parent / "gallery_bot.db").resolve()
DB_NAME = str(DB_PATH)

# ---------- ФОТО: изолированная система по ключам ----------
# Кладите картинки сюда и называйте по ключам (см. STAGE_KEYS ниже):
BASE_IMAGE_DIR = Path(r"C:\Users\SystemX\Desktop\fb_images")

# fallback-ы
FALLBACK_LOCAL = Path(r"C:\Users\SystemX\Desktop\images.jpg")
FALLBACK_URL = "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcR7FwWHWE8V3yn9qWa2VatENfT46P9j8hYmrA&s"

# Список ключей-файлов, которые вы можете положить в папку BASE_IMAGE_DIR:
# intro, consent, name, gmail, notify, represents, menu,
# about, about_authors, about_history,
# projects, projects_golf, projects_ballet, projects_two_faces,
# meeting, contacts, visit, visit_spb, visit_moscow, visit_yerevan, visit_dubai,
# contact_me, confirm, thanks, settings
STAGE_KEYS = {
    "intro","consent","name","gmail","notify","represents","menu",
    "about","about_authors","about_history",
    "projects","projects_golf","projects_ballet","projects_two_faces",
    "meeting","contacts","visit","visit_spb","visit_moscow","visit_yerevan","visit_dubai",
    "contact_me","confirm","thanks","settings"
}

def _find_local_image_for(key: str):
    """Пытается найти локальную картинку для ключа в BASE_IMAGE_DIR."""
    try:
        if BASE_IMAGE_DIR.exists():
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                path = BASE_IMAGE_DIR / f"{key}{ext}"
                if path.exists():
                    return FSInputFile(str(path))
    except Exception as e:
        log.error(f"Ошибка поиска локального фото для {key}: {e}")
    return None

def get_stage_photo(key: str):
    """Возвращает FSInputFile для локального файла или URL-строку как photo source."""
    # 1) Пробуем локальную картинку для ключа
    local = _find_local_image_for(key)
    if local:
        return local
    # 2) Пробуем общий локальный fallback
    try:
        if FALLBACK_LOCAL.exists():
            return FSInputFile(str(FALLBACK_LOCAL))
    except Exception as e:
        log.error(f"Ошибка fallback локального фото: {e}")
    # 3) Финальный fallback — URL
    return FALLBACK_URL

async def send_stage_photo(chat_id: int, key: str, caption: str = "", reply_markup=None):
    """Отправляет фото для указанного этапа (key) с подписью и разметкой."""
    try:
        await bot.send_photo(chat_id=chat_id, photo=get_stage_photo(key), caption=caption, reply_markup=reply_markup)
    except Exception as e:
        log.error(f"send_stage_photo[{key}]: {e}")
        await bot.send_message(chat_id, caption or f"(Изображение для '{key}' недоступно)", reply_markup=reply_markup)

# ---------- БАЗА ДАННЫХ ----------
async def current_columns(db, table: str):
    cur = await db.execute(f"PRAGMA table_info({table})")
    return [r[1] for r in await cur.fetchall()]

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id          INTEGER PRIMARY KEY,
            name             TEXT,
            gmail            TEXT,
            represents       TEXT,
            phone            TEXT,
            connection       INTEGER DEFAULT 0,
            city             TEXT,
            tg_notifications INTEGER DEFAULT 0,
            consent          INTEGER DEFAULT 0
        )""")
        cols = await current_columns(db, "users")
        if "gmail" not in cols:            await db.execute("ALTER TABLE users ADD COLUMN gmail TEXT")
        if "represents" not in cols:       await db.execute("ALTER TABLE users ADD COLUMN represents TEXT")
        if "phone" not in cols:            await db.execute("ALTER TABLE users ADD COLUMN phone TEXT")
        if "connection" not in cols:       await db.execute("ALTER TABLE users ADD COLUMN connection INTEGER DEFAULT 0")
        if "city" not in cols:             await db.execute("ALTER TABLE users ADD COLUMN city TEXT")
        if "tg_notifications" not in cols: await db.execute("ALTER TABLE users ADD COLUMN tg_notifications INTEGER DEFAULT 0")
        if "consent" not in cols:          await db.execute("ALTER TABLE users ADD COLUMN consent INTEGER DEFAULT 0")
        await db.execute("DROP TABLE IF EXISTS callbacks")
        await db.execute("DROP TABLE IF EXISTS visits")
        await db.commit()
    log.info(f"DB ready at: {DB_PATH}")

async def upsert_user(user_id: int, **fields):
    allowed = {"name", "gmail", "represents", "phone", "connection", "city", "tg_notifications", "consent"}
    cols = [c for c in fields if c in allowed]
    if not cols:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
            await db.commit()
        return
    columns = ", ".join(["user_id"] + cols)
    placeholders = ", ".join(["?"] * (1 + len(cols)))
    update_set = ", ".join([f"{c}=excluded.{c}" for c in cols])
    values = [user_id] + [fields[c] for c in cols]
    sql = f"INSERT INTO users ({columns}) VALUES ({placeholders}) ON CONFLICT(user_id) DO UPDATE SET {update_set}"
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(sql, values)
        await db.commit()

async def get_user_row(user_id: int):
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute(
            "SELECT user_id, name, gmail, represents, phone, connection, city, tg_notifications, consent FROM users WHERE user_id = ?",
            (user_id,))
        return await cur.fetchone()

async def get_user_notify(user_id: int) -> int:
    row = await get_user_row(user_id)
    return 0 if not row else (row[7] or 0)

async def get_users_with_notifications():
    async with aiosqlite.connect(DB_NAME) as db:
        cur = await db.execute("SELECT user_id FROM users WHERE tg_notifications = 1")
        return [r[0] for r in await cur.fetchall()]

# ---------- FSM ----------
class Registration(StatesGroup):
    wait_intro = State()
    waiting_for_consent = State()
    waiting_for_name = State()
    waiting_for_gmail = State()
    waiting_for_notifications = State()
    waiting_for_represents = State()

class ContactFlow(StatesGroup):
    waiting_for_phone = State()
    confirm_callback = State()

class Settings(StatesGroup):
    choosing_action = State()
    editing_name = State()
    editing_gmail = State()
    confirming_delete = State()

class AdminStates(StatesGroup):
    waiting_for_news_text = State()
    waiting_for_news_photo = State()

# ---------- КЛАВИАТУРЫ ----------
def ikb(rows): return InlineKeyboardMarkup(inline_keyboard=rows)

def kb_intro():      return ikb([[InlineKeyboardButton(text="Познакомиться", callback_data="intro_go")]])

def kb_consent():
    return ikb([
        [InlineKeyboardButton(text="Подробнее", callback_data="consent_details")],
        [InlineKeyboardButton(text="Даю согласие", callback_data="consent_yes")],
        [InlineKeyboardButton(text="Отказ", callback_data="consent_no")],
    ])

def kb_notifications():
    return ikb([
        [InlineKeyboardButton(text="Подробнее", callback_data="notify_details")],
        [InlineKeyboardButton(text="Согласие", callback_data="notify_yes")],
        [InlineKeyboardButton(text="Отказ", callback_data="notify_no")],
    ])

def kb_represents():
    return ikb([
        [InlineKeyboardButton(text="Коллекционер", callback_data="rep_collector")],
        [InlineKeyboardButton(text="АРТ-Дилер / Представитель", callback_data="rep_dealer")],
        [InlineKeyboardButton(text="Просто интересуюсь", callback_data="rep_just")],
        [InlineKeyboardButton(text="Автор", callback_data="rep_author")],
    ])

def kb_main_menu():
    return ikb([
        [InlineKeyboardButton(text="О галерее", callback_data="menu_about")],
        [InlineKeyboardButton(text="Спецпроекты", callback_data="menu_projects")],
        [InlineKeyboardButton(text="Пригласите главного", callback_data="menu_meeting")],
        [InlineKeyboardButton(text="Настройки", callback_data="menu_settings")],
    ])

def kb_about_gallery():
    return ikb([
        [InlineKeyboardButton(text="Авторы", callback_data="about_authors")],
        [InlineKeyboardButton(text="История галереи", callback_data="about_history")],
        [InlineKeyboardButton(text="Меню", callback_data="back_to_menu")],
    ])

def kb_projects():
    return ikb([
        [InlineKeyboardButton(text="Golf. Game as Art.", callback_data="projects_golf")],
        [InlineKeyboardButton(text="Балет", callback_data="projects_ballet")],
        [InlineKeyboardButton(text="Две грани творчества", callback_data="projects_two_faces")],
        [InlineKeyboardButton(text="Меню", callback_data="back_to_menu")],
    ])

def kb_meeting():
    return ikb([
        [InlineKeyboardButton(text="Свяжитесь со мной", callback_data="menu_contact_me")],
        [InlineKeyboardButton(text="Визит", callback_data="meeting_visit")],
        [InlineKeyboardButton(text="Контакты", callback_data="meeting_contacts")],
        [InlineKeyboardButton(text="Меню", callback_data="back_to_menu")],
    ])

def kb_contacts():
    return ikb([
        [InlineKeyboardButton(text="Номер", callback_data="contacts_phone")],
        [InlineKeyboardButton(text="Email", callback_data="contacts_email")],
        [InlineKeyboardButton(text="Меню", callback_data="back_to_menu")],
    ])

def kb_cities():
    return ikb([
        [InlineKeyboardButton(text="Санкт-Петербург", callback_data="city_spb")],
        [InlineKeyboardButton(text="Москва", callback_data="city_moscow")],
        [InlineKeyboardButton(text="Ереван", callback_data="city_yerevan")],
        [InlineKeyboardButton(text="Дубай", callback_data="city_dubai")],
        [InlineKeyboardButton(text="Меню", callback_data="back_to_menu")],
    ])

def kb_settings(notify_on: int):
    toggle = InlineKeyboardButton(
        text=("Выключить уведомления" if notify_on else "Включить уведомления"),
        callback_data=("notif_off" if notify_on else "notif_on")
    )
    return ikb([
        [InlineKeyboardButton(text="Изменить имя", callback_data="set_name")],
        [InlineKeyboardButton(text="Изменить gmail", callback_data="set_gmail")],
        [toggle],
        [InlineKeyboardButton(text="Удалить аккаунт", callback_data="set_delete")],
        [InlineKeyboardButton(text="Меню", callback_data="back_to_menu")],
    ])

def kb_yes_no(yes_cb: str, no_cb: str):
    return ikb([[InlineKeyboardButton(text="Да", callback_data=yes_cb),
                 InlineKeyboardButton(text="Нет", callback_data=no_cb)]])

def kb_share_contact():
    return ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True, keyboard=[
        [KeyboardButton(text="Поделиться контактом", request_contact=True)],
        [KeyboardButton(text="Ввести номер вручную")]
    ])

# ---------- ВАЛИДАЦИЯ ----------
def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", email or ""))

def is_valid_phone(phone: str) -> bool:
    clean = re.sub(r"[^\d+]", "", phone or "")
    return bool(re.match(r"^\+?\d{8,15}$", clean))

def city_text(code: str) -> str:
    m = {
        "spb": "Санкт-Петербург: наш шоурум с классической и современной экспозицией.",
        "moscow": "Москва: посещение по записи, актуальная подборка авторских работ.",
        "yerevan": "Ереван: камерное пространство и встречи с художниками.",
        "dubai": "Дубай: резиденция и спецпроекты, приём по предварительному согласованию.",
    }
    return m.get(code, "Город")

# ---------- /start ----------
@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext):
    await upsert_user(message.from_user.id)  # гарантируем строку
    row = await get_user_row(message.from_user.id)
    registered = bool(row and (row[8] == 1) and row[1] and row[2] and row[3])  # consent=1, name, gmail, represents
    if registered:
        await send_stage_photo(
            chat_id=message.from_user.id, key="menu",
            caption="Form & Bronze рада приветствовать вас! Выберите, что вам интересно узнать в первую очередь.",
            reply_markup=kb_main_menu()
        )
        await state.clear()
        return

    await send_stage_photo(
        chat_id=message.from_user.id, key="intro",
        caption=("Вы в пространстве <b>Form & Bronze</b> — галереи, где бронза становится языком искусства, а форма рождает смысл.\nМы <b>создаём скульптуры более двадцати лет</b>, соединяя классику и современность. "
                 "\n<b>Добро пожаловать</b> — приглашаем вас открыть наши коллекции и узнать больше о том, как звучит бронза сегодня."),
        reply_markup=kb_intro()
    )
    await state.set_state(Registration.wait_intro)

# ---------- Регистрация: согласие → имя → gmail → уведомления → represents ----------
@router.callback_query(Registration.wait_intro, F.data == "intro_go")
async def intro_go(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await send_stage_photo(
        chat_id=callback.from_user.id, key="consent",
        caption=("Перед тем как начать, нам важно получить ваше согласие на обработку персональных данных. "
                 "Мы попросим ваше имя и электронную почту, чтобы приглашать вас на выставки и сообщать о новых работах. Никаких лишних писем и никогда не передаём данные третьим лицам.\n"
                 "Отписаться можно в любой момент."),
        reply_markup=kb_consent()
    )
    await state.set_state(Registration.waiting_for_consent)

@router.callback_query(Registration.waiting_for_consent, F.data == "consent_details")
async def consent_details(callback: CallbackQuery):
    # редактируем подпись у ТЕКУЩЕГО фото
    await callback.message.edit_caption(
        caption=("Подробнее: обработка данных строго для связи по искусству и мероприятиям. "
                 "Вы можете отозвать согласие через «Настройки»."),
        reply_markup=kb_consent()
    )

@router.callback_query(Registration.waiting_for_consent, F.data == "consent_no")
async def consent_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await bot.send_message(callback.from_user.id, "Спасибо за ваш интерес. Вы всегда можете вернуться к регистрации позже.")
    await state.clear()

@router.callback_query(Registration.waiting_for_consent, F.data == "consent_yes")
async def consent_yes(callback: CallbackQuery, state: FSMContext):
    await upsert_user(callback.from_user.id, consent=1)
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "name", "Как к вам обращаться? Напишите, пожалуйста, имя.""\nИмя нужно, чтобы вести диалог корректно и персонально.")
    await state.set_state(Registration.waiting_for_name)

@router.message(Registration.waiting_for_name)
async def reg_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2:
        await message.answer("Имя должно быть не короче 2 символов. Попробуйте ещё раз.")
        return
    await upsert_user(message.from_user.id, name=name)
    await send_stage_photo(message.from_user.id, "gmail", "Оставьте e-mail для обратной связи, приглашений на выставки и представлений новых работы. Пишем редко и по делу.")
    await state.set_state(Registration.waiting_for_gmail)

@router.message(Registration.waiting_for_gmail)
async def reg_gmail(message: Message, state: FSMContext):
    email = (message.text or "").strip()
    if not is_valid_email(email):
        await message.answer("Похоже, это не email. Введите корректный адрес, пожалуйста.")
        return
    await upsert_user(message.from_user.id, gmail=email)
    await send_stage_photo(
        chat_id=message.from_user.id, key="notify",
        caption=("Хотите ли вы получать уведомления в Telegram о наших новых выставках?"),
        reply_markup=kb_notifications()
    )
    await state.set_state(Registration.waiting_for_notifications)

@router.callback_query(Registration.waiting_for_notifications, F.data.in_(["notify_details","notify_yes","notify_no"]))
async def reg_notify(callback: CallbackQuery, state: FSMContext):
    if callback.data == "notify_details":
        await callback.message.edit_caption(
            caption="Уведомления в Telegram — редкие и по делу: премьерные показы, важные анонсы.",
            reply_markup=kb_notifications()
        )
        return
    await upsert_user(callback.from_user.id, tg_notifications=(1 if callback.data == "notify_yes" else 0))
    await callback.message.delete()
    await send_stage_photo(
        chat_id=callback.from_user.id, key="represents",
        caption=("Благодарим! Вы в списке наших дорогих гостей. "
                 "Подскажите, в каком качестве вы интересуетесь галереей?"),
        reply_markup=kb_represents()
    )
    await state.set_state(Registration.waiting_for_represents)

@router.callback_query(Registration.waiting_for_represents, F.data.startswith("rep_"))
async def reg_represents(callback: CallbackQuery, state: FSMContext):
    mapping = {
        "rep_collector": "коллекционер",
        "rep_dealer": "арт-диллер",
        "rep_just": "просто",
        "rep_author": "автор",
    }
    await upsert_user(callback.from_user.id, represents=mapping.get(callback.data, "просто"))
    await callback.message.delete()
    await send_stage_photo(
        chat_id=callback.from_user.id, key="menu",
        caption="Галерея Form & Bronze рада приветствовать вас! Выберите, что вам интересно узнать в первую очередь.",
        reply_markup=kb_main_menu()
    )
    await state.clear()

# ---------- Главное меню ----------
@router.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "menu",
        "Галерея Form & Bronze рада приветствовать вас! Выберите, что вам интересно узнать в первую очередь.",
        kb_main_menu())

# О галерее
@router.callback_query(F.data == "menu_about")
async def menu_about(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "about",
        "Form & Bronze — лидер в области современной скульптуры, галерея и центр работы с бронзой в Санкт-Петербурге. Более 20 лет мы создаём произведения полного цикла: от эскиза до литейного производства и установки. Для коллекционеров и компаний мы предлагаем безупречное качество, масштабные проекты и поддержку в формировании частных и корпоративных собраний. Для художников и скульпторов — конкурсы, спецпроекты и площадку для экспериментов. Для широкой публики — выставки, лекции и уникальные материалы о современном искусстве. Наши работы — от камерных пластик до монументальных композиций — украшают улицы и университеты Санкт-Петербурга и других городов. Form & Bronze соединяет традиции академического искусства и язык современности, создавая культурный код времени",
        kb_about_gallery())

@router.callback_query(F.data == "about_authors")
async def about_authors(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "about_authors",
        "Авторы — мастера и молодые таланты, работающие с бронзой.",
        ikb([[InlineKeyboardButton(text="Меню", callback_data="back_to_menu")]]))

@router.callback_query(F.data == "about_history")
async def about_history(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "about_history",
        "История галереи: путь от первых отливок к крупным выставочным проектам и международным коллаборациям.",
        ikb([[InlineKeyboardButton(text="Меню", callback_data="back_to_menu")]]))

# Спецпроекты
@router.callback_query(F.data == "menu_projects")
async def menu_projects(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "projects",
        "Спецпроекты: премьеры и смелые трактовки классики.",
        kb_projects())

@router.callback_query(F.data == "projects_golf")
async def projects_golf(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "projects_golf",
        "Проект <b>Golf. Game as Art</b> открывает мир спорта в языке скульптуры. Героями становятся Дон Кихот, Шерлок Холмс, Черчилль и даже Папа Римский — все они оказываются на поле с клюшками и мячами. Скульптуры наполнены лёгкой иронией и превращают игру в метафору искусства",
        ikb([[InlineKeyboardButton(text="Меню", callback_data="back_to_menu")]]))

@router.callback_query(F.data == "projects_ballet")
async def projects_ballet(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "projects_ballet",
        "Цикл <b>Балет</b> в Form & Bronze объединяет работы, вдохновлённые великими спектаклями и образами танцовщиков. Герои классических партий, юные балерины и легендарные фигуры оживают в бронзе, сохраняя энергию движения и поэзию сцены. В 2024 году галерея провела международный конкурс-фестиваль «Балет. Form & Bronze», собравший десятки участников из России, Армении и Узбекистана. Победителем стал Виктор Мосиелев со скульптурой «Муза», олицетворяющей вдохновение. Среди призёров — Евгений Соколов («Мышиный король»), Александра Давыдова («Чёрный лебедь»), Екатерина Шилова («Стремление») и Хожиакбар Назиров, чья работа поразила эмоциональной выразительностью. Этот проект стал платформой для открытия новых имён и показал, как пластика бронзы может передать грацию и драму балета",
        ikb([[InlineKeyboardButton(text="Меню", callback_data="back_to_menu")]]))

@router.callback_query(F.data == "projects_two_faces")
async def projects_two_faces(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "projects_two_faces",
        "«<b>Две грани творчества</b> — наш экспериментальный проект, где живописцы и графики переводят свои работы в язык бронзовой скульптуры. Художники, привыкшие к плоскости холста, открывают для себя объём, фактуру и вес металла, а зритель получает возможность увидеть знакомые образы в новом измерении. Это диалог жанров и поиск новых художественных горизонтов, где традиция изобразительного искусства соединяется с пластикой бронзы",
        ikb([[InlineKeyboardButton(text="Меню", callback_data="back_to_menu")]]))

# Встреча
@router.callback_query(F.data == "menu_meeting")
async def menu_meeting(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "meeting", "Выберите формат встречи.", kb_meeting())

@router.callback_query(F.data == "meeting_contacts")
async def meeting_contacts(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "contacts", "Свяжитесь с нами удобным способом.", kb_contacts())

@router.callback_query(F.data == "contacts_phone")
async def contacts_phone(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("+7 (XXX) XXX-XX-XX")

@router.callback_query(F.data == "contacts_email")
async def contacts_email(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer("example@gallery.com")

@router.callback_query(F.data == "meeting_visit")
async def meeting_visit(callback: CallbackQuery):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "visit", "Выберите город визита:", kb_cities())

@router.callback_query(F.data.in_(["city_spb", "city_moscow", "city_yerevan", "city_dubai"]))
async def visit_city(callback: CallbackQuery):
    mapping = {"city_spb": ("спб","spb"), "city_moscow": ("москва","moscow"),
               "city_yerevan": ("ереван","yerevan"), "city_dubai": ("дубай","dubai")}
    value, code = mapping[callback.data]
    await upsert_user(callback.from_user.id, city=value)
    key = f"visit_{code}"  # попытка подобрать городскую фотку, напр. visit_spb
    if key not in STAGE_KEYS:
        key = "visit"
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, key, f"{city_text(code)}\n\nВаш выбор сохранён: {value}.",
        ikb([[InlineKeyboardButton(text="Меню", callback_data="back_to_menu")]]))

# Свяжитесь со мной
@router.callback_query(F.data == "menu_contact_me")
async def contact_me(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "contact_me", "Оставьте свой номер телефона.")
    await bot.send_message(callback.from_user.id, "Поделитесь контактом через Telegram или введите номер вручную.",
                           reply_markup=kb_share_contact())
    await state.set_state(ContactFlow.waiting_for_phone)

@router.message(ContactFlow.waiting_for_phone, F.contact)
async def got_tg_contact(message: Message, state: FSMContext):
    phone = message.contact.phone_number
    await upsert_user(message.from_user.id, phone=phone)
    await state.update_data(phone=phone)
    await send_stage_photo(message.from_user.id, "confirm",
        f"Отправить заявку на отложенный вызов?\nТелефон: <b>{phone}</b>",
        kb_yes_no("cb_send", "cb_cancel"))
    await state.set_state(ContactFlow.confirm_callback)

@router.message(ContactFlow.waiting_for_phone)
async def got_phone_text(message: Message, state: FSMContext):
    phone = (message.text or "").strip()
    if not is_valid_phone(phone):
        await message.answer("Введите корректный номер (минимум 8 цифр, можно с +).")
        return
    await upsert_user(message.from_user.id, phone=phone)
    await state.update_data(phone=phone)
    await send_stage_photo(message.from_user.id, "confirm",
        f"Отправить заявку на отложенный вызов?\nТелефон: <b>{phone}</b>",
        kb_yes_no("cb_send", "cb_cancel"))
    await state.set_state(ContactFlow.confirm_callback)

@router.callback_query(ContactFlow.confirm_callback, F.data == "cb_send")
async def cb_send(callback: CallbackQuery, state: FSMContext):
    await upsert_user(callback.from_user.id, connection=1)
    await callback.message.delete()
    await bot.send_message(callback.from_user.id, "Заявка отправлена.", reply_markup=ReplyKeyboardRemove())
    await send_stage_photo(callback.from_user.id, "thanks", "В ближайшее время вам напишут.",
                          ikb([[InlineKeyboardButton(text="Меню", callback_data="back_to_menu")]]))
    await state.clear()

@router.callback_query(ContactFlow.confirm_callback, F.data == "cb_cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext):
    await upsert_user(callback.from_user.id, connection=0)
    await callback.message.delete()
    await bot.send_message(callback.from_user.id, "Заявка отменена.", reply_markup=ReplyKeyboardRemove())
    await send_stage_photo(callback.from_user.id, "menu", "Возвращаемся в главное меню.", kb_main_menu())
    await state.clear()

# ---------- Настройки ----------
@router.callback_query(F.data == "menu_settings")
async def menu_settings(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    notify = await get_user_notify(callback.from_user.id)
    await send_stage_photo(callback.from_user.id, "settings", "Настройки аккаунта. Выберите действие:", kb_settings(notify))
    await state.set_state(Settings.choosing_action)

@router.callback_query(Settings.choosing_action, F.data == "set_name")
async def set_name(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "settings", "Введите новое имя:")
    await state.set_state(Settings.editing_name)

@router.message(Settings.editing_name)
async def on_edit_name(message: Message, state: FSMContext):
    new_name = (message.text or "").strip()
    if len(new_name) < 2:
        await message.answer("Имя должно быть не короче 2 символов. Повторите ввод.")
        return
    await upsert_user(message.from_user.id, name=new_name)
    notify = await get_user_notify(message.from_user.id)
    await message.answer("Имя обновлено.", reply_markup=kb_settings(notify))
    await state.set_state(Settings.choosing_action)

@router.callback_query(Settings.choosing_action, F.data == "set_gmail")
async def set_gmail(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "settings", "Введите новый gmail:")
    await state.set_state(Settings.editing_gmail)

@router.message(Settings.editing_gmail)
async def on_edit_gmail(message: Message, state: FSMContext):
    new_gmail = (message.text or "").strip()
    if not is_valid_email(new_gmail):
        await message.answer("Введите корректный email (gmail).")
        return
    await upsert_user(message.from_user.id, gmail=new_gmail)
    notify = await get_user_notify(message.from_user.id)
    await message.answer("Gmail обновлён.", reply_markup=kb_settings(notify))
    await state.set_state(Settings.choosing_action)

@router.callback_query(Settings.choosing_action, F.data == "notif_on")
async def notif_on(callback: CallbackQuery, state: FSMContext):
    await upsert_user(callback.from_user.id, tg_notifications=1)
    await callback.message.edit_reply_markup(reply_markup=kb_settings(1))
    await callback.answer("Уведомления включены")

@router.callback_query(Settings.choosing_action, F.data == "notif_off")
async def notif_off(callback: CallbackQuery, state: FSMContext):
    await upsert_user(callback.from_user.id, tg_notifications=0)
    await callback.message.edit_reply_markup(reply_markup=kb_settings(0))
    await callback.answer("Уведомления выключены")

@router.callback_query(Settings.choosing_action, F.data == "set_delete")
async def set_delete(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    await send_stage_photo(callback.from_user.id, "settings",
                           "Удалить аккаунт? Все ваши данные будут удалены.",
                           kb_yes_no("delete_yes", "delete_no"))
    await state.set_state(Settings.confirming_delete)

@router.callback_query(Settings.confirming_delete, F.data == "delete_yes")
async def delete_yes(callback: CallbackQuery, state: FSMContext):
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("DELETE FROM users WHERE user_id = ?", (callback.from_user.id,))
            await db.commit()
        await callback.message.delete()
        await bot.send_message(callback.from_user.id, "Аккаунт удалён. Вы всегда можете начать заново — /start")
    except Exception as e:
        log.error(f"delete error: {e}")
        await callback.message.answer("Не удалось удалить аккаунт. Попробуйте позже.")
    await state.clear()

@router.callback_query(Settings.confirming_delete, F.data == "delete_no")
async def delete_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.delete()
    notify = await get_user_notify(callback.from_user.id)
    await send_stage_photo(callback.from_user.id, "settings", "Операция отменена.", kb_settings(notify))
    await state.set_state(Settings.choosing_action)

# ---------- Админ-рассылка: текст -> (опционально) фото ----------
class AdminStates(StatesGroup):
    waiting_for_news_text = State()
    waiting_for_news_photo = State()

@router.message(Command("admin_news"))
async def admin_news(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        await message.answer("Нет прав на рассылку.")
        return
    await message.answer("Отправьте текст рассылки (получат только пользователи с включёнными уведомлениями).")
    await state.set_state(AdminStates.waiting_for_news_text)

@router.message(AdminStates.waiting_for_news_text)
async def admin_news_text(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        await message.answer("Нет прав на рассылку.")
        await state.clear()
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пусто. Пришлите текст.")
        return
    await state.update_data(news_text=text)
    await message.answer(
        "Текст сохранён. Теперь пришлите фото для рассылки (по желанию) "
        "или отправьте слово «нет», чтобы разослать только текст."
    )
    await state.set_state(AdminStates.waiting_for_news_photo)

@router.message(AdminStates.waiting_for_news_photo)
async def admin_news_photo(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID or ADMIN_ID == 0:
        await message.answer("Нет прав на рассылку.")
        await state.clear()
        return

    data = await state.get_data()
    news_text = data.get("news_text", "")

    users = await get_users_with_notifications()
    sent, fail = 0, 0

    if message.text and message.text.strip().lower() == "нет":
        for uid in users:
            try:
                await bot.send_message(uid, news_text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                log.error(f"admin_news text to {uid}: {e}")
                fail += 1
        await message.answer(f"Рассылка (только текст) завершена. Отправлено: {sent}, ошибок: {fail}")
        await state.clear()
        return

    if message.photo:
        file_id = message.photo[-1].file_id
        for uid in users:
            try:
                await bot.send_photo(uid, file_id, caption=news_text, parse_mode=ParseMode.HTML)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                log.error(f"admin_news photo to {uid}: {e}")
                fail += 1
        await message.answer(f"Рассылка (фото + подпись) завершена. Отправлено: {sent}, ошибок: {fail}")
        await state.clear()
        return

    await message.answer("Пришлите фото или напишите «нет».")

# ---------- Диагностика ----------
@router.message(Command("db_path"))
async def cmd_db_path(message: Message):
    await message.answer(f"Путь к БД: <code>{DB_PATH}</code>")

@router.message(Command("me"))
async def cmd_me(message: Message):
    try:
        row = await get_user_row(message.from_user.id)
        if not row:
            await message.answer("Запись не найдена.")
            return
        user_id, name, gmail, represents, phone, connection, city, tg, consent = row
        txt = (f"<b>user_id</b>: {user_id}\n<b>name</b>: {name or '—'}\n<b>gmail</b>: {gmail or '—'}\n"
               f"<b>represents</b>: {represents or '—'}\n<b>phone</b>: {phone or '—'}\n"
               f"<b>connection</b>: {connection}\n<b>city</b>: {city or '—'}\n"
               f"<b>tg_notifications</b>: {tg}\n<b>consent</b>: {consent}")
        await message.answer(txt)
    except Exception as e:
        log.error(f"/me error: {e}")
        await message.answer("Ошибка при чтении БД.")

# ---------- Fallback ----------
@router.message()
async def fallback(message: Message):
    await message.answer("Не понимаю команду. Используйте кнопки меню (/start).")

# ---------- MAIN ----------
async def main():
    await init_db()
    dp.include_router(router)
    log.info(f"SQLite DB path: {DB_PATH}")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())

