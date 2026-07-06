import asyncio
import logging
import random
import time
import io
import os
import math
from datetime import datetime

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile, BotCommand
)
from aiogram.exceptions import TelegramAPIError

try:
    from PIL import Image, ImageOps, ImageDraw
except ImportError:
    raise ImportError("Установите Pillow: pip install Pillow")

import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА
# ========================================================================
BOT_TOKEN = "7725898870:AAGWJxQSpNOF1GDtw3XaNM93MzE6WJZrxms"
SUPER_ADMIN_ID = 5341904332
DB_NAME = "cards_database.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# ========================================================================
# КОНСТАНТЫ И СЛОВАРИ С ЭМОДЗИ
# ========================================================================
RARITY_COLORS = {
    "Basic": "gray",
    "Uncommon": "green",
    "Rare": "deepskyblue",
    "Epic": "purple",
    "Legendary": "gold",
    "Mythic": "red",
    "Super": "rainbow",
    "Exclusive": "lightpink",
    "Leaderboard": "cyan" 
}

RARITY_EMOJI = {
    "Basic": "⚪",
    "Uncommon": "🟢",
    "Rare": "🔵",
    "Epic": "🟣",
    "Legendary": "🟡",
    "Mythic": "🔴",
    "Super": "🌈", 
    "Exclusive": "🌸",
    "Leaderboard": "👑" 
}

CLASS_EMOJI = {
    "AOE": "🌪",
    "Splash": "🌊",
    "Booster": "✨",
    "Single": "🎯",
    "Fire": "🔥"
}

CLASSES = list(CLASS_EMOJI.keys())

RARITY_WEIGHT = {
    "Leaderboard": 9, 
    "Exclusive": 8, 
    "Super": 7, 
    "Mythic": 6, 
    "Legendary": 5, 
    "Epic": 4, 
    "Rare": 3, 
    "Uncommon": 2, 
    "Basic": 1
}

active_combats = set()
active_trades = {}  
user_trades = {}    

SHOP_PACKAGES = [
    ("1_rnd", "1 Случайная карта", 100, 20, 1.0),
    ("3_rnd", "3 Случайные карты", 275, 20, 0.9),
    ("5_rnd", "5 Случайных карт", 450, 20, 0.9),
    ("10_rnd", "10 Случайных карт", 900, 15, 0.8),
    ("25_rnd", "25 Случайных карт", 2300, 10, 0.7),
    ("50_rnd", "50 Случайных карт", 4500, 3, 0.6),
    ("100_rnd", "100 Случайных карт", 9000, 2, 0.5),
    ("rnd_leg", "Случайная Легендарная", 1000, 5, 0.7), 
    ("rnd_myth", "Случайная Мифическая", 12500, 3, 0.4), 
    ("rnd_sup", "Случайная Супер Карта", 80000, 1, 0.2) 
]

