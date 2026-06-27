import asyncio
import logging
import random
import time
import io
import os
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile, InputMediaPhoto, BotCommand
)
from aiogram.exceptions import TelegramBadRequest

# Импорт библиотеки для обработки изображений (отрисовка рамок)
try:
    from PIL import Image, ImageOps
except ImportError:
    raise ImportError("Установите Pillow: pip install Pillow")

import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА
# ========================================================================
BOT_TOKEN = "7725898870:AAHa-6biiZkWuheNzjPl0Tun3XpNyLNq1lE" # Замени на свой токен
SUPER_ADMIN_ID = 5341904332 # Замени на свой Telegram ID
DB_NAME = "cards_database.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# ========================================================================
# КОНСТАНТЫ И СЛОВАРИ
# ========================================================================
RARITY_COLORS = {
    "Basic": "gray",
    "Uncommon": "green",
    "Rare": "deepskyblue",
    "Epic": "purple",
    "Legendary": "gold",
    "Mythic": "red",
    "Godly": "white",
    "Secret": "black",
    "Exclusive": "cyan"
}

CLASSES = ["AOE", "Splash", "Booster", "Single", "Fire"]

# ========================================================================
# БАЗА ДАННЫХ И СМАРТ-МИГРАЦИИ
# ========================================================================
async def get_db_connection():
    db = await aiosqlite.connect(DB_NAME)
    db.row_factory = aiosqlite.Row
    return db

async def execute_db(query, params=()):
    db = await get_db_connection()
    try:
        await db.execute(query, params)
        await db.commit()
    finally:
        await db.close()

async def fetch_one(query, params=()):
    db = await get_db_connection()
    try:
        async with db.execute(query, params) as cursor:
            result = await cursor.fetchone()
            return dict(result) if result else None
    finally:
        await db.close()

async def fetch_all(query, params=()):
    db = await get_db_connection()
    try:
        async with db.execute(query, params) as cursor:
            result = await cursor.fetchall()
            return [dict(row) for row in result]
    finally:
        await db.close()

