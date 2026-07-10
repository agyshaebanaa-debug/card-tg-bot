import asyncio
import logging
import random
import time
import io
import os
import math
import string
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
# ЛОКАЛИЗАЦИЯ (МУЛЬТИЯЗЫЧНОСТЬ)
# ========================================================================
def loc(lang: str, ru_text: str, en_text: str) -> str:
    return ru_text if lang == "ru" else en_text

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
    "Fire": "🔥",
    "Healer": "💗"
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
pvp_queue = set()
active_manual_battles = {} 
surrendered_players = set() 

# Временные хранилища сессий для крафтов
active_crafts = {}
active_upgrades = {}

SHOP_PACKAGES = [
    ("1_rnd", "1 Случайная карта", "1 Random Card", 100, 20, 1.0),
    ("3_rnd", "3 Случайные карты", "3 Random Cards", 275, 20, 0.9),
    ("5_rnd", "5 Случайных карт", "5 Random Cards", 450, 20, 0.9),
    ("10_rnd", "10 Случайных карт", "10 Random Cards", 900, 15, 0.8),
    ("25_rnd", "25 Случайных карт", "25 Random Cards", 2300, 10, 0.7),
    ("50_rnd", "50 Случайных карт", "50 Random Cards", 4500, 3, 0.6),
    ("100_rnd", "100 Случайных карт", "100 Random Cards", 9000, 2, 0.5),
    ("rnd_leg", "Случайная Легендарная", "Random Legendary", 1000, 5, 0.7), 
    ("rnd_myth", "Случайная Мифическая", "Random Mythic", 12500, 3, 0.4), 
    ("rnd_sup", "Случайная Супер Карта", "Random Super Card", 80000, 1, 0.2) 
]

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
BTN_ENDLESS = ["♾ Бесконечный режим", "♾ Endless Mode"]
BTN_CRAFT = ["🔨 Крафт", "🔨 Craft"]

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
                equip4 INTEGER DEFAULT 0,
                quests_cooldown REAL DEFAULT 0,
                pity_mythic INTEGER DEFAULT 0,
                pity_super INTEGER DEFAULT 0,
                lang TEXT DEFAULT 'ru'
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_action_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                action TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        for col in ['first_name', 'q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys', 'quests_cooldown', 'pity_mythic', 'pity_super', 'equip4', 'q_pvp_played', 'q_heals_done']:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            except aiosqlite.OperationalError: pass

        for col in ['notif_shop', 'notif_events', 'notif_quests', 'notif_announces']:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 1")
            except aiosqlite.OperationalError: pass
            
        detailed_shop_notifs = [
            'notif_1_rnd', 'notif_3_rnd', 'notif_5_rnd', 'notif_10_rnd', 
            'notif_25_rnd', 'notif_50_rnd', 'notif_100_rnd', 
            'notif_rnd_leg', 'notif_rnd_myth', 'notif_rnd_sup'
        ]
        for col in detailed_shop_notifs:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 1")
            except aiosqlite.OperationalError: pass
            
        try: await db.execute("ALTER TABLE users ADD COLUMN lang TEXT DEFAULT 'ru'")
        except aiosqlite.OperationalError: pass
        
        modifiers = ['mod_enemy_hp', 'mod_enemy_atk_all', 'mod_enemy_stats', 'mod_player_atk_all', 'mod_manual_atk', 'mod_player_hp']
        for col in modifiers:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS seed_packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                photo_id TEXT,
                description TEXT,
                price INTEGER DEFAULT 2000
            )
        """)
        
        try: await db.execute("ALTER TABLE seed_packs ADD COLUMN price INTEGER DEFAULT 2000")
        except aiosqlite.OperationalError: pass
        
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

        await db.execute("""CREATE TABLE IF NOT EXISTS shop_items (id INTEGER PRIMARY KEY AUTOINCREMENT, item_type TEXT, name TEXT, name_en TEXT, price INTEGER, stock INTEGER)""")
        try: await db.execute("ALTER TABLE shop_items ADD COLUMN name_en TEXT")
        except aiosqlite.OperationalError: pass

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
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reward_codes (
                code TEXT PRIMARY KEY,
                reward_type TEXT,
                amount INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                mutation TEXT DEFAULT 'Normal',
                owner_id INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Таблицы для крафтов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS craft_recipes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                target_card_id INTEGER,
                price INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS craft_ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id INTEGER,
                card_id INTEGER,
                amount INTEGER DEFAULT 1
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

async def log_user_action(user_id: int, action: str):
    try:
        await execute_db("INSERT INTO user_action_logs (user_id, action) VALUES (?, ?)", (user_id, action))
    except Exception as e:
        logging.error(f"Failed to log user action: {e}")

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
    custom_serial = State()

class TakeCard(StatesGroup):
    user_id = State()
    inv_id = State()
    amount = State()

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
    view_logs_id = State()
    
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

class CreateSeedPack(StatesGroup):
    title = State()
    photo = State()
    description = State()
    price = State()
    card_select = State()
    card_chance = State()
    confirm_save = State()

class EditSeedPack(StatesGroup):
    select_pack = State()
    menu = State()
    edit_title = State()
    edit_photo = State()
    edit_description = State()
    edit_price = State()
    card_edit_chance = State()
    add_card_select = State()
    add_card_chance = State()

class AdminRewardCode(StatesGroup):
    count = State()
    r_type = State()
    amount = State()
    card_id = State()
    mutation = State()
    pack_id = State()

class UserUseCode(StatesGroup):
    waiting_code = State()

class AdminCraftCreate(StatesGroup):
    target_card = State()
    price = State()
    add_ingredient_card = State()
    add_ingredient_amount = State()

# ========================================================================
# УТИЛИТЫ И ХЕЛПЕРЫ ДЛЯ UI
# ========================================================================
def get_display_name(user_data: dict) -> str:
    if user_data.get('username'): return f"@{user_data['username']}"
    elif user_data.get('first_name'): return user_data['first_name']
    return f"Player {user_data.get('id', '???')}"

async def get_user_titles_str(user_id: int, lang: str = "ru") -> str:
    titles = []
    if await is_admin(user_id): titles.append(loc(lang, "👑 Администратор", "👑 Admin"))
    if await is_signer(user_id): titles.append(loc(lang, "✍️ Сигнер", "✍️ Signer"))
    
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
    if field not in ['q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys', 'q_pvp_played', 'q_heals_done']:
        return
        
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user or user['quests_cooldown'] > time.time():
        return
        
    await execute_db(f"UPDATE users SET {field} = {field} + ? WHERE id = ?", (amount, user_id))
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    
    if (user['q_cards_opened'] >= 10 and
        user['q_battles'] >= 5 and
        user['q_pvp_played'] >= 3 and
        user['q_shop_buys'] >= 1 and
        user['q_heals_done'] >= 5):
        
        await execute_db("""
            UPDATE users SET
                coins = coins + 1200,
                q_cards_opened = 0,
                q_battles = 0,
                q_pvp_played = 0,
                q_shop_buys = 0,
                q_heals_done = 0,
                quests_cooldown = ?
            WHERE id = ?
        """, (time.time() + 3600, user_id))
        
        packs = await fetch_all("SELECT id, title FROM seed_packs")
        pack_reward_text = ""
        if packs:
            gift_pack = random.choice(packs)
            await execute_db("""
                INSERT INTO user_seed_packs (user_id, pack_id, count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + 1
            """, (user_id, gift_pack['id']))
            pack_reward_text = loc(user['lang'], f"\n📦 А также вы получили Сид-Пак: <b>{gift_pack['title']}</b> (1 шт.)!", f"\n📦 Also you received a Seed-Pack: <b>{gift_pack['title']}</b> (1x)!")
        
        if user['notif_quests'] == 1:
            try:
                msg = loc(user['lang'],
                          f"🎉 <b>ПОЗДРАВЛЯЕМ!</b>\nВы выполнили все ежедневные квесты и получили <b>1200 💰 Шекелей</b>!{pack_reward_text}\nВозвращайтесь через 1 час за новыми заданиями!",
                          f"🎉 <b>CONGRATULATIONS!</b>\nYou completed all daily quests and got <b>1200 💰 Shekels</b>!{pack_reward_text}\nCome back in 1 hour for new tasks!")
                await bot.send_message(user_id, msg)
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
    try: await bot.send_message(SUPER_ADMIN_ID, f"⚠️ <b>ADMIN LOG:</b>\n{text}")
    except Exception as e: logging.error(f"Не удалось отправить лог: {e}")

async def log_admin(admin_id: int, action: str):
    await execute_db("INSERT INTO admin_logs (admin_id, action) VALUES (?, ?)", (admin_id, action))
    admin_info = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (admin_id,))
    name = get_display_name(admin_info) if admin_info else f"ID {admin_id}"
    await notify_super_admin(f"Admin: <b>{name}</b> ({admin_id})\nAction: {action}")

async def broadcast_message(text_ru: str, text_en: str, notif_type: str = None, shop_types: set = None):
    query = "SELECT * FROM users WHERE banned = 0"
    if notif_type:
        query += f" AND {notif_type} = 1"
        
    users = await fetch_all(query)
    success = 0
    for u in users:
        if shop_types:
            wants = False
            for st in shop_types:
                col = f"notif_{st}"
                if u.get(col) == 1:
                    wants = True
                    break
            if not wants: continue
            
        try:
            msg = text_ru if u['lang'] == 'ru' else text_en
            await bot.send_message(u['id'], msg)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await notify_super_admin(f"📢 <b>Broadcast complete.</b>\nDelivered: {success}")

def get_main_keyboard(is_adm: bool = False, is_sgn: bool = False, lang: str = "ru"):
    i = 0 if lang == "ru" else 1
    kb = [
        [KeyboardButton(text=BTN_DRAW[i]), KeyboardButton(text=BTN_PVE[i]), KeyboardButton(text=BTN_PVP[i])],
        [KeyboardButton(text=BTN_INV[i]), KeyboardButton(text=BTN_PROF[i]), KeyboardButton(text=BTN_EQ[i])],
        [KeyboardButton(text=BTN_QUESTS[i]), KeyboardButton(text=BTN_SHOP[i]), KeyboardButton(text=BTN_BP[i])],
        [KeyboardButton(text=BTN_TOP[i]), KeyboardButton(text=BTN_IDX[i]), KeyboardButton(text=BTN_SEED_PACKS[i])],
        [KeyboardButton(text=BTN_ENDLESS[i]), KeyboardButton(text=BTN_CRAFT[i]), KeyboardButton(text=BTN_SET[i])]
    ]
    
    bottom_row = []
    if is_sgn: bottom_row.append(KeyboardButton(text=BTN_SIGN[i]))
    if is_adm: bottom_row.append(KeyboardButton(text=BTN_ADM[i]))
    if bottom_row: kb.append(bottom_row)
        
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_user_rank(trophies: int):
    ranks = await fetch_all("SELECT * FROM ranks ORDER BY min_trophies DESC")
    for idx, r in enumerate(ranks):
        if trophies >= r['min_trophies']: 
            res = dict(r)
            res['rank_idx'] = len(ranks) - idx - 1
            return res
    return {"name": "Bronze I", "difficulty_mult": 0.8, "reward_mult": 1.0, "rank_idx": 0}

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

def roll_seed_pack_mutation():
    r = random.random()
    if r <= 0.02: return "Rainbow"
    if r <= 0.14: return "Gold"
    return "Normal"

def get_mutation_multiplier(mutation: str) -> float:
    if mutation == "Rainbow": return 1.2
    if mutation == "Gold": return 1.1
    return 1.0

def needs_serial_number(rarity: str, mutation: str) -> bool:
    if rarity == 'Leaderboard': return True
    if rarity in ['Mythic', 'Super']: return True
    if rarity == 'Legendary' and mutation in ['Gold', 'Rainbow']: return True
    return False

async def give_card_to_user(user_id: int, card_id: int, mutation: str, rarity: str = None, custom_serial: int = None) -> tuple:
    if not rarity:
        card = await fetch_one("SELECT rarity FROM cards WHERE id = ?", (card_id,))
        rarity = card['rarity'] if card else 'Basic'
        
    db = await get_db_connection()
    try:
        if custom_serial is not None and custom_serial > 0:
            cursor = await db.execute(
                "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, ?, 0)",
                (user_id, card_id, mutation, custom_serial)
            )
            return cursor.lastrowid, custom_serial, True
            
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

    img_temp = Image.new("RGBA", bg.size)
    img_temp.paste(img, (0, 0), img)
    final_rgba = Image.alpha_composite(bg, img_temp)
    final_img = final_rgba.convert("RGB")
    
    border_color = "purple" if color == "rainbow" else color
    bordered_img = ImageOps.expand(final_img, border=20, fill=border_color)
    
    bio = io.BytesIO()
    bordered_img.save(bio, format='JPEG')
    bio.seek(0)
    
    msg = await bot.send_photo(chat_id=SUPER_ADMIN_ID, photo=types.BufferedInputFile(bio.read(), filename="card.jpg"), caption=f"Generated frame: {rarity}")
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
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"{prefix}_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"{prefix}_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=kb)

def generate_reward_code() -> str:
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=28))

async def clear_fsm_timeout(state: FSMContext, chat_id: int, delay: int = 60):
    await asyncio.sleep(delay)
    curr = await state.get_state()
    if curr in [TradeState.waiting_target.state, PvPState.waiting_target.state]:
        await state.clear()
        try:
            await bot.send_message(chat_id, "⏳ <i>Время ожидания истекло (1 минута). Команда сброшена.</i>")
        except: pass

async def get_card_sources(card_id: int) -> str:
    sources = []
    packs = await fetch_all("SELECT p.title FROM seed_pack_cards spc JOIN seed_packs p ON spc.pack_id = p.id WHERE spc.card_id = ?", (card_id,))
    if packs:
        sources.append("📦 Сид-Паки: " + ", ".join([p['title'] for p in packs]))
    
    c = await fetch_one("SELECT drop_chance, rarity FROM cards WHERE id = ?", (card_id,))
    if c:
        if c['drop_chance'] > 0 and c['rarity'] != 'Leaderboard':
            sources.append("🎲 Гача (/getcard) / Магазин")
        if c['rarity'] == 'Leaderboard':
            sources.append("🏆 Топ игроков (Лидерборд)")
            
    bps = await fetch_all("SELECT bp.title FROM bp_rewards bpr JOIN bp_levels bpl ON bpr.level_id = bpl.id JOIN battle_passes bp ON bpl.bp_id = bp.id WHERE bpr.card_id = ?", (card_id,))
    if bps:
        sources.append("🎟 Батл-Пасс: " + ", ".join(list(set([b['title'] for b in bps]))))
        
    if not sources:
        return "Невозможно получить (Эксклюзив)"
    return "\n".join(f"  └ {s}" for s in sources)

# ========================================================================
# ЛОГИКА ШАНСОВ И МАГАЗИНА И PITY
# ========================================================================
async def calculate_chance_weights(luck_mult: float = 1.0):
    all_cards = await fetch_all("""
        SELECT * FROM cards 
        WHERE drop_chance > 0 
        AND rarity != 'Leaderboard'
        AND id NOT IN (SELECT card_id FROM seed_pack_cards)
    """)
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
    spawned_types = set()
    try:
        spawned_any = False
        for p_id, p_name_ru, p_name_en, p_price, p_max, p_chance in SHOP_PACKAGES:
            if random.random() <= p_chance:
                stock = random.randint(1, p_max)
                await db.execute("INSERT INTO shop_items (item_type, name, name_en, price, stock) VALUES (?, ?, ?, ?, ?)", (p_id, p_name_ru, p_name_en, p_price, stock))
                spawned_any = True
                spawned_types.add(p_id)
                
        await db.execute("UPDATE server_settings SET last_restock = ? WHERE id = 1", (time.time(),))
        await db.commit()
    finally:
        await db.close()
        
    if spawned_any:
        msg_ru = "🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН ОБНОВИЛСЯ!</b>\nЗавезли свежие наборы карт. Количество ограничено, успей купить!\nИспользуй кнопку в меню или /shop"
        msg_en = "🛒 <b>GLOBAL SHOP RESTOCKED!</b>\nNew card packs are available. Quantity is limited, hurry!\nUse the menu button or /shop"
        asyncio.create_task(broadcast_message(msg_ru, msg_en, notif_type="notif_shop", shop_types=spawned_types))

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

    all_cards = await fetch_all("""
        SELECT * FROM cards 
        WHERE drop_chance > 0 
        AND rarity != 'Leaderboard'
        AND id NOT IN (SELECT card_id FROM seed_pack_cards)
    """)
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
                top_users = await fetch_all("SELECT id, lang, trophies, username, first_name FROM users ORDER BY trophies DESC LIMIT 20")
                if top_users:
                    for idx, user in enumerate(top_users):
                        pos = idx + 1
                        if pos == 1: bracket = "1"
                        elif pos == 2: bracket = "2"
                        elif pos == 3: bracket = "3"
                        elif pos <= 9: bracket = "4_9"
                        else: bracket = "10_20"
                        
                        rewards = await fetch_all("SELECT * FROM lb_rewards WHERE bracket = ?", (bracket,))
                        reward_msgs_ru = []
                        reward_msgs_en = []
                        for r in rewards:
                            if r['reward_type'] == 'shekels':
                                await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (r['amount'], user['id']))
                                reward_msgs_ru.append(f"💰 {r['amount']} Шекелей")
                                reward_msgs_en.append(f"💰 {r['amount']} Shekels")
                            elif r['reward_type'] == 'card':
                                c_info = await fetch_one("SELECT name, rarity FROM cards WHERE id = ?", (r['card_id'],))
                                if c_info:
                                    _, serial, _ = await give_card_to_user(user['id'], r['card_id'], r['mutation'], c_info['rarity'])
                                    mut_str = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                                    s_str = f" [#{serial:04d}]" if serial > 0 else ""
                                    reward_msgs_ru.append(f"🃏 {mut_str} {c_info['name']}{s_str}")
                                    reward_msgs_en.append(f"🃏 {mut_str} {c_info['name']}{s_str}")
                                    
                        if rewards:
                            msg_text = loc(user['lang'],
                                f"🏆 <b>ГРАНДИОЗНАЯ НАГРАДА ЗА ТОП ИГРОКОВ!</b> 🏆\n\nПоздравляем! Вы заняли <b>{pos} место</b> в мире!\n\n🎁 <b>Награда:</b>\n" + "\n".join([f"🔸 {m}" for m in reward_msgs_ru]) + "\n\n<i>Рейтинг сброшен. Удачи!</i>",
                                f"🏆 <b>LEADERBOARD GRAND REWARD!</b> 🏆\n\nCongratulations! You placed <b>#{pos}</b> in the world!\n\n🎁 <b>Reward:</b>\n" + "\n".join([f"🔸 {m}" for m in reward_msgs_en]) + "\n\n<i>Leaderboard reset. Good luck!</i>"
                            )
                            try: await bot.send_message(user['id'], msg_text)
                            except: pass
                            
                await execute_db("UPDATE server_settings SET last_lb_reward = ? WHERE id = 1", (now,))
        except Exception as e:
            logging.error(f"LB Rewards error: {e}")
        await asyncio.sleep(600)

async def auto_backup_db():
    while True:
        await asyncio.sleep(4 * 3600) 
        try:
            file = FSInputFile(DB_NAME)
            await bot.send_document(SUPER_ADMIN_ID, file, caption="📦 Автоматический бэкап БД (каждые 4 часа).")
            logging.info("Auto DB backup sent to Super Admin.")
        except Exception as e:
            logging.error(f"Auto DB Backup error: {e}")

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
    
    if message.from_user.id in active_combats:
        surrendered_players.add(message.from_user.id)
        
    await log_user_action(message.from_user.id, "Открыл главное меню (/start)")

    user = await fetch_one("SELECT lang FROM users WHERE id = ?", (message.from_user.id,))
    lang = user['lang'] if user else "ru"

    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    
    text = loc(lang,
        "👋 <b>Добро пожаловать в Card Battle Bot!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Собери свою колоду уникальных юнитов, прокачивай Батл-пасс, выставляй их в бой и поднимай кубки на арене!\n\n"
        "📞 Тех.поддержка: @ggtdcards_support\n"
        "📰 Новости: @ggtdcardsnews\n"
        "📧 Почта: ggtdcards@gmail.com\n\n"
        "👇 <i>Используй красивое меню снизу для навигации:</i>",
        
        "👋 <b>Welcome to Card Battle Bot!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Collect your deck of unique units, level up the Battle Pass, fight in battles and climb the arena leaderboard!\n\n"
        "📞 Tech Support: @ggtdcards_support\n"
        "📰 News: @ggtdcardsnews\n"
        "📧 Email: ggtdcards@gmail.com\n\n"
        "👇 <i>Use the menu below to navigate:</i>"
    )
    await message.answer(text, reply_markup=get_main_keyboard(adm, sgn, lang))

@dp.message(F.text.in_(BTN_ENDLESS))
async def cmd_endless(message: types.Message):
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang'] if user else 'ru'
    text = loc(lang,
        "♾ <b>БЕСКОНЕЧНЫЙ РЕЖИМ НАХОДИТСЯ В РАЗРАБОТКЕ!</b>\n\n"
        "Совсем скоро здесь появится возможность бросить вызов волнам врагов и получать эксклюзивные награды.\n\n"
        "Следите за новостями и связывайтесь с нами:\n"
        "📰 Новости: @ggtdcardsnews\n"
        "📞 Тех.поддержка: @ggtdcards_support\n"
        "📧 Почта: ggtdcards@gmail.com",
        
        "♾ <b>ENDLESS MODE IS IN DEVELOPMENT!</b>\n\n"
        "Very soon you will be able to challenge waves of enemies here and earn exclusive rewards.\n\n"
        "Follow our news and contact us:\n"
        "📰 News: @ggtdcardsnews\n"
        "📞 Tech Support: @ggtdcards_support\n"
        "📧 Email: ggtdcards@gmail.com"
    )
    await message.answer(text)

@dp.message(F.text.in_(BTN_SET))
async def cmd_settings(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id=?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    
    lang = user['lang']
    text = loc(lang, "⚙️ <b>НАСТРОЙКИ АККАУНТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━", "⚙️ <b>ACCOUNT SETTINGS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🌐 Language: {'🇷🇺 RU' if lang=='ru' else '🇬🇧 EN'}", callback_data="set_toggle_lang")],
        [InlineKeyboardButton(text=loc(lang, "🛒 Фильтр Магазина", "🛒 Shop Notifications"), callback_data="set_shop_filters")],
        [InlineKeyboardButton(text=loc(lang, "🧬 Модификаторы боя (PvE)", "🧬 Battle Modifiers (PvE)"), callback_data="set_modifiers")],
        [InlineKeyboardButton(text=loc(lang, f"🎉 Ивенты: {'🔔 Вкл' if user['notif_events'] else '🔕 Выкл'}", f"🎉 Events: {'🔔 On' if user['notif_events'] else '🔕 Off'}"), callback_data="set_toggle_events")],
        [InlineKeyboardButton(text=loc(lang, f"📜 Квесты: {'🔔 Вкл' if user['notif_quests'] else '🔕 Выкл'}", f"📜 Quests: {'🔔 On' if user['notif_quests'] else '🔕 Off'}"), callback_data="set_toggle_quests")],
        [InlineKeyboardButton(text=loc(lang, f"📢 Анонсы: {'🔔 Вкл' if user['notif_announces'] else '🔕 Выкл'}", f"📢 Announces: {'🔔 On' if user['notif_announces'] else '🔕 Off'}"), callback_data="set_toggle_announces")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "set_modifiers")
async def cb_modifiers_menu(callback: types.CallbackQuery):
    user = await fetch_one("SELECT * FROM users WHERE id=?", (callback.from_user.id,))
    lang = user['lang']
    
    def s(val): return "✅ Вкл" if val else "❌ Выкл"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔴 1.5x ХП Врагов ({s(user.get('mod_enemy_hp'))})", callback_data="set_mod_enemy_hp")],
        [InlineKeyboardButton(text=f"🔴 ИИ бьет 2 раза ({s(user.get('mod_enemy_atk_all'))})", callback_data="set_mod_enemy_atk_all")],
        [InlineKeyboardButton(text=f"🔴 1.2x Статы ИИ ({s(user.get('mod_enemy_stats'))})", callback_data="set_mod_enemy_stats")],
        [InlineKeyboardButton(text=f"🟢 Игрок бьет 2 раза ({s(user.get('mod_player_atk_all'))})", callback_data="set_mod_player_atk_all")],
        [InlineKeyboardButton(text=f"🟢 Ручной выбор атаки ({s(user.get('mod_manual_atk'))})", callback_data="set_mod_manual_atk")],
        [InlineKeyboardButton(text=f"🟢 1.3x ХП Игрока ({s(user.get('mod_player_hp'))})", callback_data="set_mod_player_hp")],
        [InlineKeyboardButton(text=loc(lang, "🔙 Назад", "🔙 Back"), callback_data="set_main")]
    ])
    text = loc(lang,
        "🧬 <b>МОДИФИКАТОРЫ БОЯ (PvE)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВключите модификаторы для усложнения или упрощения боев с ботами.\n\n"
        "🔴 <b>Дебаффы</b> повышают награды (монеты, опыт, кубки).\n🟢 <b>Баффы</b> снижают награды (монеты, опыт), кубки не режутся.",
        "🧬 <b>BATTLE MODIFIERS (PvE)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nToggle modifiers to change AI difficulty.\n\n"
        "🔴 <b>Debuffs</b> increase rewards (coins, xp, trophies).\n🟢 <b>Buffs</b> decrease rewards (coins, xp)."
    )
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("set_mod_"))
async def cb_mod_toggle(callback: types.CallbackQuery):
    mod = callback.data.replace("set_mod_", "")
    uid = callback.from_user.id
    user = await fetch_one("SELECT * FROM users WHERE id=?", (uid,))
    
    new_val = 1 if not user.get(f"mod_{mod}") else 0
    await execute_db(f"UPDATE users SET mod_{mod} = ? WHERE id = ?", (new_val, uid))
    
    await cb_modifiers_menu(callback)

@dp.callback_query(F.data == "set_shop_filters")
async def cb_shop_filters(callback: types.CallbackQuery):
    user = await fetch_one("SELECT * FROM users WHERE id=?", (callback.from_user.id,))
    lang = user['lang']
    
    text = loc(lang, "🛒 <b>ФИЛЬТР УВЕДОМЛЕНИЙ МАГАЗИНА</b>\nВыберите, о каких товарах вас уведомлять:", "🛒 <b>SHOP NOTIFICATION FILTERS</b>\nSelect which items you want to be notified about:")
    
    def b(name_ru, name_en, col):
        st = "🔔" if user.get(col, 1) else "🔕"
        return InlineKeyboardButton(text=loc(lang, f"{name_ru} {st}", f"{name_en} {st}"), callback_data=f"set_shopfilt_{col}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [b("1 Случайная", "1 Random", "notif_1_rnd"), b("3 Случайные", "3 Random", "notif_3_rnd")],
        [b("5 Случайных", "5 Random", "notif_5_rnd"), b("10 Случайных", "10 Random", "notif_10_rnd")],
        [b("25 Случайных", "25 Random", "notif_25_rnd"), b("50 Случайных", "50 Random", "notif_50_rnd")],
        [b("100 Случайных", "100 Random", "notif_100_rnd"), b("Легендарная", "Legendary", "notif_rnd_leg")],
        [b("Мифическая", "Mythic", "notif_rnd_myth"), b("Супер Карта", "Super Card", "notif_rnd_sup")],
        [InlineKeyboardButton(text=loc(lang, "🔙 Назад", "🔙 Back"), callback_data="set_main")]
    ])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("set_shopfilt_"))
async def cb_shopfilt_toggle(callback: types.CallbackQuery):
    col = callback.data.replace("set_shopfilt_", "")
    user_id = callback.from_user.id
    user = await fetch_one("SELECT * FROM users WHERE id=?", (user_id,))
    
    new_val = 0 if user.get(col, 1) == 1 else 1
    await execute_db(f"UPDATE users SET {col} = ? WHERE id = ?", (new_val, user_id))
    
    await cb_shop_filters(callback)

@dp.callback_query(F.data == "set_main")
async def cb_set_main(callback: types.CallbackQuery):
    user = await fetch_one("SELECT * FROM users WHERE id=?", (callback.from_user.id,))
    lang = user['lang']
    text = loc(lang, "⚙️ <b>НАСТРОЙКИ АККАУНТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━", "⚙️ <b>ACCOUNT SETTINGS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🌐 Language: {'🇷🇺 RU' if lang=='ru' else '🇬🇧 EN'}", callback_data="set_toggle_lang")],
        [InlineKeyboardButton(text=loc(lang, "🛒 Фильтр Магазина", "🛒 Shop Notifications"), callback_data="set_shop_filters")],
        [InlineKeyboardButton(text=loc(lang, "🧬 Модификаторы боя (PvE)", "🧬 Battle Modifiers (PvE)"), callback_data="set_modifiers")],
        [InlineKeyboardButton(text=loc(lang, f"🎉 Ивенты: {'🔔 Вкл' if user['notif_events'] else '🔕 Выкл'}", f"🎉 Events: {'🔔 On' if user['notif_events'] else '🔕 Off'}"), callback_data="set_toggle_events")],
        [InlineKeyboardButton(text=loc(lang, f"📜 Квесты: {'🔔 Вкл' if user['notif_quests'] else '🔕 Выкл'}", f"📜 Quests: {'🔔 On' if user['notif_quests'] else '🔕 Off'}"), callback_data="set_toggle_quests")],
        [InlineKeyboardButton(text=loc(lang, f"📢 Анонсы: {'🔔 Вкл' if user['notif_announces'] else '🔕 Выкл'}", f"📢 Announces: {'🔔 On' if user['notif_announces'] else '🔕 Off'}"), callback_data="set_toggle_announces")]
    ])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("set_toggle_"))
async def callback_settings_toggle(callback: types.CallbackQuery):
    setting = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT * FROM users WHERE id=?", (user_id,))
    if not user: return await callback.answer("Error DB", show_alert=True)
    
    if setting == "lang":
        new_val = "en" if user['lang'] == "ru" else "ru"
        await execute_db("UPDATE users SET lang = ? WHERE id = ?", (new_val, user_id))
        user['lang'] = new_val
        
        adm = await is_admin(user_id)
        sgn = await is_signer(user_id)
        msg = loc(new_val, "✅ Язык клавиатуры обновлен!", "✅ Language updated!")
        await callback.message.answer(msg, reply_markup=get_main_keyboard(adm, sgn, new_val))
    else:
        col = f"notif_{setting}"
        new_val = 0 if user[col] == 1 else 1
        await execute_db(f"UPDATE users SET {col} = ? WHERE id = ?", (new_val, user_id))
        user[col] = new_val

    await cb_set_main(callback)

@dp.message(Command("profile"), F.chat.type == "private")
@dp.message(F.text.in_(BTN_PROF))
async def cmd_profile(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    lang = user['lang']
    
    rank = await get_user_rank(user['trophies'])
    total_cards = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE user_id = ?", (user['id'],))
    name = get_display_name(user)
    title_str = await get_user_titles_str(user['id'], lang)
    
    active_bp = await fetch_one("""
        SELECT bp.title, ubp.level, ubp.xp 
        FROM user_bp ubp JOIN battle_passes bp ON ubp.bp_id = bp.id 
        WHERE ubp.user_id = ? AND ubp.is_active = 1
    """, (user['id'],))
    
    bp_text = loc(lang, "<i>Нет активного Батл-пасса</i>", "<i>No active Battle Pass</i>")
    if active_bp:
        lvl_t = loc(lang, "Ур.", "Lvl.")
        bp_text = f"<b>{active_bp['title']}</b> ({lvl_t} {active_bp['level']} | {active_bp['xp']} XP)"

    text = loc(lang,
        f"👤 <b>Профиль игрока {name}</b>{title_str}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖 <b>Ранг:</b> {rank['name']}\n🏆 <b>Кубки:</b> {user['trophies']}\n💰 <b>Шекелей:</b> {user['coins']}\n"
        f"🃏 <b>Всего карт:</b> {total_cards['s'] or 0}\n🎟 <b>Активный БП:</b> {bp_text}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔮 <b>Гарант на Мифик:</b> {make_progress_bar(user['pity_mythic'], 1000, 8)} ({user['pity_mythic']}/1000)\n"
        f"🌠 <b>Гарант на Супер:</b> {make_progress_bar(user['pity_super'], 10000, 8)} ({user['pity_super']}/10000)\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ <b>Экипировка:</b>\n",
        
        f"👤 <b>Player Profile {name}</b>{title_str}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖 <b>Rank:</b> {rank['name']}\n🏆 <b>Trophies:</b> {user['trophies']}\n💰 <b>Shekels:</b> {user['coins']}\n"
        f"🃏 <b>Total Cards:</b> {total_cards['s'] or 0}\n🎟 <b>Active BP:</b> {bp_text}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔮 <b>Mythic Pity:</b> {make_progress_bar(user['pity_mythic'], 1000, 8)} ({user['pity_mythic']}/1000)\n"
        f"🌠 <b>Super Pity:</b> {make_progress_bar(user['pity_super'], 10000, 8)} ({user['pity_super']}/10000)\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ <b>Equipment:</b>\n"
    )
    
    slots = ['equip1', 'equip2', 'equip3', 'equip4']
    for i, slot in enumerate(slots, 1):
        inv_id = user[slot]
        if inv_id != 0:
            row = await fetch_one("""
                SELECT c.id, c.name, c.rarity, c.class_type, c.damage, c.hp, c.booster_dmg_mult, c.booster_hp_mult,
                       i.mutation, i.serial_number, i.signed_by
                FROM inventory i JOIN cards c ON i.card_id = c.id
                WHERE i.id = ? AND i.user_id = ? AND i.count > 0
            """, (inv_id, user['id']))
            
            if row:
                mult = get_mutation_multiplier(row['mutation'])
                mut_str = " 🌈" if row['mutation'] == "Rainbow" else (" ⭐" if row['mutation'] == 'Gold' else "")
                c_dict = dict(row)
                if row['signed_by'] > 0:
                    signer = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (row['signed_by'],))
                    if signer: c_dict['signer_name'] = get_display_name(signer)
                
                n = format_card_name(c_dict)
                if row['class_type'] == 'Booster': 
                    text += loc(lang, f" {i}️⃣ {n}{mut_str}\n      └ <i>Бафф: DMG x{round(row['booster_dmg_mult']*mult, 2)} | HP x{round(row['booster_hp_mult']*mult, 2)}</i>\n",
                                      f" {i}️⃣ {n}{mut_str}\n      └ <i>Buff: DMG x{round(row['booster_dmg_mult']*mult, 2)} | HP x{round(row['booster_hp_mult']*mult, 2)}</i>\n")
                elif row['class_type'] == 'Healer':
                    text += loc(lang, f" {i}️⃣ {n}{mut_str}\n      └ <i>Статы: 💗 Лечение: {int(row['damage']*mult)} | ❤️ Здоровье: {int(row['hp']*mult)}</i>\n",
                                      f" {i}️⃣ {n}{mut_str}\n      └ <i>Stats: 💗 Healing: {int(row['damage']*mult)} | ❤️ Health: {int(row['hp']*mult)}</i>\n")
                else: 
                    text += loc(lang, f" {i}️⃣ {n}{mut_str}\n      └ <i>Статы: ⚔️ Урон: {int(row['damage']*mult)} | ❤️ Здоровье: {int(row['hp']*mult)}</i>\n",
                                      f" {i}️⃣ {n}{mut_str}\n      └ <i>Stats: ⚔️ DMG: {int(row['damage']*mult)} | ❤️ HP: {int(row['hp']*mult)}</i>\n")
            else:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ?", (user['id'],))
                text += loc(lang, f" {i}️⃣ [Слот Пуст]\n", f" {i}️⃣ [Slot Empty]\n")
        else:
            text += loc(lang, f" {i}️⃣ [Слот Пуст]\n", f" {i}️⃣ [Slot Empty]\n")
            
    await message.answer(text)

@dp.message(Command("quests"))
@dp.message(F.text.in_(BTN_QUESTS))
async def cmd_quests(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    lang = user['lang']
    
    now = time.time()
    if user['quests_cooldown'] > now:
        left = int(user['quests_cooldown'] - now)
        m, s = divmod(left, 60)
        return await message.answer(loc(lang, f"⏳ <b>Все квесты выполнены!</b>\nНовые задания появятся через {m} мин. {s} сек.", f"⏳ <b>All quests completed!</b>\nNew tasks in {m}m {s}s."))
    
    c_op = min(10, user['q_cards_opened'])
    b_pl = min(5, user['q_battles'])
    p_pl = min(3, user['q_pvp_played'])
    s_bu = min(1, user['q_shop_buys'])
    h_dn = min(5, user['q_heals_done'])
    
    text = loc(lang,
        "📜 <b>ЕЖЕДНЕВНЫЕ КВЕСТЫ</b>\n"
        "<i>Выполни все задания, чтобы сорвать куш в 1200 💰 Шекелей и получить 1 Сид-Пак!</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ <b>Открыть 10 карточек:</b>\n{make_progress_bar(c_op, 10, 8)} {c_op}/10 {'✅' if c_op>=10 else '❌'}\n\n"
        f"2️⃣ <b>Сыграть 5 PvE боёв:</b>\n{make_progress_bar(b_pl, 5, 8)} {b_pl}/5 {'✅' if b_pl>=5 else '❌'}\n\n"
        f"3️⃣ <b>Сыграть 3 PvP дуэли:</b>\n{make_progress_bar(p_pl, 3, 8)} {p_pl}/3 {'✅' if p_pl>=3 else '❌'}\n\n"
        f"4️⃣ <b>Купить любой товар в Магазине:</b>\n{make_progress_bar(s_bu, 1, 8)} {s_bu}/1 {'✅' if s_bu>=1 else '❌'}\n\n"
        f"5️⃣ <b>Исцелить союзников 5 раз (💗 Healer):</b>\n{make_progress_bar(h_dn, 5, 8)} {h_dn}/5 {'✅' if h_dn>=5 else '❌'}\n",
        
        "📜 <b>DAILY QUESTS</b>\n"
        "<i>Complete all tasks to win 1200 💰 Shekels and 1 Seed-Pack!</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ <b>Open 10 cards:</b>\n{make_progress_bar(c_op, 10, 8)} {c_op}/10 {'✅' if c_op>=10 else '❌'}\n\n"
        f"2️⃣ <b>Play 5 PvE battles:</b>\n{make_progress_bar(b_pl, 5, 8)} {b_pl}/5 {'✅' if b_pl>=5 else '❌'}\n\n"
        f"3️⃣ <b>Play 3 PvP duels:</b>\n{make_progress_bar(p_pl, 3, 8)} {p_pl}/3 {'✅' if p_pl>=3 else '❌'}\n\n"
        f"4️⃣ <b>Buy any item in Shop:</b>\n{make_progress_bar(s_bu, 1, 8)} {s_bu}/1 {'✅' if s_bu>=1 else '❌'}\n\n"
        f"5️⃣ <b>Heal allies 5 times (💗 Healer):</b>\n{make_progress_bar(h_dn, 5, 8)} {h_dn}/5 {'✅' if h_dn>=5 else '❌'}\n"
    )
    await message.answer(text)

@dp.message(Command("top"))
@dp.message(F.text.in_(BTN_TOP))
async def cmd_top(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang'] if user else "ru"
    top_users = await fetch_all("SELECT username, first_name, id, trophies FROM users ORDER BY trophies DESC LIMIT 20")
    
    text = loc(lang, "🏆 <b>МИРОВОЙ РЕЙТИНГ (Топ-20)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n", "🏆 <b>WORLD LEADERBOARD (Top-20)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n")
    for i, u in enumerate(top_users, 1):
        name = get_display_name(u)
        title_str = await get_user_titles_str(u['id'], lang)
        rank = await get_user_rank(u['trophies'])
        med = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
        text += f"{med} <b>{i}. {name}</b>{title_str} — {u['trophies']} 🏆 <i>({rank['name']})</i>\n"
        
    text += loc(lang, "\n🎁 <b>Награды Сезона (сброс каждые 2 дня):</b>\n", "\n🎁 <b>Season Rewards (resets every 2 days):</b>\n")
    brackets = ["1", "2", "3", "4_9", "10_20"]
    b_names = loc(lang, {"1": "🥇 1 место", "2": "🥈 2 место", "3": "🥉 3 место", "4_9": "🏅 4-9 места", "10_20": "🎖 10-20 места"},
                        {"1": "🥇 1st place", "2": "🥈 2nd place", "3": "🥉 3rd place", "4_9": "🏅 4-9 places", "10_20": "🎖 10-20 places"})
    
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
                    c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['card_id'],))
                    mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                    r_strs.append(f"{mut} {c['name'] if c else 'Unknown'}")
            text += f"└ {b_names[b]}: {', '.join(r_strs)}\n"
            
    if not has_rewards:
        text += loc(lang, "<i>Награды пока не настроены.</i>", "<i>Rewards not set yet.</i>")
        
    await message.answer(text)

@dp.message(Command("shop"))
@dp.message(F.text.in_(BTN_SHOP))
async def cmd_shop(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins, lang FROM users WHERE id = ?", (message.from_user.id,))
    lang = user['lang']
    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    
    if not items:
        return await message.answer(loc(lang, "🛒 <b>Магазин пока пуст.</b>\nЗавоз осуществляется каждые полтора часа. Жди уведомления!", "🛒 <b>Shop is empty.</b>\nRestocks every 1.5 hours. Wait for notification!"))
        
    text = loc(lang,
        f"🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН</b>\n💰 Твой баланс: <b>{user['coins']} Шекелей</b>\n<i>(Товары общие для всех. Кто успел, тот и купил!)</i>\n━━━━━━━━━━━━━━━━━━━━━━━━\n",
        f"🛒 <b>GLOBAL SHOP</b>\n💰 Balance: <b>{user['coins']} Shekels</b>\n<i>(Items shared globally. First come, first served!)</i>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    kb = []
    for i, item in enumerate(items, 1):
        name = item['name'] if lang == 'ru' else item['name_en']
        text += loc(lang, f"📦 <b>{name}</b>\n      └ 💵 Цена: <b>{item['price']} 💰</b> | Остаток: <b>{item['stock']} шт.</b>\n\n",
                          f"📦 <b>{name}</b>\n      └ 💵 Price: <b>{item['price']} 💰</b> | Stock: <b>{item['stock']} pcs.</b>\n\n")
        btn_txt = loc(lang, f"Купить: {name} ({item['price']} 💰)", f"Buy: {name} ({item['price']} 💰)")
        kb.append([InlineKeyboardButton(text=btn_txt, callback_data=f"buy_shop_{item['id']}")])
        
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_shop_"))
async def callback_buy_shop(callback: types.CallbackQuery):
    shop_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT coins, pity_mythic, pity_super, lang FROM users WHERE id = ?", (user_id,))
    lang = user['lang']
    item = await fetch_one("SELECT * FROM shop_items WHERE id = ?", (shop_id,))
    
    if not item or item['stock'] <= 0: return await callback.answer(loc(lang, "❌ Этот товар закончился!", "❌ Out of stock!"), show_alert=True)
    if user['coins'] < item['price']: return await callback.answer(loc(lang, "❌ Недостаточно шекелей!", "❌ Not enough shekels!"), show_alert=True)
    
    await execute_db("UPDATE users SET coins = coins - ? WHERE id = ?", (item['price'], user_id))
    await execute_db("UPDATE shop_items SET stock = stock - 1 WHERE id = ?", (shop_id,))
    
    await add_quest_progress(user_id, 'q_shop_buys', 1)
    
    i_type = item['item_type']
    
    if i_type.endswith("_rnd"):
        count = int(i_type.split("_")[0])
        won = await give_multiple_cards(user_id, count)
        
        await add_quest_progress(user_id, 'q_cards_opened', count)
            
        pity_pulls = [c for c in won if c.get('is_pity')]
        
        if count == 1: 
            mut_str = "🌈 " if won[0]['mutation'] == 'Rainbow' else ("⭐ " if won[0]['mutation'] == 'Gold' else "")
            msg = loc(lang, f"✨ <b>Грандиозная покупка!</b>\nВы выбили: {mut_str}{format_card_name(won[0])}", f"✨ <b>Grand Purchase!</b>\nYou got: {mut_str}{format_card_name(won[0])}")
            if won[0].get('is_pity'):
                msg = loc(lang, f"🌟 <b>СИСТЕМА PITY! Гарантированный {won[0]['pity_type']}!</b> 🌟\n\n", f"🌟 <b>PITY SYSTEM! Guaranteed {won[0]['pity_type']}!</b> 🌟\n\n") + msg
        else: 
            msg = loc(lang, f"🛍 <b>Успешно! Вы открыли пак из {count} карт!</b>\nПосмотрите новинки в 🎒 Инвентаре.", f"🛍 <b>Success! You opened {count} cards!</b>\nCheck your 🎒 Inventory.")
            if pity_pulls:
                p_names = ", ".join([f"{c['name']} (Pity {c['pity_type']})" for c in pity_pulls])
                msg += loc(lang, f"\n\n🌟 <b>Сработал PITY! Гарантированные редчайшие карты:</b>\n{p_names}!", f"\n\n🌟 <b>PITY Triggered! Guaranteed rare cards:</b>\n{p_names}!")
                
        await callback.message.answer(msg)
        
    elif i_type.startswith("rnd_"):
        rarity_map = {"rnd_leg": "Legendary", "rnd_myth": "Mythic", "rnd_sup": "Super"}
        target_rarity = rarity_map[i_type]
        
        all_cards = await fetch_all("""
            SELECT * FROM cards 
            WHERE rarity = ?
            AND id NOT IN (SELECT card_id FROM seed_pack_cards)
        """, (target_rarity,))
        if not all_cards:
            await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (item['price'], user_id))
            return await callback.message.answer(loc(lang, "❌ Ошибка БД.", "❌ DB Error."))
            
        won_card = random.choice(all_cards)
        mut = roll_mutation()
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        won_card['serial_number'] = serial
        won_card['signed_by'] = 0
        
        await add_quest_progress(user_id, 'q_cards_opened', 1)
            
        pm = user['pity_mythic']
        ps = user['pity_super']
        if target_rarity == 'Super': ps = 0; pm += 1
        elif target_rarity == 'Mythic': pm = 0; ps += 1
        else: ps += 1; pm += 1
        await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
        
        mut_str = loc(lang, "🌈 Радужная" if mut == 'Rainbow' else ("⭐ Золотая" if mut == 'Gold' else "Обычная"), "🌈 Rainbow" if mut == 'Rainbow' else ("⭐ Gold" if mut == 'Gold' else "Normal"))
        await callback.message.answer(loc(lang, f"✨ <b>Успешная покупка ГАРАНТА!</b>\nВы выбили: {format_card_name(won_card)}\nМутация: <b>{mut_str}</b>", f"✨ <b>Guaranteed purchase success!</b>\nYou got: {format_card_name(won_card)}\nMutation: <b>{mut_str}</b>"))

    await log_user_action(user_id, f"Купил в магазине: {i_type} ({item['price']}💰)")

    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    if not items:
        await callback.message.edit_text(loc(lang, "🛒 <b>Магазин полностью распродан!</b>\nЖдите следующего завоза.", "🛒 <b>Shop is fully sold out!</b>\nWait for next restock."))
    else:
        new_coins = user['coins'] - item['price']
        text = loc(lang, f"🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН</b>\n💰 Твой баланс: <b>{new_coins} Шекелей</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n", f"🛒 <b>GLOBAL SHOP</b>\n💰 Balance: <b>{new_coins} Shekels</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n")
        kb = []
        for i, itm in enumerate(items, 1):
            name = itm['name'] if lang == 'ru' else itm['name_en']
            text += loc(lang, f"📦 <b>{name}</b>\n      └ 💵 Цена: <b>{itm['price']} 💰</b> | Остаток: <b>{itm['stock']} шт.</b>\n\n", f"📦 <b>{name}</b>\n      └ 💵 Price: <b>{itm['price']} 💰</b> | Stock: <b>{itm['stock']} pcs.</b>\n\n")
            kb.append([InlineKeyboardButton(text=loc(lang, f"Купить: {name} ({itm['price']} 💰)", f"Buy: {name} ({itm['price']} 💰)"), callback_data=f"buy_shop_{itm['id']}")])
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
    if not user: return await message.answer("/start")
    lang = user['lang']
    if user['id'] in user_trades: return await message.answer(loc(lang, "❌ Завершите обмен перед выбиванием!", "❌ Finish trade before drawing!"))
    
    luck_mult, cd_mult = await get_active_events()
    base_cooldown = 4 * 60
    actual_cooldown = int(base_cooldown / cd_mult)
    
    now = time.time()
    passed = now - user['last_getcard']
    
    if passed < actual_cooldown:
        left = int(actual_cooldown - passed)
        mins, secs = divmod(left, 60)
        return await message.answer(loc(lang, f"⏳ <b>Колода перемешивается!</b>\nОжидай: <b>{mins} мин. {secs} сек.</b>", f"⏳ <b>Deck shuffling!</b>\nWait: <b>{mins}m {secs}s</b>"))
        
    won_list = await give_multiple_cards(user['id'], 1)
    if not won_list: return await message.answer(loc(lang, "😔 В базе нет карт.", "😔 No cards in DB."))
    won_card = won_list[0]
        
    await execute_db("UPDATE users SET last_getcard = ? WHERE id = ?", (now, user['id']))
    await add_quest_progress(user['id'], 'q_cards_opened', 1)
    await log_user_action(user['id'], f"Выбил карту: {won_card['name']} (ID:{won_card['id']}, Мутация: {won_card['mutation']})")
    
    n_fmt = format_card_name(won_card)
    rarity_text = format_rarity_display(won_card['rarity'])
    
    mutation = won_card['mutation']
    mult = get_mutation_multiplier(mutation)
    mut_str = ""
    if mutation == "Gold": mut_str = loc(lang, "⭐ <b>ЗОЛОТАЯ МУТАЦИЯ! (+10% Статов)</b>\n", "⭐ <b>GOLD MUTATION! (+10% Stats)</b>\n")
    elif mutation == "Rainbow": mut_str = loc(lang, "🌈 <b>РАДУЖНАЯ МУТАЦИЯ! (+20% Статов)</b>\n", "🌈 <b>RAINBOW MUTATION! (+20% Stats)</b>\n")
    
    msg = ""
    if won_card.get('is_pity'):
        msg += loc(lang, f"🌟 <b>СИСТЕМА PITY! ГАРАНТИРОВАННЫЙ {won_card['pity_type']}!</b> 🌟\n\n", f"🌟 <b>PITY SYSTEM! GUARANTEED {won_card['pity_type']}!</b> 🌟\n\n")
        
    msg += loc(lang, f"🎉 <b>ВЫ ВЫБИЛИ КАРТУ!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n{mut_str}🃏 {n_fmt}\n💎 <b>Редкость:</b> {rarity_text}\n", f"🎉 <b>YOU DREW A CARD!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n{mut_str}🃏 {n_fmt}\n💎 <b>Rarity:</b> {rarity_text}\n")
    
    if won_card['class_type'] == 'Booster': 
        msg += loc(lang, f"✨ <b>БУСТЕР</b>\n   └ Бафф DMG: <b>x{round(won_card['booster_dmg_mult']*mult, 2)}</b> | HP: <b>x{round(won_card['booster_hp_mult']*mult, 2)}</b>\n", f"✨ <b>BOOSTER</b>\n   └ Buff DMG Mult: <b>x{round(won_card['booster_dmg_mult']*mult, 2)}</b> | HP Mult: <b>x{round(won_card['booster_hp_mult']*mult, 2)}</b>\n")
    elif won_card['class_type'] == 'Healer':
        msg += loc(lang, f"💗 <b>Лечение:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n", f"💗 <b>Healing:</b> {int(won_card['damage']*mult)} | ❤️ <b>Health:</b> {int(won_card['hp']*mult)}\n")
    else: 
        msg += loc(lang, f"⚔️ <b>Урон:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n", f"⚔️ <b>DMG:</b> {int(won_card['damage']*mult)} | ❤️ <b>HP:</b> {int(won_card['hp']*mult)}\n")
        
    if luck_mult > 1.0 and won_card['drop_chance'] < 15.0:
        msg += loc(lang, f"\n🍀 <i>Сработал ивент удачи!</i>", f"\n🍀 <i>Luck event triggered!</i>")
        
    await message.answer_photo(photo=won_card['photo_id'], caption=msg)

# ========================================================================
# ИНДЕКС
# ========================================================================
async def get_index_text(user_id: int, page: int = 0, items_per_page: int = 8):
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (user_id,))
    lang = user['lang'] if user else 'ru'
    all_cards = await fetch_all("SELECT * FROM cards")
    user_inv = await fetch_all("SELECT DISTINCT card_id FROM inventory WHERE user_id = ?", (user_id,))
    user_card_ids = [item['card_id'] for item in user_inv]
    
    if not all_cards: return loc(lang, "Индекс пуст.", "Index empty."), None
    
    luck_mult, _ = await get_active_events()
    weights_dict, total_w = await calculate_chance_weights(luck_mult)
    
    pack_cards = await fetch_all("""
        SELECT spc.card_id, spc.drop_chance as pack_chance, sp.title
        FROM seed_pack_cards spc JOIN seed_packs sp ON spc.pack_id = sp.id
    """)
    pack_info = {pc['card_id']: pc for pc in pack_cards}
    pack_totals = {}
    for pc in pack_cards:
        w = pc['pack_chance']
        if w < 15.0: w *= luck_mult
        pack_totals[pc['title']] = pack_totals.get(pc['title'], 0) + w
    
    def index_sort_key(c):
        if c['rarity'] == 'Leaderboard': return (999, c['id'])
        rw = RARITY_WEIGHT.get(c['rarity'], 0)
        return (rw, c['id'])
        
    all_cards.sort(key=index_sort_key, reverse=True)
    total_pages = max(1, math.ceil(len(all_cards) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    
    text = loc(lang, f"📖 <b>МИРОВОЙ ИНДЕКС КАРТ (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n", f"📖 <b>WORLD CARD INDEX (Page {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n")
    if luck_mult > 1.0: text += loc(lang, f"🍀 <b>ИВЕНТ УДАЧИ АКТИВЕН (x{luck_mult})! Шансы пересчитаны!</b>\n\n", f"🍀 <b>LUCK EVENT ACTIVE (x{luck_mult})! Chances recalculated!</b>\n\n")
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = all_cards[start_idx:end_idx]
    
    for i, c in enumerate(page_items, start_idx + 1):
        inv_stats = await fetch_all("SELECT mutation, SUM(count) as c FROM inventory WHERE card_id = ? AND user_id != ? GROUP BY mutation", (c['id'], SUPER_ADMIN_ID))
        total_exists = sum(item['c'] for item in inv_stats if item['c'])
        
        mut_texts = []
        for st in inv_stats:
            if st['mutation'] == 'Gold' and st['c'] > 0: mut_texts.append(loc(lang, f"⭐ Золотых: {st['c']}", f"⭐ Gold: {st['c']}"))
            if st['mutation'] == 'Rainbow' and st['c'] > 0: mut_texts.append(loc(lang, f"🌈 Радужных: {st['c']}", f"🌈 Rainbow: {st['c']}"))
            
        mut_str = loc(lang, f"\n      └ <i>Из них: {', '.join(mut_texts)}</i>" if mut_texts else "", f"\n      └ <i>Of them: {', '.join(mut_texts)}</i>" if mut_texts else "")
        
        n_fmt = format_card_name(c).replace(" <b>[#-001]</b>", "")
        r_fmt = format_rarity_display(c['rarity'])
        
        if c['id'] in pack_info:
            p_info = pack_info[c['id']]
            p_title = p_info['title']
            p_weight = p_info['pack_chance']
            if p_weight < 15.0: p_weight *= luck_mult
            p_total = pack_totals.get(p_title, 1)
            real_chance = (p_weight / p_total) * 100 if p_total > 0 else 0
            chance_str = loc(lang, f"Шанс: {real_chance:.4f}% <b>(Пак «{p_title}»)</b>", f"Chance: {real_chance:.4f}% <b>(Pack '{p_title}')</b>")
        elif c['rarity'] == 'Leaderboard':
            chance_str = loc(lang, "Только за Топ!", "Leaderboard only!")
        else:
            real_chance = (weights_dict.get(c['id'], 0) / total_w) * 100 if total_w > 0 else 0
            chance_str = loc(lang, f"Шанс из Гачи: {real_chance:.4f}%", f"Gacha Chance: {real_chance:.4f}%")
        
        if c['id'] in user_card_ids:
            text += f"{i}. {n_fmt}\n      └ 💎 {r_fmt} ({chance_str})\n"
            if c['class_type'] == 'Booster': 
                text += loc(lang, f"      └ ✨ Бафф: DMG x{c['booster_dmg_mult']} // HP x{c['booster_hp_mult']}\n", f"      └ ✨ Buff: DMG x{c['booster_dmg_mult']} // HP x{c['booster_hp_mult']}\n")
            elif c['class_type'] == 'Healer': 
                text += loc(lang, f"      └ 💗 Лечение: {c['damage']} // ❤️ Здоровье: {c['hp']}\n", f"      └ 💗 Healing: {c['damage']} // ❤️ Health: {c['hp']}\n")
            else: 
                text += loc(lang, f"      └ ⚔️ Урон: {c['damage']} // ❤️ Здоровье: {c['hp']}\n", f"      └ ⚔️ DMG: {c['damage']} // ❤️ HP: {c['hp']}\n")
            text += loc(lang, f"      └ 🌍 Существует: {total_exists} шт.{mut_str}\n\n", f"      └ 🌍 Exists: {total_exists} pcs.{mut_str}\n\n")
        else:
            text += loc(lang, f"{i}. <b>???</b> (Не открыто)\n      └ 💎 {r_fmt} ({chance_str})\n      └ 🌍 Существует: {total_exists} шт.{mut_str}\n\n", f"{i}. <b>???</b> (Undiscovered)\n      └ 💎 {r_fmt} ({chance_str})\n      └ 🌍 Exists: {total_exists} pcs.{mut_str}\n\n")
            
    kb = []
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"idx_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"idx_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("index"))
@dp.message(F.text.in_(BTN_IDX))
async def cmd_index(message: types.Message):
    if await check_ban(message.from_user.id): return
    text, kb = await get_index_text(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)
    
@dp.callback_query(F.data.startswith("idx_page_"))
async def callback_index_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[2])
    text, kb = await get_index_text(callback.from_user.id, page)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# ========================================================================
# ИНВЕНТАРЬ
# ========================================================================
async def get_inventory_text_and_kb(user_id: int, page: int = 0, items_per_page: int = 30):
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (user_id,))
    lang = user['lang'] if user else 'ru'
    
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name
        FROM inventory i JOIN cards c ON i.card_id = c.id LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.count > 0
    """, (user_id,))
    
    toggle_row = [
        InlineKeyboardButton(text=loc(lang, "🎒 Карты (Выбрано)", "🎒 Cards (Selected)"), callback_data="ignore"),
        InlineKeyboardButton(text=loc(lang, "📦 Сид-Паки", "📦 Seed-Packs"), callback_data="inv_packs_menu")
    ]
    
    if not inv: 
        return loc(lang, "🎒 Ваш инвентарь пуст. Используйте /getcard", "🎒 Your inventory is empty. Use /getcard"), InlineKeyboardMarkup(inline_keyboard=[toggle_row])
        
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
    
    text = loc(lang, f"🎒 <b>ИНВЕНТАРЬ КАРТ (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n", f"🎒 <b>CARD INVENTORY (Page {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n")
    for item in page_items:
        n_fmt = format_card_name(item).replace(" <b>[#-001]</b>", "")
        mut_emoji = ""
        if item['mutation'] == "Gold": mut_emoji = "⭐ "
        elif item['mutation'] == "Rainbow": mut_emoji = "🌈 "
        text += loc(lang, f"• {mut_emoji}{n_fmt} — <b>{item['count']} шт.</b>\n", f"• {mut_emoji}{n_fmt} — <b>{item['count']} pcs.</b>\n")
        
    kb = [toggle_row]
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"inv_page_{page+1}"))
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

