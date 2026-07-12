import asyncio
import logging
import random
import time
import io
import os
import math
import string
import html
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
BOT_TOKEN = "8887633400:AAEvlERe0CN1twoc01jGxYzSi8f9Kbwck1A"
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
surrendered_players = set() # Хранит кортежи (user_id, battle_id) для избежания багов с ложными сдачами

active_craft_sessions = {} # user_id -> dict
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
BTN_ENDLESS = "♾ Бесконечный режим"
BTN_CRAFT = "🔨 Крафт"
BTN_WC = "⚽ World Cup 2026 (Cardball)"
BTN_MAIN_MODE = "🔙 В обычный режим"

BTN_FB_DRAW = "⚽ Cardball Гача"
BTN_FB_SHOP = "🛒 Cardball Магазин"
BTN_FB_PACKS = "📦 Cardball Паки"
BTN_FB_BP = "🎟 Cardball БП"
BTN_FB_MATCH = "⚽ Cardball Матч"
BTN_FB_LEAGUE = "🏆 Cardball Лига"
BTN_FB_PROF = "👤 Cardball Профиль"
BTN_FB_EQ = "🛡 Состав (Cardball)"
BTN_FB_INV = "🎒 Cardball Инвентарь"
BTN_FB_TRANSFER = "✈️ Трансфер в Основу"
BTN_FB_INDEX = "📖 Cardball Индекс"
BTN_FB_GUIDE = "📖 Гайд по Cardball"

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
                last_fb_getcard REAL DEFAULT 0,
                equip1 INTEGER DEFAULT 0,
                equip2 INTEGER DEFAULT 0,
                equip3 INTEGER DEFAULT 0,
                equip4 INTEGER DEFAULT 0,
                quests_cooldown REAL DEFAULT 0,
                pity_mythic INTEGER DEFAULT 0,
                pity_super INTEGER DEFAULT 0,
                total_coins INTEGER DEFAULT 0,
                q_cards_opened INTEGER DEFAULT 0,
                q_rare_obtained INTEGER DEFAULT 0,
                q_wins INTEGER DEFAULT 0,
                q_battles INTEGER DEFAULT 0,
                q_shop_buys INTEGER DEFAULT 0,
                q_pvp_played INTEGER DEFAULT 0,
                q_heals_done INTEGER DEFAULT 0,
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
                football_mode INTEGER DEFAULT 0,
                football_balls INTEGER DEFAULT 0,
                football_trophies INTEGER DEFAULT 0,
                football_team_id INTEGER DEFAULT 0,
                fb_equip1 INTEGER DEFAULT 0,
                fb_equip2 INTEGER DEFAULT 0,
                fb_equip3 INTEGER DEFAULT 0,
                fb_equip4 INTEGER DEFAULT 0,
                last_transfer REAL DEFAULT 0
            )
        """)
        
        # Добавляем новые колонки при миграциях
        for col in ['football_mode', 'football_balls', 'football_trophies', 'football_team_id', 'fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4', 'last_transfer', 'last_fb_getcard']:
            try: 
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            except aiosqlite.OperationalError: 
                pass
            
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
                is_cardball_exclusive INTEGER DEFAULT 0
            )
        """)
        try: 
            await db.execute("ALTER TABLE cards ADD COLUMN is_cardball_exclusive INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: 
            pass
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_id INTEGER,
                count INTEGER DEFAULT 1,
                mutation TEXT DEFAULT 'Normal',
                serial_number INTEGER DEFAULT 0,
                signed_by INTEGER DEFAULT 0,
                is_football INTEGER DEFAULT 0
            )
        """)
        
        try: 
            await db.execute("ALTER TABLE inventory ADD COLUMN is_football INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: 
            pass
        
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

        await db.execute("DELETE FROM ranks")
        default_ranks = [
            ("🟤 Bronze I", 0, 0.8, 1.0), ("🟤 Bronze II", 50, 0.85, 1.05), ("🟤 Bronze III", 100, 0.9, 1.1), ("🟤 Bronze IV", 150, 0.95, 1.15),
            ("⚪ Silver I", 200, 1.0, 1.2), ("⚪ Silver II", 300, 1.05, 1.25), ("⚪ Silver III", 400, 1.1, 1.3), ("⚪ Silver IV", 500, 1.15, 1.35),
            ("🟡 Gold I", 650, 1.2, 1.4), ("🟡 Gold II", 800, 1.3, 1.5), ("🟡 Gold III", 950, 1.4, 1.6), ("🟡 Gold IV", 1100, 1.5, 1.7),
            ("🟢 Platina I", 1300, 1.8, 1.8), ("🟢 Platina II", 1500, 2.5, 1.9), ("🟢 Platina III", 1700, 3.2, 2.0), ("🟢 Platina IV", 1900, 4.0, 2.1),
            ("💎 Diamond I", 2200, 5.0, 2.5), ("💎 Diamond II", 2500, 6.5, 2.8), ("💎 Diamond III", 2800, 8.0, 3.2), ("💎 Diamond IV", 3100, 10.0, 3.6),
            ("🔴 Ruby I", 3500, 13.0, 4.0), ("🔴 Ruby II", 4000, 15.0, 4.5), ("🔴 Ruby III", 4500, 17.0, 5.0), ("🔴 Ruby IV", 5000, 20.0, 5.5),
            ("☢️ Uranium I", 5700, 24.0, 6.0), ("☢️ Uranium II", 6500, 28.0, 6.5), ("☢️ Uranium III", 7400, 32.0, 7.0), ("☢️ Uranium IV", 8400, 36.0, 7.5), ("☢️ Uranium V", 9500, 40.0, 8.0)
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
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS seed_packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                photo_id TEXT,
                description TEXT,
                price INTEGER DEFAULT 2000,
                is_football INTEGER DEFAULT 0
            )
        """)
        try: 
            await db.execute("ALTER TABLE seed_packs ADD COLUMN is_football INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: 
            pass
        
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

        await db.execute("""CREATE TABLE IF NOT EXISTS shop_items (id INTEGER PRIMARY KEY AUTOINCREMENT, item_type TEXT, name TEXT, price INTEGER, stock INTEGER, is_football INTEGER DEFAULT 0)""")
        try: 
            await db.execute("ALTER TABLE shop_items ADD COLUMN is_football INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: 
            pass

        await db.execute("""CREATE TABLE IF NOT EXISTS admin_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)""")
        await db.execute("""CREATE TABLE IF NOT EXISTS lb_rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, bracket TEXT, reward_type TEXT, amount INTEGER DEFAULT 0, card_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal', lb_type TEXT DEFAULT 'trophies')""")
        
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
                created_at REAL,
                is_football INTEGER DEFAULT 0
            )
        """)
        try: 
            await db.execute("ALTER TABLE battle_passes ADD COLUMN is_football INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: 
            pass

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
                is_active INTEGER DEFAULT 1,
                is_football INTEGER DEFAULT 0
            )
        """)
        try:
            await db.execute("ALTER TABLE reward_codes ADD COLUMN is_football INTEGER DEFAULT 0")
        except aiosqlite.OperationalError:
            pass

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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS league_teams (
                id INTEGER PRIMARY KEY,
                name TEXT,
                score INTEGER DEFAULT 0
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS league_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stage INTEGER DEFAULT 0,
                t1_id INTEGER,
                t2_id INTEGER,
                t1_score INTEGER DEFAULT 0,
                t2_score INTEGER DEFAULT 0,
                winner_id INTEGER DEFAULT 0
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS league_rewards_stages (
                stage_name TEXT,
                reward_type TEXT,
                amount INTEGER DEFAULT 0,
                card_id INTEGER DEFAULT 0,
                mutation TEXT DEFAULT 'Normal'
            )
        """)

        async with db.execute("SELECT COUNT(*) as c FROM league_teams") as cursor:
            teams_count = await cursor.fetchone()
            
        if teams_count and dict(teams_count)['c'] == 0:
            for i in range(1, 9):
                await db.execute("INSERT INTO league_teams (id, name, score) VALUES (?, ?, 0)", (i, f"Сборная {i}"))

        await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (SUPER_ADMIN_ID,))
        await db.execute("INSERT OR IGNORE INTO server_settings (id) VALUES (1)")
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
    is_cardball_exclusive = State()

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
    is_football = State()
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

class CreateSeedPack(StatesGroup):
    is_football = State()
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
    is_football = State()

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

class AdminLeagueRewards(StatesGroup):
    stage = State()
    amount = State()
    card_id = State()
    mutation = State()

# Вспомогательный класс для имитации CallbackQuery из текстовых команд
class FakeCall:
    def __init__(self, message, data):
        self.message = message
        self.data = data
        self.from_user = message.from_user

# ========================================================================
# УТИЛИТЫ И ХЕЛПЕРЫ ДЛЯ UI
# ========================================================================
def get_display_name(user_data: dict) -> str:
    if user_data.get('username'): 
        return html.escape(f"@{user_data['username']}")
    elif user_data.get('first_name'): 
        return html.escape(user_data['first_name'])
    return f"Player {user_data.get('id', '???')}"

async def get_user_titles_str(user_id: int) -> str:
    titles = []
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

async def add_quest_progress(user_id: int, field: str, amount: int = 1):
    if field not in ['q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys', 'q_pvp_played', 'q_heals_done']:
        return
        
    user = await fetch_one("SELECT quests_cooldown, notif_quests, q_cards_opened, q_battles, q_pvp_played, q_shop_buys, q_heals_done FROM users WHERE id = ?", (user_id,))
    if not user or user['quests_cooldown'] > time.time():
        return
        
    await execute_db(f"UPDATE users SET {field} = {field} + ? WHERE id = ?", (amount, user_id))
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    
    if (user['q_cards_opened'] >= 10 and user['q_battles'] >= 5 and
        user['q_pvp_played'] >= 3 and user['q_shop_buys'] >= 1 and user['q_heals_done'] >= 5):
        
        await execute_db("""
            UPDATE users SET
                coins = coins + 1200,
                total_coins = total_coins + 1200,
                q_cards_opened = 0, q_battles = 0, q_pvp_played = 0, q_shop_buys = 0, q_heals_done = 0,
                quests_cooldown = ?
            WHERE id = ?
        """, (time.time() + 3600, user_id))
        
        packs = await fetch_all("SELECT id, title FROM seed_packs WHERE is_football = 0")
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
                msg = f"🎉 <b>ПОЗДРАВЛЯЕМ!</b>\nВы выполнили все ежедневные квесты и получили <b>1200 💰 Шекелей</b>!{pack_reward_text}\nВозвращайтесь через 1 час за новыми заданиями!"
                await bot.send_message(user_id, msg)
            except: 
                pass

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
    try: 
        await bot.send_message(SUPER_ADMIN_ID, f"⚠️ <b>ADMIN LOG:</b>\n{text}")
    except Exception as e: 
        logging.error(f"Не удалось отправить лог: {e}")

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

def get_main_keyboard(is_adm: bool = False, is_sgn: bool = False, is_football: bool = False):
    if is_football:
        kb = [
            [KeyboardButton(text=BTN_FB_DRAW), KeyboardButton(text=BTN_FB_SHOP), KeyboardButton(text=BTN_FB_PACKS)],
            [KeyboardButton(text=BTN_FB_BP), KeyboardButton(text=BTN_FB_MATCH), KeyboardButton(text=BTN_FB_LEAGUE)],
            [KeyboardButton(text=BTN_FB_PROF), KeyboardButton(text=BTN_FB_EQ), KeyboardButton(text=BTN_FB_INV)],
            [KeyboardButton(text=BTN_MAIN_MODE), KeyboardButton(text=BTN_FB_INDEX), KeyboardButton(text=BTN_FB_GUIDE)],
            [KeyboardButton(text=BTN_FB_TRANSFER)]
        ]
    else:
        kb = [
            [KeyboardButton(text=BTN_DRAW), KeyboardButton(text=BTN_PVE), KeyboardButton(text=BTN_PVP)],
            [KeyboardButton(text=BTN_INV), KeyboardButton(text=BTN_PROF), KeyboardButton(text=BTN_EQ)],
            [KeyboardButton(text=BTN_QUESTS), KeyboardButton(text=BTN_SHOP), KeyboardButton(text=BTN_BP)],
            [KeyboardButton(text=BTN_TOP), KeyboardButton(text=BTN_IDX), KeyboardButton(text=BTN_SEED_PACKS)],
            [KeyboardButton(text=BTN_WC), KeyboardButton(text=BTN_ENDLESS), KeyboardButton(text=BTN_CRAFT)],
            [KeyboardButton(text=BTN_SET)]
        ]
    
    bottom_row = []
    if is_sgn and not is_football: bottom_row.append(KeyboardButton(text=BTN_SIGN))
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
    if rarity in ['Leaderboard', 'Exclusive', 'Mythic', 'Super']: return True
    if rarity == 'Legendary' and mutation in ['Gold', 'Rainbow']: return True
    return False

async def give_card_to_user(user_id: int, card_id: int, mutation: str, rarity: str = None, custom_serial: int = None, is_football: int = 0) -> tuple:
    if not rarity:
        card = await fetch_one("SELECT rarity FROM cards WHERE id = ?", (card_id,))
        rarity = card['rarity'] if card else 'Basic'
        
    db = await get_db_connection()
    try:
        if custom_serial is not None and custom_serial > 0:
            cursor = await db.execute(
                "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by, is_football) VALUES (?, ?, 1, ?, ?, 0, ?)",
                (user_id, card_id, mutation, custom_serial, is_football)
            )
            return cursor.lastrowid, custom_serial, True
            
        if needs_serial_number(rarity, mutation):
            res = await db.execute("SELECT MAX(serial_number) as m FROM inventory WHERE card_id = ? AND mutation = ?", (card_id, mutation))
            row = await res.fetchone()
            curr_max = row['m'] if (row and row['m'] is not None) else 0
            new_serial = curr_max + 1
            
            cursor = await db.execute(
                "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by, is_football) VALUES (?, ?, 1, ?, ?, 0, ?)", 
                (user_id, card_id, mutation, new_serial, is_football)
            )
            return cursor.lastrowid, new_serial, True
        else:
            res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0 AND signed_by = 0 AND is_football = ?", (user_id, card_id, mutation, is_football))
            inv_item = await res.fetchone()
            if inv_item:
                await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                return inv_item['id'], 0, False
            else:
                cursor = await db.execute(
                    "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by, is_football) VALUES (?, ?, 1, ?, 0, 0, ?)", 
                    (user_id, card_id, mutation, is_football)
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
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=28))

async def clear_fsm_timeout(state: FSMContext, chat_id: int, delay: int = 60):
    await asyncio.sleep(delay)
    curr = await state.get_state()
    if curr in [TradeState.waiting_target.state, PvPState.waiting_target.state]:
        await state.clear()
        try:
            await bot.send_message(chat_id, "⏳ <i>Время ожидания истекло (1 минута). Команда сброшена.</i>")
        except: 
            pass

async def get_card_sources(card_id: int) -> str:
    sources = []
    packs = await fetch_all("SELECT p.title FROM seed_pack_cards spc JOIN seed_packs p ON spc.pack_id = p.id WHERE spc.card_id = ?", (card_id,))
    if packs:
        sources.append("📦 Сид-Паки: " + ", ".join([p['title'] for p in packs]))
    
    c = await fetch_one("SELECT drop_chance, rarity, is_cardball_exclusive FROM cards WHERE id = ?", (card_id,))
    if c:
        if c['drop_chance'] > 0 and c['rarity'] != 'Leaderboard' and c.get('is_cardball_exclusive', 0) == 0:
            sources.append("🎲 Гача (/getcard) / Магазин")
        if c['rarity'] == 'Leaderboard':
            sources.append("🏆 Топ игроков (Лидерборд)")
            
    bps = await fetch_all("SELECT bp.title FROM bp_rewards bpr JOIN bp_levels bpl ON bpr.level_id = bpl.id JOIN battle_passes bp ON bpl.bp_id = bp.id WHERE bpr.card_id = ?", (card_id,))
    if bps:
        sources.append("🎟 Батл-Пасс: " + ", ".join(list(set([b['title'] for b in bps]))))
        
    craft = await fetch_one("SELECT id FROM craft_recipes WHERE target_card_id = ?", (card_id,))
    if craft: sources.append("🔨 Мастерская Крафта")

    if not sources:
        return "Невозможно получить (Эксклюзив)"
    return "\n".join(f"  └ {s}" for s in sources)

# ========================================================================
# ЛОГИКА ШАНСОВ И МАГАЗИНА И PITY
# ========================================================================
async def calculate_chance_weights(luck_mult: float = 1.0, exclude_cardball=True):
    query = """
        SELECT * FROM cards 
        WHERE drop_chance > 0 
        AND rarity != 'Leaderboard'
        AND id NOT IN (SELECT card_id FROM seed_pack_cards)
    """
    if exclude_cardball:
        query += " AND is_cardball_exclusive = 0"
        
    all_cards = await fetch_all(query)
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
        for p_id, p_name_ru, p_price, p_max, p_chance in SHOP_PACKAGES:
            if random.random() <= p_chance:
                stock = random.randint(1, p_max)
                await db.execute("INSERT INTO shop_items (item_type, name, price, stock, is_football) VALUES (?, ?, ?, ?, 0)", (p_id, p_name_ru, p_price, stock))
                spawned_any = True
                spawned_types.add(p_id)
                
        # Спавним Cardball товары
        for p_id, p_name_ru, p_price, p_max, p_chance in SHOP_PACKAGES:
            if random.random() <= p_chance:
                stock = random.randint(1, p_max)
                price_fb = max(10, p_price // 10) 
                await db.execute("INSERT INTO shop_items (item_type, name, price, stock, is_football) VALUES (?, ?, ?, ?, 1)", (p_id, f"⚽ {p_name_ru}", price_fb, stock))
                
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

async def give_multiple_cards(user_id: int, count: int, is_football: int = 0) -> list:
    luck_mult, _ = await get_active_events()
    user = await fetch_one("SELECT pity_mythic, pity_super FROM users WHERE id=?", (user_id,))
    pm = user['pity_mythic'] if user else 0
    ps = user['pity_super'] if user else 0

    query = """
        SELECT * FROM cards 
        WHERE drop_chance > 0 
        AND rarity != 'Leaderboard'
        AND id NOT IN (SELECT card_id FROM seed_pack_cards)
    """
    if is_football == 0:
        query += " AND is_cardball_exclusive = 0"
    else:
        query += " AND is_cardball_exclusive = 1"
        
    all_cards = await fetch_all(query)
    if not all_cards: return []
    
    super_cards = [c for c in all_cards if c['rarity'] == 'Super']
    mythic_cards = [c for c in all_cards if c['rarity'] == 'Mythic']
    weights = [c['drop_chance'] * (luck_mult if c['drop_chance'] < 15.0 else 1.0) for c in all_cards]
    
    results = []
    for _ in range(count):
        card = random.choices(all_cards, weights=weights, k=1)[0]
        is_pity = False
        p_type = None

        if is_football == 0:
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
        _, serial, _ = await give_card_to_user(user_id, card['id'], mut, card['rarity'], is_football=is_football)

        c_copy = dict(card)
        c_copy['mutation'] = mut
        c_copy['serial_number'] = serial
        c_copy['is_pity'] = is_pity
        c_copy['pity_type'] = p_type
        c_copy['signed_by'] = 0
        results.append(c_copy)

    if is_football == 0:
        await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
    return results

async def leaderboard_rewards_task():
    while True:
        try:
            settings = await fetch_one("SELECT last_lb_reward FROM server_settings WHERE id = 1")
            now = time.time()
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
                            WHERE u.id != ? AND i.is_football = 0 GROUP BY u.id ORDER BY score DESC LIMIT 20
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
                                try: 
                                    await bot.send_message(user['id'], msg_text)
                                except: 
                                    pass
                
                # ИЗМЕНЕНИЕ: ТРОФЕИ ТЕПЕРЬ НЕ СБРАСЫВАЮТСЯ В 0
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
    
    await log_user_action(message.from_user.id, "Открыл главное меню (/start)")
    user = await fetch_one("SELECT football_mode FROM users WHERE id = ?", (message.from_user.id,))

    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    is_fb = user['football_mode'] == 1 if user else False
    
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
    await message.answer(text, reply_markup=get_main_keyboard(adm, sgn, is_football=is_fb))

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    if await check_ban(message.from_user.id): return
    guide = (
        "📖 <b>ОГРОМНОЕ РУКОВОДСТВО ПО CARD BATTLE BOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Добро пожаловать в карточную арену! Ниже описаны все основные механики нашего бота:\n\n"
        "⚔️ <b>ОСНОВНОЙ РЕЖИМ БОЯ (PvE и PvP)</b>\n"
        "• Вы можете собрать боевую колоду из 4-х карт. Для этого выбивайте карты в Гаче или покупайте в магазине.\n"
        "• Бой проходит в автоматическом или полуавтоматическом режиме (если включены модификаторы в Настройках).\n"
        "• В боях против ИИ (ботов) вы получаете <b>Шекели 💰</b>, кубки и опыт БП. Награды зависят от выбранной сложности.\n"
        "• <b>PvP Дуэли</b> позволяют сразиться с друзьями дружеской дуэлью (без изменения рейтинга и наград) или через автоподбор за кубки.\n\n"
        "💎 <b>РЕДКОСТИ И МУТАЦИИ КАРТ</b>\n"
        "Каждая карта имеет свою редкость и может выпасть с особой мутацией:\n"
        "⚪ Basic | 🟢 Uncommon | 🔵 Rare | 🟣 Epic | 🟡 Legendary | 🔴 Mythic | 🌈 Super | 🌸 Exclusive | 👑 Leaderboard\n"
        "• ⭐ <b>Золотая мутация</b> (+10% к характеристикам)\n"
        "• 🌈 <b>Радужная мутация</b> (+20% к характеристикам)\n\n"
        "⚡ <b>СИСТЕМА ГАРАНТИЙ (PITY)</b>\n"
        "• При открытии карт из обычной гачи вы застрахованы от неудач:\n"
        "└ Гарантированный <b>Мифик 🔴</b>: каждые 1000 открытий.\n"
        "└ Гарантированный <b>Супер 🌈</b>: каждые 10000 открытий.\n\n"
        "🔨 <b>МАСТЕРСКАЯ КРАФТА И СЛИЯНИЕ</b>\n"
        "• В меню Крафта вы можете создавать новые мощные карты по рецептам, вкладывая обычные копии.\n"
        "• Вы также можете слить 8 одинаковых обычных карт, чтобы гарантированно повысить их мутацию на уровень выше!\n\n"
        "🎟 <b>БАТЛ-ПАСС (СЕЗОНЫ)</b>\n"
        "• Получайте опыт БП за бои. Повышайте уровень и забирайте эксклюзивные награды, шекели и Сид-Паки!\n\n"
        "🤝 <b>СИСТЕМА ОБМЕНА (ТРЕЙДЫ)</b>\n"
        "• Используйте команду <code>/trade [ID/username]</code>, чтобы начать безопасный обмен картами с другим игроком в реальном времени!\n\n"
        "📞 <b>КОНТАКТЫ И СВЯЗЬ:</b>\n"
        "• 📰 Новости и обновления: @ggtdcardsnews\n"
        "• 💬 Наш чат поддержки: @ggtdcards_support\n"
        "• 📧 Email для предложений: ggtdcards@gmail.com\n"
    )
    await message.answer(guide)

@dp.message(F.text == BTN_WC)
async def cmd_switch_to_football(message: types.Message):
    await execute_db("UPDATE users SET football_mode = 1 WHERE id = ?", (message.from_user.id,))
    adm = await is_admin(message.from_user.id)
    await message.answer("⚽ <b>РЕЖИМ CARDBALL АКТИВИРОВАН!</b>\nСобери команду из 4 карт и сразись за мячи!", reply_markup=get_main_keyboard(adm, False, True))

@dp.message(F.text == BTN_MAIN_MODE)
async def cmd_switch_to_main(message: types.Message):
    await execute_db("UPDATE users SET football_mode = 0 WHERE id = ?", (message.from_user.id,))
    adm = await is_admin(message.from_user.id)
    sgn = await is_signer(message.from_user.id)
    await message.answer("🔙 <b>ВЫ ВЕРНУЛИСЬ В ОБЫЧНЫЙ РЕЖИМ!</b>", reply_markup=get_main_keyboard(adm, sgn, False))

@dp.message(F.text == BTN_ENDLESS)
async def cmd_endless(message: types.Message):
    text = (
        "♾ <b>БЕСКОНЕЧНЫЙ РЕЖИМ НАХОДИТСЯ В РАЗРАБОТКЕ!</b>\n\n"
        "Совсем скоро здесь появится возможность бросить вызов волнам врагов и получать эксклюзивные награды.\n\n"
        "Следите за новостями и связывайтесь с нами:\n"
        "📰 Новости: @ggtdcardsnews\n"
        "📞 Тех.поддержка: @ggtdcards_support\n"
        "📧 Почта: ggtdcards@gmail.com"
    )
    await message.answer(text)

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
    text = (
        "🧬 <b>МОДИФИКАТОРЫ БОЯ (PvE)</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВключите модификаторы для усложнения или упрощения боев с ботами.\n\n"
        "🔴 <b>Дебаффы</b> повышают награды (монеты, опыт, кубки).\n🟢 <b>Баффы</b> снижают награды (монеты, опыт), кубки не режутся."
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
    text = "🛒 <b>ФИЛЬТР УВЕДОМЛЕНИЙ МАГАЗИНА</b>\nВыберите, о каких товарах вас уведомлять:"
    def b(name_ru, col):
        st = "🔔" if user.get(col, 1) else "🔕"
        return InlineKeyboardButton(text=f"{name_ru} {st}", callback_data=f"set_shopfilt_{col}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [b("1 Случайная", "notif_1_rnd"), b("3 Случайные", "notif_3_rnd")],
        [b("5 Случайных", "notif_5_rnd"), b("10 Случайных", "notif_10_rnd")],
        [b("25 Случайных", "notif_25_rnd"), b("50 Случайных", "notif_50_rnd")],
        [b("100 Случайных", "notif_100_rnd"), b("Легендарная", "notif_rnd_leg")],
        [b("Мифическая", "notif_rnd_myth"), b("Супер Карта", "notif_rnd_sup")],
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
    user = await fetch_one("SELECT * FROM users WHERE id=?", (callback.from_user.id,))
    text = "⚙️ <b>НАСТРОЙКИ АККАУНТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Фильтр Магазина", callback_data="set_shop_filters")],
        [InlineKeyboardButton(text="🧬 Модификаторы боя (PvE)", callback_data="set_modifiers")],
        [InlineKeyboardButton(text=f"🎉 Ивенты: {'🔔 Вкл' if user['notif_events'] else '🔕 Выкл'}", callback_data="set_toggle_events")],
        [InlineKeyboardButton(text=f"📜 Квесты: {'🔔 Вкл' if user['notif_quests'] else '🔕 Выкл'}", callback_data="set_toggle_quests")],
        [InlineKeyboardButton(text=f"📢 Анонсы: {'🔔 Вкл' if user['notif_announces'] else '🔕 Выкл'}", callback_data="set_toggle_announces")]
    ])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass
    await callback.answer()

@dp.message(Command("profile"), F.chat.type == "private")
@dp.message(F.text.in_([BTN_PROF, BTN_FB_PROF]))
async def cmd_profile(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    
    is_fb = user['football_mode'] == 1
    rank = await get_user_rank(user['football_trophies'] if is_fb else user['trophies'])
    total_cards = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE user_id = ? AND is_football = ?", (user['id'], 1 if is_fb else 0))
    name = get_display_name(user)
    title_str = await get_user_titles_str(user['id'])
    
    active_bp = await fetch_one("""
        SELECT bp.title, ubp.level, ubp.xp 
        FROM user_bp ubp JOIN battle_passes bp ON ubp.bp_id = bp.id 
        WHERE ubp.user_id = ? AND ubp.is_active = 1 AND bp.is_football = ?
    """, (user['id'], 1 if is_fb else 0))
    
    bp_text = "<i>Нет активного Батл-пасса</i>"
    if active_bp:
        bp_text = f"<b>{active_bp['title']}</b> (Ур. {active_bp['level']} | {active_bp['xp']} XP)"

    mode_title = "⚽ Профиль Cardball" if is_fb else "👤 Профиль игрока"
    bal_str = f"⚽ <b>Мячей:</b> {user['football_balls']}" if is_fb else f"💰 <b>Шекелей:</b> {user['coins']}"
    tr_str = user['football_trophies'] if is_fb else user['trophies']
    
    text = (
        f"{mode_title} <b>{name}</b>{title_str}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎖 <b>Ранг:</b> {rank['name']}\n🏆 <b>Кубки:</b> {tr_str}\n{bal_str}\n"
        f"🃏 <b>Всего карт:</b> {total_cards['s'] or 0}\n🎟 <b>Активный БП:</b> {bp_text}\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    if not is_fb:
        text += (
            f"🔮 <b>Гарант на Мифик:</b> {make_progress_bar(user['pity_mythic'], 1000, 8)} ({user['pity_mythic']}/1000)\n"
            f"🌠 <b>Гарант на Супер:</b> {make_progress_bar(user['pity_super'], 10000, 8)} ({user['pity_super']}/10000)\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )
        
    text += "⚔️ <b>Экипировка:</b>\n"
    slots = ['fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4'] if is_fb else ['equip1', 'equip2', 'equip3', 'equip4']
    role_names = ["Вратарь", "Защитник", "Полузащитник", "Нападающий"]
    
    for i, slot in enumerate(slots):
        inv_id = user[slot]
        role_label = f"[{role_names[i]}] " if is_fb else f"{i+1}️⃣ "
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
                    text += f" {role_label}{n}{mut_str}\n      └ <i>Бафф: DMG x{round(row['booster_dmg_mult']*mult, 2)} | HP x{round(row['booster_hp_mult']*mult, 2)}</i>\n"
                elif row['class_type'] == 'Healer':
                    text += f" {role_label}{n}{mut_str}\n      └ <i>Статы: 💗 Лечение: {int(row['damage']*mult)} | ❤️ Здоровье: {int(row['hp']*mult)}</i>\n"
                else: 
                    text += f" {role_label}{n}{mut_str}\n      └ <i>Статы: ⚔️ Урон: {int(row['damage']*mult)} | ❤️ Здоровье: {int(row['hp']*mult)}</i>\n"
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
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    
    now = time.time()
    if user['quests_cooldown'] > now:
        left = int(user['quests_cooldown'] - now)
        m, s = divmod(left, 60)
        return await message.answer(f"⏳ <b>Все квесты выполнены!</b>\nНовые задания появятся через {m} мин. {s} сек.")
    
    c_op = min(10, user['q_cards_opened'])
    b_pl = min(5, user['q_battles'])
    p_pl = min(3, user['q_pvp_played'])
    s_bu = min(1, user['q_shop_buys'])
    h_dn = min(5, user['q_heals_done'])
    
    text = (
        "📜 <b>ЕЖЕДНЕВНЫЕ КВЕСТЫ</b>\n"
        "<i>Выполни все задания, чтобы сорвать куш в 1200 💰 Шекелей и получить 1 Сид-Пак!</i>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"1️⃣ <b>Открыть 10 карточек:</b>\n{make_progress_bar(c_op, 10, 8)} {c_op}/10 {'✅' if c_op>=10 else '❌'}\n\n"
        f"2️⃣ <b>Сыграть 5 PvE боёв:</b>\n{make_progress_bar(b_pl, 5, 8)} {b_pl}/5 {'✅' if b_pl>=5 else '❌'}\n\n"
        f"3️⃣ <b>Сыграть 3 PvP дуэли:</b>\n{make_progress_bar(p_pl, 3, 8)} {p_pl}/3 {'✅' if p_pl>=3 else '❌'}\n\n"
        f"4️⃣ <b>Купить любой товар в Магазине:</b>\n{make_progress_bar(s_bu, 1, 8)} {s_bu}/1 {'✅' if s_bu>=1 else '❌'}\n\n"
        f"5️⃣ <b>Исцелить союзников 5 раз (💗 Healer):</b>\n{make_progress_bar(h_dn, 5, 8)} {h_dn}/5 {'✅' if h_dn>=5 else '❌'}\n"
    )
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
        title_ru = "🏆 <b>МИРОВОЙ РЕЙТИНГ: КУБКИ (Топ-20)</b>"
        unit = "🏆"
    elif lb_type == 'coins':
        top_users = await fetch_all("SELECT username, first_name, id, total_coins as score FROM users WHERE id != ? ORDER BY total_coins DESC LIMIT 20", (SUPER_ADMIN_ID,))
        title_ru = "💰 <b>МИРОВОЙ РЕЙТИНГ: ШЕКЕЛИ (Топ-20)</b>"
        unit = "💰"
    else:
        top_users = await fetch_all("SELECT u.id, u.username, u.first_name, SUM(i.count) as score FROM users u JOIN inventory i ON u.id = i.user_id WHERE u.id != ? AND i.is_football = 0 GROUP BY u.id ORDER BY score DESC LIMIT 20", (SUPER_ADMIN_ID,))
        title_ru = "🃏 <b>МИРОВОЙ РЕЙТИНГ: КАРТЫ (Топ-20)</b>"
        unit = "🃏"

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
                if r['reward_type'] == 'shekels':
                    r_strs.append(f"{r['amount']} 💰")
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
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Кубки (Сезон)", callback_data="top_trophies")],
        [InlineKeyboardButton(text="💰 Монеты (Все время)", callback_data="top_coins")],
        [InlineKeyboardButton(text="🃏 Карты (Все время)", callback_data="top_cards")]
    ])
    try: await callback.message.edit_text("🏆 <b>МИРОВЫЕ РЕЙТИНГИ</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите категорию лидерборда:", reply_markup=kb)
    except: pass
    await callback.answer()

@dp.message(Command("shop"))
@dp.message(F.text.in_([BTN_SHOP, BTN_FB_SHOP]))
async def cmd_shop(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins, football_balls, football_mode FROM users WHERE id = ?", (message.from_user.id,))
    is_fb = user['football_mode'] == 1 if user else False
    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0 AND is_football = ?", (1 if is_fb else 0,))
    
    if not items:
        return await message.answer("🛒 <b>Магазин пока пуст.</b>\nЗавоз осуществляется каждые полтора часа. Жди уведомления!")
        
    bal = user['football_balls'] if is_fb else user['coins']
    val_sym = "⚽" if is_fb else "💰"
    val_name = "Мячей" if is_fb else "Шекелей"
    
    text = f"🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН {'(CARDBALL)' if is_fb else ''}</b>\n{val_sym} Твой баланс: <b>{bal} {val_name}</b>\n<i>(Товары общие для всех. Кто успел, тот и купил!)</i>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    kb = []
    for i, item in enumerate(items, 1):
        text += f"📦 <b>{item['name']}</b>\n      └ 💵 Цена: <b>{item['price']} {val_sym}</b> | Остаток: <b>{item['stock']} шт.</b>\n\n"
        kb.append([InlineKeyboardButton(text=f"Купить: {item['name']} ({item['price']} {val_sym})", callback_data=f"buy_shop_{item['id']}")])
        
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_shop_"))
async def callback_buy_shop(callback: types.CallbackQuery):
    shop_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT coins, football_balls, pity_mythic, pity_super FROM users WHERE id = ?", (user_id,))
    item = await fetch_one("SELECT * FROM shop_items WHERE id = ?", (shop_id,))
    
    if not item or item['stock'] <= 0: return await callback.answer("❌ Этот товар закончился!", show_alert=True)
    
    is_fb = item['is_football'] == 1
    bal_col = 'football_balls' if is_fb else 'coins'
    
    if user[bal_col] < item['price']: return await callback.answer("❌ Недостаточно средств!", show_alert=True)
    
    await execute_db(f"UPDATE users SET {bal_col} = {bal_col} - ? WHERE id = ?", (item['price'], user_id))
    await execute_db("UPDATE shop_items SET stock = stock - 1 WHERE id = ?", (shop_id,))
    
    if not is_fb: await add_quest_progress(user_id, 'q_shop_buys', 1)
    
    i_type = item['item_type']
    if i_type.endswith("_rnd"):
        count = int(i_type.split("_")[0])
        won = await give_multiple_cards(user_id, count, is_football=1 if is_fb else 0)
        
        if not is_fb: await add_quest_progress(user_id, 'q_cards_opened', count)
            
        pity_pulls = [c for c in won if c.get('is_pity')]
        
        if count == 1: 
            mut_str = "🌈 " if won[0]['mutation'] == 'Rainbow' else ("⭐ " if won[0]['mutation'] == 'Gold' else "")
            msg = f"✨ <b>Грандиозная покупка!</b>\nВы выбили: {mut_str}{format_card_name(won[0])}"
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
        
        query = "SELECT * FROM cards WHERE rarity = ? AND id NOT IN (SELECT card_id FROM seed_pack_cards)"
        if is_fb == 0: query += " AND is_cardball_exclusive = 0"
        else: query += " AND is_cardball_exclusive = 1"
        
        all_cards = await fetch_all(query, (target_rarity,))
        if not all_cards:
            await execute_db(f"UPDATE users SET {bal_col} = {bal_col} + ? WHERE id = ?", (item['price'], user_id))
            return await callback.message.answer("❌ Ошибка БД.")
            
        won_card = random.choice(all_cards)
        mut = roll_mutation()
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'], is_football=1 if is_fb else 0)
        won_card['serial_number'] = serial
        won_card['signed_by'] = 0
        
        if not is_fb: await add_quest_progress(user_id, 'q_cards_opened', 1)
            
        pm = user['pity_mythic']; ps = user['pity_super']
        if target_rarity == 'Super': ps = 0; pm += 1
        elif target_rarity == 'Mythic': pm = 0; ps += 1
        else: ps += 1; pm += 1
        await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
        
        mut_str = "🌈 Радужная" if mut == 'Rainbow' else ("⭐ Золотая" if mut == 'Gold' else "Обычная")
        await callback.message.answer(f"✨ <b>Успешная покупка ГАРАНТА!</b>\nВы выбили: {format_card_name(won_card)}\nМутация: <b>{mut_str}</b>")

    await log_user_action(user_id, f"Купил в магазине: {i_type} ({item['price']})")

    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0 AND is_football = ?", (1 if is_fb else 0,))
    if not items:
        await callback.message.edit_text("🛒 <b>Магазин полностью распродан!</b>\nЖдите следующего завоза.")
    else:
        new_val = user[bal_col] - item['price']
        val_sym = "⚽" if is_fb else "💰"
        val_name = "Мячей" if is_fb else "Шекелей"
        text = f"🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН {'(CARDBALL)' if is_fb else ''}</b>\n{val_sym} Твой баланс: <b>{new_val} {val_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        kb = []
        for i, itm in enumerate(items, 1):
            text += f"📦 <b>{itm['name']}</b>\n      └ 💵 Цена: <b>{itm['price']} {val_sym}</b> | Остаток: <b>{itm['stock']} шт.</b>\n\n"
            kb.append([InlineKeyboardButton(text=f"Купить: {itm['name']} ({itm['price']} {val_sym})", callback_data=f"buy_shop_{itm['id']}")])
        try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        except: pass
    
    await callback.answer()

# ========================================================================
# СИСТЕМА ГАЧИ (ВЫБИВАНИЕ КАРТ) И МУТАЦИИ
# ========================================================================
@dp.message(Command("getcard"))
@dp.message(F.text.in_([BTN_DRAW, BTN_FB_DRAW]))
async def cmd_getcard(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    
    if user['id'] in user_trades: return await message.answer("❌ Завершите обмен перед выбиванием!")
    is_fb = message.text == BTN_FB_DRAW or (message.text.startswith("/") and user['football_mode'] == 1)
    
    luck_mult, cd_mult = await get_active_events()
    
    # Раздельные кулдауны: Кардболл гача — 10 минут, Обычная гача — 4 минуты
    base_cooldown = 10 * 60 if is_fb else 4 * 60
    actual_cooldown = int(base_cooldown / cd_mult)
    
    now = time.time()
    last_col = 'last_fb_getcard' if is_fb else 'last_getcard'
    passed = now - user[last_col]
    
    if passed < actual_cooldown:
        left = int(actual_cooldown - passed)
        mins, secs = divmod(left, 60)
        return await message.answer(f"⏳ <b>Колода перемешивается!</b>\nОжидай: <b>{mins} мин. {secs} сек.</b>")
        
    won_list = await give_multiple_cards(user['id'], 1, is_football=1 if is_fb else 0)
    if not won_list: return await message.answer("😔 В базе нет карт для этой гачи.")
    won_card = won_list[0]
        
    await execute_db(f"UPDATE users SET {last_col} = ? WHERE id = ?", (now, user['id']))
    if not is_fb: await add_quest_progress(user['id'], 'q_cards_opened', 1)
    await log_user_action(user['id'], f"Выбил карту{' (CARDBALL)' if is_fb else ''}: {won_card['name']} (ID:{won_card['id']}, Мутация: {won_card['mutation']})")
    
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
        msg += f"✨ <b>БУСТЕР</b>\n   └ Бафф DMG: <b>x{round(won_card['booster_dmg_mult']*mult, 2)}</b> | HP: <b>x{round(won_card['booster_hp_mult']*mult, 2)}</b>\n"
    elif won_card['class_type'] == 'Healer':
        msg += f"💗 <b>Лечение:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n"
    else: 
        msg += f"⚔️ <b>Урон:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n"
        
    if luck_mult > 1.0 and won_card['drop_chance'] < 15.0:
        msg += f"\n🍀 <i>Сработал ивент удачи!</i>"
        
    await message.answer_photo(photo=won_card['photo_id'], caption=msg)

# ========================================================================
# ИНДЕКС С РАЗДЕЛАМИ
# ========================================================================
async def get_index_text(user_id: int, page: int = 0, items_per_page: int = 8, is_fb: bool = False, sub_section: str = "all"):
    # sub_section для Кардбалла: "all", "fb_exclusive", "ordinary"
    query = "SELECT * FROM cards"
    if is_fb:
        if sub_section == "fb_exclusive":
            query += " WHERE is_cardball_exclusive = 1"
        elif sub_section == "ordinary":
            query += " WHERE is_cardball_exclusive = 0"
    else:
        query += " WHERE is_cardball_exclusive = 0"
        
    all_cards = await fetch_all(query)
    user_inv = await fetch_all("SELECT DISTINCT card_id FROM inventory WHERE user_id = ?", (user_id,))
    user_card_ids = [item['card_id'] for item in user_inv]
    recipes = await fetch_all("SELECT target_card_id FROM craft_recipes")
    crafted_ids = [r['target_card_id'] for r in recipes]
    
    if not all_cards: return "Индекс пуст.", None
    
    luck_mult, _ = await get_active_events()
    weights_dict, total_w = await calculate_chance_weights(luck_mult, exclude_cardball=(not is_fb))
    
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
    
    title_str = "⚽ CARDBALL" if is_fb else "🎒 ОСНОВНОЙ"
    if is_fb:
        title_str += f" ({'Все юниты' if sub_section == 'all' else ('Футбольные' if sub_section == 'fb_exclusive' else 'Обычные')})"
        
    text = f"📖 <b>{title_str} ИНДЕКС КАРТ (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
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
        if c['id'] in crafted_ids: n_fmt += " [🛠 Крафт]"
        r_fmt = format_rarity_display(c['rarity'])
        
        if c['id'] in pack_info:
            p_info = pack_info[c['id']]
            p_title = p_info['title']
            p_weight = p_info['pack_chance']
            if p_weight < 15.0: p_weight *= luck_mult
            p_total = pack_totals.get(p_title, 1)
            real_chance = (p_weight / p_total) * 100 if p_total > 0 else 0
            chance_str = f"Шанс: {real_chance:.4f}% <b>(Пак «{p_title}»)</b>"
        elif c['rarity'] == 'Leaderboard':
            chance_str = "Только за Топ!"
        else:
            real_chance = (weights_dict.get(c['id'], 0) / total_w) * 100 if total_w > 0 else 0
            chance_str = f"Шанс из Гачи: {real_chance:.4f}%"
        
        if c['id'] in user_card_ids:
            text += f"{i}. {n_fmt}\n      └ 💎 {r_fmt} ({chance_str})\n"
            if c['class_type'] == 'Booster': 
                text += f"      └ ✨ Бафф: DMG x{c['booster_dmg_mult']} // HP x{c['booster_hp_mult']}\n"
            elif c['class_type'] == 'Healer': 
                text += f"      └ 💗 Лечение: {c['damage']} // ❤️ Здоровье: {c['hp']}\n"
            else: 
                text += f"      └ ⚔️ Урон: {c['damage']} // ❤️ Здоровье: {c['hp']}\n"
            text += f"      └ 🌍 Существует: {total_exists} шт.{mut_str}\n\n"
        else:
            text += f"{i}. <b>???</b> (Не открыто)\n      └ 💎 {r_fmt} ({chance_str})\n      └ 🌍 Существует: {total_exists} шт.{mut_str}\n\n"
            
    kb = []
    
    # Добавляем кнопки разделов ТОЛЬКО для Cardball-Индекса
    if is_fb:
        kb.append([
            InlineKeyboardButton(text="🎯 Все", callback_data=f"idxfb_sec_all_{page}"),
            InlineKeyboardButton(text="⚽ Только Футбол", callback_data=f"idxfb_sec_fb_exclusive_{page}"),
            InlineKeyboardButton(text="🎒 Обычные", callback_data=f"idxfb_sec_ordinary_{page}")
        ])

    nav_row = []
    cb_prefix = f"idxfb_{sub_section}_" if is_fb else "idx_"
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"{cb_prefix}page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"{cb_prefix}page_{page+1}"))
    if nav_row: kb.append(nav_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("index"))
@dp.message(F.text.in_([BTN_IDX, BTN_FB_INDEX]))
async def cmd_index(message: types.Message):
    if await check_ban(message.from_user.id): return
    is_fb = message.text == BTN_FB_INDEX
    text, kb = await get_index_text(message.from_user.id, 0, is_fb=is_fb)
    await message.answer(text, reply_markup=kb)
    
@dp.callback_query(F.data.startswith("idx_page_"))
async def callback_index_page(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[2])
    text, kb = await get_index_text(callback.from_user.id, page, is_fb=False)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("idxfb_"))
async def callback_idxfb_router(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    # dxfb_sec_[section]_[page] или dxfb_[section]_page_[page]
    if parts[1] == "sec":
        sub_sec = parts[2]
        page = int(parts[3])
        text, kb = await get_index_text(callback.from_user.id, page, is_fb=True, sub_section=sub_sec)
        await callback.message.edit_text(text, reply_markup=kb)
    else:
        sub_sec = parts[1]
        page = int(parts[3])
        text, kb = await get_index_text(callback.from_user.id, page, is_fb=True, sub_section=sub_sec)
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# ========================================================================
# ИНВЕНТАРЬ
# ========================================================================
async def get_inventory_text_and_kb(user_id: int, page: int = 0, items_per_page: int = 30, is_football: int = 0):
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name
        FROM inventory i JOIN cards c ON i.card_id = c.id LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.count > 0 AND i.is_football = ?
    """, (user_id, is_football))
    
    fb_str = " (CARDBALL)" if is_football else ""
    toggle_row = [
        InlineKeyboardButton(text=f"🎒 Карты (Выбрано)", callback_data="ignore"),
        InlineKeyboardButton(text=f"📦 Сид-Паки{fb_str}", callback_data=f"inv_packs_menu_{is_football}")
    ]
    
    if not inv: 
        return f"🎒 Ваш инвентарь{fb_str} пуст. Используйте /getcard", InlineKeyboardMarkup(inline_keyboard=[toggle_row])
        
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
    
    text = f"🎒 <b>ИНВЕНТАРЬ КАРТ{fb_str} (Стр. {page+1}/{total_pages})</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for item in page_items:
        n_fmt = format_card_name(item).replace(" <b>[#-001]</b>", "")
        mut_emoji = ""
        if item['mutation'] == "Gold": mut_emoji = "⭐ "
        elif item['mutation'] == "Rainbow": mut_emoji = "🌈 "
        text += f"• {mut_emoji}{n_fmt} — <b>{item['count']} шт.</b>\n"
        
    kb = [toggle_row]
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"inv_page_{page-1}_{is_football}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"inv_page_{page+1}_{is_football}"))
    if nav_row: kb.append(nav_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("inventory"))
