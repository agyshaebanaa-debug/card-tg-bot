import asyncio
import logging
import random
import time
import io
import os
import math
import json
import string
import html
import uuid
from datetime import datetime, timedelta, timezone

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
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

try:
    from PIL import Image, ImageOps, ImageDraw
except ImportError:
    raise ImportError("Установите Pillow: pip install Pillow")

import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА
# ========================================================================
BOT_TOKEN = "8953052039:AAEIYQI69yLHMRxLIUTVmmQvxxJlaJAw8hU"
SUPER_ADMIN_ID = 5341904332
DB_NAME = "cards_database.db"

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

RARITY_COLORS = {
    "Basic": "gray",
    "Uncommon": "green",
    "Rare": "deepskyblue",
    "Epic": "purple",
    "Legendary": "gold",
    "Mythic": "red",
    "Super": "rainbow",
    "Exclusive": "lightpink",
    "Leaderboard": "cyan",
    "Secret": "black" 
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
    "Leaderboard": "👑",
    "Secret": "⬛"
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
    "Secret": 10,
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

ENDLESS_RARITY_COST = {
    "Basic": 1, "Uncommon": 2, "Rare": 5, "Epic": 10,
    "Legendary": 25, "Mythic": 50, "Super": 100,
    "Exclusive": 150, "Leaderboard": 500, "Secret": 1000
}

active_combats = set()
active_trades = {}  
user_trades = {}    
pvp_queue = set()
active_manual_battles = {} 
surrendered_players = set() 
active_craft_sessions = {} 
active_upgrades = {}

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

QUEST_TEMPLATES = [
    {"id": "q_pve", "desc": "Сыграть {} PvE боёв", "target": (3, 7)},
    {"id": "q_pvp", "desc": "Сыграть {} PvP дуэлей", "target": (2, 5)},
    {"id": "q_open", "desc": "Открыть {} любых карт", "target": (5, 15)},
    {"id": "q_upgrade", "desc": "Улучшить мутацию {} раз", "target": (1, 3)},
    {"id": "q_craft", "desc": "Скрафтить {} карт", "target": (1, 2)}
]

BTN_DRAW = "🎴 Выбить карту"
BTN_PVE = "⚔️ Поиск боя (боты)"
BTN_PVP = "⚔️ PvP Дуэль"
BTN_INV = "🎒 Инвентарь"
BTN_PROF = "👤 Профиль"
BTN_EQ = "🛡 Экипировка"
BTN_QUESTS = "📜 Квесты"
BTN_SHOP = "🛒 Магазин"
BTN_BP = "🎟 Батл-пассы"
BTN_TOP = "🏆 Топ игроков"
BTN_IDX = "📖 Индекс"
BTN_SEED_PACKS = "📦 Сид-Паки"
BTN_SET = "⚙️ Настройки"
BTN_SIGN = "✍️ Подписать карту"
BTN_ADM = "⚙️ Админ-панель"
BTN_CRAFT = "🔨 Крафт"
BTN_ENDLESS_MAIN = "♾ ENDLESS"

BTN_E_SHOP = "🛒 Endless Shop"
BTN_E_LB = "🏆 Endless Leaderboard"
BTN_E_NORM = "🔙 Обычный мод"

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
                pity_mythic INTEGER DEFAULT 0,
                pity_super INTEGER DEFAULT 0,
                total_coins INTEGER DEFAULT 0,
                notif_shop INTEGER DEFAULT 1,
                notif_events INTEGER DEFAULT 1,
                notif_quests INTEGER DEFAULT 1,
                notif_announces INTEGER DEFAULT 1,
                notif_1_rnd INTEGER DEFAULT 1,
                notif_3_rnd INTEGER DEFAULT 1,
                notif_5_rnd INTEGER DEFAULT 1,
                notif_10_rnd INTEGER DEFAULT 1,
                notif_25_rnd INTEGER DEFAULT 1,
                notif_50_rnd INTEGER DEFAULT 1,
                notif_100_rnd INTEGER DEFAULT 1,
                notif_rnd_leg INTEGER DEFAULT 1,
                notif_rnd_myth INTEGER DEFAULT 1,
                notif_rnd_sup INTEGER DEFAULT 1,
                mod_enemy_hp INTEGER DEFAULT 0,
                mod_enemy_atk_all INTEGER DEFAULT 0,
                mod_enemy_stats INTEGER DEFAULT 0,
                mod_player_atk_all INTEGER DEFAULT 0,
                mod_manual_atk INTEGER DEFAULT 0,
                mod_player_hp INTEGER DEFAULT 0
            )
        """)
        
        for col in ["r_bucks", "perm_2x_shekels", "perm_2x_bpxp", "perm_5th_slot", "perm_1_5x_luck", "vip_status", "equip5", "soul_shards", "is_endless_mode"]:
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            except aiosqlite.OperationalError:
                pass
                
        await db.execute("""
            CREATE TABLE IF NOT EXISTS user_dynamic_quests (
                user_id INTEGER PRIMARY KEY,
                q1_id TEXT, q1_target INTEGER, q1_prog INTEGER DEFAULT 0,
                q2_id TEXT, q2_target INTEGER, q2_prog INTEGER DEFAULT 0,
                q3_id TEXT, q3_target INTEGER, q3_prog INTEGER DEFAULT 0,
                reset_time REAL DEFAULT 0
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
                booster_hp_mult REAL DEFAULT 1.0,
                hide_in_index INTEGER DEFAULT 0,
                hide_from_ai INTEGER DEFAULT 0
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
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS server_settings (
                id INTEGER PRIMARY KEY,
                luck_mult REAL DEFAULT 1.0,
                luck_end REAL DEFAULT 0,
                cd_mult REAL DEFAULT 1.0,
                cd_end REAL DEFAULT 0,
                last_restock REAL DEFAULT 0,
                last_lb_reward REAL DEFAULT 0,
                last_endless_lb_reward REAL DEFAULT 0,
                coin_mult REAL DEFAULT 1.0,
                coin_end REAL DEFAULT 0,
                xp_mult REAL DEFAULT 1.0,
                xp_end REAL DEFAULT 0
            )
        """)

        # Таблицы Endless Mode
        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_settings (
                id INTEGER PRIMARY KEY,
                is_active INTEGER DEFAULT 1,
                hp_mult REAL DEFAULT 0.15,
                dmg_mult REAL DEFAULT 0.15,
                budget_start INTEGER DEFAULT 5,
                budget_step REAL DEFAULT 3.0
            )
        """)
        await db.execute("INSERT OR IGNORE INTO endless_settings (id) VALUES (1)")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_runs (
                user_id INTEGER PRIMARY KEY,
                wave INTEGER DEFAULT 1,
                team_state TEXT,
                run_points INTEGER DEFAULT 0,
                buff_dmg_waves INTEGER DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_records (
                user_id INTEGER PRIMARY KEY,
                max_wave INTEGER DEFAULT 0,
                season_max_wave INTEGER DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_tiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                min_wave INTEGER,
                max_wave INTEGER,
                rarities TEXT
            )
        """)
        # Базовые тиры
        res_tiers = await db.execute("SELECT id FROM endless_tiers LIMIT 1")
        if not await res_tiers.fetchone():
            await db.execute("INSERT INTO endless_tiers (min_wave, max_wave, rarities) VALUES (1, 10, 'Basic,Uncommon')")
            await db.execute("INSERT INTO endless_tiers (min_wave, max_wave, rarities) VALUES (11, 25, 'Uncommon,Rare,Epic')")
            await db.execute("INSERT INTO endless_tiers (min_wave, max_wave, rarities) VALUES (26, 50, 'Epic,Legendary,Mythic')")
            await db.execute("INSERT INTO endless_tiers (min_wave, max_wave, rarities) VALUES (51, 9999, 'Mythic,Super,Exclusive,Leaderboard')")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wave INTEGER,
                reward_type TEXT,
                amount INTEGER,
                item_id INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_lb_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bracket TEXT,
                reward_type TEXT,
                amount INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                mutation TEXT DEFAULT 'Normal'
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_shop (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                price_shards INTEGER,
                reward_type TEXT,
                amount INTEGER,
                item_id INTEGER
            )
        """)

        # Другие таблицы
        await db.execute("CREATE TABLE IF NOT EXISTS seed_packs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, photo_id TEXT, description TEXT, price INTEGER DEFAULT 2000)")
        await db.execute("CREATE TABLE IF NOT EXISTS seed_pack_cards (pack_id INTEGER, card_id INTEGER, drop_chance REAL, PRIMARY KEY (pack_id, card_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS user_seed_packs (user_id INTEGER, pack_id INTEGER, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, pack_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS shop_items (id INTEGER PRIMARY KEY AUTOINCREMENT, item_type TEXT, name TEXT, price INTEGER, stock INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS admin_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS authorized_signers (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS ranks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, min_trophies INTEGER, difficulty_mult REAL DEFAULT 1.0, reward_mult REAL DEFAULT 1.0)")
        await db.execute("CREATE TABLE IF NOT EXISTS lb_rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, bracket TEXT, reward_type TEXT, amount INTEGER DEFAULT 0, card_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal', lb_type TEXT DEFAULT 'trophies')")
        
        await db.execute("CREATE TABLE IF NOT EXISTS battle_passes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, photo_id TEXT, created_at REAL)")
        await db.execute("CREATE TABLE IF NOT EXISTS bp_levels (id INTEGER PRIMARY KEY AUTOINCREMENT, bp_id INTEGER, level INTEGER, xp_required INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS bp_rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, level_id INTEGER, reward_type TEXT, amount INTEGER DEFAULT 0, card_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal')")
        await db.execute("CREATE TABLE IF NOT EXISTS user_bp (user_id INTEGER, bp_id INTEGER, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 0, is_active INTEGER DEFAULT 0, PRIMARY KEY (user_id, bp_id))")
        await db.execute("CREATE TABLE IF NOT EXISTS user_bp_claims (user_id INTEGER, bp_id INTEGER, level INTEGER, PRIMARY KEY (user_id, bp_id, level))")
        await db.execute("CREATE TABLE IF NOT EXISTS reward_codes (code TEXT PRIMARY KEY, reward_type TEXT, amount INTEGER DEFAULT 0, item_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal', owner_id INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1)")
        await db.execute("CREATE TABLE IF NOT EXISTS craft_recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, target_card_id INTEGER, price INTEGER DEFAULT 0)")
        await db.execute("CREATE TABLE IF NOT EXISTS craft_ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER, card_id INTEGER, amount INTEGER DEFAULT 1)")

        await db.execute("DELETE FROM ranks")
        default_ranks = [
            ("🟤 Bronze I", 0, 0.8, 1.0), ("🟤 Bronze II", 50, 0.85, 1.05), ("🟤 Bronze III", 100, 0.9, 1.1), ("🟤 Bronze IV", 150, 0.95, 1.15),
            ("⚪ Silver I", 200, 1.0, 1.2), ("⚪ Silver II", 300, 1.05, 1.25), ("⚪ Silver III", 400, 1.1, 1.3), ("⚪ Silver IV", 500, 1.15, 1.35),
            ("🟡 Gold I", 650, 1.2, 1.4), ("🟡 Gold II", 800, 1.3, 1.5), ("🟡 Gold III", 950, 1.4, 1.6), ("🟡 Gold IV", 1100, 1.5, 1.7),
            ("🟢 Platina I", 1300, 1.8, 1.8), ("🟢 Platina II", 1500, 2.5, 1.9), ("🟢 Platina III", 1700, 3.2, 2.0), ("🟢 Platina IV", 1900, 4.0, 2.1),
            ("💎 Diamond I", 2200, 5.0, 2.5), ("💎 Diamond II", 2500, 6.5, 2.8), ("💎 Diamond III", 2800, 8.0, 3.2), ("💎 Diamond IV", 3100, 10.0, 3.6),
            ("🔴 Ruby I", 3500, 13.0, 4.0), ("🔴 Ruby II", 4000, 15.0, 4.5), ("🔴 Ruby III", 4500, 17.0, 5.0), ("🔴 Ruby IV", 5000, 20.0, 5.5),
            ("☢️ Uranium I", 5700, 24.0, 6.0), ("☢️ Uranium II", 6500, 28.0, 6.5), ("☢️ Uranium III", 7400, 32.0, 7.0), ("☢️ Uranium IV", 8400, 36.0, 7.5), ("☢️ Uranium V", 9500, 40.0, 8.0),
            ("🌌 Uranium VI", 10000, 50.0, 9.0), ("🌌 Uranium VII", 15000, 60.0, 10.0)
        ]
        for r in default_ranks:
            await db.execute("INSERT INTO ranks (name, min_trophies, difficulty_mult, reward_mult) VALUES (?, ?, ?, ?)", r)

        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        await db.execute("INSERT OR IGNORE INTO server_settings (id) VALUES (1)")
        await db.commit()
    finally:
        await db.close()

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

class AdminBPEdit(StatesGroup):
    select_bp = State()
    edit_menu = State()
    edit_title = State()
    edit_photo = State()

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

class TradeRS(StatesGroup):
    amount = State()

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

class AdminCraftEdit(StatesGroup):
    menu = State()
    edit_price = State()
    add_ing_card = State()
    add_ing_amount = State()

class AdminEndless(StatesGroup):
    settings_input = State()
    milestone_input = State()
    tier_input = State()
    shop_input = State()
    lb_input = State()

async def log_user_action(user_id: int, action: str):
    try:
        await execute_db("INSERT INTO user_action_logs (user_id, action) VALUES (?, ?)", (user_id, action))
    except Exception as e:
        logging.error(f"Failed to log user action: {e}")

def get_display_name(user_data: dict) -> str:
    if user_data.get('username'): 
        return html.escape(f"@{user_data['username']}")
    elif user_data.get('first_name'): 
        return html.escape(user_data['first_name'])
    return f"Player {user_data.get('id', '???')}"

async def get_user_titles_str(user_id: int) -> str:
    titles = []
    user = await fetch_one("SELECT vip_status FROM users WHERE id = ?", (user_id,))
    if user and user.get('vip_status'): titles.append("💎 VIP")
    if await is_admin(user_id): titles.append("👑 Администратор")
    if await is_signer(user_id): titles.append("✍️ Сигнер")
    if titles: return f" [<i>{', '.join(titles)}</i>]"
    return ""

def make_progress_bar(current, total, length=10):
    if total <= 0: return "🟩" * length
    pct = min(1.0, current / total)
    filled = int(pct * length)
    empty = length - filled
    return "🟩" * filled + "⬜" * empty

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
    except: pass

async def log_admin(admin_id: int, action: str):
    await execute_db("INSERT INTO admin_logs (admin_id, action) VALUES (?, ?)", (admin_id, action))
    admin_info = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (admin_id,))
    name = get_display_name(admin_info) if admin_info else f"ID {admin_id}"
    await notify_super_admin(f"Admin: <b>{name}</b> ({admin_id})\nAction: {action}")

async def broadcast_message(text_ru: str, notif_type: str = None, shop_types: set = None):
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
            await bot.send_message(u['id'], text_ru)
            success += 1
            await asyncio.sleep(0.05)
        except: 
            pass
    await notify_super_admin(f"📢 <b>Broadcast complete.</b>\nDelivered: {success}")

def get_main_keyboard(is_adm: bool = False, is_sgn: bool = False):
    kb = [
        [KeyboardButton(text=BTN_DRAW), KeyboardButton(text=BTN_PVE), KeyboardButton(text=BTN_PVP)],
        [KeyboardButton(text=BTN_INV), KeyboardButton(text=BTN_PROF), KeyboardButton(text=BTN_EQ)],
        [KeyboardButton(text=BTN_QUESTS), KeyboardButton(text=BTN_SHOP), KeyboardButton(text=BTN_BP)],
        [KeyboardButton(text=BTN_TOP), KeyboardButton(text=BTN_IDX), KeyboardButton(text=BTN_SEED_PACKS)],
        [KeyboardButton(text=BTN_CRAFT), KeyboardButton(text=BTN_ENDLESS_MAIN)], 
        [KeyboardButton(text=BTN_SET)]
    ]
    
    bottom_row = []
    if is_sgn: bottom_row.append(KeyboardButton(text=BTN_SIGN))
    if is_adm: bottom_row.append(KeyboardButton(text=BTN_ADM))
    if bottom_row: kb.append(bottom_row)
        
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_endless_keyboard(is_adm: bool = False, is_sgn: bool = False):
    kb = [
        [KeyboardButton(text=BTN_E_SHOP), KeyboardButton(text=BTN_E_LB)],
        [KeyboardButton(text=BTN_INV), KeyboardButton(text=BTN_EQ)],
        [KeyboardButton(text=BTN_PROF), KeyboardButton(text=BTN_E_NORM)]
    ]
    bottom_row = []
    if is_sgn: bottom_row.append(KeyboardButton(text=BTN_SIGN))
    if is_adm: bottom_row.append(KeyboardButton(text=BTN_ADM))
    if bottom_row: kb.append(bottom_row)
        
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_user_rank(trophies: int):
    ranks = await fetch_all("SELECT * FROM ranks ORDER BY min_trophies DESC")
    for idx, r in enumerate(ranks):
        if trophies >= r['min_trophies']: 
            res = dict(r)
            res['rank_idx'] = len(ranks) - idx - 1
            return res
    return {"name": "🟤 Bronze I", "difficulty_mult": 0.8, "reward_mult": 1.0, "rank_idx": 0}

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
    if rarity in ['Leaderboard', 'Exclusive', 'Mythic', 'Super', 'Secret']: return True
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
    name = f"{r_em} {c_em} <b>{html.escape(c['name'])}</b>"
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
    return str(uuid.uuid4()).replace('-', '')[:28]