@dp.message(F.text.in_(BTN_SIGN))
async def cmd_sign_card(message: types.Message):
    if await check_ban(message.from_user.id): return
    if not await is_signer(message.from_user.id): return
    if message.from_user.id in user_trades: return await message.answer("❌ Завершите обмен перед подписыванием карт!")
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang'] if user else 'ru'
    
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0 AND i.signed_by = 0
    """, (message.from_user.id,))
    
    if not inv: return await message.answer(loc(lang, "❌ Нет карт для подписи.", "❌ No cards available to sign."))
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = []
    for c in inv:
        mut_emoji = "⭐ " if c['mutation'] == 'Gold' else "🌈 " if c['mutation'] == 'Rainbow' else ""
        items.append({"id": c['inv_id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {mut_emoji}{c['name']} x{c['count']}"})
        
    kb = get_pagination_keyboard(items, 0, "sgn_c", columns=1, items_per_page=8)
    await message.answer(loc(lang, "✍️ <b>ВЫБОР КАРТЫ ДЛЯ ПОДПИСИ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите карту:", "✍️ <b>SELECT CARD TO SIGN</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nChoose a card:"), reply_markup=kb)

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
    
    if not await is_signer(user_id): return await callback.answer("No perms!", show_alert=True)
    
    db = await get_db_connection()
    try:
        cur = await db.execute("SELECT card_id, count, mutation, serial_number, signed_by FROM inventory WHERE id = ? AND user_id = ?", (inv_id, user_id))
        row = await cur.fetchone()
        if not row or row['count'] < 1: return await callback.answer("Not found!", show_alert=True)
        if row['signed_by'] != 0: return await callback.answer("Already signed!", show_alert=True)
        
        await db.execute("BEGIN")
        if row['count'] == 1:
            await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
            await db.execute("UPDATE users SET equip1 = 0 WHERE equip1 = ?", (inv_id,))
            await db.execute("UPDATE users SET equip2 = 0 WHERE equip2 = ?", (inv_id,))
            await db.execute("UPDATE users SET equip3 = 0 WHERE equip3 = ?", (inv_id,))
            await db.execute("UPDATE users SET equip4 = 0 WHERE equip4 = ?", (inv_id,))
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
        return await callback.answer("Error.", show_alert=True)
    finally:
        await db.close()
        
    await callback.message.delete()
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (user_id,))
    lang = user['lang'] if user else 'ru'
    await callback.message.answer(loc(lang, "✍️✅ <b>Успешно подписано!</b>", "✍️✅ <b>Successfully signed!</b>"))
    await callback.answer()

# ========================================================================
# ЭКИПИРОВКА (4 СЛОТА)
# ========================================================================
def get_equip_main_keyboard(user_info, cards_info, lang="ru"):
    kb = []
    for i, slot in enumerate(['equip1', 'equip2', 'equip3', 'equip4'], 1):
        inv_id = user_info[slot]
        sl_t = loc(lang, "Слот", "Slot")
        emp = loc(lang, "Пусто", "Empty")
        text = f"{sl_t} {i} [{emp}]" if inv_id == 0 else f"{sl_t} {i}: {cards_info.get(inv_id, f'ID: {inv_id}')}"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"eq_select_{i}")])
    kb.append([InlineKeyboardButton(text=loc(lang, "❌ Очистить колоду", "❌ Clear deck"), callback_data="eq_clear")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("equip"))
@dp.message(F.text.in_(BTN_EQ))
async def cmd_equip(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    lang = user['lang']
    if message.from_user.id in user_trades: return await message.answer(loc(lang, "❌ Завершите обмен перед экипировкой!", "❌ Finish trade first!"))
    
    inv_ids = [c for c in [user['equip1'], user['equip2'], user['equip3'], user['equip4']] if c != 0]
    
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
            
    await message.answer(loc(lang, "🛡 <b>БОЕВАЯ КОЛОДА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите слот:", "🛡 <b>BATTLE DECK</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nChoose a slot:"), reply_markup=get_equip_main_keyboard(user, cards_info, lang))

@dp.callback_query(F.data == "eq_clear")
async def cb_eq_clear(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (user_id,))
    lang = user['lang'] if user else 'ru'
    
    await execute_db("UPDATE users SET equip1 = 0, equip2 = 0, equip3 = 0, equip4 = 0 WHERE id = ?", (user_id,))
    await callback.message.edit_text(loc(lang, "✅ Боевая колода успешно очищена!", "✅ Battle deck successfully cleared!"))
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_select_"))
async def equip_slot_callback(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (callback.from_user.id,))
    lang = user['lang'] if user else 'ru'
    
    inv = await fetch_all("""
        SELECT DISTINCT c.id, c.name, c.rarity, c.class_type
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0
    """, (callback.from_user.id,))
    
    if not inv: return await callback.answer(loc(lang, "Нет карт!", "No cards!"), show_alert=True)
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']}"} for c in inv]
    
    await state.update_data(equip_slot=slot_num, equip_items_cards=items)
    kb = get_pagination_keyboard(items, 0, "eq_c", columns=1, items_per_page=8)
    
    await callback.message.edit_text(loc(lang, f"👇 Выберите карту для <b>Слота {slot_num}</b>:", f"👇 Select card for <b>Slot {slot_num}</b>:"), reply_markup=kb)
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
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (callback.from_user.id,))
    lang = user['lang'] if user else 'ru'
    
    invs = await fetch_all("""
        SELECT i.id as inv_id, c.name, c.rarity, c.class_type, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name, i.count
        FROM inventory i 
        JOIN cards c ON i.card_id = c.id 
        LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.card_id = ? AND i.count > 0
    """, (callback.from_user.id, card_id))
    
    if not invs: return await callback.answer(loc(lang, "Карта пропала!", "Card missing!"), show_alert=True)
    
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
    kb.inline_keyboard.append([InlineKeyboardButton(text=loc(lang, "🔙 Назад", "🔙 Back"), callback_data=f"eq_select_{slot_num}")])
    
    await callback.message.edit_text(loc(lang, f"👇 Выберите конкретную копию для <b>Слота {slot_num}</b>:", f"👇 Select exact copy for <b>Slot {slot_num}</b>:"), reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_v_page_"))
async def equip_var_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (callback.from_user.id,))
    lang = user['lang'] if user else 'ru'
    kb = get_pagination_keyboard(data.get('equip_items_vars', []), page, "eq_v", columns=1, items_per_page=6)
    slot_num = data.get('equip_slot', 1)
    kb.inline_keyboard.append([InlineKeyboardButton(text=loc(lang, "🔙 Назад", "🔙 Back"), callback_data=f"eq_select_{slot_num}")])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_v_"))
async def equip_var_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    slot_num = data.get('equip_slot', 1)
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4, lang FROM users WHERE id = ?", (callback.from_user.id,))
    lang = user['lang']
    
    if inv_id in [user['equip1'], user['equip2'], user['equip3'], user['equip4']]:
        return await callback.answer(loc(lang, "❌ Эта копия уже экипирована!", "❌ Copy already equipped!"), show_alert=True)
        
    card_info = await fetch_one("SELECT card_id FROM inventory WHERE id = ?", (inv_id,))
    if not card_info: return await callback.answer("Error")
    
    equipped_invs = [user['equip1'], user['equip2'], user['equip3'], user['equip4']]
    equipped_invs.remove(user[f'equip{slot_num}'])
    
    if any(i != 0 for i in equipped_invs):
        inv_list = ",".join(map(str, [i for i in equipped_invs if i != 0]))
        other_cards = await fetch_all(f"SELECT card_id FROM inventory WHERE id IN ({inv_list})")
        if any(c['card_id'] == card_info['card_id'] for c in other_cards):
            return await callback.answer(loc(lang, "❌ Нельзя надеть две одинаковые карты!", "❌ Cannot equip identical cards!"), show_alert=True)

    await execute_db(f"UPDATE users SET equip{slot_num} = ? WHERE id = ?", (inv_id, callback.from_user.id))
    await callback.message.edit_text(loc(lang, f"✅ Установлено в Слот {slot_num}!", f"✅ Equipped in Slot {slot_num}!"))
    await state.clear()
    await callback.answer()

# ========================================================================
# БАТЛ-ПАСС (МЕНЮ ИГРОКА)
# ========================================================================
@dp.message(F.text.in_(BTN_BP))
async def cmd_battle_passes(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang'] if user else 'ru'
    passes = await fetch_all("SELECT * FROM battle_passes ORDER BY id DESC")
    
    if not passes:
        return await message.answer(loc(lang, "🎟 <b>Батл-пассы</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nНет доступных сезонов.", "🎟 <b>Battle Passes</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nNo available seasons."))
        
    kb = []
    for bp in passes:
        kb.append([InlineKeyboardButton(text=f"🎫 {bp['title']}", callback_data=f"bp_view_{bp['id']}")])
        
    await message.answer(loc(lang, "🎟 <b>БАТЛ-ПАССЫ</b>\nВыберите сезон:", "🎟 <b>BATTLE PASSES</b>\nChoose a season:"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("bp_view_"))
async def callback_bp_view(callback: types.CallbackQuery):
    bp_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (user_id,))
    lang = user['lang'] if user else 'ru'
    
    bp = await fetch_one("SELECT * FROM battle_passes WHERE id = ?", (bp_id,))
    if not bp: return await callback.answer("Not found!", show_alert=True)
    
    user_bp = await fetch_one("SELECT * FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    if not user_bp:
        await execute_db("INSERT INTO user_bp (user_id, bp_id, xp, level, is_active) VALUES (?, ?, 0, 0, 0)", (user_id, bp_id))
        user_bp = await fetch_one("SELECT * FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
        
    is_active = bool(user_bp['is_active'])
    status_str = loc(lang, "🟢 <b>АКТИВЕН</b>", "🟢 <b>ACTIVE</b>") if is_active else loc(lang, "🔴 <b>НЕАКТИВЕН</b>", "🔴 <b>INACTIVE</b>")
    
    curr_lvl = user_bp['level']
    curr_xp = user_bp['xp']
    
    next_lvl_data = await fetch_one("SELECT xp_required FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, curr_lvl + 1))
    req_xp = next_lvl_data['xp_required'] if next_lvl_data else 0
    
    if next_lvl_data:
        progress_str = f"{make_progress_bar(curr_xp, req_xp, 12)} ({curr_xp}/{req_xp})"
    else:
        progress_str = loc(lang, "🏆 <b>ПОЛНОСТЬЮ ПРОЙДЕН!</b>", "🏆 <b>FULLY COMPLETED!</b>")

    text = loc(lang,
        f"🏆 <b>СЕЗОН: {bp['title']}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n📊 Статус: {status_str}\n🎖 Уровень: <b>{curr_lvl}</b>\n✨ Опыт: {progress_str}\n",
        f"🏆 <b>SEASON: {bp['title']}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n📊 Status: {status_str}\n🎖 Level: <b>{curr_lvl}</b>\n✨ XP: {progress_str}\n"
    )
    
    kb = []
    if not is_active:
        kb.append([InlineKeyboardButton(text=loc(lang, "✅ Сделать активным", "✅ Set Active"), callback_data=f"bp_set_act_{bp_id}")])
    kb.append([InlineKeyboardButton(text=loc(lang, "▶️ Уровни и награды", "▶️ Levels & Rewards"), callback_data=f"bp_lvl_{bp_id}_1")])
    kb.append([InlineKeyboardButton(text=loc(lang, "🔙 Назад", "🔙 Back"), callback_data="bp_list")])
    
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
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (callback.from_user.id,))
    lang = user['lang'] if user else 'ru'
    passes = await fetch_all("SELECT * FROM battle_passes ORDER BY id DESC")
    kb = []
    for bp in passes:
        kb.append([InlineKeyboardButton(text=f"🎫 {bp['title']}", callback_data=f"bp_view_{bp['id']}")])
    try: await callback.message.edit_text(loc(lang, "🎟 <b>БАТЛ-ПАССЫ</b>", "🎟 <b>BATTLE PASSES</b>"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except:
        await callback.message.answer(loc(lang, "🎟 <b>БАТЛ-ПАССЫ</b>", "🎟 <b>BATTLE PASSES</b>"), reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("bp_set_act_"))
async def callback_bp_set_active(callback: types.CallbackQuery):
    bp_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    await execute_db("UPDATE user_bp SET is_active = 0 WHERE user_id = ?", (user_id,))
    await execute_db("UPDATE user_bp SET is_active = 1 WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    await callback.answer()
    await callback_bp_view(callback)

@dp.callback_query(F.data.startswith("bp_lvl_"))
async def callback_bp_level(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    bp_id = int(parts[2])
    req_level = int(parts[3])
    user_id = callback.from_user.id
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (user_id,))
    lang = user['lang'] if user else 'ru'
    
    bp = await fetch_one("SELECT * FROM battle_passes WHERE id = ?", (bp_id,))
    user_bp = await fetch_one("SELECT level FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    user_curr_lvl = user_bp['level'] if user_bp else 0
    
    lvl_data = await fetch_one("SELECT id, xp_required FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, req_level))
    if not lvl_data: return await callback.answer("Level not found", show_alert=True)
        
    rewards = await fetch_all("SELECT * FROM bp_rewards WHERE level_id = ?", (lvl_data['id'],))
    
    text = loc(lang,
        f"🏆 <b>{bp['title']} | Уровень {req_level}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Требуется XP: {lvl_data['xp_required']}</i>\n\n🎁 <b>Награды:</b>\n",
        f"🏆 <b>{bp['title']} | Level {req_level}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Required XP: {lvl_data['xp_required']}</i>\n\n🎁 <b>Rewards:</b>\n"
    )
    
    if not rewards:
        text += loc(lang, "└ <i>Наград нет.</i>\n", "└ <i>No rewards.</i>\n")
    else:
        for r in rewards:
            if r['reward_type'] == 'shekels':
                text += loc(lang, f"└ 💰 <b>{r['amount']} Шекелей</b>\n", f"└ 💰 <b>{r['amount']} Shekels</b>\n")
            elif r['reward_type'] == 'card':
                c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['card_id'],))
                n = c['name'] if c else "Unknown"
                mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                text += f"└ 🃏 <b>{mut} {n}</b>\n"
                
    text += loc(lang, "\n📊 <b>Статус:</b> ", "\n📊 <b>Status:</b> ")
    is_reached = user_curr_lvl >= req_level
    claim_check = await fetch_one("SELECT * FROM user_bp_claims WHERE user_id = ? AND bp_id = ? AND level = ?", (user_id, bp_id, req_level))
    is_claimed = bool(claim_check)
    
    if is_claimed: text += loc(lang, "✅ <i>Уже получено</i>", "✅ <i>Claimed</i>")
    elif is_reached: text += loc(lang, "🎁 <b>ДОСТУПНО!</b>", "🎁 <b>AVAILABLE!</b>")
    else: text += loc(lang, "🔒 <i>Не достигнут</i>", "🔒 <i>Locked</i>")
    
    kb = []
    if is_reached and not is_claimed and rewards:
        kb.append([InlineKeyboardButton(text=loc(lang, "🎁 ЗАБРАТЬ", "🎁 CLAIM"), callback_data=f"bp_claim_{bp_id}_{req_level}")])
        
    nav_row = []
    max_lvl = await fetch_one("SELECT MAX(level) as m FROM bp_levels WHERE bp_id = ?", (bp_id,))
    max_l = max_lvl['m'] if max_lvl and max_lvl['m'] else 1
    
    if req_level > 1: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"bp_lvl_{bp_id}_{req_level-1}"))
    if req_level < max_l: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"bp_lvl_{bp_id}_{req_level+1}"))
    if nav_row: kb.append(nav_row)
    kb.append([InlineKeyboardButton(text=loc(lang, "🔙 Назад", "🔙 Back"), callback_data=f"bp_view_{bp_id}")])
    
    try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except:
        await callback.message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("bp_claim_"))
async def callback_bp_claim_fixed(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    bp_id = int(parts[2])
    req_level = int(parts[3])
    user_id = callback.from_user.id
    
    user_bp = await fetch_one("SELECT level FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    if not user_bp or user_bp['level'] < req_level: return await callback.answer("Locked", show_alert=True)
        
    claim_check = await fetch_one("SELECT * FROM user_bp_claims WHERE user_id = ? AND bp_id = ? AND level = ?", (user_id, bp_id, req_level))
    if claim_check: return await callback.answer("Already claimed", show_alert=True)
        
    lvl_data = await fetch_one("SELECT id FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, req_level))
    rewards = await fetch_all("SELECT * FROM bp_rewards WHERE level_id = ?", (lvl_data['id'],))
    
    db = await get_db_connection()
    try:
        for r in rewards:
            if r['reward_type'] == 'shekels':
                await db.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (r['amount'], user_id))
            elif r['reward_type'] == 'card':
                res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0 AND signed_by = 0", (user_id, r['card_id'], r['mutation']))
                inv_item = await res.fetchone()
                if inv_item:
                    await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                else:
                    await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, 0, 0)", (user_id, r['card_id'], r['mutation']))
        
        await db.execute("INSERT INTO user_bp_claims (user_id, bp_id, level) VALUES (?, ?, ?)", (user_id, bp_id, req_level))
        await db.commit()
    finally:
        await db.close()
        
    await callback.answer("🎉 Reward claimed!", show_alert=True)
    await callback_bp_level(callback)

# ========================================================================
# БОЕВОЙ ДВИЖОК, БАЛАНС И ОПЫТ БП
# ========================================================================
async def get_team_data(user_id: int):
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4 FROM users WHERE id = ?", (user_id,))
    team = []
    slots = ['equip1', 'equip2', 'equip3', 'equip4']
    for slot in slots:
        inv_id = user[slot]
        if inv_id != 0:
            row = await fetch_one("""
                SELECT c.id, c.name, c.rarity, c.class_type, c.damage, c.hp, c.booster_dmg_mult, c.booster_hp_mult,
                       i.mutation, i.serial_number, i.signed_by
                FROM inventory i JOIN cards c ON i.card_id = c.id
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
                card['heal_power_mult'] = 1.0
                team.append(card)
            else:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ?", (user_id,))
    return team