@dp.message(F.text.in_([BTN_INV, BTN_FB_INV]))
async def cmd_inventory(message: types.Message):
    if await check_ban(message.from_user.id): return
    is_fb = message.text == BTN_FB_INV
    text, kb = await get_inventory_text_and_kb(message.from_user.id, 0, is_football=1 if is_fb else 0)
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("inv_page_"))
async def callback_inventory_page(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    page = int(parts[2])
    is_fb = int(parts[3]) if len(parts) > 3 else 0
    text, kb = await get_inventory_text_and_kb(callback.from_user.id, page, is_football=is_fb)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.message(F.text == BTN_SIGN)
async def cmd_sign_card(message: types.Message):
    if await check_ban(message.from_user.id): return
    if not await is_signer(message.from_user.id): return
    if message.from_user.id in user_trades: return await message.answer("❌ Завершите обмен перед подписыванием карт!")
    
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.id as inv_id, i.count, i.mutation, i.serial_number, i.signed_by
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0 AND i.signed_by = 0 AND i.is_football = 0
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
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0 AND i.signed_by = 0 AND i.is_football = 0
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
            await db.execute("UPDATE users SET equip1 = 0 WHERE equip1 = ?", (inv_id,))
            await db.execute("UPDATE users SET equip2 = 0 WHERE equip2 = ?", (inv_id,))
            await db.execute("UPDATE users SET equip3 = 0 WHERE equip3 = ?", (inv_id,))
            await db.execute("UPDATE users SET equip4 = 0 WHERE equip4 = ?", (inv_id,))
        else:
            await db.execute("UPDATE inventory SET count = count - 1 WHERE id = ?", (inv_id,))
            
        cur2 = await db.execute("""
            SELECT id FROM inventory 
            WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = ? AND signed_by = ? AND is_football = 0
        """, (user_id, row['card_id'], row['mutation'], row['serial_number'], user_id))
        dest = await cur2.fetchone()
        
        if dest:
            await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (dest['id'],))
        else:
            await db.execute("""
                INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by, is_football)
                VALUES (?, ?, 1, ?, ?, ?, 0)
            """, (user_id, row['card_id'], row['mutation'], row['serial_number'], user_id))
            
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

# ========================================================================
# ЭКИПИРОВКА (4 СЛОТА)
# ========================================================================
def get_equip_main_keyboard(user_info, cards_info, is_football=False):
    kb = []
    slots = ['fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4'] if is_football else ['equip1', 'equip2', 'equip3', 'equip4']
    role_names = ["Вратарь", "Защитник", "Полузащитник", "Нападающий"]
    
    for i, slot in enumerate(slots, 1):
        inv_id = user_info[slot]
        sl_t = f"[{role_names[i-1]}]" if is_football else f"Слот {i}"
        text = f"{sl_t} [Пусто]" if inv_id == 0 else f"{sl_t}: {cards_info.get(inv_id, f'ID: {inv_id}')}"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"eq_select_{i}_{1 if is_football else 0}")])
    kb.append([InlineKeyboardButton(text="❌ Очистить колоду", callback_data=f"eq_clear_{1 if is_football else 0}")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("equip"))
@dp.message(F.text.in_([BTN_EQ, BTN_FB_EQ]))
async def cmd_equip(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("/start")
    
    is_fb = message.text == BTN_FB_EQ
    if message.from_user.id in user_trades: return await message.answer("❌ Завершите обмен перед экипировкой!")
    
    slots = ['fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4'] if is_fb else ['equip1', 'equip2', 'equip3', 'equip4']
    inv_ids = [c for c in [user[s] for s in slots] if c != 0]
    
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
            
    header = "🛡 <b>СОСТАВ CARDBALL</b>" if is_fb else "🛡 <b>БОЕВАЯ КОЛОДА</b>"
    await message.answer(f"{header}\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите слот/позицию:", reply_markup=get_equip_main_keyboard(user, cards_info, is_fb))

@dp.callback_query(F.data.startswith("eq_clear_"))
async def cb_eq_clear(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_fb = int(callback.data.split("_")[2])
    
    if is_fb:
        await execute_db("UPDATE users SET fb_equip1 = 0, fb_equip2 = 0, fb_equip3 = 0, fb_equip4 = 0 WHERE id = ?", (user_id,))
    else:
        await execute_db("UPDATE users SET equip1 = 0, equip2 = 0, equip3 = 0, equip4 = 0 WHERE id = ?", (user_id,))
        
    await callback.message.edit_text("✅ Боевая колода успешно очищена!")
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_select_"))
async def equip_slot_callback(callback: types.CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    slot_num = int(parts[2])
    is_fb = int(parts[3])
    
    inv = await fetch_all("""
        SELECT DISTINCT c.id, c.name, c.rarity, c.class_type
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ? AND i.count > 0 AND i.is_football = ?
    """, (callback.from_user.id, is_fb))
    
    if not inv: return await callback.answer("Нет карт!", show_alert=True)
    
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']}"} for c in inv]
    
    await state.update_data(equip_slot=slot_num, equip_items_cards=items, equip_is_fb=is_fb)
    kb = get_pagination_keyboard(items, 0, "eq_c", columns=1, items_per_page=8)
    
    role_names = ["Вратаря", "Защитника", "Полузащитника", "Нападающего"]
    lbl = role_names[slot_num-1] if is_fb else f"Слота {slot_num}"
    await callback.message.edit_text(f"👇 Выберите карту для <b>{lbl}</b>:", reply_markup=kb)
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
    is_fb = data.get('equip_is_fb', 0)
    
    invs = await fetch_all("""
        SELECT i.id as inv_id, c.name, c.rarity, c.class_type, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name, i.count
        FROM inventory i 
        JOIN cards c ON i.card_id = c.id 
        LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.card_id = ? AND i.count > 0 AND i.is_football = ?
    """, (callback.from_user.id, card_id, is_fb))
    
    if not invs: return await callback.answer("Карта пропала!", show_alert=True)
    
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
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"eq_select_{slot_num}_{is_fb}")])
    
    role_names = ["Вратаря", "Защитника", "Полузащитника", "Нападающего"]
    lbl = role_names[slot_num-1] if is_fb else f"Слота {slot_num}"
    await callback.message.edit_text(f"👇 Выберите конкретную копию для <b>{lbl}</b>:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_v_page_"))