async def clear_fsm_timeout(state: FSMContext, chat_id: int, delay: int = 60):
    await asyncio.sleep(delay)
    curr = await state.get_state()
    if curr in [TradeState.waiting_target.state, PvPState.waiting_target.state]:
        await state.clear()
        try: await bot.send_message(chat_id, "⏳ <i>Время ожидания истекло.</i>")
        except: pass

async def get_card_sources(card_id: int) -> str:
    sources = []
    packs = await fetch_all("SELECT p.title FROM seed_pack_cards spc JOIN seed_packs p ON spc.pack_id = p.id WHERE spc.card_id = ?", (card_id,))
    if packs:
        sources.append("📦 Сид-Паки: " + ", ".join([p['title'] for p in packs]))
    
    c = await fetch_one("SELECT drop_chance, rarity, hide_in_index FROM cards WHERE id = ?", (card_id,))
    if c:
        if c['drop_chance'] > 0 and c['rarity'] not in ['Leaderboard', 'Secret']:
            sources.append("🎲 Гача (/getcard) / Магазин")
        if c['rarity'] == 'Leaderboard':
            sources.append("🏆 Топ игроков (Лидерборд)")
            
    bps = await fetch_all("SELECT bp.title FROM bp_rewards bpr JOIN bp_levels bpl ON bpr.level_id = bpl.id JOIN battle_passes bp ON bpl.bp_id = bp.id WHERE bpr.card_id = ?", (card_id,))
    if bps:
        sources.append("🎟 Батл-Пасс: " + ", ".join(list(set([b['title'] for b in bps]))))
        
    craft = await fetch_one("SELECT id FROM craft_recipes WHERE target_card_id = ?", (card_id,))
    if craft: sources.append("🔨 Мастерская Крафта")

    if not sources:
        return "Невозможно получить (Эксклюзив или Секрет)"
    return "\n".join(f"  └ {s}" for s in sources)