async def get_bot_team(user_id: int, difficulty_mult: float, rank_name: str, diff_type: str = "med"):
    all_cards = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards")
    if len(all_cards) < 4: return []
    
    by_rarity = {}
    for c in all_cards:
        by_rarity.setdefault(c['rarity'], []).append(c)
        
    base_rank = rank_name.split()[0]
    team_selection = []
    
    for _ in range(4):
        r = random.random()
        pool = []
        if diff_type == "nightmare":
            if base_rank == "Bronze": pool = by_rarity.get('Uncommon', []) + by_rarity.get('Rare', []) + (by_rarity.get('Epic', []) if r < 0.2 else [])
            elif base_rank == "Silver": pool = by_rarity.get('Rare', []) + by_rarity.get('Epic', []) + (by_rarity.get('Legendary', []) if r < 0.2 else [])
            elif base_rank == "Gold": pool = by_rarity.get('Epic', []) + by_rarity.get('Legendary', []) + (by_rarity.get('Mythic', []) if r < 0.2 else [])
            elif base_rank == "Platina": pool = by_rarity.get('Legendary', []) + by_rarity.get('Mythic', []) + (by_rarity.get('Super', []) + by_rarity.get('Leaderboard', []) if r < 0.3 else [])
            elif base_rank == "Diamond": pool = by_rarity.get('Mythic', []) + by_rarity.get('Super', []) + by_rarity.get('Leaderboard', [])
            elif base_rank == "Ruby": pool = by_rarity.get('Super', []) + by_rarity.get('Leaderboard', []) + (by_rarity.get('Mythic', []) if r < 0.1 else [])
        else:
            if base_rank == "Bronze":
                pool = by_rarity.get('Basic', []) + by_rarity.get('Uncommon', [])
            elif base_rank == "Silver":
                pool = by_rarity.get('Uncommon', []) + by_rarity.get('Rare', [])
            elif base_rank == "Gold":
                pool = by_rarity.get('Rare', []) + (by_rarity.get('Epic', []) if r < 0.3 else [])
            elif base_rank == "Platina":
                pool = by_rarity.get('Rare', []) + by_rarity.get('Epic', []) + (by_rarity.get('Legendary', []) if r < 0.1 else [])
            elif base_rank == "Diamond":
                pool = by_rarity.get('Epic', []) + by_rarity.get('Legendary', []) + (by_rarity.get('Mythic', []) if r < 0.05 else [])
            elif base_rank == "Ruby":
                pool = by_rarity.get('Legendary', []) + (by_rarity.get('Mythic', []) if r < 0.2 else []) + (by_rarity.get('Super', []) if r < 0.02 else [])
        
        if not pool:
            pool = [c for c in all_cards if c['rarity'] != 'Leaderboard']
            if not pool: pool = all_cards
            
        weighted_pool = []
        for c in pool:
            weight = 1 if c['class_type'] == 'Healer' else 4
            weighted_pool.extend([c] * weight)
            
        team_selection.append(random.choice(weighted_pool))
        
    team_copies = []
    for c in team_selection:
        c_copy = dict(c)
        c_copy['max_hp'] = c_copy['hp']
        mut_chance = random.random()
        if difficulty_mult >= 1.0 or diff_type == "nightmare": 
            rainbow_prob = min(0.02, 0.01 * difficulty_mult) 
            gold_prob = min(0.12, 0.05 * difficulty_mult)     
            if mut_chance < rainbow_prob: 
                c_copy['mutation'] = "Rainbow"
                c_copy['damage'] = int(c_copy['damage'] * 1.2)
                c_copy['hp'] = int(c_copy['hp'] * 1.2)
            elif mut_chance < rainbow_prob + gold_prob: 
                c_copy['mutation'] = "Gold"
                c_copy['damage'] = int(c_copy['damage'] * 1.1)
                c_copy['hp'] = int(c_copy['hp'] * 1.1)
            else: c_copy['mutation'] = "Normal"
        else: c_copy['mutation'] = "Normal"
            
        c_copy['max_hp'] = c_copy['hp']
        c_copy['burn'] = 0
        c_copy['dmg_buff'] = 0
        c_copy['serial_number'] = 0
        c_copy['signed_by'] = 0
        c_copy['heal_power_mult'] = 1.0  
        team_copies.append(c_copy)
        
    return team_copies