async def equip_var_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('equip_items_vars', []), page, "eq_v", columns=1, items_per_page=6)
    slot_num = data.get('equip_slot', 1)
    is_fb = data.get('equip_is_fb', 0)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"eq_select_{slot_num}_{is_fb}")])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_v_"))
async def equip_var_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    slot_num = data.get('equip_slot', 1)
    is_fb = data.get('equip_is_fb', 0)
    
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    
    slots = ['fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4'] if is_fb else ['equip1', 'equip2', 'equip3', 'equip4']
    current_eq = [user[s] for s in slots]
    
    if inv_id in current_eq:
        return await callback.answer("❌ Эта копия уже экипирована!", show_alert=True)
        
    card_info = await fetch_one("SELECT card_id FROM inventory WHERE id = ?", (inv_id,))
    if not card_info: return await callback.answer("Error")
    
    if user[slots[slot_num-1]] in current_eq:
        current_eq.remove(user[slots[slot_num-1]])
    
    if any(i != 0 for i in current_eq):
        inv_list = ",".join(map(str, [i for i in current_eq if i != 0]))
        other_cards = await fetch_all(f"SELECT card_id FROM inventory WHERE id IN ({inv_list})")
        if any(c['card_id'] == card_info['card_id'] for c in other_cards):
            return await callback.answer("❌ Нельзя надеть две одинаковые карты!", show_alert=True)

    await execute_db(f"UPDATE users SET {slots[slot_num-1]} = ? WHERE id = ?", (inv_id, callback.from_user.id))
    role_names = ["Вратарь", "Защитник", "Полузащитник", "Нападающий"]
    lbl = role_names[slot_num-1] if is_fb else f"Слот {slot_num}"
    await callback.message.edit_text(f"✅ Установлено в позицию: {lbl}!")
    await state.clear()
    await callback.answer()

# ========================================================================
# БАТЛ-ПАСС
# ========================================================================
@dp.message(F.text.in_([BTN_BP, BTN_FB_BP]))
async def cmd_battle_passes(message: types.Message):
    if await check_ban(message.from_user.id): return
    is_fb = message.text == BTN_FB_BP
    passes = await fetch_all("SELECT * FROM battle_passes WHERE is_football = ? ORDER BY id DESC", (1 if is_fb else 0,))
    
    if not passes:
        return await message.answer("🎟 <b>Батл-пассы</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nНет доступных сезонов.")
        
    kb = []
    for bp in passes:
        kb.append([InlineKeyboardButton(text=f"🎫 {bp['title']}", callback_data=f"bp_view_{bp['id']}")])
        
    await message.answer("🎟 <b>БАТЛ-ПАССЫ</b>\nВыберите сезон:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("bp_view_"))
async def callback_bp_view(callback: types.CallbackQuery):
    bp_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    bp = await fetch_one("SELECT * FROM battle_passes WHERE id = ?", (bp_id,))
    if not bp: return await callback.answer("Not found!", show_alert=True)
    is_fb = bp['is_football']
    
    user_bp = await fetch_one("SELECT * FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    if not user_bp:
        await execute_db("INSERT INTO user_bp (user_id, bp_id, xp, level, is_active) VALUES (?, ?, 0, 0, 0)", (user_id, bp_id))
        user_bp = await fetch_one("SELECT * FROM user_bp WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
        
    is_active = bool(user_bp['is_active'])
    status_str = "🟢 <b>АКТИВЕН</b>" if is_active else "🔴 <b>НЕАКТИВЕН</b>"
    
    curr_lvl = user_bp['level']
    curr_xp = user_bp['xp']
    
    next_lvl_data = await fetch_one("SELECT xp_required FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, curr_lvl + 1))
    req_xp = next_lvl_data['xp_required'] if next_lvl_data else 0
    
    if next_lvl_data: progress_str = f"{make_progress_bar(curr_xp, req_xp, 12)} ({curr_xp}/{req_xp})"
    else: progress_str = "🏆 <b>ПОЛНОСТЬЮ ПРОЙДЕН!</b>"

    text = (
        f"🏆 <b>СЕЗОН: {bp['title']}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n📊 Статус: {status_str}\n🎖 Уровень: <b>{curr_lvl}</b>\n✨ Опыт: {progress_str}\n"
    )
    
    kb = []
    if not is_active:
        kb.append([InlineKeyboardButton(text="✅ Сделать активным", callback_data=f"bp_set_act_{bp_id}")])
    kb.append([InlineKeyboardButton(text="▶️ Уровни и награды", callback_data=f"bp_lvl_{bp_id}_1")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"bp_list_{is_fb}")])
    
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

@dp.callback_query(F.data.startswith("bp_list_"))
async def callback_bp_list(callback: types.CallbackQuery):
    is_fb = int(callback.data.split("_")[2])
    passes = await fetch_all("SELECT * FROM battle_passes WHERE is_football = ? ORDER BY id DESC", (is_fb,))
    kb = []
    for bp in passes:
        kb.append([InlineKeyboardButton(text=f"🎫 {bp['title']}", callback_data=f"bp_view_{bp['id']}")])
    try: await callback.message.edit_text("🎟 <b>БАТЛ-ПАССЫ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except:
        await callback.message.answer("🎟 <b>БАТЛ-ПАССЫ</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("bp_set_act_"))
async def callback_bp_set_active(callback: types.CallbackQuery):
    bp_id = int(callback.data.split("_")[3])
    user_id = callback.from_user.id
    
    bp = await fetch_one("SELECT is_football FROM battle_passes WHERE id = ?", (bp_id,))
    is_fb = bp['is_football']
    
    await execute_db("""
        UPDATE user_bp SET is_active = 0 
        WHERE user_id = ? AND bp_id IN (SELECT id FROM battle_passes WHERE is_football = ?)
    """, (user_id, is_fb))
    
    await execute_db("UPDATE user_bp SET is_active = 1 WHERE user_id = ? AND bp_id = ?", (user_id, bp_id))
    await callback.answer()
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
    is_fb = bp['is_football']
    
    lvl_data = await fetch_one("SELECT id, xp_required FROM bp_levels WHERE bp_id = ? AND level = ?", (bp_id, req_level))
    if not lvl_data: return await callback.answer("Level not found", show_alert=True)
        
    rewards = await fetch_all("SELECT * FROM bp_rewards WHERE level_id = ?", (lvl_data['id'],))
    val_name = "Мячей" if is_fb else "Шекелей"
    val_sym = "⚽" if is_fb else "💰"
    
    text = (
        f"🏆 <b>{bp['title']} | Уровень {req_level}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n<i>Требуется XP: {lvl_data['xp_required']}</i>\n\n🎁 <b>Награды:</b>\n"
    )
    
    if not rewards:
        text += "└ <i>Наград нет.</i>\n"
    else:
        for r in rewards:
            if r['reward_type'] == 'shekels':
                text += f"└ {val_sym} <b>{r['amount']} {val_name}</b>\n"
            elif r['reward_type'] == 'card':
                c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['card_id'],))
                n = c['name'] if c else "Unknown"
                mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                text += f"└ 🃏 <b>{mut} {n}</b>\n"
                
    text += "\n📊 <b>Статус:</b> "
    is_reached = user_curr_lvl >= req_level
    claim_check = await fetch_one("SELECT * FROM user_bp_claims WHERE user_id = ? AND bp_id = ? AND level = ?", (user_id, bp_id, req_level))
    is_claimed = bool(claim_check)
    
    if is_claimed: text += "✅ <i>Уже получено</i>"
    elif is_reached: text += "🎁 <b>ДОСТУПНО!</b>"
    else: text += "🔒 <i>Не достигнут</i>"
    
    kb = []
    if is_reached and not is_claimed and rewards:
        kb.append([InlineKeyboardButton(text="🎁 ЗАБРАТЬ", callback_data=f"bp_claim_{bp_id}_{req_level}")])
        
    nav_row = []
    max_lvl = await fetch_one("SELECT MAX(level) as m FROM bp_levels WHERE bp_id = ?", (bp_id,))
    max_l = max_lvl['m'] if max_lvl and max_lvl['m'] else 1
    
    if req_level > 1: nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"bp_lvl_{bp_id}_{req_level-1}"))
    if req_level < max_l: nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"bp_lvl_{bp_id}_{req_level+1}"))
    if nav_row: kb.append(nav_row)
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"bp_view_{bp_id}")])
    
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
    
    bp = await fetch_one("SELECT is_football FROM battle_passes WHERE id = ?", (bp_id,))
    is_fb = bp['is_football']
    bal_col = 'football_balls' if is_fb else 'coins'
    
    db = await get_db_connection()
    try:
        await db.execute("BEGIN")
        for r in rewards:
            if r['reward_type'] == 'shekels':
                if is_fb:
                    await db.execute(f"UPDATE users SET {bal_col} = {bal_col} + ? WHERE id = ?", (r['amount'], user_id))
                else:
                    await db.execute(f"UPDATE users SET coins = coins + ?, total_coins = total_coins + ? WHERE id = ?", (r['amount'], r['amount'], user_id))
            elif r['reward_type'] == 'card':
                res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0 AND signed_by = 0 AND is_football = ?", (user_id, r['card_id'], r['mutation'], is_fb))
                inv_item = await res.fetchone()
                if inv_item:
                    await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                else:
                    await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by, is_football) VALUES (?, ?, 1, ?, 0, 0, ?)", (user_id, r['card_id'], r['mutation'], is_fb))
        
        await db.execute("INSERT INTO user_bp_claims (user_id, bp_id, level) VALUES (?, ?, ?)", (user_id, bp_id, req_level))
        await db.commit()
    finally:
        await db.close()
        
    await callback.answer("🎉 Reward claimed!", show_alert=True)
    await callback_bp_level(callback)

# ========================================================================
# БОЕВОЙ ДВИЖОК
# ========================================================================
async def get_team_data(user_id: int, is_football: int = 0):
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    team = []
    slots = ['fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4'] if is_football else ['equip1', 'equip2', 'equip3', 'equip4']
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
                card['trauma'] = 0
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
            if not filtered_pool: filtered_pool = all_cards # fail-safe
            
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
                c['dmg_buff'] += int(c['damage'] * d_mult) - c['damage']

async def process_burns(team, team_name, log1, log2):
    for c in team:
        if c['hp'] > 0 and c.get('burn', 0) > 0:
            c['hp'] -= c['burn']
            ru_str = f"🔥 {team_name}: <b>{html.escape(c['name'])}</b> получает {c['burn']} урона от горения!"
            if c['hp'] <= 0:
                c['hp'] = 0
                ru_str += " ☠️ <i>Сгорел дотла!</i>"
            add_dual_log(log1, log2, ru_str)
            c['burn'] = 0

async def execute_turn(atk_team, def_team, atk_name, def_name, log1, log2, force_attacker=None, force_target=None):
    await process_burns(atk_team, atk_name, log1, log2)
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
            target['hp'] -= dmg
            ru_str = f"🎯 {atk_name}: Одинокий Хилер <b>{html.escape(atk['name'])}</b> бьет <b>{html.escape(target['name'])}</b> на {dmg}!"
            if target['hp'] <= 0: target['hp'] = 0; ru_str += dead_ru
            add_dual_log(log1, log2, ru_str)
        
    elif c_type == "AOE":
        ru_str = f"🌪 {atk_name}: <b>{html.escape(atk['name'])}</b> бьет по всем на {base_dmg}!"
        for d in def_alive:
            d['hp'] -= base_dmg
            if d['hp'] <= 0:
                d['hp'] = 0
                ru_str += f" ☠️ <i>{html.escape(d['name'])} мертв!</i>"
        add_dual_log(log1, log2, ru_str)
        
    elif c_type == "Splash":
        if force_target and force_target['hp'] > 0 and force_target in def_alive: main_t = force_target
        else: main_t = random.choice(def_alive)
            
        splash_dmg = int(base_dmg * 0.5)
        ru_str = f"🌊 {atk_name}: <b>{html.escape(atk['name'])}</b> наносит {base_dmg} по <b>{html.escape(main_t['name'])}</b> и {splash_dmg} остальным!"
        for d in def_alive:
            dmg = base_dmg if d == main_t else splash_dmg
            d['hp'] -= dmg
            if d['hp'] <= 0:
                d['hp'] = 0
                ru_str += f" ☠️ <i>{html.escape(d['name'])} мертв!</i>"
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
    base = max(5, 18 - int((rank_idx / 25) * 12)) 
    won = random.randint(base, base+3)
    return int(won * diff_scale)

async def add_bp_xp(user_id: int, xp_to_add: int, is_football: int = 0) -> tuple:
    db = await get_db_connection()
    try:
        user_bp = await db.execute("""
            SELECT ubp.bp_id, ubp.level, ubp.xp 
            FROM user_bp ubp JOIN battle_passes bp ON ubp.bp_id = bp.id
            WHERE ubp.user_id = ? AND ubp.is_active = 1 AND bp.is_football = ?
        """, (user_id, is_football))
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
        msg = await bot.send_message(chat_id, "⏳ <b>Ваш ход!</b> Выберите карту для действия (12 сек):", reply_markup=kb)
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

# -----------------------------
# КНОПКА СДАТЬСЯ
@dp.callback_query(F.data.startswith("surrender_battle_"))
async def cb_surrender_battle_fixed(callback: types.CallbackQuery):
    battle_id = callback.data.split("_")[2]
    user_id = callback.from_user.id
    
    # Заносим строго кортеж (юзер, бой), чтобы не заблокировать следующие игры
    surrendered_players.add((user_id, battle_id))
    chat_id = callback.message.chat.id
    if chat_id in active_manual_battles and active_manual_battles[chat_id]['p1_id'] == user_id:
        active_manual_battles[chat_id]['event'].set()
    await callback.answer("🏳️ Вы сдались!", show_alert=True)

def get_battle_kb(battle_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏳️ Сдаться", callback_data=f"surrender_battle_{battle_id}")]
    ])

async def battle_delay(battle_id, p1_id, p2_id, delay=3.0):
    steps = int(delay * 10)
    for _ in range(steps):
        await asyncio.sleep(0.1)
        # Проверяем строго сдачу для текущей сессии
        if (p1_id, battle_id) in surrendered_players or (p2_id, battle_id) in surrendered_players:
            break

async def safe_edit_text(msg, text, reply_markup=None):
    try:
        await msg.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            pass 
        else:
            raise e

async def run_battle_loop(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_id: int, p2_name: str, t1: list, t2: list, diff_trophies_scale: float = 1.0, diff_bp_mult: float = 1.0, is_pvp: bool = False, pvp_no_rewards: bool = False, mods=None):
    battle_id = f"bt_{p1_id}_{int(time.time())}"
    # Принудительно очищаем флаг сдачи перед началом
    surrendered_players.discard((p1_id, battle_id))
    if p2_id:
        surrendered_players.discard((p2_id, battle_id))
        
    try:
        msg = await bot.send_message(chat_id, f"⚔️ Бой <b>{p1_name}</b> VS <b>{p2_name}</b> начнется через 3 сек!")
        await asyncio.sleep(1)
        await safe_edit_text(msg, "⚔️ Бой начнется через 2 сек!")
        await asyncio.sleep(1)
        await safe_edit_text(msg, "⚔️ Бой начнется через 1 сек!")
        
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
        p1_total_heals = 0
        p2_total_heals = 0
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
                
            if turn > 40:
                winner = "Ничья по раундам"
                break

            did_turn, heals = await do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, mods, is_pvp)
            p1_total_heals += heals
            if did_turn:
                if len(log) > 6: log = log[-6:]
                try: 
                    await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                except Exception as e:
                    if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                await battle_delay(battle_id, p1_id, p2_id)

            if mods and mods.get('mod_enemy_atk_all') and not is_pvp:
                t1_a = [c for c in t1 if c['hp']>0]
                t2_a = [c for c in t2 if c['hp']>0]
                if t1_a and t2_a:
                    did_turn_e, heals_e = await execute_turn(t2, t1, p2_name, p1_name, log, None)
                    p2_total_heals += heals_e
                    if did_turn_e:
                        if len(log) > 6: log = log[-6:]
                        try: 
                            await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                        except Exception as e:
                            if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                        await battle_delay(battle_id, p1_id, p2_id)

            t2_alive = [c for c in t2 if c['hp'] > 0]
            if t2_alive:
                if time.time() - battle_start_time > 180:
                    timeout_flag = True
                    break

                did_turn_e, heals_e = await execute_turn(t2, t1, p2_name, p1_name, log, None)
                p2_total_heals += heals_e
                if did_turn_e:
                    if len(log) > 6: log = log[-6:]
                    try: 
                        await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                    except Exception as e:
                        if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                    await battle_delay(battle_id, p1_id, p2_id)
                    
                if mods and mods.get('mod_player_atk_all') and not is_pvp:
                    t1_a = [c for c in t1 if c['hp']>0]
                    t2_a = [c for c in t2 if c['hp']>0]
                    if t1_a and t2_a:
                        did_turn, heals = await do_player_turn_wrapper(chat_id, p1_id, p1_name, p2_name, t1, t2, log, mods, is_pvp)
                        p1_total_heals += heals
                        if did_turn:
                            if len(log) > 6: log = log[-6:]
                            try: 
                                await safe_edit_text(msg, build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log), reply_markup=get_battle_kb(battle_id))
                            except Exception as e:
                                if "not found" in str(e).lower() or "deleted" in str(e).lower(): timeout_flag = True; break
                            await battle_delay(battle_id, p1_id, p2_id)
            turn += 1

        if timeout_flag:
            try: await msg.edit_text("⏳ <b>Бой автоматически прерван (ошибка или тайм-аут)!</b>")
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

            if winner_user_id is not None and "Ничья" not in winner:
                if random.random() <= 0.05: 
                    db = await get_db_connection()
                    try:
                        # Получаем не-футбольные коды для обычного мода
                        async with db.execute("SELECT code FROM reward_codes WHERE is_active = 1 AND owner_id = 0 AND is_football = 0 ORDER BY RANDOM() LIMIT 1") as cursor:
                            row = await cursor.fetchone()
                            if row:
                                code_val = row['code']
                                await db.execute("UPDATE reward_codes SET owner_id = ? WHERE code = ?", (winner_user_id, code_val))
                                await db.commit()
                                code_text = (
                                    f"🎁 <b>ВЫПАЛ УНИКАЛЬНЫЙ КОД-НАГРАДА! (Шанс 5%)</b>\nНажми, чтобы скопировать: <code>{code_val}</code>\nАктивируй через /codereward\n\n"
                                )
                    except: pass
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
                
                if winner == p1_name:
                    user_data = await fetch_one("SELECT trophies FROM users WHERE id = ?", (p1_id,))
                    user_trophies = user_data['trophies'] if user_data else 0
                    rank = await get_user_rank(user_trophies)
                    
                    coins_base = random.randint(25, 90) * rank['reward_mult'] * diff_trophies_scale * 0.85 * coin_mult
                    coins_won = int(coins_base * mod_reward_mult)
                    won_t_base = await get_dynamic_trophies(rank['name'], rank['rank_idx'], diff_trophies_scale)
                    won_t = int(won_t_base * mod_trophy_mult)
                    
                    await execute_db("UPDATE users SET coins = coins + ?, total_coins = total_coins + ?, trophies = trophies + ? WHERE id = ?", (coins_won, coins_won, won_t, p1_id))
                    
                    final_text += f"🎉 <b>Награды:</b>\n💰 {coins_won} Шекелей"
                    if coin_mult > 1.0: final_text += f" (Ивент x{coin_mult})"
                    if mod_reward_mult != 1.0: final_text += f" [Моды x{mod_reward_mult:.2f}]"
                    final_text += f"\n🏆 {won_t} Кубков\n"
                    
                    bp_xp = int((20 * diff_bp_mult * xp_mult_event) * mod_reward_mult)
                    lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp)
                    final_text += f"🎫 +{bp_xp} BP XP"
                    if lvl_up: bp_messages.append(f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> {new_lvl} уровень в сезоне «{bp_title}»!")
                    
                elif winner == p2_name:
                    await execute_db("UPDATE users SET trophies = MAX(0, trophies - 2) WHERE id = ?", (p1_id,))
                    final_text += f"💀 Вы проиграли и потеряли <b>2 🏆</b>.\n"
                    bp_xp = int((5 * diff_bp_mult * xp_mult_event) * mod_reward_mult)
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
            
    title_str = await get_user_titles_str(callback.from_user.id)
    p1_name = get_display_name(user) + title_str
    active_combats.add(callback.from_user.id)
    
    await log_user_action(callback.from_user.id, f"Начал PvE бой (сложность: {diff_type})")
    
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, callback.from_user.id, p1_name, 0, f"AI ({diff_name})", team1, team2, trophies_scale, bp_xp_mult, is_pvp=False, mods=mods))
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
        
        active_combats.add(u_id)
        active_combats.add(opp_id)
        
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
        [InlineKeyboardButton(text="⚔️ Принять", callback_data=f"pvp_accept_{user['id']}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pvp_decline_{user['id']}")]
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
    try: await bot.send_message(challenger_id, f"❌ Вызов отклонен.")
    except: pass
    try: await callback.message.edit_text("❌ Вы отклонили вызов.")
    except: pass
    await callback.answer()

async def run_pvp_dual_broadcast(p1_id: int, p2_id: int, p1_name: str, p2_name: str, t1: list, t2: list):
    battle_id = f"pvp_{p1_id}_{p2_id}_{int(time.time())}"
    surrendered_players.discard((p1_id, battle_id))
    surrendered_players.discard((p2_id, battle_id))
    
    try:
        msg1 = await bot.send_message(p1_id, f"⚔️ Дуэль против <b>{p2_name}</b> начнется через 3 сек!")
        msg2 = await bot.send_message(p2_id, f"⚔️ Дуэль против <b>{p1_name}</b> начнется через 3 сек!")
        await asyncio.sleep(1)
        await safe_edit_text(msg1, "2...")
        await safe_edit_text(msg2, "2...")
        await asyncio.sleep(1)
        await safe_edit_text(msg1, "1...")
        await safe_edit_text(msg2, "1...")
        await asyncio.sleep(1)
        
        battle_start_time = time.time()
        log1 = []
        log2 = []
        apply_boosters(t1, p1_name, log1, log2)
        apply_boosters(t2, p2_name, log1, log2)
        
        if log1:
            header1 = build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log1)
            header2 = build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log2)
            await safe_edit_text(msg1, header1, reply_markup=get_battle_kb(battle_id))
            await safe_edit_text(msg2, header2, reply_markup=get_battle_kb(battle_id))
            await battle_delay(battle_id, p1_id, p2_id)

        turn = 1
        winner = None
        p1_heals = p2_heals = 0
        timeout_flag = False
        
        while True:
            if time.time() - battle_start_time > 180:
                timeout_flag = True
                break
                
            if (p1_id, battle_id) in surrendered_players and (p2_id, battle_id) in surrendered_players:
                winner = "Ничья"
                surrendered_players.discard((p1_id, battle_id))
                surrendered_players.discard((p2_id, battle_id))
                break
            elif (p1_id, battle_id) in surrendered_players:
                winner = p2_name; surrendered_players.discard((p1_id, battle_id))
                log1.append(f"🏳️ <b>{p1_name} сдался!</b>")
                log2.append(f"🏳️ <b>{p1_name} сдался!</b>")
                break
            elif (p2_id, battle_id) in surrendered_players:
                winner = p1_name; surrendered_players.discard((p2_id, battle_id))
                log1.append(f"🏳️ <b>{p2_name} сдался!</b>")
                log2.append(f"🏳️ <b>{p2_name} сдался!</b>")
                break

            t1_a = [c for c in t1 if c['hp'] > 0]
            t2_a = [c for c in t2 if c['hp'] > 0]
            if not t1_a and not t2_a: winner = "Ничья"; break
            elif not t1_a: winner = p2_name; break
            elif not t2_a: winner = p1_name; break
            if turn > 40: winner = "Ничья по раундам"; break

            did_turn, h = await execute_turn(t1, t2, p1_name, p2_name, log1, log2)
            p1_heals += h
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
                if time.time() - battle_start_time > 180:
                    timeout_flag = True
                    break
                    
                did_turn, h = await execute_turn(t2, t1, p2_name, p1_name, log1, log2)
                p2_heals += h
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
            try: await msg1.edit_text(txt1)
            except: pass
            try: await msg2.edit_text(txt1)
            except: pass
            return

        try:
            await add_quest_progress(p1_id, 'q_pvp_played', 1)
            await add_quest_progress(p2_id, 'q_pvp_played', 1)
            if p1_heals > 0: await add_quest_progress(p1_id, 'q_heals_done', p1_heals)
            if p2_heals > 0: await add_quest_progress(p2_id, 'q_heals_done', p2_heals)

            code_text_1 = ""
            code_text_2 = ""
            winner_user_id = None
            
            if "Ничья" not in winner:
                if winner == p1_name: winner_user_id = p1_id
                elif winner == p2_name: winner_user_id = p2_id
                
            if winner_user_id is not None:
                if random.random() <= 0.05:
                    db = await get_db_connection()
                    try:
                        async with db.execute("SELECT code FROM reward_codes WHERE is_active = 1 AND owner_id = 0 AND is_football = 0 ORDER BY RANDOM() LIMIT 1") as cursor:
                            row = await cursor.fetchone()
                            if row:
                                code_val = row['code']
                                await db.execute("UPDATE reward_codes SET owner_id = ? WHERE code = ?", (winner_user_id, code_val))
                                await db.commit()
                                dropped_msg = f"🎁 <b>ВЫПАЛ УНИКАЛЬНЫЙ КОД-НАГРАДА! (5%)</b>\nНажми, чтобы скопировать: <code>{code_val}</code>\nАктивируй через /codereward\n\n"
                                if winner_user_id == p1_id: code_text_1 = dropped_msg
                                else: code_text_2 = dropped_msg
                    except Exception as e:
                        logging.error(f"Reward Code Drop PvP Error: {e}")
                    finally:
                        await db.close()

            final1 = code_text_1 + f"🏁 <b>ИТОГИ: {p1_name} VS {p2_name}</b>\nПобедитель: {winner}\nДружеская дуэль (без наград)."
            final2 = code_text_2 + f"🏁 <b>ИТОГИ: {p1_name} VS {p2_name}</b>\nПобедитель: {winner}\nДружеская дуэль (без наград)."
            
            try: await msg1.edit_text(final1, reply_markup=None)
            except: pass
            try: await msg2.edit_text(final2, reply_markup=None)
            except: pass
        except Exception as e:
            logging.error(f"PVP Reward error: {e}")
            try: await msg1.edit_text("Ошибка при выдаче наград.", reply_markup=None)
            except: pass
            try: await msg2.edit_text("Ошибка при выдаче наград.", reply_markup=None)
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
    if message.from_user.id in active_combats or message.from_user.id in user_trades: return await message.answer("Заняты!")
    parts = message.text.split()
    if len(parts) > 1:
        message.text = parts[1]
        await process_trade_target(message, state)
    else:
        await message.answer("🤝 <b>ОБМЕН</b>\nВведите @username или ID игрока:")
        await state.set_state(TradeState.waiting_target)
        asyncio.create_task(clear_fsm_timeout(state, message.chat.id, 60))