# Словари для мультиязычных кнопок (Заменен Трейд на Сид-Паки в главном меню)
BTN_DRAW = ["🎴 Выбить карту", "🎴 Draw Card"]
BTN_PVE = ["⚔️ Поиск боя (боты)", "⚔️ PvE Search"]
BTN_PVP = ["⚔️ PvP Дуэль", "⚔️ PvP Duel"]
BTN_INV = ["🎒 Инвентарь", "🎒 Inventory"]
BTN_PROF = ["👤 Профиль", "👤 Profile"]
BTN_EQ = ["🛡 Экипировка", "🛡 Equipment"]
BTN_QUESTS = ["📜 Квесты", "📜 Quests"]
BTN_SHOP = ["🛒 Магазин", "🛒 Shop"]
BTN_BP = ["🎟 Батл-пассы", "🎟 Battle Pass"]
BTN_TOP = ["🏆 Топ игроков", "🏆 Leaderboard"]
BTN_IDX = ["📖 Индекс", "📖 Index"]
BTN_SEED_PACKS = ["📦 Сид-Паки", "📦 Seed-Packs"]
BTN_SET = ["⚙️ Настройки", "⚙️ Settings"]
BTN_SIGN = ["✍️ Подписать карту", "✍️ Sign Card"]
BTN_ADM = ["⚙️ Админ-панель", "⚙️ Admin Panel"]

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
    db = await get_db_connection()
    try:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                coins INTEGER DEFAULT 0,
                trophies INTEGER DEFAULT 0,
                banned INTEGER DEFAULT 0,
                last_getcard REAL DEFAULT 0,
                equip1 INTEGER DEFAULT 0,
                equip2 INTEGER DEFAULT 0,
                equip3 INTEGER DEFAULT 0,
                quests_cooldown REAL DEFAULT 0,
                pity_mythic INTEGER DEFAULT 0,
                pity_super INTEGER DEFAULT 0
            )
        """)
        
        for col in ['first_name', 'q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys', 'quests_cooldown', 'pity_mythic', 'pity_super']:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            except aiosqlite.OperationalError: pass

        # Новые колонки для настроек
        for col in ['notif_shop', 'notif_events', 'notif_quests', 'notif_announces']:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 1")
            except aiosqlite.OperationalError: pass
            
        try: await db.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ru'")
        except aiosqlite.OperationalError: pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                rarity TEXT,
                class_type TEXT,
                damage INTEGER DEFAULT 0,
                hp INTEGER DEFAULT 0,
                drop_chance REAL DEFAULT 0,
                photo_id TEXT,
                booster_dmg_mult REAL DEFAULT 1.0,
                booster_hp_mult REAL DEFAULT 1.0
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_id INTEGER,
                count INTEGER DEFAULT 1,
                mutation TEXT DEFAULT 'Normal',
                serial_number INTEGER DEFAULT 0,
                signed_by INTEGER DEFAULT 0
            )
        """)
        
        try: await db.execute("ALTER TABLE inventory ADD COLUMN mutation TEXT DEFAULT 'Normal'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE inventory ADD COLUMN serial_number INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE inventory ADD COLUMN signed_by INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: pass
        
        await db.execute("UPDATE cards SET rarity = 'Super' WHERE rarity IN ('Godly', 'Secret')")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ranks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                min_trophies INTEGER,
                difficulty_mult REAL DEFAULT 1.0,
                reward_mult REAL DEFAULT 1.0
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS server_settings (
                id INTEGER PRIMARY KEY,
                min_coins INTEGER DEFAULT 50,
                max_coins INTEGER DEFAULT 200,
                luck_mult REAL DEFAULT 1.0,
                luck_end REAL DEFAULT 0,
                cd_mult REAL DEFAULT 1.0,
                cd_end REAL DEFAULT 0,
                last_restock REAL DEFAULT 0,
                last_lb_reward REAL DEFAULT 0,
                coin_mult REAL DEFAULT 1.0,
                coin_end REAL DEFAULT 0,
                xp_mult REAL DEFAULT 1.0,
                xp_end REAL DEFAULT 0
            )
        """)
        
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN last_restock REAL DEFAULT 0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN last_lb_reward REAL DEFAULT 0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN coin_mult REAL DEFAULT 1.0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN coin_end REAL DEFAULT 0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN xp_mult REAL DEFAULT 1.0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN xp_end REAL DEFAULT 0")
        except aiosqlite.OperationalError: pass

        # ==========================================
        # ТАБЛИЦЫ СИД-ПАКОВ
        # ==========================================
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seed_packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                photo_id TEXT,
                description TEXT,
                price INTEGER DEFAULT 2000
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seed_pack_cards (
                pack_id INTEGER,
                card_id INTEGER,
                drop_chance REAL,
                PRIMARY KEY (pack_id, card_id)
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_seed_packs (
                user_id INTEGER,
                pack_id INTEGER,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, pack_id)
            )
        """)

        await db.execute("""CREATE TABLE IF NOT EXISTS shop_items (id INTEGER PRIMARY KEY AUTOINCREMENT, item_type TEXT, name TEXT, price INTEGER, stock INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS admin_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS lb_rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, bracket TEXT, reward_type TEXT, amount INTEGER DEFAULT 0, card_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal')""")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS authorized_signers (
                user_id INTEGER PRIMARY KEY
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS battle_passes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                photo_id TEXT,
                created_at REAL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bp_levels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bp_id INTEGER,
                level INTEGER,
                xp_required INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bp_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level_id INTEGER,
                reward_type TEXT,
                amount INTEGER DEFAULT 0,
                card_id INTEGER DEFAULT 0,
                mutation TEXT DEFAULT 'Normal'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_bp (
                user_id INTEGER,
                bp_id INTEGER,
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, bp_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_bp_claims (
                user_id INTEGER,
                bp_id INTEGER,
                level INTEGER,
                PRIMARY KEY (user_id, bp_id, level)
            )
        """)

        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        await db.execute("INSERT OR IGNORE INTO server_settings (id) VALUES (1)")
        
        async with db.execute("SELECT COUNT(*) as c FROM ranks") as cursor:
            row = await cursor.fetchone()
            if row and row['c'] == 0:
                default_ranks = [
                    ("Bronze I", 0, 0.8, 1.0), ("Bronze II", 50, 0.85, 1.05), ("Bronze III", 100, 0.9, 1.1), ("Bronze IV", 150, 0.95, 1.15),
                    ("Silver I", 200, 1.0, 1.2), ("Silver II", 300, 1.05, 1.25), ("Silver III", 400, 1.1, 1.3), ("Silver IV", 500, 1.15, 1.35),
                    ("Gold I", 650, 1.2, 1.4), ("Gold II", 800, 1.3, 1.5), ("Gold III", 950, 1.4, 1.6), ("Gold IV", 1100, 1.5, 1.7),
                    ("Platina I", 1300, 1.8, 1.8), ("Platina II", 1500, 2.5, 1.9), ("Platina III", 1700, 3.2, 2.0), ("Platina IV", 1900, 4.0, 2.1),
                    ("Diamond I", 2200, 5.0, 2.5), ("Diamond II", 2500, 6.5, 2.8), ("Diamond III", 2800, 8.0, 3.2), ("Diamond IV", 3100, 10.0, 3.6),
                    ("Ruby I", 3500, 13.0, 4.0), ("Ruby II", 4000, 15.0, 4.5), ("Ruby III", 4500, 17.0, 5.0), ("Ruby IV", 5000, 20.0, 5.5), ("Ruby V", 5600, 24.0, 6.0)
                ]
                for r in default_ranks:
                    await db.execute("INSERT INTO ranks (name, min_trophies, difficulty_mult, reward_mult) VALUES (?, ?, ?, ?)", r)

        await db.commit()
    finally:
        await db.close()

# ========================================================================
# FSM СОСТОЯНИЯ
# ========================================================================
class AddCard(StatesGroup):
    photo = State()
    name = State()
    drop_chance = State()
    rarity = State()
    class_type = State()
    damage = State()
    hp = State()
    booster_dmg = State()
    booster_hp = State()

class EditCard(StatesGroup):
    waiting_new_value = State()

class GiveCard(StatesGroup):
    user_id = State()
    card_id = State()
    mutation = State()

class AdminBan(StatesGroup):
    user_id = State()

class AdminManage(StatesGroup):
    add_id = State()
    del_id = State()
    reset_battle_id = State()
    give_coins_id = State()
    give_coins_amount = State()
    give_trophies_id = State()
    give_trophies_amount = State()
    
class AdminLBRewards(StatesGroup):
    bracket = State()
    reward_type = State() 
    amount = State()
    card_id = State()
    mutation = State()

class AdminBPCreation(StatesGroup):
    title = State()
    photo = State()
    levels_count = State()
    level_xp = State()
    reward_action = State()
    reward_shekels = State()
    reward_card = State()
    reward_mutation = State()

class AdminSigner(StatesGroup):
    add_id = State()

class EventLuck(StatesGroup):
    mult = State()
    mins = State()

class EventCD(StatesGroup):
    mult = State()
    mins = State()

class EventCoin(StatesGroup):
    mult = State()
    mins = State()

class EventXP(StatesGroup):
    mult = State()
    mins = State()

class AdminAnnounce(StatesGroup):
    content = State()

class PvPState(StatesGroup):
    waiting_target = State()

class TradeState(StatesGroup):
    waiting_target = State()

# FSM Состояния для Сид-Паков
class CreateSeedPack(StatesGroup):
    title = State()
    photo = State()
    description = State()
    card_select = State()
    card_chance = State()
    confirm_save = State()

class EditSeedPack(StatesGroup):
    select_pack = State()
    menu = State()
    edit_title = State()
    edit_photo = State()
    edit_description = State()
    card_edit_chance = State()
    add_card_select = State()
    add_card_chance = State()

class OpenSeedPackState(StatesGroup):
    waiting_amount = State()

# ========================================================================
# УТИЛИТЫ И ХЕЛПЕРЫ ДЛЯ UI
# ========================================================================
def get_display_name(user_data: dict) -> str:
    if user_data.get('username'): return f"@{user_data['username']}"
    elif user_data.get('first_name'): return user_data['first_name']
    return f"Игрок {user_data.get('id', '???')}"

async def get_user_titles_str(user_id: int) -> str:
    titles = []
    if await is_admin(user_id): titles.append("👑 Администратор")
    if await is_signer(user_id): titles.append("✍️ Сигнер")
    
    if titles:
        return f" [<i>{', '.join(titles)}</i>]"
    return ""

def make_progress_bar(current, total, length=10):
    if total <= 0: return "🟩" * length
    pct = min(1.0, current / total)
    filled = int(pct * length)
    empty = length - filled
    return "🟩" * filled + "⬜" * empty

async def add_quest_progress(user_id: int, field: str, amount: int = 1):
    if field not in ['q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys']:
        return
        
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user or user['quests_cooldown'] > time.time():
        return
        
    await execute_db(f"UPDATE users SET {field} = {field} + ? WHERE id = ?", (amount, user_id))
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    
    if (user['q_cards_opened'] >= 10 and
        user['q_rare_obtained'] >= 1 and
        user['q_wins'] >= 3 and
        user['q_battles'] >= 5 and
        user['q_shop_buys'] >= 1):
        
        # Выдаем 900 монет
        await execute_db("""
            UPDATE users SET
                coins = coins + 900,
                q_cards_opened = 0,
                q_rare_obtained = 0,
                q_wins = 0,
                q_battles = 0,
                q_shop_buys = 0,
                quests_cooldown = ?
            WHERE id = ?
        """, (time.time() + 3600, user_id))
        
        # ПЛЮС выдаем случайный Сид-Пак (если они есть в БД)
        packs = await fetch_all("SELECT id, title FROM seed_packs")
        pack_reward_text = ""
        if packs:
            gift_pack = random.choice(packs)
            await execute_db("""
                INSERT INTO user_seed_packs (user_id, pack_id, count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + 1
            """, (user_id, gift_pack['id']))
            pack_reward_text = f"\n📦 А также вы получили Сид-Пак: <b>{gift_pack['title']}</b> (1 шт.)!"
        
        if user['notif_quests'] == 1:
            try:
                await bot.send_message(user_id, f"🎉 <b>ПОЗДРАВЛЯЕМ!</b>\nВы выполнили все ежедневные квесты и получили <b>900 💰 Шекелей</b>!{pack_reward_text}\nВозвращайтесь через 1 час за новыми заданиями!")
            except: pass

async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID: return True
    res = await fetch_one("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return bool(res)

async def is_signer(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID: return True
    res = await fetch_one("SELECT 1 FROM authorized_signers WHERE user_id = ?", (user_id,))
    return bool(res)

async def check_ban(user_id: int) -> bool:
    res = await fetch_one("SELECT banned FROM users WHERE id = ?", (user_id,))
    return bool(res and res['banned'] == 1)

async def notify_super_admin(text: str):
    try: await bot.send_message(SUPER_ADMIN_ID, f"⚠️ <b>АДМИН-ЛОГ:</b>\n{text}")
    except Exception as e: logging.error(f"Не удалось отправить лог: {e}")

async def log_admin(admin_id: int, action: str):
    await execute_db("INSERT INTO admin_logs (admin_id, action) VALUES (?, ?)", (admin_id, action))
    admin_info = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (admin_id,))
    name = get_display_name(admin_info) if admin_info else f"ID {admin_id}"
    await notify_super_admin(f"Админ: <b>{name}</b> ({admin_id})\nДействие: {action}")

async def broadcast_message(text: str, notif_type: str = None):
    query = "SELECT id FROM users WHERE banned = 0"
    if notif_type:
        query += f" AND {notif_type} = 1"
        
    users = await fetch_all(query)
    success = 0
    for u in users:
        try:
            await bot.send_message(u['id'], text)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await notify_super_admin(f"📢 <b>Рассылка завершена.</b>\nДоставлено: {success}/{len(users)}")

def get_main_keyboard(is_adm: bool = False, is_sgn: bool = False, lang: str = "ru"):
    i = 0 if lang == "ru" else 1
    # Вместо Трейда кнопка Сид-Паки
    kb = [
        [KeyboardButton(text=BTN_DRAW[i]), KeyboardButton(text=BTN_PVE[i]), KeyboardButton(text=BTN_PVP[i])],
        [KeyboardButton(text=BTN_INV[i]), KeyboardButton(text=BTN_PROF[i]), KeyboardButton(text=BTN_EQ[i])],
        [KeyboardButton(text=BTN_QUESTS[i]), KeyboardButton(text=BTN_SHOP[i]), KeyboardButton(text=BTN_BP[i])],
        [KeyboardButton(text=BTN_TOP[i]), KeyboardButton(text=BTN_IDX[i]), KeyboardButton(text=BTN_SEED_PACKS[i])],
        [KeyboardButton(text=BTN_SET[i])]
    ]
    
    bottom_row = []
    if is_sgn: bottom_row.append(KeyboardButton(text=BTN_SIGN[i]))
    if is_adm: bottom_row.append(KeyboardButton(text=BTN_ADM[i]))
    if bottom_row: kb.append(bottom_row)
        
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_user_rank(trophies: int):
    ranks = await fetch_all("SELECT * FROM ranks ORDER BY min_trophies DESC")
    for r in ranks:
        if trophies >= r['min_trophies']: return r
    return {"name": "Bronze I", "difficulty_mult": 0.8, "reward_mult": 1.0}

async def get_active_events():
    settings = await fetch_one("SELECT * FROM server_settings WHERE id = 1")
    now = time.time()
    luck = settings['luck_mult'] if settings['luck_end'] > now else 1.0
    cd = settings['cd_mult'] if settings['cd_end'] > now else 1.0
    return luck, cd

async def get_coin_xp_events():
    settings = await fetch_one("SELECT * FROM server_settings WHERE id = 1")
    now = time.time()
    coin_mult = settings['coin_mult'] if settings['coin_end'] > now else 1.0
    xp_mult = settings['xp_mult'] if settings['xp_end'] > now else 1.0
    return coin_mult, xp_mult

def roll_mutation():
    r = random.random()
    if r <= 0.02: return "Rainbow"
    if r <= 0.12: return "Gold"
    return "Normal"

# Фиксированные шансы мутаций для Сид-Паков: 12% Gold, 2% Rainbow, 86% Normal
def roll_seed_pack_mutation():
    r = random.random()
    if r <= 0.02: return "Rainbow"
    if r <= 0.14: return "Gold" # 2% + 12% = 14%
    return "Normal"

def get_mutation_multiplier(mutation: str) -> float:
    if mutation == "Rainbow": return 1.2
    if mutation == "Gold": return 1.1
    return 1.0

def needs_serial_number(rarity: str, mutation: str) -> bool:
    if rarity == 'Leaderboard': return True
    if rarity in ['Mythic', 'Super']: return True
    if rarity == 'Legendary' and mutation != 'Normal': return True
    return False

async def give_card_to_user(user_id: int, card_id: int, mutation: str, rarity: str = None) -> tuple:
    if not rarity:
        card = await fetch_one("SELECT rarity FROM cards WHERE id = ?", (card_id,))
        rarity = card['rarity'] if card else 'Basic'
        
    db = await get_db_connection()
    try:
        if user_id == SUPER_ADMIN_ID:
            res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = -1 AND signed_by = 0", (user_id, card_id, mutation))
            inv_item = await res.fetchone()
            if inv_item:
                await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                return inv_item['id'], -1, False
            else:
                cursor = await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, -1, 0)", (user_id, card_id, mutation))
                return cursor.lastrowid, -1, True

        if needs_serial_number(rarity, mutation):
            res = await db.execute("SELECT MAX(serial_number) as m FROM inventory WHERE card_id = ? AND mutation = ?", (card_id, mutation))
            row = await res.fetchone()
            curr_max = row['m'] if (row and row['m'] is not None) else 0
            new_serial = curr_max + 1
            
            cursor = await db.execute(
                "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, ?, 0)", 
                (user_id, card_id, mutation, new_serial)
            )
            return cursor.lastrowid, new_serial, True
        else:
            res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0 AND signed_by = 0", (user_id, card_id, mutation))
            inv_item = await res.fetchone()
            if inv_item:
                await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                return inv_item['id'], 0, False
            else:
                cursor = await db.execute(
                    "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, 0, 0)", 
                    (user_id, card_id, mutation)
                )
                return cursor.lastrowid, 0, True
    finally:
        await db.commit()
        await db.close()

async def create_bordered_image(bot: Bot, photo_id: str, rarity: str) -> str:
    color = RARITY_COLORS.get(rarity, "gray")
    file = await bot.get_file(photo_id)
    file_bytes = await bot.download_file(file.file_path)
    
    img = Image.open(file_bytes).convert("RGBA")
    width, height = img.size
    
    bg = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    if color == "rainbow":
        for y in range(height):
            r = int(255 * (1 + math.sin(y / height * math.pi * 2)) / 2)
            g = int(255 * (1 + math.sin(y / height * math.pi * 2 + 2*math.pi/3)) / 2)
            b = int(255 * (1 + math.sin(y / height * math.pi * 2 + 4*math.pi/3)) / 2)
            for x in range(width):
                bg.putpixel((x, y), (r, g, b, 255))
    else:
        bg = Image.new("RGBA", (width, height), color)

    bg.paste(img, (0, 0), img)
    final_img = bg.convert("RGB")
    
    border_color = "purple" if color == "rainbow" else color
    bordered_img = ImageOps.expand(final_img, border=20, fill=border_color)
    
    bio = io.BytesIO()
    bordered_img.save(bio, format='JPEG')
    bio.seek(0)
    
    msg = await bot.send_photo(chat_id=SUPER_ADMIN_ID, photo=types.BufferedInputFile(bio.read(), filename="card.jpg"), caption=f"Сгенерирована рамка: {rarity}")
    return msg.photo[-1].file_id

def format_card_name(c):
    r_em = RARITY_EMOJI.get(c.get('rarity', 'Basic'), "⚪")
    c_em = CLASS_EMOJI.get(c.get('class_type', 'Single'), "🎯")
    name = f"{r_em} {c_em} <b>{c['name']}</b>"
    if c.get('serial_number', 0) > 0:
        name += f" <b>[#{c['serial_number']:04d}]</b>"
    if c.get('signed_by', 0) > 0:
        signer_name = c.get('signer_name') or f"ID:{c['signed_by']}"
        name += f" <i>(✍️ Sign: {signer_name})</i>"
    return name

def format_card_name_plain(c):
    r_em = RARITY_EMOJI.get(c.get('rarity', 'Basic'), "⚪")
    c_em = CLASS_EMOJI.get(c.get('class_type', 'Single'), "🎯")
    name = f"{r_em} {c_em} {c['name']}"
    if c.get('serial_number', 0) > 0:
        name += f" [#{c['serial_number']:04d}]"
    if c.get('signed_by', 0) > 0:
        signer_name = c.get('signer_name') or f"ID:{c['signed_by']}"
        name += f" (✍️ Sign: {signer_name})"
    return name

def format_rarity_display(rarity):
    r_em = RARITY_EMOJI.get(rarity, "⚪")
    return f"{r_em} <b>{rarity.upper()}</b> {r_em}"

def get_pagination_keyboard(items, page, prefix, columns=2, items_per_page=8):
    total_pages = max(1, math.ceil(len(items) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = items[start_idx:end_idx]
    kb = []
    row = []
    for item in page_items:
        row.append(InlineKeyboardButton(text=item['btn_text'], callback_data=f"{prefix}_{item['id']}"))
        if len(row) == columns:
            kb.append(row)
            row = []
    if row: kb.append(row)
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"{prefix}_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"{prefix}_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=kb)

# ========================================================================
# ЛОГИКА ШАНСОВ И МАГАЗИНА И PITY
# ========================================================================
async def calculate_chance_weights(luck_mult: float = 1.0):
    all_cards = await fetch_all("SELECT * FROM cards WHERE drop_chance > 0 AND rarity != 'Leaderboard'")
    if not all_cards: return [], 0
    total_weight = 0
    weights_dict = {}
    
    for c in all_cards:
        weight = c['drop_chance']
        if weight < 15.0: weight *= luck_mult
        weights_dict[c['id']] = weight
        total_weight += weight
        
    return weights_dict, total_weight

async def restock_shop():
    await execute_db("DELETE FROM shop_items")
    db = await get_db_connection()
    try:
        spawned_any = False
        for p_id, p_name, p_price, p_max, p_chance in SHOP_PACKAGES:
            if random.random() <= p_chance:
                stock = random.randint(1, p_max)
                await db.execute("INSERT INTO shop_items (item_type, name, price, stock) VALUES (?, ?, ?, ?)", (p_id, p_name, p_price, stock))
                spawned_any = True
                
        await db.execute("UPDATE server_settings SET last_restock = ? WHERE id = 1", (time.time(),))
        await db.commit()
    finally:
        await db.close()
        
    if spawned_any:
        asyncio.create_task(broadcast_message("🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН ОБНОВИЛСЯ!</b>\nЗавезли свежие наборы карт. Количество строго ограничено, успей купить!\n\nИспользуй кнопку в меню или /shop", notif_type="notif_shop"))

async def shop_auto_restock_task():
    while True:
        try:
            settings = await fetch_one("SELECT last_restock FROM server_settings WHERE id = 1")
            now = time.time()
            if settings and (now - settings['last_restock'] >= 1.5 * 3600):
                await restock_shop()
        except Exception as e:
            logging.error(f"Shop restock error: {e}")
        await asyncio.sleep(60)

async def give_multiple_cards(user_id: int, count: int) -> list:
    luck_mult, _ = await get_active_events()
    user = await fetch_one("SELECT pity_mythic, pity_super FROM users WHERE id=?", (user_id,))
    pm = user['pity_mythic']
    ps = user['pity_super']

    all_cards = await fetch_all("SELECT * FROM cards WHERE drop_chance > 0 AND rarity != 'Leaderboard'")
    if not all_cards: return []
    
    super_cards = [c for c in all_cards if c['rarity'] == 'Super']
    mythic_cards = [c for c in all_cards if c['rarity'] == 'Mythic']
    weights = [c['drop_chance'] * (luck_mult if c['drop_chance'] < 15.0 else 1.0) for c in all_cards]
    
    results = []
    for _ in range(count):
        card = random.choices(all_cards, weights=weights, k=1)[0]
        is_pity = False
        p_type = None

        if ps + 1 >= 10000 and card['rarity'] != 'Super' and super_cards:
            card = random.choice(super_cards)
            is_pity = True
            p_type = 'Super'
        elif pm + 1 >= 1000 and card['rarity'] not in ['Mythic', 'Super'] and mythic_cards:
            card = random.choice(mythic_cards)
            is_pity = True
            p_type = 'Mythic'

        if card['rarity'] == 'Super': 
            ps = 0; pm += 1
        elif card['rarity'] == 'Mythic': 
            pm = 0; ps += 1
        else: 
            ps += 1; pm += 1

        mut = roll_mutation()
        _, serial, _ = await give_card_to_user(user_id, card['id'], mut, card['rarity'])

        c_copy = dict(card)
        c_copy['mutation'] = mut
        c_copy['serial_number'] = serial
        c_copy['is_pity'] = is_pity
        c_copy['pity_type'] = p_type
        c_copy['signed_by'] = 0
        results.append(c_copy)

    await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
    return results

async def leaderboard_rewards_task():
    while True:
        try:
            settings = await fetch_one("SELECT last_lb_reward FROM server_settings WHERE id = 1")
            now = time.time()
            if settings and (now - settings['last_lb_reward'] >= 2 * 24 * 3600):
                top_users = await fetch_all("SELECT id, trophies, username, first_name FROM users ORDER BY trophies DESC LIMIT 20")
                if top_users:
                    for idx, user in enumerate(top_users):
                        pos = idx + 1
                        if pos == 1: bracket = "1"
                        elif pos == 2: bracket = "2"
                        elif pos == 3: bracket = "3"
                        elif pos <= 9: bracket = "4_9"
                        else: bracket = "10_20"
                        
                        rewards = await fetch_all("SELECT * FROM lb_rewards WHERE bracket = ?", (bracket,))
                        reward_msgs = []
                        for r in rewards:
                            if r['reward_type'] == 'shekels':
                                await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (r['amount'], user['id']))
                                reward_msgs.append(f"💰 {r['amount']} Шекелей")
                            elif r['reward_type'] == 'card':
                                c_info = await fetch_one("SELECT name, rarity FROM cards WHERE id = ?", (r['card_id'],))
                                if c_info:
                                    _, serial, _ = await give_card_to_user(user['id'], r['card_id'], r['mutation'], c_info['rarity'])
                                    mut_str = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                                    s_str = f" [#{serial:04d}]" if serial > 0 else ""
                                    reward_msgs.append(f"🃏 {mut_str} {c_info['name']}{s_str}")
                                    
                        if reward_msgs:
                            msg_text = (
                                f"🏆 <b>ГРАНДИОЗНАЯ НАГРАДА ЗА ТОП ИГРОКОВ!</b> 🏆\n\n"
                                f"🎉 Поздравляем! По итогам последних 2 дней вы заняли почетное <b>{pos} место</b> в мировом рейтинге по кубкам!\n\n"
                                f"🎁 <b>Вот ваша заслуженная награда:</b>\n" + "\n".join([f"🔸 {m}" for m in reward_msgs]) + "\n\n"
                                f"<i>Спасибо за вашу активность! Рейтинг был сброшен, новые награды через 2 дня! Удачи на арене!</i>"
                            )
                            try: await bot.send_message(user['id'], msg_text)
                            except: pass
                            
                await execute_db("UPDATE server_settings SET last_lb_reward = ? WHERE id = 1", (now,))
        except Exception as e:
            logging.error(f"LB Rewards error: {e}")
        await asyncio.sleep(600)

# ========================================================================
# ОСНОВНЫЕ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ И НАСТРОЙКИ
# ========================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if await check_ban(message.from_user.id): return
    await execute_db(
        "INSERT OR IGNORE INTO users (id, username, first_name) VALUES (?, ?, ?)", 
        (message.from_user.id, message.from_user.username, message.from_user.first_name)
    )
    await execute_db(
        "UPDATE users SET username = ?, first_name = ? WHERE id = ?", 
        (message.from_user.username, message.from_user.first_name, message.from_user.id)
    )
    
    active_combats.discard(message.from_user.id)

    user = await fetch_one("SELECT lang FROM users WHERE id = ?", (message.from_user.id,))
    lang = user['lang'] if user else "ru"

    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    await message.answer(
        "👋 <b>Добро пожаловать в Card Battle Bot!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Собери свою колоду уникальных юнитов, прокачивай Батл-пасс, "
        "выставляй их в бой и поднимай кубки на арене!\n\n"
        "👇 <i>Используй красивое меню снизу для навигации:</i>",
        reply_markup=get_main_keyboard(adm, sgn, lang)
    )

@dp.message(F.text.in_(BTN_SET))
async def cmd_settings(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT lang, notif_shop, notif_events, notif_quests, notif_announces FROM users WHERE id=?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    text = "⚙️ <b>НАСТРОЙКИ АККАУНТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nЗдесь вы можете изменить язык кнопок и настроить уведомления бота:"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🌐 Язык (Language): {'🇷🇺 RU' if user['lang']=='ru' else '🇬🇧 EN'}", callback_data="set_toggle_lang")],
        [InlineKeyboardButton(text=f"🛒 Завоз в магазин: {'🔔 Вкл' if user['notif_shop'] else '🔕 Выкл'}", callback_data="set_toggle_shop")],
        [InlineKeyboardButton(text=f"🎉 Ивенты сервера: {'🔔 Вкл' if user['notif_events'] else '🔕 Выкл'}", callback_data="set_toggle_events")],
        [InlineKeyboardButton(text=f"📜 Выполнение квестов: {'🔔 Вкл' if user['notif_quests'] else '🔕 Выкл'}", callback_data="set_toggle_quests")],
        [InlineKeyboardButton(text=f"📢 Анонсы администратора: {'🔔 Вкл' if user['notif_announces'] else '🔕 Выкл'}", callback_data="set_toggle_announces")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("set_toggle_"))
async def callback_settings_toggle(callback: types.CallbackQuery):
    setting = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT lang, notif_shop, notif_events, notif_quests, notif_announces FROM users WHERE id=?", (user_id,))
    if not user: return await callback.answer("Ошибка БД", show_alert=True)
    
    if setting == "lang":
        new_val = "en" if user['lang'] == "ru" else "ru"
        await execute_db("UPDATE users SET lang = ? WHERE id = ?", (new_val, user_id))
        user['lang'] = new_val
        
        adm = await is_admin(user_id)
        sgn = await is_signer(user_id)
        await callback.message.answer("✅ Язык клавиатуры обновлен!", reply_markup=get_main_keyboard(adm, sgn, new_val))
    else:
        col = f"notif_{setting}"
        new_val = 0 if user[col] == 1 else 1
        await execute_db(f"UPDATE users SET {col} = ? WHERE id = ?", (new_val, user_id))
        user[col] = new_val

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🌐 Язык (Language): {'🇷🇺 RU' if user['lang']=='ru' else '🇬🇧 EN'}", callback_data="set_toggle_lang")],
        [InlineKeyboardButton(text=f"🛒 Завоз в магазин: {'🔔 Вкл' if user['notif_shop'] else '🔕 Выкл'}", callback_data="set_toggle_shop")],
        [InlineKeyboardButton(text=f"🎉 Ивенты сервера: {'🔔 Вкл' if user['notif_events'] else '🔕 Выкл'}", callback_data="set_toggle_events")],
        [InlineKeyboardButton(text=f"📜 Выполнение квестов: {'🔔 Вкл' if user['notif_quests'] else '🔕 Выкл'}", callback_data="set_toggle_quests")],
        [InlineKeyboardButton(text=f"📢 Анонсы администратора: {'🔔 Вкл' if user['notif_announces'] else '🔕 Выкл'}", callback_data="set_toggle_announces")]
    ])
    
    try: await callback.message.edit_reply_markup(reply_markup=kb)
    except: pass
    await callback.answer()

@dp.message(Command("profile"), F.chat.type == "private")
@dp.message(F.text.in_(BTN_PROF))
async def cmd_profile(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    rank = await get_user_rank(user['trophies'])
    total_cards = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE user_id = ?", (user['id'],))
    name = get_display_name(user)
    title_str = await get_user_titles_str(user['id'])
    
    active_bp = await fetch_one("""
        SELECT bp.title, ubp.level, ubp.xp 
        FROM user_bp ubp JOIN battle_passes bp ON ubp.bp_id = bp.id 
        WHERE ubp.user_id = ? AND ubp.is_active = 1
    """, (user['id'],))
    
    bp_text = "<i>Нет активного Батл-пасса</i>"
    if active_bp:
        bp_text = f"<b>{active_bp['title']}</b> (Ур. {active_bp['level']} | {active_bp['xp']} XP)"

    text = (
        f"👤 <b>Профиль игрока {name}</b>{title_str}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖 <b>Ранг:</b> {rank['name']}\n"
        f"🏆 <b>Кубки:</b> {user['trophies']}\n"
        f"💰 <b>Шекели:</b> {user['coins']}\n"
        f"🃏 <b>Всего карт:</b> {total_cards['s'] or 0}\n"
        f"🎟 <b>Активный БП:</b> {bp_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔮 <b>Гарант на Мифик:</b> {make_progress_bar(user['pity_mythic'], 1000, 8)} ({user['pity_mythic']}/1000)\n"
        f"🌠 <b>Гарант на Супер:</b> {make_progress_bar(user['pity_super'], 10000, 8)} ({user['pity_super']}/10000)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ <b>Экипировка (Боевая Колода):</b>\n"
    )
    
    slots = ['equip1', 'equip2', 'equip3']
    for i, slot in enumerate(slots, 1):
        inv_id = user[slot]
        if inv_id != 0:
            row = await fetch_one("""
                SELECT c.id, c.name, c.rarity, c.class_type, c.damage, c.hp, c.booster_dmg_mult, c.booster_hp_mult,
                       i.mutation, i.serial_number, i.signed_by
                FROM inventory i
                JOIN cards c ON i.card_id = c.id
                WHERE i.id = ? AND i.user_id = ? AND i.count > 0
            """, (inv_id, user['id']))
            
            if row:
                mult = get_mutation_multiplier(row['mutation'])
                mut_str = ""
                if row['mutation'] == "Rainbow": mut_str = " 🌈"
                elif row['mutation'] == "Gold": mut_str = " ⭐"
                
                c_dict = dict(row)
                if row['signed_by'] > 0:
                    signer = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (row['signed_by'],))
                    if signer: c_dict['signer_name'] = get_display_name(signer)
                
                n = format_card_name(c_dict)
                if row['class_type'] == 'Booster': 
                    text += f" {i}️⃣ {n}{mut_str}\n      └ <i>Бафф: DMG x{round(row['booster_dmg_mult']*mult, 2)} | HP x{round(row['booster_hp_mult']*mult, 2)}</i>\n"
                else: 
                    text += f" {i}️⃣ {n}{mut_str}\n      └ <i>Статы: ⚔️{int(row['damage']*mult)} | ❤️{int(row['hp']*mult)}</i>\n"
            else:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ?", (user['id'],))
                text += f" {i}️⃣ [Слот Пуст (карта утеряна/продана)]\n"
        else:
            text += f" {i}️⃣ [Слот Пуст]\n"
            
    await message.answer(text)

@dp.message(Command("quests"))
@dp.message(F.text.in_(BTN_QUESTS))
async def cmd_quests(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    now = time.time()
    if user['quests_cooldown'] > now:
        left = int(user['quests_cooldown'] - now)
        m, s = divmod(left, 60)
        return await message.answer(f"⏳ <b>Все квесты выполнены!</b>\nНовые задания появятся через {m} мин. {s} сек.")
    
    c_op = min(10, user['q_cards_opened'])
    r_ob = min(1, user['q_rare_obtained'])
    w_win = min(3, user['q_wins'])
    b_pl = min(5, user['q_battles'])
    s_bu = min(1, user['q_shop_buys'])
    
    text = (
        "📜 <b>ЕЖЕДНЕВНЫЕ КВЕСТЫ</b>\n"
        "<i>Выполни все задания, чтобы сорвать куш в 900 💰 Шекелей и получить 1 Сид-Пак!</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ <b>Открыть 10 карточек:</b>\n{make_progress_bar(c_op, 10, 8)} {c_op}/10 {'✅' if c_op>=10 else '❌'}\n\n"
        f"2️⃣ <b>Получить Редкую (или лучше):</b>\n{make_progress_bar(r_ob, 1, 8)} {r_ob}/1 {'✅' if r_ob>=1 else '❌'}\n\n"
        f"3️⃣ <b>Одержать 3 победы:</b>\n{make_progress_bar(w_win, 3, 8)} {w_win}/3 {'✅' if w_win>=3 else '❌'}\n\n"
        f"4️⃣ <b>Сыграть 5 боёв:</b>\n{make_progress_bar(b_pl, 5, 8)} {b_pl}/5 {'✅' if b_pl>=5 else '❌'}\n\n"
        f"5️⃣ <b>Купить пак в Магазине:</b>\n{make_progress_bar(s_bu, 1, 8)} {s_bu}/1 {'✅' if s_bu>=1 else '❌'}\n"
    )
    await message.answer(text)

@dp.message(Command("top"))
@dp.message(F.text.in_(BTN_TOP))
async def cmd_top(message: types.Message):
    if await check_ban(message.from_user.id): return
    top_users = await fetch_all("SELECT username, first_name, id, trophies FROM users ORDER BY trophies DESC LIMIT 20")
    
    text = "🏆 <b>МИРОВОЙ РЕЙТИНГ (Топ-20)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, u in enumerate(top_users, 1):
        name = get_display_name(u)
        title_str = await get_user_titles_str(u['id'])
        rank = await get_user_rank(u['trophies'])
        med = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
        text += f"{med} <b>{i}. {name}</b>{title_str} — {u['trophies']} 🏆 <i>({rank['name']})</i>\n"
        
    text += "\n🎁 <b>Награды Сезона (сброс каждые 2 дня):</b>\n"
    brackets = ["1", "2", "3", "4_9", "10_20"]
    bracket_names = {"1": "🥇 1 место", "2": "🥈 2 место", "3": "🥉 3 место", "4_9": "🏅 4-9 места", "10_20": "🎖 10-20 места"}
    
    has_rewards = False
    for b in brackets:
        b_rewards = await fetch_all("SELECT * FROM lb_rewards WHERE bracket = ?", (b,))
        if b_rewards:
            has_rewards = True
            r_strs = []
            for r in b_rewards:
                if r['reward_type'] == 'shekels':
                    r_strs.append(f"{r['amount']} 💰")
                elif r['reward_type'] == 'card':
                    c = await fetch_one("SELECT name, rarity FROM cards WHERE id = ?", (r['card_id'],))
                    mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                    r_strs.append(f"{mut} {c['name'] if c else 'Удаленная карта'}")
            text += f"└ {bracket_names[b]}: {', '.join(r_strs)}\n"
            
    if not has_rewards:
        text += "<i>Награды пока не настроены администратором.</i>"
        
    await message.answer(text)

@dp.message(Command("shop"))
@dp.message(F.text.in_(BTN_SHOP))
async def cmd_shop(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (message.from_user.id,))
    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    
    if not items:
        return await message.answer("🛒 <b>Магазин пока пуст.</b>\nЗавоз осуществляется каждые полтора часа. Жди уведомления!")
        
    text = (
        f"🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН</b>\n"
        f"💰 Твой баланс: <b>{user['coins']} Шекелей</b>\n"
        f"<i>(Товары общие для всех. Кто успел, тот и купил!)</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    kb = []
    for i, item in enumerate(items, 1):
        text += f"📦 <b>{item['name']}</b>\n      └ 💵 Цена: <b>{item['price']} 💰</b> | Остаток: <b>{item['stock']} шт.</b>\n\n"
        kb.append([InlineKeyboardButton(text=f"Купить: {item['name']} ({item['price']} 💰)", callback_data=f"buy_shop_{item['id']}")])
        
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_shop_"))
async def callback_buy_shop(callback: types.CallbackQuery):
    shop_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT coins, pity_mythic, pity_super FROM users WHERE id = ?", (user_id,))
    item = await fetch_one("SELECT * FROM shop_items WHERE id = ?", (shop_id,))
    
    if not item or item['stock'] <= 0: return await callback.answer("❌ Этот товар закончился!", show_alert=True)
    if user['coins'] < item['price']: return await callback.answer("❌ Недостаточно шекелей!", show_alert=True)
    
    await execute_db("UPDATE users SET coins = coins - ? WHERE id = ?", (item['price'], user_id))
    await execute_db("UPDATE shop_items SET stock = stock - 1 WHERE id = ?", (shop_id,))
    
    await add_quest_progress(user_id, 'q_shop_buys', 1)
    
    i_type = item['item_type']
    
    if i_type.endswith("_rnd"):
        count = int(i_type.split("_")[0])
        won = await give_multiple_cards(user_id, count)
        
        await add_quest_progress(user_id, 'q_cards_opened', count)
        if any(c['rarity'] == 'Rare' for c in won):
            await add_quest_progress(user_id, 'q_rare_obtained', 1)
            
        pity_pulls = [c for c in won if c.get('is_pity')]
        
        if count == 1: 
            mut_str = "🌈 " if won[0]['mutation'] == 'Rainbow' else ("⭐ " if won[0]['mutation'] == 'Gold' else "")
            msg = f"🛍 <b>Покупка успешна!</b>\nВы выбили: {mut_str}{format_card_name(won[0])}"
            if won[0].get('is_pity'):
                msg = f"🌟 <b>СИСТЕМА PITY! Гарантированный {won[0]['pity_type']}!</b> 🌟\n\n" + msg
        else: 
            msg = f"🛍 <b>Успешно! Вы открыли пак из {count} карт!</b>\nПосмотрите новинки в 🎒 Инвентаре."
            if pity_pulls:
                p_names = ", ".join([f"{c['name']} (Pity {c['pity_type']})" for c in pity_pulls])
                msg += f"\n\n🌟 <b>Сработал PITY! Гарантированные редчайшие карты:</b>\n{p_names}!"
                
        await callback.message.answer(msg)
        
    elif i_type.startswith("rnd_"):
        rarity_map = {"rnd_leg": "Legendary", "rnd_myth": "Mythic", "rnd_sup": "Super"}
        target_rarity = rarity_map[i_type]
        
        all_cards = await fetch_all("SELECT * FROM cards WHERE rarity = ?", (target_rarity,))
        if not all_cards:
            await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (item['price'], user_id))
            return await callback.message.answer("❌ Ошибка: В базе нет карт такой редкости! Шекели возвращены.")
            
        won_card = random.choice(all_cards)
        mut = roll_mutation()
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        won_card['serial_number'] = serial
        won_card['signed_by'] = 0
        
        await add_quest_progress(user_id, 'q_cards_opened', 1)
        if won_card['rarity'] == 'Rare':
            await add_quest_progress(user_id, 'q_rare_obtained', 1)
            
        pm = user['pity_mythic']
        ps = user['pity_super']
        if target_rarity == 'Super': ps = 0; pm += 1
        elif target_rarity == 'Mythic': pm = 0; ps += 1
        else: ps += 1; pm += 1
        await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
        
        mut_str = "🌈 Радужная" if mut == 'Rainbow' else ("⭐ Золотая" if mut == 'Gold' else "Обычная")
        await callback.message.answer(f"🛍 <b>Успешная покупка ГАРАНТА!</b>\nВы выбили: {format_card_name(won_card)}\nМутация: <b>{mut_str}</b>")

    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    if not items:
        await callback.message.edit_text("🛒 <b>Магазин полностью распродан!</b>\nЖдите следующего завоза.")
    else:
        new_coins = user['coins'] - item['price']
        text = f"🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН</b>\n💰 Твой баланс: <b>{new_coins} Шекелей</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        kb = []
        for i, itm in enumerate(items, 1):
            text += f"📦 <b>{itm['name']}</b>\n      └ 💵 Цена: <b>{itm['price']} 💰</b> | Остаток: <b>{itm['stock']} шт.</b>\n\n"
            kb.append([InlineKeyboardButton(text=f"Купить: {itm['name']} ({itm['price']} 💰)", callback_data=f"buy_shop_{itm['id']}")])
        try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        except: pass
    
    await callback.answer()

# ========================================================================
# СИСТЕМА ГАЧИ (ВЫБИВАНИЕ КАРТ) И МУТАЦИИ
# ========================================================================
@dp.message(Command("getcard"))
@dp.message(F.text.in_(BTN_DRAW))
async def cmd_getcard(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    if user['id'] in user_trades: return await message.answer("❌ Завершите активный обмен перед выбиванием карт!")
    
    luck_mult, cd_mult = await get_active_events()
    base_cooldown = 4 * 60
    actual_cooldown = int(base_cooldown / cd_mult)
    
    now = time.time()
    passed = now - user['last_getcard']
    
    if passed < actual_cooldown:
        left = int(actual_cooldown - passed)
        mins, secs = divmod(left, 60)
        return await message.answer(f"⏳ <b>Колода перемешивается!</b>\nОжидай: <b>{mins} мин. {secs} сек.</b>")
        
    won_list = await give_multiple_cards(user['id'], 1)
    if not won_list: return await message.answer("😔 В базе пока нет доступных для выбивания карт.")
    won_card = won_list[0]
        
    await execute_db("UPDATE users SET last_getcard = ? WHERE id = ?", (now, user['id']))
    
    await add_quest_progress(user['id'], 'q_cards_opened', 1)
    if won_card['rarity'] == 'Rare':
        await add_quest_progress(user['id'], 'q_rare_obtained', 1)
    
    n_fmt = format_card_name(won_card)
    rarity_text = format_rarity_display(won_card['rarity'])
    
    mutation = won_card['mutation']
    mult = get_mutation_multiplier(mutation)
    mut_str = ""
    if mutation == "Gold": mut_str = "⭐ <b>ЗОЛОТАЯ МУТАЦИЯ! (+10% Статов)</b>\n"
    elif mutation == "Rainbow": mut_str = "🌈 <b>РАДУЖНАЯ МУТАЦИЯ! (+20% Статов)</b>\n"
    
    msg = ""
    if won_card.get('is_pity'):
        msg += f"🌟 <b>СИСТЕМА PITY! ГАРАНТИРОВАННЫЙ {won_card['pity_type']}!</b> 🌟\n\n"
        
    msg += f"🎉 <b>ВЫ ВЫБИЛИ КАРТУ!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n{mut_str}🃏 {n_fmt}\n💎 <b>Редкость:</b> {rarity_text}\n"
    
    if won_card['class_type'] == 'Booster': 
        msg += f"✨ <b>БУСТЕР</b>\n⚔️ Урон: <b>x{round(won_card['booster_dmg_mult']*mult, 2)}</b> | ❤️ ХП: <b>x{round(won_card['booster_hp_mult']*mult, 2)}</b>\n"
    else: 
        msg += f"⚔️ <b>Урон:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n"
        
    if luck_mult > 1.0 and won_card['drop_chance'] < 15.0:
        msg += f"\n🍀 <i>Сработал ивент удачи!</i>"
        
    await message.answer_photo(photo=won_card['photo_id'], caption=msg)

# ========================================================================
# ПАГИНАЦИЯ ИНДЕКСА И ИНВЕНТАРЯ (С ПОДДЕРЖКОЙ СИДПАКОВ)
# ========================================================================
async def get_index_text(user_id: int, page: int = 0, items_per_page: int = 8, pack_id: int = None):
    # Если pack_id указан, выводим индекс Сид-Пака
    if pack_id:
        pack = await fetch_one("SELECT * FROM seed_packs WHERE id = ?", (pack_id,))
        if not pack: return "Сид-пак не найден.", None
        
        pack_cards = await fetch_all("""
            SELECT c.*, spc.drop_chance as pack_drop_chance 
            FROM seed_pack_cards spc
            JOIN cards c ON spc.card_id = c.id
            WHERE spc.pack_id = ?
        """, (pack_id,))
        
        if not pack_cards: return f"Сид-Пак <b>{pack['title']}</b> пуст.", None
        
        luck_mult, _ = await get_active_events()
        
        total_w = 0
        weights_dict = {}
        for c in pack_cards:
            weight = c['pack_drop_chance']
            if weight < 15.0: weight *= luck_mult
            weights_dict[c['id']] = weight
            total_w += weight
            
        def seed_sort_key(c):
            return weights_dict.get(c['id'], 9999)
            
        pack_cards.sort(key=seed_sort_key)
        
        total_pages = max(1, math.ceil(len(pack_cards) / items_per_page))
        page = max(0, min(page, total_pages - 1))
        
        text = f"📦 <b>ИНДЕКС СИД-ПАКА: {pack['title']} (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        if luck_mult > 1.0: text += f"🍀 <b>ИВЕНТ УДАЧИ АКТИВЕН (x{luck_mult})! Шансы пересчитаны!</b>\n\n"
        
        start_idx = page * items_per_page
        end_idx = start_idx + items_per_page
        page_items = pack_cards[start_idx:end_idx]
        
        user_inv = await fetch_all("SELECT DISTINCT card_id FROM inventory WHERE user_id = ?", (user_id,))
        user_card_ids = [item['card_id'] for item in user_inv]
        
        for i, c in enumerate(page_items, start_idx + 1):
            n_fmt = format_card_name(c)
            r_fmt = format_rarity_display(c['rarity'])
            
            real_chance = (weights_dict.get(c['id'], 0) / total_w) * 100 if total_w > 0 else 0
            chance_str = f"Шанс в паке: {real_chance:.2f}%"
            
            if c['id'] in user_card_ids:
                text += f"{i}. {n_fmt}\n      └ 💎 {r_fmt} ({chance_str})\n"
                if c['class_type'] == 'Booster': text += f"      └ ✨ Бафф: DMG x{c['booster_dmg_mult']} // HP x{c['booster_hp_mult']}\n\n"
                else: text += f"      └ ⚔️ Урон: {c['damage']} // ❤️ Здоровье: {c['hp']}\n\n"
            else:
                text += f"{i}. <b>???</b> (Не открыто)\n      └ 💎 {r_fmt} ({chance_str})\n\n"
                
        kb = []
        nav_row = []
        if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"idxpack_page_{pack_id}_{page-1}"))
        if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
        if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"idxpack_page_{pack_id}_{page+1}"))
        if nav_row: kb.append(nav_row)
        kb.append([InlineKeyboardButton(text="🔙 К выбору категорий", callback_data="idx_categories")])
        
        return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

    # Обычный индекс
    all_cards = await fetch_all("SELECT * FROM cards")
    user_inv = await fetch_all("SELECT DISTINCT card_id FROM inventory WHERE user_id = ?", (user_id,))
    user_card_ids = [item['card_id'] for item in user_inv]
    
    if not all_cards: return "Индекс пуст.", None
    
    luck_mult, _ = await get_active_events()
    weights_dict, total_w = await calculate_chance_weights(luck_mult)
    
    def index_sort_key(c):
        if c['rarity'] == 'Leaderboard': return -1
        return weights_dict.get(c['id'], 9999)
        
    all_cards.sort(key=index_sort_key)
    
    total_pages = max(1, math.ceil(len(all_cards) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    
    text = f"📖 <b>МИРОВОЙ ИНДЕКС ГАЧИ (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if luck_mult > 1.0: text += f"🍀 <b>ИВЕНТ УДАЧИ АКТИВЕН (x{luck_mult})! Шансы пересчитаны!</b>\n\n"
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = all_cards[start_idx:end_idx]
    
    for i, c in enumerate(page_items, start_idx + 1):
        inv_stats = await fetch_all("SELECT mutation, SUM(count) as c FROM inventory WHERE card_id = ? AND user_id != ? GROUP BY mutation", (c['id'], SUPER_ADMIN_ID))
        total_exists = sum(item['c'] for item in inv_stats if item['c'])
        
        mut_texts = []
        for st in inv_stats:
            if st['mutation'] == 'Gold' and st['c'] > 0: mut_texts.append(f"⭐ Золотых: {st['c']}")
            if st['mutation'] == 'Rainbow' and st['c'] > 0: mut_texts.append(f"🌈 Радужных: {st['c']}")
            
        mut_str = f"\n      └ <i>Из них: {', '.join(mut_texts)}</i>" if mut_texts else ""
        
        n_fmt = format_card_name(c).replace(" <b>[#-001]</b>", "")
        r_fmt = format_rarity_display(c['rarity'])
        
        real_chance = (weights_dict.get(c['id'], 0) / total_w) * 100 if total_w > 0 else 0
        chance_str = f"Шанс: {real_chance:.4f}%" if c['rarity'] != 'Leaderboard' else "Только за Топ!"
        
        if c['id'] in user_card_ids:
            text += f"{i}. {n_fmt}\n      └ 💎 {r_fmt} ({chance_str})\n"
            if c['class_type'] == 'Booster': text += f"      └ ✨ Бафф: DMG x{c['booster_dmg_mult']} // HP x{c['booster_hp_mult']}\n"
            else: text += f"      └ ⚔️ Урон: {c['damage']} // ❤️ Здоровье: {c['hp']}\n"
            text += f"      └ 🌍 Существует: {total_exists} шт.{mut_str}\n\n"
        else:
            text += f"{i}. <b>???</b> (Не открыто)\n      └ 💎 {r_fmt} ({chance_str})\n"
            text += f"      └ 🌍 Существует: {total_exists} шт.{mut_str}\n\n"
            
    kb = []
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"idx_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"idx_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    kb.append([InlineKeyboardButton(text="🔙 К выбору категорий", callback_data="idx_categories")])
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("index"))
@dp.message(F.text.in_(BTN_IDX))
async def cmd_index(message: types.Message):
    if await check_ban(message.from_user.id): return
    # Отправляем меню выбора категории индекса
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Обычная Гача", callback_data="idx_category_gacha")],
        [InlineKeyboardButton(text="📦 Сид-Паки", callback_data="idx_category_packs")]
    ])
    await message.answer("📖 <b>МИРОВОЙ ИНДЕКС</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите категорию для просмотра вероятностей и карт:", reply_markup=kb)

@dp.callback_query(F.data == "idx_categories")
async def cb_idx_categories(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Обычная Гача", callback_data="idx_category_gacha")],
        [InlineKeyboardButton(text="📦 Сид-Паки", callback_data="idx_category_packs")]
    ])
    try: await callback.message.edit_text("📖 <b>МИРОВОЙ ИНДЕКС</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите категорию для просмотра:", reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data == "idx_category_gacha")
async def cb_idx_category_gacha(callback: types.CallbackQuery):
    text, kb = await get_index_text(callback.from_user.id, 0)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "idx_category_packs")
async def cb_idx_category_packs(callback: types.CallbackQuery):
    packs = await fetch_all("SELECT * FROM seed_packs")
    if not packs:
        return await callback.answer("❌ Сид-Паки еще не созданы администратором!", show_alert=True)
    kb = []
    for p in packs:
        kb.append([InlineKeyboardButton(text=f"📦 {p['title']}", callback_data=f"idxpack_select_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="idx_categories")])
    await callback.message.edit_text("📦 <b>ВЫБЕРИТЕ СИД-ПАК ДЛЯ ИНДЕКСА</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("idxpack_select_"))
async def cb_idxpack_select(callback: types.CallbackQuery):
    pack_id = int(callback.data.split("_")[2])
    text, kb = await get_index_text(callback.from_user.id, 0, pack_id=pack_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("idxpack_page_"))
async def cb_idxpack_page(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    pack_id = int(parts[2])
    page = int(parts[3])
    text, kb = await get_index_text(callback.from_user.id, page, pack_id=pack_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("idx_page_"))
async def callback_index_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[2])
    text, kb = await get_index_text(callback.from_user.id, page)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

async def get_inventory_text_and_kb(user_id: int, page: int = 0, items_per_page: int = 30):
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name
        FROM inventory i 
        JOIN cards c ON i.card_id = c.id 
        LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.count > 0
    """, (user_id,))
    
    # Кнопки-переключатели инвентаря
    toggle_row = [
        InlineKeyboardButton(text="🎒 Карты (Выбрано)", callback_data="ignore"),
        InlineKeyboardButton(text="📦 Сид-Паки", callback_data="inv_packs_menu")
    ]
    
    if not inv: 
        return "🎒 Ваш инвентарь карт пуст. Используйте /getcard", InlineKeyboardMarkup(inline_keyboard=[toggle_row])
        
    mutation_weight = {"Rainbow": 3, "Gold": 2, "Normal": 1}
    
    for item in inv:
        if item['signed_by'] != 0:
            item['signer_name'] = get_display_name({'username': item['username'], 'first_name': item['first_name']})
    
    inv.sort(key=lambda x: (x['signed_by'] > 0, RARITY_WEIGHT.get(x['rarity'], 0), mutation_weight.get(x['mutation'], 0), x['card_id']), reverse=True)
    
    total_pages = max(1, math.ceil(len(inv) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = inv[start_idx:end_idx]
    
    text = f"🎒 <b>ИНВЕНТАРЬ КАРТ (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for item in page_items:
        n_fmt = format_card_name(item).replace(" <b>[#-001]</b>", "")
        mut_emoji = ""
        if item['mutation'] == "Gold": mut_emoji = "⭐ "
        elif item['mutation'] == "Rainbow": mut_emoji = "🌈 "
        text += f"• {mut_emoji}{n_fmt} — <b>{item['count']} шт.</b>\n"
        
    kb = []
    kb.append(toggle_row)
    
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"inv_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"inv_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("inventory"))
@dp.message(F.text.in_(BTN_INV))
async def cmd_inventory(message: types.Message):
    if await check_ban(message.from_user.id): return
    text, kb = await get_inventory_text_and_kb(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("inv_page_"))
async def callback_inventory_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[2])
    text, kb = await get_inventory_text_and_kb(callback.from_user.id, page)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# ========================================================================
# ПОДПИСИ (СИГНЫ) КАРТ ПОЛЬЗОВАТЕЛЯМИ
# ========================================================================
@dp.message(F.text.in_(BTN_SIGN))
async def cmd_sign_card(message: types.Message):
    if await check_ban(message.from_user.id): return
    if not await is_signer(message.from_user.id): return
    if message.from_user.id in user_trades: return await message.answer("❌ Завершите обмен перед подписыванием карт!")
    
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0 AND i.signed_by = 0
    """, (message.from_user.id,))
    
    if not inv: return await message.answer("❌ В инвентаре нет карт, доступных для подписи (или все уже подписаны).")
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = []
    for c in inv:
        mut_emoji = "⭐ " if c['mutation'] == 'Gold' else "🌈 " if c['mutation'] == 'Rainbow' else ""
        items.append({"id": c['inv_id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {mut_emoji}{c['name']} x{c['count']}"})
        
    kb = get_pagination_keyboard(items, 0, "sgn_c", columns=1, items_per_page=8)
    await message.answer("✍️ <b>ВЫБОР КАРТЫ ДЛЯ ПОДПИСИ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите карту из инвентаря, чтобы оставить на ней свою роспись:", reply_markup=kb)

@dp.callback_query(F.data.startswith("sgn_c_page_"))
async def cb_sign_card_paginate(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[3])
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0 AND i.signed_by = 0
    """, (callback.from_user.id,))
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = []
    for c in inv:
        mut_emoji = "⭐ " if c['mutation'] == 'Gold' else "🌈 " if c['mutation'] == 'Rainbow' else ""
        items.append({"id": c['inv_id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {mut_emoji}{c['name']} x{c['count']}"})
        
    kb = get_pagination_keyboard(items, page, "sgn_c", columns=1, items_per_page=8)
    try: await callback.message.edit_reply_markup(reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("sgn_c_"))
async def cb_sign_card_select(callback: types.CallbackQuery):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if not await is_signer(user_id): return await callback.answer("У вас нет прав!", show_alert=True)
    
    db = await get_db_connection()
    try:
        cur = await db.execute("SELECT card_id, count, mutation, serial_number, signed_by FROM inventory WHERE id = ? AND user_id = ?", (inv_id, user_id))
        row = await cur.fetchone()
        if not row or row['count'] < 1: return await callback.answer("Карта не найдена!", show_alert=True)
        if row['signed_by'] != 0: return await callback.answer("Эта карта уже подписана!", show_alert=True)
        
        await db.execute("BEGIN")
        if row['count'] == 1:
            await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
            
            # Если последняя удалилась и была экипирована - снимаем с экипировки
            await db.execute("UPDATE users SET equip1 = 0 WHERE equip1 = ?", (inv_id,))
            await db.execute("UPDATE users SET equip2 = 0 WHERE equip2 = ?", (inv_id,))
            await db.execute("UPDATE users SET equip3 = 0 WHERE equip3 = ?", (inv_id,))
        else:
            await db.execute("UPDATE inventory SET count = count - 1 WHERE id = ?", (inv_id,))
            
        cur2 = await db.execute("""
            SELECT id FROM inventory 
            WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = ? AND signed_by = ?
        """, (user_id, row['card_id'], row['mutation'], row['serial_number'], user_id))
        dest = await cur2.fetchone()
        
        if dest:
            await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (dest['id'],))
        else:
            await db.execute("""
                INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by)
                VALUES (?, ?, 1, ?, ?, ?)
            """, (user_id, row['card_id'], row['mutation'], row['serial_number'], user_id))
            
        await db.commit()
    except Exception as e:
        await db.execute("ROLLBACK")
        logging.error(f"Sign error: {e}")
        return await callback.answer("Ошибка при подписании.", show_alert=True)
    finally:
        await db.close()
        
    await callback.message.delete()
    await callback.message.answer("✍️✅ <b>Вы успешно оставили свою роспись на этой карте!</b>\nОна перенесена в отдельную стопку в вашем инвентаре.")
    await callback.answer()

# ========================================================================
# ЭКИПИРОВКА (ПРОДВИНУТАЯ ВЫБОРКА)
# ========================================================================
def get_equip_main_keyboard(user_info, cards_info):
    kb = []
    for i, slot in enumerate(['equip1', 'equip2', 'equip3'], 1):
        inv_id = user_info[slot]
        text = f"Слот {i} [Пусто]" if inv_id == 0 else f"Слот {i}: {cards_info.get(inv_id, f'Inv ID: {inv_id}')}"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"eq_select_{i}")])
    kb.append([InlineKeyboardButton(text="❌ Очистить колоду", callback_data="eq_clear")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("equip"))
@dp.message(F.text.in_(BTN_EQ))
async def cmd_equip(message: types.Message):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in user_trades: return await message.answer("❌ Завершите обмен перед сменой экипировки!")
    
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (message.from_user.id,))
    inv_ids = [c for c in [user['equip1'], user['equip2'], user['equip3']] if c != 0]
    
    cards_info = {}
    if inv_ids:
        inv_list = ",".join(map(str, inv_ids))
        res = await fetch_all(f"""
            SELECT i.id, c.name, i.mutation, i.serial_number 
            FROM inventory i JOIN cards c ON i.card_id = c.id 
            WHERE i.id IN ({inv_list}) AND i.count > 0
        """)
        for r in res:
            mut_str = "⭐" if r['mutation'] == 'Gold' else "🌈" if r['mutation'] == 'Rainbow' else ""
            ser_str = f" [#{r['serial_number']:04d}]" if r['serial_number'] > 0 else ""
            cards_info[r['id']] = f"{mut_str}{r['name']}{ser_str}".strip()
            
    await message.answer("🛡 <b>БОЕВАЯ КОЛОДА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nНажмите на слот, чтобы выбрать конкретную карту из инвентаря:", reply_markup=get_equip_main_keyboard(user, cards_info))

