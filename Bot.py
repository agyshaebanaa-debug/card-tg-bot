import asyncio
import logging
import random
import time
import io
import os
import math
import string
import html
import uuid
import json
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

active_combats = set()
active_trades = {}  
user_trades = {}    
pvp_queue = set()
active_manual_battles = {} 
surrendered_players = set() 
active_craft_sessions = {} 
active_upgrades = {}
active_endless_runs = set()

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

UPDATE_LOGS = [
    "🛠 <b>Update 4: ENDLESS MODE</b>\n\n"
    "• <b>Endless Mode:</b> Добавлен Бесконечный режим! Сражайтесь с волнами врагов, получайте Осколки Душ и открывайте уникальные награды.\n"
    "• <b>Endless Shop & Leaderboard:</b> Магазин Душ и отдельный топ, который сбрасывается каждые 3 дня!\n"
    "• <b>Админ-панель:</b> Добавлена полная настройка Бесконечного режима (Тиры, Награды за волны, Скейлинг).\n"
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
BTN_ENDLESS_MENU = "♾ Endless Mode"

# Кнопки для режима Endless
BTN_ENDLESS_START = "⚔️ ENDLESS"
BTN_ENDLESS_SHOP = "🛒 Endless Shop"
BTN_ENDLESS_LB = "🏆 Endless Leaderboard"
BTN_NORMAL_MODE = "🔙 Обычный мод"

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
                mod_player_hp INTEGER DEFAULT 0,
                soul_shards INTEGER DEFAULT 0,
                endless_max_wave INTEGER DEFAULT 0
            )
        """)
        
        for col in ["r_bucks", "perm_2x_shekels", "perm_2x_bpxp", "perm_5th_slot", "perm_1_5x_luck", "vip_status", "equip5", "soul_shards", "endless_max_wave"]:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            except aiosqlite.OperationalError: pass
                
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
        
        try: await db.execute("ALTER TABLE cards ADD COLUMN hide_in_index INTEGER DEFAULT 0")
        except: pass
        try: await db.execute("ALTER TABLE cards ADD COLUMN hide_from_ai INTEGER DEFAULT 0")
        except: pass
        
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
        
        await db.execute("UPDATE cards SET rarity = 'Super' WHERE rarity IN ('Godly')")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ranks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                min_trophies INTEGER,
                difficulty_mult REAL DEFAULT 1.0,
                reward_mult REAL DEFAULT 1.0
            )
        """)

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
        
        await db.execute("""CREATE TABLE IF NOT EXISTS seed_packs (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, photo_id TEXT, description TEXT, price INTEGER DEFAULT 2000)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS seed_pack_cards (pack_id INTEGER, card_id INTEGER, drop_chance REAL, PRIMARY KEY (pack_id, card_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_seed_packs (user_id INTEGER, pack_id INTEGER, count INTEGER DEFAULT 0, PRIMARY KEY (user_id, pack_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS shop_items (id INTEGER PRIMARY KEY AUTOINCREMENT, item_type TEXT, name TEXT, price INTEGER, stock INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS admin_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS lb_rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, bracket TEXT, reward_type TEXT, amount INTEGER DEFAULT 0, card_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal', lb_type TEXT DEFAULT 'trophies')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS authorized_signers (user_id INTEGER PRIMARY KEY)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS battle_passes (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, photo_id TEXT, created_at REAL)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS bp_levels (id INTEGER PRIMARY KEY AUTOINCREMENT, bp_id INTEGER, level INTEGER, xp_required INTEGER)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS bp_rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, level_id INTEGER, reward_type TEXT, amount INTEGER DEFAULT 0, card_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal')""")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_bp (user_id INTEGER, bp_id INTEGER, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 0, is_active INTEGER DEFAULT 0, PRIMARY KEY (user_id, bp_id))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS user_bp_claims (user_id INTEGER, bp_id INTEGER, level INTEGER, PRIMARY KEY (user_id, bp_id, level))""")
        await db.execute("""CREATE TABLE IF NOT EXISTS reward_codes (code TEXT PRIMARY KEY, reward_type TEXT, amount INTEGER DEFAULT 0, item_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal', owner_id INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS craft_recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, target_card_id INTEGER, price INTEGER DEFAULT 0)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS craft_ingredients (id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER, card_id INTEGER, amount INTEGER DEFAULT 1)""")

        # Таблицы для Endless Mode
        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_settings (
                id INTEGER PRIMARY KEY,
                is_active INTEGER DEFAULT 1,
                base_hp_mult REAL DEFAULT 1.05,
                base_dmg_mult REAL DEFAULT 1.05,
                budget_start INTEGER DEFAULT 5,
                budget_step INTEGER DEFAULT 2,
                last_lb_reset REAL DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_tiers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_wave INTEGER,
                end_wave INTEGER,
                allowed_rarities TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wave INTEGER,
                reward_type TEXT,
                amount INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                mutation TEXT DEFAULT 'Normal'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_lb_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rank_start INTEGER,
                rank_end INTEGER,
                reward_type TEXT,
                amount INTEGER DEFAULT 0,
                item_id INTEGER DEFAULT 0,
                mutation TEXT DEFAULT 'Normal'
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS endless_runs (
                user_id INTEGER PRIMARY KEY,
                wave INTEGER DEFAULT 1,
                team_state TEXT
            )
        """)

        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        await db.execute("INSERT OR IGNORE INTO server_settings (id) VALUES (1)")
        await db.execute("INSERT OR IGNORE INTO endless_settings (id, last_lb_reset) VALUES (1, ?)", (time.time(),))
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
class AddCard(StatesGroup): photo = State(); name = State(); drop_chance = State(); rarity = State(); class_type = State(); damage = State(); hp = State(); booster_dmg = State(); booster_hp = State()
class EditCard(StatesGroup): waiting_new_value = State()
class GiveCard(StatesGroup): user_id = State(); card_id = State(); mutation = State(); custom_serial = State()
class TakeCard(StatesGroup): user_id = State(); inv_id = State(); amount = State()
class AdminBan(StatesGroup): user_id = State()
class AdminManage(StatesGroup): add_id = State(); del_id = State(); reset_battle_id = State(); give_coins_id = State(); give_coins_amount = State(); give_trophies_id = State(); give_trophies_amount = State(); view_logs_id = State()
class AdminLBRewards(StatesGroup): bracket = State(); reward_type = State(); amount = State(); card_id = State(); mutation = State()
class AdminBPCreation(StatesGroup): title = State(); photo = State(); levels_count = State(); level_xp = State(); reward_action = State(); reward_shekels = State(); reward_card = State(); reward_mutation = State()
class AdminBPEdit(StatesGroup): select_bp = State(); edit_menu = State(); edit_title = State(); edit_photo = State()
class AdminSigner(StatesGroup): add_id = State()
class EventLuck(StatesGroup): mult = State(); mins = State()
class EventCD(StatesGroup): mult = State(); mins = State()
class EventCoin(StatesGroup): mult = State(); mins = State()
class EventXP(StatesGroup): mult = State(); mins = State()
class AdminAnnounce(StatesGroup): content = State()
class PvPState(StatesGroup): waiting_target = State()
class TradeState(StatesGroup): waiting_target = State()
class TradeRS(StatesGroup): amount = State()
class CreateSeedPack(StatesGroup): title = State(); photo = State(); description = State(); price = State(); card_select = State(); card_chance = State(); confirm_save = State()
class EditSeedPack(StatesGroup): select_pack = State(); menu = State(); edit_title = State(); edit_photo = State(); edit_description = State(); edit_price = State(); card_edit_chance = State(); add_card_select = State(); add_card_chance = State()
class AdminRewardCode(StatesGroup): count = State(); r_type = State(); amount = State(); card_id = State(); mutation = State(); pack_id = State()
class UserUseCode(StatesGroup): waiting_code = State()
class AdminCraftCreate(StatesGroup): target_card = State(); price = State(); add_ingredient_card = State(); add_ingredient_amount = State()
class AdminCraftEdit(StatesGroup): menu = State(); edit_price = State(); add_ing_card = State(); add_ing_amount = State()

class AdminEndlessSettings(StatesGroup): waiting_val = State()
class AdminEndlessTier(StatesGroup): start_wave = State(); end_wave = State(); rarities = State()
class AdminEndlessMilestone(StatesGroup): wave = State(); r_type = State(); amount = State(); item_id = State(); mutation = State()
class AdminEndlessLB(StatesGroup): rank_start = State(); rank_end = State(); r_type = State(); amount = State(); item_id = State(); mutation = State()

class FakeCall:
    def __init__(self, message, data):
        self.message = message
        self.data = data
        self.from_user = message.from_user

# ========================================================================
# УТИЛИТЫ И ХЕЛПЕРЫ ДЛЯ UI
# ========================================================================
def get_display_name(user_data: dict) -> str:
    if user_data.get('username'): return html.escape(f"@{user_data['username']}")
    elif user_data.get('first_name'): return html.escape(user_data['first_name'])
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
                    except: pass
        await db.commit()
    finally:
        await db.close()

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

async def broadcast_message(text_ru: str, notif_type: str = None, shop_types: set = None):
    query = "SELECT * FROM users WHERE banned = 0"
    if notif_type: query += f" AND {notif_type} = 1"
        
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
        except: pass
    await notify_super_admin(f"📢 <b>Broadcast complete.</b>\nDelivered: {success}")

def get_main_keyboard(is_adm: bool = False, is_sgn: bool = False):
    kb = [
        [KeyboardButton(text=BTN_DRAW), KeyboardButton(text=BTN_PVE), KeyboardButton(text=BTN_PVP)],
        [KeyboardButton(text=BTN_ENDLESS_MENU)],
        [KeyboardButton(text=BTN_INV), KeyboardButton(text=BTN_PROF), KeyboardButton(text=BTN_EQ)],
        [KeyboardButton(text=BTN_QUESTS), KeyboardButton(text=BTN_SHOP), KeyboardButton(text=BTN_BP)],
        [KeyboardButton(text=BTN_TOP), KeyboardButton(text=BTN_IDX), KeyboardButton(text=BTN_SEED_PACKS)],
        [KeyboardButton(text=BTN_CRAFT)], 
        [KeyboardButton(text=BTN_SET)]
    ]
    bottom_row = []
    if is_sgn: bottom_row.append(KeyboardButton(text=BTN_SIGN))
    if is_adm: bottom_row.append(KeyboardButton(text=BTN_ADM))
    if bottom_row: kb.append(bottom_row)
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def get_endless_keyboard(is_adm: bool = False, is_sgn: bool = False):
    kb = [
        [KeyboardButton(text=BTN_ENDLESS_START)],
        [KeyboardButton(text=BTN_ENDLESS_SHOP), KeyboardButton(text=BTN_ENDLESS_LB)],
        [KeyboardButton(text=BTN_INV), KeyboardButton(text=BTN_EQ)],
        [KeyboardButton(text=BTN_PROF), KeyboardButton(text=BTN_NORMAL_MODE)]
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
            cursor = await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, ?, 0)", (user_id, card_id, mutation, custom_serial))
            return cursor.lastrowid, custom_serial, True
            
        if needs_serial_number(rarity, mutation):
            res = await db.execute("SELECT MAX(serial_number) as m FROM inventory WHERE card_id = ? AND mutation = ?", (card_id, mutation))
            row = await res.fetchone()
            curr_max = row['m'] if (row and row['m'] is not None) else 0
            new_serial = curr_max + 1
            cursor = await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, ?, 0)", (user_id, card_id, mutation, new_serial))
            return cursor.lastrowid, new_serial, True
        else:
            res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0 AND signed_by = 0", (user_id, card_id, mutation))
            inv_item = await res.fetchone()
            if inv_item:
                await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                return inv_item['id'], 0, False
            else:
                cursor = await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, 0, 0)", (user_id, card_id, mutation))
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
    if c.get('serial_number', 0) > 0: name += f" <b>[#{c['serial_number']:04d}]</b>"
    if c.get('signed_by', 0) > 0:
        signer_name = c.get('signer_name') or f"ID:{c['signed_by']}"
        name += f" <i>(✍️ Sign: {signer_name})</i>"
    return name

def format_card_name_plain(c):
    r_em = RARITY_EMOJI.get(c.get('rarity', 'Basic'), "⚪")
    c_em = CLASS_EMOJI.get(c.get('class_type', 'Single'), "🎯")
    name = f"{r_em} {c_em} {c['name']}"
    if c.get('serial_number', 0) > 0: name += f" [#{c['serial_number']:04d}]"
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
        try: await bot.send_message(chat_id, "⏳ <i>Время ожидания истекло (1 минута). Команда сброшена.</i>")
        except: pass

async def get_card_sources(card_id: int) -> str:
    sources = []
    packs = await fetch_all("SELECT p.title FROM seed_pack_cards spc JOIN seed_packs p ON spc.pack_id = p.id WHERE spc.card_id = ?", (card_id,))
    if packs: sources.append("📦 Сид-Паки: " + ", ".join([p['title'] for p in packs]))
    c = await fetch_one("SELECT drop_chance, rarity, hide_in_index FROM cards WHERE id = ?", (card_id,))
    if c:
        if c['drop_chance'] > 0 and c['rarity'] not in ['Leaderboard', 'Secret']: sources.append("🎲 Гача (/getcard) / Магазин")
        if c['rarity'] == 'Leaderboard': sources.append("🏆 Топ игроков (Лидерборд)")
    bps = await fetch_all("SELECT bp.title FROM bp_rewards bpr JOIN bp_levels bpl ON bpr.level_id = bpl.id JOIN battle_passes bp ON bpl.bp_id = bp.id WHERE bpr.card_id = ?", (card_id,))
    if bps: sources.append("🎟 Батл-Пасс: " + ", ".join(list(set([b['title'] for b in bps]))))
    craft = await fetch_one("SELECT id FROM craft_recipes WHERE target_card_id = ?", (card_id,))
    if craft: sources.append("🔨 Мастерская Крафта")
    if not sources: return "Невозможно получить (Эксклюзив или Секрет)"
    return "\n".join(f"  └ {s}" for s in sources)

# ========================================================================
# ЛОГИКА ШАНСОВ И МАГАЗИНА И PITY
# ========================================================================
async def calculate_chance_weights(luck_mult: float = 1.0, user_luck: float = 1.0):
    query = "SELECT * FROM cards WHERE drop_chance > 0 AND rarity NOT IN ('Leaderboard', 'Secret') AND id NOT IN (SELECT card_id FROM seed_pack_cards)"
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
            if settings and (now - settings['last_restock'] >= 1.5 * 3600): await restock_shop()
        except Exception as e: logging.error(f"Shop restock error: {e}")
        await asyncio.sleep(60)

async def give_multiple_cards(user_id: int, count: int) -> list:
    luck_mult, _ = await get_active_events()
    user = await fetch_one("SELECT * FROM users WHERE id=?", (user_id,))
    
    user_luck = 1.0
    if user and user.get('vip_status'): user_luck *= 1.3
    if user and user.get('perm_1_5x_luck'): user_luck *= 1.5
    
    pm = user['pity_mythic'] if user else 0
    ps = user['pity_super'] if user else 0
    query = "SELECT * FROM cards WHERE drop_chance > 0 AND rarity NOT IN ('Leaderboard', 'Secret') AND id NOT IN (SELECT card_id FROM seed_pack_cards)"
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

        if card['rarity'] == 'Super': ps = 0; pm += 1
        elif card['rarity'] == 'Mythic': pm = 0; ps += 1
        else: ps += 1; pm += 1

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
                for lb_type in ['trophies', 'coins', 'cards']:
                    if lb_type == 'trophies': top_users = await fetch_all("SELECT id, trophies as score, username, first_name FROM users WHERE id != ? ORDER BY trophies DESC LIMIT 20", (SUPER_ADMIN_ID,))
                    elif lb_type == 'coins': top_users = await fetch_all("SELECT id, total_coins as score, username, first_name FROM users WHERE id != ? ORDER BY total_coins DESC LIMIT 20", (SUPER_ADMIN_ID,))
                    else: top_users = await fetch_all("SELECT u.id, SUM(i.count) as score, u.username, u.first_name FROM users u JOIN inventory i ON u.id = i.user_id WHERE u.id != ? GROUP BY u.id ORDER BY score DESC LIMIT 20", (SUPER_ADMIN_ID,))

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
        except Exception as e: logging.error(f"LB Rewards error: {e}")
        await asyncio.sleep(600)

async def auto_backup_db():
    while True:
        await asyncio.sleep(4 * 3600) 
        try:
            file = FSInputFile(DB_NAME)
            await bot.send_document(SUPER_ADMIN_ID, file, caption="📦 Автоматический бэкап БД (каждые 4 часа).")
        except Exception as e: logging.error(f"Auto DB Backup error: {e}")

async def endless_leaderboard_task():
    while True:
        try:
            settings = await fetch_one("SELECT * FROM endless_settings WHERE id = 1")
            if settings and settings['is_active']:
                now = time.time()
                last_reset = settings['last_lb_reset']
                if now - last_reset >= 3 * 24 * 3600:
                    top_users = await fetch_all("SELECT id, endless_max_wave, username, first_name FROM users WHERE endless_max_wave > 0 AND id != ? ORDER BY endless_max_wave DESC LIMIT 50", (SUPER_ADMIN_ID,))
                    if top_users:
                        for idx, user in enumerate(top_users):
                            pos = idx + 1
                            r_start_end = await fetch_all("SELECT * FROM endless_lb_rewards WHERE rank_start <= ? AND rank_end >= ?", (pos, pos))
                            reward_msgs_ru = []
                            for r in r_start_end:
                                if r['reward_type'] == 'shekels':
                                    await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (r['amount'], user['id']))
                                    reward_msgs_ru.append(f"💰 {r['amount']} Шекелей")
                                elif r['reward_type'] == 'rbucks':
                                    await execute_db("UPDATE users SET r_bucks = r_bucks + ? WHERE id = ?", (r['amount'], user['id']))
                                    reward_msgs_ru.append(f"💎 {r['amount']} R$")
                                elif r['reward_type'] == 'shards':
                                    await execute_db("UPDATE users SET soul_shards = soul_shards + ? WHERE id = ?", (r['amount'], user['id']))
                                    reward_msgs_ru.append(f"🔮 {r['amount']} Осколков Душ")
                                elif r['reward_type'] == 'pack':
                                    await execute_db("INSERT INTO user_seed_packs (user_id, pack_id, count) VALUES (?, ?, ?) ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + ?", (user['id'], r['item_id'], r['amount'], r['amount']))
                                    pack = await fetch_one("SELECT title FROM seed_packs WHERE id = ?", (r['item_id'],))
                                    pt = pack['title'] if pack else 'Пак'
                                    reward_msgs_ru.append(f"📦 Сид-Пак «{pt}» x{r['amount']}")
                                elif r['reward_type'] == 'card':
                                    for _ in range(max(1, r['amount'])):
                                        c_info = await fetch_one("SELECT name, rarity FROM cards WHERE id = ?", (r['item_id'],))
                                        if c_info:
                                            _, serial, _ = await give_card_to_user(user['id'], r['item_id'], r['mutation'], c_info['rarity'])
                                            mut_str = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                                            s_str = f" [#{serial:04d}]" if serial > 0 else ""
                                            reward_msgs_ru.append(f"🃏 {mut_str} {c_info['name']}{s_str}")
                                            
                            if reward_msgs_ru:
                                msg_text = f"🏆 <b>ИТОГИ СЕЗОНА ENDLESS MODE!</b> 🏆\n\nВы заняли <b>{pos} место</b> в мире (Макс. волна: {user['endless_max_wave']})!\n\n🎁 <b>Награда:</b>\n" + "\n".join([f"🔸 {m}" for m in reward_msgs_ru])
                                try: await bot.send_message(user['id'], msg_text)
                                except: pass
                                
                    await execute_db("UPDATE users SET endless_max_wave = 0")
                    await execute_db("DELETE FROM endless_runs")
                    await execute_db("UPDATE endless_settings SET last_lb_reset = ? WHERE id = 1", (now,))
                    await notify_super_admin("🔄 Сезон Endless Mode успешно сброшен, награды выданы!")
        except Exception as e:
            logging.error(f"Endless Leaderboard Reset Error: {e}")
        await asyncio.sleep(3600)

# ========================================================================
# ОСНОВНЫЕ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ И НАСТРОЙКИ
# ========================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if await check_ban(message.from_user.id): return
    await execute_db("INSERT OR IGNORE INTO users (id, username, first_name) VALUES (?, ?, ?)", (message.from_user.id, message.from_user.username, message.from_user.first_name))
    await execute_db("UPDATE users SET username = ?, first_name = ? WHERE id = ?", (message.from_user.username, message.from_user.first_name, message.from_user.id))
    await log_user_action(message.from_user.id, "Открыл главное меню (/start)")
    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    text = (
        "👋 <b>Добро пожаловать в Card Battle Bot!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Собери свою колоду уникальных юнитов, участвуй в ивентах и поднимай кубки на арене!\n\n"
        "📖 <b>ОГРОМНОЕ РУКОВОДСТВО ПО ИГРЕ:</b> /help\n"
        "📞 Тех.поддержка: @ggtdcards_support\n"
        "📰 Новости: @ggtdcardsnews\n"
        "📧 Почта: ggtdcards@gmail.com\n\n"
        "👇 <i>Используй красивое меню снизу для навигации:</i>"
    )
    await message.answer(text, reply_markup=get_main_keyboard(adm, sgn))

@dp.message(F.text == BTN_ENDLESS_MENU)
async def cmd_endless_menu(message: types.Message):
    if await check_ban(message.from_user.id): return
    settings = await fetch_one("SELECT is_active, last_lb_reset FROM endless_settings WHERE id = 1")
    if not settings or not settings['is_active']:
        return await message.answer("❌ <b>Endless Mode сейчас отключен администрацией!</b>")
        
    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    
    now = time.time()
    time_left = max(0, (settings['last_lb_reset'] + 3*24*3600) - now)
    h, rem = divmod(time_left, 3600)
    m, _ = divmod(rem, 60)
    
    text = (
        "♾ <b>ENDLESS MODE (Бесконечный режим)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Сражайся с бесконечными волнами врагов, получай Осколки Душ и эксклюзивные награды!\n\n"
        "💀 <i>Здоровье не восстанавливается между волнами!</i>\n"
        f"⏳ <b>До конца сезона:</b> {int(h)}ч {int(m)}м\n"
    )
    await message.answer(text, reply_markup=get_endless_keyboard(adm, sgn))

@dp.message(F.text == BTN_NORMAL_MODE)
async def cmd_normal_mode(message: types.Message):
    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    await message.answer("🔙 Вы вернулись в <b>Обычный режим</b>.", reply_markup=get_main_keyboard(adm, sgn))

@dp.message(Command("updatelog"))
async def cmd_updatelog(message: types.Message):
    if await check_ban(message.from_user.id): return
    text = f"📰 <b>ИСТОРИЯ ОБНОВЛЕНИЙ (Стр. 1/{len(UPDATE_LOGS)})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n{UPDATE_LOGS[0]}"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if len(UPDATE_LOGS) > 1: kb.inline_keyboard.append([InlineKeyboardButton(text="➡️", callback_data="updatelog_1")])
    await message.answer(text, reply_markup=kb if kb.inline_keyboard else None)

@dp.callback_query(F.data.startswith("updatelog_"))
async def cb_updatelog(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[1])
    text = f"📰 <b>ИСТОРИЯ ОБНОВЛЕНИЙ (Стр. {page+1}/{len(UPDATE_LOGS)})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n{UPDATE_LOGS[page]}"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    nav = []
    if page > 0: nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"updatelog_{page-1}"))
    if page < len(UPDATE_LOGS) - 1: nav.append(InlineKeyboardButton(text="➡️", callback_data=f"updatelog_{page+1}"))
    if nav: kb.inline_keyboard.append(nav)
    try: await callback.message.edit_text(text, reply_markup=kb if kb.inline_keyboard else None)
    except: pass
    await callback.answer()

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if await check_ban(message.from_user.id): return
    guide = (
        "📖 <b>ОГРОМНОЕ РУКОВОДСТВО ПО CARD BATTLE BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Добро пожаловать в карточную арену! Ниже описаны все основные механики нашего бота:\n\n"
        "⚔️ <b>ОСНОВНОЙ РЕЖИМ БОЯ (PvE и PvP)</b>\n"
        "• Бои против ИИ приносят <b>Шекели 💰</b>, кубки и опыт БП.\n"
        "• <b>PvP Дуэли</b> позволяют сразиться с друзьями (без изменения рейтинга) или через автоподбор за кубки.\n\n"
        "♾ <b>ENDLESS MODE (Бесконечный режим)</b>\n"
        "• Хардкорный режим, где здоровье не восстанавливается между волнами!\n"
        "• За прохождение волн вы получаете Осколки Душ 🔮 для покупки эксклюзива.\n"
        "• Топ игроков сбрасывается каждые 3 дня, выдавая огромные призы!\n\n"
        "💎 <b>РЕДКОСТИ И МУТАЦИИ КАРТ</b>\n"
        "⚪ Basic | 🟢 Uncommon | 🔵 Rare | 🟣 Epic | 🟡 Legendary | 🔴 Mythic | 🌈 Super | 🌸 Exclusive | 👑 Leaderboard\n"
        "• ⭐ <b>Золотая мутация</b> (+10%)\n• 🌈 <b>Радужная мутация</b> (+20%)\n\n"
        "⚡ <b>СИСТЕМА ГАРАНТИЙ (PITY)</b>\n"
        "└ Гарантированный <b>Мифик 🔴</b>: каждые 1000 открытий.\n"
        "└ Гарантированный <b>Супер 🌈</b>: каждые 10000 открытий.\n\n"
        "🔨 <b>КРАФТ И СЛИЯНИЕ</b>\n"
        "• В меню Крафта можно сливать 8 одинаковых обычных карт для получения ⭐ Золотой!\n\n"
        "📞 <b>КОНТАКТЫ И СВЯЗЬ:</b>\n"
        "• 📰 Новости и обновления: @ggtdcardsnews\n"
        "• 💬 Наш чат поддержки: @ggtdcards_support\n"
    )
    await message.answer(guide)

@dp.message(Command("donate"))
async def cmd_donate(message: types.Message):
    if await check_ban(message.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 F2P Магазин (Бусты)", callback_data="don_f2p")],
        [InlineKeyboardButton(text="💎 Купить R$", callback_data="don_buy_rs")]
    ])
    user = await fetch_one("SELECT r_bucks FROM users WHERE id = ?", (message.from_user.id,))
    rb = user['r_bucks'] if user else 0
    await message.answer(f"💎 <b>ДОНАТ МАГАЗИН</b>\nВаш баланс: <b>{rb} R$</b>\nВыберите раздел:", reply_markup=kb)

@dp.callback_query(F.data.startswith("don_"))
async def cb_donate_menu(callback: types.CallbackQuery):
    section = callback.data.replace("don_", "")
    user = await fetch_one("SELECT r_bucks, coins FROM users WHERE id = ?", (callback.from_user.id,))
    rb = user.get('r_bucks', 0)
    
    if section == "main":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 F2P Магазин (Бусты)", callback_data="don_f2p")],
            [InlineKeyboardButton(text="💎 Купить R$", callback_data="don_buy_rs")]
        ])
        try: await callback.message.edit_text(f"💎 <b>ДОНАТ МАГАЗИН</b>\nВаш баланс: <b>{rb} R$</b>\nВыберите раздел:", reply_markup=kb)
        except: pass
        
    elif section == "f2p":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="129 R$ = Навсегда Х2 Шекели", callback_data="buy_f2p_shekels")],
            [InlineKeyboardButton(text="159 R$ = Навсегда Х2 Опыт БП", callback_data="buy_f2p_bpxp")],
            [InlineKeyboardButton(text="159 R$ = 5-й слот юнита", callback_data="buy_f2p_slot")],
            [InlineKeyboardButton(text="129 R$ = Навсегда Х1.5 Удача", callback_data="buy_f2p_luck")],
            [InlineKeyboardButton(text="339 R$ = VIP Статус", callback_data="buy_f2p_vip")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="don_main")]
        ])
        try: await callback.message.edit_text(f"🎁 <b>F2P Магазин</b>\nБаланс: <b>{rb} R$</b>\n\nVIP включает: 1.3х Удача, 1.5х Шекели, 1.5х Опыт БП, скидку 10%, 5-й слот и крафт апгрейдов за 4 карты!\nВыберите товар:", reply_markup=kb)
        except: pass
        
    elif section == "buy_rs":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Купить 1 R$ (1000 💰)", callback_data="buy_rs_1")],
            [InlineKeyboardButton(text="Купить 10 R$ (10000 💰)", callback_data="buy_rs_10")],
            [InlineKeyboardButton(text="Купить 50 R$ (50000 💰)", callback_data="buy_rs_50")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="don_main")]
        ])
        sh = user.get('coins', 0)
        try: await callback.message.edit_text(f"💎 <b>Покупка R$</b>\nКурс: 1 R$ = 1000 Шекелей.\n\nВаши Шекели: <b>{sh} 💰</b>\nВаши R$: <b>{rb} 💎</b>\nВыберите:", reply_markup=kb)
        except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("buy_f2p_"))
async def cb_buy_f2p(callback: types.CallbackQuery):
    item = callback.data.replace("buy_f2p_", "")
    user_id = callback.from_user.id
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    
    prices = {"shekels": 129, "bpxp": 159, "slot": 159, "luck": 129, "vip": 339}
    cols = {"shekels": "perm_2x_shekels", "bpxp": "perm_2x_bpxp", "slot": "perm_5th_slot", "luck": "perm_1_5x_luck", "vip": "vip_status"}
    
    price = prices[item]
    col = cols[item]
    
    if user.get(col): return await callback.answer("У вас уже куплен этот товар навсегда!", show_alert=True)
    if user.get('r_bucks', 0) < price: return await callback.answer("❌ Недостаточно R$!", show_alert=True)
        
    await execute_db(f"UPDATE users SET r_bucks = r_bucks - ?, {col} = 1 WHERE id = ?", (price, user_id))
    if item == "vip": await execute_db(f"UPDATE users SET perm_5th_slot = 1 WHERE id = ?", (user_id,))
    await callback.answer("✅ Успешная покупка!", show_alert=True)
    await cb_donate_menu(callback.model_copy(update={"data": "don_f2p"}))

@dp.callback_query(F.data.startswith("buy_rs_"))
async def cb_buy_rs(callback: types.CallbackQuery):
    amount = int(callback.data.replace("buy_rs_", ""))
    cost = amount * 1000
    user_id = callback.from_user.id
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (user_id,))
    
    if user['coins'] < cost: return await callback.answer("❌ Недостаточно Шекелей!", show_alert=True)
    await execute_db("UPDATE users SET coins = coins - ?, r_bucks = r_bucks + ? WHERE id = ?", (cost, amount, user_id))
    await callback.answer(f"✅ Вы купили {amount} R$!", show_alert=True)
    await cb_donate_menu(callback.model_copy(update={"data": "don_buy_rs"}))

@dp.message(F.text == BTN_SET)
async def cmd_settings(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id=?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    
    text = "⚙️ <b>НАСТРОЙКИ АККАУНТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Фильтр Магазина", callback_data="set_shop_filters")],
        [InlineKeyboardButton(text="🧬 Модификаторы боя (PvE)", callback_data="set_modifiers")],
        [InlineKeyboardButton(text=f"🎉 Ивенты: {'🔔 Вкл' if user['notif_events'] else '🔕 Выкл'}", callback_data="set_toggle_events")],
        [InlineKeyboardButton(text=f"📜 Квесты: {'🔔 Вкл' if user['notif_quests'] else '🔕 Выкл'}", callback_data="set_toggle_quests")],
        [InlineKeyboardButton(text=f"📢 Анонсы: {'🔔 Вкл' if user['notif_announces'] else '🔕 Выкл'}", callback_data="set_toggle_announces")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "set_modifiers")
async def cb_modifiers_menu(callback: types.CallbackQuery):
    user = await fetch_one("SELECT * FROM users WHERE id=?", (callback.from_user.id,))
    def s(val): return "✅ Вкл" if val else "❌ Выкл"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔴 1.5x ХП Врагов ({s(user.get('mod_enemy_hp'))})", callback_data="set_mod_enemy_hp")],
        [InlineKeyboardButton(text=f"🔴 ИИ бьет 2 раза ({s(user.get('mod_enemy_atk_all'))})", callback_data="set_mod_enemy_atk_all")],
        [InlineKeyboardButton(text=f"🔴 1.2x Статы ИИ ({s(user.get('mod_enemy_stats'))})", callback_data="set_mod_enemy_stats")],
        [InlineKeyboardButton(text=f"🟢 Игрок бьет 2 раза ({s(user.get('mod_player_atk_all'))})", callback_data="set_mod_player_atk_all")],
        [InlineKeyboardButton(text=f"🟢 Ручной выбор атаки ({s(user.get('mod_manual_atk'))})", callback_data="set_mod_manual_atk")],
        [InlineKeyboardButton(text=f"🟢 1.3x ХП Игрока ({s(user.get('mod_player_hp'))})", callback_data="set_mod_player_hp")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="set_main")]
    ])
    text = "🧬 <b>МОДИФИКАТОРЫ БОЯ (PvE)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n🔴 <b>Дебаффы</b> повышают награды.\n🟢 <b>Баффы</b> снижают награды."
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
    text = "🛒 <b>ФИЛЬТР УВЕДОМЛЕНИЙ МАГАЗИНА</b>"
    def b(name_ru, col):
        st = "🔔" if user.get(col, 1) else "🔕"
        return InlineKeyboardButton(text=f"{name_ru} {st}", callback_data=f"set_shopfilt_{col}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [b("1 Случайная", "notif_1_rnd"), b("3 Случайные", "notif_3_rnd")],
        [b("5 Случайных", "notif_5_rnd"), b("10 Случайных", "notif_10_rnd")],
        [b("100 Случайных", "notif_100_rnd"), b("Легендарная", "notif_rnd_leg")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="set_main")]
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
    await cmd_settings(callback.message)
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.message(Command("profile"), F.chat.type == "private")
@dp.message(F.text == BTN_PROF)
async def cmd_profile(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    
    rank = await get_user_rank(user['trophies'])
    total_cards = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE user_id = ?", (user['id'],))
    name = get_display_name(user)
    title_str = await get_user_titles_str(user['id'])
    
    active_bp = await fetch_one("SELECT bp.title, ubp.level, ubp.xp FROM user_bp ubp JOIN battle_passes bp ON ubp.bp_id = bp.id WHERE ubp.user_id = ? AND ubp.is_active = 1", (user['id'],))
    bp_text = f"<b>{active_bp['title']}</b> (Ур. {active_bp['level']})" if active_bp else "<i>Нет активного БП</i>"

    text = (
        f"👤 Профиль игрока <b>{name}</b>{title_str}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖 <b>Ранг:</b> {rank['name']}\n🏆 <b>Кубки:</b> {user['trophies']}\n"
        f"💰 <b>Шекелей:</b> {user['coins']}\n💎 <b>R$:</b> {user.get('r_bucks', 0)}\n🔮 <b>Осколки Душ:</b> {user.get('soul_shards', 0)}\n"
        f"🃏 <b>Всего карт:</b> {total_cards['s'] or 0}\n🎟 <b>БП:</b> {bp_text}\n"
        f"♾ <b>Макс. Волна (Endless):</b> {user.get('endless_max_wave', 0)}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    text += (
        f"🔮 <b>Гарант на Мифик:</b> {make_progress_bar(user['pity_mythic'], 1000, 8)} ({user['pity_mythic']}/1000)\n"
        f"🌠 <b>Гарант на Супер:</b> {make_progress_bar(user['pity_super'], 10000, 8)} ({user['pity_super']}/10000)\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
        
    text += "⚔️ <b>Экипировка:</b>\n"
    slots = ['equip1', 'equip2', 'equip3', 'equip4']
    if user.get('perm_5th_slot') or user.get('vip_status'): slots.append('equip5')
        
    for i, slot in enumerate(slots):
        inv_id = user.get(slot, 0)
        role_label = f"{i+1}️⃣ "
        if inv_id != 0:
            row = await fetch_one("SELECT c.id, c.name, c.rarity, c.class_type, c.damage, c.hp, c.booster_dmg_mult, c.booster_hp_mult, i.mutation, i.serial_number, i.signed_by FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.id = ? AND i.user_id = ? AND i.count > 0", (inv_id, user['id']))
            if row:
                mult = get_mutation_multiplier(row['mutation'])
                mut_str = " 🌈" if row['mutation'] == "Rainbow" else (" ⭐" if row['mutation'] == 'Gold' else "")
                c_dict = dict(row)
                if row['signed_by'] > 0:
                    signer = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (row['signed_by'],))
                    if signer: c_dict['signer_name'] = get_display_name(signer)
                
                n = format_card_name(c_dict)
                if row['class_type'] == 'Booster': text += f" {role_label}{n}{mut_str}\n      └ <i>Бафф: DMG x{round(row['booster_dmg_mult']*mult, 2)} | HP x{round(row['booster_hp_mult']*mult, 2)}</i>\n"
                elif row['class_type'] == 'Healer': text += f" {role_label}{n}{mut_str}\n      └ <i>Статы: 💗 Лечение: {int(row['damage']*mult)} | ❤️ Здоровье: {int(row['hp']*mult)}</i>\n"
                else: text += f" {role_label}{n}{mut_str}\n      └ <i>Статы: ⚔️ Урон: {int(row['damage']*mult)} | ❤️ Здоровье: {int(row['hp']*mult)}</i>\n"
            else:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ?", (user['id'],))
                text += f" {role_label}[Слот Пуст]\n"
        else:
            text += f" {role_label}[Слот Пуст]\n"
            
    await message.answer(text)

@dp.message(Command("quests"))
@dp.message(F.text == BTN_QUESTS)
async def cmd_quests(message: types.Message):
    if await check_ban(message.from_user.id): return
    user_id = message.from_user.id
    await generate_dynamic_quests(user_id)
    user = await fetch_one("SELECT * FROM user_dynamic_quests WHERE user_id = ?", (user_id,))
    if not user: return await message.answer("Ошибка системы квестов.")
    
    now = time.time()
    if user['reset_time'] < now:
        await generate_dynamic_quests(user_id)
        user = await fetch_one("SELECT * FROM user_dynamic_quests WHERE user_id = ?", (user_id,))
        
    left = int(user['reset_time'] - now)
    m, s = divmod(left, 60)
    
    text = f"📜 <b>ЕЖЕЧАСНЫЕ КВЕСТЫ</b>\n<i>Выполни все 3 задания за час, чтобы получить 1500 💰 Шекелей и 1 Сид-Пак!</i>\n⏳ <b>До обновления:</b> {m} мин. {s} сек.\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    q_data = {t['id']: t['desc'] for t in QUEST_TEMPLATES}
    for i in range(1, 4):
        q_id = user[f'q{i}_id']; q_target = user[f'q{i}_target']; q_prog = user[f'q{i}_prog']
        desc = q_data.get(q_id, "Задание").format(q_target)
        status = "✅" if q_prog >= q_target else "❌"
        text += f"{i}️⃣ <b>{desc}:</b>\n{make_progress_bar(q_prog, q_target, 8)} {q_prog}/{q_target} {status}\n\n"
        
    await message.answer(text)

@dp.message(Command("top"))
@dp.message(F.text == BTN_TOP)
async def cmd_top(message: types.Message):
    if await check_ban(message.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Кубки (Сезон)", callback_data="top_trophies")],
        [InlineKeyboardButton(text="💰 Монеты (Все время)", callback_data="top_coins")],
        [InlineKeyboardButton(text="🃏 Карты (Все время)", callback_data="top_cards")]
    ])
    await message.answer("🏆 <b>МИРОВЫЕ РЕЙТИНГИ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите категорию лидерборда:", reply_markup=kb)

@dp.callback_query(F.data.startswith("top_"))
async def cb_top_view(callback: types.CallbackQuery):
    lb_type = callback.data.split("_")[1]
    
    if lb_type == 'trophies':
        top_users = await fetch_all("SELECT username, first_name, id, trophies as score FROM users WHERE id != ? ORDER BY trophies DESC LIMIT 20", (SUPER_ADMIN_ID,))
        title_ru = "🏆 <b>МИРОВОЙ РЕЙТИНГ: КУБКИ (Топ-20)</b>"; unit = "🏆"
    elif lb_type == 'coins':
        top_users = await fetch_all("SELECT username, first_name, id, total_coins as score FROM users WHERE id != ? ORDER BY total_coins DESC LIMIT 20", (SUPER_ADMIN_ID,))
        title_ru = "💰 <b>МИРОВОЙ РЕЙТИНГ: ШЕКЕЛИ (Топ-20)</b>"; unit = "💰"
    else:
        top_users = await fetch_all("SELECT u.id, u.username, u.first_name, SUM(i.count) as score FROM users u JOIN inventory i ON u.id = i.user_id WHERE u.id != ? GROUP BY u.id ORDER BY score DESC LIMIT 20", (SUPER_ADMIN_ID,))
        title_ru = "🃏 <b>МИРОВОЙ РЕЙТИНГ: КАРТЫ (Топ-20)</b>"; unit = "🃏"

    text = f"{title_ru}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for i, u in enumerate(top_users, 1):
        name = get_display_name(u)
        title_str = await get_user_titles_str(u['id'])
        score_val = u['score'] if u['score'] is not None else 0
        med = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
        if lb_type == 'trophies':
            rank = await get_user_rank(score_val)
            text += f"{med} <b>{i}. {name}</b>{title_str} — {score_val} {unit} <i>({rank['name']})</i>\n"
        else:
            text += f"{med} <b>{i}. {name}</b>{title_str} — {score_val} {unit}\n"
        
    text += "\n🎁 <b>Награды (выдаются каждые 2 дня):</b>\n"
    brackets = ["1", "2", "3", "4_9", "10_20"]
    b_names = {"1": "🥇 1 место", "2": "🥈 2 место", "3": "🥉 3 место", "4_9": "🏅 4-9 места", "10_20": "🎖 10-20 места"}
    
    has_rewards = False
    for b in brackets:
        b_rewards = await fetch_all("SELECT * FROM lb_rewards WHERE bracket = ? AND lb_type = ?", (b, lb_type))
        if b_rewards:
            has_rewards = True
            r_strs = []
            for r in b_rewards:
                if r['reward_type'] == 'shekels': r_strs.append(f"{r['amount']} 💰")
                elif r['reward_type'] == 'card':
                    c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['card_id'],))
                    mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                    r_strs.append(f"{mut} {c['name'] if c else 'Unknown'}")
            text += f"└ {b_names[b]}: {', '.join(r_strs)}\n"
            
    if not has_rewards: text += "<i>Награды пока не настроены.</i>"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 К выбору", callback_data="top_menu")]])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data == "top_menu")
async def cb_top_menu(callback: types.CallbackQuery):
    await cmd_top(callback.message)
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.message(Command("shop"))
@dp.message(F.text == BTN_SHOP)
async def cmd_shop(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    
    if not items: return await message.answer("🛒 <b>Магазин пока пуст.</b>\nЗавоз осуществляется каждые полтора часа. Жди уведомления!")
        
    bal = user['coins']
    discount = 0.9 if user.get('vip_status') else 1.0
    
    text = f"🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН</b>\n💰 Твой баланс: <b>{bal} Шекелей</b>\n<i>(Товары общие для всех. Кто успел, тот и купил!)</i>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if discount < 1.0: text += "💎 <b>У вас активна VIP-скидка 10%!</b>\n\n"
        
    kb = []
    for i, item in enumerate(items, 1):
        final_price = int(item['price'] * discount)
        if discount < 1.0: text += f"📦 <b>{item['name']}</b>\n      └ 💵 Цена: <s>{item['price']}</s> <b>{final_price} 💰</b> | Остаток: <b>{item['stock']} шт.</b>\n\n"
        else: text += f"📦 <b>{item['name']}</b>\n      └ 💵 Цена: <b>{item['price']} 💰</b> | Остаток: <b>{item['stock']} шт.</b>\n\n"
        kb.append([InlineKeyboardButton(text=f"Купить: {item['name']} ({final_price} 💰)", callback_data=f"buy_shop_{item['id']}")])
        
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_shop_"))
async def callback_buy_shop(callback: types.CallbackQuery):
    shop_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    item = await fetch_one("SELECT * FROM shop_items WHERE id = ?", (shop_id,))
    if not item or item['stock'] <= 0: return await callback.answer("❌ Этот товар закончился!", show_alert=True)
    
    discount = 0.9 if user.get('vip_status') else 1.0
    final_price = int(item['price'] * discount)
    bal_col = 'coins'
    
    if user[bal_col] < final_price: return await callback.answer("❌ Недостаточно средств!", show_alert=True)
    
    await execute_db(f"UPDATE users SET {bal_col} = {bal_col} - ? WHERE id = ?", (final_price, user_id))
    await execute_db("UPDATE shop_items SET stock = stock - 1 WHERE id = ?", (shop_id,))
    await add_quest_progress_new(user_id, 'q_shop_buy', 1)
    
    i_type = item['item_type']
    if i_type.endswith("_rnd"):
        count = int(i_type.split("_")[0])
        won = await give_multiple_cards(user_id, count)
        await add_quest_progress_new(user_id, 'q_open', count)
        pity_pulls = [c for c in won if c.get('is_pity')]
        
        if count == 1: 
            mut_str = "🌈 " if won[0]['mutation'] == 'Rainbow' else ("⭐ " if won[0]['mutation'] == 'Gold' else "")
            msg = f"✨ <b>Грандиозная покупка!</b>\nВы выбили: {mut_str}{format_card_name(won[0])}"
            if won[0].get('is_pity'): msg = f"🌟 <b>СИСТЕМА PITY! Гарантированный {won[0]['pity_type']}!</b> 🌟\n\n" + msg
        else: 
            msg = f"🛍 <b>Успешно! Вы открыли пак из {count} карт!</b>\nПосмотрите новинки в 🎒 Инвентаре."
            if pity_pulls:
                p_names = ", ".join([f"{c['name']} (Pity {c['pity_type']})" for c in pity_pulls])
                msg += f"\n\n🌟 <b>Сработал PITY! Гарантированные редчайшие карты:</b>\n{p_names}!"
        await callback.message.answer(msg)
        
    elif i_type.startswith("rnd_"):
        rarity_map = {"rnd_leg": "Legendary", "rnd_myth": "Mythic", "rnd_sup": "Super"}
        target_rarity = rarity_map[i_type]
        query = "SELECT * FROM cards WHERE rarity = ? AND id NOT IN (SELECT card_id FROM seed_pack_cards)"
        all_cards = await fetch_all(query, (target_rarity,))
        if not all_cards:
            await execute_db(f"UPDATE users SET {bal_col} = {bal_col} + ? WHERE id = ?", (final_price, user_id))
            return await callback.message.answer("❌ Ошибка БД.")
            
        won_card = random.choice(all_cards)
        mut = roll_mutation()
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        won_card['serial_number'] = serial
        won_card['signed_by'] = 0
        await add_quest_progress_new(user_id, 'q_open', 1)
            
        pm = user['pity_mythic']; ps = user['pity_super']
        if target_rarity == 'Super': ps = 0; pm += 1
        elif target_rarity == 'Mythic': pm = 0; ps += 1
        else: ps += 1; pm += 1
        await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
        
        mut_str = "🌈 Радужная" if mut == 'Rainbow' else ("⭐ Золотая" if mut == 'Gold' else "Обычная")
        await callback.message.answer(f"✨ <b>Успешная покупка ГАРАНТА!</b>\nВы выбили: {format_card_name(won_card)}\nМутация: <b>{mut_str}</b>")

    await log_user_action(user_id, f"Купил в магазине: {i_type} ({final_price})")
    fake_msg = callback.message
    fake_msg.from_user = callback.from_user
    await cmd_shop(fake_msg)
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.message(Command("getcard"))
@dp.message(F.text == BTN_DRAW)
async def cmd_getcard(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    if user['id'] in user_trades: return await message.answer("❌ Завершите обмен перед выбиванием!")
    
    luck_mult, cd_mult = await get_active_events()
    base_cooldown = 3 * 60
    actual_cooldown = int(base_cooldown / cd_mult)
    now = time.time()
    passed = now - user['last_getcard']
    
    if passed < actual_cooldown:
        left = int(actual_cooldown - passed)
        mins, secs = divmod(left, 60)
        return await message.answer(f"⏳ <b>Колода перемешивается!</b>\nОжидай: <b>{mins} мин. {secs} сек.</b>")
        
    won_list = await give_multiple_cards(user['id'], 1)
    if not won_list: return await message.answer("😔 В базе нет карт для этой гачи.")
    won_card = won_list[0]
        
    await execute_db("UPDATE users SET last_getcard = ? WHERE id = ?", (now, user['id']))
    await add_quest_progress_new(user['id'], 'q_open', 1)
    await log_user_action(user['id'], f"Выбил карту: {won_card['name']} (ID:{won_card['id']}, Мутация: {won_card['mutation']})")
    
    n_fmt = format_card_name(won_card)
    rarity_text = format_rarity_display(won_card['rarity'])
    mutation = won_card['mutation']
    mult = get_mutation_multiplier(mutation)
    mut_str = ""
    if mutation == "Gold": mut_str = "⭐ <b>ЗОЛОТАЯ МУТАЦИЯ! (+10% Статов)</b>\n"
    elif mutation == "Rainbow": mut_str = "🌈 <b>РАДУЖНАЯ МУТАЦИЯ! (+20% Статов)</b>\n"
    
    msg = ""
    if won_card.get('is_pity'): msg += f"🌟 <b>СИСТЕМА PITY! ГАРАНТИРОВАННЫЙ {won_card['pity_type']}!</b> 🌟\n\n"
        
    msg += f"🎉 <b>ВЫ ВЫБИЛИ КАРТУ!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n{mut_str}🃏 {n_fmt}\n💎 <b>Редкость:</b> {rarity_text}\n"
    if won_card['class_type'] == 'Booster': msg += f"✨ <b>БУСТЕР</b>\n   └ Бафф DMG: <b>x{round(won_card['booster_dmg_mult']*mult, 2)}</b> | HP: <b>x{round(won_card['booster_hp_mult']*mult, 2)}</b>\n"
    elif won_card['class_type'] == 'Healer': msg += f"💗 <b>Лечение:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n"
    else: msg += f"⚔️ <b>Урон:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n"
        
    if luck_mult > 1.0 and won_card['drop_chance'] < 15.0: msg += f"\n🍀 <i>Сработал ивент удачи!</i>"
        
    try:
        if won_card.get('photo_id'): await message.answer_photo(photo=won_card['photo_id'], caption=msg)
        else: await message.answer(msg)
    except Exception as e:
        logging.error(f"Draw photo error: {e}")
        await message.answer(msg)

async def get_index_text(user_id: int, page: int = 0, items_per_page: int = 8):
    query = "SELECT * FROM cards WHERE rarity != 'Secret' AND hide_in_index = 0"
    all_cards = await fetch_all(query)
    user_inv = await fetch_all("SELECT DISTINCT card_id FROM inventory WHERE user_id = ?", (user_id,))
    user_card_ids = [item['card_id'] for item in user_inv]
    recipes = await fetch_all("SELECT target_card_id FROM craft_recipes")
    crafted_ids = [r['target_card_id'] for r in recipes]
    
    if not all_cards: return "Индекс пуст.", None
    
    user = await fetch_one("SELECT vip_status, perm_1_5x_luck FROM users WHERE id = ?", (user_id,))
    user_luck = 1.0
    if user and user.get('vip_status'): user_luck *= 1.3
    if user and user.get('perm_1_5x_luck'): user_luck *= 1.5
    
    luck_mult, _ = await get_active_events()
    total_luck = luck_mult * user_luck
    weights_dict, total_w = await calculate_chance_weights(luck_mult, user_luck)
    
    pack_cards = await fetch_all("SELECT spc.card_id, spc.drop_chance as pack_chance, sp.title FROM seed_pack_cards spc JOIN seed_packs sp ON spc.pack_id = sp.id")
    pack_info = {pc['card_id']: pc for pc in pack_cards}
    pack_totals = {}
    for pc in pack_cards:
        w = pc['pack_chance']
        if w < 15.0: w *= total_luck
        pack_totals[pc['title']] = pack_totals.get(pc['title'], 0) + w
    
    def index_sort_key(c):
        if c['rarity'] == 'Leaderboard': return (999, c['id'])
        rw = RARITY_WEIGHT.get(c['rarity'], 0)
        return (rw, c['id'])
        
    all_cards.sort(key=index_sort_key, reverse=True)
    total_pages = max(1, math.ceil(len(all_cards) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    
    text = f"📖 <b>ОСНОВНОЙ ИНДЕКС КАРТ (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if total_luck > 1.0: text += f"🍀 <b>УДАЧА ПОВЫШЕНА (x{total_luck:.2f})!</b>\n\n"
    
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
        if c['id'] in crafted_ids: n_fmt += " [🛠 Крафт]"
        r_fmt = format_rarity_display(c['rarity'])
        
        if c['id'] in pack_info:
            p_title = pack_info[c['id']]['title']
            p_weight = pack_info[c['id']]['pack_chance']
            if p_weight < 15.0: p_weight *= total_luck
            p_total = pack_totals.get(p_title, 1)
            real_chance = (p_weight / p_total) * 100 if p_total > 0 else 0
            chance_str = f"Шанс: {real_chance:.4f}% <b>(Пак «{p_title}»)</b>"
        elif c['rarity'] == 'Leaderboard': chance_str = "Только за Топ!"
        else:
            real_chance = (weights_dict.get(c['id'], 0) / total_w) * 100 if total_w > 0 else 0
            chance_str = f"Шанс из Гачи: {real_chance:.4f}%"
        
        if c['id'] in user_card_ids:
            text += f"{i}. {n_fmt}\n      └ 💎 {r_fmt} ({chance_str})\n      └ 🌍 Существует: {total_exists} шт.{mut_str}\n\n"
        else:
            text += f"{i}. <b>???</b> (Не открыто)\n      └ 💎 {r_fmt} ({chance_str})\n      └ 🌍 Существует: {total_exists} шт.{mut_str}\n\n"
            
    kb = []
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"idx_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"idx_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("index"))
@dp.message(F.text == BTN_IDX)
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

async def get_inventory_text_and_kb(user_id: int, page: int = 0, items_per_page: int = 30):
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name
        FROM inventory i JOIN cards c ON i.card_id = c.id LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.count > 0
    """, (user_id,))
    
    toggle_row = [
        InlineKeyboardButton(text=f"🎒 Карты (Выбрано)", callback_data="ignore"),
        InlineKeyboardButton(text=f"📦 Сид-Паки", callback_data=f"inv_packs_menu")
    ]
    
    if not inv: return f"🎒 Ваш инвентарь пуст.", InlineKeyboardMarkup(inline_keyboard=[toggle_row])
        
    mutation_weight = {"Rainbow": 3, "Gold": 2, "Normal": 1}
    for item in inv:
        if item['signed_by'] != 0: item['signer_name'] = get_display_name({'username': item['username'], 'first_name': item['first_name']})
    inv.sort(key=lambda x: (x['signed_by'] > 0, RARITY_WEIGHT.get(x['rarity'], 0), mutation_weight.get(x['mutation'], 0), x['card_id']), reverse=True)
    
    total_pages = max(1, math.ceil(len(inv) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = inv[start_idx:end_idx]
    
    text = f"🎒 <b>ИНВЕНТАРЬ КАРТ (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for item in page_items:
        n_fmt = format_card_name(item).replace(" <b>[#-001]</b>", "")
        mut_emoji = "⭐ " if item['mutation'] == "Gold" else "🌈 " if item['mutation'] == "Rainbow" else ""
        text += f"• {mut_emoji}{n_fmt} — <b>{item['count']} шт.</b>\n"
        
    kb = [toggle_row]
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"inv_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("inventory"))
@dp.message(F.text == BTN_INV)
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

@dp.message(F.text == BTN_SIGN)
async def cmd_sign_card(message: types.Message):
    if await check_ban(message.from_user.id): return
    if not await is_signer(message.from_user.id): return
    if message.from_user.id in user_trades: return await message.answer("❌ Завершите обмен перед подписыванием карт!")
    
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0 AND i.signed_by = 0
    """, (message.from_user.id,))
    
    if not inv: return await message.answer("❌ Нет карт для подписи.")
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = []
    for c in inv:
        mut_emoji = "⭐ " if c['mutation'] == 'Gold' else "🌈 " if c['mutation'] == 'Rainbow' else ""
        items.append({"id": c['inv_id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {mut_emoji}{c['name']} x{c['count']}"})
        
    kb = get_pagination_keyboard(items, 0, "sgn_c", columns=1, items_per_page=8)
    await message.answer("✍️ <b>ВЫБОР КАРТЫ ДЛЯ ПОДПИСИ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите карту:", reply_markup=kb)

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
    
    if not await is_signer(user_id): return await callback.answer("Нет прав!", show_alert=True)
    
    db = await get_db_connection()
    try:
        cur = await db.execute("SELECT card_id, count, mutation, serial_number, signed_by FROM inventory WHERE id = ? AND user_id = ?", (inv_id, user_id))
        row = await cur.fetchone()
        if not row or row['count'] < 1: return await callback.answer("Not found!", show_alert=True)
        if row['signed_by'] != 0: return await callback.answer("Already signed!", show_alert=True)
        
        await db.execute("BEGIN")
        if row['count'] == 1:
            await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
            for slot in ['equip1', 'equip2', 'equip3', 'equip4', 'equip5']:
                await db.execute(f"UPDATE users SET {slot} = 0 WHERE {slot} = ?", (inv_id,))
        else:
            await db.execute("UPDATE inventory SET count = count - 1 WHERE id = ?", (inv_id,))
            
        cur2 = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = ? AND signed_by = ?", (user_id, row['card_id'], row['mutation'], row['serial_number'], user_id))
        dest = await cur2.fetchone()
        
        if dest:
            await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (dest['id'],))
        else:
            await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by) VALUES (?, ?, 1, ?, ?, ?)", (user_id, row['card_id'], row['mutation'], row['serial_number'], user_id))
        await db.commit()
    except Exception as e:
        await db.execute("ROLLBACK")
        logging.error(f"Sign error: {e}")
        return await callback.answer("Ошибка.", show_alert=True)
    finally:
        await db.close()
        
    await callback.message.delete()
    await callback.message.answer("✍️✅ <b>Успешно подписано!</b>")
    await callback.answer()

def get_equip_main_keyboard(user_info, cards_info):
    kb = []
    slots = ['equip1', 'equip2', 'equip3', 'equip4']
    if user_info.get('perm_5th_slot') or user_info.get('vip_status'): slots.append('equip5')
        
    for i, slot in enumerate(slots, 1):
        inv_id = user_info.get(slot, 0)
        sl_t = f"Слот {i}"
        text = f"{sl_t} [Пусто]" if inv_id == 0 else f"{sl_t}: {cards_info.get(inv_id, f'ID: {inv_id}')}"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"eq_select_{i}")])
    kb.append([InlineKeyboardButton(text="❌ Очистить колоду", callback_data=f"eq_clear")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("equip"))
@dp.message(F.text == BTN_EQ)
async def cmd_equip(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    if message.from_user.id in user_trades: return await message.answer("❌ Завершите обмен перед экипировкой!")
    
    slots = ['equip1', 'equip2', 'equip3', 'equip4']
    if user.get('perm_5th_slot') or user.get('vip_status'): slots.append('equip5')
        
    inv_ids = [c for c in [user.get(s, 0) for s in slots] if c != 0]
    cards_info = {}
    if inv_ids:
        inv_list = ",".join(map(str, inv_ids))
        res = await fetch_all(f"SELECT i.id, c.name, i.mutation, i.serial_number FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.id IN ({inv_list}) AND i.count > 0")
        for r in res:
            mut_str = "⭐" if r['mutation'] == 'Gold' else "🌈" if r['mutation'] == 'Rainbow' else ""
            ser_str = f" [#{r['serial_number']:04d}]" if r['serial_number'] > 0 else ""
            cards_info[r['id']] = f"{mut_str}{r['name']}{ser_str}".strip()
            
    await message.answer(f"🛡 <b>БОЕВАЯ КОЛОДА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите слот:", reply_markup=get_equip_main_keyboard(user, cards_info))

@dp.callback_query(F.data == "eq_clear")
async def cb_eq_clear(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    await execute_db("UPDATE users SET equip1 = 0, equip2 = 0, equip3 = 0, equip4 = 0, equip5 = 0 WHERE id = ?", (user_id,))
    await callback.message.edit_text("✅ Боевая колода успешно очищена!")
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_select_"))
async def equip_slot_callback(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])
    inv = await fetch_all("SELECT DISTINCT c.id, c.name, c.rarity, c.class_type FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0", (callback.from_user.id,))
    if not inv: return await callback.answer("Нет карт!", show_alert=True)
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']}"} for c in inv]
    
    await state.update_data(equip_slot=slot_num, equip_items_cards=items)
    kb = get_pagination_keyboard(items, 0, "eq_c", columns=1, items_per_page=8)
    await callback.message.edit_text(f"👇 Выберите карту для <b>Слота {slot_num}</b>:", reply_markup=kb)
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
    
    invs = await fetch_all("""
        SELECT i.id as inv_id, c.name, c.rarity, c.class_type, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name, i.count
        FROM inventory i JOIN cards c ON i.card_id = c.id LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.card_id = ? AND i.count > 0
    """, (callback.from_user.id, card_id))
    
    if not invs: return await callback.answer("Карта пропала!", show_alert=True)
    
    items = []
    for i in invs:
        c_dict = dict(i)
        if i['signed_by'] > 0: c_dict['signer_name'] = get_display_name({'username': i['username'], 'first_name': i['first_name']})
        name_str = format_card_name_plain(c_dict)
        mut = "⭐ " if i['mutation'] == 'Gold' else "🌈 " if i['mutation'] == 'Rainbow' else ""
        items.append({"id": i['inv_id'], "btn_text": f"{mut}{name_str} (x{i['count']})"})
        
    await state.update_data(equip_items_vars=items)
    kb = get_pagination_keyboard(items, 0, "eq_v", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"eq_select_{slot_num}")])
    await callback.message.edit_text(f"👇 Выберите конкретную копию для <b>Слота {slot_num}</b>:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_v_page_"))
async def equip_var_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('equip_items_vars', []), page, "eq_v", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"eq_select_{data.get('equip_slot', 1)}")])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_v_"))
async def equip_var_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    slot_num = data.get('equip_slot', 1)
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    
    slots = ['equip1', 'equip2', 'equip3', 'equip4']
    if user.get('perm_5th_slot') or user.get('vip_status'): slots.append('equip5')
    current_eq = [user.get(s, 0) for s in slots]
    
    if inv_id in current_eq: return await callback.answer("❌ Эта копия уже экипирована!", show_alert=True)
    card_info = await fetch_one("SELECT card_id FROM inventory WHERE id = ?", (inv_id,))
    
    if user.get(slots[slot_num-1], 0) in current_eq: current_eq.remove(user.get(slots[slot_num-1], 0))
    if any(i != 0 for i in current_eq):
        inv_list = ",".join(map(str, [i for i in current_eq if i != 0]))
        other_cards = await fetch_all(f"SELECT card_id FROM inventory WHERE id IN ({inv_list})")
        if any(c['card_id'] == card_info['card_id'] for c in other_cards):
            return await callback.answer("❌ Нельзя надеть две одинаковые карты!", show_alert=True)

    await execute_db(f"UPDATE users SET {slots[slot_num-1]} = ? WHERE id = ?", (inv_id, callback.from_user.id))
    await callback.message.edit_text(f"✅ Установлено в позицию: Слот {slot_num}!")
    await state.clear()
    await callback.answer()

async def get_team_data(user_id: int):
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    team = []
    slots = ['equip1', 'equip2', 'equip3', 'equip4']
    if user.get('perm_5th_slot') or user.get('vip_status'): slots.append('equip5')
        
    for slot in slots:
        inv_id = user.get(slot, 0)
        if inv_id != 0:
            row = await fetch_one("SELECT c.id, c.name, c.rarity, c.class_type, c.damage, c.hp, c.booster_dmg_mult, c.booster_hp_mult, i.mutation, i.serial_number, i.signed_by FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.id = ? AND i.user_id = ? AND i.count > 0", (inv_id, user_id))
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
                card['inv_id'] = inv_id
                team.append(card)
            else:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ?", (user_id,))
    return team

async def get_bot_team(user_id: int, difficulty_mult: float, rank_name: str, diff_type: str = "med"):
    all_cards = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE rarity != 'Secret' AND hide_from_ai = 0")
    if len(all_cards) < 4: return []
    
    by_rarity = {}
    for c in all_cards: by_rarity.setdefault(c['rarity'], []).append(c)
        
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
        c_copy['burn'] = 0; c_copy['dmg_buff'] = 0; c_copy['serial_number'] = 0; c_copy['signed_by'] = 0; c_copy['heal_power_mult'] = 1.0; c_copy['trauma'] = 0
        team_copies.append(c_copy)
    return team_copies

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
        
        s_str = f" [#{c['serial_number']:04d}]" if c.get('serial_number', 0) > 0 else ""
        sgn_str = f" ✍️ Sign: {c.get('signer_name') or f'ID:{c['signed_by']}'}" if c.get('signed_by', 0) > 0 else ""
            
        if c['class_type'] == 'Healer':
            heal_val = int((c['damage'] + c.get('dmg_buff', 0)) * c.get('heal_power_mult', 1.0))
            res.append(f"• {html.escape(c['name'])}{s_str}{sgn_str}{status} (💗{heal_val} | ❤️{c['hp']}/{c['max_hp']})")
        else:
            dmg = c['damage'] + c.get('dmg_buff', 0)
            res.append(f"• {html.escape(c['name'])}{s_str}{sgn_str}{status} (⚔️{dmg} | ❤️{c['hp']}/{c['max_hp']})")
    return "\n".join(res)

def build_battle_header(p1_name, t1, p2_name, t2, is_endless=False, wave=1):
    header = f"⚔️ <b>АРЕНА: БИТВА</b> ⚔️\n"
    if is_endless: header = f"♾ <b>ENDLESS MODE (Волна {wave})</b> ♾\n"
    return header + f"━━━━━━━━━━━━━━━━━━━━━━━━\n🔵 <b>Команда {p1_name}:</b>\n{format_combat_team_vertical(t1)}\n\n🔴 <b>Команда {p2_name}:</b>\n{format_combat_team_vertical(t2)}\n━━━━━━━━━━━━━━━━━━━━━━━━\n📜 <b>Лог боя:</b>\n"

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
            if bonus_hp > 0: c['hp'] += bonus_hp; c['max_hp'] += bonus_hp
            if c['class_type'] != 'Booster': c['dmg_buff'] += int(c['damage'] * d_mult) - c['damage']

async def process_burns(team, team_name, log1, log2):
    for c in team:
        if c['hp'] > 0 and c.get('burn', 0) > 0:
            c['hp'] -= c['burn']
            ru_str = f"🔥 {team_name}: <b>{html.escape(c['name'])}</b> получает {c['burn']} урона от горения!"
            if c['hp'] <= 0: c['hp'] = 0; ru_str += " ☠️ <i>Сгорел дотла!</i>"
            add_dual_log(log1, log2, ru_str)
            c['burn'] = 0

async def execute_turn(atk_team, def_team, atk_name, def_name, log1, log2, force_attacker=None, force_target=None):
    await process_burns(atk_team, atk_name, log1, log2)
    atk_alive = [c for c in atk_team if c['hp'] > 0]
    def_alive = [c for c in def_team if c['hp'] > 0]
    heals = 0
    if not atk_alive or not def_alive: return False, heals
    
    if force_attacker and force_attacker['hp'] > 0 and force_attacker in atk_alive: atk = force_attacker
    else: atk = random.choice(atk_alive)
        
    base_dmg = atk['damage'] + atk.get('dmg_buff', 0)
    c_type = atk['class_type']
    dead_ru = " ☠️ <i>Мертв!</i>"
    
    if c_type == "Booster":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
        dmg = max(10, int(target['max_hp'] * 0.1))
        target['hp'] -= dmg
        ru_str = f"🔋 {atk_name}: <b>{html.escape(atk['name'])}</b> пускает заряд в <b>{html.escape(target['name'])}</b> на {dmg}!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
        add_dual_log(log1, log2, ru_str)
        
    elif c_type == "Healer":
        other_allies = [c for c in atk_alive if c is not atk]
        if force_target and force_target['hp'] > 0 and force_target in atk_alive: target = force_target; do_heal = True
        elif other_allies: target = random.choice(other_allies); do_heal = True
        else: do_heal = False
            
        if do_heal:
            curr_mult = atk.get('heal_power_mult', 1.0)
            heal_amount = int(base_dmg * curr_mult)
            target['hp'] += heal_amount
            if target['hp'] > target['max_hp']: target['hp'] = target['max_hp']
            ru_str = f"💗 {atk_name}: <b>{html.escape(atk['name'])}</b> исцеляет союзника <b>{html.escape(target['name'])}</b> на {heal_amount} HP! (Эффективность: {int(curr_mult * 100)}%)"
            add_dual_log(log1, log2, ru_str)
            heals += 1
            atk['heal_power_mult'] = max(0.0, curr_mult - 0.03)
        else:
            if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
            else: target = random.choice(def_alive)
            dmg = max(5, int(base_dmg * 0.2))
            target['hp'] -= dmg
            ru_str = f"🎯 {atk_name}: Одинокий Хилер <b>{html.escape(atk['name'])}</b> бьет <b>{html.escape(target['name'])}</b> на {dmg}!"
            if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
            add_dual_log(log1, log2, ru_str)
        
    elif c_type == "AOE":
        ru_str = f"🌪 {atk_name}: <b>{html.escape(atk['name'])}</b> бьет по всем на {base_dmg}!"
        for d in def_alive:
            d['hp'] -= base_dmg
            if d['hp'] <= 0: d['hp'] = 0; ru_str += f" ☠️ <i>{html.escape(d['name'])} мертв!</i>"
        add_dual_log(log1, log2, ru_str)
        
    elif c_type == "Splash":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: main_t = force_target
        else: main_t = random.choice(def_alive)
        splash_dmg = int(base_dmg * 0.5)
        ru_str = f"🌊 {atk_name}: <b>{html.escape(atk['name'])}</b> наносит {base_dmg} по <b>{html.escape(main_t['name'])}</b> и {splash_dmg} остальным!"
        for d in def_alive:
            dmg = base_dmg if d == main_t else splash_dmg
            d['hp'] -= dmg
            if d['hp'] <= 0: d['hp'] = 0; ru_str += f" ☠️ <i>{html.escape(d['name'])} мертв!</i>"
        add_dual_log(log1, log2, ru_str)
        
    elif c_type == "Fire":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
        target['hp'] -= base_dmg
        target['burn'] = target.get('burn', 0) + base_dmg
        ru_str = f"🔥 {atk_name}: <b>{html.escape(atk['name'])}</b> бьет <b>{html.escape(target['name'])}</b> на {base_dmg} и поджигает!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
        add_dual_log(log1, log2, ru_str)
        
    else:
        if force_target and force_target['hp'] > 0 and force_target in def_alive: target = force_target
        else: target = random.choice(def_alive)
        target['hp'] -= base_dmg
        ru_str = f"🎯 {atk_name}: <b>{html.escape(atk['name'])}</b> наносит {base_dmg} по <b>{html.escape(target['name'])}</b>!"
        if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
        add_dual_log(log1, log2, ru_str)
        
    return True, heals

async def get_dynamic_trophies(rank_name: str, rank_idx: int, diff_scale: float = 1.0) -> int:
    if "Uranium VI" in rank_name or "Uranium VII" in rank_name: return random.randint(1, 2)
    base = max(5, 18 - int((rank_idx / 25) * 12)) 
    won = random.randint(base, base+3)
    return int(won * diff_scale)

async def add_bp_xp(user_id: int, xp_to_add: int) -> tuple:
    db = await get_db_connection()
    try:
        user_bp = await db.execute("SELECT ubp.bp_id, ubp.level, ubp.xp FROM user_bp ubp JOIN battle_passes bp ON ubp.bp_id = bp.id WHERE ubp.user_id = ? AND ubp.is_active = 1", (user_id,))
        ubp = await user_bp.fetchone()
        if not ubp: return False, None, 0
        bp_id = ubp['bp_id']; curr_lvl = ubp['level']; curr_xp = ubp['xp'] + xp_to_add; level_up = False
        while True:
            next_lvl = await db.execute("SELECT xp_required FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, curr_lvl + 1))
            nl = await next_lvl.fetchone()
            if not nl: break 
            if curr_xp >= nl['xp_required']:
                curr_lvl += 1; curr_xp -= nl['xp_required']; level_up = True
            else: break
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
    try: msg = await bot.send_message(chat_id, "⏳ <b>Ваш ход!</b> Выберите карту для действия (12 сек):", reply_markup=kb)
    except: return None, None
    try:
        await asyncio.wait_for(ev.wait(), timeout=12.0)
        a_idx = active_manual_battles[chat_id]['attacker_idx']
        t_idx = active_manual_battles[chat_id]['target_idx']
        atk = t1[a_idx] if a_idx is not None else None
        if atk and atk['class_type'] == 'Healer': tgt = t1[t_idx] if t_idx is not None else None
        else: tgt = t2[t_idx] if t_idx is not None else None
    except asyncio.TimeoutError:
        atk = None; tgt = None
    finally:
        active_manual_battles.pop(chat_id, None)
        try: await msg.delete()
        except: pass
    return atk, tgt

@dp.callback_query(F.data.startswith("manatk_"))
async def cb_man_atk(callback: types.CallbackQuery):
    chat_id = callback.message.chat.id
    if chat_id not in active_manual_battles or active_manual_battles[chat_id]['p1_id'] != callback.from_user.id: return await callback.answer("Не ваш ход!", show_alert=True)
    idx = int(callback.data.split("_")[1])
    active_manual_battles[chat_id]['attacker_idx'] = idx
    active_manual_battles[chat_id]['step'] = 'tgt'
    t1 = active_manual_battles[chat_id]['t1']; t2 = active_manual_battles[chat_id]['t2']; atk = t1[idx]
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
    if chat_id not in active_manual_battles or active_manual_battles[chat_id]['p1_id'] != callback.from_user.id: return await callback.answer("Не ваш ход!", show_alert=True)
    idx = int(callback.data.split("_")[1])
    active_manual_battles[chat_id]['target_idx'] = idx
    active_manual_battles[chat_id]['event'].set()
    await callback.answer()

async def do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, mods, is_pvp):
    if mods and mods.get('mod_manual_atk') and not is_pvp:
        atk, tgt = await player_manual_turn(chat_id, p1_id, t1, t2)
        did_turn, heals = await execute_turn(t1, t2, p1_name, p2_name, log, None, force_attacker=atk, force_target=tgt)
    else: did_turn, heals = await execute_turn(t1, t2, p1_name, p2_name, log, None)
    return did_turn, heals

@dp.callback_query(F.data.startswith("surrender_battle_"))
async def cb_surrender_battle_fixed(callback: types.CallbackQuery):
    battle_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    surrendered_players.add((user_id, battle_id))
    chat_id = callback.message.chat.id
    if chat_id in active_manual_battles and active_manual_battles[chat_id]['p1_id'] == user_id: active_manual_battles[chat_id]['event'].set()
    await callback.answer("🏳️ Вы сдались!", show_alert=True)

def get_battle_kb(battle_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"surrender_battle_{battle_id}")]])

async def battle_delay(battle_id, p1_id, p2_id, delay=3.0):
    steps = int(delay * 10)
    for _ in range(steps):
        await asyncio.sleep(0.1)
        if (p1_id, battle_id) in surrendered_players or (p2_id, battle_id) in surrendered_players: break

async def safe_edit_text(msg, text, reply_markup=None):
    try: await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower(): raise e

async def run_battle_loop(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_id: int, p2_name: str, t1: list, t2: list, diff_trophies_scale: float = 1.0, diff_bp_mult: float = 1.0, is_pvp: bool = False, pvp_no_rewards: bool = False, mods=None, diff_type: str = "med"):
    battle_id = f"bt_{p1_id}_{int(time.time())}"
    surrendered_players.discard((p1_id, battle_id))
    if p2_id: surrendered_players.discard((p2_id, battle_id))
        
    try:
        msg = await bot.send_message(chat_id, f"⚔️ Бой <b>{p1_name}</b> VS <b>{p2_name}</b> начнется через 3 сек!")
        await asyncio.sleep(1)
        await safe_edit_text(msg, "⚔️ Бой начнется через 2 сек!")
        await asyncio.sleep(1)
        await safe_edit_text(msg, "⚔️ Бой начнется через 1 сек!")
        
        battle_start_time = time.time()
        log = []
        apply_boosters(t1, p1_name, log, None); apply_boosters(t2, p2_name, log, None)
        
        if log:
            await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
            await battle_delay(battle_id, p1_id, p2_id)

        turn = 1
        winner = None; winner_id = None; loser_id = None
        p1_total_heals = 0; p2_total_heals = 0
        timeout_flag = False
        
        while True:
            if time.time() - battle_start_time > 180: timeout_flag = True; break
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

            did_turn, heals = await do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, mods, is_pvp)
            p1_total_heals += heals
            if did_turn:
                if len(log) > 6: log = log[-6:]
                try: await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                except Exception as e:
                    if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                await battle_delay(battle_id, p1_id, p2_id)
                
                t2_alive = [c for c in t2 if c['hp'] > 0]
                if t2_alive and mods and mods.get('mod_player_atk_all') and not is_pvp:
                    did_turn_extra, heals_extra = await do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, mods, is_pvp)
                    p1_total_heals += heals_extra
                    if did_turn_extra:
                        if len(log) > 6: log = log[-6:]
                        try: await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                        except: pass
                        await battle_delay(battle_id, p1_id, p2_id)

            t2_alive = [c for c in t2 if c['hp'] > 0]
            if t2_alive:
                if time.time() - battle_start_time > 180: timeout_flag = True; break
                did_turn_e, heals_e = await execute_turn(t2, t1, p2_name, p1_name, log, None)
                p2_total_heals += heals_e
                if did_turn_e:
                    if len(log) > 6: log = log[-6:]
                    try: await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                    except Exception as e:
                        if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                    await battle_delay(battle_id, p1_id, p2_id)
                    
                t1_alive_check = [c for c in t1 if c['hp'] > 0]
                if t1_alive_check and mods and mods.get('mod_enemy_atk_all') and not is_pvp:
                    did_turn_e_extra, heals_e_extra = await execute_turn(t2, t1, p2_name, p1_name, log, None)
                    p2_total_heals += heals_e_extra
                    if did_turn_e_extra:
                        if len(log) > 6: log = log[-6:]
                        try: await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                        except: pass
                        await battle_delay(battle_id, p1_id, p2_id)
            turn += 1

        if timeout_flag:
            try: await msg.edit_text("⏳ <b>Бой автоматически прерван (ошибка или тайм-аут)!</b>")
            except: pass
            return

        try:
            if is_pvp:
                await add_quest_progress_new(p1_id, 'q_pvp', 1)
                if p2_id != 0: await add_quest_progress_new(p2_id, 'q_pvp', 1)
            else: await add_quest_progress_new(p1_id, 'q_pve', 1)

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
                    except Exception as e: logging.error(f"Reward Code Drop Error: {e}")
                    finally: await db.close()

            final_text = code_text + f"🏁 <b>ИТОГИ БОЯ: {p1_name} VS {p2_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n👑 <b>Победитель: {winner}</b>\n\n"
            bp_messages = []
            
            if pvp_no_rewards: final_text += "🤝 <b>Дружеская дуэль завершена!</b> Награды и кубки не начислялись."
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
                user_shekels_mult = 1.0; user_bpxp_mult = 1.0
                if user_data:
                    if user_data.get('vip_status'): user_shekels_mult *= 1.5; user_bpxp_mult *= 1.5
                    if user_data.get('perm_2x_shekels'): user_shekels_mult *= 2.0
                    if user_data.get('perm_2x_bpxp'): user_bpxp_mult *= 2.0
                
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
    if callback.from_user.id in active_combats or callback.from_user.id in user_trades: return await callback.answer("❌ Заняты!", show_alert=True)
        
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
        for c in team2: c['hp'] = int(c['hp'] * 1.5); c['max_hp'] = c['hp']
    if mods['mod_enemy_stats']:
        for c in team2:
            c['damage'] = int(c['damage'] * 1.2); c['hp'] = int(c['hp'] * 1.2); c['max_hp'] = c['hp']
            c['booster_dmg_mult'] *= 1.2; c['booster_hp_mult'] *= 1.2
    if mods['mod_player_hp']:
        for c in team1: c['hp'] = int(c['hp'] * 1.3); c['max_hp'] = c['hp']
            
    title_str = await get_user_titles_str(callback.from_user.id)
    p1_name = get_display_name(user) + title_str
    active_combats.add(callback.from_user.id)
    await log_user_action(callback.from_user.id, f"Начал PvE бой (сложность: {diff_type})")
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, callback.from_user.id, p1_name, 0, f"AI ({diff_name})", team1, team2, trophies_scale, bp_xp_mult, is_pvp=False, mods=mods, diff_type=diff_type))
    await callback.answer()

@dp.message(F.text == BTN_PVP)
async def cmd_pvp_menu(message: types.Message):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats or message.from_user.id in user_trades: return await message.answer("❌ Заняты!")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Найти случайного (Автоподбор)", callback_data="pvp_random")],
        [InlineKeyboardButton(text="🎯 Вызвать по ID / @username", callback_data="pvp_direct")]
    ])
    await message.answer("⚔️ <b>PvP ДУЭЛЬ</b>\nВыберите режим (награды за PvP дуэли отключены):", reply_markup=kb)

@dp.callback_query(F.data == "pvp_direct")
async def cb_pvp_direct(callback: types.CallbackQuery, state: FSMContext):
    try: await callback.message.edit_text("Введите @username или ID игрока:")
    except: pass
    await state.set_state(PvPState.waiting_target)
    asyncio.create_task(clear_fsm_timeout(state, callback.message.chat.id, 60))
    await callback.answer()

@dp.callback_query(F.data == "pvp_random")
async def cb_pvp_random(callback: types.CallbackQuery):
    u_id = callback.from_user.id
    user = await fetch_one("SELECT * FROM users WHERE id=?", (u_id,))
    
    if u_id in active_combats or u_id in user_trades: return await callback.answer("Заняты!", show_alert=True)
    t1 = await get_team_data(u_id)
    if not t1: return await callback.answer("Колода пуста!", show_alert=True)
    
    if u_id in pvp_queue:
        pvp_queue.remove(u_id)
        try: await callback.message.edit_text("Поиск отменен.")
        except: pass
        return
        
    valid_opponents = [x for x in pvp_queue if x != u_id and x not in active_combats and x not in user_trades]
    if valid_opponents:
        opp_id = valid_opponents[0]
        pvp_queue.remove(opp_id)
        opp = await fetch_one("SELECT * FROM users WHERE id=?", (opp_id,))
        t2 = await get_team_data(opp_id)
        active_combats.add(u_id); active_combats.add(opp_id)
        title_p1 = await get_user_titles_str(u_id)
        title_p2 = await get_user_titles_str(opp_id)
        p1_name = get_display_name(user) + title_p1
        p2_name = get_display_name(opp) + title_p2
        
        try: await callback.message.edit_text("Противник найден! Начинаем...")
        except: pass
        try: await bot.send_message(opp_id, "Противник найден! Начинаем...")
        except: pass
        
        await log_user_action(u_id, f"Начал PvP бой (Автоподбор) против {opp_id}")
        await log_user_action(opp_id, f"Начал PvP бой (Автоподбор) против {u_id}")
        asyncio.create_task(run_pvp_dual_broadcast(u_id, opp_id, p1_name, p2_name, t1, t2))
    else:
        pvp_queue.add(u_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить поиск", callback_data="pvp_random")]])
        try: await callback.message.edit_text("🔍 Поиск противника... Ожидайте.", reply_markup=kb)
        except: pass
    await callback.answer()

@dp.message(PvPState.waiting_target)
async def process_pvp_target(message: types.Message, state: FSMContext):
    val = message.text.strip()
    target_user = None
    user = await fetch_one("SELECT * FROM users WHERE id=?", (message.from_user.id,))
    if val.isdigit(): target_user = await fetch_one("SELECT * FROM users WHERE id = ?", (int(val),))
    else: target_user = await fetch_one("SELECT * FROM users WHERE username = ?", (val.lstrip('@'),))
        
    if not target_user: return await message.answer("❌ Игрок не найден.")
    if target_user['id'] == message.from_user.id: return await message.answer("❌ Самому себе нельзя!")
    if target_user['id'] in active_combats or target_user['id'] in user_trades: return await message.answer("❌ Игрок занят!")

    challenger_name = get_display_name(user) + await get_user_titles_str(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚔️ Принять", callback_data=f"pvp_accept_{user['id']}"), InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pvp_decline_{user['id']}")]
    ])
    
    try:
        await bot.send_message(target_user['id'], f"⚔️ <b>{challenger_name}</b> вызывает вас на дуэль!", reply_markup=kb)
        await message.answer("📨 Вызов отправлен.")
        await log_user_action(message.from_user.id, f"Бросил вызов на PvP игроку {target_user['id']}")
    except: await message.answer("Ошибка при отправке.")
    await state.clear()

@dp.callback_query(F.data.startswith("pvp_accept_"))
async def callback_pvp_accept(callback: types.CallbackQuery):
    challenger_id = int(callback.data.split("_")[2])
    target_id = callback.from_user.id
    if target_id in active_combats or challenger_id in active_combats or target_id in user_trades or challenger_id in user_trades:
        return await callback.answer("Заняты!", show_alert=True)
        
    t1 = await get_team_data(challenger_id)
    t2 = await get_team_data(target_id)
    if not t1 or not t2: 
        try: await callback.message.edit_text("Deck empty error.")
        except: pass
        return
        
    challenger = await fetch_one("SELECT * FROM users WHERE id = ?", (challenger_id,))
    target = await fetch_one("SELECT * FROM users WHERE id = ?", (target_id,))
    title_p1 = await get_user_titles_str(challenger_id)
    title_p2 = await get_user_titles_str(target_id)
    p1_name = get_display_name(challenger) + title_p1
    p2_name = get_display_name(target) + title_p2
    
    active_combats.add(challenger_id); active_combats.add(target_id)
    await log_user_action(target_id, f"Принял PvP вызов от {challenger_id}")
    asyncio.create_task(run_pvp_dual_broadcast(challenger_id, target_id, p1_name, p2_name, t1, t2))
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("pvp_decline_"))
async def callback_pvp_decline(callback: types.CallbackQuery):
    challenger_id = int(callback.data.split("_")[2])
    try: await bot.send_message(challenger_id, f"❌ Вызов отклонен.")
    except: pass
    try: await callback.message.edit_text("❌ Вы отклонили вызов.")
    except: pass
    await callback.answer()

async def run_pvp_dual_broadcast(p1_id: int, p2_id: int, p1_name: str, p2_name: str, t1: list, t2: list):
    battle_id = f"pvp_{p1_id}_{p2_id}_{int(time.time())}"
    surrendered_players.discard((p1_id, battle_id)); surrendered_players.discard((p2_id, battle_id))
    
    try:
        msg1 = await bot.send_message(p1_id, f"⚔️ Дуэль против <b>{p2_name}</b> начнется через 3 сек!")
        msg2 = await bot.send_message(p2_id, f"⚔️ Дуэль против <b>{p1_name}</b> начнется через 3 сек!")
        await asyncio.sleep(1); await safe_edit_text(msg1, "2..."); await safe_edit_text(msg2, "2...")
        await asyncio.sleep(1); await safe_edit_text(msg1, "1..."); await safe_edit_text(msg2, "1...")
        await asyncio.sleep(1)
        
        battle_start_time = time.time(); log1 = []; log2 = []
        apply_boosters(t1, p1_name, log1, log2); apply_boosters(t2, p2_name, log1, log2)
        
        if log1:
            header1 = build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log1)
            header2 = build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log2)
            await safe_edit_text(msg1, header1, reply_markup=get_battle_kb(battle_id))
            await safe_edit_text(msg2, header2, reply_markup=get_battle_kb(battle_id))
            await battle_delay(battle_id, p1_id, p2_id)

        turn = 1; winner = None; p1_heals = p2_heals = 0; timeout_flag = False
        while True:
            if time.time() - battle_start_time > 180: timeout_flag = True; break
                
            if (p1_id, battle_id) in surrendered_players and (p2_id, battle_id) in surrendered_players:
                winner = "Ничья"
                surrendered_players.discard((p1_id, battle_id)); surrendered_players.discard((p2_id, battle_id))
                break
            elif (p1_id, battle_id) in surrendered_players:
                winner = p2_name; surrendered_players.discard((p1_id, battle_id))
                log1.append(f"🏳️ <b>{p1_name} сдался!</b>"); log2.append(f"🏳️ <b>{p1_name} сдался!</b>")
                break
            elif (p2_id, battle_id) in surrendered_players:
                winner = p1_name; surrendered_players.discard((p2_id, battle_id))
                log1.append(f"🏳️ <b>{p2_name} сдался!</b>"); log2.append(f"🏳️ <b>{p2_name} сдался!</b>")
                break

            t1_a = [c for c in t1 if c['hp'] > 0]; t2_a = [c for c in t2 if c['hp'] > 0]
            if not t1_a and not t2_a: winner = "Ничья"; break
            elif not t1_a: winner = p2_name; break
            elif not t2_a: winner = p1_name; break
            if turn > 40: winner = "Ничья по раундам"; break

            did_turn, h = await execute_turn(t1, t2, p1_name, p2_name, log1, log2); p1_heals += h
            if did_turn:
                if len(log1) > 6: log1 = log1[-6:]; log2 = log2[-6:]
                try: await safe_edit_text(msg1, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log1), reply_markup=get_battle_kb(battle_id))
                except Exception as e:
                    if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag=True; break
                try: await safe_edit_text(msg2, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log2), reply_markup=get_battle_kb(battle_id))
                except Exception as e:
                    if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag=True; break
                await battle_delay(battle_id, p1_id, p2_id)

            t2_a = [c for c in t2 if c['hp'] > 0]
            if t2_a:
                if time.time() - battle_start_time > 180: timeout_flag = True; break
                did_turn, h = await execute_turn(t2, t1, p2_name, p1_name, log1, log2); p2_heals += h
                if did_turn:
                    if len(log1) > 6: log1 = log1[-6:]; log2 = log2[-6:]
                    try: await safe_edit_text(msg1, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log1), reply_markup=get_battle_kb(battle_id))
                    except Exception as e:
                        if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag=True; break
                    try: await safe_edit_text(msg2, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log2), reply_markup=get_battle_kb(battle_id))
                    except Exception as e:
                        if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag=True; break
                    await battle_delay(battle_id, p1_id, p2_id)
            turn += 1

        if timeout_flag:
            txt1 = "⏳ <b>Бой прерван (ошибка или тайм-аут).</b>"
            try: await msg1.edit_text(txt1); await msg2.edit_text(txt1)
            except: pass
            return

        try:
            await add_quest_progress_new(p1_id, 'q_pvp', 1); await add_quest_progress_new(p2_id, 'q_pvp', 1)
            code_text_1 = ""; code_text_2 = ""; winner_user_id = None
            if "Ничья" not in winner:
                if winner == p1_name: winner_user_id = p1_id
                elif winner == p2_name: winner_user_id = p2_id
                
            if winner_user_id is not None:
                if random.random() <= 0.05:
                    db = await get_db_connection()
                    try:
                        new_code = generate_reward_code(); amt = random.randint(1000, 5000)
                        await db.execute("INSERT INTO reward_codes (code, reward_type, amount, item_id, mutation, owner_id, is_active) VALUES (?, ?, ?, ?, ?, ?, 1)", (new_code, 'shekels', amt, 0, 'Normal', winner_user_id))
                        await db.commit()
                        dropped_msg = f"🎁 <b>ВЫПАЛ УНИКАЛЬНЫЙ КОД-НАГРАДА! (5%)</b>\nНажми, чтобы скопировать: <code>{new_code}</code>\nАктивируй через /codereward\n\n"
                        if winner_user_id == p1_id: code_text_1 = dropped_msg
                        else: code_text_2 = dropped_msg
                    except Exception as e: logging.error(f"Reward Code PvP Error: {e}")
                    finally: await db.close()

            final1 = code_text_1 + f"🏁 <b>ИТОГИ: {p1_name} VS {p2_name}</b>\nПобедитель: {winner}\nДружеская дуэль (без наград)."
            final2 = code_text_2 + f"🏁 <b>ИТОГИ: {p1_name} VS {p2_name}</b>\nПобедитель: {winner}\nДружеская дуэль (без наград)."
            try: await msg1.edit_text(final1, reply_markup=None); await msg2.edit_text(final2, reply_markup=None)
            except: pass
        except Exception as e:
            logging.error(f"PVP Reward error: {e}")
            try: await msg1.edit_text("Ошибка при выдаче наград.", reply_markup=None); await msg2.edit_text("Ошибка при выдаче наград.", reply_markup=None)
            except: pass
    finally:
        active_combats.discard(p1_id); active_combats.discard(p2_id)

# ========================================================================
# ENDLESS MODE CORE
# ========================================================================
async def generate_endless_bot_team(wave: int):
    settings = await fetch_one("SELECT * FROM endless_settings WHERE id = 1")
    if not settings: return []
    
    budget = settings['budget_start'] + (wave * settings['budget_step'])
    tier = await fetch_one("SELECT allowed_rarities FROM endless_tiers WHERE start_wave <= ? AND end_wave >= ? ORDER BY id DESC LIMIT 1", (wave, wave))
    
    if tier and tier['allowed_rarities']: allowed_rarities = [r.strip() for r in tier['allowed_rarities'].split(",")]
    else: allowed_rarities = ["Basic", "Uncommon", "Rare", "Epic", "Legendary", "Mythic", "Super"]

    all_cards = await fetch_all(f"SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE hide_from_ai = 0 AND rarity IN ({','.join(['?']*len(allowed_rarities))})", tuple(allowed_rarities))
    if not all_cards: return []
    
    costs = {"Basic": 1, "Uncommon": 2, "Rare": 4, "Epic": 8, "Legendary": 15, "Mythic": 30, "Super": 60, "Exclusive": 100, "Leaderboard": 150, "Secret": 200}
    
    team_selection = []
    current_budget = 0
    max_slots = 4
    
    available_cards = [c for c in all_cards if costs.get(c['rarity'], 1) <= budget]
    if not available_cards: available_cards = all_cards

    while current_budget < budget and len(team_selection) < max_slots:
        affordable = [c for c in available_cards if current_budget + costs.get(c['rarity'], 1) <= budget]
        if not affordable:
            affordable = available_cards 
        chosen = random.choice(affordable)
        team_selection.append(chosen)
        current_budget += costs.get(chosen['rarity'], 1)
        
        if len(team_selection) >= max_slots: break

    hp_mult = 1.0 + ((settings['base_hp_mult'] - 1.0) * wave)
    dmg_mult = 1.0 + ((settings['base_dmg_mult'] - 1.0) * wave)
    
    team_copies = []
    for c in team_selection:
        c_copy = dict(c)
        c_copy['hp'] = int(c['hp'] * hp_mult)
        c_copy['damage'] = int(c['damage'] * dmg_mult)
        c_copy['max_hp'] = c_copy['hp']
        
        if wave >= 20: c_copy['mutation'] = 'Rainbow'
        elif wave >= 10: c_copy['mutation'] = 'Gold'
        else: c_copy['mutation'] = 'Normal'
            
        c_copy['burn'] = 0; c_copy['dmg_buff'] = 0; c_copy['serial_number'] = 0; c_copy['signed_by'] = 0; c_copy['heal_power_mult'] = 1.0; c_copy['trauma'] = 0
        team_copies.append(c_copy)
        
    return team_copies

@dp.message(F.text == BTN_ENDLESS_START)
async def cmd_start_endless(message: types.Message):
    if await check_ban(message.from_user.id): return
    uid = message.from_user.id
    if uid in active_combats or uid in user_trades or uid in active_endless_runs: 
        return await message.answer("❌ Вы заняты!")
        
    settings = await fetch_one("SELECT is_active FROM endless_settings WHERE id = 1")
    if not settings or not settings['is_active']:
        return await message.answer("❌ Endless Mode отключен администрацией.")

    run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ?", (uid,))
    if run:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"▶️ Продолжить (Волна {run['wave']})", callback_data="endl_continue")],
            [InlineKeyboardButton(text="💀 Начать заново", callback_data="endl_restart")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="endl_cancel")]
        ])
        await message.answer(f"♾ <b>Вы уже находитесь в забеге!</b>\nТекущая волна: <b>{run['wave']}</b>\nВаша команда сохранила здоровье с прошлой битвы.", reply_markup=kb)
    else:
        team = await get_team_data(uid)
        if not team: return await message.answer("❌ Боевая колода пуста! Экипируйте карты.")
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚔️ В БОЙ (Волна 1)", callback_data="endl_start_new")],
            [InlineKeyboardButton(text="🔙 Отмена", callback_data="endl_cancel")]
        ])
        await message.answer("♾ <b>ENDLESS MODE</b>\nГотовы начать забег с 1-й волны? Здоровье между боями не восстанавливается!", reply_markup=kb)

@dp.callback_query(F.data == "endl_cancel")
async def cb_endl_cancel(callback: types.CallbackQuery):
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.callback_query(F.data == "endl_restart")
async def cb_endl_restart(callback: types.CallbackQuery):
    uid = callback.from_user.id
    await execute_db("DELETE FROM endless_runs WHERE user_id = ?", (uid,))
    await callback.answer("Забег сброшен!", show_alert=True)
    fake_msg = callback.message
    fake_msg.from_user = callback.from_user
    await cmd_start_endless(fake_msg)
    try: await callback.message.delete()
    except: pass

@dp.callback_query(F.data == "endl_start_new")
async def cb_endl_start_new(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in active_combats or uid in active_endless_runs: return await callback.answer("Заняты!")
    team = await get_team_data(uid)
    if not team: return await callback.answer("Колода пуста!")
    
    active_endless_runs.add(uid)
    try: await callback.message.edit_text("♾ <i>Запуск Бесконечного режима... Волна 1</i>")
    except: pass
    
    await log_user_action(uid, "Начал забег в Endless Mode (Волна 1)")
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (uid,))
    p1_name = get_display_name(user) + await get_user_titles_str(uid)
    
    bot_team = await generate_endless_bot_team(1)
    asyncio.create_task(run_endless_battle(bot, callback.message.chat.id, uid, p1_name, team, bot_team, 1))
    await callback.answer()

@dp.callback_query(F.data == "endl_continue")
async def cb_endl_continue(callback: types.CallbackQuery):
    uid = callback.from_user.id
    if uid in active_combats or uid in active_endless_runs: return await callback.answer("Заняты!")
    
    run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ?", (uid,))
    if not run: return await callback.answer("Забег не найден!", show_alert=True)
    
    wave = run['wave']
    team = json.loads(run['team_state'])
    
    active_endless_runs.add(uid)
    try: await callback.message.edit_text(f"♾ <i>Продолжаем забег... Волна {wave}</i>")
    except: pass
    
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (uid,))
    p1_name = get_display_name(user) + await get_user_titles_str(uid)
    
    bot_team = await generate_endless_bot_team(wave)
    asyncio.create_task(run_endless_battle(bot, callback.message.chat.id, uid, p1_name, team, bot_team, wave))
    await callback.answer()

async def run_endless_battle(bot: Bot, chat_id: int, p1_id: int, p1_name: str, t1: list, t2: list, wave: int):
    battle_id = f"endl_{p1_id}_{wave}_{int(time.time())}"
    surrendered_players.discard((p1_id, battle_id))
    
    try:
        msg = await bot.send_message(chat_id, f"♾ <b>ВОЛНА {wave}</b> начинается через 3 сек!")
        await asyncio.sleep(1); await safe_edit_text(msg, "♾ <b>ВОЛНА {wave}</b> начинается через 2 сек!")
        await asyncio.sleep(1); await safe_edit_text(msg, "♾ <b>ВОЛНА {wave}</b> начинается через 1 сек!")
        
        battle_start_time = time.time(); log = []
        apply_boosters(t1, p1_name, log, None); apply_boosters(t2, f"Волна {wave}", log, None)
        
        if log:
            await safe_edit_text(msg, build_battle_header(p1_name, t1, f"Боты (Волна {wave})", t2, is_endless=True, wave=wave) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
            await battle_delay(battle_id, p1_id, 0)

        turn = 1; winner = None; timeout_flag = False
        
        while True:
            if time.time() - battle_start_time > 180: timeout_flag = True; break
            if (p1_id, battle_id) in surrendered_players:
                winner = "Боты"; surrendered_players.discard((p1_id, battle_id)); log.append(f"🏳️ <b>{p1_name} отступил!</b>"); break

            t1_alive = [c for c in t1 if c['hp'] > 0]
            t2_alive = [c for c in t2 if c['hp'] > 0]
            if not t1_alive: winner = "Боты"; break
            elif not t2_alive: winner = p1_name; break
            if turn > 40: winner = "Боты"; log.append("⏳ <i>Время вышло, боты прорвали оборону!</i>"); break

            did_turn, _ = await execute_turn(t1, t2, p1_name, f"Волна {wave}", log, None)
            if did_turn:
                if len(log) > 6: log = log[-6:]
                try: await safe_edit_text(msg, build_battle_header(p1_name, t1, f"Боты (Волна {wave})", t2, is_endless=True, wave=wave) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                except Exception as e:
                    if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                await battle_delay(battle_id, p1_id, 0)

            t2_alive = [c for c in t2 if c['hp'] > 0]
            if t2_alive:
                if time.time() - battle_start_time > 180: timeout_flag = True; break
                did_turn_e, _ = await execute_turn(t2, t1, f"Волна {wave}", p1_name, log, None)
                if did_turn_e:
                    if len(log) > 6: log = log[-6:]
                    try: await safe_edit_text(msg, build_battle_header(p1_name, t1, f"Боты (Волна {wave})", t2, is_endless=True, wave=wave) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                    except Exception as e:
                        if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                    await battle_delay(battle_id, p1_id, 0)
            turn += 1

        if timeout_flag:
            try: await msg.edit_text("⏳ <b>Бой прерван из-за ошибки/таймаута! Забег отменен.</b>")
            except: pass
            await execute_db("DELETE FROM endless_runs WHERE user_id = ?", (p1_id,))
            return

        final_text = f"🏁 <b>ИТОГИ ВОЛНЫ {wave}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        if winner == p1_name:
            survivors = [c for c in t1 if c['hp'] > 0]
            shards_won = 10 + wave * 2
            await execute_db("UPDATE users SET soul_shards = soul_shards + ? WHERE id = ?", (shards_won, p1_id))
            
            user_data = await fetch_one("SELECT endless_max_wave FROM users WHERE id = ?", (p1_id,))
            if user_data['endless_max_wave'] < wave:
                await execute_db("UPDATE users SET endless_max_wave = ? WHERE id = ?", (wave, p1_id))
                
            milestones = await fetch_all("SELECT * FROM endless_milestones WHERE wave = ?", (wave,))
            reward_strs = []
            for m in milestones:
                if m['reward_type'] == 'shekels':
                    await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (m['amount'], p1_id))
                    reward_strs.append(f"💰 {m['amount']} Шекелей")
                elif m['reward_type'] == 'rbucks':
                    await execute_db("UPDATE users SET r_bucks = r_bucks + ? WHERE id = ?", (m['amount'], p1_id))
                    reward_strs.append(f"💎 {m['amount']} R$")
                elif m['reward_type'] == 'pack':
                    await execute_db("INSERT INTO user_seed_packs (user_id, pack_id, count) VALUES (?, ?, ?) ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + ?", (p1_id, m['item_id'], m['amount'], m['amount']))
                    reward_strs.append(f"📦 Сид-Пак (ID:{m['item_id']}) x{m['amount']}")
                elif m['reward_type'] == 'card':
                    _, serial, _ = await give_card_to_user(p1_id, m['item_id'], m['mutation'])
                    mut_s = "🌈" if m['mutation'] == 'Rainbow' else ("⭐" if m['mutation'] == 'Gold' else "")
                    s_str = f" [#{serial:04d}]" if serial > 0 else ""
                    reward_strs.append(f"🃏 {mut_s} Карта (ID:{m['item_id']}){s_str}")
                    
            state_json = json.dumps([{
                'id': c['id'], 'name': c['name'], 'rarity': c['rarity'], 'class_type': c['class_type'],
                'damage': c['damage'], 'hp': c['hp'], 'max_hp': c['max_hp'], 'booster_dmg_mult': c['booster_dmg_mult'],
                'booster_hp_mult': c['booster_hp_mult'], 'mutation': c.get('mutation', 'Normal'),
                'serial_number': c.get('serial_number', 0), 'signed_by': c.get('signed_by', 0), 'signer_name': c.get('signer_name', '')
            } for c in survivors])
            
            run = await fetch_one("SELECT * FROM endless_runs WHERE user_id = ?", (p1_id,))
            if run: await execute_db("UPDATE endless_runs SET wave = ?, team_state = ? WHERE user_id = ?", (wave + 1, state_json, p1_id))
            else: await execute_db("INSERT INTO endless_runs (user_id, wave, team_state) VALUES (?, ?, ?)", (p1_id, wave + 1, state_json))

            final_text += f"🎉 <b>ВОЛНА {wave} ПРОЙДЕНА!</b>\n🔮 Получено <b>{shards_won} Осколков Душ</b>.\n"
            if reward_strs:
                final_text += "🎁 <b>Специальные награды за волну:</b>\n" + "\n".join([f"  └ {r}" for r in reward_strs]) + "\n"
                
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"▶️ Следующая волна ({wave+1})", callback_data="endl_continue")],
                [InlineKeyboardButton(text="⛺ Отступить в лагерь", callback_data="endl_cancel")]
            ])
            try: await msg.edit_text(final_text, reply_markup=kb)
            except: pass
            
        else:
            await execute_db("DELETE FROM endless_runs WHERE user_id = ?", (p1_id,))
            final_text += f"💀 <b>ВЫ ПОГИБЛИ!</b>\nВаша команда уничтожена на волне {wave}. Забег окончен.\nВся не потраченная валюта (Осколки) сохранена."
            try: await msg.edit_text(final_text, reply_markup=None)
            except: pass

    except Exception as e:
        logging.error(f"Endless Loop Error: {e}")
        try: await bot.send_message(chat_id, "⚠️ Ошибка в Endless Mode. Забег сохранен.")
        except: pass
    finally:
        active_endless_runs.discard(p1_id)

@dp.message(F.text == BTN_ENDLESS_SHOP)
async def cmd_endless_shop(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT soul_shards FROM users WHERE id = ?", (message.from_user.id,))
    shards = user.get('soul_shards', 0)
    
    text = (
        f"🛒 <b>МАГАЗИН БЕСКОНЕЧНОСТИ (Души)</b>\n"
        f"🔮 Твой баланс: <b>{shards} Осколков Душ</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<i>Эти осколки можно добыть только в Endless Mode.</i>\n\n"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Случайная Легендарная (500 🔮)", callback_data="eshop_buy_leg")],
        [InlineKeyboardButton(text="🔴 Случайная Мифическая (3000 🔮)", callback_data="eshop_buy_myth")],
        [InlineKeyboardButton(text="🌈 Случайная Супер Карта (15000 🔮)", callback_data="eshop_buy_super")],
        [InlineKeyboardButton(text="💎 5 R$ (2500 🔮)", callback_data="eshop_buy_r5")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("eshop_buy_"))
async def cb_eshop_buy(callback: types.CallbackQuery):
    item = callback.data.split("_")[2]
    user_id = callback.from_user.id
    user = await fetch_one("SELECT soul_shards FROM users WHERE id = ?", (user_id,))
    shards = user.get('soul_shards', 0)
    
    prices = {"leg": 500, "myth": 3000, "super": 15000, "r5": 2500}
    cost = prices.get(item, 999999)
    if shards < cost: return await callback.answer("❌ Недостаточно Осколков!", show_alert=True)
    
    await execute_db("UPDATE users SET soul_shards = soul_shards - ? WHERE id = ?", (cost, user_id))
    
    if item == "r5":
        await execute_db("UPDATE users SET r_bucks = r_bucks + 5 WHERE id = ?", (user_id,))
        await callback.answer("✅ Успешно куплено 5 R$!", show_alert=True)
    else:
        rarity_map = {"leg": "Legendary", "myth": "Mythic", "super": "Super"}
        target = rarity_map[item]
        all_cards = await fetch_all("SELECT * FROM cards WHERE rarity = ? AND id NOT IN (SELECT card_id FROM seed_pack_cards)", (target,))
        if not all_cards:
            await execute_db("UPDATE users SET soul_shards = soul_shards + ? WHERE id = ?", (cost, user_id))
            return await callback.answer("❌ Нет карт в БД.", show_alert=True)
            
        won_card = random.choice(all_cards)
        mut = roll_mutation()
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        won_card['serial_number'] = serial; won_card['signed_by'] = 0
        mut_str = "🌈 Радужная" if mut == 'Rainbow' else ("⭐ Золотая" if mut == 'Gold' else "Обычная")
        await callback.message.answer(f"🔮 <b>Покупка за Осколки Душ успешна!</b>\nВы выбили: {format_card_name(won_card)}\nМутация: <b>{mut_str}</b>")
        await callback.answer()
        
    await cmd_endless_shop(callback.message)
    try: await callback.message.delete()
    except: pass

@dp.message(F.text == BTN_ENDLESS_LB)
async def cmd_endless_lb(message: types.Message):
    if await check_ban(message.from_user.id): return
    top_users = await fetch_all("SELECT id, endless_max_wave, username, first_name FROM users WHERE endless_max_wave > 0 AND id != ? ORDER BY endless_max_wave DESC LIMIT 20", (SUPER_ADMIN_ID,))
    
    text = f"🏆 <b>ЗАЛ СЛАВЫ БЕСКОНЕЧНОСТИ (Топ-20)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    if not top_users:
        text += "<i>Пока никто не рискнул спуститься в подземелья...</i>\n"
    else:
        for i, u in enumerate(top_users, 1):
            name = get_display_name(u)
            med = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
            text += f"{med} <b>{i}. {name}</b> — <b>Волна {u['endless_max_wave']}</b>\n"
            
    settings = await fetch_one("SELECT last_lb_reset FROM endless_settings WHERE id = 1")
    now = time.time()
    time_left = max(0, (settings['last_lb_reset'] + 3*24*3600) - now)
    h, rem = divmod(time_left, 3600)
    m, _ = divmod(rem, 60)
    
    text += f"\n⏳ <b>До сброса и наград:</b> {int(h)}ч {int(m)}м"
    await message.answer(text)

# ========================================================================
# АДМИН-ПАНЕЛЬ: ENDLESS MODE
# ========================================================================
def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="♾ Настройка Endless", callback_data="adm_endless_main")],
        [InlineKeyboardButton(text="🃏 Карты", callback_data="adm_cards"), InlineKeyboardButton(text="👤 Игроки", callback_data="adm_users")],
        [InlineKeyboardButton(text="🎉 Ивенты", callback_data="adm_events"), InlineKeyboardButton(text="👑 Админы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="🎟 Батл-пассы", callback_data="adm_bp_main"), InlineKeyboardButton(text="✍️ Сигнеры", callback_data="adm_signers")],
        [InlineKeyboardButton(text="🏆 Награды Топа", callback_data="adm_lb_main"), InlineKeyboardButton(text="📦 Сид-Паки", callback_data="adm_sp_main")],
        [InlineKeyboardButton(text="🎁 Коды-Награды", callback_data="adm_codes_main"), InlineKeyboardButton(text="🔨 Настройка Крафтов", callback_data="adm_craft_main")],
        [InlineKeyboardButton(text="📦 Бэкап БД", callback_data="adm_db")]
    ])

@dp.callback_query(F.data == "adm_endless_main")
async def adm_endless_main(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    settings = await fetch_one("SELECT * FROM endless_settings WHERE id = 1")
    is_on = settings['is_active']
    on_btn = "🔴 ВЫКЛЮЧИТЬ" if is_on else "🟢 ВКЛЮЧИТЬ"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{on_btn} РЕЖИМ", callback_data="admen_toggle")],
        [InlineKeyboardButton(text="⚙️ Множители и Бюджет", callback_data="admen_scaling")],
        [InlineKeyboardButton(text="📊 Пулы Спавна (Тиры)", callback_data="admen_tiers_list")],
        [InlineKeyboardButton(text="🎁 Награды за Волны (Milestones)", callback_data="admen_ms_list")],
        [InlineKeyboardButton(text="🏆 Награды Лидерборда", callback_data="admen_lb_list")],
        [InlineKeyboardButton(text="🔄 СБРОСИТЬ СЕЗОН (Вайп)", callback_data="admen_force_reset")],
        [InlineKeyboardButton(text="🔙 В главное админ-меню", callback_data="adm_main")]
    ])
    
    text = (
        "♾ <b>НАСТРОЙКИ БЕСКОНЕЧНОГО РЕЖИМА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Статус: <b>{'РАБОТАЕТ' if is_on else 'ОТКЛЮЧЕН'}</b>\n"
        f"Скейл ХП: {settings['base_hp_mult']} | Урона: {settings['base_dmg_mult']}\n"
        f"Бюджет: Старт {settings['budget_start']} | Шаг {settings['budget_step']}\n"
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "admen_toggle")
async def adm_endless_toggle(callback: types.CallbackQuery):
    settings = await fetch_one("SELECT is_active FROM endless_settings WHERE id = 1")
    new_val = 0 if settings['is_active'] else 1
    await execute_db("UPDATE endless_settings SET is_active = ? WHERE id = 1", (new_val,))
    await callback.answer(f"Режим {'ВКЛЮЧЕН' if new_val else 'ВЫКЛЮЧЕН'}!", show_alert=True)
    await adm_endless_main(callback)

@dp.callback_query(F.data == "admen_scaling")
async def adm_endless_scaling(callback: types.CallbackQuery):
    settings = await fetch_one("SELECT * FROM endless_settings WHERE id = 1")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Шаг множителя ХП", callback_data="admen_set_base_hp_mult")],
        [InlineKeyboardButton(text="✏️ Шаг множителя Урона", callback_data="admen_set_base_dmg_mult")],
        [InlineKeyboardButton(text="✏️ Стартовый бюджет", callback_data="admen_set_budget_start")],
        [InlineKeyboardButton(text="✏️ Прирост бюджета за волну", callback_data="admen_set_budget_step")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_endless_main")]
    ])
    text = (
        "⚙️ <b>НАСТРОЙКА СЛОЖНОСТИ (Scaling)</b>\n"
        f"Множитель ХП: <b>{settings['base_hp_mult']}</b> (Формула: 1.0 + (множитель - 1.0)*волна)\n"
        f"Множитель Урона: <b>{settings['base_dmg_mult']}</b>\n"
        f"Бюджет Угрозы (Старт): <b>{settings['budget_start']}</b> очков\n"
        f"Бюджет Угрозы (Прирост): <b>{settings['budget_step']}</b> очков/волна\n"
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("admen_set_"))
async def adm_endless_set_start(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.replace("admen_set_", "")
    await state.update_data(admen_field=field)
    await callback.message.answer(f"Введите новое значение для {field}:")
    await state.set_state(AdminEndlessSettings.waiting_val)
    await callback.answer()

@dp.message(AdminEndlessSettings.waiting_val)
async def adm_endless_set_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    field = data['admen_field']
    try:
        if "mult" in field: val = float(message.text.replace(",", "."))
        else: val = int(message.text)
        await execute_db(f"UPDATE endless_settings SET {field} = ? WHERE id = 1", (val,))
        await message.answer("✅ Настройка обновлена!")
    except: await message.answer("❌ Ошибка ввода числа.")
    await state.clear()

@dp.callback_query(F.data == "admen_tiers_list")
async def adm_endless_tiers_list(callback: types.CallbackQuery):
    tiers = await fetch_all("SELECT * FROM endless_tiers ORDER BY start_wave ASC")
    kb = [[InlineKeyboardButton(text="➕ Добавить Тир", callback_data="adment_add")]]
    for t in tiers: kb.append([InlineKeyboardButton(text=f"🗑 Волны {t['start_wave']}-{t['end_wave']}: {t['allowed_rarities'][:20]}...", callback_data=f"adment_del_{t['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_endless_main")])
    await callback.message.edit_text("📊 <b>Пулы Спавна (Тиры)</b>\nНастройте, на каких волнах падают какие редкости. Если волна не покрыта тирами, падают ВСЕ.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("adment_del_"))
async def adment_del(callback: types.CallbackQuery):
    tid = int(callback.data.split("_")[2])
    await execute_db("DELETE FROM endless_tiers WHERE id = ?", (tid,))
    await callback.answer("Удалено!")
    await adm_endless_tiers_list(callback)

@dp.callback_query(F.data == "adment_add")
async def adment_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите СТАРТОВУЮ волну тира (например, 1):")
    await state.set_state(AdminEndlessTier.start_wave)
    await callback.answer()

@dp.message(AdminEndlessTier.start_wave)
async def adment_add_sw(message: types.Message, state: FSMContext):
    try:
        await state.update_data(sw=int(message.text))
        await message.answer("Введите КОНЕЧНУЮ волну тира (например, 15):")
        await state.set_state(AdminEndlessTier.end_wave)
    except: await message.answer("Число!")

@dp.message(AdminEndlessTier.end_wave)
async def adment_add_ew(message: types.Message, state: FSMContext):
    try:
        await state.update_data(ew=int(message.text))
        await message.answer("Введите разрешенные редкости ЧЕРЕЗ ЗАПЯТУЮ (например: Basic,Uncommon,Rare):")
        await state.set_state(AdminEndlessTier.rarities)
    except: await message.answer("Число!")

@dp.message(AdminEndlessTier.rarities)
async def adment_add_finish(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await execute_db("INSERT INTO endless_tiers (start_wave, end_wave, allowed_rarities) VALUES (?, ?, ?)", (data['sw'], data['ew'], message.text))
    await message.answer("✅ Тир создан!")
    await state.clear()

@dp.callback_query(F.data == "admen_ms_list")
async def adm_endless_ms_list(callback: types.CallbackQuery):
    ms = await fetch_all("SELECT * FROM endless_milestones ORDER BY wave ASC")
    kb = [[InlineKeyboardButton(text="➕ Добавить Milestone", callback_data="admenm_add")]]
    for m in ms:
        rt = m['reward_type']
        amt = m['amount']
        kb.append([InlineKeyboardButton(text=f"🗑 Волна {m['wave']}: {rt} x{amt}", callback_data=f"admenm_del_{m['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_endless_main")])
    await callback.message.edit_text("🎁 <b>Награды за Волны (Milestones)</b>\nВыдаются игроку при завершении конкретной волны.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("admenm_del_"))
async def admenm_del(callback: types.CallbackQuery):
    mid = int(callback.data.split("_")[2])
    await execute_db("DELETE FROM endless_milestones WHERE id = ?", (mid,))
    await callback.answer("Удалено!")
    await adm_endless_ms_list(callback)

@dp.callback_query(F.data == "admenm_add")
async def admenm_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите НОМЕР ВОЛНЫ для награды:")
    await state.set_state(AdminEndlessMilestone.wave)
    await callback.answer()

@dp.message(AdminEndlessMilestone.wave)
async def admenm_add_w(message: types.Message, state: FSMContext):
    try:
        await state.update_data(m_wave=int(message.text))
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Шекели", callback_data="admenmr_shekels"), InlineKeyboardButton(text="💎 R$", callback_data="admenmr_rbucks")],
            [InlineKeyboardButton(text="📦 Сид-Пак", callback_data="admenmr_pack"), InlineKeyboardButton(text="🃏 Карта", callback_data="admenmr_card")]
        ])
        await message.answer("Что выдаем?", reply_markup=kb)
        await state.set_state(AdminEndlessMilestone.r_type)
    except: await message.answer("Число!")

@dp.callback_query(AdminEndlessMilestone.r_type, F.data.startswith("admenmr_"))
async def admenm_add_type(callback: types.CallbackQuery, state: FSMContext):
    rtype = callback.data.split("_")[1]
    await state.update_data(m_rtype=rtype)
    if rtype in ["shekels", "rbucks"]:
        await callback.message.answer("Введите количество:")
        await state.set_state(AdminEndlessMilestone.amount)
    elif rtype == "pack":
        await callback.message.answer("Введите ID Сид-Пака и через пробел количество (Например: 1 5):")
        await state.set_state(AdminEndlessMilestone.item_id)
    elif rtype == "card":
        await callback.message.answer("Введите ID Карты, затем пробел, затем Мутацию (Например: 5 Gold):")
        await state.set_state(AdminEndlessMilestone.mutation)
    await callback.answer()

@dp.message(AdminEndlessMilestone.amount)
async def admenm_add_amt(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        amt = int(message.text)
        await execute_db("INSERT INTO endless_milestones (wave, reward_type, amount) VALUES (?, ?, ?)", (data['m_wave'], data['m_rtype'], amt))
        await message.answer("✅ Добавлено!")
        await state.clear()
    except: await message.answer("Число!")

@dp.message(AdminEndlessMilestone.item_id)
async def admenm_add_pack(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        parts = message.text.split()
        item_id = int(parts[0])
        amt = int(parts[1]) if len(parts) > 1 else 1
        await execute_db("INSERT INTO endless_milestones (wave, reward_type, amount, item_id) VALUES (?, ?, ?, ?)", (data['m_wave'], data['m_rtype'], amt, item_id))
        await message.answer("✅ Добавлено!")
        await state.clear()
    except: await message.answer("Формат: ID Кол-во")

@dp.message(AdminEndlessMilestone.mutation)
async def admenm_add_card(message: types.Message, state: FSMContext):
    data = await state.get_data()
    try:
        parts = message.text.split()
        item_id = int(parts[0])
        mut = parts[1] if len(parts) > 1 else "Normal"
        await execute_db("INSERT INTO endless_milestones (wave, reward_type, item_id, mutation) VALUES (?, ?, ?, ?)", (data['m_wave'], data['m_rtype'], item_id, mut))
        await message.answer("✅ Добавлено!")
        await state.clear()
    except: await message.answer("Формат: ID Mutation")

@dp.callback_query(F.data == "admen_lb_list")
async def adm_endless_lb_list(callback: types.CallbackQuery):
    lbr = await fetch_all("SELECT * FROM endless_lb_rewards ORDER BY rank_start ASC")
    kb = [[InlineKeyboardButton(text="➕ Добавить Награду Лидерборда", callback_data="admenlb_add")]]
    for r in lbr: kb.append([InlineKeyboardButton(text=f"🗑 Топ {r['rank_start']}-{r['rank_end']}: {r['reward_type']} x{r['amount']}", callback_data=f"admenlb_del_{r['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_endless_main")])
    await callback.message.edit_text("🏆 <b>Награды Лидерборда (Endless)</b>\nРаздаются автоматически каждые 3 дня лучшим игрокам по макс. волне.", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("admenlb_del_"))
async def admenlb_del(callback: types.CallbackQuery):
    lbid = int(callback.data.split("_")[2])
    await execute_db("DELETE FROM endless_lb_rewards WHERE id = ?", (lbid,))
    await callback.answer("Удалено!")
    await adm_endless_lb_list(callback)

@dp.callback_query(F.data == "admenlb_add")
async def admenlb_add_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите диапазон мест через дефис (например: 1-1, 2-3, 4-10):")
    await state.set_state(AdminEndlessLB.rank_start)
    await callback.answer()

@dp.message(AdminEndlessLB.rank_start)
async def admenlb_add_r(message: types.Message, state: FSMContext):
    try:
        parts = message.text.split("-")
        r_start = int(parts[0])
        r_end = int(parts[1]) if len(parts) > 1 else r_start
        await state.update_data(lb_rstart=r_start, lb_rend=r_end)
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Шекели", callback_data="admenlbr_shekels"), InlineKeyboardButton(text="💎 R$", callback_data="admenlbr_rbucks")],
            [InlineKeyboardButton(text="🔮 Осколки", callback_data="admenlbr_shards")],