@dp.message(TradeState.waiting_target)
async def process_trade_target(message: types.Message, state: FSMContext):
    val = message.text.strip()
    user = await fetch_one("SELECT * FROM users WHERE id=?", (message.from_user.id,))
    target_user = None
    
    if val.isdigit(): target_user = await fetch_one("SELECT * FROM users WHERE id = ?", (int(val),))
    else: target_user = await fetch_one("SELECT * FROM users WHERE username = ?", (val.lstrip('@'),))
        
    if not target_user: return await message.answer("Игрок не найден.")
    if target_user['id'] == message.from_user.id: return await message.answer("Самому себе нельзя!")
    if target_user['id'] in active_combats or target_user['id'] in user_trades: return await message.answer("Игрок занят!")

    challenger_name = get_display_name(user) + await get_user_titles_str(message.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять", callback_data=f"tr_acc_{user['id']}"),
         InlineKeyboardButton(text="❌ Отклонить", callback_data=f"tr_dec_{user['id']}")]
    ])
    
    try:
        await bot.send_message(target_user['id'], f"🤝 <b>{challenger_name}</b> предлагает обмен!", reply_markup=kb)
        await message.answer("📨 Запрос отправлен.")
        await log_user_action(message.from_user.id, f"Отправил запрос на трейд игроку {target_user['id']}")
    except: await message.answer("Ошибка.")
    await state.clear()

@dp.callback_query(F.data.startswith("tr_acc_"))
async def callback_trade_accept(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[2])
    p2_id = callback.from_user.id
    if p1_id in user_trades or p2_id in user_trades or p1_id in active_combats or p2_id in active_combats: return await callback.answer("Заняты!", show_alert=True)
        
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
        'start_time': time.time(), 'status': 'ongoing'
    }
    
    active_trades[trade_id] = trade
    user_trades[p1_id] = trade_id
    user_trades[p2_id] = trade_id
    
    await log_user_action(p2_id, f"Принял запрос на трейд от {p1_id}")
    
    try:
        msg1 = await bot.send_message(p1_id, await render_trade_text(trade), reply_markup=get_trade_main_kb(trade, p1_id))
        trade['p1_msg'] = msg1.message_id
    except: pass
    try:
        msg2 = await bot.send_message(p2_id, await render_trade_text(trade), reply_markup=get_trade_main_kb(trade, p2_id))
        trade['p2_msg'] = msg2.message_id
    except: pass
    
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_dec_"))
async def callback_trade_decline(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[2])
    try: await bot.send_message(p1_id, "❌ Отклонено.")
    except: pass
    try: await callback.message.edit_text("❌ Отклонено.")
    except: pass
    await callback.answer()

async def render_trade_text(trade):
    text = "🤝 <b>ТОРГОВАЯ КОМНАТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    text += f"🔵 <b>Предлагает {trade['p1_name']}:</b>\n"
    if not trade['p1_offer']: text += "  └ <i>Ничего</i>\n"
    else:
        for inv_id, qty in trade['p1_offer'].items(): text += f"  └ {qty}x {trade['p1_strings'].get(inv_id, '?')}\n"
            
    text += f"\n🔴 <b>Предлагает {trade['p2_name']}:</b>\n"
    if not trade['p2_offer']: text += "  └ <i>Ничего</i>\n"
    else:
        for inv_id, qty in trade['p2_offer'].items(): text += f"  └ {qty}x {trade['p2_strings'].get(inv_id, '?')}\n"
            
    r_str = "✅ Готов"
    w_str = "⏳ Выбирает..."
    p1_st = r_str if trade['p1_ready'] else w_str
    p2_st = r_str if trade['p2_ready'] else w_str
    
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━\n📊 <b>Статус:</b>\n"
    text += f"{trade['p1_name']}: {p1_st}\n{trade['p2_name']}: {p2_st}\n"
    return text