@dp.callback_query(F.data.startswith("eq_select_"))
async def equip_slot_callback(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])
    # Сначала показываем уникальные карточки
    inv = await fetch_all("""
        SELECT DISTINCT c.id, c.name, c.rarity, c.class_type
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0
    """, (callback.from_user.id,))
    
    if not inv: return await callback.answer("У вас нет карт!", show_alert=True)
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']}"} for c in inv]
    
    await state.update_data(equip_slot=slot_num, equip_items_cards=items)
    kb = get_pagination_keyboard(items, 0, "eq_c", columns=1, items_per_page=8)
    
    await callback.message.edit_text(f"👇 Выберите вид карты для <b>Слота {slot_num}</b>:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_c_page_"))
async def equip_card_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('equip_items_cards', []), page, "eq_c", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_c_"))
async def equip_card_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return 
    card_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    slot_num = data.get('equip_slot', 1)
    
    # Теперь ищем все вариации этой карты у юзера
    invs = await fetch_all("""
        SELECT i.id as inv_id, c.name, c.rarity, c.class_type, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name, i.count
        FROM inventory i 
        JOIN cards c ON i.card_id = c.id 
        LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.card_id = ? AND i.count > 0
    """, (callback.from_user.id, card_id))
    
    if not invs: return await callback.answer("У вас больше нет этой карты!", show_alert=True)
    
    items = []
    for i in invs:
        c_dict = dict(i)
        if i['signed_by'] > 0:
            c_dict['signer_name'] = get_display_name({'username': i['username'], 'first_name': i['first_name']})
        
        name_str = format_card_name_plain(c_dict)
        mut = "⭐ " if i['mutation'] == 'Gold' else "🌈 " if i['mutation'] == 'Rainbow' else ""
        items.append({"id": i['inv_id'], "btn_text": f"{mut}{name_str} (x{i['count']})"})
        
    await state.update_data(equip_items_vars=items)
    kb = get_pagination_keyboard(items, 0, "eq_v", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад к списку", callback_data=f"eq_select_{slot_num}")])
    
    await callback.message.edit_text(f"👇 Выберите конкретную вариацию для <b>Слота {slot_num}</b>:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_v_page_"))
async def equip_var_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('equip_items_vars', []), page, "eq_v", columns=1, items_per_page=6)
    slot_num = data.get('equip_slot', 1)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад к списку", callback_data=f"eq_select_{slot_num}")])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_v_"))
async def equip_var_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    slot_num = data.get('equip_slot', 1)
    
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (callback.from_user.id,))
    if inv_id in [user['equip1'], user['equip2'], user['equip3']]:
        return await callback.answer("❌ Эта конкретная карта уже экипирована в другом слоте!", show_alert=True)
        
    # Проверка на то, что слот не может дублировать card_id (нельзя надеть 3 одинаковых юнита)
    card_info = await fetch_one("SELECT card_id FROM inventory WHERE id = ?", (inv_id,))
    if not card_info: return await callback.answer("Карта не найдена!")
    
    equipped_invs = [user['equip1'], user['equip2'], user['equip3']]
    equipped_invs.remove(user[f'equip{slot_num}'])
    
    if any(i != 0 for i in equipped_invs):
        inv_list = ",".join(map(str, [i for i in equipped_invs if i != 0]))
        other_cards = await fetch_all(f"SELECT card_id FROM inventory WHERE id IN ({inv_list})")
        if any(c['card_id'] == card_info['card_id'] for c in other_cards):
            return await callback.answer("❌ Нельзя надеть две одинаковые карты в разные слоты (даже если они разной мутации)!", show_alert=True)

    await execute_db(f"UPDATE users SET equip{slot_num} = ? WHERE id = ?", (inv_id, callback.from_user.id))
    await callback.message.edit_text(f"✅ Карточка успешно установлена в Слот {slot_num}!")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "eq_clear")
async def equip_clear_callback(callback: types.CallbackQuery):
    await execute_db("UPDATE users SET equip1=0, equip2=0, equip3=0 WHERE id = ?", (callback.from_user.id,))
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (callback.from_user.id,))
    await callback.message.edit_text("✅ Боевая колода полностью очищена.", reply_markup=get_equip_main_keyboard(user, {}))
    await callback.answer()