async def generate_dynamic_quests(user_id: int):
    now = time.time()
    db = await get_db_connection()
    try:
        user_q = await db.execute("SELECT * FROM user_dynamic_quests WHERE user_id = ?", (user_id,))
        uq = await user_q.fetchone()
        
        if not uq or uq['reset_time'] < now:
            chosen = random.sample(QUEST_TEMPLATES, 3)
            q1_t = random.randint(chosen[0]['target'][0], chosen[0]['target'][1])
            q2_t = random.randint(chosen[1]['target'][0], chosen[1]['target'][1])
            q3_t = random.randint(chosen[2]['target'][0], chosen[2]['target'][1])
            
            next_hour = (int(now) // 3600 + 1) * 3600
            
            if uq:
                await db.execute("""
                    UPDATE user_dynamic_quests SET 
                    q1_id = ?, q1_target = ?, q1_prog = 0,
                    q2_id = ?, q2_target = ?, q2_prog = 0,
                    q3_id = ?, q3_target = ?, q3_prog = 0,
                    reset_time = ? WHERE user_id = ?
                """, (chosen[0]['id'], q1_t, chosen[1]['id'], q2_t, chosen[2]['id'], q3_t, next_hour, user_id))
            else:
                await db.execute("""
                    INSERT INTO user_dynamic_quests (user_id, q1_id, q1_target, q2_id, q2_target, q3_id, q3_target, reset_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, chosen[0]['id'], q1_t, chosen[1]['id'], q2_t, chosen[2]['id'], q3_t, next_hour))
            await db.commit()
    finally:
        await db.close()

async def add_quest_progress_new(user_id: int, quest_type: str, amount: int = 1):
    await generate_dynamic_quests(user_id)
    db = await get_db_connection()
    try:
        user_q = await db.execute("SELECT * FROM user_dynamic_quests WHERE user_id = ?", (user_id,))
        uq = await user_q.fetchone()
        if not uq: return
        
        uq_dict = dict(uq)
        updated = False
        
        for i in range(1, 4):
            if uq_dict[f'q{i}_id'] == quest_type and uq_dict[f'q{i}_prog'] < uq_dict[f'q{i}_target']:
                new_prog = min(uq_dict[f'q{i}_target'], uq_dict[f'q{i}_prog'] + amount)
                await db.execute(f"UPDATE user_dynamic_quests SET q{i}_prog = ? WHERE user_id = ?", (new_prog, user_id))
                uq_dict[f'q{i}_prog'] = new_prog
                updated = True
                
        if updated:
            if uq_dict['q1_prog'] >= uq_dict['q1_target'] and uq_dict['q2_prog'] >= uq_dict['q2_target'] and uq_dict['q3_prog'] >= uq_dict['q3_target']:
                user = await fetch_one("SELECT notif_quests FROM users WHERE id = ?", (user_id,))
                
                await db.execute("UPDATE users SET coins = coins + 1500, total_coins = total_coins + 1500 WHERE id = ?", (user_id,))
                next_hour = (int(time.time()) // 3600 + 1) * 3600
                await db.execute("UPDATE user_dynamic_quests SET reset_time = ? WHERE user_id = ?", (next_hour, user_id))
                
                packs = await fetch_all("SELECT id, title FROM seed_packs")
                pack_reward_text = ""
                if packs:
                    gift_pack = random.choice(packs)
                    await db.execute("""
                        INSERT INTO user_seed_packs (user_id, pack_id, count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + 1
                    """, (user_id, gift_pack['id']))
                    pack_reward_text = f"\n📦 А также вы получили Сид-Пак: <b>{gift_pack['title']}</b> (1 шт.)!"
                
                if user and user['notif_quests'] == 1:
                    try:
                        msg = f"🎉 <b>ПОЗДРАВЛЯЕМ!</b>\nВы выполнили все задания этого часа и получили <b>1500 💰 Шекелей</b>!{pack_reward_text}\nНовые квесты появятся в начале следующего часа!"
                        await bot.send_message(user_id, msg)
                    except: 
                        pass
        await db.commit()
    finally:
        await db.close()

async def calculate_chance_weights(luck_mult: float = 1.0, user_luck: float = 1.0):
    query = """
        SELECT * FROM cards 
        WHERE drop_chance > 0 
        AND rarity NOT IN ('Leaderboard', 'Secret')
        AND id NOT IN (SELECT card_id FROM seed_pack_cards)
    """
    all_cards = await fetch_all(query)
    if not all_cards: return [], 0
    total_weight = 0
    weights_dict = {}
    for c in all_cards:
        weight = c['drop_chance']
        if weight < 15.0: weight *= (luck_mult * user_luck)
        weights_dict[c['id']] = weight
        total_weight += weight
    return weights_dict, total_weight

async def give_multiple_cards(user_id: int, count: int) -> list:
    luck_mult, _ = await get_active_events()
    user = await fetch_one("SELECT * FROM users WHERE id=?", (user_id,))
    
    user_luck = 1.0
    if user and user.get('vip_status'): user_luck *= 1.3
    if user and user.get('perm_1_5x_luck'): user_luck *= 1.5
    
    pm = user['pity_mythic'] if user else 0
    ps = user['pity_super'] if user else 0

    query = """
        SELECT * FROM cards 
        WHERE drop_chance > 0 
        AND rarity NOT IN ('Leaderboard', 'Secret')
        AND id NOT IN (SELECT card_id FROM seed_pack_cards)
    """
    all_cards = await fetch_all(query)
    if not all_cards: return []
    
    super_cards = [c for c in all_cards if c['rarity'] == 'Super']
    mythic_cards = [c for c in all_cards if c['rarity'] == 'Mythic']
    weights = [c['drop_chance'] * (luck_mult * user_luck if c['drop_chance'] < 15.0 else 1.0) for c in all_cards]
    
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

async def restock_shop():
    await execute_db("DELETE FROM shop_items")
    db = await get_db_connection()
    spawned_types = set()
    try:
        spawned_any = False
        for p_id, p_name_ru, p_price, p_max, p_chance in SHOP_PACKAGES:
            if random.random() <= p_chance:
                stock = random.randint(1, p_max)
                await db.execute("INSERT INTO shop_items (item_type, name, price, stock) VALUES (?, ?, ?, ?)", (p_id, p_name_ru, p_price, stock))
                spawned_any = True
                spawned_types.add(p_id)
                
        await db.execute("UPDATE server_settings SET last_restock = ? WHERE id = 1", (time.time(),))
        await db.commit()
    finally:
        await db.close()
        
    if spawned_any:
        msg_ru = "🛒 <b>МАГАЗИНЫ ОБНОВЛЕНЫ!</b>\nЗавезли свежие наборы карт. Количество ограничено, успей купить!"
        asyncio.create_task(broadcast_message(msg_ru, notif_type="notif_shop", shop_types=spawned_types))

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

async def leaderboard_rewards_task():
    while True:
        try:
            settings = await fetch_one("SELECT last_lb_reward, last_endless_lb_reward FROM server_settings WHERE id = 1")
            now = time.time()
            
            # Обычный Лидерборд (раз в 2 дня)
            if settings and (now - settings['last_lb_reward'] >= 2 * 24 * 3600):
                for lb_type in ['trophies', 'coins', 'cards']:
                    if lb_type == 'trophies':
                        top_users = await fetch_all("SELECT id, trophies as score, username, first_name FROM users WHERE id != ? ORDER BY trophies DESC LIMIT 20", (SUPER_ADMIN_ID,))
                    elif lb_type == 'coins':
                        top_users = await fetch_all("SELECT id, total_coins as score, username, first_name FROM users WHERE id != ? ORDER BY total_coins DESC LIMIT 20", (SUPER_ADMIN_ID,))
                    else:
                        top_users = await fetch_all("""
                            SELECT u.id, SUM(i.count) as score, u.username, u.first_name 
                            FROM users u JOIN inventory i ON u.id = i.user_id 
                            WHERE u.id != ? GROUP BY u.id ORDER BY score DESC LIMIT 20
                        """, (SUPER_ADMIN_ID,))

                    if top_users:
                        for idx, user in enumerate(top_users):
                            pos = idx + 1
                            if pos == 1: bracket = "1"
                            elif pos == 2: bracket = "2"
                            elif pos == 3: bracket = "3"
                            elif pos <= 9: bracket = "4_9"
                            else: bracket = "10_20"
                            
                            rewards = await fetch_all("SELECT * FROM lb_rewards WHERE bracket = ? AND lb_type = ?", (bracket, lb_type))
                            reward_msgs_ru = []
                            for r in rewards:
                                if r['reward_type'] == 'shekels':
                                    await execute_db("UPDATE users SET coins = coins + ?, total_coins = total_coins + ? WHERE id = ?", (r['amount'], r['amount'], user['id']))
                                    reward_msgs_ru.append(f"💰 {r['amount']} Шекелей")
                                elif r['reward_type'] == 'card':
                                    c_info = await fetch_one("SELECT name, rarity FROM cards WHERE id = ?", (r['card_id'],))
                                    if c_info:
                                        _, serial, _ = await give_card_to_user(user['id'], r['card_id'], r['mutation'], c_info['rarity'])
                                        mut_str = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                                        s_str = f" [#{serial:04d}]" if serial > 0 else ""
                                        reward_msgs_ru.append(f"🃏 {mut_str} {c_info['name']}{s_str}")
                                        
                            if rewards:
                                lb_name_ru = "Кубки (Сезон)" if lb_type == 'trophies' else ("Шекели (Все время)" if lb_type == 'coins' else "Карты (Все время)")
                                msg_text = f"🏆 <b>ГРАНДИОЗНАЯ НАГРАДА ЗА ТОП ИГРОКОВ ({lb_name_ru})!</b> 🏆\n\nПоздравляем! Вы заняли <b>{pos} место</b> в мире!\n\n🎁 <b>Награда:</b>\n" + "\n".join([f"🔸 {m}" for m in reward_msgs_ru])
                                try: await bot.send_message(user['id'], msg_text)
                                except: pass
                
                await execute_db("UPDATE server_settings SET last_lb_reward = ? WHERE id = 1", (now,))
                
            # Бесконечный Лидерборд (раз в 3 дня)
            if settings and (now - settings['last_endless_lb_reward'] >= 3 * 24 * 3600):
                top_users = await fetch_all("""
                    SELECT u.id, e.season_max_wave as score, u.username, u.first_name 
                    FROM endless_records e JOIN users u ON e.user_id = u.id 
                    WHERE e.season_max_wave > 0 AND u.id != ? 
                    ORDER BY e.season_max_wave DESC LIMIT 20
                """, (SUPER_ADMIN_ID,))
                
                if top_users:
                    for idx, user in enumerate(top_users):
                        pos = idx + 1
                        if pos == 1: bracket = "1"
                        elif pos == 2: bracket = "2"
                        elif pos == 3: bracket = "3"
                        elif pos <= 9: bracket = "4_9"
                        else: bracket = "10_20"
                        
                        rewards = await fetch_all("SELECT * FROM endless_lb_rewards WHERE bracket = ?", (bracket,))
                        reward_msgs_ru = []
                        for r in rewards:
                            if r['reward_type'] == 'shekels':
                                await execute_db("UPDATE users SET coins = coins + ?, total_coins = total_coins + ? WHERE id = ?", (r['amount'], r['amount'], user['id']))
                                reward_msgs_ru.append(f"💰 {r['amount']} Шекелей")
                            elif r['reward_type'] == 'shards':
                                await execute_db("UPDATE users SET soul_shards = soul_shards + ? WHERE id = ?", (r['amount'], user['id']))
                                reward_msgs_ru.append(f"🔮 {r['amount']} Осколков Душ")
                            elif r['reward_type'] == 'r_bucks':
                                await execute_db("UPDATE users SET r_bucks = r_bucks + ? WHERE id = ?", (r['amount'], user['id']))
                                reward_msgs_ru.append(f"💎 {r['amount']} R$")
                            elif r['reward_type'] == 'card':
                                c_info = await fetch_one("SELECT name, rarity FROM cards WHERE id = ?", (r['item_id'],))
                                if c_info:
                                    _, serial, _ = await give_card_to_user(user['id'], r['item_id'], r['mutation'], c_info['rarity'])
                                    mut_str = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                                    s_str = f" [#{serial:04d}]" if serial > 0 else ""
                                    reward_msgs_ru.append(f"🃏 {mut_str} {c_info['name']}{s_str}")
                                    
                        if rewards:
                            msg_text = f"🏆 <b>ЗАВЕРШЕНИЕ СЕЗОНА ENDLESS MODE!</b> 🏆\n\nПоздравляем! Вы заняли <b>{pos} место</b> в мире (Макс. волна: {user['score']})!\n\n🎁 <b>Награда:</b>\n" + "\n".join([f"🔸 {m}" for m in reward_msgs_ru])
                            try: await bot.send_message(user['id'], msg_text)
                            except: pass
                            
                # Сброс сезона
                await execute_db("UPDATE endless_records SET season_max_wave = 0")
                await execute_db("DELETE FROM endless_runs")
                await execute_db("UPDATE server_settings SET last_endless_lb_reward = ? WHERE id = 1", (now,))
                
                asyncio.create_task(broadcast_message("🔄 <b>Сезон Endless Mode завершен!</b> Награды за Топ-20 выданы. Новый сезон начался!", notif_type="notif_events"))
                
        except Exception as e:
            logging.error(f"LB Rewards error: {e}")
        await asyncio.sleep(600)

async def auto_backup_db():
    while True:
        await asyncio.sleep(4 * 3600) 
        try:
            file = FSInputFile(DB_NAME)
            await bot.send_document(SUPER_ADMIN_ID, file, caption="📦 Автоматический бэкап БД (каждые 4 часа).")
        except Exception as e:
            logging.error(f"Auto DB Backup error: {e}")

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
    
    await log_user_action(message.from_user.id, "Открыл главное меню (/start)")

    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    
    user = await fetch_one("SELECT is_endless_mode FROM users WHERE id = ?", (message.from_user.id,))
    is_e = user['is_endless_mode'] if user else 0
    kb = get_endless_keyboard(adm, sgn) if is_e else get_main_keyboard(adm, sgn)
    
    text = (
        "👋 <b>Добро пожаловать в Card Battle Bot!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Собери свою колоду уникальных юнитов, участвуй в ивентах и поднимай кубки на арене!\n\n"
        "📖 <b>ОГРОМНОЕ РУКОВОДСТВО ПО ИГРЕ:</b> /help\n"
        "📞 Тех.поддержка: @ggtdcards_support\n"
        "📰 Новости: @ggtdcardsnews\n\n"
        "👇 <i>Используй красивое меню снизу для навигации:</i>"
    )
    await message.answer(text, reply_markup=kb)

@dp.message(F.text == BTN_ENDLESS_MAIN)
async def cmd_switch_to_endless(message: types.Message):
    if await check_ban(message.from_user.id): return
    await execute_db("UPDATE users SET is_endless_mode = 1 WHERE id = ?", (message.from_user.id,))
    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    
    settings = await fetch_one("SELECT is_active FROM endless_settings WHERE id = 1")
    if not settings or settings['is_active'] == 0:
        return await message.answer("⚠️ В данный момент Бесконечный Режим отключен администратором.", reply_markup=get_main_keyboard(adm, sgn))
        
    await message.answer("🔄 Переключение на <b>ENDLESS MODE</b>...", reply_markup=get_endless_keyboard(adm, sgn))
    await show_endless_hub(message.from_user.id, message)

@dp.message(F.text == BTN_E_NORM)
async def cmd_switch_to_normal(message: types.Message):
    if await check_ban(message.from_user.id): return
    await execute_db("UPDATE users SET is_endless_mode = 0 WHERE id = ?", (message.from_user.id,))
    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    await message.answer("🔄 Возврат в <b>ОБЫЧНЫЙ РЕЖИМ</b>...", reply_markup=get_main_keyboard(adm, sgn))

async def show_endless_hub(user_id: int, message_or_call):
    user = await fetch_one("SELECT soul_shards FROM users WHERE id = ?", (user_id,))
    rec = await fetch_one("SELECT max_wave, season_max_wave FROM endless_records WHERE user_id = ?", (user_id,))
    run = await fetch_one("SELECT wave, run_points FROM endless_runs WHERE user_id = ?", (user_id,))
    
    s_shards = user['soul_shards'] if user else 0
    m_wave = rec['max_wave'] if rec else 0
    s_wave = rec['season_max_wave'] if rec else 0
    
    text = (
        "♾ <b>ENDLESS MODE (БЕСКОНЕЧНЫЙ РЕЖИМ)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔮 <b>Ваши Осколки Душ:</b> {s_shards}\n"
        f"🏆 <b>Макс. Волна (Сезон):</b> {s_wave}\n"
        f"🏅 <b>Рекорд (Всё время):</b> {m_wave}\n\n"
    )
    
    kb = []
    if run:
        text += f"⚠️ У вас есть незаконченный забег! Вы находитесь на <b>Волне {run['wave']}</b>.\nНакоплено Очков Душ: {run['run_points']}."
        kb.append([InlineKeyboardButton(text="▶️ Продолжить забег", callback_data="endless_continue")])
        kb.append([InlineKeyboardButton(text="🛑 Завершить досрочно", callback_data="endless_abort")])
    else:
        text += "Соберите лучшую команду и продержитесь как можно дольше против бесконечных волн врагов! Статы врагов растут с каждой волной."
        kb.append([InlineKeyboardButton(text="⚔️ НАЧАТЬ ЗАБЕГ", callback_data="endless_start")])
        
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.edit_text(text, reply_markup=markup)
    else:
        await message_or_call.answer(text, reply_markup=markup)

@dp.callback_query(F.data == "endless_start")
async def cb_endless_start(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id in active_combats or user_id in user_trades:
        return await callback.answer("❌ Заняты!", show_alert=True)
        
    team = await get_team_data(user_id)
    if not team:
        return await callback.answer("❌ Боевая колода пуста! Экипируйте карты.", show_alert=True)
        
    team_json = json.dumps(team)
    await execute_db("INSERT OR REPLACE INTO endless_runs (user_id, wave, team_state, run_points, buff_dmg_waves) VALUES (?, 1, ?, 0, 0)", (user_id, team_json))
    await callback.answer("Забег начат!")
    await show_endless_midrun_menu(user_id, callback)

@dp.callback_query(F.data == "endless_continue")
async def cb_endless_continue(callback: types.CallbackQuery):
    await show_endless_midrun_menu(callback.from_user.id, callback)
    await callback.answer()

@dp.callback_query(F.data == "endless_abort")
async def cb_endless_abort(callback: types.CallbackQuery):
    await execute_db("DELETE FROM endless_runs WHERE user_id = ?", (callback.from_user.id,))
    await callback.answer("Забег завершен.", show_alert=True)
    await show_endless_hub(callback.from_user.id, callback)

@dp.message(F.text == BTN_E_SHOP)
async def cmd_endless_shop(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT soul_shards FROM users WHERE id = ?", (message.from_user.id,))
    items = await fetch_all("SELECT * FROM endless_shop")
    
    text = f"🛒 <b>ENDLESS SHOP</b>\nВаш баланс: <b>{user['soul_shards']} 🔮 Осколков Душ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nЗдесь можно приобрести уникальные предметы за валюту бесконечного режима.\n\n"
    
    kb = []
    if not items:
        text += "<i>Магазин пока пуст.</i>"
    else:
        for i, item in enumerate(items, 1):
            text += f"📦 <b>{item['name']}</b>\n      └ 💵 Цена: <b>{item['price_shards']} 🔮</b>\n\n"
            kb.append([InlineKeyboardButton(text=f"Купить: {item['name']}", callback_data=f"buy_eshop_{item['id']}")])
            
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_eshop_"))
async def cb_buy_eshop(callback: types.CallbackQuery):
    item_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    item = await fetch_one("SELECT * FROM endless_shop WHERE id = ?", (item_id,))
    user = await fetch_one("SELECT soul_shards FROM users WHERE id = ?", (user_id,))
    if not item: return await callback.answer("Товар не найден", show_alert=True)
    
    if user['soul_shards'] < item['price_shards']:
        return await callback.answer("❌ Недостаточно Осколков Душ!", show_alert=True)
        
    await execute_db("UPDATE users SET soul_shards = soul_shards - ? WHERE id = ?", (item['price_shards'], user_id))
    
    if item['reward_type'] == 'card':
        c_info = await fetch_one("SELECT name, rarity FROM cards WHERE id = ?", (item['item_id'],))
        _, serial, _ = await give_card_to_user(user_id, item['item_id'], "Normal", c_info['rarity'])
        await callback.answer(f"✅ Вы купили {c_info['name']}!", show_alert=True)
    elif item['reward_type'] == 'pack':
        await execute_db("INSERT INTO user_seed_packs (user_id, pack_id, count) VALUES (?, ?, 1) ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + 1", (user_id, item['item_id']))
        await callback.answer(f"✅ Вы купили Сид-Пак!", show_alert=True)
    elif item['reward_type'] == 'r_bucks':
        await execute_db("UPDATE users SET r_bucks = r_bucks + ? WHERE id = ?", (item['amount'], user_id))
        await callback.answer(f"✅ Вы купили {item['amount']} R$!", show_alert=True)
        
    # Обновление UI магазина
    user_upd = await fetch_one("SELECT soul_shards FROM users WHERE id = ?", (user_id,))
    text = f"🛒 <b>ENDLESS SHOP</b>\nВаш баланс: <b>{user_upd['soul_shards']} 🔮 Осколков Душ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nЗдесь можно приобрести уникальные предметы за валюту бесконечного режима.\n\n"
    items = await fetch_all("SELECT * FROM endless_shop")
    kb = []
    for i, it in enumerate(items, 1):
        text += f"📦 <b>{it['name']}</b>\n      └ 💵 Цена: <b>{it['price_shards']} 🔮</b>\n\n"
        kb.append([InlineKeyboardButton(text=f"Купить: {it['name']}", callback_data=f"buy_eshop_{it['id']}")])
    try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except: pass

@dp.message(F.text == BTN_E_LB)
async def cmd_endless_lb(message: types.Message):
    if await check_ban(message.from_user.id): return
    top_users = await fetch_all("""
        SELECT u.id, e.season_max_wave as score, u.username, u.first_name 
        FROM endless_records e JOIN users u ON e.user_id = u.id 
        WHERE e.season_max_wave > 0 AND u.id != ? 
        ORDER BY e.season_max_wave DESC LIMIT 20
    """, (SUPER_ADMIN_ID,))
    
    text = "🏆 <b>МИРОВОЙ РЕЙТИНГ: ENDLESS MODE (Топ-20 Сезона)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if not top_users:
        text += "<i>В этом сезоне пока никто не играл.</i>"
    else:
        for i, u in enumerate(top_users, 1):
            name = get_display_name(u)
            med = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
            text += f"{med} <b>{i}. {name}</b> — Волна {u['score']}\n"
            
    text += "\n🎁 <b>Награды в конце сезона (каждые 3 дня):</b>\n"
    brackets = ["1", "2", "3", "4_9", "10_20"]
    b_names = {"1": "🥇 1 место", "2": "🥈 2 место", "3": "🥉 3 место", "4_9": "🏅 4-9 места", "10_20": "🎖 10-20 места"}
    
    for b in brackets:
        b_rewards = await fetch_all("SELECT * FROM endless_lb_rewards WHERE bracket = ?", (b,))
        if b_rewards:
            r_strs = []
            for r in b_rewards:
                if r['reward_type'] == 'shekels': r_strs.append(f"{r['amount']} 💰")
                elif r['reward_type'] == 'shards': r_strs.append(f"{r['amount']} 🔮")
                elif r['reward_type'] == 'r_bucks': r_strs.append(f"{r['amount']} 💎")
                elif r['reward_type'] == 'card':
                    c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['item_id'],))
                    mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                    r_strs.append(f"{mut} {c['name'] if c else 'Unknown'}")
            text += f"└ {b_names[b]}: {', '.join(r_strs)}\n"
            
    await message.answer(text)

async def generate_endless_wave(wave: int, settings: dict):
    budget = settings['budget_start'] + (wave - 1) * settings['budget_step']
    
    tier = await fetch_one("SELECT rarities FROM endless_tiers WHERE ? BETWEEN min_wave AND max_wave", (wave,))
    if not tier:
        tier = await fetch_one("SELECT rarities FROM endless_tiers ORDER BY max_wave DESC LIMIT 1")
    allowed_rarities = [r.strip() for r in tier['rarities'].split(',')] if tier else list(ENDLESS_RARITY_COST.keys())
    
    pool = await fetch_all("SELECT * FROM cards WHERE rarity IN ({}) AND hide_from_ai = 0 AND rarity != 'Secret'".format(','.join('?' * len(allowed_rarities))), allowed_rarities)
    if not pool: pool = await fetch_all("SELECT * FROM cards WHERE hide_from_ai = 0 AND rarity != 'Secret'")
    
    team_selection = []
    used_budget = 0
    max_slots = 5
    is_boss_wave = (wave % 10 == 0)
    
    if is_boss_wave: max_slots = 1
    
    while len(team_selection) < max_slots:
        affordable = [c for c in pool if ENDLESS_RARITY_COST.get(c['rarity'], 1) <= (budget - used_budget)]
        if not affordable:
            if not team_selection and pool:
                team_selection.append(random.choice(pool))
            break
            
        chosen = random.choice(affordable)
        team_selection.append(chosen)
        used_budget += ENDLESS_RARITY_COST.get(chosen['rarity'], 1)
        
    team_copies = []
    for c in team_selection:
        c_copy = dict(c)
        c_copy['damage'] = int(c_copy['damage'] * (1 + (wave - 1) * settings['dmg_mult']))
        c_copy['hp'] = int(c_copy['hp'] * (1 + (wave - 1) * settings['hp_mult']))
        
        if is_boss_wave:
            c_copy['hp'] *= 5
            c_copy['damage'] = int(c_copy['damage'] * 1.5)
            c_copy['elite_mutator'] = "boss"
        elif wave > 15:
            mutators = ['regen', 'armored', 'enraged']
            if random.random() < 0.3:
                c_copy['elite_mutator'] = random.choice(mutators)
                
        c_copy['max_hp'] = c_copy['hp']
        c_copy['burn'] = 0
        c_copy['dmg_buff'] = 0
        c_copy['serial_number'] = 0
        c_copy['signed_by'] = 0
        c_copy['heal_power_mult'] = 1.0  
        c_copy['trauma'] = 0
        c_copy['mutation'] = "Normal"
        
        mut_chance = random.random()
        rainbow_prob = min(0.1, settings['mut_base'] + wave * settings['mut_step'])
        gold_prob = min(0.3, settings['mut_base'] + wave * settings['mut_step'] * 2)
        if mut_chance < rainbow_prob:
            c_copy['mutation'] = "Rainbow"
            c_copy['damage'] = int(c_copy['damage'] * 1.2)
            c_copy['hp'] = int(c_copy['hp'] * 1.2)
            c_copy['max_hp'] = c_copy['hp']
        elif mut_chance < rainbow_prob + gold_prob:
            c_copy['mutation'] = "Gold"
            c_copy['damage'] = int(c_copy['damage'] * 1.1)
            c_copy['hp'] = int(c_copy['hp'] * 1.1)
            c_copy['max_hp'] = c_copy['hp']
            
        team_copies.append(c_copy)
        
    return team_copies

async def show_endless_midrun_menu(user_id: int, message_or_call):
    run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ?", (user_id,))
    if not run: return
    
    team = json.loads(run['team_state'])
    alive = [c for c in team if c['hp'] > 0]
    dead = [c for c in team if c['hp'] <= 0]
    
    text = (
        f"♾ <b>БЕСКОНЕЧНЫЙ ЗАБЕГ: ПЕРЕРЫВ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Текущая волна: <b>{run['wave']}</b>\n"
        f"Ваши Очки Душ (для баффов): <b>{run['run_points']}</b>\n"
        f"Активный бафф урона (Волн): <b>{run['buff_dmg_waves']}</b>\n\n"
        f"<b>Ваша команда:</b>\n"
    )
    for c in team:
        st = "💀 Мертв" if c['hp'] <= 0 else f"❤️ {c['hp']}/{c['max_hp']}"
        text += f"• {c['name']} - {st}\n"
        
    kb = []
    kb.append([InlineKeyboardButton(text=f"▶️ В БОЙ (Волна {run['wave']})", callback_data=f"er_fight_{run['wave']}")])
    
    if run['run_points'] >= 50 and any(c['hp'] < c['max_hp'] and c['hp'] > 0 for c in team):
        kb.append([InlineKeyboardButton(text="❤️ Отхил живых на 30% (50 ОД)", callback_data="er_heal")])
    if run['run_points'] >= 150 and dead:
        kb.append([InlineKeyboardButton(text="💉 Воскресить юнита (150 ОД)", callback_data="er_revive")])
    if run['run_points'] >= 100:
        kb.append([InlineKeyboardButton(text="⚔️ Урон +50% на 3 волны (100 ОД)", callback_data="er_buff")])
        
    kb.append([InlineKeyboardButton(text="⏸ В хаб (Сохранить)", callback_data="er_pause")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    if isinstance(message_or_call, types.CallbackQuery):
        try: await message_or_call.message.edit_text(text, reply_markup=markup)
        except: pass
    else:
        await message_or_call.answer(text, reply_markup=markup)

@dp.callback_query(F.data == "er_pause")
async def er_pause(callback: types.CallbackQuery):
    await show_endless_hub(callback.from_user.id, callback)
    await callback.answer("Прогресс сохранен.")

@dp.callback_query(F.data == "er_heal")
async def er_heal(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ?", (user_id,))
    if not run or run['run_points'] < 50: return await callback.answer("Ошибка или нехватка очков!", show_alert=True)
    
    team = json.loads(run['team_state'])
    for c in team:
        if c['hp'] > 0:
            c['hp'] = min(c['max_hp'], int(c['hp'] + c['max_hp'] * 0.3))
            
    await execute_db("UPDATE endless_runs SET team_state = ?, run_points = run_points - 50 WHERE user_id = ?", (json.dumps(team), user_id))
    await callback.answer("Команда исцелена на 30%!")
    await show_endless_midrun_menu(user_id, callback)

@dp.callback_query(F.data == "er_buff")
async def er_buff(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ?", (user_id,))
    if not run or run['run_points'] < 100: return await callback.answer("Ошибка или нехватка очков!", show_alert=True)
    
    await execute_db("UPDATE endless_runs SET buff_dmg_waves = buff_dmg_waves + 3, run_points = run_points - 100 WHERE user_id = ?", (user_id,))
    await callback.answer("Бафф на урон применен!")
    await show_endless_midrun_menu(user_id, callback)

@dp.callback_query(F.data == "er_revive")
async def er_revive(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ?", (user_id,))
    if not run or run['run_points'] < 150: return await callback.answer("Ошибка или нехватка очков!", show_alert=True)
    
    team = json.loads(run['team_state'])
    dead = [i for i, c in enumerate(team) if c['hp'] <= 0]
    if not dead: return await callback.answer("Нет мертвых юнитов!")
    
    idx = dead[0] 
    team[idx]['hp'] = int(team[idx]['max_hp'] * 0.5)
    
    await execute_db("UPDATE endless_runs SET team_state = ?, run_points = run_points - 150 WHERE user_id = ?", (json.dumps(team), user_id))
    await callback.answer(f"{team[idx]['name']} воскрешен!")
    await show_endless_midrun_menu(user_id, callback)

def format_combat_team_vertical(team):
    if not team: return "<i>Все мертвы</i>"
    res = []
    for c in team:
        if c['hp'] <= 0:
            res.append(f"💀 <s>{html.escape(c['name'])}</s>")
            continue
        status = ""
        if c.get('mutation') == 'Rainbow': status += "🌈"
        elif c.get('mutation') == 'Gold': status += "⭐"
        if c.get('burn', 0) > 0: status += "🔥"
        if c.get('dmg_buff', 0) > 0: status += "✨"
        if c['class_type'] == 'Booster': status += "🔋"
        if c['class_type'] == 'Healer': status += "💗"
        if c.get('elite_mutator') == 'boss': status += "👹"
        if c.get('elite_mutator') == 'regen': status += "🩸"
        if c.get('elite_mutator') == 'armored': status += "🛡"
        if c.get('elite_mutator') == 'enraged': status += "💢"
        
        s_str = f" [#{c['serial_number']:04d}]" if c.get('serial_number', 0) > 0 else ""
        sgn_str = ""
        if c.get('signed_by', 0) > 0:
            s_name = c.get('signer_name') or f"ID:{c['signed_by']}"
            sgn_str = f" ✍️ Sign: {s_name}"
            
        if c['class_type'] == 'Healer':
            heal_val = int((c['damage'] + c.get('dmg_buff', 0)) * c.get('heal_power_mult', 1.0))
            res.append(f"• {html.escape(c['name'])}{s_str}{sgn_str}{status} (💗{heal_val} | ❤️{c['hp']}/{c['max_hp']})")
        else:
            dmg = c['damage'] + c.get('dmg_buff', 0)
            res.append(f"• {html.escape(c['name'])}{s_str}{sgn_str}{status} (⚔️{dmg} | ❤️{c['hp']}/{c['max_hp']})")
    return "\n".join(res)

def build_battle_header(p1_name, t1, p2_name, t2):
    return (
        f"⚔️ <b>АРЕНА: БИТВА</b> ⚔️\n━━━━━━━━━━━━━━━━━━━━━━━━\n🔵 <b>Команда {p1_name}:</b>\n{format_combat_team_vertical(t1)}\n\n🔴 <b>Команда {p2_name}:</b>\n{format_combat_team_vertical(t2)}\n━━━━━━━━━━━━━━━━━━━━━━━━\n📜 <b>Лог боя:</b>\n"
    )

def add_dual_log(log1, log2, text_ru):
    if log1 is not None: log1.append(text_ru)
    if log2 is not None: log2.append(text_ru)

def apply_boosters(team, team_name, log1, log2):
    boosters = [c for c in team if c['class_type'] == 'Booster']
    if not boosters: return
    for b in boosters:
        d_mult = b['booster_dmg_mult']
        h_mult = b['booster_hp_mult']
        add_dual_log(log1, log2, f"✨ <b>{team_name}:</b> Бустер <b>{html.escape(b['name'])}</b> усиливает команду! (Урон x{d_mult}, ХП x{h_mult})")
        for c in team:
            bonus_hp = int(c['hp'] * h_mult) - c['hp']
            if bonus_hp > 0:
                c['hp'] += bonus_hp
                c['max_hp'] += bonus_hp
            if c['class_type'] != 'Booster':
                c['dmg_buff'] = c.get('dmg_buff', 0) + int(c['damage'] * d_mult) - c['damage']

async def process_turn_start_effects(team, team_name, log1, log2):
    for c in team:
        if c['hp'] <= 0: continue
        
        if c.get('elite_mutator') == 'regen':
            heal = int(c['max_hp'] * 0.05)
            c['hp'] = min(c['max_hp'], c['hp'] + heal)
            add_dual_log(log1, log2, f"🩸 {team_name}: <b>{html.escape(c['name'])}</b> регенерирует {heal} HP!")
            
        if c.get('burn', 0) > 0:
            c['hp'] -= c['burn']
            ru_str = f"🔥 {team_name}: <b>{html.escape(c['name'])}</b> получает {c['burn']} урона от горения!"
            if c['hp'] <= 0:
                c['hp'] = 0
                ru_str += " ☠️ <i>Сгорел дотла!</i>"
            add_dual_log(log1, log2, ru_str)
            c['burn'] = 0

async def execute_turn(atk_team, def_team, atk_name, def_name, log1, log2, force_attacker=None, force_target=None):
    await process_turn_start_effects(atk_team, atk_name, log1, log2)
    atk_alive = [c for c in atk_team if c['hp'] > 0]
    def_alive = [c for c in def_team if c['hp'] > 0]
    heals = 0
    if not atk_alive or not def_alive: return False, heals
    
    if force_attacker and force_attacker['hp'] > 0 and force_attacker in atk_alive:
        atk = force_attacker
    else:
        atk = random.choice(atk_alive)
        
    base_dmg = atk['damage'] + atk.get('dmg_buff', 0)
    
    if atk.get('elite_mutator') == 'enraged' and atk['hp'] < atk['max_hp'] * 0.3:
        base_dmg *= 2
        add_dual_log(log1, log2, f"💢 {atk_name}: <b>{html.escape(atk['name'])}</b> в ярости (x2 урон)!")
        
    c_type = atk['class_type']
    dead_ru = " ☠️ <i>Мертв!</i>"
    
    if c_type == "Booster":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
        
        dmg = max(10, int(target['max_hp'] * 0.1))
        if target.get('elite_mutator') == 'armored': dmg = int(dmg * 0.7)
        
        target['hp'] -= dmg
        ru_str = f"🔋 {atk_name}: <b>{html.escape(atk['name'])}</b> пускает заряд в <b>{html.escape(target['name'])}</b> на {dmg}!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
        add_dual_log(log1, log2, ru_str)
        
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
                
            ru_str = f"💗 {atk_name}: <b>{html.escape(atk['name'])}</b> исцеляет союзника <b>{html.escape(target['name'])}</b> на {heal_amount} HP! (Эффективность: {int(curr_mult * 100)}%)"
            add_dual_log(log1, log2, ru_str)
            heals += 1
            
            atk['heal_power_mult'] = max(0.0, curr_mult - 0.03)
        else:
            if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
            else: target = random.choice(def_alive)
            
            dmg = max(5, int(base_dmg * 0.2))
            if target.get('elite_mutator') == 'armored': dmg = int(dmg * 0.7)
            target['hp'] -= dmg
            ru_str = f"🎯 {atk_name}: Одинокий Хилер <b>{html.escape(atk['name'])}</b> бьет <b>{html.escape(target['name'])}</b> на {dmg}!"
            if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
            add_dual_log(log1, log2, ru_str)
        
    elif c_type == "AOE":
        ru_str = f"🌪 {atk_name}: <b>{html.escape(atk['name'])}</b> бьет по всем!"
        for d in def_alive:
            dmg = base_dmg
            if d.get('elite_mutator') == 'armored': dmg = int(dmg * 0.5)
            d['hp'] -= dmg
            if d['hp'] <= 0:
                d['hp'] = 0
                ru_str += f" ☠️ <i>{html.escape(d['name'])} мертв!</i>"
        add_dual_log(log1, log2, ru_str)
        
    elif c_type == "Splash":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: main_t = force_target
        else: main_t = random.choice(def_alive)
            
        splash_dmg = int(base_dmg * 0.5)
        ru_str = f"🌊 {atk_name}: <b>{html.escape(atk['name'])}</b> наносит сплеш урон!"
        for d in def_alive:
            dmg = base_dmg if d == main_t else splash_dmg
            if d.get('elite_mutator') == 'armored': dmg = int(dmg * 0.5)
            d['hp'] -= dmg
            if d['hp'] <= 0:
                d['hp'] = 0
                ru_str += f" ☠️ <i>{html.escape(d['name'])} мертв!</i>"
        add_dual_log(log1, log2, ru_str)
        
    elif c_type == "Fire":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
            
        dmg = base_dmg
        if target.get('elite_mutator') == 'armored': dmg = int(dmg * 0.7)
        target['hp'] -= dmg
        target['burn'] = target.get('burn', 0) + dmg
        ru_str = f"🔥 {atk_name}: <b>{html.escape(atk['name'])}</b> бьет <b>{html.escape(target['name'])}</b> на {dmg} и поджигает!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
        add_dual_log(log1, log2, ru_str)
        
    else:
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
            
        dmg = base_dmg
        if target.get('elite_mutator') == 'armored': dmg = int(dmg * 0.7)
        target['hp'] -= dmg
        ru_str = f"🎯 {atk_name}: <b>{html.escape(atk['name'])}</b> наносит {dmg} по <b>{html.escape(target['name'])}</b>!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
        add_dual_log(log1, log2, ru_str)
        
    return True, heals

async def get_team_data(user_id: int):
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    team = []
    slots = ['equip1', 'equip2', 'equip3', 'equip4']
    if user.get('perm_5th_slot') or user.get('vip_status'):
        slots.append('equip5')
        
    for slot in slots:
        inv_id = user.get(slot, 0)
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
                card['trauma'] = 0
                team.append(card)
            else:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ?", (user_id,))
    return team

async def get_bot_team(user_id: int, difficulty_mult: float, rank_name: str, diff_type: str = "med"):
    all_cards = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE rarity != 'Secret' AND hide_from_ai = 0")
    if len(all_cards) < 4: return []
    
    by_rarity = {}
    for c in all_cards:
        by_rarity.setdefault(c['rarity'], []).append(c)
        
    parts = rank_name.split()
    base_rank = parts[1] if len(parts) > 1 else "Bronze"
    
    ranks_order = ["Bronze", "Silver", "Gold", "Platina", "Diamond", "Ruby", "Uranium"]
    rank_idx = ranks_order.index(base_rank) if base_rank in ranks_order else 0

    if diff_type == "easy": effective_idx = max(0, rank_idx - 1)
    elif diff_type == "med": effective_idx = rank_idx
    elif diff_type == "hard": effective_idx = min(len(ranks_order)-1, rank_idx + 1)
    elif diff_type == "nightmare": effective_idx = min(len(ranks_order)-1, rank_idx + 2)
    else: effective_idx = rank_idx

    effective_rank = ranks_order[effective_idx]
    team_selection = []
    used_ids = set()
    
    for _ in range(4):
        r = random.random()
        pool = []
        if effective_rank == "Bronze": pool = by_rarity.get('Basic', []) + by_rarity.get('Uncommon', [])
        elif effective_rank == "Silver": pool = by_rarity.get('Uncommon', []) + by_rarity.get('Rare', []) + (by_rarity.get('Epic', []) if r < 0.1 else [])
        elif effective_rank == "Gold": pool = by_rarity.get('Rare', []) + by_rarity.get('Epic', []) + (by_rarity.get('Legendary', []) if r < 0.1 else [])
        elif effective_rank == "Platina": pool = by_rarity.get('Epic', []) + by_rarity.get('Legendary', []) + (by_rarity.get('Mythic', []) if r < 0.1 else [])
        elif effective_rank == "Diamond": pool = by_rarity.get('Legendary', []) + by_rarity.get('Mythic', []) + (by_rarity.get('Super', []) if r < 0.1 else [])
        elif effective_rank == "Ruby": pool = by_rarity.get('Mythic', []) + by_rarity.get('Super', []) + by_rarity.get('Exclusive', []) + (by_rarity.get('Leaderboard', []) if r < 0.1 else [])
        elif effective_rank == "Uranium":
            if diff_type == "nightmare": pool = by_rarity.get('Super', []) + by_rarity.get('Exclusive', []) + by_rarity.get('Leaderboard', [])
            else: pool = by_rarity.get('Super', []) + by_rarity.get('Exclusive', []) + by_rarity.get('Mythic', []) + by_rarity.get('Leaderboard', [])
        
        filtered_pool = [c for c in pool if c['id'] not in used_ids]
        if not filtered_pool:
            filtered_pool = [c for c in all_cards if c['id'] not in used_ids and c['rarity'] != 'Leaderboard']
            if not filtered_pool: filtered_pool = all_cards 
            
        weighted_pool = []
        for c in filtered_pool:
            weight = 1 if c['class_type'] == 'Healer' else 4
            weighted_pool.extend([c] * weight)
            
        chosen = random.choice(weighted_pool)
        used_ids.add(chosen['id'])
        team_selection.append(chosen)
        
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
        c_copy['trauma'] = 0
        team_copies.append(c_copy)
        
    return team_copies

async def get_dynamic_trophies(rank_name: str, rank_idx: int, diff_scale: float = 1.0) -> int:
    if "Uranium VI" in rank_name or "Uranium VII" in rank_name:
        return random.randint(1, 2)
    base = max(5, 18 - int((rank_idx / 25) * 12)) 
    won = random.randint(base, base+3)
    return int(won * diff_scale)

async def add_bp_xp(user_id: int, xp_to_add: int) -> tuple:
    db = await get_db_connection()
    try:
        user_bp = await db.execute("""
            SELECT ubp.bp_id, ubp.level, ubp.xp 
            FROM user_bp ubp JOIN battle_passes bp ON ubp.bp_id = bp.id
            WHERE ubp.user_id = ? AND ubp.is_active = 1
        """, (user_id,))
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

async def player_manual_turn(chat_id, p1_id, t1, t2):
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
        msg = await bot.send_message(chat_id, "⏳ <b>Ваш ход!</b> Выберите карту (12 сек):", reply_markup=kb)
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
        return await callback.answer("Не ваш ход!", show_alert=True)

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
        return await callback.answer("Не ваш ход!", show_alert=True)

    idx = int(callback.data.split("_")[1])
    active_manual_battles[chat_id]['target_idx'] = idx
    active_manual_battles[chat_id]['event'].set()
    await callback.answer()

async def do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, mods, is_pvp):
    if mods and mods.get('mod_manual_atk') and not is_pvp:
        atk, tgt = await player_manual_turn(chat_id, p1_id, t1, t2)
        did_turn, heals = await execute_turn(t1, t2, p1_name, p2_name, log, None, force_attacker=atk, force_target=tgt)
    else:
        did_turn, heals = await execute_turn(t1, t2, p1_name, p2_name, log, None)
    return did_turn, heals

@dp.callback_query(F.data.startswith("surrender_battle_"))
async def cb_surrender_battle_fixed(callback: types.CallbackQuery):
    battle_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    surrendered_players.add((user_id, battle_id))
    chat_id = callback.message.chat.id
    if chat_id in active_manual_battles and active_manual_battles[chat_id]['p1_id'] == user_id:
        active_manual_battles[chat_id]['event'].set()
    await callback.answer("🏳️ Вы сдались!", show_alert=True)

def get_battle_kb(battle_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"surrender_battle_{battle_id}")]])

async def battle_delay(battle_id, p1_id, p2_id, delay=3.0):
    steps = int(delay * 10)
    for _ in range(steps):
        await asyncio.sleep(0.1)
        if (p1_id, battle_id) in surrendered_players or (p2_id, battle_id) in surrendered_players:
            break

async def safe_edit_text(msg, text, reply_markup=None):
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower(): pass 
        else: raise e

@dp.callback_query(F.data.startswith("er_fight_"))
async def er_fight(callback: types.CallbackQuery):
    wave = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    if user_id in active_combats: return await callback.answer("Уже в бою!", show_alert=True)
        
    run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ? AND wave = ?", (user_id, wave))
    if not run: return await callback.answer("Ошибка сессии забега!", show_alert=True)
    
    settings = await fetch_one("SELECT * FROM endless_settings WHERE id = 1")
    t1 = json.loads(run['team_state'])
    if run['buff_dmg_waves'] > 0:
        for c in t1: c['dmg_buff'] = c.get('dmg_buff', 0) + int(c['damage'] * 0.5)
        
    t2 = await generate_endless_wave(wave, settings)
    
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    title_str = await get_user_titles_str(user_id)
    p1_name = get_display_name(user) + title_str
    
    active_combats.add(user_id)
    mods = {
        'mod_enemy_hp': user.get('mod_enemy_hp', 0),
        'mod_enemy_atk_all': user.get('mod_enemy_atk_all', 0),
        'mod_enemy_stats': user.get('mod_enemy_stats', 0),
        'mod_player_atk_all': user.get('mod_player_atk_all', 0),
        'mod_manual_atk': user.get('mod_manual_atk', 0),
        'mod_player_hp': user.get('mod_player_hp', 0)
    }
    
    asyncio.create_task(run_battle_loop(
        bot, callback.message.chat.id, user_id, p1_name, 0, f"Endless Боты (В.{wave})", 
        t1, t2, is_endless=True, endless_wave=wave, mods=mods
    ))
    await callback.answer()

async def run_battle_loop(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_id: int, p2_name: str, t1: list, t2: list, diff_trophies_scale: float = 1.0, diff_bp_mult: float = 1.0, is_pvp: bool = False, pvp_no_rewards: bool = False, mods=None, diff_type: str = "med", is_endless: bool = False, endless_wave: int = 0):
    battle_id = f"bt_{p1_id}_{int(time.time())}"
    surrendered_players.discard((p1_id, battle_id))
    if p2_id: surrendered_players.discard((p2_id, battle_id))
        
    try:
        msg = await bot.send_message(chat_id, f"⚔️ Бой <b>{p1_name}</b> VS <b>{p2_name}</b> начнется через 3 сек!")
        await asyncio.sleep(1); await safe_edit_text(msg, "⚔️ Бой начнется через 2 сек!")
        await asyncio.sleep(1); await safe_edit_text(msg, "⚔️ Бой начнется через 1 сек!")
        
        battle_start_time = time.time()
        log = []
        apply_boosters(t1, p1_name, log, None)
        apply_boosters(t2, p2_name, log, None)
        
        if log:
            await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
            await battle_delay(battle_id, p1_id, p2_id)

        turn = 1
        winner = None
        winner_id = None
        loser_id = None
        timeout_flag = False
        
        while True:
            if time.time() - battle_start_time > 180:
                timeout_flag = True
                break
                
            if (p1_id, battle_id) in surrendered_players:
                winner = p2_name; winner_id = p2_id; loser_id = p1_id
                surrendered_players.discard((p1_id, battle_id))
                log.append(f"🏳️ <b>{p1_name} сдался!</b>")
                break

            t1_alive = [c for c in t1 if c['hp'] > 0]
            t2_alive = [c for c in t2 if c['hp'] > 0]
            
            if not t1_alive and not t2_alive: winner = "Ничья"; break
            elif not t1_alive: winner = p2_name; winner_id = p2_id; loser_id = p1_id; break
            elif not t2_alive: winner = p1_name; winner_id = p1_id; loser_id = p2_id; break
                
            if turn > 40: winner = "Ничья по раундам"; break

            did_turn, _ = await do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, mods, is_pvp)
            if did_turn:
                if len(log) > 6: log = log[-6:]
                try: await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                except Exception as e:
                    if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                await battle_delay(battle_id, p1_id, p2_id)
                
                t2_alive = [c for c in t2 if c['hp'] > 0]
                if t2_alive and mods and mods.get('mod_player_atk_all') and not is_pvp:
                    did_turn_extra, _ = await do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, mods, is_pvp)
                    if did_turn_extra:
                        if len(log) > 6: log = log[-6:]
                        try: await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                        except: pass
                        await battle_delay(battle_id, p1_id, p2_id)

            t2_alive = [c for c in t2 if c['hp'] > 0]
            if t2_alive:
                if time.time() - battle_start_time > 180: timeout_flag = True; break
                did_turn_e, _ = await execute_turn(t2, t1, p2_name, p1_name, log, None)
                if did_turn_e:
                    if len(log) > 6: log = log[-6:]
                    try: await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                    except Exception as e:
                        if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                    await battle_delay(battle_id, p1_id, p2_id)
                    
                t1_alive_check = [c for c in t1 if c['hp'] > 0]
                if t1_alive_check and mods and mods.get('mod_enemy_atk_all') and not is_pvp:
                    did_turn_e_extra, _ = await execute_turn(t2, t1, p2_name, p1_name, log, None)
                    if did_turn_e_extra:
                        if len(log) > 6: log = log[-6:]
                        try: await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                        except: pass
                        await battle_delay(battle_id, p1_id, p2_id)
            turn += 1

        if timeout_flag:
            try: await msg.edit_text("⏳ <b>Бой автоматически прерван!</b>")
            except: pass
            return
            
        # Логика Endless Mode
        if is_endless:
            if winner == p1_name:
                run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ?", (p1_id,))
                
                new_wave = endless_wave + 1
                earned_points = endless_wave * 2
                earned_shards = max(1, endless_wave // 5)
                
                # Сохраняем состояние (снимаем временные баффы)
                for c in t1: c['dmg_buff'] = 0
                
                new_buff = run['buff_dmg_waves'] - 1 if run['buff_dmg_waves'] > 0 else 0
                await execute_db(
                    "UPDATE endless_runs SET wave = ?, team_state = ?, run_points = run_points + ?, buff_dmg_waves = ? WHERE user_id = ?",
                    (new_wave, json.dumps(t1), earned_points, new_buff, p1_id)
                )
                await execute_db("UPDATE users SET soul_shards = soul_shards + ? WHERE id = ?", (earned_shards, p1_id))
                
                # Check Milestones
                ms_text = ""
                milestones = await fetch_all("SELECT * FROM endless_milestones WHERE wave = ?", (endless_wave,))
                for ms in milestones:
                    if ms['reward_type'] == 'shekels':
                        await execute_db("UPDATE users SET coins = coins + ?, total_coins = total_coins + ? WHERE id = ?", (ms['amount'], ms['amount'], p1_id))
                        ms_text += f"\n🎁 Milestone Награда: <b>{ms['amount']} Шекелей</b>!"
                    elif ms['reward_type'] == 'r_bucks':
                        await execute_db("UPDATE users SET r_bucks = r_bucks + ? WHERE id = ?", (ms['amount'], p1_id))
                        ms_text += f"\n💎 Milestone Награда: <b>{ms['amount']} R$</b>!"
                    elif ms['reward_type'] == 'pack':
                        await execute_db("INSERT INTO user_seed_packs (user_id, pack_id, count) VALUES (?, ?, ?) ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + ?", (p1_id, ms['item_id'], ms['amount'], ms['amount']))
                        p_info = await fetch_one("SELECT title FROM seed_packs WHERE id = ?", (ms['item_id'],))
                        ms_text += f"\n📦 Milestone Награда: <b>Сид-Пак «{p_info['title']}» (x{ms['amount']})</b>!"

                final_text = f"🏁 <b>ВОЛНА {endless_wave} ПРОЙДЕНА!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nПолучено Осколков Душ: <b>{earned_shards}</b> 🔮\nОчков для апгрейда: <b>{earned_points}</b>{ms_text}"
                try: await msg.edit_text(final_text, reply_markup=None)
                except: pass
                await asyncio.sleep(2)
                await show_endless_midrun_menu(p1_id, msg)
                
            else:
                await execute_db("DELETE FROM endless_runs WHERE user_id = ?", (p1_id,))
                
                rec = await fetch_one("SELECT * FROM endless_records WHERE user_id = ?", (p1_id,))
                if not rec:
                    await execute_db("INSERT INTO endless_records (user_id, max_wave, season_max_wave) VALUES (?, ?, ?)", (p1_id, endless_wave, endless_wave))
                else:
                    await execute_db("UPDATE endless_records SET max_wave = MAX(max_wave, ?), season_max_wave = MAX(season_max_wave, ?) WHERE user_id = ?", (endless_wave, endless_wave, p1_id))
                    
                final_text = f"💀 <b>ЗАБЕГ ОКОНЧЕН!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВаша команда погибла на <b>{endless_wave} Волне</b>.\nВозвращайтесь, став сильнее!"
                try: await msg.edit_text(final_text, reply_markup=None)
                except: pass
            return

        # Логика PvE / PvP
        try:
            if is_pvp:
                await add_quest_progress_new(p1_id, 'q_pvp', 1)
                if p2_id != 0: await add_quest_progress_new(p2_id, 'q_pvp', 1)
            else:
                await add_quest_progress_new(p1_id, 'q_pve', 1)

            code_text = ""
            winner_user_id = None
            if winner == p1_name: winner_user_id = p1_id
            elif is_pvp and winner == p2_name: winner_user_id = p2_id

            if winner_user_id is not None and "Ничья" not in winner:
                if random.random() <= 0.05: 
                    db = await get_db_connection()
                    try:
                        new_code = generate_reward_code()
                        amt = random.randint(1000, 5000)
                        await db.execute("INSERT INTO reward_codes (code, reward_type, amount, item_id, mutation, owner_id, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)", (new_code, 'shekels', amt, 0, 'Normal', winner_user_id))
                        await db.commit()
                        code_text = f"🎁 <b>ВЫПАЛ УНИКАЛЬНЫЙ КОД-НАГРАДА! (Шанс 5%)</b>\nНажми, чтобы скопировать: <code>{new_code}</code>\nАктивируй через /codereward\n\n"
                    except Exception: pass
                    finally: await db.close()

            final_text = code_text + f"🏁 <b>ИТОГИ БОЯ: {p1_name} VS {p2_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n👑 <b>Победитель: {winner}</b>\n\n"
            bp_messages = []
            
            if pvp_no_rewards:
                final_text += "🤝 <b>Дружеская дуэль завершена!</b> Награды и кубки не начислялись."
            elif is_pvp:
                if "Ничья" not in winner and winner_id and loser_id:
                    await execute_db("UPDATE users SET trophies = trophies + 15 WHERE id = ?", (winner_id,))
                    await execute_db("UPDATE users SET trophies = MAX(0, trophies - 10) WHERE id = ?", (loser_id,))
                    final_text += f"🏆 Победитель забирает <b>+15 Кубков</b>\n💀 Проигравший теряет <b>-10 Кубков</b>"
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
                
                user_data = await fetch_one("SELECT * FROM users WHERE id = ?", (p1_id,))
                user_shekels_mult = 1.0
                user_bpxp_mult = 1.0
                if user_data:
                    if user_data.get('vip_status'):
                        user_shekels_mult *= 1.5; user_bpxp_mult *= 1.5
                    if user_data.get('perm_2x_shekels'):
                        user_shekels_mult *= 2.0
                    if user_data.get('perm_2x_bpxp'):
                        user_bpxp_mult *= 2.0
                
                if winner == p1_name:
                    user_trophies = user_data['trophies'] if user_data else 0
                    rank = await get_user_rank(user_trophies)
                    
                    coins_base = random.randint(25, 90) * rank['reward_mult'] * diff_trophies_scale * 0.85 * coin_mult
                    coins_won = int(coins_base * mod_reward_mult * user_shekels_mult)
                    won_t_base = await get_dynamic_trophies(rank['name'], rank['rank_idx'], diff_trophies_scale)
                    won_t = int(won_t_base * mod_trophy_mult)
                    
                    await execute_db("UPDATE users SET coins = coins + ?, total_coins = total_coins + ?, trophies = trophies + ? WHERE id = ?", (coins_won, coins_won, won_t, p1_id))
                    
                    final_text += f"🎉 <b>Награды:</b>\n💰 {coins_won} Шекелей"
                    if coin_mult > 1.0: final_text += f" (Ивент x{coin_mult})"
                    if mod_reward_mult != 1.0: final_text += f" [Моды x{mod_reward_mult:.2f}]"
                    if user_shekels_mult > 1.0: final_text += f" [Бусты x{user_shekels_mult}]"
                    final_text += f"\n🏆 {won_t} Кубков\n"
                    
                    bp_xp = int((20 * diff_bp_mult * xp_mult_event) * mod_reward_mult * user_bpxp_mult)
                    lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp)
                    final_text += f"🎫 +{bp_xp} BP XP"
                    if lvl_up: bp_messages.append(f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> {new_lvl} уровень в сезоне «{bp_title}»!")
                    
                    r_bucks_dropped = 0
                    if diff_type == "easy" and random.random() <= 0.10: r_bucks_dropped = 1
                    elif diff_type == "med" and random.random() <= 0.15: r_bucks_dropped = 1
                    elif diff_type == "hard" and random.random() <= 0.20: r_bucks_dropped = 2
                    elif diff_type == "nightmare" and random.random() <= 0.30: r_bucks_dropped = 2
                    
                    if r_bucks_dropped > 0:
                        await execute_db("UPDATE users SET r_bucks = r_bucks + ? WHERE id = ?", (r_bucks_dropped, p1_id))
                        final_text += f"\n💎 <b>ВЫПАЛО {r_bucks_dropped} R$!</b>"
                    
                elif winner == p2_name:
                    user_trophies = user_data['trophies'] if user_data else 0
                    rank = await get_user_rank(user_trophies)
                    
                    if "Uranium VI" in rank['name'] or "Uranium VII" in rank['name']: lost_t = random.randint(30, 50)
                    else: lost_t = 2
                    
                    await execute_db("UPDATE users SET trophies = MAX(0, trophies - ?) WHERE id = ?", (lost_t, p1_id))
                    final_text += f"💀 Вы проиграли и потеряли <b>{lost_t} 🏆</b>.\n"
                    bp_xp = int((5 * diff_bp_mult * xp_mult_event) * mod_reward_mult * user_bpxp_mult)
                    lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp)
                    final_text += f"🎫 +{bp_xp} BP XP"
                    if lvl_up: bp_messages.append(f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> {new_lvl} уровень в сезоне «{bp_title}»!")
                    
            try: await msg.edit_text(final_text, reply_markup=None)
            except Exception: pass
            
            for b_msg in bp_messages:
                try: await bot.send_message(p1_id, b_msg)
                except: pass

        except Exception as e:
            logging.error(f"Reward error: {e}")
            try: await msg.edit_text("Ошибка при выдаче наград.", reply_markup=None)
            except: pass

    except Exception as e:
        logging.error(f"Critical battle loop error: {e}")
        try: await bot.send_message(chat_id, "⚠️ Критическая ошибка. Бой прерван.")
        except: pass
    finally:
        active_combats.discard(p1_id)
        if is_pvp and p2_id != 0: active_combats.discard(p2_id)
        if chat_id in active_manual_battles: active_manual_battles.pop(chat_id, None)


@dp.message(F.text == BTN_PVE)
async def cmd_pve_select(message: types.Message):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats: return await message.answer("❌ Вы уже в бою!")
    if message.from_user.id in user_trades: return await message.answer("❌ Завершите обмен!")
        
    team1 = await get_team_data(message.from_user.id)
    if not team1: return await message.answer("❌ Боевая колода пуста!")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Лёгкий (-50% Кубки, -20% XP)", callback_data="pve_diff_easy")],
        [InlineKeyboardButton(text="🟡 Средний (Стандарт)", callback_data="pve_diff_med")],
        [InlineKeyboardButton(text="🔴 Сложный (+40% Кубки, +20% XP)", callback_data="pve_diff_hard")],
        [InlineKeyboardButton(text="☠️ Кошмар (+80% Кубки, +50% XP)", callback_data="pve_diff_nightmare")]
    ])
    await message.answer("⚔️ <b>ВЫБОР СЛОЖНОСТИ ИИ:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━", reply_markup=kb)

@dp.callback_query(F.data.startswith("pve_diff_"))
async def cmd_pve_battle(callback: types.CallbackQuery):
    if callback.from_user.id in active_combats or callback.from_user.id in user_trades:
        return await callback.answer("❌ Заняты!", show_alert=True)
        
    diff_type = callback.data.split("_")[2]
    power_mult, trophies_scale, bp_xp_mult = 1.0, 1.0, 1.0
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    
    diff_name = "Средний"
    if diff_type == "easy": power_mult, trophies_scale, bp_xp_mult, diff_name = 0.7, 0.5, 0.8, "Лёгкий 🟢"
    elif diff_type == "med": power_mult, trophies_scale, bp_xp_mult, diff_name = 1.0, 1.0, 1.0, "Средний 🟡"
    elif diff_type == "hard": power_mult, trophies_scale, bp_xp_mult, diff_name = 1.5, 1.4, 1.2, "Сложный 🔴" 
    elif diff_type == "nightmare": power_mult, trophies_scale, bp_xp_mult, diff_name = 1.9, 1.8, 1.5, "Кошмар ☠️"
        
    mods = {
        'mod_enemy_hp': user.get('mod_enemy_hp', 0),
        'mod_enemy_atk_all': user.get('mod_enemy_atk_all', 0),
        'mod_enemy_stats': user.get('mod_enemy_stats', 0),
        'mod_player_atk_all': user.get('mod_player_atk_all', 0),
        'mod_manual_atk': user.get('mod_manual_atk', 0),
        'mod_player_hp': user.get('mod_player_hp', 0)
    }

    try: await callback.message.edit_text(f"⚔️ <i>Ищем противника... Сложность: <b>{diff_name}</b></i>")
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
            c['hp'] = int(c['hp'] * 1.5); c['max_hp'] = c['hp']
    if mods['mod_enemy_stats']:
        for c in team2:
            c['damage'] = int(c['damage'] * 1.2)
            c['hp'] = int(c['hp'] * 1.2); c['max_hp'] = c['hp']
            c['booster_dmg_mult'] *= 1.2; c['booster_hp_mult'] *= 1.2
    if mods['mod_player_hp']:
        for c in team1:
            c['hp'] = int(c['hp'] * 1.3); c['max_hp'] = c['hp']
            
    title_str = await get_user_titles_str(callback.from_user.id)
    p1_name = get_display_name(user) + title_str
    active_combats.add(callback.from_user.id)
    
    await log_user_action(callback.from_user.id, f"Начал PvE бой (сложность: {diff_type})")
    
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, callback.from_user.id, p1_name, 0, f"AI ({diff_name})", team1, team2, trophies_scale, bp_xp_mult, is_pvp=False, mods=mods, diff_type=diff_type))
    await callback.answer()

@dp.callback_query(F.data == "adm_endless_main")
async def adm_endless_main(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    s = await fetch_one("SELECT is_active FROM endless_settings WHERE id = 1")
    is_a = s['is_active'] if s else 0
    st_text = "🟢 Включен" if is_a else "🔴 Выключен"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Переключить режим ({st_text})", callback_data="adm_e_toggle")],
        [InlineKeyboardButton(text="⚙️ Множители и Сложность", callback_data="adm_e_settings")],
        [InlineKeyboardButton(text="🎯 Настройка Пулов (Тиры)", callback_data="adm_e_tiers")],
        [InlineKeyboardButton(text="🎁 Milestones (Награды за волны)", callback_data="adm_e_milestones")],
        [InlineKeyboardButton(text="🛒 Магазин Осколков", callback_data="adm_e_shop")],
        [InlineKeyboardButton(text="🏆 Награды Лидерборда", callback_data="adm_e_lb")],
        [InlineKeyboardButton(text="🔄 Экстренный сброс сезона", callback_data="adm_e_wipe")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("♾ <b>УПРАВЛЕНИЕ ENDLESS MODE</b>", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "adm_e_toggle")
async def adm_e_toggle(callback: types.CallbackQuery):
    s = await fetch_one("SELECT is_active FROM endless_settings WHERE id = 1")
    new_v = 0 if s['is_active'] else 1
    await execute_db("UPDATE endless_settings SET is_active = ? WHERE id = 1", (new_v,))
    await adm_endless_main(callback)

@dp.callback_query(F.data == "adm_e_settings")
async def adm_e_settings(callback: types.CallbackQuery, state: FSMContext):
    s = await fetch_one("SELECT * FROM endless_settings WHERE id = 1")
    text = (
        f"⚙️ <b>Сложность Endless Mode</b>\n"
        f"HP Множитель: {s['hp_mult']}\nDMG Множитель: {s['dmg_mult']}\n"
        f"Старт Бюджет: {s['budget_start']}\nПрирост Бюджета: {s['budget_step']}\n"
        f"Шанс Мутаций (Старт): {s['mut_base']}\nПрирост Шанса: {s['mut_step']}\n\n"
        f"Чтобы изменить, отправьте 6 чисел через пробел:\n"
        f"<code>[hp_mult] [dmg_mult] [budget_start] [budget_step] [mut_base] [mut_step]</code>\n"
        f"Пример: <code>0.15 0.15 5 3.0 0.05 0.01</code>"
    )
    await callback.message.answer(text)
    await state.set_state(AdminEndless.settings_input)
    await callback.answer()

@dp.message(AdminEndless.settings_input)
async def adm_e_settings_save(message: types.Message, state: FSMContext):
    try:
        parts = list(map(float, message.text.replace(',', '.').split()))
        if len(parts) != 6: raise ValueError
        await execute_db(
            "UPDATE endless_settings SET hp_mult=?, dmg_mult=?, budget_start=?, budget_step=?, mut_base=?, mut_step=? WHERE id=1",
            (parts[0], parts[1], int(parts[2]), parts[3], parts[4], parts[5])
        )
        await message.answer("✅ Настройки Endless обновлены!")
    except:
        await message.answer("❌ Ошибка ввода. Нужно ровно 6 чисел через пробел.")
    await state.clear()

@dp.callback_query(F.data == "adm_e_tiers")
async def adm_e_tiers(callback: types.CallbackQuery, state: FSMContext):
    tiers = await fetch_all("SELECT * FROM endless_tiers ORDER BY min_wave ASC")
    text = "🎯 <b>Настройка пулов спавна (Тиры)</b>\n"
    for t in tiers:
        text += f"ID {t['id']} | Волны {t['min_wave']} - {t['max_wave']} | {t['rarities']}\n"
        
    text += "\nЧтобы <b>Добавить/Изменить</b> тир, отправьте:\n<code>[Мин_Волна] [Макс_Волна] [Rare,Epic,Legendary]</code>\n"
    text += "Чтобы <b>Удалить</b> тир, отправьте:\n<code>del [ID]</code>"
    
    await callback.message.answer(text)
    await state.set_state(AdminEndless.tier_input)
    await callback.answer()

@dp.message(AdminEndless.tier_input)
async def adm_e_tiers_save(message: types.Message, state: FSMContext):
    txt = message.text.strip()
    try:
        if txt.lower().startswith('del '):
            tid = int(txt.split()[1])
            await execute_db("DELETE FROM endless_tiers WHERE id = ?", (tid,))
            await message.answer(f"✅ Тир {tid} удален.")
        else:
            parts = txt.split()
            min_w = int(parts[0])
            max_w = int(parts[1])
            rarities = parts[2]
            await execute_db("INSERT INTO endless_tiers (min_wave, max_wave, rarities) VALUES (?, ?, ?)", (min_w, max_w, rarities))
            await message.answer("✅ Тир добавлен!")
    except:
        await message.answer("❌ Ошибка ввода.")
    await state.clear()

@dp.callback_query(F.data == "adm_e_milestones")
async def adm_e_milestones(callback: types.CallbackQuery, state: FSMContext):
    ms = await fetch_all("SELECT * FROM endless_milestones ORDER BY wave ASC")
    text = "🎁 <b>Настройки Наград (Milestones)</b>\n"
    for m in ms:
        text += f"ID {m['id']} | Волна {m['wave']} | {m['reward_type']} - Кол-во: {m['amount']} | Item_ID: {m['item_id']}\n"
        
    text += "\nДобавить: <code>[Волна] [Тип: shekels/pack/r_bucks] [Кол-во] [ID_пака(если pack, иначе 0)]</code>\n"
    text += "Удалить: <code>del [ID]</code>"
    
    await callback.message.answer(text)
    await state.set_state(AdminEndless.milestone_input)
    await callback.answer()

@dp.message(AdminEndless.milestone_input)
async def adm_e_milestones_save(message: types.Message, state: FSMContext):
    txt = message.text.strip()
    try:
        if txt.lower().startswith('del '):
            mid = int(txt.split()[1])
            await execute_db("DELETE FROM endless_milestones WHERE id = ?", (mid,))
            await message.answer("✅ Удалено.")
        else:
            parts = txt.split()
            w = int(parts[0]); r_type = parts[1]; amt = int(parts[2]); i_id = int(parts[3])
            await execute_db("INSERT INTO endless_milestones (wave, reward_type, amount, item_id) VALUES (?, ?, ?, ?)", (w, r_type, amt, i_id))
            await message.answer("✅ Добавлено!")
    except:
        await message.answer("❌ Ошибка ввода.")
    await state.clear()

@dp.callback_query(F.data == "adm_e_shop")
async def adm_e_shop(callback: types.CallbackQuery, state: FSMContext):
    items = await fetch_all("SELECT * FROM endless_shop")
    text = "🛒 <b>Магазин за Осколки</b>\n"
    for i in items:
        text += f"ID {i['id']} | {i['name']} | Цена: {i['price_shards']} | {i['reward_type']} | Amt: {i['amount']} | Item: {i['item_id']}\n"
        
    text += "\nДобавить: <code>[Цена_Осколков] [Тип: card/pack/r_bucks] [Кол-во] [Item_ID] [Имя_товара]</code>\n"
    text += "Удалить: <code>del [ID]</code>"
    
    await callback.message.answer(text)
    await state.set_state(AdminEndless.shop_input)
    await callback.answer()

@dp.message(AdminEndless.shop_input)
async def adm_e_shop_save(message: types.Message, state: FSMContext):
    txt = message.text.strip()
    try:
        if txt.lower().startswith('del '):
            sid = int(txt.split()[1])
            await execute_db("DELETE FROM endless_shop WHERE id = ?", (sid,))
            await message.answer("✅ Удалено.")
        else:
            parts = txt.split(maxsplit=4)
            p = int(parts[0]); t = parts[1]; a = int(parts[2]); i = int(parts[3]); n = parts[4]
            await execute_db("INSERT INTO endless_shop (name, price_shards, reward_type, amount, item_id) VALUES (?, ?, ?, ?, ?)", (n, p, t, a, i))
            await message.answer("✅ Добавлено!")
    except:
        await message.answer("❌ Ошибка ввода.")
    await state.clear()

@dp.callback_query(F.data == "adm_e_lb")
async def adm_e_lb(callback: types.CallbackQuery, state: FSMContext):
    rws = await fetch_all("SELECT * FROM endless_lb_rewards ORDER BY bracket ASC")
    text = "🏆 <b>Награды Лидерборда Endless</b>\n"
    for r in rws:
        text += f"ID {r['id']} | Место {r['bracket']} | {r['reward_type']} | Amt: {r['amount']} | Item: {r['item_id']} | Mut: {r['mutation']}\n"
        
    text += "\nДобавить: <code>[Место: 1/2/3/4_9/10_20] [Тип: shekels/shards/r_bucks/card] [Кол-во] [Item_ID] [Mut]</code>\n"
    text += "Удалить: <code>del [ID]</code>"
    
    await callback.message.answer(text)
    await state.set_state(AdminEndless.lb_input)
    await callback.answer()

@dp.message(AdminEndless.lb_input)
async def adm_e_lb_save(message: types.Message, state: FSMContext):
    txt = message.text.strip()
    try:
        if txt.lower().startswith('del '):
            rid = int(txt.split()[1])
            await execute_db("DELETE FROM endless_lb_rewards WHERE id = ?", (rid,))
            await message.answer("✅ Удалено.")
        else:
            parts = txt.split()
            b = parts[0]; t = parts[1]; a = int(parts[2]); i = int(parts[3]); m = parts[4]
            await execute_db("INSERT INTO endless_lb_rewards (bracket, reward_type, amount, item_id, mutation) VALUES (?, ?, ?, ?, ?)", (b, t, a, i, m))
            await message.answer("✅ Добавлено!")
    except:
        await message.answer("❌ Ошибка ввода.")
    await state.clear()

@dp.callback_query(F.data == "adm_e_wipe")
async def adm_e_wipe(callback: types.CallbackQuery):
    await execute_db("UPDATE endless_records SET season_max_wave = 0")
    await execute_db("DELETE FROM endless_runs")
    await execute_db("UPDATE server_settings SET last_endless_lb_reward = ? WHERE id = 1", (time.time(),))
    await callback.answer("✅ Сезон обнулен! База очищена.", show_alert=True)
    await adm_endless_main(callback)

def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Настройка Endless", callback_data="adm_endless_main")],
        [InlineKeyboardButton(text="🃏 Карты", callback_data="adm_cards"), InlineKeyboardButton(text="👤 Игроки", callback_data="adm_users")],
        [InlineKeyboardButton(text="🎉 Ивенты", callback_data="adm_events"), InlineKeyboardButton(text="👑 Админы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="🎟 Батл-пассы", callback_data="adm_bp_main"), InlineKeyboardButton(text="✍️ Сигнеры", callback_data="adm_signers")],
        [InlineKeyboardButton(text="🏆 Награды за Топ", callback_data="adm_lb_main"), InlineKeyboardButton(text="📦 Сид-Паки", callback_data="adm_sp_main")],
        [InlineKeyboardButton(text="🎁 Коды-Награды", callback_data="adm_codes_main"), InlineKeyboardButton(text="🔨 Настройка Крафтов", callback_data="adm_craft_main")],
        [InlineKeyboardButton(text="📦 Бэкап БД", callback_data="adm_db")]
    ])

@dp.message(F.text == BTN_ADM)
@dp.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id): return
    await message.answer("⚙️ <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\nВыберите раздел для управления ботом:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_main")
async def cq_adm_main(callback: types.CallbackQuery):
    await callback.message.edit_text("⚙️ <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\nВыберите раздел для управления ботом:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_sp_main")
async def adm_sp_main_menu(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать Сид-Пак", callback_data="adm_sp_cr")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="adm_sp_del_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("📦 <b>Управление Сид-Паками</b>", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "adm_sp_cr")
async def adm_sp_cr_start(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(sp_cards=[])
    await callback.message.answer(f"Создание Сид-Пака.\nВведите название:")
    await state.set_state(CreateSeedPack.title)
    await callback.answer()

@dp.message(CreateSeedPack.title)
async def adm_sp_cr_title(message: types.Message, state: FSMContext):
    await state.update_data(sp_title=message.text)
    await message.answer("Отправьте фото для пака (или 'Пропустить'):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True))
    await state.set_state(CreateSeedPack.photo)

@dp.message(CreateSeedPack.photo)
async def adm_sp_cr_photo(message: types.Message, state: FSMContext):
    if message.text == "Пропустить": await state.update_data(sp_photo=None)
    elif message.photo: await state.update_data(sp_photo=message.photo[-1].file_id)
    else: return await message.answer("Фото или 'Пропустить'!")
    await message.answer("Введите описание пака:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(CreateSeedPack.description)

@dp.message(CreateSeedPack.description)
async def adm_sp_cr_desc(message: types.Message, state: FSMContext):
    await state.update_data(sp_desc=message.text)
    await message.answer("Введите цену пака в шекелях:")
    await state.set_state(CreateSeedPack.price)

@dp.message(CreateSeedPack.price)
async def adm_sp_cr_price(message: types.Message, state: FSMContext):
    try:
        price = int(message.text)
        await state.update_data(sp_price=price)
        await adm_sp_cr_menu(message, state)
    except: await message.answer("Число!")

async def adm_sp_cr_menu(msg, state: FSMContext):
    data = await state.get_data()
    text = f"📦 <b>Пак: {data['sp_title']}</b>\nЦена: {data['sp_price']}\nКарты:\n"
    for i, c in enumerate(data['sp_cards']):
        text += f"{i+1}. ID:{c['card_id']} - Вес: {c['chance']}\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить карту", callback_data="sp_cr_add_c")],
        [InlineKeyboardButton(text="✅ Завершить создание", callback_data="sp_cr_finish")]
    ])
    if isinstance(msg, types.CallbackQuery): await msg.message.answer(text, reply_markup=kb)
    else: await msg.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "sp_cr_add_c")
async def sp_cr_add_c(callback: types.CallbackQuery, state: FSMContext):
    query = "SELECT id, name, rarity FROM cards"
    cards = await fetch_all(query)
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'],'')} {c['name']}"} for c in cards]
    await state.update_data(sp_items=items)
    kb = get_pagination_keyboard(items, 0, "sp_cr_c", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту:", reply_markup=kb)
    await state.set_state(CreateSeedPack.card_select)

@dp.callback_query(CreateSeedPack.card_select, F.data.startswith("sp_cr_c_page_"))
async def sp_cr_c_pag(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[4])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('sp_items', []), page, "sp_cr_c", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(CreateSeedPack.card_select, F.data.startswith("sp_cr_c_"))
async def sp_cr_c_sel(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    cid = int(callback.data.split("_")[3])
    await state.update_data(sp_curr_c=cid)
    await callback.message.edit_text("Введите вес выпадения:")
    await state.set_state(CreateSeedPack.card_chance)

@dp.message(CreateSeedPack.card_chance)
async def sp_cr_c_chance(message: types.Message, state: FSMContext):
    try:
        w = float(message.text.replace(',', '.'))
        data = await state.get_data()
        data['sp_cards'].append({'card_id': data['sp_curr_c'], 'chance': w})
        await state.update_data(sp_cards=data['sp_cards'])
        await adm_sp_cr_menu(message, state)
    except: await message.answer("Число!")

@dp.callback_query(F.data == "sp_cr_finish")
async def sp_cr_finish(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data['sp_cards']: return await callback.answer("Пак пуст!", show_alert=True)
    db = await get_db_connection()
    try:
        cur = await db.execute("INSERT INTO seed_packs (title, photo_id, description, price) VALUES (?, ?, ?, ?)",
                               (data['sp_title'], data.get('sp_photo'), data['sp_desc'], data['sp_price']))
        pid = cur.lastrowid
        for c in data['sp_cards']:
            await db.execute("INSERT INTO seed_pack_cards (pack_id, card_id, drop_chance) VALUES (?, ?, ?)",
                             (pid, c['card_id'], c['chance']))
        await db.commit()
        await callback.message.edit_text("✅ Сид-пак успешно создан!")
    finally: await db.close()
    await state.clear()
    
@dp.callback_query(F.data == "adm_sp_del_list")
async def adm_sp_del_list(callback: types.CallbackQuery):
    packs = await fetch_all("SELECT id, title FROM seed_packs")
    kb = []
    for p in packs: kb.append([InlineKeyboardButton(text=f"🗑 {p['title']}", callback_data=f"adm_sp_del_{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_sp_main")])
    await callback.message.edit_text("Выберите пак для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    
@dp.callback_query(F.data.startswith("adm_sp_del_"))
async def adm_sp_del_action(callback: types.CallbackQuery):
    pid = int(callback.data.split("_")[3])
    await execute_db("DELETE FROM seed_packs WHERE id = ?", (pid,))
    await execute_db("DELETE FROM seed_pack_cards WHERE pack_id = ?", (pid,))
    await callback.answer("✅ Удалено!", show_alert=True)
    await adm_sp_main_menu(callback)

@dp.callback_query(F.data == "adm_codes_main")
async def adm_codes_main(callback: types.CallbackQuery):
    if callback.from_user.id != SUPER_ADMIN_ID: return await callback.answer("Только для Супер-Админа!", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Сгенерировать коды", callback_data="adm_code_gen")],
        [InlineKeyboardButton(text="📜 Просмотр кодов", callback_data="adm_code_list_0")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🎁 <b>Управление Уникальными Кодами</b>", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "adm_code_gen")
async def adm_code_gen_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Сколько кодов вы хотите сгенерировать?")
    await state.set_state(AdminRewardCode.count)
    await callback.answer()

@dp.message(AdminRewardCode.count)
async def adm_code_gen_count(message: types.Message, state: FSMContext):
    try:
        count = int(message.text.strip())
        if count <= 0: raise ValueError
        await state.update_data(gen_code_count=count)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Шекели", callback_data="cg_type_shekels")],
            [InlineKeyboardButton(text="🃏 Юниты", callback_data="cg_type_card")],
            [InlineKeyboardButton(text="📦 Сид-Паки", callback_data="cg_type_pack")]
        ])
        await message.answer(f"Генерируем {count} кодов. Что будет в награде?", reply_markup=kb)
        await state.set_state(AdminRewardCode.r_type)
    except:
        await message.answer("❌ Введите положительное число.")

@dp.callback_query(AdminRewardCode.r_type, F.data.startswith("cg_type_"))
async def adm_code_gen_type(callback: types.CallbackQuery, state: FSMContext):
    r_type = callback.data.split("_")[2]
    await state.update_data(gen_code_type=r_type)
    
    if r_type == "shekels":
        await callback.message.edit_text("Введите количество шекелей:")
        await state.set_state(AdminRewardCode.amount)
    elif r_type == "card":
        all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
        items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']}"} for c in all_cards]
        await state.update_data(gen_items=items)
        kb = get_pagination_keyboard(items, 0, "cgc", columns=1, items_per_page=8)
        await callback.message.edit_text("Выберите карту:", reply_markup=kb)
        await state.set_state(AdminRewardCode.card_id)
    elif r_type == "pack":
        packs = await fetch_all("SELECT id, title FROM seed_packs ORDER BY id DESC")
        items = [{"id": p['id'], "btn_text": f"📦 {p['title']}"} for p in packs]
        await state.update_data(gen_items=items)
        kb = get_pagination_keyboard(items, 0, "cgp", columns=1, items_per_page=8)
        await callback.message.edit_text("Выберите Сид-Пак:", reply_markup=kb)
        await state.set_state(AdminRewardCode.pack_id)
    await callback.answer()

@dp.message(AdminRewardCode.amount)
async def adm_code_gen_shekels_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        data = await state.get_data()
        await generate_and_save_codes(message, state, data['gen_code_count'], 'shekels', amount=amount)
    except:
        await message.answer("❌ Число!")

@dp.callback_query(AdminRewardCode.card_id, F.data.startswith("cgc_page_"))
async def adm_code_card_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('gen_items', []), page, "cgc", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(AdminRewardCode.card_id, F.data.startswith("cgc_"))
async def adm_code_card_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[1])
    await state.update_data(gen_card_id=card_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Обычная", callback_data="cgmut_Normal")],
        [InlineKeyboardButton(text="⭐ Золотая", callback_data="cgmut_Gold")],
        [InlineKeyboardButton(text="🌈 Радужная", callback_data="cgmut_Rainbow")]
    ])
    await callback.message.edit_text("Выберите мутацию:", reply_markup=kb)
    await state.set_state(AdminRewardCode.mutation)

@dp.callback_query(AdminRewardCode.mutation, F.data.startswith("cgmut_"))
async def adm_code_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[1]
    data = await state.get_data()
    await generate_and_save_codes(callback.message, state, data['gen_code_count'], 'card', card_id=data['gen_card_id'], mutation=mutation)

@dp.callback_query(AdminRewardCode.pack_id, F.data.startswith("cgp_page_"))
async def adm_code_pack_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('gen_items', []), page, "cgp", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(AdminRewardCode.pack_id, F.data.startswith("cgp_"))
async def adm_code_pack_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    pack_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    await generate_and_save_codes(callback.message, state, data['gen_code_count'], 'pack', item_id=pack_id)

async def generate_and_save_codes(message: types.Message, state: FSMContext, count: int, r_type: str, amount: int = 0, card_id: int = 0, mutation: str = 'Normal', item_id: int = 0):
    db = await get_db_connection()
    codes = []
    try:
        await db.execute("BEGIN EXCLUSIVE")
        for _ in range(count):
            code = generate_reward_code()
            codes.append(code)
            await db.execute(
                "INSERT INTO reward_codes (code, reward_type, amount, item_id, mutation, owner_id, is_active) VALUES (?, ?, ?, ?, ?, 0, 1)",
                (code, r_type, amount, card_id if r_type == 'card' else item_id, mutation)
            )
        await db.commit()
        
        codes_str = "\n".join(codes)
        bio = io.BytesIO(codes_str.encode('utf-8'))
        bio.seek(0)
        file = types.BufferedInputFile(bio.read(), filename="reward_codes.txt")
        await bot.send_document(message.chat.id, file, caption=f"✅ Сгенерировано {count} кодов.")
    finally:
        await db.close()
    await state.clear()

@dp.callback_query(F.data.startswith("adm_code_list_"))
async def adm_code_list(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[3])
    codes = await fetch_all("SELECT * FROM reward_codes WHERE is_active = 1 ORDER BY code DESC")
    if not codes: return await callback.answer("Нет активных кодов.", show_alert=True)
    items = []
    for c in codes:
        own_status = f"ID:{c['owner_id']}" if c['owner_id'] != 0 else "Общий"
        items.append({"id": c['code'], "btn_text": f"🔑 {c['code'][:8]}... ({c['reward_type']} | {own_status})"})
        
    kb = get_pagination_keyboard(items, page, "admcode", columns=1, items_per_page=8)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_codes_main")])
    try: await callback.message.edit_text(f"📜 <b>Активные коды ({len(codes)} шт.)</b>", reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("admcode_page_"))
async def adm_code_list_pag(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[2])
    fake_call = callback.model_copy(update={"data": f"adm_code_list_{page}"})
    await adm_code_list(fake_call)

@dp.callback_query(F.data.startswith("admcode_"))
async def adm_code_deactivate(callback: types.CallbackQuery):
    if "page" in callback.data: return
    code = callback.data.split("_")[1]
    await execute_db("UPDATE reward_codes SET is_active = 0 WHERE code = ?", (code,))
    await callback.answer(f"Код деактивирован!", show_alert=True)
    fake_call = callback.model_copy(update={"data": "adm_code_list_0"})
    await adm_code_list(fake_call)

@dp.callback_query(F.data == "adm_lb_main")
async def adm_lb_main(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Кубки (Сезон)", callback_data="adm_lb_cat_trophies")],
        [InlineKeyboardButton(text="💰 Шекели (Все время)", callback_data="adm_lb_cat_coins")],
        [InlineKeyboardButton(text="🃏 Карты (Все время)", callback_data="adm_lb_cat_cards")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🏆 <b>Настройка наград за Лидерборд</b>\nВыберите категорию:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_lb_cat_"))
async def adm_lb_cat_select(callback: types.CallbackQuery, state: FSMContext):
    cat = callback.data.split("_")[3]
    await state.update_data(lb_current_type=cat)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥇 1 Место", callback_data=f"lb_edit_1")],
        [InlineKeyboardButton(text="🥈 2 Место", callback_data=f"lb_edit_2")],
        [InlineKeyboardButton(text="🥉 3 Место", callback_data=f"lb_edit_3")],
        [InlineKeyboardButton(text="🏅 4-9 Места", callback_data=f"lb_edit_4_9")],
        [InlineKeyboardButton(text="🎖 10-20 Места", callback_data=f"lb_edit_10_20")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_lb_main")]
    ])
    await callback.message.edit_text(f"🏆 <b>Настройка наград</b>", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("lb_edit_"))
async def adm_lb_edit(callback: types.CallbackQuery, state: FSMContext):
    bracket = callback.data.replace("lb_edit_", "")
    data = await state.get_data()
    lb_type = data.get('lb_current_type', 'trophies')
    
    rewards = await fetch_all("SELECT * FROM lb_rewards WHERE bracket = ? AND lb_type = ?", (bracket, lb_type))
    text = f"🏆 <b>Награды для места: {bracket.replace('_', '-')} ({lb_type})</b>\n\n"
    if not rewards: text += "<i>Не установлены.</i>\n"
    else:
        for r in rewards:
            if r['reward_type'] == 'shekels': text += f"💰 {r['amount']} Шекелей\n"
            elif r['reward_type'] == 'card':
                c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['card_id'],))
                n = c['name'] if c else "Удаленная карта"
                text += f"🃏 {r['mutation']} {n}\n"
                
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Шекели", callback_data=f"lb_add_sh_{bracket}"), InlineKeyboardButton(text="➕ Карту", callback_data=f"lb_add_cd_{bracket}")],
        [InlineKeyboardButton(text="🗑 Очистить", callback_data=f"lb_clear_{bracket}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data=f"adm_lb_cat_{lb_type}")]
    ])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("lb_clear_"))
async def adm_lb_clear(callback: types.CallbackQuery, state: FSMContext):
    bracket = callback.data.replace("lb_clear_", "")
    data = await state.get_data()
    lb_type = data.get('lb_current_type', 'trophies')
    await execute_db("DELETE FROM lb_rewards WHERE bracket = ? AND lb_type = ?", (bracket, lb_type))
    await callback.answer("✅ Награды очищены!", show_alert=True)
    fake_call = callback.model_copy(update={"data": f"lb_edit_{bracket}"})
    await adm_lb_edit(fake_call, state)

@dp.callback_query(F.data.startswith("lb_add_sh_"))
async def adm_lb_add_shekels(callback: types.CallbackQuery, state: FSMContext):
    bracket = callback.data.replace("lb_add_sh_", "")
    await state.update_data(lb_bracket=bracket, lb_reward_type="shekels")
    await callback.message.answer("Введите количество Шекелей:")
    await state.set_state(AdminLBRewards.amount)
    await callback.answer()

@dp.message(AdminLBRewards.amount)
async def adm_lb_save_shekels(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        data = await state.get_data()
        lb_type = data.get('lb_current_type', 'trophies')
        await execute_db("INSERT INTO lb_rewards (bracket, reward_type, amount, lb_type) VALUES (?, ?, ?, ?)", (data['lb_bracket'], 'shekels', amt, lb_type))
        await message.answer(f"✅ Награда добавлена!")
    except:
        await message.answer("❌ Число!")
    await state.clear()

@dp.callback_query(F.data.startswith("lb_add_cd_"))
async def adm_lb_add_card(callback: types.CallbackQuery, state: FSMContext):
    bracket = callback.data.replace("lb_add_cd_", "")
    await state.update_data(lb_bracket=bracket, lb_reward_type="card")
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']} (ID:{c['id']})"} for c in all_cards]
    await state.update_data(lb_items=items)
    kb = get_pagination_keyboard(items, 0, "lbc", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту:", reply_markup=kb)
    await state.set_state(AdminLBRewards.card_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("lbc_page_"), AdminLBRewards.card_id)
async def adm_lb_c_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('lb_items', []), page, "lbc", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)

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
    await callback.message.edit_text("Выберите мутацию:", reply_markup=kb)
    await state.set_state(AdminLBRewards.mutation)

@dp.callback_query(F.data.startswith("lb_mut_"), AdminLBRewards.mutation)
async def adm_lb_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[2]
    data = await state.get_data()
    lb_type = data.get('lb_current_type', 'trophies')
    await execute_db("INSERT INTO lb_rewards (bracket, reward_type, card_id, mutation, lb_type) VALUES (?, ?, ?, ?, ?)", (data['lb_bracket'], 'card', data['lb_card_id'], mutation, lb_type))
    await callback.message.edit_text(f"✅ Карта добавлена в награды!")
    await state.clear()

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
    await message.answer("Введи БАЗОВЫЙ ШАНС (0 для Secret/Leaderboard):")
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
    elif message.text == "Healer":
        await message.answer("Введи базовую силу лечения (целое число):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(AddCard.damage)
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
        hp_mult = float(message.text.replace(',','.'))
        await state.update_data(booster_hp_mult=hp_mult)
        await add_card_finish(message, state)
    except: await message.answer("❌ Число!")

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
        if await state.get_state() == AddCard.hp:
            hp = int(message.text)
            await state.update_data(hp=hp, booster_hp_mult=1.0)
        
        data = await state.get_data()
        await message.answer("⏳ Генерирую рамку редкости для карты...", reply_markup=ReplyKeyboardRemove())
        
        new_photo_id = await create_bordered_image(bot, data['photo'], data['rarity'])
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id, booster_dmg_mult, booster_hp_mult, hide_in_index, hide_from_ai) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
            (data['name'], data['rarity'], data['class_type'], data.get('damage', 0), data.get('hp', 0), data['drop_chance'], new_photo_id, data.get('booster_dmg_mult', 1.0), data.get('booster_hp_mult', 1.0))
        )
        await message.answer_photo(new_photo_id, caption=f"✅ <b>Карта {data['name']} создана!</b>")
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

@dp.callback_query(F.data.startswith("adm_ed_c_"))
async def adm_card_edit_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    c_id = int(callback.data.split("_")[3])
    card = await fetch_one("SELECT * FROM cards WHERE id = ?", (c_id,))
    if not card: return await callback.answer("❌ Карта не найдена.")
    
    await state.update_data(edit_id=c_id)
    
    label_dmg = "Лечение" if card['class_type'] == "Healer" else "Урон"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data="edit_val_name"), InlineKeyboardButton(text="✏️ Шанс (Вес)", callback_data="edit_val_chance")],
        [InlineKeyboardButton(text=f"✏️ {label_dmg}", callback_data="edit_val_dmg"), InlineKeyboardButton(text="✏️ ХП", callback_data="edit_val_hp")],
        [InlineKeyboardButton(text="✏️ Буст Урон", callback_data="edit_val_bdmg"), InlineKeyboardButton(text="✏️ Буст ХП", callback_data="edit_val_bhp")],
        [InlineKeyboardButton(text="✏️ Класс", callback_data="edit_val_class")],
        [InlineKeyboardButton(text=f"👁 В Индексе: {'Скрыта' if card.get('hide_in_index') else 'Видима'}", callback_data="edit_tgl_idx")],
        [InlineKeyboardButton(text=f"🤖 ИИ (Боты): {'Запрещено' if card.get('hide_from_ai') else 'Разрешено'}", callback_data="edit_tgl_ai")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_card_edit_list")]
    ])
    await callback.message.edit_text(f"Редактирование <b>{card['name']}</b> (ID: {c_id})\nЧто меняем?", reply_markup=kb)

@dp.callback_query(F.data.in_(["edit_tgl_idx", "edit_tgl_ai"]))
async def adm_card_toggle_flags(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    c_id = data.get('edit_id')
    card = await fetch_one("SELECT * FROM cards WHERE id = ?", (c_id,))
    if callback.data == "edit_tgl_idx":
        await execute_db("UPDATE cards SET hide_in_index = ? WHERE id = ?", (0 if card.get('hide_in_index') else 1, c_id))
    else:
        await execute_db("UPDATE cards SET hide_from_ai = ? WHERE id = ?", (0 if card.get('hide_from_ai') else 1, c_id))
    await adm_card_edit_select(callback.model_copy(update={"data": f"adm_ed_c_{c_id}"}), state)

@dp.callback_query(EditCard.waiting_new_value, F.data.startswith("edit_val_"))
async def adm_card_edit_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[2]
    await state.update_data(edit_field=field)
    if field == "class":
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c)] for c in CLASSES], resize_keyboard=True)
        await callback.message.answer("Выберите новый класс с клавиатуры:", reply_markup=kb)
    else:
        await callback.message.answer(f"Отправь новое значение:")
    await callback.answer()

@dp.message(EditCard.waiting_new_value)
async def adm_card_edit_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    c_id = data['edit_id']; field = data['edit_field']; val = message.text
    
    col_map = {
        "name": ("name", str), "chance": ("drop_chance", float),
        "dmg": ("damage", int), "hp": ("hp", int),
        "bdmg": ("booster_dmg_mult", float), "bhp": ("booster_hp_mult", float),
        "class": ("class_type", str)
    }
    col, cast_fn = col_map[field]
    try:
        if field == "class" and val not in CLASSES: return await message.answer("Неверный класс.")
        val = cast_fn(val.replace(',', '.')) if cast_fn == float else cast_fn(val)
        await execute_db(f"UPDATE cards SET {col} = ? WHERE id = ?", (val, c_id))
        await message.answer("✅ Изменено!", reply_markup=get_main_keyboard(await is_admin(message.from_user.id), await is_signer(message.from_user.id)))
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
            for slot in ['equip1', 'equip2', 'equip3', 'equip4', 'equip5']:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE {slot} = ?", (i_id,))
        await message.answer(f"✅ Карта {c_id} полностью удалена.")
    except: pass
    await state.clear()

@dp.callback_query(F.data == "adm_users")
async def cq_adm_users(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Выдать карту", callback_data="adm_usr_givecard"),
         InlineKeyboardButton(text="➖ Забрать карту", callback_data="adm_usr_takecard")],
        [InlineKeyboardButton(text="💰 Выдать шекели", callback_data="adm_usr_give_coins"),
         InlineKeyboardButton(text="🏆 Выдать кубки", callback_data="adm_usr_give_trophies")],
        [InlineKeyboardButton(text="🔄 Сбросить состояние", callback_data="adm_usr_reset_battle")],
        [InlineKeyboardButton(text="🔨 Бан / Разбан", callback_data="adm_usr_ban")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("👤 <b>Управление Игроками</b>", reply_markup=kb)

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
    except:
        await message.answer("❌ ID должен быть числом.")

@dp.callback_query(F.data.startswith("give_c_page_"), GiveCard.card_id)
async def adm_give_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('give_items', []), page, "give_c", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)

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

@dp.callback_query(F.data.startswith("give_mut_"), GiveCard.mutation)
async def adm_give_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[2]
    await state.update_data(give_mutation=mutation)
    await callback.message.edit_text("Введите СЕРИЙНЫЙ НОМЕР (0 для без серийника):")
    await state.set_state(GiveCard.custom_serial)

@dp.message(GiveCard.custom_serial)
async def adm_give_serial_save(message: types.Message, state: FSMContext):
    try:
        serial = int(message.text)
        data = await state.get_data()
        user_id = data.get('give_user_id')
        card_id = data.get('give_card_id')
        mutation = data.get('give_mutation')
        
        if serial == 0:
            db = await get_db_connection()
            try:
                res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0 AND signed_by = 0", (user_id, card_id, mutation))
                inv_item = await res.fetchone()
                if inv_item: await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                else: await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, 0, 0)", (user_id, card_id, mutation))
                await db.commit()
            finally: await db.close()
            assigned_serial = 0
        else:
            _, assigned_serial, _ = await give_card_to_user(user_id, card_id, mutation, custom_serial=serial)
            
        await message.answer(f"✅ Карта выдана игроку {user_id}!")
        await state.clear()
    except ValueError:
        await message.answer("❌ Число.")

@dp.callback_query(F.data == "adm_usr_takecard")
async def adm_usr_take_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока:")
    await state.set_state(TakeCard.user_id)
    await callback.answer()

@dp.message(TakeCard.user_id)
async def adm_usr_take_user(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(take_user_id=uid)
        
        inv = await fetch_all("""
            SELECT i.id as inv_id, c.name, c.rarity, i.count, i.mutation, i.serial_number
            FROM inventory i JOIN cards c ON i.card_id = c.id 
            WHERE i.user_id = ? AND i.count > 0
        """, (uid,))
        
        if not inv: return await message.answer("Инвентарь пуст.")
            
        items = []
        for c in inv:
            items.append({"id": c['inv_id'], "btn_text": f"{c['name']} (x{c['count']})"})
            
        await state.update_data(take_items=items)
        kb = get_pagination_keyboard(items, 0, "take_c", columns=1, items_per_page=8)
        await message.answer("Выберите карту для изъятия:", reply_markup=kb)
        await state.set_state(TakeCard.inv_id)
    except: pass

@dp.callback_query(F.data.startswith("take_c_page_"), TakeCard.inv_id)
async def adm_take_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('take_items', []), page, "take_c", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(F.data.startswith("take_c_"), TakeCard.inv_id)
async def adm_take_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    await state.update_data(take_inv_id=inv_id)
    await callback.message.edit_text("Сколько штук удалить? (Или 'all'):")
    await state.set_state(TakeCard.amount)

@dp.message(TakeCard.amount)
async def adm_take_amount(message: types.Message, state: FSMContext):
    amt_str = message.text.lower()
    data = await state.get_data()
    uid = data['take_user_id']; inv_id = data['take_inv_id']
    
    inv_item = await fetch_one("SELECT count FROM inventory WHERE id = ? AND user_id = ?", (inv_id, uid))
    count_have = inv_item['count']
    amt = count_have if amt_str == 'all' else min(int(amt_str), count_have)
        
    if amt == count_have:
        await execute_db("DELETE FROM inventory WHERE id = ?", (inv_id,))
        for slot in ['equip1', 'equip2', 'equip3', 'equip4', 'equip5']:
            await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ? AND {slot} = ?", (uid, inv_id))
    else:
        await execute_db("UPDATE inventory SET count = count - ? WHERE id = ?", (amt, inv_id))
        
    await message.answer(f"✅ Успешно удалено {amt} шт.")
    await state.clear()

@dp.callback_query(F.data == "adm_usr_ban")
async def adm_usr_ban_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправь ID игрока для смены статуса бана:")
    await state.set_state(AdminBan.user_id)
    await callback.answer()

@dp.message(AdminBan.user_id)
async def adm_usr_ban_finish(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        usr = await fetch_one("SELECT banned FROM users WHERE id = ?", (uid,))
        new_st = 0 if usr['banned'] == 1 else 1
        await execute_db("UPDATE users SET banned = ? WHERE id = ?", (new_st, uid))
        await message.answer(f"✅ Статус бана изменен на {new_st}.")
    except: pass
    await state.clear()

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
    except: pass

@dp.message(AdminManage.give_coins_amount)
async def adm_usr_give_coins_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data['target_id']
        await execute_db("UPDATE users SET coins = coins + ?, total_coins = total_coins + ? WHERE id = ?", (amount, amount, uid))
        await message.answer(f"✅ Успешно выдано {amount} единиц валюты игроку {uid}.")
    except: pass
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
    except: pass

@dp.message(AdminManage.give_trophies_amount)
async def adm_usr_give_trophies_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data['target_id']
        await execute_db(f"UPDATE users SET trophies = trophies + ? WHERE id = ?", (amount, uid))
        await message.answer(f"✅ Успешно выдано {amount} кубков игроку {uid}.")
    except: pass
    await state.clear()

@dp.callback_query(F.data == "adm_usr_reset_battle")
async def adm_usr_reset_battle_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока для сброса состояния:")
    await state.set_state(AdminManage.reset_battle_id)
    await callback.answer()

@dp.message(AdminManage.reset_battle_id)
async def adm_usr_reset_battle_finish(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        flag = False
        if uid in active_combats: active_combats.discard(uid); flag = True
        if uid in pvp_queue: pvp_queue.discard(uid); flag = True
        if uid in user_trades:
            trade_id = user_trades[uid]
            trade = active_trades.pop(trade_id, None)
            if trade:
                user_trades.pop(trade['p1'], None)
                user_trades.pop(trade['p2'], None)
            flag = True
        if flag: await message.answer(f"✅ Состояние для игрока {uid} успешно сброшено.")
        else: await message.answer("ℹ️ Игрок не находился в активном поиске/трейде.")
    except: pass
    await state.clear()

@dp.callback_query(F.data == "adm_craft_main")
async def adm_craft_main(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать рецепт", callback_data="adm_craft_create")],
        [InlineKeyboardButton(text="🗑 Удалить рецепт", callback_data="adm_craft_delete")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🔨 <b>Управление Рецептами Крафта</b>", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "adm_craft_delete")
async def adm_craft_del_list(callback: types.CallbackQuery):
    recipes = await fetch_all("SELECT r.id, c.name FROM craft_recipes r JOIN cards c ON r.target_card_id = c.id")
    if not recipes: return await callback.answer("Нет рецептов.", show_alert=True)
    
    kb = []
    for r in recipes:
        kb.append([InlineKeyboardButton(text=f"🗑 Удалить: {r['name']}", callback_data=f"adm_cr_del_{r['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="adm_craft_main")])
    await callback.message.edit_text("Выберите рецепт для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_cr_del_"))
async def adm_craft_del_action(callback: types.CallbackQuery):
    r_id = int(callback.data.split("_")[3])
    await execute_db("DELETE FROM craft_recipes WHERE id = ?", (r_id,))
    await execute_db("DELETE FROM craft_ingredients WHERE recipe_id = ?", (r_id,))
    await callback.answer("✅ Рецепт удален!", show_alert=True)
    await adm_craft_main(callback)

@dp.callback_query(F.data == "adm_craft_create")
async def adm_craft_cr_start(callback: types.CallbackQuery, state: FSMContext):
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']} (ID:{c['id']})"} for c in all_cards]
    await state.update_data(craft_items=items)
    kb = get_pagination_keyboard(items, 0, "crc_target", columns=1, items_per_page=8)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="adm_craft_main")])
    await callback.message.edit_text("🔨 <b>Шаг 1: Выберите карту, которая получится при крафте:</b>", reply_markup=kb)
    await state.set_state(AdminCraftCreate.target_card)
    await callback.answer()

@dp.callback_query(AdminCraftCreate.target_card, F.data.startswith("crc_target_page_"))
async def adm_craft_cr_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('craft_items', []), page, "crc_target", columns=1, items_per_page=8)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="adm_craft_main")])
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(AdminCraftCreate.target_card, F.data.startswith("crc_target_"))
async def adm_craft_cr_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[2])
    await state.update_data(cr_target=card_id, cr_ings=[])
    await callback.message.edit_text("🔨 <b>Шаг 2: Введите цену крафта в Шекелях:</b>")
    await state.set_state(AdminCraftCreate.price)
    
@dp.message(AdminCraftCreate.price)
async def adm_craft_cr_price(message: types.Message, state: FSMContext):
    try:
        price = int(message.text)
        await state.update_data(cr_price=price)
        await adm_craft_cr_show_menu(message, state)
    except: pass

async def adm_craft_cr_show_menu(msg, state: FSMContext):
    data = await state.get_data()
    t_card = await fetch_one("SELECT name FROM cards WHERE id = ?", (data['cr_target'],))
    
    text = f"🔨 <b>Настройка Рецепта</b>\nЦель: <b>{t_card['name']}</b>\nЦена: <b>{data['cr_price']} 💰</b>\n\nИнгредиенты:\n"
    for idx, ing in enumerate(data['cr_ings'], 1):
        c = await fetch_one("SELECT name FROM cards WHERE id = ?", (ing['card_id'],))
        text += f"{idx}. {c['name']} x{ing['amount']}\n"
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ингредиент", callback_data="cr_add_ing")],
        [InlineKeyboardButton(text="✅ Завершить и сохранить", callback_data="cr_save")]
    ])
    if isinstance(msg, types.CallbackQuery): await msg.message.edit_text(text, reply_markup=kb)
    else: await msg.answer(text, reply_markup=kb)
    await state.set_state(AdminCraftCreate.add_ingredient_card)

@dp.callback_query(AdminCraftCreate.add_ingredient_card, F.data == "cr_add_ing")
async def adm_craft_add_ing(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('craft_items', []), 0, "crc_ing", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту-ингредиент:", reply_markup=kb)

@dp.callback_query(AdminCraftCreate.add_ingredient_card, F.data.startswith("crc_ing_page_"))
async def adm_craft_ing_pag(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('craft_items', []), page, "crc_ing", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(AdminCraftCreate.add_ingredient_card, F.data.startswith("crc_ing_"))
async def adm_craft_ing_sel(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[2])
    await state.update_data(cr_curr_ing=card_id)
    await callback.message.edit_text("Введите количество требуемых штук:")
    await state.set_state(AdminCraftCreate.add_ingredient_amount)

@dp.message(AdminCraftCreate.add_ingredient_amount)
async def adm_craft_ing_amt(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        data = await state.get_data()
        data['cr_ings'].append({'card_id': data['cr_curr_ing'], 'amount': amt})
        await state.update_data(cr_ings=data['cr_ings'])
        await adm_craft_cr_show_menu(message, state)
    except: pass

@dp.callback_query(AdminCraftCreate.add_ingredient_card, F.data == "cr_save")
async def adm_craft_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    db = await get_db_connection()
    try:
        cur = await db.execute("INSERT INTO craft_recipes (target_card_id, price) VALUES (?, ?)", (data['cr_target'], data['cr_price']))
        r_id = cur.lastrowid
        for ing in data['cr_ings']:
            await db.execute("INSERT INTO craft_ingredients (recipe_id, card_id, amount) VALUES (?, ?, ?)", (r_id, ing['card_id'], ing['amount']))
        await db.commit()
        await callback.message.edit_text("✅ Рецепт успешно создан!")
    finally: await db.close()
    await state.clear()
    
@dp.callback_query(F.data == "adm_bp_main")
async def adm_bp_main(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать Батл-пасс", callback_data="adm_bp_create")],
        [InlineKeyboardButton(text="🗑 Удалить Батл-пасс", callback_data="adm_bp_delete")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🎟 <b>Управление Батл-пассами</b>", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "adm_bp_delete")
async def adm_bp_del_list(callback: types.CallbackQuery):
    passes = await fetch_all("SELECT * FROM battle_passes ORDER BY id DESC")
    kb = []
    for bp in passes: kb.append([InlineKeyboardButton(text=f"🗑 {bp['title']}", callback_data=f"adm_bp_del_id_{bp['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="adm_bp_main")])
    await callback.message.edit_text("Выберите Батл-пасс для полного удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_bp_del_id_"))
async def adm_bp_del_confirm(callback: types.CallbackQuery):
    bp_id = int(callback.data.split("_")[4])
    await execute_db("DELETE FROM battle_passes WHERE id = ?", (bp_id,))
    await execute_db("DELETE FROM bp_levels WHERE bp_id = ?", (bp_id,))
    await callback.answer("✅ Батл-пасс удален!", show_alert=True)
    await adm_bp_main(callback)

@dp.callback_query(F.data == "adm_bp_create")
async def adm_bp_create_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer(f"🎟 <b>Создание Батл-пасса</b>\nВведите название:")
    await state.set_state(AdminBPCreation.title)

@dp.message(AdminBPCreation.title)
async def adm_bp_cr_title(message: types.Message, state: FSMContext):
    await state.update_data(bp_title=message.text)
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True)
    await message.answer("Отправьте фото (или Пропустить):", reply_markup=kb)
    await state.set_state(AdminBPCreation.photo)

@dp.message(AdminBPCreation.photo)
async def adm_bp_cr_photo(message: types.Message, state: FSMContext):
    if message.text == "Пропустить": await state.update_data(bp_photo=None)
    elif message.photo: await state.update_data(bp_photo=message.photo[-1].file_id)
    await message.answer("Сколько уровней?", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AdminBPCreation.levels_count)

@dp.message(AdminBPCreation.levels_count)
async def adm_bp_cr_count(message: types.Message, state: FSMContext):
    try:
        count = int(message.text)
        await state.update_data(bp_levels_count=count, current_level=1, bp_data_levels={})
        await adm_bp_ask_level_xp(message, state, 1)
    except: pass

async def adm_bp_ask_level_xp(message_or_call, state: FSMContext, lvl: int):
    msg = f"⚙️ <b>Настройка Уровня {lvl}</b>\nСколько ОПЫТА (XP) требуется?"
    if isinstance(message_or_call, types.CallbackQuery): await message_or_call.message.answer(msg)
    else: await message_or_call.answer(msg)
    await state.set_state(AdminBPCreation.level_xp)

@dp.message(AdminBPCreation.level_xp)
async def adm_bp_cr_lvl_xp(message: types.Message, state: FSMContext):
    try:
        xp = int(message.text)
        data = await state.get_data()
        lvl = data['current_level']
        data['bp_data_levels'][lvl] = {'xp': xp, 'rewards': []}
        await state.update_data(bp_data_levels=data['bp_data_levels'])
        await adm_bp_show_reward_menu(message, state, lvl)
    except: pass

async def adm_bp_show_reward_menu(message_or_call, state: FSMContext, lvl: int):
    data = await state.get_data()
    rewards = data['bp_data_levels'][lvl]['rewards']
    
    text = f"⚙️ <b>Уровень {lvl}</b>\nНаграды:\n"
    for r in rewards:
        if r['type'] == 'shekels': text += f"💰 {r['amount']} Шекелей\n"
        elif r['type'] == 'card': text += f"🃏 Карта ID:{r['card_id']} ({r['mutation']})\n"
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Шекели", callback_data="bpr_add_sh"), InlineKeyboardButton(text="➕ Карта", callback_data="bpr_add_cd")],
        [InlineKeyboardButton(text="✅ Дальше", callback_data="bpr_next_lvl")]
    ])
    
    if isinstance(message_or_call, types.CallbackQuery): await message_or_call.message.answer(text, reply_markup=kb)
    else: await message_or_call.answer(text, reply_markup=kb)
    await state.set_state(AdminBPCreation.reward_action)

@dp.callback_query(AdminBPCreation.reward_action, F.data == "bpr_add_sh")
async def bpr_add_sh(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Количество шекелей:")
    await state.set_state(AdminBPCreation.reward_shekels)

@dp.message(AdminBPCreation.reward_shekels)
async def bpr_save_sh(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        data = await state.get_data()
        lvl = data['current_level']
        data['bp_data_levels'][lvl]['rewards'].append({'type': 'shekels', 'amount': amt})
        await state.update_data(bp_data_levels=data['bp_data_levels'])
        await adm_bp_show_reward_menu(message, state, lvl)
    except: pass

@dp.callback_query(AdminBPCreation.reward_action, F.data == "bpr_add_cd")
async def bpr_add_cd(callback: types.CallbackQuery, state: FSMContext):
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']}"} for c in all_cards]
    await state.update_data(bpadm_items=items)
    kb = get_pagination_keyboard(items, 0, "bpadmc", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту:", reply_markup=kb)
    await state.set_state(AdminBPCreation.reward_card)

@dp.callback_query(AdminBPCreation.reward_card, F.data.startswith("bpadmc_page_"))
async def bpadm_c_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('bpadm_items', []), page, "bpadmc", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)

@dp.callback_query(AdminBPCreation.reward_card, F.data.startswith("bpadmc_"))
async def bpadm_c_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[1])
    await state.update_data(bpadm_sel_card=card_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Обычная", callback_data="bpadmmut_Normal"), InlineKeyboardButton(text="⭐ Золотая", callback_data="bpadmmut_Gold")],
        [InlineKeyboardButton(text="🌈 Радужная", callback_data="bpadmmut_Rainbow")]
    ])
    await callback.message.edit_text("Мутация:", reply_markup=kb)
    await state.set_state(AdminBPCreation.reward_mutation)

@dp.callback_query(AdminBPCreation.reward_mutation, F.data.startswith("bpadmmut_"))
async def bpadm_mut_select(callback: types.Callback