def get_trade_main_kb(trade, user_id):
    if trade['status'] != 'ongoing': return None
    kb = []
    if trade['p1_ready'] and trade['p2_ready']:
        is_conf = trade['p1_confirmed'] if user_id == trade['p1'] else trade['p2_confirmed']
        if is_conf: kb.append([InlineKeyboardButton(text="⏳ Ожидание...", callback_data="ignore")])
        else: kb.append([InlineKeyboardButton(text="🔒 ПОДТВЕРДИТЬ", callback_data="tr_action_confirm")])
    else:
        kb.append([
            InlineKeyboardButton(text="➕ Добавить", callback_data="tr_menu_add"),
            InlineKeyboardButton(text="➖ Убрать", callback_data="tr_menu_rem")
        ])
        is_ready = trade['p1_ready'] if user_id == trade['p1'] else trade['p2_ready']
        if is_ready: kb.append([InlineKeyboardButton(text="⏳ Ждем партнера...", callback_data="ignore")])
        else: kb.append([InlineKeyboardButton(text="✅ ГОТОВ К ОБМЕНУ", callback_data="tr_action_ready")])
            
    kb.append([InlineKeyboardButton(text="❌ Отменить трейд", callback_data="tr_action_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

async def update_trade_uis(trade):
    try: await bot.edit_message_text(await render_trade_text(trade), chat_id=trade['p1'], message_id=trade['p1_msg'], reply_markup=get_trade_main_kb(trade, trade['p1']))
    except: pass
    try: await bot.edit_message_text(await render_trade_text(trade), chat_id=trade['p2'], message_id=trade['p2_msg'], reply_markup=get_trade_main_kb(trade, trade['p2']))
    except: pass

@dp.callback_query(F.data.startswith("tr_action_"))
async def cb_trade_actions_fixed(callback: types.CallbackQuery):
    action = callback.data.split("_")[2]
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer("Ошибка: Трейд не найден", show_alert=True)
    trade = active_trades[trade_id]
    
    if action == "cancel":
        trade['status'] = 'cancelled'
        try: await bot.edit_message_text("❌ Обмен отменен.", chat_id=trade['p1'], message_id=trade['p1_msg'])
        except: pass
        try: await bot.edit_message_text("❌ Обмен отменен.", chat_id=trade['p2'], message_id=trade['p2_msg'])
        except: pass
        user_trades.pop(trade['p1'], None)
        user_trades.pop(trade['p2'], None)
        active_trades.pop(trade_id, None)
        return await callback.answer("Вы отменили трейд.")
        
    if action == "ready":
        if user_id == trade['p1']: trade['p1_ready'] = True
        else: trade['p2_ready'] = True
        await update_trade_uis(trade)
        return await callback.answer("Вы готовы!")
        
    if action == "confirm":
        if user_id == trade['p1']: trade['p1_confirmed'] = True
        else: trade['p2_confirmed'] = True
        await update_trade_uis(trade)
        if trade['p1_confirmed'] and trade['p2_confirmed']: 
            await execute_trade_fixed(trade_id)
    await callback.answer()

async def execute_trade_fixed(trade_id):
    trade = active_trades.pop(trade_id, None)
    if not trade: return
    user_trades.pop(trade['p1'], None)
    user_trades.pop(trade['p2'], None)
    
    db = await get_db_connection()
    try:
        await db.execute("BEGIN")
        async def transfer_items(from_u, to_u, offer):
            for i_id, qty in offer.items():
                cur = await db.execute("SELECT card_id, mutation, serial_number, signed_by, count, is_football FROM inventory WHERE id = ?", (i_id,))
                row = await cur.fetchone()
                if not row or row['count'] < qty: raise Exception("Not enough")
                
                if row['count'] == qty:
                    await db.execute("DELETE FROM inventory WHERE id = ?", (i_id,))
                    await db.execute("UPDATE users SET equip1 = 0 WHERE equip1 = ?", (i_id,))
                    await db.execute("UPDATE users SET equip2 = 0 WHERE equip2 = ?", (i_id,))
                    await db.execute("UPDATE users SET equip3 = 0 WHERE equip3 = ?", (i_id,))
                    await db.execute("UPDATE users SET equip4 = 0 WHERE equip4 = ?", (i_id,))
                else:
                    await db.execute("UPDATE inventory SET count = count - ? WHERE id = ?", (qty, i_id))
                    
                cur2 = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = ? AND signed_by = ? AND is_football = ?", (to_u, row['card_id'], row['mutation'], row['serial_number'], row['signed_by'], row['is_football']))
                dest = await cur2.fetchone()
                
                if dest: await db.execute("UPDATE inventory SET count = count + ? WHERE id = ?", (qty, dest['id']))
                else: await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by, is_football) VALUES (?, ?, ?, ?, ?, ?, ?)", (to_u, row['card_id'], qty, row['mutation'], row['serial_number'], row['signed_by'], row['is_football']))

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
        await log_user_action(trade['p1'], f"Успешно завершил трейд с {trade['p2']}")
        await log_user_action(trade['p2'], f"Успешно завершил трейд с {trade['p1']}")
        try: await bot.edit_message_text("🎉 <b>ОБМЕН ЗАВЕРШЕН! Карты переведены.</b>", chat_id=trade['p1'], message_id=trade['p1_msg'])
        except: pass
        try: await bot.edit_message_text("🎉 <b>ОБМЕН ЗАВЕРШЕН! Карты переведены.</b>", chat_id=trade['p2'], message_id=trade['p2_msg'])
        except: pass
    else:
        try: await bot.edit_message_text("❌ ОШИБКА ОБМЕНА (предметы пропали или не найдены).", chat_id=trade['p1'], message_id=trade['p1_msg'])
        except: pass
        try: await bot.edit_message_text("❌ ОШИБКА ОБМЕНА (предметы пропали или не найдены).", chat_id=trade['p2'], message_id=trade['p2_msg'])
        except: pass

async def cancel_trade(trade_id, reason="Cancelled"):
    trade = active_trades.pop(trade_id, None)
    if not trade: return
    user_trades.pop(trade['p1'], None)
    user_trades.pop(trade['p2'], None)
    try: await bot.edit_message_text(f"❌ {reason}", chat_id=trade['p1'], message_id=trade['p1_msg'])
    except: pass
    try: await bot.edit_message_text(f"❌ {reason}", chat_id=trade['p2'], message_id=trade['p2_msg'])
    except: pass

async def get_inv_item_details(inv_id):
    row = await fetch_one("""
        SELECT c.id as card_id, c.name, c.rarity, c.class_type, i.count, i.mutation, i.serial_number, i.signed_by, u.username, u.first_name
        FROM inventory i JOIN cards c ON i.card_id = c.id LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.id = ?
    """, (inv_id,))
    if not row: return None
    if row['signed_by'] != 0: row['signer_name'] = get_display_name({'username': row['username'], 'first_name': row['first_name']})
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
        FROM inventory i JOIN cards c ON i.card_id = c.id LEFT JOIN users u ON i.signed_by = u.id
        WHERE i.user_id = ? AND i.count > 0 AND i.is_football = 0
    """, (user_id,))
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    
    items = []
    for c in inv:
        avail = c['count'] - offer_dict.get(c['inv_id'], 0)
        if avail > 0:
            if c['signed_by'] != 0: c['signer_name'] = get_display_name({'username': c['username'], 'first_name': c['first_name']})
            n = format_card_name_plain(c)
            mut = "⭐ " if c['mutation'] == 'Gold' else ("🌈 " if c['mutation'] == 'Rainbow' else "")
            items.append({"id": c['inv_id'], "btn_text": f"{mut}{n} ({avail})"})
            
    kb = get_pagination_keyboard(items, 0, "tr_add", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙", callback_data="tr_menu_main")])
    try: await callback.message.edit_text("👇", reply_markup=kb)
    except: pass
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
        WHERE i.user_id = ? AND i.count > 0 AND i.is_football = 0
    """, (user_id,))
    inv.sort(key=lambda x: RARITY_WEIGHT.get(x['rarity'], 0), reverse=True)
    items = []
    for c in inv:
        avail = c['count'] - offer_dict.get(c['inv_id'], 0)
        if avail > 0:
            if c['signed_by'] != 0: c['signer_name'] = get_display_name({'username': c['username'], 'first_name': c['first_name']})
            n = format_card_name_plain(c)
            mut = "⭐ " if c['mutation'] == 'Gold' else ("🌈 " if c['mutation'] == 'Rainbow' else "")
            items.append({"id": c['inv_id'], "btn_text": f"{mut}{n} ({avail})"})
            
    kb = get_pagination_keyboard(items, page, "tr_add", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙", callback_data="tr_menu_main")])
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
    if not row: return await callback.answer("Not found!", show_alert=True)
    
    avail = row['count'] - offer_dict.get(inv_id, 0)
    if avail <= 0: return await callback.answer("Limit!", show_alert=True)
    
    offer_dict[inv_id] = offer_dict.get(inv_id, 0) + 1
    mut = "⭐ " if row['mutation'] == 'Gold' else ("🌈 " if row['mutation'] == 'Rainbow' else "")
    string_dict[inv_id] = f"{mut}{format_card_name_plain(row)}"
    
    trade['p1_ready'] = False; trade['p2_ready'] = False
    trade['p1_confirmed'] = False; trade['p2_confirmed'] = False
    
    await callback.answer(f"Added!")
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
        if qty > 0: items.append({"id": i_id, "btn_text": f"❌ {string_dict[i_id]} (x{qty})"})
            
    kb = get_pagination_keyboard(items, 0, "tr_rem", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙", callback_data="tr_menu_main")])
    try: await callback.message.edit_text("👇", reply_markup=kb)
    except: pass
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
        if qty > 0: items.append({"id": i_id, "btn_text": f"❌ {string_dict[i_id]} (x{qty})"})
            
    kb = get_pagination_keyboard(items, page, "tr_rem", columns=1, items_per_page=6)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙", callback_data="tr_menu_main")])
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
        if offer_dict[inv_id] == 0: del offer_dict[inv_id]
            
    trade['p1_ready'] = False; trade['p2_ready'] = False
    trade['p1_confirmed'] = False; trade['p2_confirmed'] = False
    
    await callback.answer("-1")
    await update_trade_uis(trade)

@dp.callback_query(F.data == "tr_menu_main")
async def cb_trade_menu_main(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    trade_id = user_trades.get(user_id)
    if not trade_id or trade_id not in active_trades: return await callback.answer()
    await update_trade_uis(active_trades[trade_id])
    await callback.answer()

async def trade_timeout_task():
    while True:
        try:
            now = time.time()
            to_cancel = []
            for t_id, trade in active_trades.items():
                if now - trade['start_time'] > 600:
                    to_cancel.append(t_id)
            for t_id in to_cancel:
                await cancel_trade(t_id, reason="Тайм-аут / Timeout")
        except: pass
        await asyncio.sleep(60)

# ========================================================================
# СИД-ПАКИ
# ========================================================================
@dp.message(F.text.in_([BTN_SEED_PACKS, BTN_FB_PACKS]))
async def cmd_seed_packs_menu(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins, football_balls FROM users WHERE id = ?", (message.from_user.id,))
    is_fb = message.text == BTN_FB_PACKS
    packs = await fetch_all("SELECT * FROM seed_packs WHERE is_football = ?", (1 if is_fb else 0,))
    
    bal = user['football_balls'] if is_fb else user['coins']
    val_sym = "⚽" if is_fb else "💰"
    val_name = "Мячей" if is_fb else "Шекелей"
    
    text = (
        f"📦 <b>МАГАЗИН СИД-ПАКОВ {'(CARDBALL)' if is_fb else ''}</b>\n{val_sym} Твой баланс: <b>{bal} {val_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nСид-Пак — это особый набор карт с гарантированным набором юнитов и повышенным шансом мутаций (<b>12% на Золотую</b>, <b>2% на Радужную</b>)!\n\nДоступные паки:\n"
    )
    
    kb = []
    if not packs:
        text += "\n<i>Пусто. Ожидайте!</i>"
    else:
        for p in packs:
            desc_text = f" — {p['description']}" if p['description'] else ""
            price_val = p.get('price', 2000)
            text += f"🔹 <b>{p['title']}</b> (Цена: <b>{price_val} {val_sym}</b>){desc_text}\n"
            kb.append([InlineKeyboardButton(text=f"🔍 Смотреть: {p['title']}", callback_data=f"sp_view_{p['id']}_shop")])
            
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("sp_view_"))
async def cb_sp_view(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    pack_id = int(parts[2])
    mode = parts[3] 
    user_id = callback.from_user.id
    user = await fetch_one("SELECT coins, football_balls FROM users WHERE id=?", (user_id,))
    
    pack = await fetch_one("SELECT * FROM seed_packs WHERE id = ?", (pack_id,))
    if not pack: return await callback.answer("Error!", show_alert=True)
    is_fb = pack['is_football'] == 1
    
    pack_cards = await fetch_all("SELECT c.name, spc.drop_chance FROM seed_pack_cards spc JOIN cards c ON spc.card_id = c.id WHERE spc.pack_id = ?", (pack_id,))
    pack_price = pack.get('price', 2000)
    
    text = f"📦 <b>СИД-ПАК: {pack['title']}</b>\n💬 <i>{pack['description']}</i>\n━━━━━━━━━━━━━━━━━━━━━━━━\n📊 <b>Содержимое пака:</b>\n"
    if not pack_cards:
        text += "  └ <i>Пак пуст!</i>\n"
    else:
        luck_mult, _ = await get_active_events()
        total_w = sum(c['drop_chance'] * (luck_mult if c['drop_chance'] < 15.0 else 1.0) for c in pack_cards)
        for idx, c in enumerate(pack_cards, 1):
            w = c['drop_chance'] * (luck_mult if c['drop_chance'] < 15.0 else 1.0)
            chance_pct = (w / total_w) * 100 if total_w > 0 else 0
            text += f"  {idx}. {c['name']} (~{chance_pct:.2f}%)\n"
            
    kb = []
    if mode == "shop":
        bal = user['football_balls'] if is_fb else user['coins']
        val_sym = "⚽" if is_fb else "💰"
        val_name = "Мячей" if is_fb else "Шекелей"
        text += f"\n{val_sym} Ваш баланс: <b>{bal} {val_name}</b>\nЦена: <b>{pack_price} {val_sym}</b> за штуку."
        kb.append([InlineKeyboardButton(text=f"🛒 Купить x1", callback_data=f"sp_buy_{pack_id}_1")])
        kb.append([InlineKeyboardButton(text=f"x3 ({pack_price * 3} {val_sym})", callback_data=f"sp_buy_{pack_id}_3"), InlineKeyboardButton(text=f"x10 ({pack_price * 10} {val_sym})", callback_data=f"sp_buy_{pack_id}_10")])
        kb.append([InlineKeyboardButton(text="🔙 Назад в магазин", callback_data=f"sp_shop_back_{1 if is_fb else 0}")])
    elif mode == "inv":
        user_pack = await fetch_one("SELECT count FROM user_seed_packs WHERE user_id = ? AND pack_id = ?", (user_id, pack_id))
        amount = user_pack['count'] if user_pack else 0
        text += f"\nУ вас есть: <b>{amount} шт.</b>\n"
        if amount > 0:
            kb.append([InlineKeyboardButton(text="📦 Открыть x1", callback_data=f"sp_open_{pack_id}_1")])
            if amount >= 5:
                kb.append([InlineKeyboardButton(text="📦 Открыть x5", callback_data=f"sp_open_{pack_id}_5")])
            kb.append([InlineKeyboardButton(text="📦 Открыть ВСЕ", callback_data=f"sp_open_{pack_id}_all")])
        kb.append([InlineKeyboardButton(text="🔙 Назад в инвентарь", callback_data=f"sp_inv_back_{1 if is_fb else 0}")])

    try: await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    except:
        try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("sp_shop_back_"))
async def cb_sp_shop_back(callback: types.CallbackQuery):
    is_fb = int(callback.data.split("_")[3])
    fake_msg = callback.message
    fake_msg.text = BTN_FB_PACKS if is_fb else BTN_SEED_PACKS
    await cmd_seed_packs_menu(fake_msg)
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("sp_inv_back_"))
async def cb_sp_inv_back(callback: types.CallbackQuery):
    await cb_inv_packs_menu(callback)

@dp.callback_query(F.data.startswith("inv_packs_menu_"))
async def cb_inv_packs_menu(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    is_fb = int(callback.data.split("_")[3])
    
    user_packs = await fetch_all("""
        SELECT usp.count, sp.id as pack_id, sp.title
        FROM user_seed_packs usp JOIN seed_packs sp ON usp.pack_id = sp.id
        WHERE usp.user_id = ? AND usp.count > 0 AND sp.is_football = ?
    """, (user_id, is_fb))
    
    fb_str = " (CARDBALL)" if is_fb else ""
    text = f"🎒 <b>ИНВЕНТАРЬ СИД-ПАКОВ{fb_str}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите пак для распаковки:\n\n"
    
    kb = [[InlineKeyboardButton(text="🎒 Карты", callback_data=f"inv_cards_menu_{is_fb}"), InlineKeyboardButton(text="📦 Сид-Паки (Выбрано)", callback_data="ignore")]]
    
    if not user_packs: text += "<i>У вас нет Сид-Паков.</i>"
    else:
        for p in user_packs:
            text += f"📦 <b>{p['title']}</b> — <b>{p['count']} шт.</b>\n"
            kb.append([InlineKeyboardButton(text=f"🔍 Смотреть: {p['title']}", callback_data=f"sp_view_{p['pack_id']}_inv")])
            
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("inv_cards_menu_"))
async def cb_inv_cards_menu(callback: types.CallbackQuery):
    is_fb = int(callback.data.split("_")[3])
    text, kb = await get_inventory_text_and_kb(callback.from_user.id, 0, is_football=is_fb)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("sp_buy_"))
async def cb_sp_buy_fixed(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    pack_id = int(parts[2])
    amount = int(parts[3])
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT coins, football_balls FROM users WHERE id=?", (user_id,))
    pack = await fetch_one("SELECT title, price, is_football FROM seed_packs WHERE id = ?", (pack_id,))
    
    if not pack: return await callback.answer("Ошибка БД!", show_alert=True)
    
    is_fb = pack['is_football'] == 1
    pack_price = pack['price'] if pack.get('price') is not None else 2000
    total_cost = pack_price * amount
    bal_col = 'football_balls' if is_fb else 'coins'
    
    if user[bal_col] < total_cost:
        return await callback.answer("❌ Недостаточно средств!", show_alert=True)
        
    await execute_db(f"UPDATE users SET {bal_col} = {bal_col} - ? WHERE id = ?", (total_cost, user_id))
    await execute_db("""
        INSERT INTO user_seed_packs (user_id, pack_id, count)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + ?
    """, (user_id, pack_id, amount, amount))
    
    if not is_fb: await add_quest_progress(user_id, 'q_shop_buys', 1)
    await log_user_action(user_id, f"Купил Сид-Пак '{pack['title']}' x{amount}")
    
    await callback.answer(f"✅ Куплено {amount} шт. Сид-Паков «{pack['title']}»!", show_alert=True)
    
    new_callback = callback.model_copy(update={"data": f"sp_view_{pack_id}_shop"})
    await cb_sp_view(new_callback)

@dp.callback_query(F.data.startswith("sp_open_"))
async def cb_sp_open_fixed(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    pack_id = int(parts[2])
    amt_str = parts[3]
    user_id = callback.from_user.id
    
    user_pack = await fetch_one("SELECT count FROM user_seed_packs WHERE user_id = ? AND pack_id = ?", (user_id, pack_id))
    pack = await fetch_one("SELECT title, photo_id, is_football FROM seed_packs WHERE id = ?", (pack_id,))
    
    if not user_pack or user_pack['count'] <= 0: return await callback.answer("❌ У вас нет этого пака!", show_alert=True)
        
    amount = user_pack['count'] if amt_str == 'all' else int(amt_str)
    if amount > user_pack['count']: return await callback.answer("Ошибка количества", show_alert=True)
    
    is_fb = pack['is_football'] == 1
    await execute_db("UPDATE user_seed_packs SET count = count - ? WHERE user_id = ? AND pack_id = ?", (amount, user_id, pack_id))
    pack_cards = await fetch_all("SELECT card_id, drop_chance FROM seed_pack_cards WHERE pack_id = ?", (pack_id,))
    
    if not pack_cards:
        await execute_db("UPDATE user_seed_packs SET count = count + ? WHERE user_id = ? AND pack_id = ?", (amount, user_id, pack_id))
        return await callback.answer("Пак пуст в БД", show_alert=True)
        
    luck_mult, _ = await get_active_events()
    weights = []
    cards_list = []
    for pc in pack_cards:
        w = pc['drop_chance']
        if w < 15.0: w *= luck_mult
        weights.append(w)
        card_info = await fetch_one("SELECT * FROM cards WHERE id = ?", (pc['card_id'],))
        cards_list.append(card_info)
        
    won_cards = []
    for _ in range(amount):
        won_card = random.choices(cards_list, weights=weights, k=1)[0]
        mut = roll_seed_pack_mutation() 
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'], is_football=1 if is_fb else 0)
        
        c_copy = dict(won_card)
        c_copy['mutation'] = mut
        c_copy['serial_number'] = serial
        won_cards.append(c_copy)
        
    if not is_fb: await add_quest_progress(user_id, 'q_cards_opened', amount)
    await log_user_action(user_id, f"Открыл Сид-Пак '{pack['title']}' x{amount}")
    
    text_results = f"🎉 <b>РАСПАКОВКА {amount}x СИД-ПАКА «{pack['title']}» ЗАВЕРШЕНА!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    
    if amount == 1:
        single = won_cards[0]
        mut_str = "🌈 Радужная " if single['mutation'] == 'Rainbow' else ("⭐ Золотая " if single['mutation'] == 'Gold' else "")
        mult = get_mutation_multiplier(single['mutation'])
        
        caption_text = text_results + f"🃏 {mut_str}{format_card_name(single)}\n💎 {format_rarity_display(single['rarity'])}\n"
        if single['class_type'] == 'Booster': 
            caption_text += f"✨ <b>БУСТЕР</b>\n⚔️ DMG Mult: <b>x{round(single['booster_dmg_mult']*mult, 2)}</b> | ❤️ HP Mult: <b>x{round(single['booster_hp_mult']*mult, 2)}</b>\n"
        elif single['class_type'] == 'Healer':
            caption_text += f"💗 <b>Лечение:</b> {int(single['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(single['hp']*mult)}\n"
        else: 
            caption_text += f"⚔️ <b>Урон:</b> {int(single['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(single['hp']*mult)}\n"
            
        await callback.message.answer_photo(photo=single['photo_id'], caption=caption_text)
        try: await callback.message.delete()
        except: pass
    else:
        for idx, c in enumerate(won_cards, 1):
            mut_str = "🌈 " if c['mutation'] == 'Rainbow' else ("⭐ " if c['mutation'] == 'Gold' else "⚪ ")
            text_results += f"{idx}. {mut_str}{format_card_name(c)}\n"
        text_results += "\n<i>Все карты добавлены в 🎒 Инвентарь.</i>"
        await callback.message.answer(text_results)
        try: await callback.message.delete()
        except: pass
        
    new_callback = callback.model_copy(update={"data": f"sp_view_{pack_id}_inv"})
    await cb_sp_view(new_callback)

# ========================================================================
# ПАНЕЛЬ АДМИНИСТРАТОРА
# ========================================================================
def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Карты", callback_data="adm_cards"), InlineKeyboardButton(text="👤 Игроки", callback_data="adm_users")],
        [InlineKeyboardButton(text="🎉 Ивенты", callback_data="adm_events"), InlineKeyboardButton(text="👑 Админы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="🎟 Батл-пассы", callback_data="adm_bp_main"), InlineKeyboardButton(text="✍️ Сигнеры", callback_data="adm_signers")],
        [InlineKeyboardButton(text="🏆 Награды за Топ", callback_data="adm_lb_main"), InlineKeyboardButton(text="📦 Сид-Паки", callback_data="adm_sp_main")],
        [InlineKeyboardButton(text="🎁 Коды-Награды", callback_data="adm_codes_main"), InlineKeyboardButton(text="⚽ Лига Награды", callback_data="adm_league_rewards")],
        [InlineKeyboardButton(text="🔨 Настройка Крафтов", callback_data="adm_craft_main"), InlineKeyboardButton(text="📦 Бэкап БД", callback_data="adm_db")]
    ])

@dp.message(F.text == BTN_ADM)
@dp.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id): return
    await message.answer("⚙️ <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\nВыберите раздел для управления ботом:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_main")
async def cq_adm_main(callback: types.CallbackQuery):
    await callback.message.edit_text("⚙️ <b>ПАНЕЛЬ АДМИНИСТРАТОРА</b>\nВыберите раздел для управления ботом:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_league_rewards")
async def adm_league_rewards_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Четвертьфинал", callback_data="admlig_stage_1")],
        [InlineKeyboardButton(text="🟡 Полуфинал", callback_data="admlig_stage_2")],
        [InlineKeyboardButton(text="🔴 Финал", callback_data="admlig_stage_3")],
        [InlineKeyboardButton(text="🏆 Победитель Кубка", callback_data="admlig_stage_win")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("⚽ <b>Настройка Наград Лиги Cardball</b>\n\nВыбывшие команды получают награду той стадии, на которой вылетели. Победитель турнира получает награду за победу.\nВыберите стадию для настройки:", reply_markup=kb)

@dp.callback_query(F.data.startswith("admlig_stage_"))
async def adm_league_stage_edit(callback: types.CallbackQuery, state: FSMContext):
    stage = callback.data.split("_")[2]
    await state.update_data(league_stage=stage)
    
    rewards = await fetch_all("SELECT * FROM league_rewards_stages WHERE stage_name = ?", (stage,))
    
    s_names = {"1": "Четвертьфинал", "2": "Полуфинал", "3": "Финал", "win": "Победитель Кубка"}
    text = f"🏆 <b>Награды: {s_names[stage]}</b>\n\n"
    if not rewards:
        text += "<i>Пусто.</i>\n"
    else:
        for r in rewards:
            if r['reward_type'] == 'balls': text += f"⚽ {r['amount']} Мячей\n"
            elif r['reward_type'] == 'shekels': text += f"💰 {r['amount']} Шекелей\n"
            elif r['reward_type'] == 'card':
                c = await fetch_one("SELECT name FROM cards WHERE id = ?", (r['card_id'],))
                n = c['name'] if c else "Unknown"
                mut = "🌈" if r['mutation'] == 'Rainbow' else ("⭐" if r['mutation'] == 'Gold' else "")
                text += f"🃏 {mut} {n}\n"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Мячи", callback_data="admlig_add_balls"), InlineKeyboardButton(text="➕ Шекели", callback_data="admlig_add_shekels")],
        [InlineKeyboardButton(text="➕ Карта", callback_data="admlig_add_card"), InlineKeyboardButton(text="🗑 Очистить", callback_data="admlig_clear")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_league_rewards")]
    ])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data == "admlig_clear")
async def adm_league_clear(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    stage = data['league_stage']
    await execute_db("DELETE FROM league_rewards_stages WHERE stage_name = ?", (stage,))
    await callback.answer("✅ Награды очищены!", show_alert=True)
    fake_call = callback.model_copy(update={"data": f"admlig_stage_{stage}"})
    await adm_league_stage_edit(fake_call, state)

@dp.callback_query(F.data.in_(["admlig_add_balls", "admlig_add_shekels"]))
async def adm_league_add_curr(callback: types.CallbackQuery, state: FSMContext):
    r_type = "balls" if "balls" in callback.data else "shekels"
    await state.update_data(lig_reward_type=r_type)
    await callback.message.answer(f"Введите количество {'Мячей' if r_type=='balls' else 'Шекелей'} для награды:")
    await state.set_state(AdminLeagueRewards.amount)
    await callback.answer()

@dp.message(AdminLeagueRewards.amount)
async def adm_league_save_curr(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        data = await state.get_data()
        stage = data['league_stage']
        r_type = data['lig_reward_type']
        
        await execute_db("INSERT INTO league_rewards_stages (stage_name, reward_type, amount) VALUES (?, ?, ?)", (stage, r_type, amt))
        await message.answer("✅ Валюта добавлена в награды!")
        fake_call = FakeCall(message, f"admlig_stage_{stage}")
        await adm_league_stage_edit(fake_call, state)
    except ValueError:
        await message.answer("❌ Число!")

@dp.callback_query(F.data == "admlig_add_card")
async def adm_league_add_card(callback: types.CallbackQuery, state: FSMContext):
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']} (ID:{c['id']})"} for c in all_cards]
    await state.update_data(lig_items=items)
    kb = get_pagination_keyboard(items, 0, "ligc", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту для награды:", reply_markup=kb)
    await state.set_state(AdminLeagueRewards.card_id)

@dp.callback_query(AdminLeagueRewards.card_id, F.data.startswith("ligc_page_"))
async def adm_league_c_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('lig_items', []), page, "ligc", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(AdminLeagueRewards.card_id, F.data.startswith("ligc_"))
async def adm_league_c_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[1])
    await state.update_data(lig_card_id=card_id)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚪ Обычная", callback_data="ligmut_Normal")],
        [InlineKeyboardButton(text="⭐ Золотая", callback_data="ligmut_Gold")],
        [InlineKeyboardButton(text="🌈 Радужная", callback_data="ligmut_Rainbow")]
    ])
    await callback.message.edit_text("Выберите мутацию:", reply_markup=kb)
    await state.set_state(AdminLeagueRewards.mutation)
    await callback.answer()

@dp.callback_query(AdminLeagueRewards.mutation, F.data.startswith("ligmut_"))
async def adm_league_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[1]
    data = await state.get_data()
    stage = data['league_stage']
    card_id = data['lig_card_id']
    
    await execute_db("INSERT INTO league_rewards_stages (stage_name, reward_type, card_id, mutation) VALUES (?, 'card', ?, ?)", (stage, card_id, mutation))
    
    await callback.answer("✅ Карта добавлена в награды!", show_alert=True)
    fake_call = callback.model_copy(update={"data": f"admlig_stage_{stage}"})
    await adm_league_stage_edit(fake_call, state)

@dp.callback_query(F.data == "adm_sp_main")
async def adm_sp_main_menu(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать Сид-Пак (Обычный)", callback_data="adm_sp_cr_0")],
        [InlineKeyboardButton(text="⚽ Создать Сид-Пак (Футбол)", callback_data="adm_sp_cr_1")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="adm_sp_del_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("📦 <b>Управление Сид-Паками</b>\nЗдесь можно создавать паки карт с уникальными шансами.", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_sp_cr_"))
async def adm_sp_cr_start(callback: types.CallbackQuery, state: FSMContext):
    is_fb = int(callback.data.split("_")[3])
    await state.update_data(sp_is_fb=is_fb, sp_cards=[])
    await callback.message.answer(f"Создание {'ФУТБОЛЬНОГО' if is_fb else 'ОБЫЧНОГО'} Сид-Пака.\nВведите название (например: Новогодний Пак):")
    await state.set_state(CreateSeedPack.title)
    await callback.answer()

@dp.message(CreateSeedPack.title)
async def adm_sp_cr_title(message: types.Message, state: FSMContext):
    await state.update_data(sp_title=message.text)
    await message.answer("Отправьте фото для пака (или напишите 'Пропустить'):", reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Пропустить")]], resize_keyboard=True))
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
    await message.answer("Введите цену пака (в валюте режима):")
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
    text = f"📦 <b>Пак: {data['sp_title']}</b>\nЦена: {data['sp_price']}\nКарты в паке:\n"
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
    data = await state.get_data()
    is_fb = data.get('sp_is_fb', 0)
    query = "SELECT id, name, rarity FROM cards WHERE is_cardball_exclusive = ?"
    cards = await fetch_all(query, (is_fb,))
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'],'')} {c['name']}"} for c in cards]
    await state.update_data(sp_items=items)
    kb = get_pagination_keyboard(items, 0, "sp_cr_c", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту для добавления в пак:", reply_markup=kb)
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
    await callback.message.edit_text("Введите вес выпадения этой карты (например 1.0, 50, 0.1):")
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
        cur = await db.execute("INSERT INTO seed_packs (title, photo_id, description, price, is_football) VALUES (?, ?, ?, ?, ?)",
                               (data['sp_title'], data.get('sp_photo'), data['sp_desc'], data['sp_price'], data.get('sp_is_fb', 0)))
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
        [InlineKeyboardButton(text="➕ Сгенерировать коды (Обычные)", callback_data="adm_code_gen_0")],
        [InlineKeyboardButton(text="⚽ Сгенерировать коды (Футбол)", callback_data="adm_code_gen_1")],
        [InlineKeyboardButton(text="📜 Просмотр кодов", callback_data="adm_code_list_0")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🎁 <b>Управление Уникальными Кодами-наградами</b>\nКоды с шансом 5% могут выпадать победителям боёв.", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_code_gen_"))
async def adm_code_gen_start(callback: types.CallbackQuery, state: FSMContext):
    is_fb = int(callback.data.split("_")[3])
    await state.update_data(gen_code_fb=is_fb)
    await callback.message.answer("Сколько кодов вы хотите сгенерировать? (Введите число)")
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
        await message.answer("❌ Введите корректное положительное число.")

@dp.callback_query(AdminRewardCode.r_type, F.data.startswith("cg_type_"))
async def adm_code_gen_type(callback: types.CallbackQuery, state: FSMContext):
    r_type = callback.data.split("_")[2]
    await state.update_data(gen_code_type=r_type)
    
    if r_type == "shekels":
        await callback.message.edit_text("Введите количество шекелей, которое даст один код:")
        await state.set_state(AdminRewardCode.amount)
    elif r_type == "card":
        all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
        items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']} (ID:{c['id']})"} for c in all_cards]
        await state.update_data(gen_items=items)
        kb = get_pagination_keyboard(items, 0, "cgc", columns=1, items_per_page=8)
        await callback.message.edit_text("Выберите карту, которую даст код:", reply_markup=kb)
        await state.set_state(AdminRewardCode.card_id)
    elif r_type == "pack":
        packs = await fetch_all("SELECT id, title FROM seed_packs ORDER BY id DESC")
        if not packs: return await callback.answer("Сид-паков нет!", show_alert=True)
        items = [{"id": p['id'], "btn_text": f"📦 {p['title']}"} for p in packs]
        await state.update_data(gen_items=items)
        kb = get_pagination_keyboard(items, 0, "cgp", columns=1, items_per_page=8)
        await callback.message.edit_text("Выберите Сид-Пак для награды:", reply_markup=kb)
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
    await callback.answer()

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
    await callback.answer()

@dp.callback_query(AdminRewardCode.mutation, F.data.startswith("cgmut_"))
async def adm_code_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[1]
    data = await state.get_data()
    await generate_and_save_codes(callback.message, state, data['gen_code_count'], 'card', card_id=data['gen_card_id'], mutation=mutation)
    await callback.answer()

@dp.callback_query(AdminRewardCode.pack_id, F.data.startswith("cgp_page_"))
async def adm_code_pack_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('gen_items', []), page, "cgp", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(AdminRewardCode.pack_id, F.data.startswith("cgp_"))
async def adm_code_pack_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    pack_id = int(callback.data.split("_")[1])
    data = await state.get_data()
    await generate_and_save_codes(callback.message, state, data['gen_code_count'], 'pack', item_id=pack_id)
    await callback.answer()

async def generate_and_save_codes(message: types.Message, state: FSMContext, count: int, r_type: str, amount: int = 0, card_id: int = 0, mutation: str = 'Normal', item_id: int = 0):
    data = await state.get_data()
    is_fb = data.get('gen_code_fb', 0)
    db = await get_db_connection()
    codes = []
    try:
        await db.execute("BEGIN EXCLUSIVE")
        for _ in range(count):
            code = generate_reward_code()
            codes.append(code)
            await db.execute(
                "INSERT INTO reward_codes (code, reward_type, amount, item_id, mutation, owner_id, is_active, is_football) VALUES (?, ?, ?, ?, ?, 0, 1, ?)",
                (code, r_type, amount, card_id if r_type == 'card' else item_id, mutation, is_fb)
            )
        await db.commit()
        
        codes_str = "\n".join(codes)
        bio = io.BytesIO(codes_str.encode('utf-8'))
        bio.seek(0)
        file = types.BufferedInputFile(bio.read(), filename="reward_codes.txt")
        
        info = f"Сгенерировано {count} кодов.\nРежим: {'ФУТБОЛ' if is_fb else 'ОСНОВА'}\nТип: {r_type}\n"
        if r_type == 'shekels': info += f"Сумма: {amount}"
        elif r_type == 'card': info += f"Card ID: {card_id} | Mut: {mutation}"
        elif r_type == 'pack': info += f"Pack ID: {item_id}"
        
        await bot.send_document(message.chat.id, file, caption=f"✅ Готово!\n{info}")
    except Exception as e:
        await db.execute("ROLLBACK")
        logging.error(f"Gen code error: {e}")
    finally:
        await db.close()
    await state.clear()

@dp.callback_query(F.data.startswith("adm_code_list_"))
async def adm_code_list(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[3])
    codes = await fetch_all("SELECT * FROM reward_codes WHERE is_active = 1 ORDER BY code DESC")
    if not codes: return await callback.answer("Нет активных невыданных кодов.", show_alert=True)
    
    items = []
    for c in codes:
        own_status = f"Выбит ID:{c['owner_id']}" if c['owner_id'] != 0 else "Общий"
        mod_str = "⚽" if c.get('is_football', 0) == 1 else "🎒"
        items.append({"id": c['code'], "btn_text": f"🔑 {mod_str} {c['code'][:8]}... ({c['reward_type']} | {own_status})"})
        
    kb = get_pagination_keyboard(items, page, "admcode", columns=1, items_per_page=8)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_codes_main")])
    
    try: await callback.message.edit_text(f"📜 <b>Активные коды ({len(codes)} шт.)</b>\nНажмите для деактивации:", reply_markup=kb)
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

@dp.message(Command("codereward"))
async def cmd_codereward(message: types.Message, state: FSMContext):
    if await check_ban(message.from_user.id): return
    await message.answer("🎁 <b>АКТИВАЦИЯ КОДА</b>\nОтправьте ваш 28-значный код:")
    await state.set_state(UserUseCode.waiting_code)

@dp.message(UserUseCode.waiting_code)
async def process_code_reward(message: types.Message, state: FSMContext):
    code = message.text.strip()
    user_id = message.from_user.id
    
    db = await get_db_connection()
    try:
        await db.execute("BEGIN EXCLUSIVE")
        cursor = await db.execute("SELECT * FROM reward_codes WHERE code = ? AND is_active = 1", (code,))
        code_data = await cursor.fetchone()
        
        if not code_data:
            await db.execute("ROLLBACK")
            await message.answer("❌ Код недействителен или уже использован.")
            return await state.clear()
            
        if code_data['owner_id'] != 0 and code_data['owner_id'] != user_id:
            await db.execute("ROLLBACK")
            await message.answer("❌ Этот код предназначен не для вас!")
            return await state.clear()
            
        await db.execute("UPDATE reward_codes SET is_active = 0 WHERE code = ?", (code,))
        
        r_type = code_data['reward_type']
        is_fb = code_data.get('is_football', 0)
        
        if r_type == 'shekels':
            if is_fb:
                await db.execute("UPDATE users SET football_balls = football_balls + ? WHERE id = ?", (code_data['amount'], user_id))
                await message.answer(f"✅ Вы успешно активировали код!\nНаграда: <b>{code_data['amount']} ⚽ Мячей</b>!")
            else:
                await db.execute("UPDATE users SET coins = coins + ?, total_coins = total_coins + ? WHERE id = ?", (code_data['amount'], code_data['amount'], user_id))
                await message.answer(f"✅ Вы успешно активировали код!\nНаграда: <b>{code_data['amount']} 💰 Шекелей</b>!")
        elif r_type == 'card':
            _, serial, _ = await give_card_to_user(user_id, code_data['item_id'], code_data['mutation'], is_football=is_fb)
            c_info = await fetch_one("SELECT name FROM cards WHERE id = ?", (code_data['item_id'],))
            mut_str = "🌈 " if code_data['mutation'] == 'Rainbow' else ("⭐ " if code_data['mutation'] == 'Gold' else "")
            s_str = f" [#{serial:04d}]" if serial > 0 else ""
            fb_str = " (Футбол)" if is_fb else ""
            await message.answer(f"✅ Вы успешно активировали код!\nНаграда: 🃏 <b>{mut_str}{c_info['name']}{s_str}</b>{fb_str}!")
        elif r_type == 'pack':
            await db.execute("INSERT INTO user_seed_packs (user_id, pack_id, count) VALUES (?, ?, 1) ON CONFLICT(user_id, pack_id) DO UPDATE SET count = count + 1", (user_id, code_data['item_id']))
            p_info = await fetch_one("SELECT title FROM seed_packs WHERE id = ?", (code_data['item_id'],))
            await message.answer(f"✅ Вы успешно активировали код!\nНаграда: 📦 <b>Сид-Пак «{p_info['title']}»</b> (1 шт.)!")
        
        await db.commit()
    except Exception as e:
        await db.execute("ROLLBACK")
        logging.error(f"Code redeem error: {e}")
        await message.answer("❌ Произошла ошибка при получении награды. Обратитесь к админу.")
    finally:
        await db.close()
    await state.clear()

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
    if val.isdigit(): target_user = await fetch_one("SELECT id FROM users WHERE id = ?", (int(val),))
    else: target_user = await fetch_one("SELECT id FROM users WHERE username = ?", (val.lstrip('@'),))
        
    if not target_user: await message.answer("❌ Пользователь не найден в базе данных бота.")
    else:
        uid = target_user['id']
        await execute_db("INSERT OR IGNORE INTO authorized_signers (user_id) VALUES (?)", (uid,))
        await message.answer(f"✅ Пользователь {uid} назначен Сигнером!\n\n<i>Чтобы у него появилась кнопка в меню, ему нужно отправить любое сообщение боту или нажать /start.</i>")
    await state.clear()

@dp.callback_query(F.data == "adm_sgn_del")
async def cq_adm_sgn_del(callback: types.CallbackQuery):
    signers = await fetch_all("""
        SELECT a.user_id, u.username, u.first_name 
        FROM authorized_signers a LEFT JOIN users u ON a.user_id = u.id
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
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Да")], [KeyboardButton(text="Нет")]], resize_keyboard=True)
        await message.answer("Сделать эту карту ЭКСКЛЮЗИВНОЙ ДЛЯ CARDBALL? (Она не будет падать в обычной Гаче, только в Cardball паках и турнирах):", reply_markup=kb)
        await state.set_state(AddCard.is_cardball_exclusive)
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
        hp = int(message.text)
        await state.update_data(hp=hp, booster_hp_mult=1.0)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Да")], [KeyboardButton(text="Нет")]], resize_keyboard=True)
        await message.answer("Сделать эту карту ЭКСКЛЮЗИВНОЙ ДЛЯ CARDBALL? (Она не будет падать в обычной Гаче, только в Cardball паках):", reply_markup=kb)
        await state.set_state(AddCard.is_cardball_exclusive)
    except: await message.answer("❌ Число!")

@dp.message(AddCard.is_cardball_exclusive)
async def add_card_exclusive(message: types.Message, state: FSMContext):
    is_fb_ex = 1 if message.text.lower() == "да" else 0
    data = await state.get_data()
    
    try:
        await message.answer("⏳ Генерирую рамку редкости для карты...", reply_markup=ReplyKeyboardRemove())
        
        new_photo_id = await create_bordered_image(bot, data['photo'], data['rarity'])
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id, booster_dmg_mult, booster_hp_mult, is_cardball_exclusive) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data['name'], data['rarity'], data['class_type'], data.get('damage', 0), data.get('hp', 0), data['drop_chance'], new_photo_id, data.get('booster_dmg_mult', 1.0), data.get('booster_hp_mult', 1.0), is_fb_ex)
        )
        
        ex_str = " (Эксклюзив Cardball)" if is_fb_ex else ""
        await log_admin(message.from_user.id, f"Создана карта{ex_str}: {data['name']}")
        await message.answer_photo(new_photo_id, caption=f"✅ <b>Карта {data['name']} создана!{ex_str}</b>", reply_markup=get_main_keyboard(await is_admin(message.from_user.id), await is_signer(message.from_user.id)))
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
    
    label_dmg = "Лечение" if card['class_type'] == "Healer" else "Урон"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data="edit_val_name"), InlineKeyboardButton(text="✏️ Шанс (Вес)", callback_data="edit_val_chance")],
        [InlineKeyboardButton(text=f"✏️ {label_dmg}", callback_data="edit_val_dmg"), InlineKeyboardButton(text="✏️ ХП", callback_data="edit_val_hp")],
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
        label = "значение силы исцеления" if field == "dmg" else f"новое значение для параметра {field}"
        await callback.message.answer(f"Отправь {label}:")
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
        if field == "class" and val not in CLASSES: return await message.answer("Неверный класс.")
        val = cast_fn(val.replace(',', '.')) if cast_fn == float else cast_fn(val)
        await execute_db(f"UPDATE cards SET {col} = ? WHERE id = ?", (val, c_id))
        await log_admin(message.from_user.id, f"Edited card ID {c_id}, {col} = {val}")
        
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
            for slot in ['equip1', 'equip2', 'equip3', 'equip4', 'fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4']:
                await execute_db(f"UPDATE users SET {slot} = 0 WHERE {slot} = ?", (i_id,))
                
        await log_admin(message.from_user.id, f"DELETED card ID {c_id}")
        await message.answer(f"✅ Карта {c_id} полностью удалена.")
    except: await message.answer("❌ Число.")
    await state.clear()

@dp.callback_query(F.data == "adm_users")
async def cq_adm_users(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Выдать карту", callback_data="adm_usr_givecard"),
         InlineKeyboardButton(text="➖ Забрать карту", callback_data="adm_usr_takecard")],
        [InlineKeyboardButton(text="💰 Выдать шекели/мячи", callback_data="adm_usr_give_coins"),
         InlineKeyboardButton(text="🏆 Выдать кубки", callback_data="adm_usr_give_trophies")],
        [InlineKeyboardButton(text="🔄 Сбросить состояние", callback_data="adm_usr_reset_battle")],
        [InlineKeyboardButton(text="🔨 Бан / Разбан", callback_data="adm_usr_ban")],
        [InlineKeyboardButton(text="📜 Логи игроков", callback_data="adm_usr_logs_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("👤 <b>Управление Игроками</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_usr_logs_menu")
async def adm_usr_logs_menu_start(callback: types.CallbackQuery, state: FSMContext):
    recent_users = await fetch_all("""
        SELECT DISTINCT u.id, u.username, u.first_name 
        FROM user_action_logs l 
        JOIN users u ON l.user_id = u.id 
        ORDER BY l.timestamp DESC LIMIT 30
    """)
    
    items = []
    for u in recent_users:
        name = get_display_name(u)
        items.append({"id": u['id'], "btn_text": f"👤 {name} (ID:{u['id']})"})
        
    kb = get_pagination_keyboard(items, 0, "admlog_u", columns=1, items_per_page=10)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admlog_search_id")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_users")])
    
    await state.update_data(admlog_users=items)
    await callback.message.edit_text("📜 <b>Глобальные логи игроков</b>\nВыберите игрока из недавних активных или найдите по ID:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("admlog_u_page_"))
async def admlog_u_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('admlog_users', []), page, "admlog_u", columns=1, items_per_page=10)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔍 Поиск по ID", callback_data="admlog_search_id")])
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_users")])
    try: await callback.message.edit_reply_markup(reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("admlog_u_"))
async def admlog_u_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    uid = int(callback.data.split("_")[2])
    await show_user_logs(callback, uid)

@dp.callback_query(F.data == "admlog_search_id")
async def admlog_search_id(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока для просмотра его логов:")
    await state.set_state(AdminManage.view_logs_id)
    await callback.answer()

@dp.message(AdminManage.view_logs_id)
async def admlog_search_id_msg(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text.strip())
        await show_user_logs_msg(message, uid)
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
    await state.clear()

async def show_user_logs(callback: types.CallbackQuery, uid: int):
    logs = await fetch_all("SELECT action, timestamp FROM user_action_logs WHERE user_id = ? ORDER BY id DESC LIMIT 50", (uid,))
    if not logs:
        return await callback.answer("У этого игрока нет логов.", show_alert=True)
        
    text = f"📜 <b>Последние 50 действий (ID: {uid}):</b>\n\n"
    for l in logs:
        text += f"🕒 {l['timestamp']}\n📝 {l['action']}\n\n"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_usr_logs_menu")]])
    try: await callback.message.edit_text(text[:4000], reply_markup=kb)
    except: pass
    await callback.answer()
    
async def show_user_logs_msg(message: types.Message, uid: int):
    logs = await fetch_all("SELECT action, timestamp FROM user_action_logs WHERE user_id = ? ORDER BY id DESC LIMIT 50", (uid,))
    if not logs:
        return await message.answer("У этого игрока нет логов.")
        
    text = f"📜 <b>Последние 50 действий (ID: {uid}):</b>\n\n"
    for l in logs:
        text += f"🕒 {l['timestamp']}\n📝 {l['action']}\n\n"
        
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_usr_logs_menu")]])
    await message.answer(text[:4000], reply_markup=kb)

@dp.callback_query(F.data == "adm_usr_give_coins")
async def adm_usr_give_coins_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока для выдачи:")
    await state.set_state(AdminManage.give_coins_id)
    await callback.answer()

@dp.message(AdminManage.give_coins_id)
async def adm_usr_give_coins_id(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(target_id=uid)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Шекели", callback_data="givecurr_coins"), InlineKeyboardButton(text="⚽ Мячи (Футбол)", callback_data="givecurr_balls")]
        ])
        await message.answer("Что именно выдать?", reply_markup=kb)
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

@dp.callback_query(F.data.startswith("givecurr_"))
async def adm_usr_give_curr_type(callback: types.CallbackQuery, state: FSMContext):
    c_type = callback.data.split("_")[1]
    await state.update_data(give_curr_type=c_type)
    await callback.message.answer("Сколько выдать?")
    await state.set_state(AdminManage.give_coins_amount)
    await callback.answer()

@dp.message(AdminManage.give_coins_amount)
async def adm_usr_give_coins_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data['target_id']
        c_type = data['give_curr_type']
        
        if c_type == 'coins':
            await execute_db("UPDATE users SET coins = coins + ?, total_coins = total_coins + ? WHERE id = ?", (amount, amount, uid))
            msg_alert = f"🎁 Администратор выдал вам <b>{amount} 💰 Шекелей</b>!"
        else:
            await execute_db("UPDATE users SET football_balls = football_balls + ? WHERE id = ?", (amount, uid))
            msg_alert = f"⚽ Администратор выдал вам <b>{amount} ⚽ Мячей</b>!"
            
        await log_admin(message.from_user.id, f"Выдал {amount} {c_type} игроку {uid}")
        await message.answer(f"✅ Успешно выдано {amount} единиц валюты игроку {uid}.")
        try: await bot.send_message(uid, msg_alert)
        except: pass
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
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏆 Кубки (Обычные)", callback_data="givetroph_main"), InlineKeyboardButton(text="⚽ Кубки (Футбол)", callback_data="givetroph_fb")]
        ])
        await message.answer("Какие кубки выдать?", reply_markup=kb)
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

@dp.callback_query(F.data.startswith("givetroph_"))
async def adm_usr_give_trophies_type(callback: types.CallbackQuery, state: FSMContext):
    t_type = callback.data.split("_")[1]
    await state.update_data(give_trophies_type=t_type)
    await callback.message.answer("Сколько кубков выдать?")
    await state.set_state(AdminManage.give_trophies_amount)
    await callback.answer()

@dp.message(AdminManage.give_trophies_amount)
async def adm_usr_give_trophies_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data['target_id']
        t_type = data['give_trophies_type']
        
        col = 'trophies' if t_type == 'main' else 'football_trophies'
        await execute_db(f"UPDATE users SET {col} = {col} + ? WHERE id = ?", (amount, uid))
        await log_admin(message.from_user.id, f"Выдал {amount} {col} игроку {uid}")
        await message.answer(f"✅ Успешно выдано {amount} кубков игроку {uid}.")
        try:
            icon = "🏆" if t_type == 'main' else "⚽"
            msg_alert = f"{icon} Администратор выдал вам <b>{amount} {icon}</b>!"
            await bot.send_message(uid, msg_alert)
        except: pass
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
        if uid in pvp_queue:
            pvp_queue.discard(uid)
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
    except:
        await message.answer("❌ ID должен быть числом.")

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
    await state.update_data(give_mutation=mutation)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="В обычный инвентарь", callback_data="givemode_0")],
        [InlineKeyboardButton(text="⚽ В ФУТБОЛЬНЫЙ инвентарь", callback_data="givemode_1")]
    ])
    await callback.message.edit_text("В какой инвентарь выдать карту?", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("givemode_"))
async def adm_give_mode(callback: types.CallbackQuery, state: FSMContext):
    is_fb = int(callback.data.split("_")[1])
    await state.update_data(give_is_fb=is_fb)
    await callback.message.edit_text("Введите СЕРИЙНЫЙ НОМЕР для карты (от 1 до 9999) или введите 0, чтобы выдать строго БЕЗ номера:")
    await state.set_state(GiveCard.custom_serial)
    await callback.answer()

@dp.message(GiveCard.custom_serial)
async def adm_give_serial_save(message: types.Message, state: FSMContext):
    try:
        serial = int(message.text)
        if serial < 0 or serial > 9999: raise ValueError
        
        data = await state.get_data()
        user_id = data.get('give_user_id')
        card_id = data.get('give_card_id')
        mutation = data.get('give_mutation')
        is_fb = data.get('give_is_fb', 0)
        
        if serial == 0:
            db = await get_db_connection()
            try:
                res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0 AND signed_by = 0 AND is_football = ?", (user_id, card_id, mutation, is_fb))
                inv_item = await res.fetchone()
                if inv_item:
                    await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                else:
                    await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by, is_football) VALUES (?, ?, 1, ?, 0, 0, ?)", (user_id, card_id, mutation, is_fb))
                await db.commit()
            finally:
                await db.close()
            assigned_serial = 0
        else:
            _, assigned_serial, _ = await give_card_to_user(user_id, card_id, mutation, custom_serial=serial, is_football=is_fb)
            
        s_str = f" [#{assigned_serial:04d}]" if assigned_serial > 0 else ""
        fb_str = " (ФУТБОЛ)" if is_fb else ""
        await log_admin(message.from_user.id, f"GAVE card ID {card_id} (Mut:{mutation}, Serial:{assigned_serial}) to User {user_id} {fb_str}")
        await message.answer(f"✅ Карта (ID {card_id}) успешно выдана игроку {user_id}!{fb_str}\nМутация: {mutation}{s_str}")
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число от 0 до 9999.")

@dp.callback_query(F.data == "adm_usr_takecard")
async def adm_usr_take_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока, у которого хотим забрать карту (удалить):")
    await state.set_state(TakeCard.user_id)
    await callback.answer()

@dp.message(TakeCard.user_id)
async def adm_usr_take_user(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(take_user_id=uid)
        
        inv = await fetch_all("""
            SELECT i.id as inv_id, c.name, c.rarity, i.count, i.mutation, i.serial_number, i.is_football 
            FROM inventory i JOIN cards c ON i.card_id = c.id 
            WHERE i.user_id = ? AND i.count > 0
        """, (uid,))
        
        if not inv:
            return await message.answer("У этого пользователя пустой инвентарь или нет карт.")
            
        items = []
        for c in inv:
            mut_str = "⭐" if c['mutation'] == 'Gold' else "🌈" if c['mutation'] == 'Rainbow' else "⚪"
            ser_str = f" [#{c['serial_number']:04d}]" if c['serial_number'] > 0 else ""
            fb_str = "⚽ " if c['is_football'] else ""
            items.append({"id": c['inv_id'], "btn_text": f"{fb_str}{mut_str} {c['name']}{ser_str} (x{c['count']})"})
            
        await state.update_data(take_items=items)
        kb = get_pagination_keyboard(items, 0, "take_c", columns=1, items_per_page=8)
        await message.answer("Выберите карту для изъятия:", reply_markup=kb)
        await state.set_state(TakeCard.inv_id)
    except:
        await message.answer("❌ ID должен быть числом.")

@dp.callback_query(F.data.startswith("take_c_page_"), TakeCard.inv_id)
async def adm_take_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('take_items', []), page, "take_c", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("take_c_"), TakeCard.inv_id)
async def adm_take_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[2])
    await state.update_data(take_inv_id=inv_id)
    
    await callback.message.edit_text("Сколько штук удалить? (Введите число или 'all' для удаления всех копий):")
    await state.set_state(TakeCard.amount)
    await callback.answer()

@dp.message(TakeCard.amount)
async def adm_take_amount(message: types.Message, state: FSMContext):
    amt_str = message.text.lower()
    data = await state.get_data()
    uid = data['take_user_id']
    inv_id = data['take_inv_id']
    
    inv_item = await fetch_one("SELECT count FROM inventory WHERE id = ? AND user_id = ?", (inv_id, uid))
    if not inv_item:
        await message.answer("Ошибка: карта не найдена в инвентаре.")
        return await state.clear()
        
    count_have = inv_item['count']
    if amt_str == 'all':
        amt = count_have
    else:
        try:
            amt = int(amt_str)
            if amt <= 0: raise ValueError
        except:
            return await message.answer("Введите корректное число больше 0 или 'all'.")
            
    if amt > count_have:
        amt = count_have
        
    if amt == count_have:
        await execute_db("DELETE FROM inventory WHERE id = ?", (inv_id,))
        for slot in ['equip1', 'equip2', 'equip3', 'equip4', 'fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4']:
            await execute_db(f"UPDATE users SET {slot} = 0 WHERE id = ? AND {slot} = ?", (uid, inv_id))
    else:
        await execute_db("UPDATE inventory SET count = count - ? WHERE id = ?", (amt, inv_id))
        
    await log_admin(message.from_user.id, f"Изъял карту inv_id {inv_id} в кол-ве {amt} у {uid}")
    await message.answer(f"✅ Успешно удалено {amt} шт. карты из инвентаря пользователя {uid}. Счётчик Exists автоматически обновлен.")
    await state.clear()

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
    except:
        pass
    await state.clear()

@dp.callback_query(F.data == "adm_bp_main")
async def adm_bp_main(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать ОБЫЧНЫЙ Батл-пасс", callback_data="adm_bp_create_0")],
        [InlineKeyboardButton(text="⚽ Создать ФУТБОЛЬНЫЙ Батл-пасс", callback_data="adm_bp_create_1")],
        [InlineKeyboardButton(text="✏️ Редактировать Батл-пасс", callback_data="adm_bp_edit_list")],
        [InlineKeyboardButton(text="🗑 Удалить Батл-пасс", callback_data="adm_bp_delete")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🎟 <b>Управление Батл-пассами</b>\nСоздавайте новые сезоны и настраивайте награды.", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "adm_bp_edit_list")
async def adm_bp_edit_list(callback: types.CallbackQuery):
    bps = await fetch_all("SELECT id, title FROM battle_passes")
    if not bps: return await callback.answer("Нет БП.", show_alert=True)
    kb = []
    for b in bps: kb.append([InlineKeyboardButton(text=f"✏️ {b['title']}", callback_data=f"abp_ed_{b['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="adm_bp_main")])
    await callback.message.edit_text("Выберите БП для редактирования:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("abp_ed_"))
async def abp_ed_menu(callback: types.CallbackQuery, state: FSMContext):
    bpid = int(callback.data.split("_")[2])
    await state.update_data(ed_bp_id=bpid)
    bp = await fetch_one("SELECT * FROM battle_passes WHERE id = ?", (bpid,))
    text = f"✏️ Редактирование БП: <b>{bp['title']}</b>\nЧто меняем?"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить название", callback_data="abp_ed_title")],
        [InlineKeyboardButton(text="Изменить фото", callback_data="abp_ed_photo")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_bp_edit_list")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(AdminBPEdit.edit_menu)
    await callback.answer()
    
@dp.callback_query(AdminBPEdit.edit_menu, F.data == "abp_ed_title")
async def abp_ed_title(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новое название для Батл-Пасса:")
    await state.set_state(AdminBPEdit.edit_title)
    await callback.answer()

@dp.message(AdminBPEdit.edit_title)
async def abp_ed_title_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await execute_db("UPDATE battle_passes SET title = ? WHERE id = ?", (message.text, data['ed_bp_id']))
    await message.answer("✅ Название обновлено!")
    await state.clear()

@dp.callback_query(AdminBPEdit.edit_menu, F.data == "abp_ed_photo")
async def abp_ed_photo(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправьте новое фото для Батл-Пасса:")
    await state.set_state(AdminBPEdit.edit_photo)
    await callback.answer()

@dp.message(AdminBPEdit.edit_photo, F.photo)
async def abp_ed_photo_save(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await execute_db("UPDATE battle_passes SET photo_id = ? WHERE id = ?", (message.photo[-1].file_id, data['ed_bp_id']))
    await message.answer("✅ Фото обновлено!")
    await state.clear()

@dp.callback_query(F.data == "adm_bp_delete")
async def adm_bp_del_list(callback: types.CallbackQuery):
    passes = await fetch_all("SELECT * FROM battle_passes ORDER BY id DESC")
    if not passes:
        return await callback.answer("Батл-пассов пока нет.", show_alert=True)
        
    kb = []
    for bp in passes:
        fb_str = "⚽ " if bp['is_football'] else ""
        kb.append([InlineKeyboardButton(text=f"🗑 Удалить: {fb_str}{bp['title']}", callback_data=f"adm_bp_del_id_{bp['id']}")])
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

@dp.callback_query(F.data.startswith("adm_bp_create_"))
async def adm_bp_create_start(callback: types.CallbackQuery, state: FSMContext):
    is_fb = int(callback.data.split("_")[3])
    await state.update_data(bp_is_football=is_fb)
    mode_str = "ФУТБОЛЬНОГО" if is_fb else "ОБЫЧНОГО"
    await callback.message.answer(f"🎟 <b>Создание {mode_str} Батл-пасса</b>\nШаг 1: Введите красивое НАЗВАНИЕ сезона (например: <i>Сезон 1: Зимняя Сказка</i>):")
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
    is_fb = data.get('bp_is_football', 0)
    
    val_name = "Мячей" if is_fb else "Шекелей"
    val_sym = "⚽" if is_fb else "💰"
    
    text = f"⚙️ <b>Настройка Уровня {lvl}</b>\nНаграды на этом уровне:\n"
    if not rewards: text += "<i>Пока пусто</i>\n"
    else:
        for r in rewards:
            if r['type'] == 'shekels': text += f"{val_sym} {r['amount']} {val_name}\n"
            elif r['type'] == 'card': text += f"🃏 Карта ID:{r['card_id']} ({r['mutation']})\n"
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"➕ Добавить {val_name}", callback_data="bpr_add_sh"), InlineKeyboardButton(text="➕ Добавить Карту", callback_data="bpr_add_cd")],
        [InlineKeyboardButton(text="✅ Завершить уровень", callback_data="bpr_next_lvl")]
    ])
    
    if isinstance(message_or_call, types.CallbackQuery):
        await message_or_call.message.answer(text, reply_markup=kb)
    else:
        await message_or_call.answer(text, reply_markup=kb)
    await state.set_state(AdminBPCreation.reward_action)

@dp.callback_query(AdminBPCreation.reward_action, F.data == "bpr_add_sh")
async def bpr_add_sh(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите количество:")
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
    except:
        await message.answer("❌ Число!")

@dp.callback_query(AdminBPCreation.reward_action, F.data == "bpr_add_cd")
async def bpr_add_cd(callback: types.CallbackQuery, state: FSMContext):
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']} (ID:{c['id']})"} for c in all_cards]
    await state.update_data(bpadm_items=items)
    kb = get_pagination_keyboard(items, 0, "bpadmc", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту для награды:", reply_markup=kb)
    await state.set_state(AdminBPCreation.reward_card)
    await callback.answer()

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
    
    try: await callback.message.delete()
    except: pass
    await adm_bp_show_reward_menu(callback, state, lvl)
    await callback.answer()

@dp.callback_query(AdminBPCreation.reward_action, F.data == "bpr_next_lvl")
async def bpr_next_lvl(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lvl = data['current_level']
    total_lvls = data['bp_levels_count']
    
    if lvl < total_lvls:
        await state.update_data(current_level=lvl + 1)
        try: await callback.message.delete()
        except: pass
        await adm_bp_ask_level_xp(callback, state, lvl + 1)
    else:
        try: await callback.message.delete()
        except: pass
        await adm_bp_finish_and_save(callback, state)
    await callback.answer()

async def adm_bp_finish_and_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    is_fb = data.get('bp_is_football', 0)
    
    text = f"✅ <b>Все настроено! Создаю Батл-пасс:</b>\nНазвание: {data['bp_title']}\nУровней: {data['bp_levels_count']}\n\n"
    await callback.message.answer(text)
    
    db = await get_db_connection()
    try:
        cursor = await db.execute("INSERT INTO battle_passes (title, photo_id, created_at, is_football) VALUES (?, ?, ?, ?)", (data['bp_title'], data.get('bp_photo'), time.time(), is_fb))
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
    cat_name = "Кубки" if cat == "trophies" else ("Шекели" if cat == "coins" else "Карты")
    await callback.message.edit_text(f"🏆 <b>Настройка наград: {cat_name}</b>\nВыберите позицию для редактирования наград:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("lb_edit_"))
async def adm_lb_edit(callback: types.CallbackQuery, state: FSMContext):
    bracket = callback.data.replace("lb_edit_", "")
    data = await state.get_data()
    lb_type = data.get('lb_current_type', 'trophies')
    
    rewards = await fetch_all("SELECT * FROM lb_rewards WHERE bracket = ? AND lb_type = ?", (bracket, lb_type))
    
    text = f"🏆 <b>Награды для места: {bracket.replace('_', '-')} ({lb_type})</b>\n\n"
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
    await callback.message.answer("Введите количество Шекелей для выдачи:")
    await state.set_state(AdminLBRewards.amount)
    await callback.answer()

@dp.message(AdminLBRewards.amount)
async def adm_lb_save_shekels(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        data = await state.get_data()
        lb_type = data.get('lb_current_type', 'trophies')
        await execute_db("INSERT INTO lb_rewards (bracket, reward_type, amount, lb_type) VALUES (?, ?, ?, ?)", (data['lb_bracket'], 'shekels', amt, lb_type))
        await message.answer(f"✅ Награда {amt} шекелей добавлена для {data['lb_bracket']} места ({lb_type})!")
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
    
    await callback.message.edit_text("Выберите карту для награды:", reply_markup=kb)
    await state.set_state(AdminLBRewards.card_id)
    await callback.answer()

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
    lb_type = data.get('lb_current_type', 'trophies')
    
    await execute_db("INSERT INTO lb_rewards (bracket, reward_type, card_id, mutation, lb_type) VALUES (?, ?, ?, ?, ?)", (bracket, 'card', card_id, mutation, lb_type))
    
    await callback.message.edit_text(f"✅ Карта (ID {card_id}, Мутация: {mutation}) добавлена в награды для {bracket} места ({lb_type})!")
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
    await callback.answer()

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
        
        ru_text = f"🍀 <b>ГЛОБАЛЬНЫЙ ИВЕНТ УДАЧИ!</b>\nШанс на редкие карты увеличен в {data['mult']} раз на {mins} минут! Загляните в Индекс, чтобы увидеть шансы!\n\n/getcard"
        asyncio.create_task(broadcast_message(ru_text, notif_type="notif_events"))
    except:
        await message.answer("Ошибка ввода.")

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
        
        ru_text = f"⏳ <b>ГЛОБАЛЬНЫЙ ИВЕНТ СКОРОСТИ!</b>\nТаймер выбивания карт ускорен в {data['mult']} раз на {mins} минут!\n\n/getcard"
        asyncio.create_task(broadcast_message(ru_text, notif_type="notif_events"))
    except:
        await message.answer("Ошибка ввода.")

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
        
        ru_text = f"💰 <b>ГЛОБАЛЬНЫЙ ИВЕНТ МОНЕТ!</b>\nПолучаемые шекели в боях против ИИ увеличены в {data['mult']} раз на {mins} минут!\n\n/pve"
        asyncio.create_task(broadcast_message(ru_text, notif_type="notif_events"))
    except:
        await message.answer("Ошибка ввода.")

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
        
        ru_text = f"🎫 <b>ГЛОБАЛЬНЫЙ ИВЕНТ НА ОПЫТ БП!</b>\nПолучаемый опыт Батл-пасса во всех боях увеличен в {data['mult']} раз на {mins} минут!\n\n/pve"
        asyncio.create_task(broadcast_message(ru_text, notif_type="notif_events"))
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
# МАСТЕРСКАЯ КРАФТА (ПРОДВИНУТЫЙ ПОЛЬЗОВАТЕЛЬСКИЙ ИНТЕРФЕЙС И АДМИНКА)
# ========================================================================
@dp.callback_query(F.data == "adm_craft_main")
async def adm_craft_main(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать рецепт", callback_data="adm_craft_create")],
        [InlineKeyboardButton(text="✏️ Изменить рецепт", callback_data="adm_craft_edit_list")],
        [InlineKeyboardButton(text="🗑 Удалить рецепт", callback_data="adm_craft_delete")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🔨 <b>Управление Рецептами Крафта</b>\nЗдесь вы можете настраивать рецепты для создания карт.", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "adm_craft_edit_list")
async def adm_craft_edit_list(callback: types.CallbackQuery):
    recipes = await fetch_all("SELECT r.id, c.name FROM craft_recipes r JOIN cards c ON r.target_card_id = c.id")
    if not recipes: return await callback.answer("Нет рецептов.", show_alert=True)
    
    kb = []
    for r in recipes:
        kb.append([InlineKeyboardButton(text=f"✏️ Изменить: {r['name']}", callback_data=f"adm_cr_ed_{r['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Отмена", callback_data="adm_craft_main")])
    await callback.message.edit_text("Выберите рецепт для изменения:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_cr_ed_"))
async def adm_craft_edit_menu(callback: types.CallbackQuery, state: FSMContext):
    r_id = int(callback.data.split("_")[3])
    await state.update_data(editing_recipe_id=r_id)
    await show_craft_edit_menu(callback.message, state)
    await callback.answer()

async def show_craft_edit_menu(message_or_call, state: FSMContext):
    data = await state.get_data()
    r_id = data['editing_recipe_id']
    recipe = await fetch_one("SELECT r.id, r.price, c.name FROM craft_recipes r JOIN cards c ON r.target_card_id = c.id WHERE r.id = ?", (r_id,))
    ingredients = await fetch_all("SELECT i.id as ing_id, c.name, i.amount FROM craft_ingredients i JOIN cards c ON i.card_id = c.id WHERE i.recipe_id = ?", (r_id,))
    
    text = f"🔨 <b>Изменение рецепта: {recipe['name']}</b>\nЦена крафта: <b>{recipe['price']} 💰</b>\n\nИнгредиенты:\n"
    if not ingredients: text += "<i>Пусто</i>\n"
    else:
        for idx, ing in enumerate(ingredients, 1):
            text += f"{idx}. {ing['name']} x{ing['amount']}\n"
            
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить цену", callback_data="cr_ed_price")],
        [InlineKeyboardButton(text="➕ Добавить ингредиент", callback_data="cr_ed_add_ing")],
        [InlineKeyboardButton(text="🗑 Удалить ингредиент", callback_data="cr_ed_del_ing")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_craft_edit_list")]
    ])
    
    if isinstance(message_or_call, types.Message): await message_or_call.answer(text, reply_markup=kb)
    else: await message_or_call.edit_text(text, reply_markup=kb)
    await state.set_state(AdminCraftEdit.menu)

@dp.callback_query(AdminCraftEdit.menu, F.data == "cr_ed_price")
async def cr_ed_price(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите новую цену крафта в шекелях:")
    await state.set_state(AdminCraftEdit.edit_price)
    await callback.answer()

@dp.message(AdminCraftEdit.edit_price)
async def cr_ed_price_save(message: types.Message, state: FSMContext):
    try:
        price = int(message.text)
        if price < 0: raise ValueError
        data = await state.get_data()
        r_id = data['editing_recipe_id']
        await execute_db("UPDATE craft_recipes SET price = ? WHERE id = ?", (price, r_id))
        await message.answer("✅ Цена обновлена!")
        await show_craft_edit_menu(message, state)
    except:
        await message.answer("❌ Введите положительное число.")

@dp.callback_query(AdminCraftEdit.menu, F.data == "cr_ed_add_ing")
async def cr_ed_add_ing(callback: types.CallbackQuery, state: FSMContext):
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']} (ID:{c['id']})"} for c in all_cards]
    await state.update_data(craft_items=items)
    kb = get_pagination_keyboard(items, 0, "cred_ing", columns=1, items_per_page=8)
    await callback.message.edit_text("Выберите карту-ингредиент для добавления:", reply_markup=kb)
    await state.set_state(AdminCraftEdit.add_ing_card)
    await callback.answer()

@dp.callback_query(AdminCraftEdit.add_ing_card, F.data.startswith("cred_ing_page_"))
async def cr_ed_add_ing_pag(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('craft_items', []), page, "cred_ing", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(AdminCraftEdit.add_ing_card, F.data.startswith("cred_ing_"))
async def cr_ed_add_ing_sel(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[2])
    await state.update_data(cr_curr_ing=card_id)
    await callback.message.edit_text("Введите количество требуемых штук (например: 5):")
    await state.set_state(AdminCraftEdit.add_ing_amount)
    await callback.answer()

@dp.message(AdminCraftEdit.add_ing_amount)
async def cr_ed_add_ing_amt(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        if amt <= 0: raise ValueError
        data = await state.get_data()
        r_id = data['editing_recipe_id']
        c_id = data['cr_curr_ing']
        await execute_db("INSERT INTO craft_ingredients (recipe_id, card_id, amount) VALUES (?, ?, ?)", (r_id, c_id, amt))
        await message.answer("✅ Ингредиент добавлен!")
        await show_craft_edit_menu(message, state)
    except:
        await message.answer("❌ Число > 0.")

@dp.callback_query(AdminCraftEdit.menu, F.data == "cr_ed_del_ing")
async def cr_ed_del_ing(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    r_id = data['editing_recipe_id']
    ingredients = await fetch_all("SELECT i.id as ing_id, c.name, i.amount FROM craft_ingredients i JOIN cards c ON i.card_id = c.id WHERE i.recipe_id = ?", (r_id,))
    if not ingredients: return await callback.answer("Нет ингредиентов для удаления.", show_alert=True)
    
    kb = []
    for ing in ingredients:
        kb.append([InlineKeyboardButton(text=f"🗑 {ing['name']} x{ing['amount']}", callback_data=f"cr_del_ing_{ing['ing_id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="cr_ed_back")])
    await callback.message.edit_text("Выберите ингредиент для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(F.data.startswith("cr_del_ing_"))
async def cr_del_ing_action(callback: types.CallbackQuery, state: FSMContext):
    ing_id = int(callback.data.split("_")[3])
    await execute_db("DELETE FROM craft_ingredients WHERE id = ?", (ing_id,))
    await callback.answer("✅ Ингредиент удален!", show_alert=True)
    await show_craft_edit_menu(callback.message, state)

@dp.callback_query(F.data == "cr_ed_back")
async def cr_ed_back(callback: types.CallbackQuery, state: FSMContext):
    await show_craft_edit_menu(callback.message, state)
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
    await callback.answer()

@dp.callback_query(AdminCraftCreate.target_card, F.data.startswith("crc_target_"))
async def adm_craft_cr_select(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[2])
    await state.update_data(cr_target=card_id, cr_ings=[])
    await callback.message.edit_text("🔨 <b>Шаг 2: Введите цену крафта в Шекелях (например: 50000):</b>")
    await state.set_state(AdminCraftCreate.price)
    await callback.answer()
    
@dp.message(AdminCraftCreate.price)
async def adm_craft_cr_price(message: types.Message, state: FSMContext):
    try:
        price = int(message.text)
        if price < 0: raise ValueError
        await state.update_data(cr_price=price)
        await adm_craft_cr_show_menu(message, state)
    except:
        await message.answer("❌ Введите положительное число.")

async def adm_craft_cr_show_menu(msg, state: FSMContext):
    data = await state.get_data()
    t_card = await fetch_one("SELECT name FROM cards WHERE id = ?", (data['cr_target'],))
    
    text = f"🔨 <b>Настройка Рецепта</b>\nЦель: <b>{t_card['name']}</b>\nЦена: <b>{data['cr_price']} 💰</b>\n\nИнгредиенты:\n"
    if not data['cr_ings']: text += "<i>Пусто</i>\n"
    else:
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
    await callback.answer()

@dp.callback_query(AdminCraftCreate.add_ingredient_card, F.data.startswith("crc_ing_page_"))
async def adm_craft_ing_pag(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('craft_items', []), page, "crc_ing", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(AdminCraftCreate.add_ingredient_card, F.data.startswith("crc_ing_"))
async def adm_craft_ing_sel(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return
    card_id = int(callback.data.split("_")[2])
    await state.update_data(cr_curr_ing=card_id)
    await callback.message.edit_text("Введите количество требуемых штук (например: 5):")
    await state.set_state(AdminCraftCreate.add_ingredient_amount)
    await callback.answer()

@dp.message(AdminCraftCreate.add_ingredient_amount)
async def adm_craft_ing_amt(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        if amt <= 0: raise ValueError
        data = await state.get_data()
        data['cr_ings'].append({'card_id': data['cr_curr_ing'], 'amount': amt})
        await state.update_data(cr_ings=data['cr_ings'])
        await adm_craft_cr_show_menu(message, state)
    except:
        await message.answer("❌ Число > 0.")

@dp.callback_query(AdminCraftCreate.add_ingredient_card, F.data == "cr_save")
async def adm_craft_save(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data['cr_ings']: return await callback.answer("❌ Добавьте хотя бы 1 ингредиент!", show_alert=True)
    
    db = await get_db_connection()
    try:
        cur = await db.execute("INSERT INTO craft_recipes (target_card_id, price) VALUES (?, ?)", (data['cr_target'], data['cr_price']))
        r_id = cur.lastrowid
        for ing in data['cr_ings']:
            await db.execute("INSERT INTO craft_ingredients (recipe_id, card_id, amount) VALUES (?, ?, ?)", (r_id, ing['card_id'], ing['amount']))
        await db.commit()
        await callback.message.edit_text("✅ Рецепт успешно создан!")
    finally:
        await db.close()
    await state.clear()
    await callback.answer()

# ========================================================================
# ПОЛЬЗОВАТЕЛЬСКИЙ КРАФТ (ПЕРЕРАБОТКА С ВЫБОРОМ МУТАЦИЙ)
# ========================================================================
@dp.message(F.text == BTN_CRAFT)
@dp.message(Command("craft"))
async def cmd_craft_menu(message: types.Message):
    if await check_ban(message.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Рецепты", callback_data="craft_recipes_list")],
        [InlineKeyboardButton(text="✨ Улучшение мутаций", callback_data="craft_upgrade_list")]
    ])
    await message.answer("🔨 <b>МАСТЕРСКАЯ КРАФТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите раздел:", reply_markup=kb)

@dp.callback_query(F.data == "craft_menu_main")
async def cb_craft_menu_main(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Рецепты", callback_data="craft_recipes_list")],
        [InlineKeyboardButton(text="✨ Улучшение мутаций", callback_data="craft_upgrade_list")]
    ])
    try: await callback.message.edit_text("🔨 <b>МАСТЕРСКАЯ КРАФТА</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВыберите раздел:", reply_markup=kb)
    except: pass
    await callback.answer()

@dp.callback_query(F.data == "craft_recipes_list")
async def cb_craft_recipes_list(callback: types.CallbackQuery):
    recipes = await fetch_all("SELECT r.id, c.name FROM craft_recipes r JOIN cards c ON r.target_card_id = c.id")
    if not recipes: return await callback.answer("Рецептов пока нет.", show_alert=True)
    
    items = [{"id": r['id'], "btn_text": f"🔨 {r['name']}"} for r in recipes]
    kb = get_pagination_keyboard(items, 0, "craft_rec", columns=1, items_per_page=8)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="craft_menu_main")])
    await callback.message.edit_text("📜 <b>Доступные Рецепты</b>:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("craft_rec_page_"))
async def cb_craft_recipes_pag(callback: types.CallbackQuery):
    page = int(callback.data.split("_")[3])
    recipes = await fetch_all("SELECT r.id, c.name FROM craft_recipes r JOIN cards c ON r.target_card_id = c.id")
    items = [{"id": r['id'], "btn_text": f"🔨 {r['name']}"} for r in recipes]
    kb = get_pagination_keyboard(items, page, "craft_rec", columns=1, items_per_page=8)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="craft_menu_main")])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

async def render_user_craft_ui(msg_or_call, user_id, recipe_id):
    recipe = await fetch_one("SELECT target_card_id, price FROM craft_recipes WHERE id = ?", (recipe_id,))
    target_card = await fetch_one("SELECT name, photo_id, rarity FROM cards WHERE id = ?", (recipe['target_card_id'],))
    ingredients = await fetch_all("SELECT id, card_id, amount FROM craft_ingredients WHERE recipe_id = ?", (recipe_id,))
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (user_id,))
    
    session = active_craft_sessions.get(user_id)
    if not session or session['recipe_id'] != recipe_id:
        session = {'recipe_id': recipe_id, 'selected_slots': {}}
        for ing in ingredients:
            session['selected_slots'][ing['card_id']] = [] 
        active_craft_sessions[user_id] = session

    text = f"🔨 <b>КРАФТ: {target_card['name']}</b>\nСтоимость: {recipe['price']} 💰 (У вас: {user['coins']})\n━━━━━━━━━━━━━━━━━━━━━━━━\nТребования для сборки:\n"
    
    all_filled = True
    gold_count = 0
    rainbow_count = 0
    total_needed = 0

    kb_btns = []
    
    for idx, ing in enumerate(ingredients, 1):
        c_name = (await fetch_one("SELECT name FROM cards WHERE id = ?", (ing['card_id'],)))['name']
        needed = ing['amount']
        total_needed += needed
        
        selected_for_this = session['selected_slots'].get(ing['card_id'], [])
        sel_count = sum(s['qty'] for s in selected_for_this)
        
        for s in selected_for_this:
            if s['mutation'] == 'Gold': gold_count += s['qty']
            if s['mutation'] == 'Rainbow': rainbow_count += s['qty']

        text += f"{idx}. {c_name} (Собрано {sel_count}/{needed})\n"
        if sel_count < needed: 
            all_filled = False
            kb_btns.append([InlineKeyboardButton(text=f"➕ Добавить {c_name}", callback_data=f"ucraft_add_{recipe_id}_{ing['card_id']}")])

    text += f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"⚠️ <i>Вы можете вкладывать любые версии карт (с росписью, с мутацией). Чем больше золотых/радужных вы вложите, тем выше шанс получить мутированный результат!</i>\n"
    
    if total_needed > 0:
        base_gold_chance = 20.0
        base_rainbow_chance = 5.0
        bonus_gold = (gold_count / total_needed) * 80.0
        bonus_rainbow = (rainbow_count / total_needed) * 50.0
        
        final_g = min(100.0, base_gold_chance + bonus_gold)
        final_r = min(100.0, base_rainbow_chance + bonus_rainbow)
        text += f"Текущий шанс на ⭐ Золотую: ~{final_g:.1f}%\n"
        text += f"Текущий шанс на 🌈 Радужную: ~{final_r:.1f}%\n"
    
    if all_filled:
        kb_btns.insert(0, [InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ И СКРАФТИТЬ ✅", callback_data=f"ucraft_execute_{recipe_id}")])
        
    kb_btns.append([
        InlineKeyboardButton(text="⚡ Авто-заполнение", callback_data=f"ucraft_auto_{recipe_id}"),
        InlineKeyboardButton(text="🧹 Очистить слоты", callback_data=f"ucraft_clear_{recipe_id}")
    ])
    kb_btns.append([InlineKeyboardButton(text="❓ Как получить ингредиенты?", callback_data=f"craft_sources_{recipe['target_card_id']}")])
    kb_btns.append([InlineKeyboardButton(text="🔙 К рецептам", callback_data="craft_recipes_list")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=kb_btns)
    if isinstance(msg_or_call, types.CallbackQuery):
        try:
            await msg_or_call.message.delete()
        except: pass
        await msg_or_call.message.answer_photo(photo=target_card['photo_id'], caption=text, reply_markup=markup)
    else:
        try:
            await msg_or_call.delete()
        except: pass
        await msg_or_call.answer_photo(photo=target_card['photo_id'], caption=text, reply_markup=markup)

@dp.callback_query(F.data.startswith("craft_rec_"))
async def cb_craft_rec_select(callback: types.CallbackQuery):
    if "page" in callback.data: return
    recipe_id = int(callback.data.split("_")[2])
    if callback.from_user.id in active_craft_sessions:
        active_craft_sessions.pop(callback.from_user.id)
    await render_user_craft_ui(callback, callback.from_user.id, recipe_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("ucraft_clear_"))
async def cb_ucraft_clear(callback: types.CallbackQuery):
    recipe_id = int(callback.data.split("_")[2])
    if callback.from_user.id in active_craft_sessions:
        active_craft_sessions.pop(callback.from_user.id)
    await render_user_craft_ui(callback, callback.from_user.id, recipe_id)
    await callback.answer("Слоты очищены!")

@dp.callback_query(F.data.startswith("ucraft_auto_"))
async def cb_ucraft_auto(callback: types.CallbackQuery):
    recipe_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    ingredients = await fetch_all("SELECT card_id, amount FROM craft_ingredients WHERE recipe_id = ?", (recipe_id,))
    session = active_craft_sessions.get(user_id)
    if not session: return await callback.answer("Ошибка сессии", show_alert=True)

    for ing in ingredients:
        c_id = ing['card_id']
        needed = ing['amount']
        
        selected_now = session['selected_slots'].get(c_id, [])
        sel_count = sum(s['qty'] for s in selected_now)
        if sel_count >= needed: continue
        
        rem_needed = needed - sel_count
        
        invs = await fetch_all("""
            SELECT id, count, mutation, serial_number, signed_by 
            FROM inventory 
            WHERE user_id = ? AND card_id = ? AND is_football = 0
            ORDER BY 
                CASE mutation WHEN 'Normal' THEN 1 WHEN 'Gold' THEN 2 WHEN 'Rainbow' THEN 3 END ASC,
                signed_by ASC, serial_number ASC
        """, (user_id, c_id))
        
        for inv_item in invs:
            if rem_needed <= 0: break
            
            already_taken = 0
            for s in selected_now:
                if s['inv_id'] == inv_item['id']: already_taken += s['qty']
                
            available = inv_item['count'] - already_taken
            if available <= 0: continue
            
            take = min(available, rem_needed)
            
            found = False
            for s in session['selected_slots'][c_id]:
                if s['inv_id'] == inv_item['id']:
                    s['qty'] += take
                    found = True
                    break
            if not found:
                session['selected_slots'][c_id].append({
                    'inv_id': inv_item['id'],
                    'qty': take,
                    'mutation': inv_item['mutation']
                })
                
            rem_needed -= take

    active_craft_sessions[user_id] = session
    await render_user_craft_ui(callback, user_id, recipe_id)
    await callback.answer("Авто-заполнение выполнено!")

@dp.callback_query(F.data.startswith("ucraft_add_"))
async def cb_ucraft_add(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    recipe_id = int(parts[2])
    card_id = int(parts[3])
    user_id = callback.from_user.id
    
    session = active_craft_sessions.get(user_id)
    if not session: return await callback.answer("Ошибка сессии")
    
    invs = await fetch_all("""
        SELECT i.id, i.count, i.mutation, i.serial_number, i.signed_by, c.name 
        FROM inventory i JOIN cards c ON i.card_id = c.id
        WHERE i.user_id = ? AND i.card_id = ? AND i.is_football = 0
    """, (user_id, card_id))
    
    items = []
    selected_now = session['selected_slots'].get(card_id, [])
    
    for i in invs:
        already_taken = sum(s['qty'] for s in selected_now if s['inv_id'] == i['id'])
        available = i['count'] - already_taken
        if available > 0:
            mut_str = "⭐" if i['mutation'] == 'Gold' else "🌈" if i['mutation'] == 'Rainbow' else "⚪"
            sign_str = "✍️" if i['signed_by'] > 0 else ""
            ser_str = f"[#{i['serial_number']:04d}]" if i['serial_number'] > 0 else ""
            
            label = f"{mut_str} {i['name']} {ser_str}{sign_str} (Дост: {available})"
            items.append({"id": f"{recipe_id}_{card_id}_{i['id']}", "btn_text": label})
            
    if not items:
        return await callback.answer("У вас нет свободных подходящих карт!", show_alert=True)
        
    kb = get_pagination_keyboard(items, 0, "ucraft_sel", columns=1, items_per_page=8)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"craft_rec_0_{recipe_id}")]) 
    
    try: await callback.message.delete()
    except: pass
    await callback.message.answer(f"Выберите конкретную карту для крафта:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("ucraft_sel_page_"))
async def cb_ucraft_sel_page(callback: types.CallbackQuery):
    await callback.answer("Используйте первые 8 карт.")

@dp.callback_query(F.data.startswith("ucraft_sel_"))
async def cb_ucraft_sel(callback: types.CallbackQuery):
    if "page" in callback.data: return
    parts = callback.data.split("_")
    recipe_id = int(parts[2])
    card_id = int(parts[3])
    inv_id = int(parts[4])
    user_id = callback.from_user.id
    
    session = active_craft_sessions.get(user_id)
    if not session: return await callback.answer("Сессия истекла")
    
    row = await fetch_one("SELECT count, mutation FROM inventory WHERE id = ?", (inv_id,))
    if not row: return await callback.answer("Не найдено")
    
    ing_needed = await fetch_one("SELECT amount FROM craft_ingredients WHERE recipe_id = ? AND card_id = ?", (recipe_id, card_id))
    if not ing_needed: return await callback.answer("Ошибка рецепта")
    
    needed = ing_needed['amount']
    selected_now = session['selected_slots'].get(card_id, [])
    sel_count = sum(s['qty'] for s in selected_now)
    
    rem_needed = needed - sel_count
    if rem_needed <= 0:
        return await callback.answer("Слот уже заполнен полностью!", show_alert=True)
        
    already_taken = sum(s['qty'] for s in selected_now if s['inv_id'] == inv_id)
    available = row['count'] - already_taken
    
    take = min(available, rem_needed)
    if take > 0:
        found = False
        for s in session['selected_slots'][card_id]:
            if s['inv_id'] == inv_id:
                s['qty'] += take
                found = True
                break
        if not found:
            session['selected_slots'][card_id].append({
                'inv_id': inv_id,
                'qty': take,
                'mutation': row['mutation']
            })
            
    active_craft_sessions[user_id] = session
    await render_user_craft_ui(callback, user_id, recipe_id)
    await callback.answer("Добавлено!")

@dp.callback_query(F.data.startswith("ucraft_execute_"))
async def cb_ucraft_execute(callback: types.CallbackQuery):
    recipe_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    session = active_craft_sessions.get(user_id)
    if not session or session['recipe_id'] != recipe_id:
        return await callback.answer("Ошибка сессии!", show_alert=True)
        
    recipe = await fetch_one("SELECT target_card_id, price FROM craft_recipes WHERE id = ?", (recipe_id,))
    ingredients = await fetch_all("SELECT card_id, amount FROM craft_ingredients WHERE recipe_id = ?", (recipe_id,))
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (user_id,))
    
    if user['coins'] < recipe['price']:
        return await callback.answer("❌ Недостаточно шекелей!", show_alert=True)
        
    gold_count = 0
    rainbow_count = 0
    total_needed = 0
    
    to_delete = {} 
    
    for ing in ingredients:
        c_id = ing['card_id']
        needed = ing['amount']
        total_needed += needed
        
        sel = session['selected_slots'].get(c_id, [])
        sel_count = sum(s['qty'] for s in sel)
        if sel_count < needed:
            return await callback.answer("❌ Вы не заполнили все слоты!", show_alert=True)
            
        for s in sel:
            if s['mutation'] == 'Gold': gold_count += s['qty']
            elif s['mutation'] == 'Rainbow': rainbow_count += s['qty']
            to_delete[s['inv_id']] = to_delete.get(s['inv_id'], 0) + s['qty']
            
    db = await get_db_connection()
    try:
        await db.execute("BEGIN EXCLUSIVE") 
        
        for inv_id, qty in to_delete.items():
            row = await db.execute("SELECT count FROM inventory WHERE id = ? AND user_id = ?", (inv_id, user_id))
            r = await row.fetchone()
            if not r or r['count'] < qty:
                raise ValueError(f"Not enough cards")
                
        for inv_id, qty in to_delete.items():
            row = await db.execute("SELECT count FROM inventory WHERE id = ?", (inv_id,))
            r = await row.fetchone()
            if r['count'] == qty:
                await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
                for s in ['equip1', 'equip2', 'equip3', 'equip4', 'fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4']:
                    await db.execute(f"UPDATE users SET {s} = 0 WHERE id = ? AND {s} = ?", (user_id, inv_id))
            else:
                await db.execute("UPDATE inventory SET count = count - ? WHERE id = ?", (qty, inv_id))
                
        await db.execute("UPDATE users SET coins = coins - ? WHERE id = ?", (recipe['price'], user_id))
        await db.commit()
    except ValueError:
        await db.execute("ROLLBACK")
        return await callback.answer("❌ Ошибка: Выбраны несуществующие или уже потраченные карты.", show_alert=True)
    except Exception as e:
        await db.execute("ROLLBACK")
        logging.error(f"Craft Error: {e}")
        return await callback.answer("❌ Системная ошибка БД.", show_alert=True)
    finally:
        await db.close()
        
    active_craft_sessions.pop(user_id, None)
    
    target_card = await fetch_one("SELECT * FROM cards WHERE id = ?", (recipe['target_card_id'],))
    
    base_gold_chance = 20.0
    base_rainbow_chance = 5.0
    bonus_gold = (gold_count / total_needed) * 80.0
    bonus_rainbow = (rainbow_count / total_needed) * 50.0
    
    final_g = min(100.0, base_gold_chance + bonus_gold)
    final_r = min(100.0, base_rainbow_chance + bonus_rainbow)
    
    rand_val = random.random() * 100.0
    if rand_val < final_r: result_mut = "Rainbow"
    elif rand_val < final_r + final_g: result_mut = "Gold"
    else: result_mut = "Normal"
    
    _, serial, _ = await give_card_to_user(user_id, target_card['id'], result_mut, target_card['rarity'], is_football=0)
    
    target_card['mutation'] = result_mut
    target_card['serial_number'] = serial
    target_card['signed_by'] = 0
    
    await log_user_action(user_id, f"Скрафтил {target_card['name']} (Mut: {result_mut})")
    
    mut_str = "🌈 Радужная" if result_mut == 'Rainbow' else ("⭐ Золотая" if result_mut == 'Gold' else "Обычная")
    text = f"🎉 <b>КРАФТ УСПЕШЕН!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВы создали: {format_card_name(target_card)}\nМутация: <b>{mut_str}</b>\n\nШансы были: Золото {final_g:.1f}%, Радуга {final_r:.1f}%\nКарта добавлена в инвентарь!"
    
    try: await callback.message.delete()
    except: pass
    await callback.message.answer_photo(photo=target_card['photo_id'], caption=text)
    await callback.answer()

@dp.callback_query(F.data == "craft_upgrade_list")
async def cb_craft_upgrade_list(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    invs = await fetch_all("""
        SELECT card_id, mutation, SUM(count) as total
        FROM inventory
        WHERE user_id = ? AND is_football = 0 AND signed_by = 0
        GROUP BY card_id, mutation
        HAVING total >= 8
    """, (user_id,))
    
    if not invs:
        return await callback.answer("У вас нет 8 одинаковых копий одной мутации (без росписи) для улучшения.", show_alert=True)
        
    items = []
    for r in invs:
        if r['mutation'] == 'Rainbow': continue
        
        c_info = await fetch_one("SELECT name, rarity FROM cards WHERE id = ?", (r['card_id'],))
        if not c_info: continue
        
        from_mut = "⚪" if r['mutation'] == 'Normal' else "⭐"
        to_mut = "⭐" if r['mutation'] == 'Normal' else "🌈"
        
        items.append({
            "id": f"{r['card_id']}_{r['mutation']}",
            "btn_text": f"✨ {from_mut} {c_info['name']} ➡️ {to_mut}"
        })
        
    if not items:
        return await callback.answer("Нет доступных улучшений.", show_alert=True)
        
    kb = get_pagination_keyboard(items, 0, "crupgrade", columns=1, items_per_page=8)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="craft_menu_main")])
    await callback.message.edit_text("✨ <b>ДОСТУПНЫЕ УЛУЧШЕНИЯ</b>\nТребуется 8 карт для слияния.", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("crupgrade_page_"))
async def cb_cr_upg_pag(callback: types.CallbackQuery):
    await cb_craft_upgrade_list(callback) 

@dp.callback_query(F.data.startswith("crupgrade_"))
async def cb_cr_upg_select(callback: types.CallbackQuery):
    if "page" in callback.data: return
    parts = callback.data.split("_")
    card_id = int(parts[1])
    mutation = parts[2]
    user_id = callback.from_user.id
    
    c_info = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
    from_mut = "⚪ Обычная" if mutation == 'Normal' else "⭐ Золотая"
    to_mut = "⭐ Золотую" if mutation == 'Normal' else "🌈 Радужную"
    
    total = (await fetch_one("SELECT SUM(count) as t FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND is_football = 0 AND signed_by = 0", (user_id, card_id, mutation)))['t']
    
    text = f"✨ <b>Улучшение: {c_info['name']}</b>\nИз {from_mut} в {to_mut}.\n\nУ вас есть: {total} шт. Требуется: 8 шт.\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ ПОДТВЕРДИТЬ СЛИЯНИЕ", callback_data=f"crup_confirm_{card_id}_{mutation}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="craft_upgrade_list")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("crup_confirm_"))
async def cb_crup_confirm(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    card_id = int(parts[2])
    mutation = parts[3]
    user_id = callback.from_user.id
    
    to_mut = "Gold" if mutation == 'Normal' else "Rainbow"
    
    db = await get_db_connection()
    try:
        await db.execute("BEGIN EXCLUSIVE")
        cur = await db.execute("SELECT SUM(count) as t FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND is_football = 0 AND signed_by = 0", (user_id, card_id, mutation))
        row = await cur.fetchone()
        if not row or row['t'] is None or row['t'] < 8:
            raise ValueError("Not enough")
            
        needed = 8
        cur = await db.execute("SELECT id, count FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND is_football = 0 AND signed_by = 0 ORDER BY id ASC", (user_id, card_id, mutation))
        packs = await cur.fetchall()
        for pack in packs:
            if needed <= 0: break
            take = min(needed, pack['count'])
            if take == pack['count']:
                await db.execute("DELETE FROM inventory WHERE id = ?", (pack['id'],))
                for s in ['equip1', 'equip2', 'equip3', 'equip4']:
                    await db.execute(f"UPDATE users SET {s} = 0 WHERE id = ? AND {s} = ?", (user_id, pack['id']))
            else:
                await db.execute("UPDATE inventory SET count = count - ? WHERE id = ?", (take, pack['id']))
            needed -= take
        await db.commit()
    except ValueError:
        await db.execute("ROLLBACK")
        return await callback.answer("Ошибка слияния! Не хватает карт.", show_alert=True)
    except Exception as e:
        await db.execute("ROLLBACK")
        return await callback.answer("Системная ошибка.", show_alert=True)
    finally:
        await db.close()
        
    target_card = await fetch_one("SELECT * FROM cards WHERE id = ?", (card_id,))
    _, serial, _ = await give_card_to_user(user_id, target_card['id'], to_mut, target_card['rarity'], is_football=0)
    
    target_card['mutation'] = to_mut
    target_card['serial_number'] = serial
    target_card['signed_by'] = 0
    
    await log_user_action(user_id, f"Улучшил {target_card['name']} до {to_mut}")
    
    mut_str = "🌈 Радужная" if to_mut == 'Rainbow' else "⭐ Золотая"
    text = f"🎉 <b>УЛУЧШЕНИЕ УСПЕШНО!</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\nВы получили: {format_card_name(target_card)}\nНовая Мутация: <b>{mut_str}</b>\n\nКарта добавлена в инвентарь!"
    await callback.message.edit_text(text, reply_markup=None)
    await callback.answer()

# ========================================================================
# ТРАНСФЕР (ИЗ ФУТБОЛА В ОСНОВУ)
# ========================================================================
@dp.message(F.text == BTN_FB_TRANSFER)
async def cmd_fb_transfer(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT last_transfer FROM users WHERE id = ?", (message.from_user.id,))
    
    now = time.time()
    if user['last_transfer'] > now:
        left = int(user['last_transfer'] - now)
        m, s = divmod(left, 60)
        return await message.answer(f"⏳ <b>Трансферное окно закрыто!</b>\nПодождите: {m} мин. {s} сек.")
        
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, i.id as inv_id, i.count, i.mutation
        FROM inventory i JOIN cards c ON i.card_id = c.id
        WHERE i.user_id = ? AND i.is_football = 1 AND i.count > 0
    """, (message.from_user.id,))
    
    if not inv:
        return await message.answer("✈️ <b>ТРАНСФЕР</b>\nУ вас нет карт Cardball для переноса в основной профиль!")
        
    items = []
    for item in inv:
        mut_str = "⭐" if item['mutation'] == 'Gold' else "🌈" if item['mutation'] == 'Rainbow' else "⚪"
        items.append({"id": item['inv_id'], "btn_text": f"{mut_str} {item['name']} (x{item['count']})"})
        
    kb = get_pagination_keyboard(items, 0, "trans", columns=1, items_per_page=8)
    await message.answer("✈️ <b>ТРАНСФЕР КАРТ</b>\nЗдесь вы можете забрать заработанные в Cardball карты в основной аккаунт!\n\n<i>Внимание: Трансфер можно делать 1 раз в 30 минут. Выбранная пачка карт (все её копии) будет навсегда перенесена.</i>\n\nВыберите карту:", reply_markup=kb)

@dp.callback_query(F.data.startswith("trans_page_"))
async def cb_trans_pag(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    inv = await fetch_all("""
        SELECT c.id as card_id, c.name, i.id as inv_id, i.count, i.mutation
        FROM inventory i JOIN cards c ON i.card_id = c.id
        WHERE i.user_id = ? AND i.is_football = 1 AND i.count > 0
    """, (callback.from_user.id,))
    items = []
    for item in inv:
        mut_str = "⭐" if item['mutation'] == 'Gold' else "🌈" if item['mutation'] == 'Rainbow' else "⚪"
        items.append({"id": item['inv_id'], "btn_text": f"{mut_str} {item['name']} (x{item['count']})"})
    kb = get_pagination_keyboard(items, page, "trans", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("trans_"))
async def cb_trans_execute(callback: types.CallbackQuery):
    if "page" in callback.data: return
    inv_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    db = await get_db_connection()
    try:
        await db.execute("BEGIN EXCLUSIVE")
        user = await db.execute("SELECT last_transfer FROM users WHERE id = ?", (user_id,))
        u = await user.fetchone()
        if u['last_transfer'] > time.time():
            raise ValueError("Cooldown")
            
        cur = await db.execute("SELECT * FROM inventory WHERE id = ? AND user_id = ? AND is_football = 1", (inv_id, user_id))
        row = await cur.fetchone()
        if not row or row['count'] <= 0:
            raise ValueError("Not found")
            
        qty = row['count']
        card_id = row['card_id']
        mutation = row['mutation']
        serial = row['serial_number']
        signed = row['signed_by']
        
        await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
        for s in ['fb_equip1', 'fb_equip2', 'fb_equip3', 'fb_equip4']:
            await db.execute(f"UPDATE users SET {s} = 0 WHERE id = ? AND {s} = ?", (user_id, inv_id))
            
        cur2 = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = ? AND signed_by = ? AND is_football = 0", (user_id, card_id, mutation, serial, signed))
        dest = await cur2.fetchone()
        if dest:
            await db.execute("UPDATE inventory SET count = count + ? WHERE id = ?", (qty, dest['id']))
        else:
            await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number, signed_by, is_football) VALUES (?, ?, ?, ?, ?, ?, 0)", (user_id, card_id, qty, mutation, serial, signed))
            
        await db.execute("UPDATE users SET last_transfer = ? WHERE id = ?", (time.time() + 1800, user_id))
        await db.commit()
        
        c_info = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
        await callback.message.edit_text(f"✈️✅ <b>ТРАНСФЕР УСПЕШЕН!</b>\nКарта <b>{c_info['name']}</b> (x{qty}) перенесена в основной инвентарь!\nСледующий трансфер доступен через 30 минут.")
    except ValueError as e:
        await db.execute("ROLLBACK")
        if str(e) == "Cooldown": await callback.answer("Кулдаун!", show_alert=True)
        else: await callback.answer("Ошибка карты!", show_alert=True)
    except Exception as e:
        await db.execute("ROLLBACK")
        await callback.answer("Системная ошибка", show_alert=True)
    finally:
        await db.close()
    await callback.answer()


# ========================================================================
# CARDBALL-ЛИГА (WORLD CUP) С РАСШИРЕННЫМИ ФУНКЦИЯМИ И НАГРАДАМИ
# ========================================================================
def get_next_league_reset() -> datetime:
    msk_tz = timezone(timedelta(hours=3))
    now = datetime.now(msk_tz)
    base_date = datetime(2026, 7, 14, 0, 0, 0, tzinfo=msk_tz)
    
    if now < base_date:
        return base_date
        
    delta = now - base_date
    days_passed = delta.days
    periods_passed = days_passed // 2
    next_reset = base_date + timedelta(days=(periods_passed + 1) * 2)
    return next_reset

@dp.message(Command("startcuplig"))
async def cmd_start_league(message: types.Message):
    if not await is_admin(message.from_user.id): return
    
    db = await get_db_connection()
    try:
        await db.execute("BEGIN")
        final_match = await db.execute("SELECT t1_id, t2_id, winner_id FROM league_matches WHERE stage = 3")
        f_match = await final_match.fetchone()
        
        await db.execute("UPDATE league_teams SET score = 0")
        await db.execute("UPDATE users SET football_team_id = 0")
        await db.execute("DELETE FROM league_matches")
        
        matches = [(1,1,2), (1,3,4), (1,5,6), (1,7,8)]
        for stage, t1, t2 in matches:
            await db.execute("INSERT INTO league_matches (stage, t1_id, t2_id) VALUES (?, ?, ?)", (stage, t1, t2))
            
        await db.commit()
    finally:
        await db.close()
        
    await message.answer("⚽ <b>ЛИГА CARDBALL СБРОШЕНА И ЗАПУЩЕНА!</b>\nВсе команды обнулены, сформирована сетка четвертьфиналов.")

@dp.message(F.text == BTN_FB_LEAGUE)
async def cmd_fb_league(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT football_team_id FROM users WHERE id = ?", (message.from_user.id,))
    
    if user['football_team_id'] == 0:
        teams = await fetch_all("SELECT id, name FROM league_teams")
        kb = []
        for t in teams:
            kb.append([InlineKeyboardButton(text=f"Вступить: {t['name']}", callback_data=f"jointeam_{t['id']}")])
        return await message.answer("⚽ <b>ЛИГА CARDBALL</b>\nВы еще не в команде! Выберите сборную (Осторожно, сменить нельзя до конца лиги!):", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        
    my_team = await fetch_one("SELECT name, score FROM league_teams WHERE id = ?", (user['football_team_id'],))
    
    matches = await fetch_all("SELECT * FROM league_matches ORDER BY stage ASC, id ASC")
    
    msk_tz = timezone(timedelta(hours=3))
    now_msk = datetime.now(msk_tz)
    next_reset = get_next_league_reset()
    time_left = next_reset - now_msk
    h, rem = divmod(time_left.seconds, 3600)
    m, s = divmod(rem, 60)
    time_str = f"{time_left.days} дн. {h} ч. {m} мин."
    
    text = f"🏆 <b>WORLD CUP: СЕТКА ЛИГИ</b>\nВаша команда: <b>{my_team['name']}</b>\nВаши очки активности: <b>{my_team['score']} ⚔️</b>\n\n"
    
    stages = {1: "🟢 ЧЕТВЕРТЬФИНАЛ", 2: "🟡 ПОЛУФИНАЛ", 3: "🔴 ФИНАЛ"}
    current_stage = 0
    for m_data in matches:
        if m_data['stage'] != current_stage:
            current_stage = m_data['stage']
            text += f"\n{stages.get(current_stage, 'МАТЧИ')}:\n"
            
        t1 = await fetch_one("SELECT name, score FROM league_teams WHERE id = ?", (m_data['t1_id'],))
        t2 = await fetch_one("SELECT name, score FROM league_teams WHERE id = ?", (m_data['t2_id'],))
        n1 = f"{t1['name']} ({t1['score']}⚔️)" if t1 else "???"
        n2 = f"{t2['name']} ({t2['score']}⚔️)" if t2 else "???"
        
        if m_data['winner_id'] == 0:
            text += f"⚔️ {n1}  VS  {n2}\n"
        else:
            w_name = n1 if m_data['winner_id'] == m_data['t1_id'] else n2
            text += f"✅ <s>{t1['name'] if t1 else '?'}</s> VS <s>{t2['name'] if t2 else '?'}</s> (Победитель: <b>{w_name}</b>)\n"
            
    text += f"\n⏳ <b>Сброс и итоги:</b> каждые 2 дня в 00:00 МСК.\nСледующий сброс через: <b>{time_str}</b>\n"
    text += "\n<i>* Очки активности команд ⚔️ зарабатываются всеми участниками команды за победы в Cardball-Матче! Команда с наибольшим количеством очков в паре проходит дальше. Выбывшие получают утешительные призы.</i>"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👥 Состав команд", callback_data="fbleague_members")]])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "fbleague_members")
async def cb_fbleague_members(callback: types.CallbackQuery):
    teams = await fetch_all("SELECT id, name FROM league_teams")
    text = "👥 <b>СОСТАВ КОМАНД ЛИГИ:</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for t in teams:
        members = await fetch_all("SELECT id, username, first_name FROM users WHERE football_team_id = ?", (t['id'],))
        text += f"🏆 <b>{t['name']}</b>:\n"
        if not members:
            text += "  └ <i>Пусто</i>\n"
        else:
            for m in members:
                text += f"  └ 👤 {get_display_name(m)} (ID:{m['id']})\n"
        text += "\n"
        
    try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="fbleague_back")]]))
    except: pass
    await callback.answer()