# ========================================================================
# БАТЛ-ПАСС (МЕНЮ ИГРОКА)
# ========================================================================
@dp.message(F.text.in_(BTN_BP))
async def cmd_battle_passes(message: types.Message):
    if await check_ban(message.from_user.id): return
    passes = await fetch_all("SELECT * FROM battle_passes ORDER BY id DESC")
    
    if not passes:
        return await message.answer("🎟 <b>Батл-пассы</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВ данный момент нет доступных сезонов. Ожидайте обновлений!")
        
    kb = []
    for bp in passes:
        kb.append([InlineKeyboardButton(text=f"🎫 {bp['title']}", callback_data=f"bp_view_{bp['id']}")])
        
    await message.answer("🎟 <b>ДОСТУПНЫЕ БАТЛ-ПАССЫ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите сезон, чтобы посмотреть прогресс или сделать его активным:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("bp_view_"))
async def callback_bp_view(callback: types.CallbackQuery):
    bp_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    bp = await fetch_one("SELECT * FROM battle_passes WHERE id = ?", (bp_id,))
    if not bp: return await callback.answer("Батл-пасс не найден!", show_alert=True)
    
    user_bp = await fetch_one("SELECT * FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    if not user_bp:
        await execute_db("INSERT INTO user_bp (user_id, bp_id, xp, level, is_active) VALUES (?, ?, 0, 0, 0)", (user_id, bp_id))
        user_bp = await fetch_one("SELECT * FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
        
    is_active = bool(user_bp['is_active'])
    status_str = "🟢 <b>АКТИВЕН</b> (Весь опыт идет сюда)" if is_active else "🔴 <b>НЕАКТИВЕН</b>"
    
    curr_lvl = user_bp['level']
    curr_xp = user_bp['xp']
    
    next_lvl_data = await fetch_one("SELECT xp_required FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, curr_lvl + 1))
    req_xp = next_lvl_data['xp_required'] if next_lvl_data else 0
    
    if next_lvl_data:
        progress_str = f"{make_progress_bar(curr_xp, req_xp, 12)} ({curr_xp}/{req_xp})"
    else:
        progress_str = f"🏆 <b>БАТЛ-ПАСС ПОЛНОСТЬЮ ПРОЙДЕН!</b>"

    text = (
        f"🏆 <b>СЕЗОН: {bp['title']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Статус: {status_str}\n"
        f"🎖 Ваш уровень: <b>{curr_lvl}</b>\n"
        f"✨ Опыт до след. ур: {progress_str}\n"
    )
    
    kb = []
    if not is_active:
        kb.append([InlineKeyboardButton(text="✅ Сделать активным", callback_data=f"bp_set_act_{bp_id}")])
    kb.append([InlineKeyboardButton(text="▶️ Посмотреть уровни и награды", callback_data=f"bp_lvl_{bp_id}_1")])
    kb.append([InlineKeyboardButton(text="🔙 Назад к списку", callback_data="bp_list")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    
    if bp['photo_id']:
        try:
            await callback.message.answer_photo(photo=bp['photo_id'], caption=text, reply_markup=markup)
            await callback.message.delete()
        except:
            await callback.message.edit_text(text, reply_markup=markup)
    else:
        await callback.message.edit_text(text, reply_markup=markup)
    await callback.answer()

@dp.callback_query(F.data == "bp_list")
async def callback_bp_list(callback: types.CallbackQuery):
    passes = await fetch_all("SELECT * FROM battle_passes ORDER BY id DESC")
    if not passes:
        return await callback.message.edit_text("🎟 Батл-пассов пока нет.")
    kb = []
    for bp in passes:
        kb.append([InlineKeyboardButton(text=f"🎫 {bp['title']}", callback_data=f"bp_view_{bp['id']}")])
    
    try:
        await callback.message.edit_text("🎟 <b>ДОСТУПНЫЕ БАТЛ-ПАССЫ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите сезон:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except:
        await callback.message.answer("🎟 <b>ДОСТУПНЫЕ БАТЛ-ПАССЫ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите сезон:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("bp_set_act_"))
async def callback_bp_set_active(callback: types.CallbackQuery):
    bp_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    
    await execute_db("UPDATE user_bp SET is_active = 0 WHERE user_id = ?", (user_id,))
    await execute_db("UPDATE user_bp SET is_active = 1 WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    
    await callback.answer("✅ Батл-пасс установлен как активный!", show_alert=True)
    await callback_bp_view(callback)

@dp.callback_query(F.data.startswith("bp_lvl_"))
async def callback_bp_level(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    bp_id = int(parts[2])
    req_level = int(parts[3])
    user_id = callback.from_user.id
    
    bp = await fetch_one("SELECT * FROM battle_passes WHERE id = ?", (bp_id,))
    user_bp = await fetch_one("SELECT level FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    user_curr_lvl = user_bp['level'] if user_bp else 0
    
    lvl_data = await fetch_one("SELECT id, xp_required FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, req_level))
    if not lvl_data:
        return await callback.answer("Уровень не найден!", show_alert=True)
        
    rewards = await fetch_all("SELECT * FROM bp_rewards WHERE level_id = ?", (lvl_data['id'],))
    
    text = (
        f"🏆 <b>{bp['title']} | Уровень {req_level}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Требуется Опыта (XP): {lvl_data['xp_required']}</i>\n\n"
        f"🎁 <b>Награды за уровень:</b>\n"
    )
    
    if not rewards:
        text += "└ <i>Наград нет.</i>\n"
    else:
        for r in rewards:
            if r['reward_type'] == 'shekels':
                text += f"└ 💰 <b>{r['amount']} Шекелей</b>\n"
            elif r['reward_type'] == 'card':
                c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['card_id'],))
                n = c['name'] if c else "Неизвестная карта"
                mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                text += f"└ 🃏 <b>{mut} {n}</b>\n"
                
    text += "\n📊 <b>Статус:</b> "
    is_reached = user_curr_lvl >= req_level
    claim_check = await fetch_one("SELECT * FROM user_bp_claims WHERE user_id = ? AND bp_id = ? AND level = ?", (user_id, bp_id, req_level))
    is_claimed = bool(claim_check)
    
    if is_claimed: text += "✅ <i>Уже получено</i>"
    elif is_reached: text += "🎁 <b>ДОСТУПНО ДЛЯ ПОЛУЧЕНИЯ!</b>"
    else: text += "🔒 <i>Уровень не достигнут</i>"
    
    kb = []
    if is_reached and not is_claimed and rewards:
        kb.append([InlineKeyboardButton(text="🎁 ЗАБРАТЬ НАГРАДУ", callback_data=f"bp_claim_{bp_id}_{req_level}")])
        
    nav_row = []
    max_lvl = await fetch_one("SELECT MAX(level) as m FROM bp_levels WHERE bp_id = ?", (bp_id,))
    max_l = max_lvl['m'] if max_lvl and max_lvl['m'] else 1
    
    if req_level > 1: nav_row.append(InlineKeyboardButton(text="⬅️ Прошлый", callback_data=f"bp_lvl_{bp_id}_{req_level-1}"))
    if req_level < max_l: nav_row.append(InlineKeyboardButton(text="Следующий ➡️", callback_data=f"bp_lvl_{bp_id}_{req_level+1}"))
    if nav_row: kb.append(nav_row)
    
    kb.append([InlineKeyboardButton(text="🔙 Вернуться к Батл-пассу", callback_data=f"bp_view_{bp_id}")])
    
    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except:
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("bp_claim_"))
async def callback_bp_claim(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    bp_id = int(parts[2])
    req_level = int(parts[3])
    user_id = callback.from_user.id
    
    user_bp = await fetch_one("SELECT level FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    if not user_bp or user_bp['level'] < req_level:
        return await callback.answer("❌ Уровень еще не достигнут!", show_alert=True)
        
    claim_check = await fetch_one("SELECT * FROM user_bp_claims WHERE user_id = ? AND bp_id = ? AND level = ?", (user_id, bp_id, req_level))
    if claim_check:
        return await callback.answer("❌ Награда уже была получена!", show_alert=True)
        
    lvl_data = await fetch_one("SELECT id FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, req_level))
    if not lvl_data: return await callback.answer("Ошибка БД.", show_alert=True)
    
    rewards = await fetch_all("SELECT * FROM bp_rewards WHERE level_id = ?", (lvl_data['id'],))
    if not rewards: return await callback.answer("На этом уровне нет наград.", show_alert=True)
    
    for r in rewards:
        if r['reward_type'] == 'shekels':
            await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (r['amount'], user_id))
        elif r['reward_type'] == 'card':
            await give_card_to_user(user_id, r['card_id'], r['mutation'])
            
    await execute_db("INSERT INTO user_bp_claims (user_id, bp_id, level) VALUES (?, ?, ?)", (user_id, bp_id, req_level))
    await callback.answer("🎉 Вы успешно забрали награды!", show_alert=True)
    await callback_bp_level(callback)

# ========================================================================
# БОЕВОЙ ДВИЖОК, БАЛАНС И ОПЫТ БП (С УЧЕТОМ ИВЕНТОВ МОНЕТ И ОПЫТА ИИ)
# ========================================================================
async def get_team_data(user_id: int):
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (user_id,))
    team = []
    
    slots = ['equip1', 'equip2', 'equip3']
    for slot in slots:
        inv_id = user[slot]
        if inv_id != 0:
            row = await fetch_one("""
                SELECT c.id, c.name, c.rarity, c.class_type, c.damage, c.hp, c.booster_dmg_mult, c.booster_hp_mult,
                       i.mutation, i.serial_number, i.signed_by
                FROM inventory i
                JOIN cards c ON i.card_id = c.id
                WHERE i.id = ? AND i.user_id = ? AND i.count > 0
            """, (inv_id, user_id))
            
            if row:
                card = dict(row)
                mult = get_mutation_multiplier(card['mutation'])
                
                card['damage'] = int(card['damage'] * mult)
                card['hp'] = int(card['hp'] * mult)
                if card['class_type'] == 'Booster':
                    card['booster_dmg_mult'] = round(card['booster_dmg_mult'] * mult, 2)
                    card['booster_hp_mult'] = round(card['booster_hp_mult'] * mult, 2)
                    
                if card['signed_by'] > 0:
                    signer_info = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (card['signed_by'],))
                    card['signer_name'] = get_display_name(signer_info) if signer_info else f"ID:{card['signed_by']}"

                card['max_hp'] = card['hp']
                card['burn'] = 0     
                card['dmg_buff'] = 0 
                team.append(card)
            else:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ?", (user_id,))
    return team

async def get_bot_team(user_id: int, difficulty_mult: float, rank_name: str, diff_type: str = "med"):
    all_cards = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards")
    if len(all_cards) < 3: return []
    
    by_rarity = {}
    for c in all_cards:
        by_rarity.setdefault(c['rarity'], []).append(c)
        
    base_rank = rank_name.split()[0]
    team_selection = []
    
    for _ in range(3):
        r = random.random()
        pool = []
        
        if diff_type == "nightmare":
            if base_rank == "Bronze":
                pool = by_rarity.get('Uncommon', []) + by_rarity.get('Rare', []) + (by_rarity.get('Epic', []) if r < 0.2 else [])
            elif base_rank == "Silver":
                pool = by_rarity.get('Rare', []) + by_rarity.get('Epic', []) + (by_rarity.get('Legendary', []) if r < 0.2 else [])
            elif base_rank == "Gold":
                pool = by_rarity.get('Epic', []) + by_rarity.get('Legendary', []) + (by_rarity.get('Mythic', []) if r < 0.2 else [])
            elif base_rank == "Platina":
                pool = by_rarity.get('Legendary', []) + by_rarity.get('Mythic', []) + (by_rarity.get('Super', []) + by_rarity.get('Leaderboard', []) if r < 0.3 else [])
            elif base_rank == "Diamond":
                pool = by_rarity.get('Mythic', []) + by_rarity.get('Super', []) + by_rarity.get('Leaderboard', [])
            elif base_rank == "Ruby":
                pool = by_rarity.get('Super', []) + by_rarity.get('Leaderboard', []) + (by_rarity.get('Mythic', []) if r < 0.1 else [])
        else:
            small_chance = min(0.3, 0.05 * difficulty_mult)
            if base_rank == "Bronze":
                if r < small_chance and 'Rare' in by_rarity: pool = by_rarity['Rare']
                else: pool = by_rarity.get('Basic', []) + by_rarity.get('Uncommon', [])
            elif base_rank == "Silver":
                if r < small_chance and 'Epic' in by_rarity: pool = by_rarity['Epic']
                else: pool = by_rarity.get('Uncommon', []) + by_rarity.get('Rare', [])
            elif base_rank == "Gold":
                if r < small_chance and 'Legendary' in by_rarity: pool = by_rarity['Legendary']
                else: pool = by_rarity.get('Rare', []) + by_rarity.get('Epic', [])
            elif base_rank == "Platina":
                if r < small_chance and 'Mythic' in by_rarity: pool = by_rarity['Mythic']
                else: pool = by_rarity.get('Epic', []) + by_rarity.get('Legendary', [])
            elif base_rank == "Diamond":
                if r < small_chance and 'Super' in by_rarity: pool = by_rarity['Super']
                else: pool = by_rarity.get('Legendary', []) + by_rarity.get('Mythic', [])
            elif base_rank == "Ruby":
                pool = by_rarity.get('Mythic', []) + by_rarity.get('Super', [])
        
        if not pool:
            pool = [c for c in all_cards if c['rarity'] != 'Leaderboard']
            if not pool: pool = all_cards
            
        team_selection.append(random.choice(pool))
        
    team_copies = []
    for c in team_selection:
        c_copy = dict(c)
        c_copy['max_hp'] = c_copy['hp']
        
        mut_chance = random.random()
        # ========================================================================
        # REBALАНС МУТАЦИЙ ИИ (ПЛАТИНА, ДАЙМОНД, РУБИН ТЕПЕРЬ ПОЛУЧАЮТ МЕНЬШЕ РАДУГИ/ГОЛДЫ)
        # ========================================================================
        if difficulty_mult >= 1.0 or diff_type == "nightmare": 
            rainbow_prob = min(0.04, 0.015 * difficulty_mult) # Кап 4% вместо бесконечного роста
            gold_prob = min(0.18, 0.07 * difficulty_mult)     # Кап 18% вместо 45%
            
            if mut_chance < rainbow_prob: 
                c_copy['mutation'] = "Rainbow"
                c_copy['damage'] = int(c_copy['damage'] * 1.2)
                c_copy['hp'] = int(c_copy['hp'] * 1.2)
            elif mut_chance < rainbow_prob + gold_prob: 
                c_copy['mutation'] = "Gold"
                c_copy['damage'] = int(c_copy['damage'] * 1.1)
                c_copy['hp'] = int(c_copy['hp'] * 1.1)
            else: 
                c_copy['mutation'] = "Normal"
        else:
            c_copy['mutation'] = "Normal"
            
        c_copy['max_hp'] = c_copy['hp']
        c_copy['burn'] = 0
        c_copy['dmg_buff'] = 0
        c_copy['serial_number'] = 0
        c_copy['signed_by'] = 0
        team_copies.append(c_copy)
        
    return team_copies

def format_combat_team_vertical(team):
    if not team: return "<i>Все мертвы</i>"
    res = []
    for c in team:
        if c['hp'] <= 0:
            res.append(f"💀 <s>{c['name']}</s>")
            continue
        status = ""
        if c.get('mutation') == 'Rainbow': status += "🌈"
        elif c.get('mutation') == 'Gold': status += "⭐"
        if c.get('burn', 0) > 0: status += "🔥"
        if c.get('dmg_buff', 0) > 0: status += "✨"
        if c['class_type'] == 'Booster': status += "🔋"
        
        s_str = f" [#{c['serial_number']:04d}]" if c.get('serial_number', 0) > 0 else ""
        sgn_str = ""
        if c.get('signed_by', 0) > 0:
            s_name = c.get('signer_name') or f"ID:{c['signed_by']}"
            sgn_str = f" ✍️ Sign: {s_name}"
            
        dmg = c['damage'] + c.get('dmg_buff', 0)
        res.append(f"• {c['name']}{s_str}{sgn_str}{status} (⚔️{dmg} | ❤️{c['hp']}/{c['max_hp']})")
    return "\n".join(res)

def build_battle_header(p1_name, t1, p2_name, t2):
    return (
        f"⚔️ <b>АРЕНА: БИТВА</b> ⚔️\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔵 <b>Команда {p1_name}:</b>\n{format_combat_team_vertical(t1)}\n\n"
        f"🔴 <b>Команда {p2_name}:</b>\n{format_combat_team_vertical(t2)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📜 <b>Лог боя:</b>\n"
    )

def apply_boosters(team, team_name, log):
    boosters = [c for c in team if c['class_type'] == 'Booster']
    if not boosters: return
    for b in boosters:
        d_mult = b['booster_dmg_mult']
        h_mult = b['booster_hp_mult']
        log.append(f"✨ <b>{team_name}:</b> Бустер <b>{b['name']}</b> усиливает команду! (Урон x{d_mult}, ХП x{h_mult})")
        for c in team:
            bonus_hp = int(c['hp'] * h_mult) - c['hp']
            if bonus_hp > 0:
                c['hp'] += bonus_hp
                c['max_hp'] += bonus_hp
            if c['class_type'] != 'Booster':
                c['dmg_buff'] += int(c['damage'] * d_mult) - c['damage']

async def process_burns(team, team_name, log):
    for c in team:
        if c['hp'] > 0 and c.get('burn', 0) > 0:
            c['hp'] -= c['burn']
            log_str = f"🔥 {team_name}: <b>{c['name']}</b> получает {c['burn']} урона от горения!"
            if c['hp'] <= 0:
                c['hp'] = 0
                log_str += " ☠️ <i>Сгорел дотла!</i>"
            log.append(log_str)
            c['burn'] = 0

async def execute_turn(atk_team, def_team, atk_name, def_name, log):
    await process_burns(atk_team, atk_name, log)
    atk_alive = [c for c in atk_team if c['hp'] > 0]
    def_alive = [c for c in def_team if c['hp'] > 0]
    if not atk_alive or not def_alive: return False
    
    atk = random.choice(atk_alive)
    base_dmg = atk['damage'] + atk.get('dmg_buff', 0)
    c_type = atk['class_type']
    
    if c_type == "Booster":
        target = random.choice(def_alive)
        dmg = max(10, int(target['max_hp'] * 0.1))
        target['hp'] -= dmg
        log_str = f"🔋 {atk_name}: <b>{atk['name']}</b> пускает заряд в <b>{target['name']}</b> на {dmg}!"
        if target['hp'] <= 0: target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
        log.append(log_str)
        
    elif c_type == "AOE":
        log_str = f"🌪 {atk_name}: <b>{atk['name']}</b> бьет по всем на {base_dmg}!"
        for d in def_alive:
            d['hp'] -= base_dmg
            if d['hp'] <= 0: d['hp'] = 0; log_str += f" ☠️ <i>{d['name']} мертв!</i>"
        log.append(log_str)
        
    elif c_type == "Splash":
        main_t = random.choice(def_alive)
        splash_dmg = int(base_dmg * 0.5)
        log_str = f"🌊 {atk_name}: <b>{atk['name']}</b> наносит {base_dmg} по <b>{main_t['name']}</b> и {splash_dmg} остальным!"
        for d in def_alive:
            dmg = base_dmg if d == main_t else splash_dmg
            d['hp'] -= dmg
            if d['hp'] <= 0: d['hp'] = 0; log_str += f" ☠️ <i>{d['name']} мертв!</i>"
        log.append(log_str)
        
    elif c_type == "Fire":
        target = random.choice(def_alive)
        target['hp'] -= base_dmg
        target['burn'] = target.get('burn', 0) + base_dmg
        log_str = f"🔥 {atk_name}: <b>{atk['name']}</b> бьет <b>{target['name']}</b> на {base_dmg} и поджигает!"
        if target['hp'] <= 0: target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
        log.append(log_str)
        
    else:
        target = random.choice(def_alive)
        target['hp'] -= base_dmg
        log_str = f"🎯 {atk_name}: <b>{atk['name']}</b> наносит {base_dmg} по <b>{target['name']}</b>!"
        if target['hp'] <= 0: target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
        log.append(log_str)
        
    return True

async def get_dynamic_trophies(rank_name: str, diff_scale: float = 1.0) -> int:
    ranks = await fetch_all("SELECT name FROM ranks ORDER BY min_trophies ASC")
    rank_idx = next((i for i, r in enumerate(ranks) if r['name'] == rank_name), 0)
    base = max(1, 15 - int((rank_idx / 21) * 14)) 
    won = random.randint(max(1, base-1), base+1)
    return int(won * diff_scale)

async def add_bp_xp(user_id: int, xp_to_add: int) -> tuple:
    db = await get_db_connection()
    try:
        user_bp = await db.execute("SELECT bp_id, level, xp FROM user_bp WHERE user_id = ? AND is_active = 1", (user_id,))
        ubp = await user_bp.fetchone()
        if not ubp: return False, None, 0
        
        bp_id = ubp['bp_id']
        curr_lvl = ubp['level']
        curr_xp = ubp['xp'] + xp_to_add
        level_up = False
        
        while True:
            next_lvl = await db.execute("SELECT xp_required FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, curr_lvl + 1))
            nl = await next_lvl.fetchone()
            if not nl: break 
            
            if curr_xp >= nl['xp_required']:
                curr_lvl += 1
                curr_xp -= nl['xp_required']
                level_up = True
            else:
                break
                
        await db.execute("UPDATE user_bp SET level = ?, xp = ? WHERE user_id = ? AND bp_id = ?", (curr_lvl, curr_xp, user_id, bp_id))
        bp_info = await db.execute("SELECT title FROM battle_passes WHERE id = ?", (bp_id,))
        bp = await bp_info.fetchone()
        
        await db.commit()
        return level_up, bp['title'] if bp else "Батл-пасс", curr_lvl
    finally:
        await db.close()

async def run_battle_loop(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_id: int, p2_name: str, t1: list, t2: list, diff_trophies_scale: float = 1.0, diff_bp_mult: float = 1.0, is_pvp: bool = False, pvp_no_rewards: bool = False):
    msg = await bot.send_message(chat_id, f"⚔️ Бой <b>{p1_name}</b> VS <b>{p2_name}</b> начнется через 3 сек!")
    await asyncio.sleep(1)
    await msg.edit_text(f"⚔️ Бой начнется через 2 сек!")
    await asyncio.sleep(1)
    await msg.edit_text(f"⚔️ Бой начнется через 1 сек!")
    
    log = []
    apply_boosters(t1, p1_name, log)
    apply_boosters(t2, p2_name, log)
    
    if log:
        await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
        await asyncio.sleep(3)

    turn = 1
    winner = None
    
    while True:
        t1_alive = [c for c in t1 if c['hp'] > 0]
        t2_alive = [c for c in t2 if c['hp'] > 0]
        
        if not t1_alive and not t2_alive:
            winner = "Ничья"; break
        elif not t1_alive:
            winner = p2_name; winner_id = p2_id; loser_id = p1_id; break
        elif not t2_alive:
            winner = p1_name; winner_id = p1_id; loser_id = p2_id; break
            
        if turn > 30:
            winner = "Ничья по таймауту"; break

        did_turn = await execute_turn(t1, t2, p1_name, p2_name, log)
        if did_turn:
            if len(log) > 6: log = log[-6:]
            await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
            await asyncio.sleep(3)

        t2_alive = [c for c in t2 if c['hp'] > 0]
        if t2_alive:
            did_turn = await execute_turn(t2, t1, p2_name, p1_name, log)
            if did_turn:
                if len(log) > 6: log = log[-6:]
                await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
                await asyncio.sleep(3)
        turn += 1

    await add_quest_progress(p1_id, 'q_battles', 1)
    if winner == p1_name:
        await add_quest_progress(p1_id, 'q_wins', 1)
        
    if is_pvp:
        await add_quest_progress(p2_id, 'q_battles', 1)
        if winner == p2_name:
            await add_quest_progress(p2_id, 'q_wins', 1)

    final_text = f"🏁 <b>ИТОГИ БОЯ: {p1_name} VS {p2_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n👑 <b>Победитель: {winner}</b>\n\n"
    
    bp_messages = []
    
    if pvp_no_rewards:
        final_text += "🤝 <b>Дружеская дуэль завершена!</b> Награды и кубки не начислялись."
    elif is_pvp:
        if winner not in ["Ничья", "Ничья по таймауту"]:
            await execute_db("UPDATE users SET trophies = trophies + 15 WHERE id = ?", (winner_id,))
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 10) WHERE id = ?", (loser_id,))
            final_text += f"🏆 Победитель забирает <b>+15 Кубков</b>\n💀 Проигравший теряет <b>-10 Кубков</b>"
    else:
        # Учитываем новые мультипликаторы ивентов монет и опыта БП
        coin_mult, xp_mult_event = await get_coin_xp_events()
        
        if winner == p1_name:
            user = await fetch_one("SELECT trophies FROM users WHERE id = ?", (p1_id,))
            rank = await get_user_rank(user['trophies'])
            
            coins_won = int(random.randint(25, 90) * rank['reward_mult'] * diff_trophies_scale * 0.85 * coin_mult)
            won_t = await get_dynamic_trophies(rank['name'], diff_trophies_scale)
            
            await execute_db("UPDATE users SET coins = coins + ?, trophies = trophies + ? WHERE id = ?", (coins_won, won_t, p1_id))
            final_text += f"🎉 <b>Награды за победу:</b>\n💰 {coins_won} Шекелей"
            if coin_mult > 1.0:
                final_text += f" <i>(Ивент монет x{coin_mult}!)</i>"
            final_text += f"\n🏆 {won_t} Кубков\n"
            
            bp_xp = int(20 * diff_bp_mult * xp_mult_event)
            lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp)
            final_text += f"🎫 +{bp_xp} Опыта БП"
            if xp_mult_event > 1.0:
                final_text += f" <i>(Ивент опыта БП x{xp_mult_event}!)</i>"
            if lvl_up: bp_messages.append(f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> Вы достигли {new_lvl} уровня в сезоне «{bp_title}»! Зайдите в меню Батл-пассов за наградой.")
            
        elif winner == p2_name:
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 2) WHERE id = ?", (p1_id,))
            final_text += f"💀 Вы проиграли ИИ и потеряли <b>2 🏆</b>.\n"
            bp_xp = int(5 * diff_bp_mult * xp_mult_event)
            lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp)
            final_text += f"🎫 +{bp_xp} Опыта БП (Утешительный приз)"
            if xp_mult_event > 1.0:
                final_text += f" <i>(Ивент опыта БП x{xp_mult_event}!)</i>"
            if lvl_up: bp_messages.append(f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> Вы достигли {new_lvl} уровня в сезоне «{bp_title}»! Зайдите в меню Батл-пассов за наградой.")
            
    await msg.edit_text(final_text)
    
    for b_msg in bp_messages:
        try: await bot.send_message(p1_id, b_msg)
        except: pass
        
    active_combats.discard(p1_id)
    if is_pvp: active_combats.discard(p2_id)

@dp.message(F.text.in_(BTN_PVE))
async def cmd_pve_select(message: types.Message):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats:
        return await message.answer("❌ Вы уже находитесь в бою или в поиске!")
    if message.from_user.id in user_trades:
        return await message.answer("❌ Завершите активный обмен перед боем!")
        
    team1 = await get_team_data(message.from_user.id)
    if not team1: return await message.answer("❌ Боевая колода пуста! Зайдите в раздел 🛡 Экипировка.")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Лёгкий (-50% Кубки, -20% XP)", callback_data="pve_diff_easy")],
        [InlineKeyboardButton(text="🟡 Средний (Стандарт)", callback_data="pve_diff_med")],
        [InlineKeyboardButton(text="🔴 Сложный (+50% Кубки, +20% XP)", callback_data="pve_diff_hard")],
        [InlineKeyboardButton(text="☠️ Кошмар (+80% Кубки, +50% XP)", callback_data="pve_diff_nightmare")]
    ])
    await message.answer("⚔️ <b>ВЫБОР СЛОЖНОСТИ ИИ:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━", reply_markup=kb)

@dp.callback_query(F.data.startswith("pve_diff_"))
async def cmd_pve_battle(callback: types.CallbackQuery):
    if callback.from_user.id in active_combats or callback.from_user.id in user_trades:
        return await callback.answer("❌ Вы уже в бою или обмене!", show_alert=True)
        
    diff_type = callback.data.split("_")[2]
    power_mult = 1.0
    trophies_scale = 1.0
    bp_xp_mult = 1.0
    diff_name = "Средний"
    
    if diff_type == "easy":
        power_mult = 0.7  
        trophies_scale = 0.5
        bp_xp_mult = 0.8
        diff_name = "Лёгкий 🟢"
    elif diff_type == "med":
        power_mult = 1.1  
        trophies_scale = 1.0
        bp_xp_mult = 1.0
        diff_name = "Средний 🟡"
    elif diff_type == "hard":
        power_mult = 1.6  
        trophies_scale = 1.5
        bp_xp_mult = 1.2
        diff_name = "Сложный 🔴"
    elif diff_type == "nightmare":
        power_mult = 2.0
        trophies_scale = 1.8
        bp_xp_mult = 1.5
        diff_name = "Кошмар ☠️"
        
    await callback.message.edit_text(f"⚔️ <i>Ищем достойного противника... Сложность: <b>{diff_name}</b></i>")
    
    team1 = await get_team_data(callback.from_user.id)
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    rank = await get_user_rank(user['trophies'])
    
    final_diff_mult = rank['difficulty_mult'] * power_mult
    team2 = await get_bot_team(callback.from_user.id, final_diff_mult, rank['name'], diff_type)
    
    if not team2: return await callback.message.edit_text("❌ На сервере нет карт для генерации бота.")
        
    title_str = await get_user_titles_str(callback.from_user.id)
    p1_name = get_display_name(user) + title_str
    active_combats.add(callback.from_user.id)
    
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, callback.from_user.id, p1_name, 0, f"ИИ ({diff_name})", team1, team2, trophies_scale, bp_xp_mult, is_pvp=False))
    await callback.answer()

# ========================================================================
# ДУЭЛИ (PVP) СИНХРОННЫЕ
# ========================================================================
@dp.message(F.text.in_(BTN_PVP))
async def cmd_pvp_request_start(message: types.Message, state: FSMContext):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats or message.from_user.id in user_trades:
        return await message.answer("❌ Вы уже в бою или обмене!")
    await message.answer("⚔️ <b>PvP ДУЭЛЬ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВведите @username или ID игрока, которого вы хотите вызвать на дружескую дуэль:")
    await state.set_state(PvPState.waiting_target)

@dp.message(PvPState.waiting_target)
async def process_pvp_target(message: types.Message, state: FSMContext):
    val = message.text.strip()
    target_user = None
    
    if val.isdigit():
        target_user = await fetch_one("SELECT * FROM users WHERE id = ?", (int(val),))
    else:
        target_username = val.lstrip('@')
        target_user = await fetch_one("SELECT * FROM users WHERE username = ?", (target_username,))
        
    if not target_user:
        await state.clear()
        return await message.answer("❌ Данный игрок не зарегистрирован в боте.")
        
    if target_user['id'] == message.from_user.id:
        await state.clear()
        return await message.answer("❌ Вы не можете вызвать самого себя!")
        
    if target_user['id'] in active_combats or target_user['id'] in user_trades:
        await state.clear()
        return await message.answer("❌ Игрок сейчас занят (в бою или обмене)!")

    challenger = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    challenger_name = get_display_name(challenger)
    title_str = await get_user_titles_str(message.from_user.id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚔️ Принять вызов", callback_data=f"pvp_accept_{challenger['id']}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pvp_decline_{challenger['id']}")
        ]
    ])
    
    try:
        await bot.send_message(
            target_user['id'], 
            f"⚔️ Игрок <b>{challenger_name}</b>{title_str} вызывает вас на дружескую дуэль!\n\n<i>Для принятия вызова у вас должна быть собрана Боевая колода (в Экипировке).</i>",
            reply_markup=kb
        )
        await message.answer(f"📨 Вызов успешно отправлен игроку {get_display_name(target_user)}. Ждем ответа...")
    except Exception:
        await message.answer("❌ Не удалось отправить уведомление игроку (возможно, бот заблокирован).")
    await state.clear()

@dp.callback_query(F.data.startswith("pvp_accept_"))
async def callback_pvp_accept(callback: types.CallbackQuery):
    challenger_id = int(callback.data.split("_")[2])
    target_id = callback.from_user.id
    
    if target_id in active_combats or challenger_id in active_combats or target_id in user_trades or challenger_id in user_trades:
        return await callback.answer("❌ Один из игроков уже находится в бою или обмене!", show_alert=True)
        
    t1 = await get_team_data(challenger_id)
    t2 = await get_team_data(target_id)
    
    if not t1:
        return await callback.message.edit_text("❌ У вызывающего игрока пустая колода экипировки! Дуэль отменена.")
    if not t2:
        return await callback.message.edit_text("❌ У вас не экипирована колода! Зайдите в раздел 🛡 Экипировка и примите вызов заново.")
        
    challenger = await fetch_one("SELECT * FROM users WHERE id = ?", (challenger_id,))
    target = await fetch_one("SELECT * FROM users WHERE id = ?", (target_id,))
    
    title_p1 = await get_user_titles_str(challenger_id)
    title_p2 = await get_user_titles_str(target_id)
    p1_name = get_display_name(challenger) + title_p1
    p2_name = get_display_name(target) + title_p2
    
    active_combats.add(challenger_id)
    active_combats.add(target_id)
    
    asyncio.create_task(run_pvp_dual_broadcast(challenger_id, target_id, p1_name, p2_name, t1, t2))
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("pvp_decline_"))
async def callback_pvp_decline(callback: types.CallbackQuery):
    challenger_id = int(callback.data.split("_")[2])
    target = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    try:
        await bot.send_message(challenger_id, f"❌ Игрок {get_display_name(target)} отклонил ваш вызов на дуэль.")
    except: pass
    await callback.message.edit_text("❌ Вы отклонили вызов на дуэль.")
    await callback.answer()

async def run_pvp_dual_broadcast(p1_id: int, p2_id: int, p1_name: str, p2_name: str, t1: list, t2: list):
    msg1 = await bot.send_message(p1_id, f"⚔️ Дуэль против <b>{p2_name}</b> начнется через 3 сек!")
    msg2 = await bot.send_message(p2_id, f"⚔️ Дуэль против <b>{p1_name}</b> начнется через 3 сек!")
    await asyncio.sleep(1)
    await msg1.edit_text("⚔️ Бой начнется через 2 сек!")
    await msg2.edit_text("⚔️ Бой начнется через 2 сек!")
    await asyncio.sleep(1)
    await msg1.edit_text("⚔️ Бой начнется через 1 сек!")
    await msg2.edit_text("⚔️ Бой начнется через 1 сек!")
    await asyncio.sleep(1)
    
    log = []
    apply_boosters(t1, p1_name, log)
    apply_boosters(t2, p2_name, log)
    
    if log:
        header = build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log)
        await msg1.edit_text(header)
        await msg2.edit_text(header)
        await asyncio.sleep(3)

    turn = 1
    winner = None
    
    while True:
        t1_alive = [c for c in t1 if c['hp'] > 0]
        t2_alive = [c for c in t2 if c['hp'] > 0]
        
        if not t1_alive and not t2_alive:
            winner = "Ничья"; break
        elif not t1_alive:
            winner = p2_name; break
        elif not t2_alive:
            winner = p1_name; break
            
        if turn > 30:
            winner = "Ничья по таймауту"; break

        did_turn = await execute_turn(t1, t2, p1_name, p2_name, log)
        if did_turn:
            if len(log) > 6: log = log[-6:]
            header = build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log)
            try: await msg1.edit_text(header)
            except: pass
            try: await msg2.edit_text(header)
            except: pass
            await asyncio.sleep(3)

        t2_alive = [c for c in t2 if c['hp'] > 0]
        if t2_alive:
            did_turn = await execute_turn(t2, t1, p2_name, p1_name, log)
            if did_turn:
                if len(log) > 6: log = log[-6:]
                header = build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log)
                try: await msg1.edit_text(header)
                except: pass
                try: await msg2.edit_text(header)
                except: pass
                await asyncio.sleep(3)
        turn += 1

    final_text = (
        f"🏁 <b>ИТОГИ ДУЭЛИ: {p1_name} VS {p2_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 <b>Победитель: {winner}</b>\n\n"
        f"🤝 Награды и кубки за товарищеский бой не начисляются!"
    )
    
    try: await msg1.edit_text(final_text)
    except: pass
    try: await msg2.edit_text(final_text)
    except: pass
    
    active_combats.discard(p1_id)
    active_combats.discard(p2_id)