def format_combat_team_vertical(team, lang="ru"):
    if not team: return loc(lang, "<i>Все мертвы</i>", "<i>All dead</i>")
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
        if c['class_type'] == 'Healer': status += "💗"
        
        s_str = f" [#{c['serial_number']:04d}]" if c.get('serial_number', 0) > 0 else ""
        sgn_str = ""
        if c.get('signed_by', 0) > 0:
            s_name = c.get('signer_name') or f"ID:{c['signed_by']}"
            sgn_str = f" ✍️ Sign: {s_name}"
            
        if c['class_type'] == 'Healer':
            heal_val = int((c['damage'] + c.get('dmg_buff', 0)) * c.get('heal_power_mult', 1.0))
            res.append(f"• {c['name']}{s_str}{sgn_str}{status} (💗{heal_val} | ❤️{c['hp']}/{c['max_hp']})")
        else:
            dmg = c['damage'] + c.get('dmg_buff', 0)
            res.append(f"• {c['name']}{s_str}{sgn_str}{status} (⚔️{dmg} | ❤️{c['hp']}/{c['max_hp']})")
    return "\n".join(res)

def build_battle_header(p1_name, t1, p2_name, t2, lang="ru"):
    return loc(lang,
        f"⚔️ <b>АРЕНА: БИТВА</b> ⚔️\n━━━━━━━━━━━━━━━━━━━━━━━━\n🔵 <b>Команда {p1_name}:</b>\n{format_combat_team_vertical(t1, lang)}\n\n🔴 <b>Команда {p2_name}:</b>\n{format_combat_team_vertical(t2, lang)}\n━━━━━━━━━━━━━━━━━━━━━━━━\n📜 <b>Лог боя:</b>\n",
        f"⚔️ <b>BATTLE ARENA</b> ⚔️\n━━━━━━━━━━━━━━━━━━━━━━━━\n🔵 <b>Team {p1_name}:</b>\n{format_combat_team_vertical(t1, lang)}\n\n🔴 <b>Team {p2_name}:</b>\n{format_combat_team_vertical(t2, lang)}\n━━━━━━━━━━━━━━━━━━━━━━━━\n📜 <b>Combat Log:</b>\n"
    )