@dp.callback_query(F.data == "fbleague_back")
async def cb_fbleague_back(callback: types.CallbackQuery):
    fake_msg = callback.message
    fake_msg.from_user = callback.from_user
    await cmd_fb_league(fake_msg)
    try: await callback.message.delete()
    except: pass
    await callback.answer()

@dp.callback_query(F.data.startswith("jointeam_"))
async def cb_jointeam(callback: types.CallbackQuery):
    t_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    count = await fetch_one("SELECT COUNT(*) as c FROM users WHERE football_team_id = ?", (t_id,))
    if count and count['c'] >= 2:
        return await callback.answer("Команда уже заполнена (Макс. 2)! Выберите другую.", show_alert=True)
        
    await execute_db("UPDATE users SET football_team_id = ? WHERE id = ?", (t_id, user_id))
    team = await fetch_one("SELECT name FROM league_teams WHERE id = ?", (t_id,))
    await callback.message.edit_text(f"✅ Вы успешно вступили в <b>{team['name']}</b>!")
    await callback.answer()

# ========================================================================
# ГАЙД ПО CARDBALL
# ========================================================================
@dp.message(F.text == BTN_FB_GUIDE)
async def cmd_fb_guide(message: types.Message):
    if await check_ban(message.from_user.id): return
    guide_text = (
        "📖 <b>ГАЙД ПО CARDBALL (ФУТБОЛЬНЫЙ РЕЖИМ)</b> ⚽\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Добро пожаловать в уникальный мини-режим Cardball! Это специальный футбольный ивент с отдельной механикой.\n\n"
        "<b>1. Разделение Инвентаря</b>\n"
        "В режиме Cardball вы выбиваете карты из специальных Футбольных Паков. Эти карты попадают в ваш **Футбольный Инвентарь** и экипируются в **Футбольный Состав**.\n"
        "Вы можете перенести футбольные карты в основной профиль через кнопку ✈️ Трансфер.\n\n"
        "<b>2. Состав Команды</b>\n"
        "Ваш состав должен состоять ровно из 4-х карт:\n"
        "🧤 [1] Вратарь\n"
        "🛡 [2] Защитник\n"
        "👟 [3] Полузащитник\n"
        "🏃‍♂️ [4] Нападающий\n\n"
        "<b>3. Механика Матча</b>\n"
        "В матче ваши карты соревнуются с картами ИИ. Мяч перемещается по полю от центра к воротам (-5 ... 0 ... +5).\n"
        "🔹 <i>Single (Убийца)</i> — рвется вперед с мячом.\n"
        "🔹 <i>Healer</i> — дает точные пасы и лечит команду.\n"
        "🔹 <i>Booster</i> — делает навесы и баффает силу удара.\n"
        "🔹 <i>AOE / Splash / Fire</i> — играют жестко, обходя защиту и нанося травмы!\n"
        "Если игрок теряет всё ХП, он получает <b>Травму 🟥</b> на несколько ходов и не участвует в игре.\n\n"
        "<b>4. Турнир (Лига)</b>\n"
        "Вступайте в одну из сборных. За каждую победу в Cardball-матче ваша сборная получает очки активности (⚔️). Каждые 2 дня подводятся итоги и лучшие команды проходят по сетке. Победители забирают грандиозные награды!\n"
    )
    await message.answer(guide_text)