async def check_and_update_schema():
    """Умная проверка БД. Если админ закинул старую БД, бот сам добавит нужные колонки."""
    db = await get_db_connection()
    try:
        # Таблица users
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                coins INTEGER DEFAULT 0,
                trophies INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                last_getcard REAL DEFAULT 0,
                equip1 INTEGER DEFAULT 0,
                equip2 INTEGER DEFAULT 0,
                equip3 INTEGER DEFAULT 0
            )
        """)
        
        # Таблица cards (шанс теперь полностью кастомный, редкость - косметика)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                rarity TEXT,
                class_type TEXT,
                damage INTEGER,
                hp INTEGER,
                drop_chance REAL,
                photo_id TEXT
            )
        """)
        
        # Таблица inventory
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_id INTEGER,
                count INTEGER DEFAULT 1
            )
        """)
        
        # Таблица ranks (настройки сложности боев)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ranks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                min_trophies INTEGER,
                difficulty_mult REAL DEFAULT 1.0,
                reward_mult REAL DEFAULT 1.0
            )
        """)
        
        # Таблица настроек сервера (ивенты, награды)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS server_settings (
                id INTEGER PRIMARY KEY,
                min_coins INTEGER DEFAULT 50,
                max_coins INTEGER DEFAULT 200,
                luck_mult REAL DEFAULT 1.0,
                luck_end REAL DEFAULT 0,
                cd_mult REAL DEFAULT 1.0,
                cd_end REAL DEFAULT 0
            )
        """)
        
        # Таблица логов админов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Таблица админов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        
        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        await db.execute("INSERT OR IGNORE INTO server_settings (id) VALUES (1)")
        
        # Инициализация дефолтных рангов, если их нет
        ranks = await db.execute("SELECT COUNT(*) FROM ranks")
        count = await ranks.fetchone()
        if count[0] == 0:
            default_ranks = [
                ("Новичок", 0, 0.8, 1.0),
                ("Бронза", 100, 1.0, 1.2),
                ("Серебро", 250, 1.3, 1.5),
                ("Золото", 500, 1.6, 2.0),
                ("Платина", 1000, 2.0, 2.5),
                ("Алмаз", 1250, 2.5, 3.0),
                ("Мастер", 2000, 3.5, 4.0)
            ]
            for r in default_ranks:
                await db.execute("INSERT INTO ranks (name, min_trophies, difficulty_mult, reward_mult) VALUES (?, ?, ?, ?)", r)

        await db.commit()
    finally:
        await db.close()

# ========================================================================
# МАШИНА СОСТОЯНИЙ (FSM)
# ========================================================================
class AddCard(StatesGroup):
    photo = State()
    name = State()
    drop_chance = State()
    rarity = State()
    class_type = State()
    damage = State()
    hp = State()

class DelCard(StatesGroup):
    card_id = State()

class SetupRank(StatesGroup):
    name = State()
    min_trophies = State()
    diff_mult = State()
    reward_mult = State()

class DuelState(StatesGroup):
    waiting_accept = State()

# ========================================================================
# УТИЛИТЫ И ХЕЛПЕРЫ
# ========================================================================
async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID: return True
    res = await fetch_one("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return bool(res)

async def check_ban(user_id: int) -> bool:
    res = await fetch_one("SELECT banned FROM users WHERE id = ?", (user_id,))
    return bool(res and res['banned'] == 1)

async def log_admin(admin_id: int, action: str):
    await execute_db("INSERT INTO admin_logs (admin_id, action) VALUES (?, ?)", (admin_id, action))

def get_main_keyboard(is_adm: bool = False):
    kb = [
        [KeyboardButton(text="🎴 Выбить карту"), KeyboardButton(text="⚔️ Поиск боя (боты)")],
        [KeyboardButton(text="🎒 Инвентарь"), KeyboardButton(text="🛡 Экипировка")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏆 Топ игроков")],
        [KeyboardButton(text="📖 Индекс")]
    ]
    if is_adm:
        kb.append([KeyboardButton(text="➕ Добавить карту"), KeyboardButton(text="🗑 Удалить карту")])
        kb.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_user_rank(trophies: int):
    ranks = await fetch_all("SELECT * FROM ranks ORDER BY min_trophies DESC")
    for r in ranks:
        if trophies >= r['min_trophies']:
            return r
    return {"name": "Без ранга", "difficulty_mult": 1.0, "reward_mult": 1.0}

async def get_active_events():
    settings = await fetch_one("SELECT * FROM server_settings WHERE id = 1")
    now = time.time()
    
    luck = settings['luck_mult'] if settings['luck_end'] > now else 1.0
    cd = settings['cd_mult'] if settings['cd_end'] > now else 1.0
    
    return luck, cd

async def create_bordered_image(bot: Bot, photo_id: str, rarity: str) -> str:
    """Скачивает фото, рисует рамку по редкости и загружает обратно"""
    color = RARITY_COLORS.get(rarity, "gray")
    
    file = await bot.get_file(photo_id)
    file_bytes = await bot.download_file(file.file_path)
    
    img = Image.open(file_bytes).convert("RGB")
    bordered_img = ImageOps.expand(img, border=20, fill=color)
    
    bio = io.BytesIO()
    bordered_img.save(bio, format='JPEG')
    bio.seek(0)
    
    msg = await bot.send_photo(chat_id=SUPER_ADMIN_ID, photo=types.BufferedInputFile(bio.read(), filename="card.jpg"), caption=f"Сгенерирована рамка: {rarity}")
    return msg.photo[-1].file_id

# ========================================================================
# ОСНОВНЫЕ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ
# ========================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if await check_ban(message.from_user.id): return
    await execute_db("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (message.from_user.id, message.from_user.username))
    await execute_db("UPDATE users SET username = ? WHERE id = ?", (message.from_user.username, message.from_user.id))
    
    adm = await is_admin(message.from_user.id)
    await message.answer(
        "👋 <b>Добро пожаловать в Card Battle Bot!</b>\n\n"
        "Собери свою колоду уникальных юнитов, выставляй их в бой и поднимай кубки!\n\n"
        "Используй меню снизу для навигации или нажми /help для списка команд.",
        reply_markup=get_main_keyboard(adm)
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if await check_ban(message.from_user.id): return
    text = (
        "📖 <b>Помощь по командам:</b>\n"
        "/start - Перезапуск бота и вызов меню\n"
        "/help - Это сообщение\n"
        "/getcard - Выбить случайную карту (КД 8 минут)\n"
        "/inventory - Ваш инвентарь юнитов\n"
        "/equip - Настройка боевой колоды\n"
        "/duel - Вызвать игрока на бой (ТОЛЬКО В ГРУППАХ)\n"
        "/top - Топ 20 игроков по кубкам\n"
        "/index - Энциклопедия всех существующих карт\n"
        "/profile - Посмотреть свой профиль\n"
    )
    if await is_admin(message.from_user.id):
        text += (
            "\n👑 <b>Команды Админа:</b>\n"
            "/bd - Загрузить бэкап (.db файл)\n"
            "/ban [ID] - Бан\n"
            "/unban [ID] - Разбан\n"
            "/gettrophies [ID] [Кол-во] - Выдать кубки\n"
            "/addadmin [ID] - Выдать админку\n"
            "/deladmin [ID] - Снять админку\n"
            "/luckevent [Множитель] [Минуты] - Ивент удачи\n"
            "/cooldownevent [Множитель] [Минуты] - Ивент КД"
        )
    await message.answer(text)

@dp.message(Command("profile"), F.chat.type == "private")
@dp.message(F.text == "👤 Профиль")
async def cmd_profile(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    rank = await get_user_rank(user['trophies'])
    total_cards = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE user_id = ?", (user['id'],))
    
    text = (
        f"👤 <b>Профиль игрока {user['username'] or user['id']}</b>\n\n"
        f"🎖 <b>Ранг:</b> {rank['name']}\n"
        f"🏆 <b>Кубки:</b> {user['trophies']}\n"
        f"💰 <b>Монеты:</b> {user['coins']}\n"
        f"🃏 <b>Всего карт:</b> {total_cards['s'] or 0}\n\n"
        f"⚔️ <b>Экипировка:</b>\n"
    )
    
    for i, slot in enumerate(['equip1', 'equip2', 'equip3'], 1):
        if user[slot] != 0:
            card = await fetch_one("SELECT name, damage, hp FROM cards WHERE id = ?", (user[slot],))
            if card:
                text += f"{i}. <b>{card['name']}</b> (⚔️{card['damage']} | ❤️{card['hp']})\n"
            else:
                text += f"{i}. [Пусто]\n"
        else:
            text += f"{i}. [Пусто]\n"
            
    await message.answer(text)

@dp.message(Command("top"))
@dp.message(F.text == "🏆 Топ игроков")
async def cmd_top(message: types.Message):
    if await check_ban(message.from_user.id): return
    top_users = await fetch_all("SELECT username, id, trophies FROM users ORDER BY trophies DESC LIMIT 20")
    
    text = "🏆 <b>Топ 20 игроков сервера:</b>\n\n"
    for i, u in enumerate(top_users, 1):
        name = u['username'] or f"ID: {u['id']}"
        text += f"{i}. {name} — <b>{u['trophies']} 🏆</b>\n"
        
    await message.answer(text)

# ========================================================================
# СИСТЕМА ГАЧИ (ВЫБИВАНИЕ КАРТ)
# ========================================================================
@dp.message(Command("getcard"))
@dp.message(F.text == "🎴 Выбить карту")
async def cmd_getcard(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    luck_mult, cd_mult = await get_active_events()
    base_cooldown = 8 * 60
    actual_cooldown = int(base_cooldown / cd_mult)
    
    now = time.time()
    passed = now - user['last_getcard']
    
    if passed < actual_cooldown:
        left = int(actual_cooldown - passed)
        mins, secs = divmod(left, 60)
        return await message.answer(f"⏳ <b>Колода перемешивается!</b>\nВозвращайся через {mins} мин. {secs} сек.")
        
    all_cards = await fetch_all("SELECT * FROM cards")
    if not all_cards:
        return await message.answer("😔 В базе пока нет карт. Пните админа!")
        
    # Логика выпадения берет шансы ПРЯМО из базы (как мы их настроили)
    weights = []
    for c in all_cards:
        chance = c['drop_chance']
        # Удача немного повышает шанс карт, чей шанс ниже 15%
        if chance < 15.0:
            chance *= luck_mult
        weights.append(chance)
        
    won_card = random.choices(all_cards, weights=weights, k=1)[0]
    
    inv_item = await fetch_one("SELECT id FROM inventory WHERE user_id = ? AND card_id = ?", (user['id'], won_card['id']))
    if inv_item:
        await execute_db("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
    else:
        await execute_db("INSERT INTO inventory (user_id, card_id) VALUES (?, ?)", (user['id'], won_card['id']))
        
    await execute_db("UPDATE users SET last_getcard = ? WHERE id = ?", (now, user['id']))
    
    msg = (
        f"🎉 <b>ПОЗДРАВЛЯЕМ! ВЫ ВЫБИЛИ КАРТУ!</b>\n\n"
        f"🃏 <b>Имя:</b> {won_card['name']}\n"
        f"💎 <b>Редкость:</b> {won_card['rarity']}\n"
        f"⚔️ <b>Урон:</b> {won_card['damage']} | ❤️ <b>Здоровье:</b> {won_card['hp']}\n"
        f"🔮 <b>Класс:</b> {won_card['class_type']}\n\n"
    )
    if luck_mult > 1.0:
        msg += f"🍀 <i>Сработал ивент удачи (x{luck_mult})!</i>"
        
    await message.answer_photo(photo=won_card['photo_id'], caption=msg)

# ========================================================================
# ИНДЕКС И ИНВЕНТАРЬ
# ========================================================================
@dp.message(Command("index"))
@dp.message(F.text == "📖 Индекс")
async def cmd_index(message: types.Message):
    if await check_ban(message.from_user.id): return
    all_cards = await fetch_all("SELECT * FROM cards ORDER BY drop_chance DESC")
    user_inv = await fetch_all("SELECT card_id FROM inventory WHERE user_id = ?", (message.from_user.id,))
    user_card_ids = [item['card_id'] for item in user_inv]
    
    if not all_cards:
        return await message.answer("Индекс пуст.")
        
    text = "📖 <b>Мировой Индекс Карт:</b>\n\n"
    for i, c in enumerate(all_cards, 1):
        exists = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE card_id = ?", (c['id'],))
        total_exists = exists['s'] if exists and exists['s'] else 0
        
        if c['id'] in user_card_ids:
            text += f"{i}. <b>{c['name']}</b>\n"
            text += f"💎 Редкость: {c['rarity']} // Шанс: {c['drop_chance']}%\n"
            text += f"⚔️ Урон: {c['damage']} // ❤️ Здоровье: {c['hp']}\n"
            text += f"🌍 Существует в мире: {total_exists} шт.\n\n"
        else:
            text += f"{i}. <b>???</b>\n"
            text += f"💎 Редкость: {c['rarity']} // Шанс: {c['drop_chance']}%\n"
            text += f"⚔️ Урон: ??? // ❤️ Здоровье: ???\n"
            text += f"🌍 Существует в мире: {total_exists} шт.\n\n"
            
    for x in range(0, len(text), 4000):
        await message.answer(text[x:x+4000])

@dp.message(Command("inventory"))
@dp.message(F.text == "🎒 Инвентарь")
async def cmd_inventory(message: types.Message):
    if await check_ban(message.from_user.id): return
    inv = await fetch_all("""
        SELECT c.id, c.name, c.rarity, c.class_type, i.count 
        FROM inventory i 
        JOIN cards c ON i.card_id = c.id 
        WHERE i.user_id = ?
    """, (message.from_user.id,))
    
    if not inv:
        return await message.answer("🎒 Ваш инвентарь пуст. Используйте /getcard")
        
    text = "🎒 <b>Ваш Инвентарь:</b>\n\n"
    for item in inv:
        text += f"[{item['id']}] <b>{item['name']}</b> ({item['rarity']}) — {item['count']} шт.\n"
        
    text += "\n<i>Используйте ID карты (в квадратных скобках) для экипировки.</i>"
    
    for x in range(0, len(text), 4000):
        await message.answer(text[x:x+4000])

# ========================================================================
# ЭКИПИРОВКА
# ========================================================================
def equip_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Слот 1", callback_data="equip_slot_1"),
         InlineKeyboardButton(text="Слот 2", callback_data="equip_slot_2"),
         InlineKeyboardButton(text="Слот 3", callback_data="equip_slot_3")],
        [InlineKeyboardButton(text="❌ Снять всё", callback_data="equip_clear")]
    ])

@dp.message(Command("equip"))
@dp.message(F.text == "🛡 Экипировка")
async def cmd_equip(message: types.Message):
    if await check_ban(message.from_user.id): return
    await message.answer("🛡 <b>Настройка Боевой Колоды</b>\n\nВыберите слот, который хотите изменить:", reply_markup=equip_keyboard())

@dp.callback_query(F.data.startswith("equip_slot_"))
async def equip_slot_callback(callback: types.CallbackQuery, state: FSMContext):
    slot_num = callback.data.split("_")[2]
    await callback.message.answer(f"Отправьте мне <b>ID карты</b> из инвентаря, чтобы поместить её в Слот {slot_num}:")
    await state.update_data(equip_target_slot=slot_num)
    await state.set_state("waiting_for_equip_id")
    await callback.answer()

@dp.message(StateFilter("waiting_for_equip_id"))
async def process_equip_id(message: types.Message, state: FSMContext):
    try:
        card_id = int(message.text)
    except ValueError:
        return await message.answer("❌ ID должен быть числом.")
        
    has_card = await fetch_one("SELECT * FROM inventory WHERE user_id = ? AND card_id = ?", (message.from_user.id, card_id))
    if not has_card:
        await state.clear()
        return await message.answer("❌ У вас нет этой карты в инвентаре.")
        
    data = await state.get_data()
    slot = f"equip{data['equip_target_slot']}"
    
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (message.from_user.id,))
    if card_id in [user['equip1'], user['equip2'], user['equip3']]:
        await state.clear()
        return await message.answer("❌ Эта карта уже экипирована в другом слоте!")
    
    await execute_db(f"UPDATE users SET {slot} = ? WHERE id = ?", (card_id, message.from_user.id))
    
    card = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
    await message.answer(f"✅ Карта <b>{card['name']}</b> успешно экипирована в Слот {data['equip_target_slot']}!")
    await state.clear()

@dp.callback_query(F.data == "equip_clear")
async def equip_clear_callback(callback: types.CallbackQuery):
    await execute_db("UPDATE users SET equip1=0, equip2=0, equip3=0 WHERE id = ?", (callback.from_user.id,))
    await callback.message.edit_text("✅ Все слоты экипировки очищены.")
    await callback.answer()

# ========================================================================
# БОЕВАЯ СИСТЕМА (ДВИЖОК БОЯ С ПОЛНОЙ ЛОГИКОЙ КЛАССОВ)
# ========================================================================
async def get_team_data(user_id: int):
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (user_id,))
    team = []
    for slot in ['equip1', 'equip2', 'equip3']:
        if user[slot] != 0:
            card = await fetch_one("SELECT id, name, damage, hp, class_type FROM cards WHERE id = ?", (user[slot],))
            if card:
                card['max_hp'] = card['hp']
                card['burn'] = 0     # Урон от горения (сработает в следующий тик)
                card['dmg_buff'] = 0 # Буст урона
                team.append(card)
    return team

async def get_bot_team(difficulty_mult: float):
    all_cards = await fetch_all("SELECT id, name, damage, hp, class_type FROM cards")
    if len(all_cards) < 3: return []
    
    team = random.sample(all_cards, 3)
    for c in team:
        c['damage'] = int(c['damage'] * difficulty_mult)
        c['hp'] = int(c['hp'] * difficulty_mult)
        c['max_hp'] = c['hp']
        c['burn'] = 0
        c['dmg_buff'] = 0
    return team

def format_card_hp(c):
    status = ""
    if c.get('burn', 0) > 0: status += "🔥"
    if c.get('dmg_buff', 0) > 0: status += "✨"
    return f"{c['name']}{status} (❤️{c['hp']}/{c['max_hp']})"

def build_battle_header(p1_name, t1, p2_name, t2):
    t1_text = " | ".join([format_card_hp(c) for c in t1])
    t2_text = " | ".join([format_card_hp(c) for c in t2])
    
    return (
        f"⚔️ <b>БИТВА НАЧАЛАСЬ</b> ⚔️\n\n"
        f"🔵 <b>Команда {p1_name}:</b>\n{t1_text or 'Все мертвы'}\n\n"
        f"🔴 <b>Команда {p2_name}:</b>\n{t2_text or 'Все мертвы'}\n\n"
        f"📜 <b>Лог боя:</b>\n"
    )

async def process_burns(team, team_name, log):
    """Срабатывает в начале хода команды: наносит урон от горения, которое было повешено в прошлый тик"""
    for c in team:
        if c['hp'] > 0 and c.get('burn', 0) > 0:
            c['hp'] -= c['burn']
            log_str = f"🔥 {team_name}: <b>{c['name']}</b> получает {c['burn']} урона от горения!"
            if c['hp'] <= 0:
                c['hp'] = 0
                log_str += " ☠️ <i>Сгорел дотла!</i>"
            log.append(log_str)
            c['burn'] = 0 # Горение спадает после 1 тика (как в ТЗ)

async def execute_turn(atk_team, def_team, atk_name, def_name, log):
    """Выполняет один ход (одна карта атакует). Возвращает True если кто-то походил, иначе False"""
    await process_burns(atk_team, atk_name, log)
    
    atk_alive = [c for c in atk_team if c['hp'] > 0]
    def_alive = [c for c in def_team if c['hp'] > 0]
    
    if not atk_alive or not def_alive: return False
    
    atk = random.choice(atk_alive)
    base_dmg = atk['damage'] + atk.get('dmg_buff', 0)
    c_type = atk['class_type']
    
    if c_type == "AOE":
        log_str = f"🌪 {atk_name}: <b>{atk['name']}</b> (AOE) бьет по всем на {base_dmg}!"
        for d in def_alive:
            d['hp'] -= base_dmg
            if d['hp'] <= 0: d['hp'] = 0; log_str += f" ☠️ <i>{d['name']} мертв!</i>"
        log.append(log_str)
        
    elif c_type == "Splash":
        main_t = random.choice(def_alive)
        splash_dmg = int(base_dmg * 0.5)
        log_str = f"🌊 {atk_name}: <b>{atk['name']}</b> (Splash) наносит {base_dmg} по <b>{main_t['name']}</b> и {splash_dmg} остальным!"
        for d in def_alive:
            dmg = base_dmg if d == main_t else splash_dmg
            d['hp'] -= dmg
            if d['hp'] <= 0: d['hp'] = 0; log_str += f" ☠️ <i>{d['name']} мертв!</i>"
        log.append(log_str)
        
    elif c_type == "Booster":
        # Booster: Баффает всей своей команде урон и ХП
        log_str = f"✨ {atk_name}: <b>{atk['name']}</b> (Booster) усиливает команду! (+{base_dmg} Урон/ХП)"
        for a in atk_alive:
            a['hp'] += base_dmg
            a['max_hp'] += base_dmg
            a['dmg_buff'] = a.get('dmg_buff', 0) + base_dmg
        log.append(log_str)
        
    elif c_type == "Fire":
        # Fire: наносит урон сейчас и вешает такой же урон на следующий тик (через burn)
        target = random.choice(def_alive)
        target['hp'] -= base_dmg
        target['burn'] = target.get('burn', 0) + base_dmg
        log_str = f"🔥 {atk_name}: <b>{atk['name']}</b> (Fire) бьет <b>{target['name']}</b> на {base_dmg} и поджигает его!"
        if target['hp'] <= 0:
            target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
        log.append(log_str)
        
    else: # Single (по умолчанию)
        target = random.choice(def_alive)
        target['hp'] -= base_dmg
        log_str = f"🎯 {atk_name}: <b>{atk['name']}</b> наносит {base_dmg} по <b>{target['name']}</b>!"
        if target['hp'] <= 0:
            target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
        log.append(log_str)
        
    return True

async def run_battle_loop(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_id: int, p2_name: str, t1: list, t2: list, is_pvp: bool = False):
    msg = await bot.send_message(chat_id, f"⚔️ Бой между <b>{p1_name}</b> и <b>{p2_name}</b> начнется через 3 секунды!")
    await asyncio.sleep(1)
    await msg.edit_text(f"⚔️ Бой между <b>{p1_name}</b> и <b>{p2_name}</b> начнется через 2 секунды!")
    await asyncio.sleep(1)
    await msg.edit_text(f"⚔️ Бой между <b>{p1_name}</b> и <b>{p2_name}</b> начнется через 1 секунду!")
    await asyncio.sleep(1)

    turn = 1
    log = []
    
    while True:
        # Проверка на победу (До горения)
        t1_alive = [c for c in t1 if c['hp'] > 0]
        t2_alive = [c for c in t2 if c['hp'] > 0]
        
        if not t1_alive and not t2_alive:
            winner = "Ничья"
            break
        elif not t1_alive:
            winner = p2_name
            winner_id = p2_id
            loser_id = p1_id
            break
        elif not t2_alive:
            winner = p1_name
            winner_id = p1_id
            loser_id = p2_id
            break
            
        if turn > 30:
            winner = "Ничья по таймауту"
            break

        # Тик Команды 1
        did_turn = await execute_turn(t1, t2, p1_name, p2_name, log)
        if did_turn:
            if len(log) > 6: log = log[-6:] # Храним только последние действия
            await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
            await asyncio.sleep(4)

        # Тик Команды 2 (Только если Команда 2 еще жива после удара Команды 1)
        t2_alive = [c for c in t2 if c['hp'] > 0]
        if t2_alive:
            did_turn = await execute_turn(t2, t1, p2_name, p1_name, log)
            if did_turn:
                if len(log) > 6: log = log[-6:]
                await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
                await asyncio.sleep(4)
        
        turn += 1

    # Итоги боя
    final_text = build_battle_header(p1_name, t1, p2_name, t2)
    final_text += f"\n\n🏁 <b>БОЙ ОКОНЧЕН! Победитель: {winner}</b>"
    
    settings = await fetch_one("SELECT * FROM server_settings WHERE id = 1")
    if is_pvp:
        if winner != "Ничья" and winner != "Ничья по таймауту":
            await execute_db("UPDATE users SET trophies = trophies + 15 WHERE id = ?", (winner_id,))
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 10) WHERE id = ?", (loser_id,))
            final_text += f"\nПобедитель получает +15 🏆\nПроигравший теряет -10 🏆"
    else:
        if winner == p1_name:
            user = await fetch_one("SELECT trophies FROM users WHERE id = ?", (p1_id,))
            rank = await get_user_rank(user['trophies'])
            
            coins_won = random.randint(settings['min_coins'], settings['max_coins'])
            coins_won = int(coins_won * rank['reward_mult'])
            
            await execute_db("UPDATE users SET coins = coins + ?, trophies = trophies + 5 WHERE id = ?", (coins_won, p1_id))
            final_text += f"\n🎉 Вы получили: <b>{coins_won} 💰</b> и <b>5 🏆</b>"
        elif winner == p2_name:
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 2) WHERE id = ?", (p1_id,))
            final_text += f"\n💀 Вы проиграли и потеряли 2 🏆."
            
    await msg.edit_text(final_text)

@dp.message(F.text == "⚔️ Поиск боя (боты)")
async def cmd_pve_battle(message: types.Message):
    if await check_ban(message.from_user.id): return
    team1 = await get_team_data(message.from_user.id)
    if not team1:
        return await message.answer("❌ У вас не экипировано ни одной карты! Зайдите в /equip")
        
    user = await fetch_one("SELECT trophies FROM users WHERE id = ?", (message.from_user.id,))
    rank = await get_user_rank(user['trophies'])
    
    team2 = await get_bot_team(rank['difficulty_mult'])
    if not team2:
        return await message.answer("❌ На сервере недостаточно карт для создания команды бота.")
        
    p1_name = message.from_user.username or "Игрок"
    p2_name = f"ИИ ({rank['name']})"
    
    asyncio.create_task(run_battle_loop(bot, message.chat.id, message.from_user.id, p1_name, 0, p2_name, team1, team2, is_pvp=False))

# ========================================================================
# ДУЭЛИ (PvP В ГРУППАХ)
# ========================================================================
active_duels = {}

@dp.message(Command("duel"))
async def cmd_duel(message: types.Message):
    if message.chat.type not in ["group", "supergroup"]:
        return await message.answer("❌ Дуэли доступны только в группах!")
        
    if not message.reply_to_message:
        return await message.answer("❌ Чтобы вызвать игрока, ответьте на его сообщение командой /duel")
        
    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id or target_id == bot.id:
        return await message.answer("❌ Нельзя вызвать самого себя или бота.")
        
    team1 = await get_team_data(message.from_user.id)
    if not team1:
        return await message.answer("❌ У вас не экипированы карты!")
        
    team2 = await get_team_data(target_id)
    if not team2:
        return await message.answer("❌ У противника не экипированы карты!")
        
    duel_id = f"{message.from_user.id}_{target_id}_{time.time()}"
    active_duels[duel_id] = {
        "p1_id": message.from_user.id,
        "p1_name": message.from_user.username or "Игрок 1",
        "p2_id": target_id,
        "p2_name": message.reply_to_message.from_user.username or "Игрок 2",
        "t1": team1,
        "t2": team2
    }
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ ПРИНЯТЬ ВЫЗОВ", callback_data=f"accept_duel_{duel_id}")]
    ])
    
    await message.answer(f"🥊 Игрок {active_duels[duel_id]['p1_name']} вызывает {active_duels[duel_id]['p2_name']} на карточную дуэль!\n\nНажмите кнопку ниже, чтобы начать.", reply_markup=kb)

@dp.callback_query(F.data.startswith("accept_duel_"))
async def accept_duel_callback(callback: types.CallbackQuery):
    duel_id = callback.data.replace("accept_duel_", "")
    if duel_id not in active_duels:
        return await callback.answer("Дуэль устарела или не существует.", show_alert=True)
        
    duel = active_duels[duel_id]
    if callback.from_user.id != duel['p2_id']:
        return await callback.answer("Этот вызов не для вас!", show_alert=True)
        
    await callback.message.delete()
    del active_duels[duel_id]
    
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, duel['p1_id'], duel['p1_name'], duel['p2_id'], duel['p2_name'], duel['t1'], duel['t2'], is_pvp=True))

# ========================================================================
# ПАНЕЛЬ АДМИНИСТРАТОРА
# ========================================================================
@dp.message(F.text == "⚙️ Админ-панель")
@dp.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id): return
    
    text = (
        "⚙️ <b>Панель Администратора</b>\n\n"
        "Быстрые команды:\n"
        "/bd - Бэкап и Восстановление БД\n"
        "/luckevent [Множитель] [Мин]\n"
        "/cooldownevent [Множитель] [Мин]\n"
        "/gettrophies [ID] [Кол-во]\n"
        "/ban [ID] и /unban [ID]"
    )
    await message.answer(text)

# ИВЕНТЫ
@dp.message(Command("luckevent"))
async def cmd_luck_event(message: types.Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 3: return await message.answer("Формат: /luckevent 2.0 60 (х2 удача на 60 минут)")
    
    mult = float(args[1])
    mins = int(args[2])
    end_time = time.time() + (mins * 60)
    
    await execute_db("UPDATE server_settings SET luck_mult = ?, luck_end = ? WHERE id = 1", (mult, end_time))
    await log_admin(message.from_user.id, f"luckevent {mult}x {mins}m")
    await message.answer(f"✅ Ивент УДАЧИ (x{mult}) запущен на {mins} минут!")

@dp.message(Command("cooldownevent"))
async def cmd_cd_event(message: types.Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 3: return await message.answer("Формат: /cooldownevent 2.0 60 (кд быстрее в 2 раза на 60 мин)")
    
    mult = float(args[1])
    mins = int(args[2])
    end_time = time.time() + (mins * 60)
    
    await execute_db("UPDATE server_settings SET cd_mult = ?, cd_end = ? WHERE id = 1", (mult, end_time))
    await log_admin(message.from_user.id, f"cdevent {mult}x {mins}m")
    await message.answer(f"✅ Ивент ПЕРЕЗАРЯДКИ (x{mult} быстрее) запущен на {mins} минут!")

# УПРАВЛЕНИЕ ИГРОКАМИ
@dp.message(Command("ban"))
async def cmd_ban(message: types.Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2: return await message.answer("Формат: /ban [ID]")
    
    await execute_db("UPDATE users SET banned = 1 WHERE id = ?", (int(args[1]),))
    await log_admin(message.from_user.id, f"ban {args[1]}")
    await message.answer(f"✅ Игрок {args[1]} забанен.")

@dp.message(Command("unban"))
async def cmd_unban(message: types.Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2: return await message.answer("Формат: /unban [ID]")
    
    await execute_db("UPDATE users SET banned = 0 WHERE id = ?", (int(args[1]),))
    await log_admin(message.from_user.id, f"unban {args[1]}")
    await message.answer(f"✅ Игрок {args[1]} разбанен.")

@dp.message(Command("gettrophies"))
async def cmd_give_cups(message: types.Message):
    if not await is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 3: return await message.answer("Формат: /gettrophies [ID] [Кол-во]")
    
    await execute_db("UPDATE users SET trophies = trophies + ? WHERE id = ?", (int(args[2]), int(args[1])))
    await log_admin(message.from_user.id, f"gettrophies {args[2]} to {args[1]}")
    await message.answer(f"✅ Игроку {args[1]} выдано {args[2]} кубков.")

# АДМИНЫ
@dp.message(Command("addadmin"))
async def cmd_addadm(message: types.Message):
    if message.from_user.id != SUPER_ADMIN_ID: return
    args = message.text.split()
    await execute_db("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (int(args[1]),))
    await message.answer("✅ Админ добавлен.")

@dp.message(Command("deladmin"))
async def cmd_deladm(message: types.Message):
    if message.from_user.id != SUPER_ADMIN_ID: return
    args = message.text.split()
    await execute_db("DELETE FROM admins WHERE user_id = ?", (int(args[1]),))
    await message.answer("✅ Админ удален.")

# БЭКАПЫ БД
@dp.message(Command("bd"))
async def cmd_bd(message: types.Message):
    if not await is_admin(message.from_user.id): return
    file = FSInputFile(DB_NAME)
    await message.answer_document(file, caption="📦 Текущая БД. Скиньте сюда новый .db файл чтобы восстановить/заменить.")

@dp.message(F.document)
async def process_bd_upload(message: types.Message):
    if not await is_admin(message.from_user.id): return
    if not message.document.file_name.endswith(".db"): return
    
    file = await bot.get_file(message.document.file_id)
    await bot.download_file(file.file_path, DB_NAME)
    
    await check_and_update_schema()
    await log_admin(message.from_user.id, "DB Upload and Migration")
    
    await message.answer("✅ <b>База данных успешно загружена и обновлена до последней структуры!</b>")

# ========================================================================
# ДОБАВЛЕНИЕ И УДАЛЕНИЕ КАРТ (FSM)
# ========================================================================
@dp.message(F.text == "➕ Добавить карту")
async def cmd_add_card_start(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    await message.answer("Отправь фото карты:")
    await state.set_state(AddCard.photo)

@dp.message(AddCard.photo, F.photo)
async def add_card_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("Введи название:")
    await state.set_state(AddCard.name)

@dp.message(AddCard.name)
async def add_card_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введи шанс выпадения (число, например 15.5):")
    await state.set_state(AddCard.drop_chance)

@dp.message(AddCard.drop_chance)
async def add_card_chance(message: types.Message, state: FSMContext):
    try:
        chance = float(message.text)
        await state.update_data(drop_chance=chance)
        
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=r)] for r in RARITY_COLORS.keys()], resize_keyboard=True)
        await message.answer("Выбери редкость (только для цвета рамки):", reply_markup=kb)
        await state.set_state(AddCard.rarity)
    except ValueError:
        await message.answer("Должно быть число!")

@dp.message(AddCard.rarity)
async def add_card_rarity(message: types.Message, state: FSMContext):
    if message.text not in RARITY_COLORS:
        return await message.answer("Выбери с клавиатуры.")
    await state.update_data(rarity=message.text)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c)] for c in CLASSES], resize_keyboard=True)
    await message.answer("Выбери тип (класс):", reply_markup=kb)
    await state.set_state(AddCard.class_type)

@dp.message(AddCard.class_type)
async def add_card_class(message: types.Message, state: FSMContext):
    if message.text not in CLASSES:
        return await message.answer("Выбери с клавиатуры.")
    await state.update_data(class_type=message.text)
    await message.answer("Введи урон (целое число):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AddCard.damage)

@dp.message(AddCard.damage)
async def add_card_dmg(message: types.Message, state: FSMContext):
    try:
        await state.update_data(damage=int(message.text))
        await message.answer("Введи здоровье (хп):")
        await state.set_state(AddCard.hp)
    except ValueError:
        await message.answer("Должно быть число!")

@dp.message(AddCard.hp)
async def add_card_finish(message: types.Message, state: FSMContext):
    try:
        hp = int(message.text)
        data = await state.get_data()
        
        await message.answer("⏳ Генерирую рамку редкости для карты, подождите...")
        
        new_photo_id = await create_bordered_image(bot, data['photo'], data['rarity'])
        
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (data['name'], data['rarity'], data['class_type'], data['damage'], hp, data['drop_chance'], new_photo_id)
        )
        await log_admin(message.from_user.id, f"Added card {data['name']}")
        
        await message.answer_photo(
            photo=new_photo_id,
            caption=f"✅ <b>Карта успешно создана!</b>\n\nИмя: {data['name']}\nРедкость (косметика): {data['rarity']} | Шанс: {data['drop_chance']}%\nУрон: {data['damage']} | ХП: {hp}",
            reply_markup=get_main_keyboard(True)
        )
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")
        await state.clear()

@dp.message(F.text == "🗑 Удалить карту")
async def cmd_del_card_start(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    await message.answer("Отправь ID карты для удаления (Посмотри в /index):")
    await state.set_state(DelCard.card_id)

@dp.message(DelCard.card_id)
async def cmd_del_card_finish(message: types.Message, state: FSMContext):
    try:
        c_id = int(message.text)
        await execute_db("DELETE FROM cards WHERE id = ?", (c_id,))
        await execute_db("DELETE FROM inventory WHERE card_id = ?", (c_id,))
        for slot in ['equip1', 'equip2', 'equip3']:
            await execute_db(f"UPDATE users SET {slot} = 0 WHERE {slot} = ?", (c_id,))
            
        await log_admin(message.from_user.id, f"Deleted card ID {c_id}")
        await message.answer(f"✅ Карта {c_id} удалена отовсюду.")
    except ValueError:
        await message.answer("❌ Нужно число.")
    await state.clear()

# ========================================================================
# ЗАПУСК БОТА
# ========================================================================
async def main():
    await check_and_update_schema()
    
    commands = [
        BotCommand(command="start", description="Главное меню / Старт"),
        BotCommand(command="help", description="Помощь по командам"),
        BotCommand(command="getcard", description="Выбить карту (Гача)"),
        BotCommand(command="inventory", description="Инвентарь карт"),
        BotCommand(command="equip", description="Экипировка колоды"),
        BotCommand(command="profile", description="Профиль и статы"),
        BotCommand(command="index", description="Индекс всех карт"),
        BotCommand(command="top", description="Лидерборд"),
    ]
    await bot.set_my_commands(commands)
    
    logging.info("🤖 Карточный бот с новыми классами запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