# ========================================================================
# ТРЕЙДЫ (БЕЗОПАСНЫЙ ОБМЕН КАРТАМИ С ТРАНЗАКЦИЯМИ И ДВОЙНЫМ ПОДТВЕРЖДЕНИЕМ)
# ========================================================================
@dp.message(Command("trade"))
async def cmd_trade_request(message: types.Message, state: FSMContext):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats or message.from_user.id in user_trades:
        return await message.answer("❌ Вы уже находитесь в бою или обмене!")
        
    parts = message.text.split()
    if len(parts) > 1:
        message.text = parts[1]
        await process_trade_target(message, state)
    else:
        await message.answer("🤝 <b>ОБМЕН КАРТАМИ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВведите @username или ID игрока, которому хотите предложить обмен:")
        await state.set_state(TradeState.waiting_target)

@dp.message(TradeState.waiting_target)
async def process_trade_target(message: types.Message, state: FSMContext):
    val = message.text.strip()
    target_user = None
    
    if val.isdigit():
        target_user = await fetch_one("SELECT * FROM users WHERE id = ?", (int(val),))
    else:
        target_username = val.lstrip('@')
        target_user = await fetch_one("SELECT * FROM users WHERE username = ?", (target_username,))
        
    if not target_user:
        await state.clear()
        return await message.answer("❌ Данный игрок не зарегистрирован в боте.")
        
    if target_user['id'] == message.from_user.id:
        await state.clear()
        return await message.answer("❌ Вы не можете торговать с самим собой!")
        
    if target_user['id'] in active_combats or target_user['id'] in user_trades:
        await state.clear()
        return await message.answer("❌ Игрок сейчас занят (в бою или уже торгуется)!")

    challenger = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    title_str = await get_user_titles_str(message.from_user.id)
    challenger_name = get_display_name(challenger) + title_str
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Принять трейд", callback_data=f"tr_acc_{challenger['id']}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"tr_dec_{challenger['id']}")
        ]
    ])
    
    try:
        await bot.send_message(
            target_user['id'], 
            f"🤝 Игрок <b>{challenger_name}</b> предлагает вам обмен картами!",
            reply_markup=kb
        )
        await message.answer(f"📨 Запрос на трейд отправлен игроку {get_display_name(target_user)}. Ждем ответа...")
    except Exception:
        await message.answer("❌ Не удалось отправить уведомление игроку (возможно, бот заблокирован).")
    await state.clear()

@dp.callback_query(F.data.startswith("tr_acc_"))
async def callback_trade_accept(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[2])
    p2_id = callback.from_user.id
    
    if p1_id in user_trades or p2_id in user_trades or p1_id in active_combats or p2_id in active_combats:
        return await callback.answer("❌ Один из игроков уже занят!", show_alert=True)
        
    p1 = await fetch_one("SELECT * FROM users WHERE id = ?", (p1_id,))
    p2 = await fetch_one("SELECT * FROM users WHERE id = ?", (p2_id,))
    
    title_p1 = await get_user_titles_str(p1_id)
    title_p2 = await get_user_titles_str(p2_id)
    
    trade_id = f"tr_{p1_id}_{p2_id}_{int(time.time())}"
    trade = {
        'id': trade_id,
        'p1': p1_id, 'p2': p2_id,
        'p1_name': get_display_name(p1) + title_p1, 
        'p2_name': get_display_name(p2) + title_p2,
        'p1_offer': {}, 'p2_offer': {},  
        'p1_strings': {}, 'p2_strings': {}, 
        'p1_ready': False, 'p2_ready': False,
        'p1_confirmed': False, 'p2_confirmed': False,
        'p1_msg': None, 'p2_msg': None,
        'start_time': time.time(),
        'status': 'ongoing'
    }
    
    active_trades[trade_id] = trade
    user_trades[p1_id] = trade_id
    user_trades[p2_id] = trade_id
    
    text = await render_trade_text(trade)
    
    try:
        msg1 = await bot.send_message(p1_id, text, reply_markup=get_trade_main_kb(trade, p1_id))
        trade['p1_msg'] = msg1.message_id
    except: pass
    
    try:
        msg2 = await bot.send_message(p2_id, text, reply_markup=get_trade_main_kb(trade, p2_id))
        trade['p2_msg'] = msg2.message_id
    except: pass
    
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_dec_"))
async def callback_trade_decline(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[2])
    p2 = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    try:
        await bot.send_message(p1_id, f"❌ Игрок {get_display_name(p2)} отклонил ваш трейд.")
    except: pass
    await callback.message.edit_text("❌ Вы отклонили трейд.")
    await callback.answer()

async def render_trade_text(trade):
    text = f"🤝 <b>ТОРГОВАЯ КОМНАТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    text += f"🔵 <b>Предлагает {trade['p1_name']}:</b>\n"
    if not trade['p1_offer']: text += "  └ <i>Ничего не предложено</i>\n"
    else:
        for inv_id, qty in trade['p1_offer'].items():
            text += f"  └ {qty}x {trade['p1_strings'].get(inv_id, 'Неизвестно')}\n"
            
    text += f"\n🔴 <b>Предлагает {trade['p2_name']}:</b>\n"
    if not trade['p2_offer']: text += "  └ <i>Ничего не предложено</i>\n"
    else:
        for inv_id, qty in trade['p2_offer'].items():
            text += f"  └ {qty}x {trade['p2_strings'].get(inv_id, 'Неизвестно')}\n"
            
    p1_st = "✅ Готов" if trade['p1_ready'] else "⏳ Выбирает..."
    p2_st = "✅ Готов" if trade['p2_ready'] else "⏳ Выбирает..."
    
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━\n📊 <b>Статус:</b>\n"
    text += f"{trade['p1_name']}: {p1_st}\n"
    text += f"{trade['p2_name']}: {p2_st}\n"
    text += f"<i>(Трейд автоматически отменится через 10 минут)</i>"
    return text

def get_trade_main_kb(trade, user_id):
    if trade['status'] != 'ongoing': return None
    
    kb = []
    if trade['p1_ready'] and trade['p2_ready']:
        is_conf = trade['p1_confirmed'] if user_id == trade['p1'] else trade['p2_confirmed']
        if is_conf:
            kb.append([InlineKeyboardButton(text="⏳ Ожидание второго игрока...", callback_data="ignore")])
        else:
            kb.append([InlineKeyboardButton(text="🔒 ПОДТВЕРДИТЬ ОБМЕН", callback_data="tr_action_confirm")])
    else:
        kb.append([
            InlineKeyboardButton(text="➕ Добавить", callback_data="tr_menu_add"),
            InlineKeyboardButton(text="➖ Убрать", callback_data="tr_menu_rem")
        ])
        
        is_ready = trade['p1_ready'] if user_id == trade['p1'] else trade['p2_ready']
        if is_ready:
            kb.append([InlineKeyboardButton(text="⏳ Ждем партнера...", callback_data="ignore")])
        else:
            kb.append([InlineKeyboardButton(text="✅ ГОТОВ К ОБМЕНУ", callback_data="tr_action_ready")])
            
    kb.append([InlineKeyboardButton(text="❌ Отменить трейд", callback_data="tr_action_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def update_trade_uis(trade):
    text = await render_trade_text(trade)
    try: await bot.edit_message_text(text, chat_id=trade['p1'], message_id=trade['p1_msg'], reply_markup=get_trade_main_kb(trade, trade['p1']))
    except: pass
    try: await bot.edit_message_text(text, chat_id=trade['p2'], message_id=trade['p2_msg'], reply_markup=get_trade_main_kb(trade, trade['p2']))
    except: pass

@dp.callback_query(F.data.startswith("tr_action_"))
async def cb_trade_actions(callback: types.CallbackQuery):
    action = callback.data.split("_")[2]
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    
    if not trade_id or trade_id not in active_trades:
        return await callback.answer("Трейд не найден или завершен.", show_alert=True)
        
    trade = active_trades[trade_id]
    
    if action == "cancel":
        trade['status'] = 'cancelled'
        try: await bot.edit_message_text("❌ Трейд отменен.", chat_id=trade['p1'], message_id=trade['p1_msg'])
        except: pass
        try: await bot.edit_message_text("❌ Трейд отменен.", chat_id=trade['p2'], message_id=trade['p2_msg'])
        except: pass
        user_trades.pop(trade['p1'], None)
        user_trades.pop(trade['p2'], None)
        active_trades.pop(trade_id, None)
        return await callback.answer()
        
    if action == "ready":
        if user_id == trade['p1']: trade['p1_ready'] = True
        else: trade['p2_ready'] = True
        await update_trade_uis(trade)
        return await callback.answer()
        
    if action == "confirm":
        if user_id == trade['p1']: trade['p1_confirmed'] = True
        else: trade['p2_confirmed'] = True
        
        await update_trade_uis(trade)
        
        if trade['p1_confirmed'] and trade['p2_confirmed']:
            await execute_trade(trade_id)
            
    await callback.answer()

async def cancel_trade(trade_id, reason="Отменен"):
    trade = active_trades.pop(trade_id, None)
    if not trade: return
    user_trades.pop(trade['p1'], None)
    user_trades.pop(trade['p2'], None)
    text = f"❌ <b>Трейд завершен.</b> ({reason})"
    try: await bot.edit_message_text(text, chat_id=trade['p1'], message_id=trade['p1_msg'])
    except: pass
    try: await bot.edit_message_text(text, chat_id=trade['p2'], message_id=trade['p2_msg'])
    except: pass

async def get_inv_item_details(inv_id):
    row = await fetch_one("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.count, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name
        FROM inventory i 
        JOIN cards c ON i.card_id = c.id 
        LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.id = ?
    """, (inv_id,))
    if not row: return None
    if row['signed_by'] != 0:
        row['signer_name'] = get_display_name({'username': row['username'], 'first_name': row['first_name']})
    return row

@dp.callback_query(F.data == "tr_menu_add")
async def cb_trade_menu_add(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer()
    
    trade = active_trades[trade_id]
    offer_dict = trade['p1_offer'] if user_id == trade['p1'] else trade['p2_offer']
    
    trade['p1_ready'] = False; trade['p2_ready'] = False
    trade['p1_confirmed'] = False; trade['p2_confirmed'] = False
    
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name
        FROM inventory i 
        JOIN cards c ON i.card_id = c.id 
        LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.count > 0
    """, (user_id,))
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    
    items = []
    for c in inv:
        avail = c['count'] - offer_dict.get(c['inv_id'], 0)
        if avail > 0:
            if c['signed_by'] != 0: c['signer_name'] = get_display_name({'username': c['username'], 'first_name': c['first_name']})
            n = format_card_name_plain(c)
            mut = "⭐ " if c['mutation'] == 'Gold' else ("🌈 " if c['mutation'] == 'Rainbow' else "")
            items.append({"id": c['inv_id'], "btn_text": f"{mut}{n} (Дост: {avail})"})
            
    kb = get_pagination_keyboard(items, 0, "tr_add", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад к трейду", callback_data="tr_menu_main")])
    
    await callback.message.edit_text("👇 <b>Выберите карту для добавления в обмен:</b>\n<i>Нажмите несколько раз, чтобы добавить больше копий.</i>", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_add_page_"))
async def cb_trade_add_paginate(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer()
    trade = active_trades[trade_id]
    offer_dict = trade['p1_offer'] if user_id == trade['p1'] else trade['p2_offer']
    
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name
        FROM inventory i JOIN cards c ON i.card_id = c.id LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.count > 0
    """, (user_id,))
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    
    items = []
    for c in inv:
        avail = c['count'] - offer_dict.get(c['inv_id'], 0)
        if avail > 0:
            if c['signed_by'] != 0: c['signer_name'] = get_display_name({'username': c['username'], 'first_name': c['first_name']})
            n = format_card_name_plain(c)
            mut = "⭐ " if c['mutation'] == 'Gold' else ("🌈 " if c['mutation'] == 'Rainbow' else "")
            items.append({"id": c['inv_id'], "btn_text": f"{mut}{n} (Дост: {avail})"})
            
    kb = get_pagination_keyboard(items, page, "tr_add", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад к трейду", callback_data="tr_menu_main")])
    try: await callback.message.edit_reply_markup(reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_add_"))
async def cb_trade_do_add(callback: types.CallbackQuery):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer()
    
    trade = active_trades[trade_id]
    offer_dict = trade['p1_offer'] if user_id == trade['p1'] else trade['p2_offer']
    string_dict = trade['p1_strings'] if user_id == trade['p1'] else trade['p2_strings']
    
    row = await get_inv_item_details(inv_id)
    if not row: return await callback.answer("Карта не найдена!", show_alert=True)
    
    avail = row['count'] - offer_dict.get(inv_id, 0)
    if avail <= 0: return await callback.answer("Больше нет в наличии!", show_alert=True)
    
    offer_dict[inv_id] = offer_dict.get(inv_id, 0) + 1
    mut = "⭐ " if row['mutation'] == 'Gold' else ("🌈 " if row['mutation'] == 'Rainbow' else "")
    
    string_dict[inv_id] = f"{mut}{format_card_name_plain(row)}"
    
    trade['p1_ready'] = False; trade['p2_ready'] = False
    trade['p1_confirmed'] = False; trade['p2_confirmed'] = False
    
    await callback.answer(f"Добавлено!")
    await update_trade_uis(trade)

@dp.callback_query(F.data == "tr_menu_rem")
async def cb_trade_menu_rem(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer()
    
    trade = active_trades[trade_id]
    offer_dict = trade['p1_offer'] if user_id == trade['p1'] else trade['p2_offer']
    string_dict = trade['p1_strings'] if user_id == trade['p1'] else trade['p2_strings']
    
    trade['p1_ready'] = False; trade['p2_ready'] = False
    trade['p1_confirmed'] = False; trade['p2_confirmed'] = False
    
    items = []
    for i_id, qty in offer_dict.items():
        if qty > 0:
            items.append({"id": i_id, "btn_text": f"❌ Убрать: {string_dict[i_id]} (В трейде: {qty})"})
            
    kb = get_pagination_keyboard(items, 0, "tr_rem", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад к трейду", callback_data="tr_menu_main")])
    
    await callback.message.edit_text("👇 <b>Выберите карту для удаления из обмена:</b>", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_rem_page_"))
async def cb_trade_rem_paginate(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer()
    
    trade = active_trades[trade_id]
    offer_dict = trade['p1_offer'] if user_id == trade['p1'] else trade['p2_offer']
    string_dict = trade['p1_strings'] if user_id == trade['p1'] else trade['p2_strings']
    
    items = []
    for i_id, qty in offer_dict.items():
        if qty > 0:
            items.append({"id": i_id, "btn_text": f"❌ Убрать: {string_dict[i_id]} (В трейде: {qty})"})
            
    kb = get_pagination_keyboard(items, page, "tr_rem", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад к трейду", callback_data="tr_menu_main")])
    try: await callback.message.edit_reply_markup(reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_rem_"))
async def cb_trade_do_rem(callback: types.CallbackQuery):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer()
    
    trade = active_trades[trade_id]
    offer_dict = trade['p1_offer'] if user_id == trade['p1'] else trade['p2_offer']
    
    if offer_dict.get(inv_id, 0) > 0:
        offer_dict[inv_id] -= 1
        if offer_dict[inv_id] == 0:
            del offer_dict[inv_id]
            
    trade['p1_ready'] = False; trade['p2_ready'] = False
    trade['p1_confirmed'] = False; trade['p2_confirmed'] = False
    
    await callback.answer("Убрано 1 шт.")
    await update_trade_uis(trade)

@dp.callback_query(F.data == "tr_menu_main")
async def cb_trade_menu_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer()
    await update_trade_uis(active_trades[trade_id])
    await callback.answer()

async def execute_trade(trade_id):
    trade = active_trades.pop(trade_id, None)
    if not trade: return
    
    user_trades.pop(trade['p1'], None)
    user_trades.pop(trade['p2'], None)
    
    db = await get_db_connection()
    try:
        await db.execute("BEGIN")
        
        async def transfer_items(from_u, to_u, offer):
            for i_id, qty in offer.items():
                cur = await db.execute("SELECT card_id, mutation, serial_number, signed_by, count FROM inventory WHERE id = ?", (i_id,))
                row = await cur.fetchone()
                if not row or row['count'] < qty:
                    raise Exception("Not enough items")
                
                if row['count'] == qty:
                    await db.execute("DELETE FROM inventory WHERE id = ?", (i_id,))
                    # Автоматическое снятие экипировки при трейде
                    await db.execute("UPDATE users SET equip1 = 0 WHERE equip1 = ?", (i_id,))
                    await db.execute("UPDATE users SET equip2 = 0 WHERE equip2 = ?", (i_id,))
                    await db.execute("UPDATE users SET equip3 = 0 WHERE equip3 = ?", (i_id,))
                else:
                    await db.execute("UPDATE inventory SET count = count - ? WHERE id = ?", (qty, i_id))
                    
                cur2 = await db.execute("""
                    SELECT id FROM inventory 
                    WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = ? AND signed_by = ?
                """, (to_u, row['card_id'], row['mutation'], row['serial_number'], row['signed_by']))
                dest = await cur2.fetchone()
                
                if dest:
                    await db.execute("UPDATE inventory SET count = count + ? WHERE id = ?", (qty, dest['id']))
                else:
                    await db.execute("""
                        INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (to_u, row['card_id'], qty, row['mutation'], row['serial_number'], row['signed_by']))

        await transfer_items(trade['p1'], trade['p2'], trade['p1_offer'])
        await transfer_items(trade['p2'], trade['p1'], trade['p2_offer'])
        
        await db.commit()
        success = True
    except Exception as e:
        await db.execute("ROLLBACK")
        logging.error(f"Trade Error: {e}")
        success = False
    finally:
        await db.close()
        
    if success:
        text = f"🎉 <b>ОБМЕН УСПЕШНО ЗАВЕРШЕН!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nКарточки перенесены в инвентари."
        try: await bot.edit_message_text(text, chat_id=trade['p1'], message_id=trade['p1_msg'])
        except: pass
        try: await bot.edit_message_text(text, chat_id=trade['p2'], message_id=trade['p2_msg'])
        except: pass
    else:
        text = f"❌ <b>ОШИБКА ОБМЕНА!</b>\nВероятно, кто-то попытался обмануть систему. Трейд отменен, ничего не списано."
        try: await bot.edit_message_text(text, chat_id=trade['p1'], message_id=trade['p1_msg'])
        except: pass
        try: await bot.edit_message_text(text, chat_id=trade['p2'], message_id=trade['p2_msg'])
        except: pass

async def trade_timeout_task():
    while True:
        try:
            now = time.time()
            to_cancel = []
            for t_id, trade in active_trades.items():
                if now - trade['start_time'] > 600:
                    to_cancel.append(t_id)
            for t_id in to_cancel:
                await cancel_trade(t_id, reason="Таймаут в 10 минут")
        except Exception as e:
            logging.error(f"Trade Timeout Task: {e}")
        await asyncio.sleep(60)

# ========================================================================
# СИСТЕМА СИД-ПАКОВ (ИНТЕРФЕЙС И ОПЕРАЦИИ ИГРОКА)
# ========================================================================
@dp.message(F.text.in_(BTN_SEED_PACKS))
async def cmd_seed_packs_menu(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (message.from_user.id,))
    packs = await fetch_all("SELECT * FROM seed_packs")
    
    text = (
        "📦 <b>МАГАЗИН СИД-ПАКОВ</b>\n"
        f"💰 Твой баланс: <b>{user['coins']} Шекелей</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Сид-Пак — это особый набор карт с гарантированным набором юнитов "
        "и повышенным шансом мутаций (<b>12% на Золотую</b>, <b>2% на Радужную</b>)!\n\n"
        "Вы можете приобрести любой пак из списка ниже за фиксированную стоимость в <b>2000 Шекелей</b>:\n"
    )
    
    kb = []
    if not packs:
        text += "\n<i>Сид-Паки пока не созданы администратором сервера. Ожидайте!</i>"
    else:
        for p in packs:
            desc_text = f" — {p['description']}" if p['description'] else ""
            text += f"🔹 <b>{p['title']}</b>{desc_text}\n"
            kb.append([InlineKeyboardButton(text=f"🛒 Купить {p['title']} (2000 💰)", callback_data=f"sp_buy_{p['id']}")])
            
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("sp_buy_"))
async def callback_sp_buy(callback: types.CallbackQuery):
    pack_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (user_id,))
    pack = await fetch_one("SELECT * FROM seed_packs WHERE id = ?", (pack_id,))
    
    if not pack: return await callback.answer("❌ Сид-пак не найден!", show_alert=True)
    if user['coins'] < 2000: return await callback.answer("❌ Недостаточно шекелей для покупки! Нужно 2000 💰", show_alert=True)
    
    await execute_db("UPDATE users SET coins = coins - 2000 WHERE id = ?", (user_id,))
    await execute_db("""
        INSERT INTO user_seed_packs (user_id, pack_id, count)
        VALUES (?, ?, 1)
        ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + 1
    """, (user_id, pack_id))
    
    await callback.answer("🎉 Покупка Сид-Пака успешна!", show_alert=True)
    
    # Обновляем меню магазина Сид-паков
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (user_id,))
    packs = await fetch_all("SELECT * FROM seed_packs")
    text = (
        "📦 <b>МАГАЗИН СИД-ПАКОВ</b>\n"
        f"💰 Твой баланс: <b>{user['coins']} Шекелей</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Сид-Пак куплен и добавлен в ваш инвентарь!\n\n"
        "Вы можете приобрести любой пак из списка ниже за <b>2000 Шекелей</b>:\n"
    )
    kb = []
    for p in packs:
        desc_text = f" — {p['description']}" if p['description'] else ""
        text += f"🔹 <b>{p['title']}</b>{desc_text}\n"
        kb.append([InlineKeyboardButton(text=f"🛒 Купить {p['title']} (2000 💰)", callback_data=f"sp_buy_{p['id']}")])
        
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

# Переключение инвентаря на Сид-Паки
@dp.callback_query(F.data == "inv_packs_menu")
async def cb_inv_packs_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user_packs = await fetch_all("""
        SELECT usp.count, sp.id as pack_id, sp.title, sp.description
        FROM user_seed_packs usp
        JOIN seed_packs sp ON usp.pack_id = sp.id
        WHERE usp.user_id = ? AND usp.count > 0
    """, (user_id,))
    
    text = (
        "🎒 <b>ИНВЕНТАРЬ СИД-ПАКОВ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Здесь хранятся ваши запечатанные Сид-Паки. Выберите пак для распаковки:\n\n"
    )
    
    kb = []
    toggle_row = [
        InlineKeyboardButton(text="🎒 Карты", callback_data="inv_cards_menu"),
        InlineKeyboardButton(text="📦 Сид-Паки (Выбрано)", callback_data="ignore")
    ]
    kb.append(toggle_row)
    
    if not user_packs:
        text += "<i>У вас пока нет купленных Сид-Паков. Приобрести их можно во вкладке меню «📦 Сид-Паки».</i>"
    else:
        for p in user_packs:
            text += f"📦 <b>{p['title']}</b> — <b>{p['count']} шт.</b>\n"
            kb.append([InlineKeyboardButton(text=f"🔓 Открыть {p['title']}", callback_data=f"sp_open_select_{p['pack_id']}")])
            
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data == "inv_cards_menu")
async def cb_inv_cards_menu(callback: types.CallbackQuery):
    text, kb = await get_inventory_text_and_kb(callback.from_user.id, 0)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("sp_open_select_"))