# ========================================================================
# ФУТБОЛ-МАТЧ (CARDBALL ДВИЖОК С ВЫБОРОМ СЛОЖНОСТИ)
# ========================================================================
async def execute_fb_turn(atk_team, def_team, atk_name, def_name, log, force_attacker=None):
    for c in atk_team + def_team:
        if c.get('trauma', 0) > 0:
            c['trauma'] -= 1
            if c['trauma'] == 0:
                c['hp'] = int(c['max_hp'] * 0.5)
                log.append(f"🔄 <i>{c['name']} возвращается на поле после травмы!</i>")
                
    atk_alive = [c for c in atk_team if c['hp'] > 0 and c.get('trauma', 0) == 0]
    def_alive = [c for c in def_team if c['hp'] > 0 and c.get('trauma', 0) == 0]
    
    if not atk_alive: 
        log.append(f"❌ {atk_name}: Некому играть! Мяч переходит к противнику.")
        return 0, False 
        
    if not def_alive: 
        log.append(f"⚠️ {def_name}: Вся защита травмирована! Открытые ворота!")
        
    if force_attacker and force_attacker in atk_alive: atk = force_attacker
    else: atk = random.choice(atk_alive)
        
    base_dmg = atk['damage'] + atk.get('dmg_buff', 0)
    c_type = atk['class_type']
    
    pos_shift = 0
    goal_attempt = False
    
    if c_type == "Single":
        log.append(f"🏃‍♂️ {atk_name}: Форвард <b>{atk['name']}</b> рвется вперед!")
        pos_shift = 2
        goal_attempt = True
    elif c_type == "Healer":
        target = random.choice(atk_alive) if len(atk_alive)>1 else atk
        heal = int(base_dmg * 1.5)
        target['hp'] = min(target['max_hp'], target['hp'] + heal)
        log.append(f"👟 {atk_name}: <b>{atk['name']}</b> дает точный пас на <b>{target['name']}</b>, восстанавливая ему {heal} ХП!")
        pos_shift = 1
    elif c_type == "Booster":
        target = random.choice(atk_alive) if len(atk_alive)>1 else atk
        target['dmg_buff'] += int(atk['damage'] * atk['booster_dmg_mult'])
        log.append(f"🔋 {atk_name}: <b>{atk['name']}</b> делает навес на <b>{target['name']}</b>, сильно баффая его удар!")
        pos_shift = 1
    elif c_type == "AOE" or c_type == "Splash":
        log.append(f"🌪 {atk_name}: <b>{atk['name']}</b> финтит, обходя всю защиту!")
        for d in def_alive:
            d['hp'] -= int(base_dmg * 0.4)
            if d['hp'] <= 0: d['trauma'] = 2; log.append(f"🟥 <i>{d['name']} падает без сил!</i>")
        pos_shift = 2
    elif c_type == "Fire":
        log.append(f"🔥 {atk_name}: <b>{atk['name']}</b> играет грязно, нанося мощный урон с мячом!")
        if def_alive:
            tgt = random.choice(def_alive)
            tgt['hp'] -= base_dmg
            if tgt['hp'] <= 0: tgt['trauma'] = 2; log.append(f"🟥 <i>{tgt['name']} получает травму!</i>")
        pos_shift = 1
        
    if def_alive:
        defender = random.choice(def_alive)
        def_dmg = defender['damage'] + defender.get('dmg_buff', 0)
        
        log.append(f"🛡 {def_name}: <b>{defender['name']}</b> делает жесткий подкат!")
        atk['hp'] -= def_dmg
        if atk['hp'] <= 0:
            atk['trauma'] = 2
            log.append(f"💥 <b>Перехват!</b> {atk['name']} сбит с ног. Мяч переходит к {def_name}!")
            return 0, False 
    else:
        log.append(f"🛡 {def_name}: Никого нет на защите!")
        
    if goal_attempt:
        gk = def_team[0] 
        if gk['hp'] > 0 and gk.get('trauma', 0) == 0:
            if base_dmg > gk['hp']:
                gk['hp'] = max(1, gk['hp'] - base_dmg // 2) 
                log.append(f"⚽ <b>ГОООООЛ!</b> Удар силой {base_dmg} пробил вратаря {gk['name']} (ХП: {gk['hp']})!")
                return 1, False 
            else:
                gk['hp'] -= base_dmg
                if gk['hp'] <= 0: gk['trauma'] = 2
                log.append(f"🧤 <b>СЕЙВ!</b> Вратарь {gk['name']} ловит мяч силой {base_dmg}!")
                return 0, False 
        else:
            log.append(f"⚽ <b>ГОООООЛ!</b> Ворота были пусты!")
            return 1, False

    return pos_shift, True 

async def run_football_match(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_name: str, t1: list, t2: list, difficulty: float):
    battle_id = f"fb_{p1_id}_{int(time.time())}"
    surrendered_players.discard((p1_id, battle_id))
    
    try:
        msg = await bot.send_message(chat_id, f"⚽ Cardball Матч: <b>{p1_name}</b> VS <b>{p2_name}</b> начнется через 3 сек!")
        await asyncio.sleep(2)
        try: await msg.edit_text("⚽ Свисток арбитра! Матч начался!")
        except: pass
        
        turn = 1
        p1_goals = 0
        p2_goals = 0
        field_pos = 0 
        ball_owner = 1 
        log = []
        
        while turn <= 30 and p1_goals < 3 and p2_goals < 3:
            if (p1_id, battle_id) in surrendered_players:
                p2_goals = 3; break
                
            if field_pos >= 4:
                log.append(f"⚠️ {p1_name} у ворот противника!")
            elif field_pos <= -4:
                log.append(f"⚠️ {p2_name} у ворот противника!")
                
            if ball_owner == 1:
                shift, keeps_ball = await execute_fb_turn(t1, t2, p1_name, p2_name, log)
                if shift == 1 and keeps_ball == False: 
                    p1_goals += 1
                    field_pos = 0
                    ball_owner = 2
                else:
                    field_pos += shift
                    if not keeps_ball: ball_owner = 2
            else:
                shift, keeps_ball = await execute_fb_turn(t2, t1, p2_name, p1_name, log)
                if shift == 1 and keeps_ball == False: 
                    p2_goals += 1
                    field_pos = 0
                    ball_owner = 1
                else:
                    field_pos -= shift
                    if not keeps_ball: ball_owner = 1
                    
            field_pos = max(-5, min(5, field_pos))
            
            field_str = "['🥅'] " + " ".join(["⚽" if i == field_pos else "🟩" for i in range(-5, 6)]) + " ['🥅']"
            
            header = f"⚽ <b>СЧЁТ: {p1_goals} - {p2_goals}</b> (Ход {turn}/30)\n{field_str}\nМяч у: <b>{'🔵 ' + p1_name if ball_owner == 1 else '🔴 ' + p2_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
            
            if len(log) > 6: log = log[-6:]
            try: await msg.edit_text(header + "\n".join(log), reply_markup=get_battle_kb(battle_id))
            except Exception as e: 
                pass
            
            await asyncio.sleep(4.0)
            turn += 1
            
        if p1_goals > p2_goals: winner = p1_name
        elif p2_goals > p1_goals: winner = p2_name
        else: winner = "Ничья"
        
        final_text = f"🏁 <b>ФИНАЛЬНЫЙ СВИСТОК!</b>\nСчет: {p1_goals} - {p2_goals}\nПобедитель: <b>{winner}</b>\n\n"
        
        if winner == p1_name:
            balls = int(random.randint(15, 40) * difficulty)
            await execute_db("UPDATE users SET football_balls = football_balls + ?, football_trophies = football_trophies + 10 WHERE id = ?", (balls, p1_id))
            final_text += f"🎉 <b>Награды:</b>\n⚽ {balls} Мячей\n🏆 10 Футбольных Кубков\n"
            
            bp_xp = int(20 * difficulty)
            lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp, is_football=1)
            final_text += f"🎫 +{bp_xp} BP XP\n"
            if lvl_up:
                try: await bot.send_message(p1_id, f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> {new_lvl} уровень в сезоне «{bp_title}»!")
                except: pass
                
            user = await fetch_one("SELECT football_team_id FROM users WHERE id = ?", (p1_id,))
            if user and user['football_team_id'] > 0:
                await execute_db("UPDATE league_teams SET score = score + 5 WHERE id = ?", (user['football_team_id'],))
                final_text += f"\n📈 Ваша сборная получила +5 очков в Лиге (⚔️)!"
                
        elif winner == p2_name:
            await execute_db("UPDATE users SET football_trophies = MAX(0, football_trophies - 5) WHERE id = ?", (p1_id,))
            final_text += f"💀 Вы проиграли и потеряли 5 Футбольных Кубков.\n"
            
            bp_xp = int(5 * difficulty)
            lvl_up, bp_title, new_lvl = await add_bp_xp(p1_id, bp_xp, is_football=1)
            final_text += f"🎫 +{bp_xp} BP XP\n"
            if lvl_up:
                try: await bot.send_message(p1_id, f"🎉 <b>НОВЫЙ УРОВЕНЬ БП!</b> {new_lvl} уровень в сезоне «{bp_title}»!")
                except: pass
            
        try: await msg.edit_text(final_text, reply_markup=None)
        except: pass
        
    except Exception as e:
        logging.error(f"FB Match error: {e}")
    finally:
        active_combats.discard(p1_id)

@dp.message(F.text == BTN_FB_MATCH)
async def cmd_fb_match_select(message: types.Message):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats: return await message.answer("❌ Вы уже в игре!")
        
    team1 = await get_team_data(message.from_user.id, is_football=1)
    if len(team1) < 4: return await message.answer("❌ Для футбола нужно экипировать ровно 4 карты (Вратарь, Защитник, ПЗ, Нападающий)!")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Лёгкая команда (Меньше наград)", callback_data="fbdiff_easy")],
        [InlineKeyboardButton(text="🟡 Обычная команда (Стандарт)", callback_data="fbdiff_med")],
        [InlineKeyboardButton(text="🔴 Профи (+50% Мячей)", callback_data="fbdiff_hard")]
    ])
    await message.answer("⚽ <b>Выбор противника для Cardball-Матча:</b>\n", reply_markup=kb)