def add_dual_log(log1, log2, lang1, lang2, text_ru, text_en):
    if log1 is not None: log1.append(text_ru if lang1 == 'ru' else text_en)
    if log2 is not None: log2.append(text_ru if lang2 == 'ru' else text_en)

def apply_boosters(team, team_name, log1, log2, lang1, lang2):
    boosters = [c for c in team if c['class_type'] == 'Booster']
    if not boosters: return
    for b in boosters:
        d_mult = b['booster_dmg_mult']
        h_mult = b['booster_hp_mult']
        add_dual_log(log1, log2, lang1, lang2,
            f"✨ <b>{team_name}:</b> Бустер <b>{b['name']}</b> усиливает команду! (Урон x{d_mult}, ХП x{h_mult})",
            f"✨ <b>{team_name}:</b> Booster <b>{b['name']}</b> empowers team! (DMG x{d_mult}, HP x{h_mult})"
        )
        for c in team:
            bonus_hp = int(c['hp'] * h_mult) - c['hp']
            if bonus_hp > 0:
                c['hp'] += bonus_hp
                c['max_hp'] += bonus_hp
            if c['class_type'] != 'Booster':
                c['dmg_buff'] += int(c['damage'] * d_mult) - c['damage']

async def process_burns(team, team_name, log1, log2, lang1, lang2):
    for c in team:
        if c['hp'] > 0 and c.get('burn', 0) > 0:
            c['hp'] -= c['burn']
            ru_str = f"🔥 {team_name}: <b>{c['name']}</b> получает {c['burn']} урона от горения!"
            en_str = f"🔥 {team_name}: <b>{c['name']}</b> takes {c['burn']} burn damage!"
            if c['hp'] <= 0:
                c['hp'] = 0
                ru_str += " ☠️ <i>Сгорел дотла!</i>"
                en_str += " ☠️ <i>Burned to ashes!</i>"
            add_dual_log(log1, log2, lang1, lang2, ru_str, en_str)
            c['burn'] = 0