async def cb_sp_open_select(callback: types.CallbackQuery, state: FSMContext):
    pack_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    
    user_pack = await fetch_one("SELECT count FROM user_seed_packs WHERE user_id = ? AND pack_id = ?", (user_id, pack_id))
    pack = await fetch_one("SELECT title FROM seed_packs WHERE id = ?", (pack_id,))
    
    if not user_pack or user_pack['count'] <= 0:
        return await callback.answer("❌ У вас нет этого сид-пака!", show_alert=True)
        
    await state.update_data(open_pack_id=pack_id, max_amount=user_pack['count'])
    await callback.message.answer(
        f"🔓 <b>РАСПАКОВКА СИД-ПАКА: {pack['title']}</b>\n"
        f"У вас в наличии: <b>{user_pack['count']} шт.</b>\n\n"
        "Введите целым числом количество Сид-Паков, которые вы хотите открыть:"
    )
    await state.set_state(OpenSeedPackState.waiting_amount)
    await callback.answer()

@dp.message(OpenSeedPackState.waiting_amount)
async def process_sp_open_amount(message: types.Message, state: FSMContext):
    val = message.text.strip()
    data = await state.get_data()
    pack_id = data['open_pack_id']
    max_amount = data['max_amount']
    user_id = message.from_user.id
    
    if not val.isdigit() or int(val) <= 0:
        return await message.answer("❌ Введите корректное положительное число.")
        
    amount = int(val)
    if amount > max_amount:
        return await message.answer(f"❌ Недостаточно паков! Вы можете открыть максимум {max_amount} шт.")
        
    # Списываем паки
    await execute_db("UPDATE user_seed_packs SET count = count - ? WHERE user_id = ? AND pack_id = ?", (amount, user_id, pack_id))
    
    # Загружаем карты пака
    pack_cards = await fetch_all("SELECT card_id, drop_chance FROM seed_pack_cards WHERE pack_id = ?", (pack_id,))
    pack = await fetch_one("SELECT title, photo_id FROM seed_packs WHERE id = ?", (pack_id,))
    
    if not pack_cards:
        await execute_db("UPDATE user_seed_packs SET count = count + ? WHERE user_id = ? AND pack_id = ?", (amount, user_id, pack_id))
        await state.clear()
        return await message.answer("❌ Этот Сид-Пак пуст (внутри нет карт). Свяжитесь с администрацией. Паки возвращены.")
        
    luck_mult, _ = await get_active_events()
    weights = []
    cards_list = []
    
    for pc in pack_cards:
        weight = pc['drop_chance']
        if weight < 15.0: weight *= luck_mult
        weights.append(weight)
        
        card_info = await fetch_one("SELECT * FROM cards WHERE id = ?", (pc['card_id'],))
        cards_list.append(card_info)
        
    won_cards = []
    for _ in range(amount):
        won_card = random.choices(cards_list, weights=weights, k=1)[0]
        mut = roll_seed_pack_mutation() # Фиксированные шансы мутации сидпака
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        
        c_copy = dict(won_card)
        c_copy['mutation'] = mut
        c_copy['serial_number'] = serial
        won_cards.append(c_copy)
        
    # Статистика выпавших
    await add_quest_progress(user_id, 'q_cards_opened', amount)
    if any(c['rarity'] == 'Rare' for c in won_cards):
        await add_quest_progress(user_id, 'q_rare_obtained', 1)
        
    text_results = f"🎉 <b>РАСПАКОВКА {amount}x СИД-ПАКА «{pack['title']}» ЗАВЕРШЕНА!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    if amount == 1:
        single = won_cards[0]
        mut_str = "🌈 Радужная " if single['mutation'] == 'Rainbow' else ("⭐ Золотая " if single['mutation'] == 'Gold' else "")
        mult = get_mutation_multiplier(single['mutation'])
        
        caption_text = (
            f"🎉 <b>ВЫ ВЫБИЛИ КАРТУ ИЗ СИД-ПАКА!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🃏 {mut_str}{format_card_name(single)}\n"
            f"💎 <b>Редкость:</b> {format_rarity_display(single['rarity'])}\n"
        )
        if single['class_type'] == 'Booster':
            caption_text += f"✨ <b>БУСТЕР</b>\n⚔️ DMG Mult: <b>x{round(single['booster_dmg_mult']*mult, 2)}</b> | ❤️ HP Mult: <b>x{round(single['booster_hp_mult']*mult, 2)}</b>\n"
        else:
            caption_text += f"⚔️ <b>Урон:</b> {int(single['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(single['hp']*mult)}\n"
            
        await message.answer_photo(photo=single['photo_id'], caption=caption_text)
    else:
        # Для массового открытия выводим структурированный список
        text_results += "📦 <b>Список выпавших карт:</b>\n"
        for idx, c in enumerate(won_cards, 1):
            mut_str = "🌈 " if c['mutation'] == 'Rainbow' else ("⭐ " if c['mutation'] == 'Gold' else "⚪ ")
            text_results += f"{idx}. {mut_str}{format_card_name(c)}\n"
        text_results += "\n<i>Все карты были перемещены в ваш 🎒 Инвентарь.</i>"
        await message.answer(text_results)
        
    await state.clear()

# ========================================================================
# ПАНЕЛЬ АДМИНИСТРАТОРА (ОБНОВЛЕННАЯ С КНОПКАМИ ИВЕНТОВ И СИД-ПАКОВ)
# ========================================================================
def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Карты", callback_data="adm_cards"), InlineKeyboardButton(text="👤 Игроки", callback_data="adm_users")],
        [InlineKeyboardButton(text="🎉 Ивенты", callback_data="adm_events"), InlineKeyboardButton(text="👑 Админы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="🎟 Батл-пассы", callback_data="adm_bp_main"), InlineKeyboardButton(text="✍️ Сигнеры", callback_data="adm_signers")],
        [InlineKeyboardButton(text="🏆 Награды за Топ", callback_data="adm_lb_main"), InlineKeyboardButton(text="📦 Сид-Паки", callback_data="adm_sp_main")],
        [InlineKeyboardButton(text="📦 Бэкап БД", callback_data="adm_db")]
    ])

@dp.message(F.text.in_(BTN_ADM))
@dp.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id): return
    await message.answer("⚙️ <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\nВыберите раздел для управления ботом:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_main")
async def cq_adm_main(callback: types.CallbackQuery):
    await callback.message.edit_text("⚙️ <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\nВыберите раздел для управления ботом:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_admins")
async def cq_adm_admins(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID: return await callback.answer("Только для Супер-Админа!", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="adm_add_admin"), InlineKeyboardButton(text="➖ Удалить", callback_data="adm_del_admin")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("👑 <b>Управление Администраторами</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_add_admin")
async def cq_adm_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID пользователя для выдачи прав админа:")
    await state.set_state(AdminManage.add_id)
    await callback.answer()

@dp.message(AdminManage.add_id)
async def cq_adm_add_msg(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await execute_db("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (uid,))
        await message.answer(f"✅ Пользователь {uid} назначен администратором.")
    except: await message.answer("❌ Должно быть числом.")
    await state.clear()

@dp.callback_query(F.data == "adm_del_admin")
async def cq_adm_del(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID администратора для снятия прав:")
    await state.set_state(AdminManage.del_id)
    await callback.answer()

@dp.message(AdminManage.del_id)
async def cq_adm_del_msg(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        if uid == SUPER_ADMIN_ID:
            await message.answer("❌ Нельзя удалить Супер-Админа!")
        else:
            await execute_db("DELETE FROM admins WHERE user_id = ?", (uid,))
            await message.answer(f"✅ Администратор {uid} удален.")
    except: await message.answer("❌ Должно быть числом.")
    await state.clear()

# ========================================================================
# УПРАВЛЕНИЕ СИГНЕРАМИ
# ========================================================================
@dp.callback_query(F.data == "adm_signers")
async def cq_adm_signers(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Нанять (Добавить)", callback_data="adm_sgn_add"), InlineKeyboardButton(text="➖ Уволить (Убрать)", callback_data="adm_sgn_del")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("✍️ <b>Управление Сигнерами</b>\nПользователи в этом списке получают кнопку «Подписать карту» и могут оставлять свои росписи.", reply_markup=kb)

@dp.callback_query(F.data == "adm_sgn_add")
async def cq_adm_sgn_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID или @username пользователя для выдачи прав Сигнера:")
    await state.set_state(AdminSigner.add_id)
    await callback.answer()

@dp.message(AdminSigner.add_id)
async def cq_adm_sgn_add_msg(message: types.Message, state: FSMContext):
    val = message.text.strip()
    target_user = None
    if val.isdigit():
        target_user = await fetch_one("SELECT id FROM users WHERE id = ?", (int(val),))
    else:
        target_username = val.lstrip('@')
        target_user = await fetch_one("SELECT id FROM users WHERE username = ?", (target_username,))
        
    if not target_user:
        await message.answer("❌ Пользователь не найден в базе данных бота.")
    else:
        uid = target_user['id']
        await execute_db("INSERT OR IGNORE INTO authorized_signers (user_id) VALUES (?)", (uid,))
        await message.answer(f"✅ Пользователь {uid} назначен Сигнером!\n\n<i>Чтобы у него появилась кнопка в меню, ему нужно отправить любое сообщение боту или нажать /start.</i>")
    await state.clear()

@dp.callback_query(F.data == "adm_sgn_del")
async def cq_adm_sgn_del(callback: types.CallbackQuery):
    signers = await fetch_all("""
        SELECT a.user_id, u.username, u.first_name 
        FROM authorized_signers a 
        LEFT JOIN users u ON a.user_id = u.id
    """)
    if not signers: return await callback.answer("В списке никого нет.", show_alert=True)
    
    kb = []
    for s in signers:
        name = get_display_name({'username': s['username'], 'first_name': s['first_name'], 'id': s['user_id']})
        kb.append([InlineKeyboardButton(text=f"❌ {name}", callback_data=f"adm_sgn_rm_{s['user_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_signers")])
    
    await callback.message.edit_text("Выберите Сигнера для снятия прав:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("adm_sgn_rm_"))
async def cq_adm_sgn_rm(callback: types.CallbackQuery):
    uid = int(callback.data.split("_")[3])
    await execute_db("DELETE FROM authorized_signers WHERE user_id = ?", (uid,))
    await callback.answer("✅ Пользователь уволен с должности Сигнера!", show_alert=True)
    await cq_adm_sgn_del(callback)

# ========================================================================
# УПРАВЛЕНИЕ КАРТАМИ В АДМИНКЕ
# ========================================================================
@dp.callback_query(F.data == "adm_cards")
async def cq_adm_cards(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать", callback_data="adm_card_add"), InlineKeyboardButton(text="✏️ Редактировать", callback_data="adm_card_edit_list")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="adm_card_del")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🃏 <b>Управление Картами</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_card_add")
async def adm_card_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправь фото карты:")
    await state.set_state(AddCard.photo)
    await callback.answer()

@dp.message(AddCard.photo, F.photo)
async def add_card_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer("Введи название:")
    await state.set_state(AddCard.name)

@dp.message(AddCard.name)
async def add_card_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введи БАЗОВЫЙ ШАНС (вес, например 0.1, 5, 100). Для Лидерборда введи 0:")
    await state.set_state(AddCard.drop_chance)

@dp.message(AddCard.drop_chance)
async def add_card_chance(message: types.Message, state: FSMContext):
    try:
        chance = float(message.text.replace(',', '.'))
        await state.update_data(drop_chance=chance)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=r)] for r in RARITY_COLORS.keys()], resize_keyboard=True)
        await message.answer("Выбери редкость:", reply_markup=kb)
        await state.set_state(AddCard.rarity)
    except: await message.answer("❌ Должно быть число!")

@dp.message(AddCard.rarity)
async def add_card_rarity(message: types.Message, state: FSMContext):
    if message.text not in RARITY_COLORS: return await message.answer("Выбери с клавиатуры.")
    await state.update_data(rarity=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c)] for c in CLASSES], resize_keyboard=True)
    await message.answer("Выбери тип (класс):", reply_markup=kb)
    await state.set_state(AddCard.class_type)

@dp.message(AddCard.class_type)
async def add_card_class(message: types.Message, state: FSMContext):
    if message.text not in CLASSES: return await message.answer("Выбери с клавиатуры.")
    await state.update_data(class_type=message.text)
    
    if message.text == "Booster":
        await message.answer("Введи множитель УРОНА (например, 1.5):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(AddCard.booster_dmg)
    else:
        await message.answer("Введи базовый урон (целое число):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(AddCard.damage)

@dp.message(AddCard.booster_dmg)
async def add_card_boost_dmg(message: types.Message, state: FSMContext):
    try:
        await state.update_data(booster_dmg_mult=float(message.text.replace(',','.')), damage=0)
        await message.answer("Введи множитель ХП (например, 1.2):")
        await state.set_state(AddCard.booster_hp)
    except: await message.answer("❌ Число!")

@dp.message(AddCard.booster_hp)
async def add_card_boost_hp(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        hp_mult = float(message.text.replace(',','.'))
        await message.answer("⏳ Генерирую рамку редкости для карты...")
        
        new_photo_id = await create_bordered_image(bot, data['photo'], data['rarity'])
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id, booster_dmg_mult, booster_hp_mult) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data['name'], data['rarity'], data['class_type'], 0, 0, data['drop_chance'], new_photo_id, data['booster_dmg_mult'], hp_mult)
        )
        
        await log_admin(message.from_user.id, f"Создан БУСТЕР: {data['name']}")
        is_adm = await is_admin(message.from_user.id)
        is_sgn = await is_signer(message.from_user.id)
        u_data = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
        l = u_data['lang'] if u_data else "ru"
        await message.answer_photo(new_photo_id, caption=f"✅ <b>Бустер {data['name']} создан!</b>", reply_markup=get_main_keyboard(is_adm, is_sgn, l))
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}"); await state.clear()

@dp.message(AddCard.damage)
async def add_card_dmg(message: types.Message, state: FSMContext):
    try:
        await state.update_data(damage=int(message.text), booster_dmg_mult=1.0)
        await message.answer("Введи здоровье (хп):")
        await state.set_state(AddCard.hp)
    except: await message.answer("❌ Число!")

@dp.message(AddCard.hp)
async def add_card_finish(message: types.Message, state: FSMContext):
    try:
        hp = int(message.text)
        data = await state.get_data()
        await message.answer("⏳ Генерирую рамку редкости для карты...")
        
        new_photo_id = await create_bordered_image(bot, data['photo'], data['rarity'])
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id, booster_dmg_mult, booster_hp_mult) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data['name'], data['rarity'], data['class_type'], data['damage'], hp, data['drop_chance'], new_photo_id, 1.0, 1.0)
        )
        
        await log_admin(message.from_user.id, f"Создана карта: {data['name']}")
        is_adm = await is_admin(message.from_user.id)
        is_sgn = await is_signer(message.from_user.id)
        u_data = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
        l = u_data['lang'] if u_data else "ru"
        await message.answer_photo(new_photo_id, caption=f"✅ <b>Карта {data['name']} создана!</b>", reply_markup=get_main_keyboard(is_adm, is_sgn, l))
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}"); await state.clear()

@dp.callback_query(F.data == "adm_card_edit_list")
async def adm_card_edit_start(callback: types.CallbackQuery, state: FSMContext):
    cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    if not cards: return await callback.answer("В базе нет карт!", show_alert=True)
    
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']} (ID:{c['id']})"} for c in cards]
    await state.update_data(adm_edit_items=items)
    
    kb = get_pagination_keyboard(items, 0, "adm_ed_c", columns=1, items_per_page=8)
    await callback.message.edit_text("👇 Выберите карту для редактирования:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_ed_c_page_"))
async def adm_card_edit_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[4])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('adm_edit_items', []), page, "adm_ed_c", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_ed_c_"))
async def adm_card_edit_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    c_id = int(callback.data.split("_")[3])
    
    card = await fetch_one("SELECT * FROM cards WHERE id = ?", (c_id,))
    if not card: return await callback.answer("❌ Карта не найдена.")
    
    await state.update_data(edit_id=c_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data="edit_val_name"), InlineKeyboardButton(text="✏️ Шанс (Вес)", callback_data="edit_val_chance")],
        [InlineKeyboardButton(text="✏️ Урон", callback_data="edit_val_dmg"), InlineKeyboardButton(text="✏️ ХП", callback_data="edit_val_hp")],
        [InlineKeyboardButton(text="✏️ Буст Урон", callback_data="edit_val_bdmg"), InlineKeyboardButton(text="✏️ Буст ХП", callback_data="edit_val_bhp")],
        [InlineKeyboardButton(text="✏️ Класс", callback_data="edit_val_class")]
    ])
    await callback.message.edit_text(f"Редактирование <b>{card['name']}</b> (ID: {c_id})\nЧто меняем?", reply_markup=kb)
    await state.set_state(EditCard.waiting_new_value)
    await callback.answer()

@dp.callback_query(EditCard.waiting_new_value, F.data.startswith("edit_val_"))
async def adm_card_edit_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[2]
    await state.update_data(edit_field=field)
    
    if field == "class":
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c)] for c in CLASSES], resize_keyboard=True)
        await callback.message.answer("Выберите новый класс с клавиатуры:", reply_markup=kb)
    else:
        await callback.message.answer(f"Отправь новое значение для параметра {field}:")
    await callback.answer()

@dp.message(EditCard.waiting_new_value)
async def adm_card_edit_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_id = data['edit_id']
    field = data['edit_field']
    val = message.text
    
    col_map = {
        "name": ("name", str), "chance": ("drop_chance", float),
        "dmg": ("damage", int), "hp": ("hp", int),
        "bdmg": ("booster_dmg_mult", float), "bhp": ("booster_hp_mult", float),
        "class": ("class_type", str)
    }
    
    col, cast_fn = col_map[field]
    try:
        if field == "class" and val not in CLASSES:
            return await message.answer("Неверный класс. Используйте клавиатуру.")
            
        val = cast_fn(val.replace(',', '.')) if cast_fn == float else cast_fn(val)
        await execute_db(f"UPDATE cards SET {col} = ? WHERE id = ?", (val, c_id))
        await log_admin(message.from_user.id, f"Edited card ID {c_id}, {col} = {val}")
        
        reply = "✅ Изменено!"
        if field == "class": reply += " Возвращена стандартная клавиатура."
        is_adm = await is_admin(message.from_user.id)
        is_sgn = await is_signer(message.from_user.id)
        u_data = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
        l = u_data['lang'] if u_data else "ru"
        await message.answer(reply, reply_markup=get_main_keyboard(is_adm, is_sgn, l))
        await state.clear()
    except: await message.answer("❌ Неверный формат значения.")

@dp.callback_query(F.data == "adm_card_del")
async def adm_card_del_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи ID карты для удаления:")
    await state.set_state("waiting_del_id")
    await callback.answer()

@dp.message(StateFilter("waiting_del_id"))
async def adm_card_del_finish(message: types.Message, state: FSMContext):
    try:
        c_id = int(message.text)
        await execute_db("DELETE FROM cards WHERE id = ?", (c_id,))
        
        invs = await fetch_all("SELECT id FROM inventory WHERE card_id = ?", (c_id,))
        inv_ids = [i['id'] for i in invs]
        
        await execute_db("DELETE FROM inventory WHERE card_id = ?", (c_id,))
        
        for i_id in inv_ids:
            for slot in ['equip1', 'equip2', 'equip3']:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE {slot} = ?", (i_id,))
                
        await log_admin(message.from_user.id, f"DELETED card ID {c_id}")
        await message.answer(f"✅ Карта {c_id} полностью удалена.")
    except: await message.answer("❌ Число.")
    await state.clear()