@dp.callback_query(F.data.startswith("fbdiff_"))
async def cb_fb_match_diff(callback: types.CallbackQuery):
    if callback.from_user.id in active_combats: return await callback.answer("Уже в бою!", show_alert=True)
    
    diff_type = callback.data.split("_")[1]
    
    team1 = await get_team_data(callback.from_user.id, is_football=1)
    if len(team1) < 4: return await callback.answer("Колода неполная!", show_alert=True)
    
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    rank = await get_user_rank(user['football_trophies'])
    
    power_mult = 1.0
    reward_mult = 1.0
    p2_name = "Сборная Ботов (Норм)"
    
    if diff_type == "easy":
        power_mult = 0.6; reward_mult = 0.5; p2_name = "Сборная Ботов (Лёгк)"
    elif diff_type == "hard":
        power_mult = 1.5; reward_mult = 1.5; p2_name = "Сборная Ботов (Хард)"
        
    team2 = await get_bot_team(callback.from_user.id, rank['difficulty_mult'] * power_mult, rank['name'], diff_type)
    
    title_str = await get_user_titles_str(callback.from_user.id)
    p1_name = get_display_name(user) + title_str
    
    active_combats.add(callback.from_user.id)
    await log_user_action(callback.from_user.id, f"Начал Cardball-Матч ({diff_type})")
    
    try: await callback.message.delete()
    except: pass
    
    asyncio.create_task(run_football_match(bot, callback.message.chat.id, callback.from_user.id, p1_name, p2_name, team1, team2, reward_mult))
    await callback.answer()

# ========================================================================
# ЗАПУСК БОТА
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
    asyncio.create_task(auto_backup_db())
    
    commands = [
        BotCommand(command="start", description="Главное меню / Main Menu"),
        BotCommand(command="help", description="Огромное руководство / Guide"),
        BotCommand(command="getcard", description="Выбить карту / Draw Card"),
        BotCommand(command="shop", description="Магазин / Shop"),
        BotCommand(command="inventory", description="Инвентарь / Inventory"),
        BotCommand(command="equip", description="Экипировка колоды / Equip Deck"),
        BotCommand(command="craft", description="Мастерская Крафта / Crafting"),
        BotCommand(command="profile", description="Профиль и статы / Profile & Stats"),
        BotCommand(command="trade", description="Обменяться картами / Trade Cards"),
        BotCommand(command="quests", description="Квесты / Quests"),
        BotCommand(command="index", description="Индекс всех карт / Card Index"),
        BotCommand(command="top", description="Рейтинг игроков / Leaderboard"),
        BotCommand(command="codereward", description="Активировать код / Redeem Code")
    ]
    await bot.set_my_commands(commands)
    
    logging.info("🤖 Карточный бот успешно перезапущен (Полный апдейт: Трейды, Крафты, Cardball)!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