async def execute_turn(atk_team, def_team, atk_name, def_name, log1, log2, lang1, lang2, force_attacker=None, force_target=None):
    await process_burns(atk_team, atk_name, log1, log2, lang1, lang2)
    atk_alive = [c for c in atk_team if c['hp'] > 0]
    def_alive = [c for c in def_team if c['hp'] > 0]
    heals = 0
    if not atk_alive or not def_alive: return False, heals
    
    if force_attacker and force_attacker['hp'] > 0 and force_attacker in atk_alive:
        atk = force_attacker
    else:
        atk = random.choice(atk_alive)
        
    base_dmg = atk['damage'] + atk.get('dmg_buff', 0)
    c_type = atk['class_type']
    
    dead_ru = " ☠️ <i>Мертв!</i>"
    dead_en = " ☠️ <i>Dead!</i>"
    
    if c_type == "Booster":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
        
        dmg = max(10, int(target['max_hp'] * 0.1))
        target['hp'] -= dmg
        ru_str = f"🔋 {atk_name}: <b>{atk['name']}</b> пускает заряд в <b>{target['name']}</b> на {dmg}!"
        en_str = f"🔋 {atk_name}: <b>{atk['name']}</b> zaps <b>{target['name']}</b> for {dmg}!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru; en_str += dead_en
        add_dual_log(log1, log2, lang1, lang2, ru_str, en_str)
        
    elif c_type == "Healer":
        other_allies = [c for c in atk_alive if c is not atk]
        
        if force_target and force_target['hp'] > 0 and force_target in atk_alive:
            target = force_target
            do_heal = True
        elif other_allies:
            target = random.choice(other_allies)
            do_heal = True
        else:
            do_heal = False
            
        if do_heal:
            curr_mult = atk.get('heal_power_mult', 1.0)
            heal_amount = int(base_dmg * curr_mult)
            
            target['hp'] += heal_amount
            if target['hp'] > target['max_hp']: 
                target['hp'] = target['max_hp']
                
            ru_str = f"💗 {atk_name}: <b>{atk['name']}</b> исцеляет союзника <b>{target['name']}</b> на {heal_amount} HP! (Эффективность: {int(curr_mult * 100)}%)"
            en_str = f"💗 {atk_name}: <b>{atk['name']}</b> heals ally <b>{target['name']}</b> for {heal_amount} HP! (Efficiency: {int(curr_mult * 100)}%)"
            add_dual_log(log1, log2, lang1, lang2, ru_str, en_str)
            heals += 1
            
            atk['heal_power_mult'] = max(0.0, curr_mult - 0.03)
        else:
            if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
            else: target = random.choice(def_alive)
            
            dmg = max(5, int(base_dmg * 0.2))
            target['hp'] -= dmg
            ru_str = f"🎯 {atk_name}: Одинокий Хилер <b>{atk['name']}</b> бьет <b>{target['name']}</b> на {dmg}!"
            en_str = f"🎯 {atk_name}: Lonely Healer <b>{atk['name']}</b> attacks <b>{target['name']}</b> for {dmg}!"
            if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru; en_str += dead_en
            add_dual_log(log1, log2, lang1, lang2, ru_str, en_str)
        
    elif c_type == "AOE":
        ru_str = f"🌪 {atk_name}: <b>{atk['name']}</b> бьет по всем на {base_dmg}!"
        en_str = f"🌪 {atk_name}: <b>{atk['name']}</b> hits ALL for {base_dmg}!"
        for d in def_alive:
            d['hp'] -= base_dmg
            if d['hp'] <= 0:
                d['hp'] = 0
                ru_str += f" ☠️ <i>{d['name']} мертв!</i>"
                en_str += f" ☠️ <i>{d['name']} is dead!</i>"
        add_dual_log(log1, log2, lang1, lang2, ru_str, en_str)
        
    elif c_type == "Splash":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: main_t = force_target
        else: main_t = random.choice(def_alive)
            
        splash_dmg = int(base_dmg * 0.5)
        ru_str = f"🌊 {atk_name}: <b>{atk['name']}</b> наносит {base_dmg} по <b>{main_t['name']}</b> и {splash_dmg} остальным!"
        en_str = f"🌊 {atk_name}: <b>{atk['name']}</b> hits <b>{main_t['name']}</b> for {base_dmg} and {splash_dmg} splash!"
        for d in def_alive:
            dmg = base_dmg if d == main_t else splash_dmg
            d['hp'] -= dmg
            if d['hp'] <= 0:
                d['hp'] = 0
                ru_str += f" ☠️ <i>{d['name']} мертв!</i>"
                en_str += f" ☠️ <i>{d['name']} is dead!</i>"
        add_dual_log(log1, log2, lang1, lang2, ru_str, en_str)
        
    elif c_type == "Fire":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
            
        target['hp'] -= base_dmg
        target['burn'] = target.get('burn', 0) + base_dmg
        ru_str = f"🔥 {atk_name}: <b>{atk['name']}</b> бьет <b>{target['name']}</b> на {base_dmg} и поджигает!"
        en_str = f"🔥 {atk_name}: <b>{atk['name']}</b> hits <b>{target['name']}</b> for {base_dmg} and burns!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru; en_str += dead_en
        add_dual_log(log1, log2, lang1, lang2, ru_str, en_str)
        
    else:
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
            
        target['hp'] -= base_dmg
        ru_str = f"🎯 {atk_name}: <b>{atk['name']}</b> наносит {base_dmg} по <b>{target['name']}</b>!"
        en_str = f"🎯 {atk_name}: <b>{atk['name']}</b> deals {base_dmg} to <b>{target['name']}</b>!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru; en_str += dead_en
        add_dual_log(log1, log2, lang1, lang2, ru_str, en_str)
        
    return True, heals

async def get_dynamic_trophies(rank_name: str, rank_idx: int, diff_scale: float = 1.0) -> int:
    base = max(5, 18 - int((rank_idx / 25) * 12)) 
    won = random.randint(base, base+3)
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
        return level_up, bp['title'] if bp else "BP", curr_lvl
    finally:
        await db.close()

# --- ЛОГИКА РУЧНОГО БОЯ ---
async def player_manual_turn(chat_id, p1_id, t1, t2, lang):
    t1_alive = [c for c in t1 if c['hp'] > 0]
    t2_alive = [c for c in t2 if c['hp'] > 0]
    if not t1_alive or not t2_alive: return None, None

    ev = asyncio.Event()
    active_manual_battles[chat_id] = {'p1_id': p1_id, 't1': t1, 't2': t2, 'event': ev, 'attacker_idx': None, 'target_idx': None, 'step': 'atk'}

    kb_btns = []
    for i, c in enumerate(t1):
        if c['hp'] > 0:
            is_heal = (c['class_type'] == 'Healer')
            stat_val = int((c['damage'] + c.get('dmg_buff', 0)) * c.get('heal_power_mult', 1.0)) if is_heal else (c['damage'] + c.get('dmg_buff', 0))
            icon = "💗" if is_heal else "⚔️"
            kb_btns.append([InlineKeyboardButton(text=f"{icon} {c['name']} ({icon}{stat_val} | ❤️{c['hp']})", callback_data=f"manatk_{i}")])
            
    kb = InlineKeyboardMarkup(inline_keyboard=kb_btns)
    
    try:
        msg = await bot.send_message(chat_id, loc(lang, "⏳ <b>Ваш ход!</b> Выберите карту для действия (12 сек):", "⏳ <b>Your turn!</b> Select card (12s):"), reply_markup=kb)
    except:
        return None, None

    try:
        await asyncio.wait_for(ev.wait(), timeout=12.0)
        a_idx = active_manual_battles[chat_id]['attacker_idx']
        t_idx = active_manual_battles[chat_id]['target_idx']
        atk = t1[a_idx] if a_idx is not None else None
        
        if atk and atk['class_type'] == 'Healer':
            tgt = t1[t_idx] if t_idx is not None else None
        else:
            tgt = t2[t_idx] if t_idx is not None else None
    except asyncio.TimeoutError:
        atk = None
        tgt = None
    finally:
        active_manual_battles.pop(chat_id, None)
        try: await msg.delete()
        except: pass

    return atk, tgt

@dp.callback_query(F.data.startswith("manatk_"))
async def cb_man_atk(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in active_manual_battles or active_manual_battles[chat_id]['p1_id'] != callback.from_user.id:
        return await callback.answer("Not your turn!", show_alert=True)

    idx = int(callback.data.split("_")[1])
    active_manual_battles[chat_id]['attacker_idx'] = idx
    active_manual_battles[chat_id]['step'] = 'tgt'

    t1 = active_manual_battles[chat_id]['t1']
    t2 = active_manual_battles[chat_id]['t2']
    atk = t1[idx]

    is_heal = (atk['class_type'] == 'Healer')
    target_team = t1 if is_heal else t2

    kb_btns = []
    for i, c in enumerate(target_team):
        if c['hp'] > 0:
            dmg_val = (c['damage'] + c.get('dmg_buff', 0))
            kb_btns.append([InlineKeyboardButton(text=f"{'💗' if is_heal else '🎯'} {c['name']} (⚔️{dmg_val} | ❤️{c['hp']})", callback_data=f"mantgt_{i}")])
            
    kb = InlineKeyboardMarkup(inline_keyboard=kb_btns)
    try: await callback.message.edit_text(f"Выбран: <b>{atk['name']}</b>\nВыберите цель:", reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("mantgt_"))
async def cb_man_tgt(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in active_manual_battles or active_manual_battles[chat_id]['p1_id'] != callback.from_user.id:
        return await callback.answer("Not your turn!", show_alert=True)

    idx = int(callback.data.split("_")[1])
    active_manual_battles[chat_id]['target_idx'] = idx
    active_manual_battles[chat_id]['event'].set()
    await callback.answer()

async def do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, lang, mods, is_pvp):
    if mods and mods.get('mod_manual_atk') and not is_pvp:
        atk, tgt = await player_manual_turn(chat_id, p1_id, t1, t2, lang)
        did_turn, heals = await execute_turn(t1, t2, p1_name, p2_name, log, None, lang, lang, force_attacker=atk, force_target=tgt)
    else:
        did_turn, heals = await execute_turn(t1, t2, p1_name, p2_name, log, None, lang, lang)
    return did_turn, heals

# -----------------------------
# КНОПКА СДАТЬСЯ
@dp.callback_query(F.data == "surrender_battle")
async def cb_surrender_battle(callback: types.CallbackQuery):
    if callback.from_user.id in active_combats:
        surrendered_players.add(callback.from_user.id)
        chat_id = callback.message.chat.id
        if chat_id in active_manual_battles and active_manual_battles[chat_id]['p1_id'] == callback.from_user.id:
            active_manual_battles[chat_id]['event'].set()
        await callback.answer("🏳️ Вы сдались!", show_alert=True)
    else:
        await callback.answer("Вы не в бою!", show_alert=True)

def get_battle_kb(lang="ru"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=loc(lang, "🏳️ Сдаться", "🏳️ Surrender"), callback_data="surrender_battle")]
    ])

# Умная задержка (мгновенно прерывается, если кто-то нажал "сдаться")
async def battle_delay(*p_ids, delay=3.0):
    steps = int(delay * 10)
    for _ in range(steps):
        await asyncio.sleep(0.1)
        if any(pid in surrendered_players for pid in p_ids if pid):
            break

async def run_battle_loop(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_id: int, p2_name: str, t1: list, t2: list, diff_trophies_scale: float = 1.0, diff_bp_mult: float = 1.0, is_pvp: bool = False, pvp_no_rewards: bool = False, lang="ru", mods=None):
    try:
        msg = await bot.send_message(chat_id, loc(lang, f"⚔️ Бой <b>{p1_name}</b> VS <b>{p2_name}</b> начнется через 3 сек!", f"⚔️ Battle <b>{p1_name}</b> VS <b>{p2_name}</b> starts in 3s!"))
        await asyncio.sleep(1)
        try: await msg.edit_text(loc(lang, "⚔️ Бой начнется через 2 сек!", "⚔️ Battle starts in 2s!"))
        except: pass
        await asyncio.sleep(1)
        try: await msg.edit_text(loc(lang, "⚔️ Бой начнется через 1 сек!", "⚔️ Battle starts in 1s!"))
        except: pass
        
        battle_start_time = time.time()
        log = []
        apply_boosters(t1, p1_name, log, None, lang, lang)
        apply_boosters(t2, p2_name, log, None, lang, lang)
        
        if log:
            try:
                await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2, lang) + "\n".join(log), reply_markup=get_battle_kb(lang))
            except Exception: pass
            await battle_delay(p1_id, p2_id)

        turn = 1
        winner = None
        winner_id = None
        loser_id = None
        p1_total_heals = 0
        p2_total_heals = 0
        timeout_flag = False
        
        while True:
            if time.time() - battle_start_time > 180:
                timeout_flag = True
                break
                
            if p1_id in surrendered_players:
                winner = p2_name; winner_id = p2_id; loser_id = p1_id
                surrendered_players.discard(p1_id)
                log.append(loc(lang, f"🏳️ <b>{p1_name} сдался!</b>", f"🏳️ <b>{p1_name} surrendered!</b>"))
                break

            t1_alive = [c for c in t1 if c['hp'] > 0]
            t2_alive = [c for c in t2 if c['hp'] > 0]
            
            if not t1_alive and not t2_alive:
                winner = loc(lang, "Ничья", "Draw"); break
            elif not t1_alive:
                winner = p2_name; winner_id = p2_id; loser_id = p1_id; break
            elif not t2_alive:
                winner = p1_name; winner_id = p1_id; loser_id = p2_id; break
                
            if turn > 40:
                winner = loc(lang, "Ничья по раундам", "Timeout Draw"); break

            did_turn, heals = await do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, lang, mods, is_pvp)
            p1_total_heals += heals
            if did_turn:
                if len(log) > 6: log = log[-6:]
                try:
                    await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2, lang) + "\n".join(log), reply_markup=get_battle_kb(lang))
                except Exception as e:
                    if "not found" in str(e).lower() or "deleted" in str(e).lower():
                        timeout_flag = True; break
                await battle_delay(p1_id, p2_id)

            if mods and mods.get('mod_enemy_atk_all') and not is_pvp:
                t1_a = [c for c in t1 if c['hp']>0]
                t2_a = [c for c in t2 if c['hp']>0]
                if t1_a and t2_a:
                    did_turn_e, heals_e = await execute_turn(t2, t1, p2_name, p1_name, log, None, lang, lang)
                    p2_total_heals += heals_e
                    if did_turn_e:
                        if len(log) > 6: log = log[-6:]
                        try: await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2, lang) + "\n".join(log), reply_markup=get_battle_kb(lang))
                        except Exception as e:
                            if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                        await battle_delay(p1_id, p2_id)

            t2_alive = [c for c in t2 if c['hp'] > 0]
            if t2_alive:
                if time.time() - battle_start_time > 180:
                    timeout_flag = True
                    break

                did_turn_e, heals_e = await execute_turn(t2, t1, p2_name, p1_name, log, None, lang, lang)
                p2_total_heals += heals_e
                if did_turn_e:
                    if len(log) > 6: log = log[-6:]
                    try: await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2, lang) + "\n".join(log), reply_markup=get_battle_kb(lang))
                    except Exception as e:
                        if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                    await battle_delay(p1_id, p2_id)
                    
                if mods and mods.get('mod_player_atk_all') and not is_pvp:
                    t1_a = [c for c in t1 if c['hp']>0]
                    t2_a = [c for c in t2 if c['hp']>0]
                    if t1_a and t2_a:
                        did_turn, heals = await do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, lang, mods, is_pvp)
                        p1_total_heals += heals
                        if did_turn:
                            if len(log) > 6: log = log[-6:]
                            try: await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2, lang) + "\n".join(log), reply_markup=get_battle_kb(lang))
                            except Exception as e:
                                if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                            await battle_delay(p1_id, p2_id)
            turn += 1

        if timeout_flag:
            try: await msg.edit_text(loc(lang, "⏳ <b>Бой автоматически прерван (ошибка или тайм-аут)!</b>", "⏳ <b>Battle automatically terminated (timeout/error)!</b>"))
            except: pass
            return

        try:
            if p1_total_heals > 0: await add_quest_progress(p1_id, 'q_heals_done', p1_total_heals)
            
            if is_pvp:
                await add_quest_progress(p1_id, 'q_pvp_played', 1)
                if p2_id != 0: 
                    await add_quest_progress(p2_id, 'q_pvp_played', 1)
                    if p2_total_heals > 0: await add_quest_progress(p2_id, 'q_heals_done', p2_total_heals)
            else:
                await add_quest_progress(p1_id, 'q_battles', 1)
                if winner == p1_name: await add_quest_progress(p1_id, 'q_wins', 1)

            code_text = ""
            winner_user_id = None
            if winner == p1_name: winner_user_id = p1_id
            elif is_pvp and winner == p2_name: winner_user_id = p2_id

            if winner_user_id is not None and "Draw" not in winner and "Ничья" not in winner:
                if random.random() <= 0.04:
                    db = await get_db_connection()
                    try:
                        async with db.execute("SELECT code FROM reward_codes WHERE is_active = 1 AND owner_id = 0 ORDER BY RANDOM() LIMIT 1") as cursor:
                            row = await cursor.fetchone()
                            if row:
                                code_val = row['code']
                                await db.execute("UPDATE reward_codes SET owner_id = ? WHERE code = ?", (winner_user_id, code_val))
                                await db.commit()
                                code_text = loc(lang,
                                    f"🎁 <b>ВЫПАЛ УНИКАЛЬНЫЙ КОД-НАГРАДА!</b>\nНажми, чтобы скопировать: <code>{code_val}</code>\nАктивируй через /codereward\n\n",
                                    f"🎁 <b>UNIQUE REWARD CODE DROPPED!</b>\nClick to copy: <code>{code_val}</code>\nActivate via /codereward\n\n"
                                )
                    except: pass
                    finally: await db.close()

            final_text = code_text + loc(lang, f"🏁 <b>ИТОГИ БОЯ: {p1_name} VS {p2_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n👑 <b>Победитель: {winner}</b>\n\n", f"🏁 <b>BATTLE RESULTS: {p1_name} VS {p2_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n👑 <b>Winner: {winner}</b>\n\n")
            bp_messages = []
            
            if pvp_no_rewards:
                final_text += loc(lang, "🤝 <b>Дружеская дуэль завершена!</b> Награды и кубки не начислялись.", "🤝 <b>Friendly duel finished!</b> No rewards or trophies.")
            elif is_pvp:
                if "Draw" not in winner and "Ничья" not in winner and winner_id and loser_id:
                    await execute_db("UPDATE users SET trophies = trophies + 15 WHERE id = ?", (winner_id,))
                    await execute_db("UPDATE users SET trophies = MAX(0, trophies - 10) WHERE id = ?", (loser_id,))
                    final_text += loc(lang, f"🏆 Победитель забирает <b>+15 Кубков</b>\n💀 Проигравший теряет <b>-10 Кубков</b>", f"🏆 Winner gets <b>+15 Trophies</b>\n💀 Loser loses <b>-10 Trophies</b>")
            else:
                mod_reward_mult = 1.0; mod_trophy_mult = 1.0
                if mods:
                    if mods.get('mod_enemy_hp'): mod_reward_mult += 0.3; mod_trophy_mult += 0.3
                    if mods.get('mod_enemy_atk_all'): mod_reward_mult += 0.35; mod_trophy_mult += 0.35
                    if mods.get('mod_enemy_stats'): mod_reward_mult += 0.2; mod_trophy_mult += 0.2
                    if mods.get('mod_player_atk_all'): mod_reward_mult -= 0.4
                    if mods.get('mod_manual_atk'): mod_reward_mult -= 0.5
                    if mods.get('mod_player_hp'): mod_reward_mult -= 0.3
                    
                mod_reward_mult = max(0.1, mod_reward_mult)
                coin_mult, xp_mult_event = await get_coin_xp_events()
                
                if winner == p1_name:
                    user = await fetch_one("SELECT trophies FROM users WHERE id = ?", (p1_id,))
                    rank = await get_user_rank(user['trophies'])
                    
                    coins_base = random.randint(25, 90) * rank['reward_mult'] * diff_trophies_scale * 0.85 * coin_mult
                    coins_won = int(coins_base * mod_reward_mult)
                    won_t_base = await get_dynamic_trophies(rank['name'], rank['rank_idx'], diff_trophies_scale)
                    won_t = int(won_t_base * mod_trophy_mult)
                    
                    await execute_db("UPDATE users SET coins = coins + ?, trophies = trophies + ? WHERE id = ?", (coins_won, won_t, p1_id))
                    
                    final_text += loc(lang, f"🎉 <b>Награды:</b>\n💰 {coins_won} Шекелей", f"🎉 <b>Rewards:</b>\n💰 {coins_won} Shekels")
                    if coin_mult > 1.0: final_text += f" (Ивент x{coin_mult})"
                    if mod_reward_mult != 1.0: final_text += f" [Моды x{mod_reward_mult:.2f}]"
                    final_text += loc(lang, f"\n🏆 {won_t} Кубков\n", f"\n🏆 {won_t} Trophies\n")
                    
                    bp_xp = int((20 * diff_bp_mult * xp_mult_event) * mod_reward_mult)
                    lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp)
                    final_text += f"🎫 +{bp_xp} BP XP"
                    if lvl_up: bp_messages.append(loc(lang, f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> {new_lvl} уровень в сезоне «{bp_title}»!", f"🎉 <b>NEW BP LEVEL!</b> Level {new_lvl} in '{bp_title}'!"))
                    
                elif winner == p2_name:
                    await execute_db("UPDATE users SET trophies = MAX(0, trophies - 2) WHERE id = ?", (p1_id,))
                    final_text += loc(lang, f"💀 Вы проиграли и потеряли <b>2 🏆</b>.\n", f"💀 You lost and dropped <b>2 🏆</b>.\n")
                    bp_xp = int((5 * diff_bp_mult * xp_mult_event) * mod_reward_mult)
                    lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp)
                    final_text += f"🎫 +{bp_xp} BP XP"
                    if lvl_up: bp_messages.append(loc(lang, f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> {new_lvl} уровень в сезоне «{bp_title}»!", f"🎉 <b>NEW BP LEVEL!</b> Level {new_lvl} in '{bp_title}'!"))
                    
            try: await msg.edit_text(final_text, reply_markup=None)
            except Exception: pass
            
            for b_msg in bp_messages:
                try: await bot.send_message(p1_id, b_msg)
                except: pass

        except Exception as e:
            logging.error(f"Reward error: {e}")
            try: await msg.edit_text("Ошибка при выдаче наград.", reply_markup=None)
            except: pass

    finally:
        active_combats.discard(p1_id)
        if is_pvp and p2_id != 0: active_combats.discard(p2_id)
        if chat_id in active_manual_battles: active_manual_battles.pop(chat_id, None)

@dp.message(F.text.in_(BTN_PVE))
async def cmd_pve_select(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang'] if user else 'ru'
    
    if message.from_user.id in active_combats: return await message.answer(loc(lang, "❌ Вы уже в бою!", "❌ You are already in combat!"))
    if message.from_user.id in user_trades: return await message.answer(loc(lang, "❌ Завершите обмен!", "❌ Finish your trade first!"))
        
    team1 = await get_team_data(message.from_user.id)
    if not team1: return await message.answer(loc(lang, "❌ Боевая колода пуста!", "❌ Battle deck is empty!"))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=loc(lang, "🟢 Лёгкий (-50% Кубки, -20% XP)", "🟢 Easy (-50% Trophies, -20% XP)"), callback_data="pve_diff_easy")],
        [InlineKeyboardButton(text=loc(lang, "🟡 Средний (Стандарт)", "🟡 Medium (Standard)"), callback_data="pve_diff_med")],
        [InlineKeyboardButton(text=loc(lang, "🔴 Сложный (+50% Кубки, +20% XP)", "🔴 Hard (+50% Trophies, +20% XP)"), callback_data="pve_diff_hard")],
        [InlineKeyboardButton(text=loc(lang, "☠️ Кошмар (+80% Кубки, +50% XP)", "☠️ Nightmare (+80% Trophies, +50% XP)"), callback_data="pve_diff_nightmare")]
    ])
    await message.answer(loc(lang, "⚔️ <b>ВЫБОР СЛОЖНОСТИ ИИ:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━", "⚔️ <b>SELECT AI DIFFICULTY:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━"), reply_markup=kb)