# ========================================================================
# УПРАВЛЕНИЕ ИГРОКАМИ В АДМИНКЕ
# ========================================================================
@dp.callback_query(F.data == "adm_users")
async def cq_adm_users(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Выдать карту", callback_data="adm_usr_givecard")],
        [InlineKeyboardButton(text="💰 Выдать шекели", callback_data="adm_usr_give_coins"),
         InlineKeyboardButton(text="🏆 Выдать кубки", callback_data="adm_usr_give_trophies")],
        [InlineKeyboardButton(text="🔄 Сбросить бой", callback_data="adm_usr_reset_battle")],
        [InlineKeyboardButton(text="🔨 Бан / Разбан", callback_data="adm_usr_ban")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("👤 <b>Управление Игроками</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_usr_give_coins")
async def adm_usr_give_coins_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока для выдачи шекелей:")
    await state.set_state(AdminManage.give_coins_id)
    await callback.answer()

@dp.message(AdminManage.give_coins_id)
async def adm_usr_give_coins_id(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(target_id=uid)
        await message.answer("Сколько шекелей выдать?")
        await state.set_state(AdminManage.give_coins_amount)
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

@dp.message(AdminManage.give_coins_amount)
async def adm_usr_give_coins_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data['target_id']
        await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (amount, uid))
        await log_admin(message.from_user.id, f"Выдал {amount} шекелей игроку {uid}")
        await message.answer(f"✅ Успешно выдано {amount} шекелей игроку {uid}.")
        try:
            await bot.send_message(uid, f"🎁 Администратор выдал вам <b>{amount} 💰 Шекелей</b>!")
        except:
            pass
    except ValueError:
        await message.answer("❌ Сумма должна быть числом.")
    await state.clear()

@dp.callback_query(F.data == "adm_usr_give_trophies")
async def adm_usr_give_trophies_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока для выдачи кубков:")
    await state.set_state(AdminManage.give_trophies_id)
    await callback.answer()

@dp.message(AdminManage.give_trophies_id)
async def adm_usr_give_trophies_id(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(target_id=uid)
        await message.answer("Сколько кубков выдать?")
        await state.set_state(AdminManage.give_trophies_amount)
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

@dp.message(AdminManage.give_trophies_amount)
async def adm_usr_give_trophies_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data['target_id']
        await execute_db("UPDATE users SET trophies = trophies + ? WHERE id = ?", (amount, uid))
        await log_admin(message.from_user.id, f"Выдал {amount} кубков игроку {uid}")
        await message.answer(f"✅ Успешно выдано {amount} кубков игроку {uid}.")
        try:
            await bot.send_message(uid, f"🏆 Администратор выдал вам <b>{amount} 🏆</b>!")
        except:
            pass
    except ValueError:
        await message.answer("❌ Количество должно быть числом.")
    await state.clear()

@dp.callback_query(F.data == "adm_usr_reset_battle")
async def adm_usr_reset_battle_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока для сброса состояния боя и трейда:")
    await state.set_state(AdminManage.reset_battle_id)
    await callback.answer()

@dp.message(AdminManage.reset_battle_id)
async def adm_usr_reset_battle_finish(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        flag = False
        if uid in active_combats:
            active_combats.discard(uid)
            flag = True
        if uid in user_trades:
            await cancel_trade(user_trades[uid], reason="Отмена администратором")
            flag = True
            
        if flag:
            await message.answer(f"✅ Состояние для игрока {uid} успешно сброшено.")
            await log_admin(message.from_user.id, f"Сбросил состояние для {uid}")
        else:
            await message.answer("ℹ️ Игрок не находился в активном поиске/трейде.")
            
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
    await state.clear()

@dp.callback_query(F.data == "adm_usr_givecard")
async def adm_usr_give(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока, которому хотим выдать карту:")
    await state.set_state(GiveCard.user_id)
    await callback.answer()

@dp.message(GiveCard.user_id)
async def adm_usr_give_user(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(give_user_id=uid)
        all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
        items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']} (ID:{c['id']})"} for c in all_cards]
        await state.update_data(give_items=items)
        kb = get_pagination_keyboard(items, 0, "give_c", columns=1, items_per_page=8)
        await message.answer("Выберите карту для выдачи:", reply_markup=kb)
        await state.set_state(GiveCard.card_id)
    except: await message.answer("❌ ID должен быть числом.")

@dp.callback_query(F.data.startswith("give_c_page_"), GiveCard.card_id)
async def adm_give_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('give_items', []), page, "give_c", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("give_c_"), GiveCard.card_id)
async def adm_give_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[2])
    await state.update_data(give_card_id=card_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Обычная", callback_data="give_mut_Normal")],
        [InlineKeyboardButton(text="⭐ Золотая", callback_data="give_mut_Gold")],
        [InlineKeyboardButton(text="🌈 Радужная", callback_data="give_mut_Rainbow")]
    ])
    await callback.message.edit_text("Выберите мутацию для карты:", reply_markup=kb)
    await state.set_state(GiveCard.mutation)
    await callback.answer()

@dp.callback_query(F.data.startswith("give_mut_"), GiveCard.mutation)
async def adm_give_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[2]
    data = await state.get_data()
    user_id = data.get('give_user_id')
    card_id = data.get('give_card_id')
    
    _, serial, _ = await give_card_to_user(user_id, card_id, mutation)
    
    s_str = f" [#{serial:04d}]" if serial > 0 else ""
    await log_admin(callback.from_user.id, f"GAVE card ID {card_id} (Mut:{mutation}) to User {user_id}")
    await callback.message.edit_text(f"✅ Карта (ID {card_id}) успешно выдана игроку {user_id}!\nМутация: {mutation}{s_str}")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "adm_usr_ban")
async def adm_usr_ban_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправь ID игрока для смены статуса бана (если забанен - разбанит):")
    await state.set_state(AdminBan.user_id)
    await callback.answer()

@dp.message(AdminBan.user_id)
async def adm_usr_ban_finish(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        usr = await fetch_one("SELECT banned FROM users WHERE id = ?", (uid,))
        if not usr: return await message.answer("Игрок не найден.")
        new_st = 0 if usr['banned'] == 1 else 1
        await execute_db("UPDATE users SET banned = ? WHERE id = ?", (new_st, uid))
        await log_admin(message.from_user.id, f"Set BAN status to {new_st} for {uid}")
        await message.answer(f"✅ Статус бана изменен на {new_st}.")
    except: pass
    await state.clear()

# ========================================================================
# УПРАВЛЕНИЕ БАТЛ-ПАССАМИ (АДМИНКА)
# ========================================================================
@dp.callback_query(F.data == "adm_bp_main")
async def adm_bp_main(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать Батл-пасс", callback_data="adm_bp_create")],
        [InlineKeyboardButton(text="🗑 Удалить Батл-пасс", callback_data="adm_bp_delete")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🎟 <b>Управление Батл-пассами</b>\nСоздавайте новые сезоны и настраивайте награды.", reply_markup=kb)

@dp.callback_query(F.data == "adm_bp_delete")
async def adm_bp_del_list(callback: types.CallbackQuery):
    passes = await fetch_all("SELECT * FROM battle_passes ORDER BY id DESC")
    if not passes:
        return await callback.answer("Батл-пассов пока нет.", show_alert=True)
        
    kb = []
    for bp in passes:
        kb.append([InlineKeyboardButton(text=f"🗑 Удалить: {bp['title']}", callback_data=f"adm_bp_del_id_{bp['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="adm_bp_main")])
    
    await callback.message.edit_text("Выберите Батл-пасс для полного удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("adm_bp_del_id_"))
async def adm_bp_del_confirm(callback: types.CallbackQuery):
    bp_id = int(callback.data.split("_")[4])
    await execute_db("DELETE FROM battle_passes WHERE id = ?", (bp_id,))
    await execute_db("DELETE FROM bp_levels WHERE bp_id = ?", (bp_id,))
    await callback.answer("✅ Батл-пасс удален!", show_alert=True)
    await adm_bp_main(callback)

@dp.callback_query(F.data == "adm_bp_create")
async def adm_bp_create_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("🎟 <b>Создание нового Батл-пасса</b>\nШаг 1: Введите красивое НАЗВАНИЕ сезона (например: <i>Сезон 1: Зимняя Сказка</i>):")
    await state.set_state(AdminBPCreation.title)
    await callback.answer()

@dp.message(AdminBPCreation.title)
async def adm_bp_cr_title(message: types.Message, state: FSMContext):
    await state.update_data(bp_title=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True)
    await message.answer("Шаг 2: Отправьте ФОТО для батл-пасса (или нажмите Пропустить):", reply_markup=kb)
    await state.set_state(AdminBPCreation.photo)

@dp.message(AdminBPCreation.photo)
async def adm_bp_cr_photo(message: types.Message, state: FSMContext):
    if message.text == "Пропустить":
        await state.update_data(bp_photo=None)
    elif message.photo:
        await state.update_data(bp_photo=message.photo[-1].file_id)
    else:
        return await message.answer("Пожалуйста, отправьте фото или нажмите Пропустить.")
        
    await message.answer("Шаг 3: Сколько всего УРОВНЕЙ будет в этом батл-пассе? (Введите число, например 10):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminBPCreation.levels_count)

@dp.message(AdminBPCreation.levels_count)
async def adm_bp_cr_count(message: types.Message, state: FSMContext):
    try:
        count = int(message.text)
        if count <= 0: raise ValueError
        await state.update_data(bp_levels_count=count, current_level=1, bp_data_levels={})
        await adm_bp_ask_level_xp(message, state, 1)
    except:
        await message.answer("❌ Введите корректное число больше 0.")

async def adm_bp_ask_level_xp(message_or_call, state: FSMContext, lvl: int):
    msg = f"⚙️ <b>Настройка Уровня {lvl}</b>\nСколько ОПЫТА (XP) требуется для достижения этого уровня?"
    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.answer(msg)
    else:
        await message_or_call.answer(msg)
    await state.set_state(AdminBPCreation.level_xp)

@dp.message(AdminBPCreation.level_xp)
async def adm_bp_cr_lvl_xp(message: types.Message, state: FSMContext):
    try:
        xp = int(message.text)
        data = await state.get_data()
        lvl = data['current_level']
        
        bp_levels = data['bp_data_levels']
        if lvl not in bp_levels:
            bp_levels[lvl] = {'xp': xp, 'rewards': []}
        else:
            bp_levels[lvl]['xp'] = xp
            
        await state.update_data(bp_data_levels=bp_levels)
        await adm_bp_show_reward_menu(message, state, lvl)
    except ValueError:
        await message.answer("❌ Введите число.")

async def adm_bp_show_reward_menu(message_or_call, state: FSMContext, lvl: int):
    data = await state.get_data()
    rewards = data['bp_data_levels'][lvl]['rewards']
    
    text = f"⚙️ <b>Настройка Уровня {lvl}</b>\nНаграды на этом уровне:\n"
    if not rewards: text += "<i>Пока пусто</i>\n"
    else:
        for r in rewards:
            if r['type'] == 'shekels': text += f"💰 {r['amount']} Шекелей\n"
            elif r['type'] == 'card': text += f"🃏 Карта ID:{r['card_id']} ({r['mutation']})\n"
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить Шекели", callback_data="bpr_add_sh"), InlineKeyboardButton(text="➕ Добавить Карту", callback_data="bpr_add_cd")],
        [InlineKeyboardButton(text="✅ Завершить уровень", callback_data="bpr_next_lvl")]
    ])
    
    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=kb)
    else:
        await message_or_call.answer(text, reply_markup=kb)
    await state.set_state(AdminBPCreation.reward_action)

@dp.callback_query(AdminBPCreation.reward_action, F.data == "bpr_add_sh")
async def bpr_add_sh(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите количество Шекелей:")
    await state.set_state(AdminBPCreation.reward_shekels)
    await callback.answer()

@dp.message(AdminBPCreation.reward_shekels)
async def bpr_save_sh(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        data = await state.get_data()
        lvl = data['current_level']
        data['bp_data_levels'][lvl]['rewards'].append({'type': 'shekels', 'amount': amt})
        await state.update_data(bp_data_levels=data['bp_data_levels'])
        await adm_bp_show_reward_menu(message, state, lvl)
    except: await message.answer("❌ Число!")

@dp.callback_query(AdminBPCreation.reward_action, F.data == "bpr_add_cd")
async def bpr_add_cd(callback: types.CallbackQuery, state: FSMContext):
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']} (ID:{c['id']})"} for c in all_cards]
    await state.update_data(bpadm_items=items)
    kb = get_pagination_keyboard(items, 0, "bpadmc", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту для награды:", reply_markup=kb)
    await state.set_state(AdminBPCreation.reward_card)

@dp.callback_query(AdminBPCreation.reward_card, F.data.startswith("bpadmc_page_"))
async def bpadm_c_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('bpadm_items', []), page, "bpadmc", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(AdminBPCreation.reward_card, F.data.startswith("bpadmc_"))
async def bpadm_c_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[1])
    await state.update_data(bpadm_sel_card=card_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Обычная", callback_data="bpadmmut_Normal")],
        [InlineKeyboardButton(text="⭐ Золотая", callback_data="bpadmmut_Gold")],
        [InlineKeyboardButton(text="🌈 Радужная", callback_data="bpadmmut_Rainbow")]
    ])
    await callback.message.edit_text("Выберите мутацию для этой карты:", reply_markup=kb)
    await state.set_state(AdminBPCreation.reward_mutation)
    await callback.answer()

@dp.callback_query(AdminBPCreation.reward_mutation, F.data.startswith("bpadmmut_"))
async def bpadm_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[1]
    data = await state.get_data()
    lvl = data['current_level']
    card_id = data['bpadm_sel_card']
    
    data['bp_data_levels'][lvl]['rewards'].append({'type': 'card', 'card_id': card_id, 'mutation': mutation})
    await state.update_data(bp_data_levels=data['bp_data_levels'])
    
    await callback.message.delete()
    await adm_bp_show_reward_menu(callback, state, lvl)
    await callback.answer()

@dp.callback_query(AdminBPCreation.reward_action, F.data == "bpr_next_lvl")
async def bpr_next_lvl(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lvl = data['current_level']
    total_lvls = data['bp_levels_count']
    
    if lvl < total_lvls:
        await state.update_data(current_level=lvl + 1)
        await callback.message.delete()
        await adm_bp_ask_level_xp(callback, state, lvl + 1)
    else:
        await callback.message.delete()
        await adm_bp_finish_and_save(callback, state)
    await callback.answer()

async def adm_bp_finish_and_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    text = f"✅ <b>Все настроено! Создаю Батл-пасс:</b>\nНазвание: {data['bp_title']}\nУровней: {data['bp_levels_count']}\n\n"
    await callback.message.answer(text)
    
    db = await get_db_connection()
    try:
        cursor = await db.execute("INSERT INTO battle_passes (title, photo_id, created_at) VALUES (?, ?, ?)", (data['bp_title'], data.get('bp_photo'), time.time()))
        bp_id = cursor.lastrowid
        
        for lvl_num, lvl_data in data['bp_data_levels'].items():
            l_cursor = await db.execute("INSERT INTO bp_levels (bp_id, level, xp_required) VALUES (?, ?, ?)", (bp_id, lvl_num, lvl_data['xp']))
            level_id = l_cursor.lastrowid
            
            for r in lvl_data['rewards']:
                if r['type'] == 'shekels':
                    await db.execute("INSERT INTO bp_rewards (level_id, reward_type, amount) VALUES (?, ?, ?)", (level_id, 'shekels', r['amount']))
                elif r['type'] == 'card':
                    await db.execute("INSERT INTO bp_rewards (level_id, reward_type, card_id, mutation) VALUES (?, ?, ?, ?)", (level_id, 'card', r['card_id'], r['mutation']))
        
        await db.commit()
    finally:
        await db.close()
        
    await callback.message.answer("🎉 Батл-пасс успешно сохранен в базу и доступен игрокам!")
    await log_admin(callback.from_user.id, f"Создал новый Батл-пасс: {data['bp_title']}")
    await state.clear()

# ========================================================================
# НАГРАДЫ И ИВЕНТЫ (АДМИНКА)
# ========================================================================
@dp.callback_query(F.data == "adm_lb_main")
async def adm_lb_main(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥇 1 Место", callback_data="lb_edit_1")],
        [InlineKeyboardButton(text="🥈 2 Место", callback_data="lb_edit_2")],
        [InlineKeyboardButton(text="🥉 3 Место", callback_data="lb_edit_3")],
        [InlineKeyboardButton(text="🏅 4-9 Места", callback_data="lb_edit_4_9")],
        [InlineKeyboardButton(text="🎖 10-20 Места", callback_data="lb_edit_10_20")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🏆 <b>Настройка наград за Лидерборд</b>\nВыберите позицию для редактирования наград (выдаются каждые 2 дня):", reply_markup=kb)

@dp.callback_query(F.data.startswith("lb_edit_"))
async def adm_lb_edit(callback: types.CallbackQuery, state: FSMContext):
    bracket = callback.data.replace("lb_edit_", "")
    rewards = await fetch_all("SELECT * FROM lb_rewards WHERE bracket = ?", (bracket,))
    
    text = f"🏆 <b>Награды для места: {bracket.replace('_', '-')}</b>\n\n"
    if not rewards:
        text += "<i>Награды не установлены.</i>\n"
    else:
        for r in rewards:
            if r['reward_type'] == 'shekels':
                text += f"💰 {r['amount']} Шекелей\n"
            elif r['reward_type'] == 'card':
                c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['card_id'],))
                n = c['name'] if c else "Удаленная карта"
                mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                text += f"🃏 {mut} {n} (ID: {r['card_id']})\n"
                
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить Шекели", callback_data=f"lb_add_sh_{bracket}")],
        [InlineKeyboardButton(text="➕ Добавить Карту", callback_data=f"lb_add_cd_{bracket}")],
        [InlineKeyboardButton(text="🗑 Очистить награды", callback_data=f"lb_clear_{bracket}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_lb_main")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("lb_clear_"))
async def adm_lb_clear(callback: types.CallbackQuery):
    bracket = callback.data.replace("lb_clear_", "")
    await execute_db("DELETE FROM lb_rewards WHERE bracket = ?", (bracket,))
    await callback.answer("✅ Награды очищены!", show_alert=True)
    await adm_lb_edit(callback, None)

@dp.callback_query(F.data.startswith("lb_add_sh_"))
async def adm_lb_add_shekels(callback: types.CallbackQuery, state: FSMContext):
    bracket = callback.data.replace("lb_add_sh_", "")
    await state.update_data(lb_bracket=bracket, lb_reward_type="shekels")
    await callback.message.answer("Введите количество Шекелей для выдачи:")
    await state.set_state(AdminLBRewards.amount)
    await callback.answer()

@dp.message(AdminLBRewards.amount)
async def adm_lb_save_shekels(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        data = await state.get_data()
        await execute_db("INSERT INTO lb_rewards (bracket, reward_type, amount) VALUES (?, ?, ?)", (data['lb_bracket'], 'shekels', amt))
        await message.answer(f"✅ Награда {amt} шекелей добавлена для {data['lb_bracket']} места!")
    except: await message.answer("❌ Число!")
    await state.clear()

@dp.callback_query(F.data.startswith("lb_add_cd_"))
async def adm_lb_add_card(callback: types.CallbackQuery, state: FSMContext):
    bracket = callback.data.replace("lb_add_cd_", "")
    await state.update_data(lb_bracket=bracket, lb_reward_type="card")
    
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']} (ID:{c['id']})"} for c in all_cards]
    await state.update_data(lb_items=items)
    kb = get_pagination_keyboard(items, 0, "lbc", columns=1, items_per_page=8)
    
    await callback.message.edit_text("Выберите карту для награды:", reply_markup=kb)
    await state.set_state(AdminLBRewards.card_id)

@dp.callback_query(F.data.startswith("lbc_page_"), AdminLBRewards.card_id)
async def adm_lb_c_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('lb_items', []), page, "lbc", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("lbc_"), AdminLBRewards.card_id)
async def adm_lb_c_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[1])
    await state.update_data(lb_card_id=card_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Обычная", callback_data="lb_mut_Normal")],
        [InlineKeyboardButton(text="⭐ Золотая", callback_data="lb_mut_Gold")],
        [InlineKeyboardButton(text="🌈 Радужная", callback_data="lb_mut_Rainbow")]
    ])
    await callback.message.edit_text("Выберите мутацию для этой награды:", reply_markup=kb)
    await state.set_state(AdminLBRewards.mutation)
    await callback.answer()

@dp.callback_query(F.data.startswith("lb_mut_"), AdminLBRewards.mutation)
async def adm_lb_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[2]
    data = await state.get_data()
    bracket = data['lb_bracket']
    card_id = data['lb_card_id']
    
    await execute_db("INSERT INTO lb_rewards (bracket, reward_type, card_id, mutation) VALUES (?, ?, ?, ?)", (bracket, 'card', card_id, mutation))
    
    await callback.message.edit_text(f"✅ Карта (ID {card_id}, Мутация: {mutation}) добавлена в награды для {bracket} места!")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "adm_events")
async def cq_adm_events(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍀 Ивент Удачи", callback_data="ev_luck"), InlineKeyboardButton(text="⏳ Ивент КД", callback_data="ev_cd")],
        [InlineKeyboardButton(text="💰 Множитель монет", callback_data="ev_coin"), InlineKeyboardButton(text="🎫 Множитель опыта БП", callback_data="ev_xp")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🎉 <b>Запуск Ивентов</b>\nПри запуске бот сделает массовую рассылку всем игрокам.", reply_markup=kb)

@dp.callback_query(F.data == "ev_luck")
async def ev_luck_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи множитель УДАЧИ (например 2.0 для х2):")
    await state.set_state(EventLuck.mult)
    await callback.answer()

@dp.message(EventLuck.mult)
async def ev_luck_mult(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text.replace(',','.')))
    await message.answer("На сколько МИНУТ запускаем?")
    await state.set_state(EventLuck.mins)

@dp.message(EventLuck.mins)
async def ev_luck_finish(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mins = int(message.text)
        end = time.time() + (mins * 60)
        await execute_db("UPDATE server_settings SET luck_mult = ?, luck_end = ? WHERE id = 1", (data['mult'], end))
        await log_admin(message.from_user.id, f"LUCK EVENT x{data['mult']} for {mins}m")
        await message.answer("✅ Ивент Удачи запущен. Начинаю рассылку...")
        await state.clear()
        asyncio.create_task(broadcast_message(f"🍀 <b>ГЛОБАЛЬНЫЙ ИВЕНТ УДАЧИ!</b>\nШанс на редкие карты увеличен в {data['mult']} раз на {mins} минут! Зайди в /index, чтобы увидеть новые шансы!\n\nБегом крутить гачу: /getcard", notif_type="notif_events"))
    except: await message.answer("Ошибка ввода.")

@dp.callback_query(F.data == "ev_cd")
async def ev_cd_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи множитель СКОРОСТИ (например 2.0 сделает откат в 2 раза быстрее):")
    await state.set_state(EventCD.mult)
    await callback.answer()

@dp.message(EventCD.mult)
async def ev_cd_mult(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text.replace(',','.')))
    await message.answer("На сколько МИНУТ запускаем?")
    await state.set_state(EventCD.mins)

@dp.message(EventCD.mins)
async def ev_cd_finish(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mins = int(message.text)
        end = time.time() + (mins * 60)
        await execute_db("UPDATE server_settings SET cd_mult = ?, cd_end = ? WHERE id = 1", (data['mult'], end))
        await log_admin(message.from_user.id, f"CD EVENT x{data['mult']} for {mins}m")
        await message.answer("✅ Ивент Скорости запущен. Начинаю рассылку...")
        await state.clear()
        asyncio.create_task(broadcast_message(f"⏳ <b>ГЛОБАЛЬНЫЙ ИВЕНТ СКОРОСТИ!</b>\nТаймер выбивания карт ускорен в {data['mult']} раз на {mins} минут!\n\nКрути гачу быстрее: /getcard", notif_type="notif_events"))
    except: await message.answer("Ошибка ввода.")

# Множитель монет
@dp.callback_query(F.data == "ev_coin")
async def ev_coin_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи множитель ШЕКЕЛЕЙ (например 1.5 или 2.0 для х2 за бои):")
    await state.set_state(EventCoin.mult)
    await callback.answer()

@dp.message(EventCoin.mult)
async def ev_coin_mult(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text.replace(',','.')))
    await message.answer("На сколько МИНУТ запускаем?")
    await state.set_state(EventCoin.mins)

@dp.message(EventCoin.mins)
async def ev_coin_finish(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mins = int(message.text)
        end = time.time() + (mins * 60)
        await execute_db("UPDATE server_settings SET coin_mult = ?, coin_end = ? WHERE id = 1", (data['mult'], end))
        await log_admin(message.from_user.id, f"COIN EVENT x{data['mult']} for {mins}m")
        await message.answer("✅ Ивент Множителя монет запущен. Начинаю рассылку...")
        await state.clear()
        asyncio.create_task(broadcast_message(f"💰 <b>ГЛОБАЛЬНЫЙ ИВЕНТ НА МОНЕТЫ!</b>\nКоличество получаемых шекелей в боях против ИИ увеличено в {data['mult']} раз на {mins} минут!\n\nЗарабатывай золото в боях: /pve", notif_type="notif_events"))
    except: await message.answer("Ошибка ввода.")

# Множитель опыта БП
@dp.callback_query(F.data == "ev_xp")
async def ev_xp_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи множитель ОПЫТА БП (например 2.0 для х2 опыта за бои):")
    await state.set_state(EventXP.mult)
    await callback.answer()

@dp.message(EventXP.mult)
async def ev_xp_mult(message: types.Message, state: FSMContext):
    try:
        await state.update_data(mult=float(message.text.replace(',', '.')))
        await message.answer("На сколько МИНУТ запускаем?")
        await state.set_state(EventXP.mins)
    except ValueError:
        await message.answer("❌ Введите корректный множитель (число).")

@dp.message(EventXP.mins)
async def ev_xp_finish(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mins = int(message.text)
        end = time.time() + (mins * 60)
        await execute_db("UPDATE server_settings SET xp_mult = ?, xp_end = ? WHERE id = 1", (data['mult'], end))
        await log_admin(message.from_user.id, f"XP EVENT x{data['mult']} for {mins}m")
        await message.answer("✅ Ивент Множителя опыта БП запущен. Начинаю рассылку...")
        await state.clear()
        asyncio.create_task(broadcast_message(
            f"🎫 <b>ГЛОБАЛЬНЫЙ ИВЕНТ НА ОПЫТ БП!</b>\n"
            f"Получаемый опыт Батл-пасса во всех боях увеличен в {data['mult']} раз на {mins} минут!\n\n"
            f"Прокачай свой БП скорее: /pve", 
            notif_type="notif_events"
        ))
    except Exception as e:
        await message.answer(f"Ошибка ввода: {e}")
        await state.clear()

@dp.message(Command("announce"))
async def cmd_announce(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    await message.answer("📢 <b>Глобальная Рассылка</b>\nОтправьте сообщение (текст, фото или видео с текстом), которое нужно разослать всем игрокам:")
    await state.set_state(AdminAnnounce.content)

@dp.message(AdminAnnounce.content)
async def process_announce(message: types.Message, state: FSMContext):
    users = await fetch_all("SELECT id FROM users WHERE banned = 0 AND notif_announces = 1")
    success = 0
    await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей (у кого включены анонсы)...")
    for u in users:
        try:
            await message.send_copy(chat_id=u['id'])
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
    await message.answer(f"✅ Рассылка успешно завершена!\nДоставлено: {success} из {len(users)}")
    await log_admin(message.from_user.id, f"Использовал команду /announce (разослано {success} игрокам)")
    await state.clear()

@dp.message(Command("restock"))
async def cmd_admin_restock(message: types.Message):
    if not await is_admin(message.from_user.id): return
    await restock_shop()
    await message.answer("✅ Ассортимент глобального магазина принудительно обновлен! Рассылка запущена.")

@dp.callback_query(F.data == "adm_db")
async def adm_db_func(callback: types.CallbackQuery):
    file = FSInputFile(DB_NAME)
    await callback.message.answer_document(file, caption="📦 Текущая БД. Чтобы восстановить/заменить, просто отправьте мне новый .db файл.")
    await callback.answer()

@dp.message(F.document)
async def process_bd_upload(message: types.Message):
    if not await is_admin(message.from_user.id): return
    if not message.document.file_name.endswith(".db"): return
    file = await bot.get_file(message.document.file_id)
    
    for ext in ["-wal", "-shm", "-journal"]:
        try:
            os.remove(f"{DB_NAME}{ext}")
        except OSError:
            pass
            
    await bot.download_file(file.file_path, DB_NAME)
    await check_and_update_schema()
    await log_admin(message.from_user.id, "DB Upload and Migration")
    await message.answer("✅ <b>БД успешно загружена и заменена!</b>")

# ========================================================================
# АДМИН-ПАНЕЛЬ: УПРАВЛЕНИЕ СИД-ПАКОВ (СОЗДАНИЕ, ИЗМЕНЕНИЕ ШАНСОВ, УДАЛЕНИЕ)
# ========================================================================
@dp.callback_query(F.data == "adm_sp_main")
async def cq_adm_sp_main(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать Сид-Пак", callback_data="adm_sp_create")],
        [InlineKeyboardButton(text="✏️ Редактировать / Удалить", callback_data="adm_sp_manage_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text(
        "📦 <b>УПРАВЛЕНИЕ СИД-ПАКАМИ</b>\n"
        "Здесь вы можете создавать новые тематические Сид-Паки и изменять их содержимое.", 
        reply_markup=kb
    )
    await callback.answer()

@dp.callback_query(F.data == "adm_sp_create")
async def cq_adm_sp_create_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("📦 <b>Создание Сид-Пака</b>\n\nШаг 1: Введите красивое НАЗВАНИЕ пака (например, <i>Mango Fest Pack</i>):")
    await state.set_state(CreateSeedPack.title)
    await callback.answer()

@dp.message(CreateSeedPack.title)
async def adm_sp_cr_title(message: types.Message, state: FSMContext):
    await state.update_data(sp_title=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True)
    await message.answer("Шаг 2: Отправьте ФОТО для пака (или нажмите Пропустить):", reply_markup=kb)
    await state.set_state(CreateSeedPack.photo)

@dp.message(CreateSeedPack.photo)
async def adm_sp_cr_photo(message: types.Message, state: FSMContext):
    if message.text == "Пропустить":
        await state.update_data(sp_photo=None)
    elif message.photo:
        await state.update_data(sp_photo=message.photo[-1].file_id)
    else:
        return await message.answer("Пожалуйста, отправьте фото или нажмите кнопку Пропустить.")
        
    await message.answer("Шаг 3: Введите описание Сид-Пака (например: <i>Набор с повышенными шансами на Огненные типы!</i>):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(CreateSeedPack.description)

@dp.message(CreateSeedPack.description)
async def adm_sp_cr_desc(message: types.Message, state: FSMContext):
    await state.update_data(sp_desc=message.text, sp_cards={})
    await cq_adm_sp_show_card_select(message, state, 0)

async def cq_adm_sp_show_card_select(message_or_call, state: FSMContext, page: int):
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    if not all_cards:
        if isinstance(message_or_call, types.CallbackQuery):
            await message_or_call.message.answer("❌ В базе нет ни одной карты для добавления!")
        else:
            await message_or_call.answer("❌ В базе нет ни одной карты для добавления!")
        return await state.clear()
        
    items = []
    for c in all_cards:
        items.append({"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']} (ID:{c['id']})"})
        
    kb = get_pagination_keyboard(items, page, "spaddc", columns=1, items_per_page=6)
    
    data = await state.get_data()
    sp_cards = data.get('sp_cards', {})
    
    current_list_str = ""
    if sp_cards:
        current_list_str = "\n<b>Текущий состав пака:</b>\n"
        for idx, (c_id, chance) in enumerate(sp_cards.items(), 1):
            c_info = await fetch_one("SELECT name FROM cards WHERE id = ?", (c_id,))
            current_list_str += f"{idx}. {c_info['name'] if c_info else 'ID ' + str(c_id)} — {chance}%\n"
            
    text = (
        f"⚙️ <b>Добавление карт в Сид-Пак</b>\n"
        f"Выберите карту из списка ниже, чтобы добавить её в Сид-Пак:\n"
        f"{current_list_str}\n"
        f"<i>Для продолжения или завершения выберите опцию в меню ниже.</i>"
    )
    
    kb.inline_keyboard.append([InlineKeyboardButton(text="✅ Завершить и проверить", callback_data="sp_create_finish")])
    
    if isinstance(message_or_call, types.CallbackQuery):
        try: await message_or_call.message.edit_text(text, reply_markup=kb)
        except: pass
    else:
        await message_or_call.answer(text, reply_markup=kb)
        
    await state.set_state(CreateSeedPack.card_select)

@dp.callback_query(CreateSeedPack.card_select, F.data.startswith("spaddc_page_"))
async def cb_adm_sp_cr_card_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    await cq_adm_sp_show_card_select(callback, state, page)
    await callback.answer()

@dp.callback_query(CreateSeedPack.card_select, F.data.startswith("spaddc_"))
async def cb_adm_sp_cr_card_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[1])
    
    card_info = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
    if not card_info:
        return await callback.answer("Карта не найдена!", show_alert=True)
        
    await state.update_data(sel_card_id=card_id)
    await callback.message.answer(f"Введите шанс выпадения (вес) для карты <b>{card_info['name']}</b> (например, 10 или 25.5):")
    await state.set_state(CreateSeedPack.card_chance)
    await callback.answer()

@dp.message(CreateSeedPack.card_chance)
async def adm_sp_cr_card_chance(message: types.Message, state: FSMContext):
    try:
        chance = float(message.text.replace(',', '.'))
        if chance <= 0: raise ValueError
        
        data = await state.get_data()
        sp_cards = data.get('sp_cards', {})
        sel_card_id = data['sel_card_id']
        
        sp_cards[sel_card_id] = chance
        await state.update_data(sp_cards=sp_cards)
        
        await message.answer("✅ Карта успешно добавлена в пак!")
        await cq_adm_sp_show_card_select(message, state, 0)
    except:
        await message.answer("❌ Введите положительное число!")

@dp.callback_query(CreateSeedPack.card_select, F.data == "sp_create_finish")
async def cb_adm_sp_finish_draft(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    sp_cards = data.get('sp_cards', {})
    
    if not sp_cards:
        return await callback.answer("❌ Пак не может быть пустым! Добавьте хотя бы одну карту.", show_alert=True)
        
    title = data['sp_title']
    desc = data['sp_desc']
    
    text = (
        f"🔬 <b>ПРОВЕРКА СИД-ПАКА</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 Название: <b>{title}</b>\n"
        f"💬 Описание: {desc}\n\n"
        f"📊 <b>Содержимое пака:</b>\n"
    )
    
    total_weights = sum(sp_cards.values())
    for idx, (c_id, chance) in enumerate(sp_cards.items(), 1):
        c_info = await fetch_one("SELECT name FROM cards WHERE id = ?", (c_id,))
        pct = (chance / total_weights) * 100 if total_weights > 0 else 0
        text += f"  └ {idx}. {c_info['name'] if c_info else 'ID ' + str(c_id)} — {chance} (вероятность ~{pct:.2f}%)\n"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 СОХРАНИТЬ И ОПУБЛИКОВАТЬ", callback_data="sp_draft_save")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="sp_draft_cancel")]
    ])
    
    if data['bp_photo']:
        await callback.message.answer_photo(photo=data['bp_photo'], caption=text, reply_markup=kb)
        await callback.message.delete()
    else:
        await callback.message.answer(text, reply_markup=kb)
        await callback.message.delete()
        
    await state.set_state(CreateSeedPack.confirm_save)
    await callback.answer()

@dp.callback_query(CreateSeedPack.confirm_save, F.data == "sp_draft_save")
async def cb_adm_sp_save_draft(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    title = data['sp_title']
    desc = data['sp_desc']
    photo = data.get('bp_photo') # Используем сохраненное поле фото
    sp_cards = data.get('sp_cards', {})
    
    db = await get_db_connection()
    try:
        await db.execute("BEGIN")
        cursor = await db.execute(
            "INSERT INTO seed_packs (title, photo_id, description, price) VALUES (?, ?, ?, 2000)",
            (title, photo, desc)
        )
        pack_id = cursor.lastrowid
        
        for c_id, chance in sp_cards.items():
            await db.execute(
                "INSERT INTO seed_pack_cards (pack_id, card_id, drop_chance) VALUES (?, ?, ?)",
                (pack_id, c_id, chance)
            )
            
        await db.commit()
        await callback.message.answer(f"🎉 Сид-Пак «<b>{title}</b>» успешно создан и добавлен в магазин!")
        await log_admin(callback.from_user.id, f"Создал новый Сид-Пак: {title}")
    except Exception as e:
        await db.execute("ROLLBACK")
        await callback.message.answer(f"❌ Ошибка сохранения Сид-Пака: {e}")
    finally:
        await db.close()
        
    await state.clear()
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(CreateSeedPack.confirm_save, F.data == "sp_draft_cancel")
async def cb_adm_sp_cancel_draft(callback: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("❌ Создание Сид-Пака отменено.")
    await callback.message.delete()
    await callback.answer()

# ========================================================================
# РЕДАКТИРОВАНИЕ СИД-ПАКОВ (ШУСТРЫЙ ИНТЕРФЕЙС С FSM)
# ========================================================================
@dp.callback_query(F.data == "adm_sp_manage_list")
async def cb_adm_sp_manage_list(callback: types.CallbackQuery, state: FSMContext):
    packs = await fetch_all("SELECT * FROM seed_packs")
    if not packs:
        return await callback.answer("❌ На сервере нет созданных Сид-Паков!", show_alert=True)
        
    text = "📝 <b>Выбор Сид-Пака для редактирования:</b>"
    kb = []
    for p in packs:
        kb.append([InlineKeyboardButton(text=f"⚙️ Редактировать: {p['title']}", callback_data=f"sp_edit_pack_id_{p['id']}")])
        
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_sp_main")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("sp_edit_pack_id_"))
async def cb_adm_sp_edit_menu(callback: types.CallbackQuery, state: FSMContext):
    pack_id = int(callback.data.split("_")[4])
    pack = await fetch_one("SELECT * FROM seed_packs WHERE id = ?", (pack_id,))
    
    if not pack:
        return await callback.answer("❌ Сид-пак не найден!", show_alert=True)
        
    pack_cards = await fetch_all("""
        SELECT c.name, spc.card_id, spc.drop_chance 
        FROM seed_pack_cards spc 
        JOIN cards c ON spc.card_id = c.id 
        WHERE spc.pack_id = ?
    """, (pack_id,))
    
    text = (
        f"⚙️ <b>РЕДАКТИРОВАНИЕ: {pack['title']}</b>\n"
        f"💬 Описание: <i>{pack['description'] or 'Отсутствует'}</i>\n"
        f"💵 Цена в магазине: <b>{pack['price']} Шекелей</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Содержимое пака:</b>\n"
    )
    
    if not pack_cards:
        text += "  └ <i>Пак пуст!</i>\n"
    else:
        total_w = sum(c['drop_chance'] for c in pack_cards)
        for idx, c in enumerate(pack_cards, 1):
            chance_pct = (c['drop_chance'] / total_w) * 100 if total_w > 0 else 0
            text += f"  {idx}. {c['name']} (Вес: {c['drop_chance']} | ~{chance_str := f'{real_chance:.2f}%' if (real_chance := (c['drop_chance']/total_w)*100 if total_w > 0 else 0) else '0%'}%)\n"
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Название", callback_data=f"sp_edval_title_{pack_id}"),
         InlineKeyboardButton(text="✏️ Описание", callback_data=f"sp_edval_desc_{pack_id}")],
        [InlineKeyboardButton(text="✏️ Фото", callback_data=f"sp_edval_photo_{pack_id}"),
         InlineKeyboardButton(text="➕ Добавить юнита", callback_data=f"sp_edval_addcard_{pack_id}")],
        [InlineKeyboardButton(text="⚙️ Изменить шансы / Удалить юнитов", callback_data=f"sp_edval_cards_list_{pack_id}")],
        [InlineKeyboardButton(text="🗑 УДАЛИТЬ СИД-ПАК ПОЛНОСТЬЮ", callback_data=f"sp_edval_delete_pack_{pack_id}")],
        [InlineKeyboardButton(text="🔙 Назад к списку", callback_data="adm_sp_manage_list")]
    ])
    
    await state.update_data(editing_pack_id=pack_id)
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(EditSeedPack.menu)
    await callback.answer()

@dp.callback_query(EditSeedPack.menu, F.data.startswith("sp_edval_"))
async def cb_sp_edit_field(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    field = parts[2]
    pack_id = int(parts[3])
    
    if field == "title":
        await callback.message.answer("Введите НОВОЕ название для Сид-Пака:")
        await state.set_state(EditSeedPack.edit_title)
    elif field == "desc":
        await callback.message.answer("Введите НОВОЕ описание для Сид-Пака:")
        await state.set_state(EditSeedPack.edit_description)
    elif field == "photo":
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить (Удалить фото)")]], resize_keyboard=True)
        await callback.message.answer("Отправьте новое ФОТО для Сид-Пака (или нажмите кнопку снизу):", reply_markup=kb)
        await state.set_state(EditSeedPack.edit_photo)
    elif field == "addcard":
        all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
        items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']} (ID:{c['id']})"} for c in all_cards]
        await state.update_data(add_card_items=items)
        kb = get_pagination_keyboard(items, 0, "sp_ed_addc", columns=1, items_per_page=6)
        kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 В меню редактирования", callback_data=f"sp_edit_pack_id_{pack_id}")])
        await callback.message.edit_text("Выберите карту из базы данных для добавления в Сид-Пак:", reply_markup=kb)
        await state.set_state(EditSeedPack.add_card_select)
    elif field == "cards_list":
        await cq_sp_edit_manage_cards(callback, state, pack_id)
    elif field == "delete_pack":
        await cq_sp_edit_delete_pack(callback, pack_id)
        
    await callback.answer()

# Сохранение текстовых полей сид пака
@dp.message(EditSeedPack.edit_title)
async def adm_sp_edit_title_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pack_id = data['editing_pack_id']
    new_title = message.text.strip()
    
    await execute_db("UPDATE seed_packs SET title = ? WHERE id = ?", (new_title, pack_id))
    await log_admin(message.from_user.id, f"Сид-Пак {pack_id} новое название: {new_title}")
    
    await message.answer("✅ Название успешно обновлено!")
    # Возвращаемся в меню
    fake_call = types.CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data=f"sp_edit_pack_id_{pack_id}")
    await cb_adm_sp_edit_menu(fake_call, state)

@dp.message(EditSeedPack.edit_description)
async def adm_sp_edit_desc_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pack_id = data['editing_pack_id']
    new_desc = message.text.strip()
    
    await execute_db("UPDATE seed_packs SET description = ? WHERE id = ?", (new_desc, pack_id))
    await log_admin(message.from_user.id, f"Сид-Пак {pack_id} новое описание: {new_desc}")
    
    await message.answer("✅ Описание успешно обновлено!")
    fake_call = types.CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data=f"sp_edit_pack_id_{pack_id}")
    await cb_adm_sp_edit_menu(fake_call, state)

@dp.message(EditSeedPack.edit_photo)
async def adm_sp_edit_photo_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    pack_id = data['editing_pack_id']
    
    photo_id = None
    if message.photo:
        photo_id = message.photo[-1].file_id
        await message.answer("✅ Фото Сид-Пака успешно обновлено!", reply_markup=ReplyKeyboardRemove())
    else:
        await message.answer("✅ Фото удалено из Сид-Пака!", reply_markup=ReplyKeyboardRemove())
        
    await execute_db("UPDATE seed_packs SET photo_id = ? WHERE id = ?", (photo_id, pack_id))
    fake_call = types.CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data=f"sp_edit_pack_id_{pack_id}")
    await cb_adm_sp_edit_menu(fake_call, state)

# Добавление карт в существующий сид-пак
@dp.callback_query(EditSeedPack.add_card_select, F.data.startswith("sp_ed_addc_page_"))
async def cb_sp_edit_add_card_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[4])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('add_card_items', []), page, "sp_ed_addc", columns=1, items_per_page=6)
    pack_id = data['editing_pack_id']
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 В меню редактирования", callback_data=f"sp_edit_pack_id_{pack_id}")])
    try: await callback.message.edit_reply_markup(reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(EditSeedPack.add_card_select, F.data.startswith("sp_ed_addc_"))
async def cb_sp_edit_add_card_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[3])
    
    card_info = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
    if not card_info: return await callback.answer("Карта не найдена!", show_alert=True)
    
    await state.update_data(edit_add_card_id=card_id)
    await callback.message.answer(f"Введите шанс выпадения (вес) для карты <b>{card_info['name']}</b>:")
    await state.set_state(EditSeedPack.add_card_chance)
    await callback.answer()

@dp.message(EditSeedPack.add_card_chance)
async def adm_sp_edit_add_card_chance_save(message: types.Message, state: FSMContext):
    try:
        chance = float(message.text.replace(',', '.'))
        if chance <= 0: raise ValueError
        
        data = await state.get_data()
        pack_id = data['editing_pack_id']
        card_id = data['edit_add_card_id']
        
        await execute_db(
            "INSERT INTO seed_pack_cards (pack_id, card_id, drop_chance) VALUES (?, ?, ?) "
            "ON CONFLICT(pack_id, card_id) DO UPDATE SET drop_chance = ?",
            (pack_id, card_id, chance, chance)
        )
        
        await message.answer("✅ Карта успешно добавлена / обновлена в Сид-Паке!")
        fake_call = types.CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data=f"sp_edit_pack_id_{pack_id}")
        await cb_adm_sp_edit_menu(fake_call, state)
    except:
        await message.answer("❌ Введите положительное число.")

# Изменение и удаление существующих карт в паке
async def cq_sp_edit_manage_cards(callback: types.CallbackQuery, state: FSMContext, pack_id: int):
    pack_cards = await fetch_all("""
        SELECT c.name, spc.card_id, spc.drop_chance 
        FROM seed_pack_cards spc 
        JOIN cards c ON spc.card_id = c.id 
        WHERE spc.pack_id = ?
    """, (pack_id,))
    
    if not pack_cards:
        return await callback.answer("❌ В Сид-Паке нет карт для настройки!", show_alert=True)
        
    text = "⚙️ <b>Выберите карту для настройки шанса или удаления:</b>"
    kb = []
    for c in pack_cards:
        kb.append([
            InlineKeyboardButton(text=f"✏️ {c['name']} ({c['drop_chance']})", callback_data=f"sp_cact_edit_{pack_id}_{c['card_id']}"),
            InlineKeyboardButton(text=f"🗑 Удалить", callback_data=f"sp_cact_del_{pack_id}_{c['card_id']}")
        ])
    kb.append([InlineKeyboardButton(text="🔙 В меню редактирования", callback_data=f"sp_edit_pack_id_{pack_id}")])
    
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(EditSeedPack.menu, F.data.startswith("sp_cact_"))
async def cb_sp_edit_card_action(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    action = parts[2]
    pack_id = int(parts[3])
    card_id = int(parts[4])
    
    if action == "del":
        await execute_db("DELETE FROM seed_pack_cards WHERE pack_id = ? AND card_id = ?", (pack_id, card_id))
        await callback.answer("✅ Юнит удален из Сид-Пака!", show_alert=True)
        await cq_sp_edit_manage_cards(callback, state, pack_id)
    elif action == "edit":
        card_info = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
        await state.update_data(edit_chance_card_id=card_id)
        await callback.message.answer(f"Введите новое значение шанса (веса) для карты <b>{card_info['name']}</b>:")
        await state.set_state(EditSeedPack.card_edit_chance)
        await callback.answer()

@dp.message(EditSeedPack.card_edit_chance)
async def adm_sp_edit_card_chance_save(message: types.Message, state: FSMContext):
    try:
        chance = float(message.text.replace(',', '.'))
        if chance <= 0: raise ValueError
        
        data = await state.get_data()
        pack_id = data['editing_pack_id']
        card_id = data['edit_chance_card_id']
        
        await execute_db("UPDATE seed_pack_cards SET drop_chance = ? WHERE pack_id = ? AND card_id = ?", (chance, pack_id, card_id))
        await message.answer("✅ Шанс успешно изменен!")
        fake_call = types.CallbackQuery(id="0", from_user=message.from_user, chat_instance="0", message=message, data=f"sp_edit_pack_id_{pack_id}")
        await cb_adm_sp_edit_menu(fake_call, state)
    except:
        await message.answer("❌ Введите положительное число.")

# Полное удаление Сид-Пака
async def cq_sp_edit_delete_pack(callback: types.CallbackQuery, pack_id: int):
    pack_info = await fetch_one("SELECT title FROM seed_packs WHERE id = ?", (pack_id,))
    name = pack_info['title'] if pack_info else f"ID {pack_id}"
    
    await execute_db("DELETE FROM seed_packs WHERE id = ?", (pack_id,))
    await execute_db("DELETE FROM seed_pack_cards WHERE pack_id = ?", (pack_id,))
    await execute_db("DELETE FROM user_seed_packs WHERE pack_id = ?", (pack_id,))
    
    await log_admin(callback.from_user.id, f"Удалил полностью Сид-Пак: {name}")
    await callback.answer(f"✅ Сид-Пак «{name}» полностью удален!", show_alert=True)
    await cb_adm_sp_manage_list(callback, None)


# ========================================================================
# ЗАПУСК БОТА И ФОНОВЫХ ЗАДАЧ
# ========================================================================
async def main():
    await check_and_update_schema()
    
    shop_exists = await fetch_all("SELECT * FROM shop_items")
    if not shop_exists: await restock_shop()
    
    settings = await fetch_one("SELECT last_lb_reward FROM server_settings WHERE id = 1")
    if settings and settings['last_lb_reward'] == 0:
        await execute_db("UPDATE server_settings SET last_lb_reward = ? WHERE id = 1", (time.time(),))
    
    asyncio.create_task(shop_auto_restock_task())
    asyncio.create_task(leaderboard_rewards_task())
    asyncio.create_task(trade_timeout_task())
    
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="getcard", description="Выбить карту (Гача)"),
        BotCommand(command="shop", description="Магазин"),
        BotCommand(command="inventory", description="Инвентарь"),
        BotCommand(command="equip", description="Экипировка колоды"),
        BotCommand(command="profile", description="Профиль и статы"),
        BotCommand(command="quests", description="Квесты"),
        BotCommand(command="index", description="Индекс всех карт"),
        BotCommand(command="top", description="Рейтинг игроков")
    ]
    await bot.set_my_commands(commands)
    
    logging.info("🤖 Карточный бот запущен (Батл-пасс + Кошмар + UI Rework + Сигны + Сид-Паки + Ивенты)!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
        