@dp.callback_query(F.data.startswith("pve_diff_"))
async def cmd_pve_battle(callback: types.CallbackQuery):
    if callback.from_user.id in active_combats or callback.from_user.id in user_trades:
        return await callback.answer("❌ Already busy!", show_alert=True)
        
    diff_type = callback.data.split("_")[2]
    power_mult, trophies_scale, bp_xp_mult = 1.0, 1.0, 1.0
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    lang = user['lang']
    
    diff_name = loc(lang, "Средний", "Medium")
    if diff_type == "easy": power_mult, trophies_scale, bp_xp_mult, diff_name = 0.7, 0.5, 0.8, loc(lang, "Лёгкий 🟢", "Easy 🟢")
    elif diff_type == "med": power_mult, trophies_scale, bp_xp_mult, diff_name = 1.1, 1.0, 1.0, loc(lang, "Средний 🟡", "Medium 🟡")
    elif diff_type == "hard": power_mult, trophies_scale, bp_xp_mult, diff_name = 1.6, 1.5, 1.2, loc(lang, "Сложный 🔴", "Hard 🔴")
    elif diff_type == "nightmare": power_mult, trophies_scale, bp_xp_mult, diff_name = 2.0, 1.8, 1.5, loc(lang, "Кошмар ☠️", "Nightmare ☠️")
        
    mods = {
        'mod_enemy_hp': user.get('mod_enemy_hp', 0),
        'mod_enemy_atk_all': user.get('mod_enemy_atk_all', 0),
        'mod_enemy_stats': user.get('mod_enemy_stats', 0),
        'mod_player_atk_all': user.get('mod_player_atk_all', 0),
        'mod_manual_atk': user.get('mod_manual_atk', 0),
        'mod_player_hp': user.get('mod_player_hp', 0)
    }

    try: await callback.message.edit_text(loc(lang, f"⚔️ <i>Ищем противника... Сложность: <b>{diff_name}</b></i>", f"⚔️ <i>Finding opponent... Diff: <b>{diff_name}</b></i>"))
    except: pass
    
    team1 = await get_team_data(callback.from_user.id)
    rank = await get_user_rank(user['trophies'])
    
    team2 = await get_bot_team(callback.from_user.id, rank['difficulty_mult'] * power_mult, rank['name'], diff_type)
    if not team2: 
        try: await callback.message.edit_text("Error: no cards in DB")
        except: pass
        return
    
    if mods['mod_enemy_hp']:
        for c in team2:
            c['hp'] = int(c['hp'] * 1.5)
            c['max_hp'] = c['hp']
    if mods['mod_enemy_stats']:
        for c in team2:
            c['damage'] = int(c['damage'] * 1.2)
            c['hp'] = int(c['hp'] * 1.2)
            c['max_hp'] = c['hp']
            c['booster_dmg_mult'] *= 1.2
            c['booster_hp_mult'] *= 1.2
    if mods['mod_player_hp']:
        for c in team1:
            c['hp'] = int(c['hp'] * 1.3)
            c['max_hp'] = c['hp']
            
    title_str = await get_user_titles_str(callback.from_user.id, lang)
    p1_name = get_display_name(user) + title_str
    active_combats.add(callback.from_user.id)
    
    await log_user_action(callback.from_user.id, f"Начал PvE бой (сложность: {diff_type})")
    
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, callback.from_user.id, p1_name, 0, f"AI ({diff_name})", team1, team2, trophies_scale, bp_xp_mult, is_pvp=False, lang=lang, mods=mods))
    await callback.answer()

# ========================================================================
# ДУЭЛИ И АВТОПОДБОР (PVP)
# ========================================================================
@dp.message(F.text.in_(BTN_PVP))
async def cmd_pvp_menu(message: types.Message):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats or message.from_user.id in user_trades:
        return await message.answer("❌ Busy!")
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang'] if user else 'ru'
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=loc(lang, "🎲 Найти случайного (Автоподбор)", "🎲 Find Random (Matchmaking)"), callback_data="pvp_random")],
        [InlineKeyboardButton(text=loc(lang, "🎯 Вызвать по ID / @username", "🎯 Challenge by ID / @username"), callback_data="pvp_direct")]
    ])
    await message.answer(loc(lang, "⚔️ <b>PvP ДУЭЛЬ</b>\nВыберите режим (награды за PvP дуэли отключены):", "⚔️ <b>PvP DUEL</b>\nChoose mode (No rewards for PvP):"), reply_markup=kb)

@dp.callback_query(F.data == "pvp_direct")
async def cb_pvp_direct(callback: types.CallbackQuery, state: FSMContext):
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (callback.from_user.id,))
    lang = user['lang'] if user else 'ru'
    try: await callback.message.edit_text(loc(lang, "Введите @username или ID игрока:", "Enter @username or ID of player:"))
    except: pass
    await state.set_state(PvPState.waiting_target)
    asyncio.create_task(clear_fsm_timeout(state, callback.message.chat.id, 60))
    await callback.answer()

@dp.callback_query(F.data == "pvp_random")
async def cb_pvp_random(callback: types.CallbackQuery):
    u_id = callback.from_user.id
    user = await fetch_one("SELECT * FROM users WHERE id=?", (u_id,))
    lang = user['lang']
    
    if u_id in active_combats or u_id in user_trades: return await callback.answer("Busy!", show_alert=True)
    t1 = await get_team_data(u_id)
    if not t1: return await callback.answer(loc(lang, "Колода пуста!", "Deck empty!"), show_alert=True)
    
    if u_id in pvp_queue:
        pvp_queue.remove(u_id)
        try: await callback.message.edit_text(loc(lang, "Поиск отменен.", "Search cancelled."))
        except: pass
        return
        
    valid_opponents = [x for x in pvp_queue if x != u_id and x not in active_combats and x not in user_trades]
    
    if valid_opponents:
        opp_id = valid_opponents[0]
        pvp_queue.remove(opp_id)
        
        opp = await fetch_one("SELECT * FROM users WHERE id=?", (opp_id,))
        t2 = await get_team_data(opp_id)
        
        active_combats.add(u_id)
        active_combats.add(opp_id)
        
        title_p1 = await get_user_titles_str(u_id, lang)
        title_p2 = await get_user_titles_str(opp_id, opp['lang'])
        p1_name = get_display_name(user) + title_p1
        p2_name = get_display_name(opp) + title_p2
        
        try: await callback.message.edit_text(loc(lang, "Противник найден! Начинаем...", "Opponent found! Starting..."))
        except: pass
        try: await bot.send_message(opp_id, loc(opp['lang'], "Противник найден! Начинаем...", "Opponent found! Starting..."))
        except: pass
        
        await log_user_action(u_id, f"Начал PvP бой (Автоподбор) против {opp_id}")
        await log_user_action(opp_id, f"Начал PvP бой (Автоподбор) против {u_id}")
        
        asyncio.create_task(run_pvp_dual_broadcast(u_id, opp_id, p1_name, p2_name, t1, t2))
    else:
        pvp_queue.add(u_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=loc(lang, "❌ Отменить поиск", "❌ Cancel Search"), callback_data="pvp_random")]])
        try: await callback.message.edit_text(loc(lang, "🔍 Поиск противника... Ожидайте.", "🔍 Searching opponent... Wait."), reply_markup=kb)
        except: pass
    await callback.answer()

@dp.message(PvPState.waiting_target)
async def process_pvp_target(message: types.Message, state: FSMContext):
    val = message.text.strip()
    target_user = None
    user = await fetch_one("SELECT * FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang']
    
    if val.isdigit(): target_user = await fetch_one("SELECT * FROM users WHERE id = ?", (int(val),))
    else: target_user = await fetch_one("SELECT * FROM users WHERE username = ?", (val.lstrip('@'),))
        
    if not target_user: return await message.answer(loc(lang, "❌ Игрок не найден.", "❌ Player not found."))
    if target_user['id'] == message.from_user.id: return await message.answer("❌ Self!")
    if target_user['id'] in active_combats or target_user['id'] in user_trades: return await message.answer("❌ Busy!")

    challenger_name = get_display_name(user) + await get_user_titles_str(message.from_user.id, lang)
    t_lang = target_user['lang']
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=loc(t_lang, "⚔️ Принять", "⚔️ Accept"), callback_data=f"pvp_accept_{user['id']}"),
         InlineKeyboardButton(text=loc(t_lang, "❌ Отклонить", "❌ Decline"), callback_data=f"pvp_decline_{user['id']}")]
    ])
    
    try:
        await bot.send_message(target_user['id'], loc(t_lang, f"⚔️ <b>{challenger_name}</b> вызывает вас на дуэль!", f"⚔️ <b>{challenger_name}</b> challenges you to a duel!"), reply_markup=kb)
        await message.answer(loc(lang, "📨 Вызов отправлен.", "📨 Challenge sent."))
        await log_user_action(message.from_user.id, f"Бросил вызов на PvP игроку {target_user['id']}")
    except: await message.answer("Error sending message.")
    await state.clear()

@dp.callback_query(F.data.startswith("pvp_accept_"))
async def callback_pvp_accept(callback: types.CallbackQuery):
    challenger_id = int(callback.data.split("_")[2])
    target_id = callback.from_user.id
    
    if target_id in active_combats or challenger_id in active_combats or target_id in user_trades or challenger_id in user_trades:
        return await callback.answer("Busy!", show_alert=True)
        
    t1 = await get_team_data(challenger_id)
    t2 = await get_team_data(target_id)
    
    if not t1 or not t2: 
        try: await callback.message.edit_text("Deck empty error.")
        except: pass
        return
        
    challenger = await fetch_one("SELECT * FROM users WHERE id = ?", (challenger_id,))
    target = await fetch_one("SELECT * FROM users WHERE id = ?", (target_id,))
    
    title_p1 = await get_user_titles_str(challenger_id, challenger['lang'])
    title_p2 = await get_user_titles_str(target_id, target['lang'])
    p1_name = get_display_name(challenger) + title_p1
    p2_name = get_display_name(target) + title_p2
    
    active_combats.add(challenger_id)
    active_combats.add(target_id)
    
    await log_user_action(target_id, f"Принял PvP вызов от {challenger_id}")
    
    asyncio.create_task(run_pvp_dual_broadcast(challenger_id, target_id, p1_name, p2_name, t1, t2))
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("pvp_decline_"))
async def callback_pvp_decline(callback: types.CallbackQuery):
    challenger_id = int(callback.data.split("_")[2])
    target = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    try: await bot.send_message(challenger_id, f"❌ Declined.")
    except: pass
    try: await callback.message.edit_text("❌ Declined.")
    except: pass
    await callback.answer()

async def run_pvp_dual_broadcast(p1_id: int, p2_id: int, p1_name: str, p2_name: str, t1: list, t2: list):
    try:
        p1_lang = (await fetch_one("SELECT lang FROM users WHERE id=?", (p1_id,)))['lang']
        p2_lang = (await fetch_one("SELECT lang FROM users WHERE id=?", (p2_id,)))['lang']
        
        msg1 = await bot.send_message(p1_id, loc(p1_lang, f"⚔️ Дуэль против <b>{p2_name}</b> начнется через 3 сек!", f"⚔️ Duel vs <b>{p2_name}</b> in 3s!"))
        msg2 = await bot.send_message(p2_id, loc(p2_lang, f"⚔️ Дуэль против <b>{p1_name}</b> начнется через 3 сек!", f"⚔️ Duel vs <b>{p1_name}</b> in 3s!"))
        await asyncio.sleep(1)
        try: await msg1.edit_text("2...")
        except: pass
        try: await msg2.edit_text("2...")
        except: pass
        await asyncio.sleep(1)
        try: await msg1.edit_text("1...")
        except: pass
        try: await msg2.edit_text("1...")
        except: pass
        await asyncio.sleep(1)
        
        battle_start_time = time.time()
        log1 = []
        log2 = []
        apply_boosters(t1, p1_name, log1, log2, p1_lang, p2_lang)
        apply_boosters(t2, p2_name, log1, log2, p1_lang, p2_lang)
        
        if log1:
            header1 = build_battle_header(p1_name, t1, p2_name, t2, p1_lang) + "\n".join(log1)
            header2 = build_battle_header(p1_name, t1, p2_name, t2, p2_lang) + "\n".join(log2)
            try: await msg1.edit_text(header1, reply_markup=get_battle_kb(p1_lang))
            except: pass
            try: await msg2.edit_text(header2, reply_markup=get_battle_kb(p2_lang))
            except: pass
            await battle_delay(p1_id, p2_id)

        turn = 1
        winner = None
        p1_heals = p2_heals = 0
        timeout_flag = False
        
        while True:
            if time.time() - battle_start_time > 180:
                timeout_flag = True
                break
                
            if p1_id in surrendered_players and p2_id in surrendered_players:
                winner = "Draw"
                surrendered_players.discard(p1_id); surrendered_players.discard(p2_id)
                break
            elif p1_id in surrendered_players:
                winner = p2_name; surrendered_players.discard(p1_id)
                log1.append(loc(p1_lang, f"🏳️ <b>{p1_name} сдался!</b>", f"🏳️ <b>{p1_name} surrendered!</b>"))
                log2.append(loc(p2_lang, f"🏳️ <b>{p1_name} сдался!</b>", f"🏳️ <b>{p1_name} surrendered!</b>"))
                break
            elif p2_id in surrendered_players:
                winner = p1_name
                surrendered_players.discard(p2_id)
                log1.append(loc(p1_lang, f"🏳️ <b>{p2_name} сдался!</b>", f"🏳️ <b>{p2_name} surrendered!</b>"))
                log2.append(loc(p2_lang, f"🏳️ <b>{p2_name} сдался!</b>", f"🏳️ <b>{p2_name} surrendered!</b>"))
                break

            t1_a = [c for c in t1 if c['hp'] > 0]
            t2_a = [c for c in t2 if c['hp'] > 0]
            if not t1_a and not t2_a: winner = "Draw"; break
            elif not t1_a: winner = p2_name; break
            elif not t2_a: winner = p1_name; break
            if turn > 40: winner = "Timeout Draw"; break

            did_turn, h = await execute_turn(t1, t2, p1_name, p2_name, log1, log2, p1_lang, p2_lang)
            p1_heals += h
            if did_turn:
                if len(log1) > 6: log1 = log1[-6:]; log2 = log2[-6:]
                try: await msg1.edit_text(build_battle_header(p1_name, t1, p2_name, t2, p1_lang) + "\n".join(log1), reply_markup=get_battle_kb(p1_lang))
                except Exception as e:
                    if "message is not modified" not in str(e).lower() and ("not found" in str(e).lower() or "deleted" in str(e).lower()): timeout_flag=True; break
                try: await msg2.edit_text(build_battle_header(p1_name, t1, p2_name, t2, p2_lang) + "\n".join(log2), reply_markup=get_battle_kb(p2_lang))
                except Exception as e:
                    if "message is not modified" not in str(e).lower() and ("not found" in str(e).lower() or "deleted" in str(e).lower()): timeout_flag=True; break
                await battle_delay(p1_id, p2_id)

            t2_a = [c for c in t2 if c['hp'] > 0]
            if t2_a:
                if time.time() - battle_start_time > 180:
                    timeout_flag = True
                    break
                    
                did_turn, h = await execute_turn(t2, t1, p2_name, p1_name, log1, log2, p1_lang, p2_lang)
                p2_heals += h
                if did_turn:
                    if len(log1) > 6: log1 = log1[-6:]; log2 = log2[-6:]
                    try: await msg1.edit_text(build_battle_header(p1_name, t1, p2_name, t2, p1_lang) + "\n".join(log1), reply_markup=get_battle_kb(p1_lang))
                    except Exception as e:
                        if "message is not modified" not in str(e).lower() and ("not found" in str(e).lower() or "deleted" in str(e).lower()): timeout_flag=True; break
                    try: await msg2.edit_text(build_battle_header(p1_name, t1, p2_name, t2, p2_lang) + "\n".join(log2), reply_markup=get_battle_kb(p2_lang))
                    except Exception as e:
                        if "message is not modified" not in str(e).lower() and ("not found" in str(e).lower() or "deleted" in str(e).lower()): timeout_flag=True; break
                    await battle_delay(p1_id, p2_id)
            turn += 1

        if timeout_flag:
            txt1 = loc(p1_lang, "⏳ <b>Бой прерван (ошибка или тайм-аут).</b>", "⏳ <b>Battle terminated (timeout/error).</b>")
            txt2 = loc(p2_lang, "⏳ <b>Бой прерван (ошибка или тайм-аут).</b>", "⏳ <b>Battle terminated (timeout/error).</b>")
            try: await msg1.edit_text(txt1)
            except: pass
            try: await msg2.edit_text(txt2)
            except: pass
            return

        await add_quest_progress(p1_id, 'q_pvp_played', 1)
        await add_quest_progress(p2_id, 'q_pvp_played', 1)
        if p1_heals > 0: await add_quest_progress(p1_id, 'q_heals_done', p1_heals)
        if p2_heals > 0: await add_quest_progress(p2_id, 'q_heals_done', p2_heals)

        code_text_1 = ""
        code_text_2 = ""
        winner_user_id = None
        
        if "Draw" not in winner and "Ничья" not in winner:
            if winner == p1_name: winner_user_id = p1_id
            elif winner == p2_name: winner_user_id = p2_id
            
        if winner_user_id is not None:
            if random.random() <= 0.04:
                db = await get_db_connection()
                try:
                    async with db.execute("SELECT code FROM reward_codes WHERE is_active = 1 AND owner_id = 0 ORDER BY RANDOM() LIMIT 1") as cursor:
                        row = await cursor.fetchone()
                        if row:
                            code_val = row['code']
                            await db.execute("UPDATE reward_codes SET owner_id = ? WHERE code = ?", (winner_user_id, code_val))
                            await db.commit()
                            dropped_msg_ru = f"🎁 <b>ВЫПАЛ УНИКАЛЬНЫЙ КОД-НАГРАДА!</b>\nНажми, чтобы скопировать: <code>{code_val}</code>\nАктивируй через /codereward\n\n"
                            dropped_msg_en = f"🎁 <b>UNIQUE REWARD CODE DROPPED!</b>\nClick to copy: <code>{code_val}</code>\nActivate via /codereward\n\n"
                            if winner_user_id == p1_id:
                                code_text_1 = loc(p1_lang, dropped_msg_ru, dropped_msg_en)
                            else:
                                code_text_2 = loc(p2_lang, dropped_msg_ru, dropped_msg_en)
                except Exception as e:
                    logging.error(f"Reward Code Drop PvP Error: {e}")
                finally:
                    await db.close()

        final1 = code_text_1 + loc(p1_lang, f"🏁 <b>ИТОГИ: {p1_name} VS {p2_name}</b>\nПобедитель: {winner}\nДружеская дуэль (без наград).", f"🏁 <b>RESULTS: {p1_name} VS {p2_name}</b>\nWinner: {winner}\nFriendly duel (no rewards).")
        final2 = code_text_2 + loc(p2_lang, f"🏁 <b>ИТОГИ: {p1_name} VS {p2_name}</b>\nПобедитель: {winner}\nДружеская дуэль (без наград).", f"🏁 <b>RESULTS: {p1_name} VS {p2_name}</b>\nWinner: {winner}\nFriendly duel (no rewards).")
        
        try: await msg1.edit_text(final1, reply_markup=None)
        except: pass
        try: await msg2.edit_text(final2, reply_markup=None)
        except: pass
        
    finally:
        active_combats.discard(p1_id)
        active_combats.discard(p2_id)

# ========================================================================
# ТРЕЙДЫ
# ========================================================================
@dp.message(Command("trade"))
async def cmd_trade_request(message: types.Message, state: FSMContext):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats or message.from_user.id in user_trades: return await message.answer("Busy!")
    user = await fetch_one("SELECT lang FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang'] if user else 'ru'
    parts = message.text.split()
    if len(parts) > 1:
        message.text = parts[1]
        await process_trade_target(message, state)
    else:
        await message.answer(loc(lang, "🤝 <b>ОБМЕН</b>\nВведите @username или ID игрока:", "🤝 <b>TRADE</b>\nEnter @username or ID:"))
        await state.set_state(TradeState.waiting_target)
        asyncio.create_task(clear_fsm_timeout(state, message.chat.id, 60))

@dp.message(TradeState.waiting_target)
async def process_trade_target(message: types.Message, state: FSMContext):
    val = message.text.strip()
    user = await fetch_one("SELECT * FROM users WHERE id=?", (message.from_user.id,))
    lang = user['lang']
    target_user = None
    
    if val.isdigit(): target_user = await fetch_one("SELECT * FROM users WHERE id = ?", (int(val),))
    else: target_user = await fetch_one("SELECT * FROM users WHERE username = ?", (val.lstrip('@'),))
        
    if not target_user: return await message.answer("Not found.")
    if target_user['id'] == message.from_user.id: return await message.answer("Self!")
    if target_user['id'] in active_combats or target_user['id'] in user_trades: return await message.answer("Busy!")

    challenger_name = get_display_name(user) + await get_user_titles_str(message.from_user.id, lang)
    t_lang = target_user['lang']
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=loc(t_lang, "✅ Принять", "✅ Accept"), callback_data=f"tr_acc_{user['id']}"),
         InlineKeyboardButton(text=loc(t_lang, "❌ Отклонить", "❌ Decline"), callback_data=f"tr_dec_{user['id']}")]
    ])
    
    try:
        await bot.send_message(target_user['id'], loc(t_lang, f"🤝 <b>{challenger_name}</b> предлагает обмен!", f"🤝 <b>{challenger_name}</b> offers a trade!"), reply_markup=kb)
        await message.answer(loc(lang, "📨 Запрос отправлен.", "📨 Request sent."))
        await log_user_action(message.from_user.id, f"Отправил запрос на трейд игроку {target_user['id']}")
    except: await message.answer("Error.")
    await state.clear()

@dp.callback_query(F.data.startswith("tr_acc_"))
async def callback_trade_accept(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[2])
    p2_id = callback.from_user.id
    if p1_id in user_trades or p2_id in user_trades or p1_id in active_combats or p2_id in active_combats: return await callback.answer("Busy!", show_alert=True)
        
    p1 = await fetch_one("SELECT * FROM users WHERE id = ?", (p1_id,))
    p2 = await fetch_one("SELECT * FROM users WHERE id = ?", (p2_id,))
    
    trade_id = f"tr_{p1_id}_{p2_id}_{int(time.time())}"
    trade = {
        'id': trade_id, 'p1': p1_id, 'p2': p2_id,
        'p1_name': get_display_name(p1), 'p2_name': get_display_name(p2),
        'p1_offer': {}, 'p2_offer': {},  
        'p1_strings': {}, 'p2_strings': {}, 
        'p1_ready': False, 'p2_ready': False,
        'p1_confirmed': False, 'p2_confirmed': False,
        'p1_msg': None, 'p2_msg': None,
        'start_time': time.time(), 'status': 'ongoing',
        'l1': p1['lang'], 'l2': p2['lang']
    }
    
    active_trades[trade_id] = trade
    user_trades[p1_id] = trade_id
    user_trades[p2_id] = trade_id
    
    await log_user_action(p2_id, f"Принял запрос на трейд от {p1_id}")
    
    try:
        msg1 = await bot.send_message(p1_id, await render_trade_text(trade, trade['l1']), reply_markup=get_trade_main_kb(trade, p1_id))
        trade['p1_msg'] = msg1.message_id
    except: pass
    try:
        msg2 = await bot.send_message(p2_id, await render_trade_text(trade, trade['l2']), reply_markup=get_trade_main_kb(trade, p2_id))
        trade['p2_msg'] = msg2.message_id
    except: pass
    
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_dec_"))
async def callback_trade_decline(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[2])
    try: await bot.send_message(p1_id, "❌ Declined.")
    except: pass
    try: await callback.message.edit_text("❌ Declined.")
    except: pass
    await callback.answer()

async def render_trade_text(trade, lang="ru"):
    text = loc(lang, "🤝 <b>ТОРГОВАЯ КОМНАТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n", "🤝 <b>TRADE ROOM</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n")
    
    text += loc(lang, f"🔵 <b>Предлагает {trade['p1_name']}:</b>\n", f"🔵 <b>{trade['p1_name']} offers:</b>\n")
    if not trade['p1_offer']: text += loc(lang, "  └ <i>Ничего</i>\n", "  └ <i>Nothing</i>\n")
    else:
        for inv_id, qty in trade['p1_offer'].items(): text += f"  └ {qty}x {trade['p1_strings'].get(inv_id, '?')}\n"
            
    text += loc(lang, f"\n🔴 <b>Предлагает {trade['p2_name']}:</b>\n", f"\n🔴 <b>{trade['p2_name']} offers:</b>\n")
    if not trade['p2_offer']: text += loc(lang, "  └ <i>Ничего</i>\n", "  └ <i>Nothing</i>\n")
    else:
        for inv_id, qty in trade['p2_offer'].items(): text += f"  └ {qty}x {trade['p2_strings'].get(inv_id, '?')}\n"
            
    r_str = loc(lang, "✅ Готов", "✅ Ready")
    w_str = loc(lang, "⏳ Выбирает...", "⏳ Choosing...")
    p1_st = r_str if trade['p1_ready'] else w_str
    p2_st = r_str if trade['p2_ready'] else w_str
    
    text += loc(lang, f"━━━━━━━━━━━━━━━━━━━━━━━━\n📊 <b>Статус:</b>\n", f"━━━━━━━━━━━━━━━━━━━━━━━━\n📊 <b>Status:</b>\n")
    text += f"{trade['p1_name']}: {p1_st}\n{trade['p2_name']}: {p2_st}\n"
    return text

def get_trade_main_kb(trade, user_id):
    if trade['status'] != 'ongoing': return None
    lang = trade['l1'] if user_id == trade['p1'] else trade['l2']
    kb = []
    if trade['p1_ready'] and trade['p2_ready']:
        is_conf = trade['p1_confirmed'] if user_id == trade['p1'] else trade['p2_confirmed']
        if is_conf: kb.append([InlineKeyboardButton(text=loc(lang, "⏳ Ожидание...", "⏳ Waiting..."), callback_data="ignore")])
        else: kb.append([InlineKeyboardButton(text=loc(lang, "🔒 ПОДТВЕРДИТЬ", "🔒 CONFIRM"), callback_data="tr_action_confirm")])
    else:
        kb.append([
            InlineKeyboardButton(text=loc(lang, "➕ Добавить", "➕ Add"), callback_data="tr_menu_add"),
            InlineKeyboardButton(text=loc(lang, "➖ Убрать", "➖ Remove"), callback_data="tr_menu_rem")
        ])
        is_ready = trade['p1_ready'] if user_id == trade['p1'] else trade['p2_ready']
        if is_ready: kb.append([InlineKeyboardButton(text=loc(lang, "⏳ Ждем партнера...", "⏳ Waiting for partner..."), callback_data="ignore")])
        else: kb.append([InlineKeyboardButton(text=loc(lang, "✅ ГОТОВ К ОБМЕНУ", "✅ READY"), callback_data="tr_action_ready")])
            
    kb.append([InlineKeyboardButton(text=loc(lang, "❌ Отменить трейд", "❌ Cancel Trade"), callback_data="tr_action_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def update_trade_uis(trade):
    try: await bot.edit_message_text(await render_trade_text(trade, trade['l1']), chat_id=trade['p1'], message_id=trade['p1_msg'], reply_markup=get_trade_main_kb(trade, trade['p1']))
    except: pass
    try: await bot.edit_message_text(await render_trade_text(trade, trade['l2']), chat_id=trade['p2'], message_id=trade['p2_msg'], reply_markup=get_trade_main_kb(trade, trade['p2']))
    except: pass

@dp.callback_query(F.data.startswith("tr_action_"))
async def cb_trade_actions(callback: types.CallbackQuery):
    action = callback.data.split("_")[2]
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer("Error", show_alert=True)
    trade = active_trades[trade_id]
    
    if action == "cancel":
        trade['status'] = 'cancelled'
        try: await bot.edit_message_text("❌ Cancelled.", chat_id=trade['p1'], message_id=trade['p1_msg'])
        except: pass
        try: await bot.edit_message_text("❌ Cancelled.", chat_id=trade['p2'], message_id=trade['p2_msg'])
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
        if trade['p1_confirmed'] and trade['p2_confirmed']: await execute_trade(trade_id)
    await callback.answer()

async def cancel_trade(trade_id, reason="Cancelled"):
    trade = active_trades.pop(trade_id, None)
    if not trade: return
    user_trades.pop(trade['p1'], None)
    user_trades.pop(trade['p
