import asyncio
import logging
import random
import time
import io
import os
import math
import json
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

BOT_TOKEN = "7725898870:AAHa-6biiZkWuheNzjPl0Tun3XpNyLNq1lE"
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
    "Poison": "🧪",   # Изменено с Fire
    "Stunner": "⚡"   # Новый класс
}

CLASSES = list(CLASS_EMOJI.keys())

active_combats = set()
user_battle_mods = {}

# Обновленные шансы и цены в магазине
SHOP_PACKAGES = [
    ("1_rnd", "1 Случайная карта", 100, 20, 1.0),
    ("3_rnd", "3 Случайные карты", 275, 20, 1.0),
    ("5_rnd", "5 Случайных карт", 450, 20, 0.9),
    ("10_rnd", "10 Случайных карт", 900, 15, 0.8),
    ("25_rnd", "25 Случайных карт", 2300, 10, 0.7),
    ("50_rnd", "50 Случайных карт", 4500, 3, 0.6),
    ("100_rnd", "100 Случайных карт", 9000, 2, 0.4),
    ("rnd_leg", "Случайная Легендарная", 1750, 5, 0.7), 
    ("rnd_myth", "Случайная Мифическая", 20000, 3, 0.4), 
    ("rnd_sup", "Случайная Супер Карта", 150000, 1, 0.2) 
]

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
                robux INTEGER DEFAULT 0,
                is_vip INTEGER DEFAULT 0,
                x2_shekels INTEGER DEFAULT 0,
                extra_slot INTEGER DEFAULT 0
            )
        """)
        
        # Миграции
        cols_to_add = [
            ('q_cards_opened', 'INTEGER DEFAULT 0'), ('q_rare_obtained', 'INTEGER DEFAULT 0'),
            ('q_wins', 'INTEGER DEFAULT 0'), ('q_battles', 'INTEGER DEFAULT 0'),
            ('q_shop_buys', 'INTEGER DEFAULT 0'), ('pity_mythic', 'INTEGER DEFAULT 0'),
            ('pity_super', 'INTEGER DEFAULT 0'), ('robux', 'INTEGER DEFAULT 0'),
            ('is_vip', 'INTEGER DEFAULT 0'), ('x2_shekels', 'INTEGER DEFAULT 0'),
            ('extra_slot', 'INTEGER DEFAULT 0'), ('equip4', 'INTEGER DEFAULT 0')
        ]
        for col, ctype in cols_to_add:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} {ctype}")
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
        
        await db.execute("UPDATE cards SET class_type = 'Poison' WHERE class_type = 'Fire'")
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_id INTEGER,
                count INTEGER DEFAULT 1,
                mutation TEXT DEFAULT 'Normal',
                serial_number INTEGER DEFAULT 0
            )
        """)
        
        try: await db.execute("ALTER TABLE inventory ADD COLUMN mutation TEXT DEFAULT 'Normal'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE inventory ADD COLUMN serial_number INTEGER DEFAULT 0")
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
                luck_mult REAL DEFAULT 1.0,
                luck_end REAL DEFAULT 0,
                cd_mult REAL DEFAULT 1.0,
                cd_end REAL DEFAULT 0,
                shekel_mult REAL DEFAULT 1.0,
                shekel_end REAL DEFAULT 0,
                last_restock REAL DEFAULT 0,
                last_lb_reward REAL DEFAULT 0
            )
        """)
        
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN shekel_mult REAL DEFAULT 1.0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN shekel_end REAL DEFAULT 0")
        except aiosqlite.OperationalError: pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT,
                name TEXT,
                price INTEGER,
                stock INTEGER
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS donate_units (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER,
                price INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS global_event (
                id INTEGER PRIMARY KEY,
                command TEXT,
                type TEXT,
                goal INTEGER,
                current INTEGER DEFAULT 0,
                end_time REAL,
                is_active INTEGER DEFAULT 1,
                top_card_id INTEGER,
                part_shekels INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS event_donations (
                user_id INTEGER,
                amount INTEGER,
                PRIMARY KEY (user_id)
            )
        """)

        await db.execute("CREATE TABLE IF NOT EXISTS admin_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY)")
        await db.execute("CREATE TABLE IF NOT EXISTS lb_rewards (id INTEGER PRIMARY KEY AUTOINCREMENT, bracket TEXT, reward_type TEXT, amount INTEGER DEFAULT 0, card_id INTEGER DEFAULT 0, mutation TEXT DEFAULT 'Normal')")
        
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

class EventLuck(StatesGroup):
    mult = State()
    mins = State()

class EventCD(StatesGroup):
    mult = State()
    mins = State()

class EventShekel(StatesGroup):
    mult = State()
    mins = State()

class AdminGlobalEvent(StatesGroup):
    cmd = State()
    etype = State()
    goal = State()
    mins = State()
    top_card_id = State()
    part_shekels = State()

class AdminDonateUnit(StatesGroup):
    card_id = State()
    price = State()

class PvPState(StatesGroup):
    waiting_target = State()

def get_display_name(user_data: dict) -> str:
    if user_data.get('username'): return f"@{user_data['username']}"
    elif user_data.get('first_name'): return user_data['first_name']
    return f"Игрок {user_data.get('id', '???')}"

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
        try:
            await bot.send_message(user_id, "🎉 <b>ПОЗДРАВЛЯЕМ!</b>\nВы выполнили все ежедневные квесты и получили <b>900 💰 Шекелей</b>!\nВозвращайтесь через 1 час за новыми заданиями!")
        except: pass

async def is_admin(user_id: int) -> bool:
    if user_id == SUPER_ADMIN_ID: return True
    res = await fetch_one("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
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

async def broadcast_message(text: str):
    users = await fetch_all("SELECT id FROM users WHERE banned = 0")
    success = 0
    for u in users:
        try:
            await bot.send_message(u['id'], text)
            success += 1
            await asyncio.sleep(0.05)
        except: pass
    await notify_super_admin(f"📢 <b>Рассылка завершена.</b>\nДоставлено: {success}/{len(users)}")

def get_main_keyboard(is_adm: bool = False):
    kb = [
        [KeyboardButton(text="🎴 Выбить карту"), KeyboardButton(text="⚔️ Поиск боя (боты)")],
        [KeyboardButton(text="🎒 Инвентарь"), KeyboardButton(text="🛡 Экипировка")],
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="💎 Донат Магазин")],
        [KeyboardButton(text="⚔️ PvP Дуэль"), KeyboardButton(text="🏆 Топ игроков")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="📜 Квесты")],
        [KeyboardButton(text="📖 Индекс"), KeyboardButton(text="🆘 Помощь (/help)")]
    ]
    if is_adm: kb.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_user_rank(trophies: int):
    ranks = await fetch_all("SELECT * FROM ranks ORDER BY min_trophies DESC")
    for r in ranks:
        if trophies >= r['min_trophies']: return r
    return {"name": "Bronze I", "difficulty_mult": 0.8, "reward_mult": 1.0}

async def get_active_events(user_id=None):
    settings = await fetch_one("SELECT * FROM server_settings WHERE id = 1")
    now = time.time()
    luck = settings['luck_mult'] if settings['luck_end'] > now else 1.0
    cd = settings['cd_mult'] if settings['cd_end'] > now else 1.0
    sh_mult = settings['shekel_mult'] if settings['shekel_end'] > now else 1.0
    
    if user_id:
        u = await fetch_one("SELECT is_vip FROM users WHERE id = ?", (user_id,))
        if u and u['is_vip']:
            luck *= 1.10
            
    return luck, cd, sh_mult

def roll_mutation(luck_mult: float = 1.0):
    r = random.random()
    # Удача теперь влияет на мутации!
    rb_chance = 0.02 * luck_mult
    gold_chance = 0.12 * luck_mult
    if r <= rb_chance: return "Rainbow"
    if r <= rb_chance + gold_chance: return "Gold"
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
            res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = -1", (user_id, card_id, mutation))
            inv_item = await res.fetchone()
            if inv_item:
                await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                return inv_item['id'], -1, False
            else:
                cursor = await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, 1, ?, -1)", (user_id, card_id, mutation))
                return cursor.lastrowid, -1, True

        if needs_serial_number(rarity, mutation):
            res = await db.execute("SELECT MAX(serial_number) as m FROM inventory WHERE card_id = ? AND mutation = ?", (card_id, mutation))
            row = await res.fetchone()
            curr_max = row['m'] if (row and row['m'] is not None) else 0
            new_serial = curr_max + 1
            
            cursor = await db.execute(
                "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, 1, ?, ?)", 
                (user_id, card_id, mutation, new_serial)
            )
            return cursor.lastrowid, new_serial, True
        else:
            res = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0", (user_id, card_id, mutation))
            inv_item = await res.fetchone()
            if inv_item:
                await db.execute("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
                return inv_item['id'], 0, False
            else:
                cursor = await db.execute(
                    "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, 1, ?, 0)", 
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
    r_em = RARITY_EMOJI.get(c['rarity'], "⚪")
    c_em = CLASS_EMOJI.get(c['class_type'], "🎯")
    name = f"{r_em} {c_em} <b>{c['name']}</b>"
    if c.get('serial_number', 0) > 0:
        name += f" <b>[#{c['serial_number']:04d}]</b>"
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

async def give_multiple_cards(user_id: int, count: int) -> list:
    luck_mult, cd_mult, sh_mult = await get_active_events(user_id)
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
        elif pm + 1 >= 700 and card['rarity'] not in ['Mythic', 'Super'] and mythic_cards:
            card = random.choice(mythic_cards)
            is_pity = True
            p_type = 'Mythic'

        if card['rarity'] == 'Super': 
            ps = 0; pm += 1
        elif card['rarity'] == 'Mythic': 
            pm = 0; ps += 1
        else: 
            ps += 1; pm += 1

        mut = roll_mutation(luck_mult)
        _, serial, _ = await give_card_to_user(user_id, card['id'], mut, card['rarity'])

        c_copy = dict(card)
        c_copy['mutation'] = mut
        c_copy['serial_number'] = serial
        c_copy['is_pity'] = is_pity
        c_copy['pity_type'] = p_type
        results.append(c_copy)

    await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
    return results

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
        asyncio.create_task(broadcast_message("🛒 <b>ГЛОБАЛЬНЫ МАГАЗИН ОБНОВИЛСЯ!</b>\nЗавезли свежие наборы карт. Количество строго ограничено, успей купить!\n\nИспользуй кнопку в меню или /shop"))

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

async def global_event_task():
    while True:
        try:
            db = await get_db_connection()
            async with db.execute("SELECT * FROM global_event WHERE is_active = 1") as cursor:
                evs = await cursor.fetchall()
            
            now = time.time()
            for ev in evs:
                if now >= ev['end_time'] or ev['current'] >= ev['goal']:
                    await db.execute("UPDATE global_event SET is_active = 0 WHERE id = ?", (ev['id'],))
                    
                    # Распределение наград
                    async with db.execute("SELECT * FROM event_donations ORDER BY amount DESC") as c_donations:
                        donators = await c_donations.fetchall()
                    
                    if donators:
                        top1 = donators[0]['user_id']
                        if ev['top_card_id'] > 0:
                            _, _, _ = await give_card_to_user(top1, ev['top_card_id'], roll_mutation(1.0))
                            try: await bot.send_message(top1, "🎉 <b>ГЛОБАЛЬНЫЙ ИВЕНТ ОКОНЧЕН!</b>\nВы заняли 1-е место и получаете эксклюзивную карточку!")
                            except: pass
                        
                        for d in donators[1:]:
                            if ev['part_shekels'] > 0:
                                await db.execute("UPDATE users SET coins = coins + ? WHERE id = ?", (ev['part_shekels'], d['user_id']))
                                try: await bot.send_message(d['user_id'], f"🎉 <b>ГЛОБАЛЬНЫЙ ИВЕНТ ОКОНЧЕН!</b>\nВы получили утешительный приз: {ev['part_shekels']} 💰")
                                except: pass
                                
                    await db.execute("DELETE FROM event_donations")
                    await broadcast_message(f"🏁 <b>Глобальный Ивент /{ev['command']} завершён!</b> Награды выданы участникам.")
            await db.commit()
            await db.close()
        except Exception as e:
            logging.error(f"Global Event Error: {e}")
        await asyncio.sleep(10)

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
                            try:
                                await bot.send_message(user['id'], msg_text)
                            except: pass
                            
                await execute_db("UPDATE server_settings SET last_lb_reward = ? WHERE id = 1", (now,))
        except Exception as e:
            logging.error(f"LB Rewards error: {e}")
        await asyncio.sleep(600)

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

    adm = await is_admin(message.from_user.id)
    await message.answer(
        "👋 <b>Добро пожаловать в Card Battle Bot!</b>\n\n"
        "Собери свою колоду уникальных юнитов, выставляй их в бой и поднимай кубки!\n\n"
        "Используй меню снизу для навигации.",
        reply_markup=get_main_keyboard(adm)
    )

@dp.message(Command("profile"), F.chat.type == "private")
@dp.message(F.text == "👤 Профиль")
async def cmd_profile(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    rank = await get_user_rank(user['trophies'])
    total_cards = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE user_id = ?", (user['id'],))
    name = get_display_name(user)
    
    vip_str = "🌟 <b>VIP Статус: Активен</b>\n" if user['is_vip'] else ""
    x2_str = "💰 <b>Множитель Шекелей: x2 (Навсегда)</b>\n" if user['x2_shekels'] else ""
    
    text = (
        f"👤 <b>Профиль игрока {name}</b>\n\n"
        f"{vip_str}{x2_str}"
        f"🎖 <b>Ранг:</b> {rank['name']}\n"
        f"🏆 <b>Кубки:</b> {user['trophies']}\n"
        f"💰 <b>Шекели:</b> {user['coins']}\n"
        f"🪙 <b>Робуксы:</b> {user['robux']}\n"
        f"🃏 <b>Всего карт:</b> {total_cards['s'] or 0}\n\n"
        f"🔮 <b>Pity (Мифик):</b> {user['pity_mythic']}/700\n"
        f"🌠 <b>Pity (Супер):</b> {user['pity_super']}/10000\n\n"
        f"⚔️ <b>Экипировка:</b>\n"
    )
    
    slots = ['equip1', 'equip2', 'equip3']
    if user['extra_slot']: slots.append('equip4')
    
    for i, slot in enumerate(slots, 1):
        if user[slot] != 0:
            card = await fetch_one("SELECT name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE id = ?", (user[slot],))
            if card:
                invs = await fetch_all("SELECT mutation FROM inventory WHERE user_id = ? AND card_id = ?", (user['id'], user[slot]))
                muts = [item['mutation'] for item in invs]
                mult = 1.0
                mut_str = ""
                if "Rainbow" in muts: mult = 1.2; mut_str = " 🌈"
                elif "Gold" in muts: mult = 1.1; mut_str = " ⭐"
                
                n = format_card_name(card)
                if card['class_type'] == 'Booster': 
                    text += f"{i}. {n}{mut_str} (DMG x{round(card['booster_dmg_mult']*mult, 2)} | HP x{round(card['booster_hp_mult']*mult, 2)})\n"
                else: 
                    text += f"{i}. {n}{mut_str} (⚔️{int(card['damage']*mult)} | ❤️{int(card['hp']*mult)})\n"
            else: text += f"{i}. [Пусто]\n"
        else: text += f"{i}. [Пусто]\n"
            
    await message.answer(text)

@dp.message(F.text == "💎 Донат Магазин")
@dp.message(Command("donate"))
async def cmd_donate(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins, robux, is_vip, x2_shekels, extra_slot FROM users WHERE id = ?", (message.from_user.id,))
    
    text = (
        f"💎 <b>ДОНАТ МАГАЗИН</b>\n\n"
        f"💰 Шекели: {user['coins']}\n"
        f"🪙 Робуксы: {user['robux']}\n\n"
        f"<i>Здесь вы можете приобрести эксклюзивные функции и юнитов за Робуксы!</i>"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🪙 Купить 1 Робукс (500 Шекелей)", callback_data="don_buy_rbx")],
        [InlineKeyboardButton(text="💰 x2 Шекели навсегда (199 R$)", callback_data="don_buy_x2")],
        [InlineKeyboardButton(text="🌟 VIP Статус (399 R$)", callback_data="don_buy_vip")],
        [InlineKeyboardButton(text="🛡 +1 Слот Экипировки (449 R$)", callback_data="don_buy_slot")],
        [InlineKeyboardButton(text="🃏 Уникальные Юниты", callback_data="don_units_menu")]
    ])
    
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "don_buy_rbx")
async def don_buy_rbx(callback: types.CallbackQuery):
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (callback.from_user.id,))
    if user['coins'] < 500: return await callback.answer("❌ Недостаточно шекелей! Нужно 500.", show_alert=True)
    await execute_db("UPDATE users SET coins = coins - 500, robux = robux + 1 WHERE id = ?", (callback.from_user.id,))
    await callback.answer("✅ Вы купили 1 Робукс за 500 шекелей!", show_alert=True)
    await cmd_donate(callback.message)
    await callback.message.delete()

@dp.callback_query(F.data.startswith("don_buy_"))
async def don_buy_features(callback: types.CallbackQuery):
    feature = callback.data.split("_")[2]
    user = await fetch_one("SELECT robux, is_vip, x2_shekels, extra_slot FROM users WHERE id = ?", (callback.from_user.id,))
    
    costs = {'x2': 199, 'vip': 399, 'slot': 449}
    db_fields = {'x2': 'x2_shekels', 'vip': 'is_vip', 'slot': 'extra_slot'}
    names = {'x2': 'x2 Шекели', 'vip': 'VIP Статус', 'slot': '+1 Слот Экипировки'}
    
    if feature in costs:
        if user[db_fields[feature]]: return await callback.answer(f"❌ У вас уже есть {names[feature]}!", show_alert=True)
        if user['robux'] < costs[feature]: return await callback.answer(f"❌ Нужно {costs[feature]} Робуксов!", show_alert=True)
        
        await execute_db(f"UPDATE users SET robux = robux - ?, {db_fields[feature]} = 1 WHERE id = ?", (costs[feature], callback.from_user.id))
        await callback.answer(f"✅ Успешно приобретено: {names[feature]}!", show_alert=True)
        await cmd_donate(callback.message)
        await callback.message.delete()

@dp.callback_query(F.data == "don_units_menu")
async def don_units_menu(callback: types.CallbackQuery):
    units = await fetch_all("SELECT d.id, d.price, c.name, c.rarity FROM donate_units d JOIN cards c ON d.card_id = c.id")
    if not units: return await callback.answer("❌ В донат магазине пока нет юнитов.", show_alert=True)
    
    kb = []
    for u in units:
        kb.append([InlineKeyboardButton(text=f"🃏 {u['name']} — {u['price']} R$", callback_data=f"don_buy_unit_{u['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="don_back_main")])
    
    await callback.message.edit_text("💎 <b>Эксклюзивные Донат Юниты</b>\n<i>При покупке: 20% шанс на Gold, 10% на Rainbow!</i>", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data == "don_back_main")
async def don_back_main(callback: types.CallbackQuery):
    await cmd_donate(callback.message)
    await callback.message.delete()

@dp.callback_query(F.data.startswith("don_buy_unit_"))
async def don_buy_unit(callback: types.CallbackQuery):
    d_id = int(callback.data.split("_")[3])
    user = await fetch_one("SELECT robux FROM users WHERE id = ?", (callback.from_user.id,))
    item = await fetch_one("SELECT card_id, price FROM donate_units WHERE id = ?", (d_id,))
    
    if not item: return await callback.answer("❌ Товар не найден.", show_alert=True)
    if user['robux'] < item['price']: return await callback.answer("❌ Недостаточно Робуксов!", show_alert=True)
    
    await execute_db("UPDATE users SET robux = robux - ? WHERE id = ?", (item['price'], callback.from_user.id))
    
    # 20% gold, 10% rainbow, 70% normal
    r = random.random()
    mut = "Rainbow" if r <= 0.10 else ("Gold" if r <= 0.30 else "Normal")
    
    _, serial, _ = await give_card_to_user(callback.from_user.id, item['card_id'], mut)
    card = await fetch_one("SELECT name FROM cards WHERE id = ?", (item['card_id'],))
    
    await callback.answer("✅ Успешно куплено!", show_alert=True)
    mut_str = "🌈" if mut == 'Rainbow' else ("⭐" if mut == 'Gold' else "")
    s_str = f" [#{serial:04d}]" if serial > 0 else ""
    await callback.message.answer(f"💎 <b>Покупка из Донат Магазина!</b>\nВы получили: 🃏 {mut_str} {card['name']}{s_str}")

@dp.message(Command("quests"))
@dp.message(F.text == "📜 Квесты")
async def cmd_quests(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    now = time.time()
    if user['quests_cooldown'] > now:
        left = int(user['quests_cooldown'] - now)
        m, s = divmod(left, 60)
        return await message.answer(f"⏳ <b>Квесты выполнены!</b>\nНовые задания появятся через {m} мин. {s} сек.")
    
    c_op = min(10, user['q_cards_opened'])
    r_ob = min(1, user['q_rare_obtained'])
    w_win = min(3, user['q_wins'])
    b_pl = min(5, user['q_battles'])
    s_bu = min(1, user['q_shop_buys'])
    
    text = (
        "📜 <b>ЕЖЕДНЕВНЫЕ КВЕСТЫ</b>\n"
        "<i>Выполни все задания, чтобы получить 900 💰 Шекелей!</i>\n\n"
        f"1️⃣ Открой 10 карточек: {c_op}/10 {'✅' if c_op>=10 else '❌'}\n"
        f"2️⃣ Получи редкую карточку: {r_ob}/1 {'✅' if r_ob>=1 else '❌'}\n"
        f"3️⃣ Победи в бою 3 раза: {w_win}/3 {'✅' if w_win>=3 else '❌'}\n"
        f"4️⃣ Сыграй в катку 5 раз: {b_pl}/5 {'✅' if b_pl>=5 else '❌'}\n"
        f"5️⃣ Купи любую карточку: {s_bu}/1 {'✅' if s_bu>=1 else '❌'}\n"
    )
    await message.answer(text)

@dp.message(Command("top"))
@dp.message(F.text == "🏆 Топ игроков")
async def cmd_top(message: types.Message):
    if await check_ban(message.from_user.id): return
    top_users = await fetch_all("SELECT username, first_name, id, trophies FROM users ORDER BY trophies DESC LIMIT 20")
    
    text = "🏆 <b>Топ 20 игроков сервера:</b>\n\n"
    for i, u in enumerate(top_users, 1):
        name = get_display_name(u)
        rank = await get_user_rank(u['trophies'])
        text += f"{i}. {name} — <b>{u['trophies']} 🏆</b> ({rank['name']})\n"
        
    await message.answer(text)

@dp.message(Command("shop"))
@dp.message(F.text == "🛒 Магазин")
async def cmd_shop(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins, is_vip FROM users WHERE id = ?", (message.from_user.id,))
    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    
    if not items:
        return await message.answer("🛒 Магазин пока пуст. Ближайший завоз скоро!")
        
    text = f"🛒 <b>Глобальный Магазин</b>\n💰 Твой баланс: {user['coins']} шекелей\n"
    if user['is_vip']: text += "🌟 <b>Скидка VIP: -10%</b>\n"
    text += "\n"
    
    kb = []
    for i, item in enumerate(items, 1):
        price = int(item['price'] * 0.9) if user['is_vip'] else item['price']
        text += f"📦 <b>{item['name']}</b>\n💵 Цена: <b>{price} 💰</b>\n📉 Осталось в мире: {item['stock']} шт.\n\n"
        kb.append([InlineKeyboardButton(text=f"Купить: {item['name']} ({price} 💰)", callback_data=f"buy_shop_{item['id']}")])
        
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_shop_"))
async def callback_buy_shop(callback: types.CallbackQuery):
    shop_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT coins, pity_mythic, pity_super, is_vip FROM users WHERE id = ?", (user_id,))
    item = await fetch_one("SELECT * FROM shop_items WHERE id = ?", (shop_id,))
    
    if not item or item['stock'] <= 0: return await callback.answer("❌ Этот товар закончился!", show_alert=True)
    
    price = int(item['price'] * 0.9) if user['is_vip'] else item['price']
    if user['coins'] < price: return await callback.answer("❌ Недостаточно шекелей!", show_alert=True)
    
    await execute_db("UPDATE users SET coins = coins - ? WHERE id = ?", (price, user_id))
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
                msg = f"🌟 <b>ЖАЛОСТЬ СРАБОТАЛА! Гарантированный {won[0]['pity_type']}!</b> 🌟\n\n" + msg
        else: 
            msg = f"🛍 <b>Успешно! Вы открыли пак из {count} карт!</b>\nПосмотрите новинки в 🎒 Инвентаре."
            if pity_pulls:
                p_names = ", ".join([f"{c['name']} (Pity {c['pity_type']})" for c in pity_pulls])
                msg += f"\n\n🌟 <b>Сработала ЖАЛОСТЬ! Получены гарантированные карты:</b>\n{p_names}!"
                
        await callback.message.answer(msg)
        
    elif i_type.startswith("rnd_"):
        rarity_map = {"rnd_leg": "Legendary", "rnd_myth": "Mythic", "rnd_sup": "Super"}
        target_rarity = rarity_map[i_type]
        
        all_cards = await fetch_all("SELECT * FROM cards WHERE rarity = ?", (target_rarity,))
        if not all_cards:
            await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (price, user_id))
            return await callback.message.answer("❌ Ошибка: В базе нет карт такой редкости! Шекели возвращены.")
            
        won_card = random.choice(all_cards)
        luck_mult, _, _ = await get_active_events(user_id)
        mut = roll_mutation(luck_mult)
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        won_card['serial_number'] = serial
        
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
        await callback.message.answer(f"🛍 <b>Покупка успешна!</b>\nГарантированная редкость {target_rarity}!\nВы выбили: {format_card_name(won_card)}\nМутация: {mut_str}")

    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    if not items:
        await callback.message.edit_text("🛒 <b>Магазин полностью распродан!</b>\nЖдите следующего завоза.")
    else:
        new_coins = user['coins'] - price
        text = f"🛒 <b>Глобальный Магазин</b>\n💰 Твой баланс: {new_coins} шекелей\n"
        if user['is_vip']: text += "🌟 <b>Скидка VIP: -10%</b>\n"
        text += "\n"
        kb = []
        for i, itm in enumerate(items, 1):
            itm_price = int(itm['price'] * 0.9) if user['is_vip'] else itm['price']
            text += f"📦 <b>{itm['name']}</b>\n💵 Цена: <b>{itm_price} 💰</b>\n📉 Осталось в мире: {itm['stock']} шт.\n\n"
            kb.append([InlineKeyboardButton(text=f"Купить: {itm['name']} ({itm_price} 💰)", callback_data=f"buy_shop_{itm['id']}")])
        try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        except: pass
    
    await callback.answer()

@dp.message(Command("getcard"))
@dp.message(F.text == "🎴 Выбить карту")
async def cmd_getcard(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    luck_mult, cd_mult, _ = await get_active_events(user['id'])
    base_cooldown = 4 * 60
    actual_cooldown = int(base_cooldown / cd_mult)
    
    now = time.time()
    passed = now - user['last_getcard']
    
    if passed < actual_cooldown:
        left = int(actual_cooldown - passed)
        mins, secs = divmod(left, 60)
        return await message.answer(f"⏳ <b>Колода перемешивается!</b>\nВозвращайся через {mins} мин. {secs} сек.")
        
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
    if mutation == "Gold": mut_str = "⭐ <b>ЗОЛОТАЯ! (+10% Статов)</b>\n"
    elif mutation == "Rainbow": mut_str = "🌈 <b>РАДУЖНАЯ! (+20% Статов)</b>\n"
    
    msg = ""
    if won_card.get('is_pity'):
        msg += f"🌟 <b>СИСТЕМА PITY СРАБОТАЛА! ГАРАНТИРОВАННЫЙ {won_card['pity_type']}!</b> 🌟\n\n"
        
    msg += f"🎉 <b>ВЫ ВЫБИЛИ КАРТУ!</b>\n\n{mut_str}🃏 {n_fmt}\n💎 <b>Редкость:</b> {rarity_text}\n"
    
    if won_card['class_type'] == 'Booster': 
        msg += f"✨ <b>БУСТЕР</b>\n⚔️ Урон: x{round(won_card['booster_dmg_mult']*mult, 2)} | ❤️ ХП: x{round(won_card['booster_hp_mult']*mult, 2)}\n\n"
    else: 
        msg += f"⚔️ <b>Урон:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n\n"
        
    if luck_mult > 1.0 and won_card['drop_chance'] < 15.0:
        msg += f"🍀 <i>Сработал ивент (или VIP) удачи!</i>"
        
    await message.answer_photo(photo=won_card['photo_id'], caption=msg)

async def get_index_text(user_id: int, page: int = 0, items_per_page: int = 8):
    all_cards = await fetch_all("SELECT * FROM cards")
    user_inv = await fetch_all("SELECT DISTINCT card_id FROM inventory WHERE user_id = ?", (user_id,))
    user_card_ids = [item['card_id'] for item in user_inv]
    
    if not all_cards: return "Индекс пуст.", None
    
    luck_mult, _, _ = await get_active_events(user_id)
    weights_dict, total_w = await calculate_chance_weights(luck_mult)
    
    def index_sort_key(c):
        if c['rarity'] == 'Leaderboard': return -1
        return weights_dict.get(c['id'], 9999)
        
    all_cards.sort(key=index_sort_key)
    
    total_pages = max(1, math.ceil(len(all_cards) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    
    text = f"📖 <b>Мировой Индекс Карт (Стр. {page+1}/{total_pages})</b>\n"
    if luck_mult > 1.0: text += f"🍀 <b>ИВЕНТ УДАЧИ АКТИВЕН (x{luck_mult})! Шансы пересчитаны!</b>\n"
    text += "\n"
    
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
            
        mut_str = f"\n  └ <i>Из них: {', '.join(mut_texts)}</i>" if mut_texts else ""
        
        n_fmt = format_card_name(c).replace(" <b>[#-001]</b>", "") 
        r_fmt = format_rarity_display(c['rarity'])
        
        real_chance = (weights_dict.get(c['id'], 0) / total_w) * 100 if total_w > 0 else 0
        chance_str = f"Шанс выпадения: {real_chance:.4f}%" if c['rarity'] != 'Leaderboard' else "Только эксклюзив!"
        
        if c['id'] in user_card_ids:
            text += f"{i}. {n_fmt}\n"
            text += f"💎 {r_fmt} ({chance_str})\n"
            if c['class_type'] == 'Booster': text += f"✨ Бафф: DMG x{c['booster_dmg_mult']} // HP x{c['booster_hp_mult']}\n"
            else: text += f"⚔️ Урон: {c['damage']} // ❤️ Здоровье: {c['hp']}\n"
            text += f"🌍 Существует: {total_exists} шт.{mut_str}\n\n"
        else:
            text += f"{i}. <b>???</b> (У вас нет этой карты)\n"
            text += f"💎 {r_fmt} ({chance_str})\n"
            text += f"🌍 Существует: {total_exists} шт.{mut_str}\n\n"
            
    kb = []
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"idx_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"idx_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("index"))
@dp.message(F.text == "📖 Индекс")
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
        SELECT c.id, c.name, c.rarity, c.class_type, i.count, i.mutation, i.serial_number 
        FROM inventory i JOIN cards c ON i.card_id = c.id 
        WHERE i.user_id = ?
    """, (user_id,))
    
    if not inv: return "🎒 Ваш инвентарь пуст. Используйте /getcard", None
        
    rarity_weight = {"Leaderboard": 9, "Exclusive": 8, "Super": 7, "Mythic": 6, "Legendary": 5, "Epic": 4, "Rare": 3, "Uncommon": 2, "Basic": 1}
    mutation_weight = {"Rainbow": 3, "Gold": 2, "Normal": 1}
    
    inv.sort(key=lambda x: (rarity_weight.get(x['rarity'], 0), mutation_weight.get(x['mutation'], 0), x['id']), reverse=True)
    
    total_pages = max(1, math.ceil(len(inv) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = inv[start_idx:end_idx]
    
    text = f"🎒 <b>Ваш Инвентарь (Стр. {page+1}/{total_pages}):</b>\n\n"
    for item in page_items:
        n_fmt = format_card_name(item).replace(" <b>[#-001]</b>", "")
        mut_emoji = ""
        if item['mutation'] == "Gold": mut_emoji = "⭐ "
        elif item['mutation'] == "Rainbow": mut_emoji = "🌈 "
        text += f"• {mut_emoji}{n_fmt} — {item['count']} шт.\n"
        
    kb = []
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"inv_page_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"inv_page_{page+1}"))
    if nav_row: kb.append(nav_row)
    
    return text, InlineKeyboardMarkup(inline_keyboard=kb) if kb else None

@dp.message(Command("inventory"))
@dp.message(F.text == "🎒 Инвентарь")
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

def get_equip_main_keyboard(user_info, cards_info):
    kb = []
    slots = ['equip1', 'equip2', 'equip3']
    if user_info['extra_slot']: slots.append('equip4')
    
    for i, slot in enumerate(slots, 1):
        c_id = user_info[slot]
        text = f"Слот {i} [Пусто]" if c_id == 0 else f"Слот {i} [{cards_info.get(c_id, f'ID: {c_id}')}]"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"eq_select_{i}")])
    kb.append([InlineKeyboardButton(text="❌ Снять всё", callback_data="eq_clear")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("equip"))
@dp.message(F.text == "🛡 Экипировка")
async def cmd_equip(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4, extra_slot FROM users WHERE id = ?", (message.from_user.id,))
    c_ids = [c for c in [user['equip1'], user['equip2'], user['equip3'], user['equip4']] if c != 0]
    cards_info = {}
    if c_ids:
        c_list = ",".join(map(str, c_ids))
        res = await fetch_all(f"SELECT id, name FROM cards WHERE id IN ({c_list})")
        for r in res: cards_info[r['id']] = r['name']
    await message.answer("🛡 <b>Настройка Боевой Колоды</b>\n\nНажмите на слот (мутации применяются автоматически):", reply_markup=get_equip_main_keyboard(user, cards_info))

@dp.callback_query(F.data.startswith("eq_select_"))
async def equip_slot_callback(callback: types.CallbackQuery, state: FSMContext):
    slot_num = int(callback.data.split("_")[2])
    inv = await fetch_all("""
        SELECT DISTINCT c.id, c.name, c.rarity, c.class_type
        FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.user_id = ?
    """, (callback.from_user.id,))
    if not inv: return await callback.answer("У вас нет карт!", show_alert=True)
    
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']}"} for c in inv]
    await state.update_data(equip_slot=slot_num, equip_items=items)
    kb = get_pagination_keyboard(items, 0, "eq_set", columns=1, items_per_page=8)
    await callback.message.edit_text(f"👇 Выберите карту для <b>Слота {slot_num}</b>:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_set_page_"))
async def equip_paginate_callback(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('equip_items', []), page, "eq_set", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_set_"))
async def equip_set_callback(callback: types.CallbackQuery, state: FSMContext):
    if "page" in callback.data: return 
    card_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    slot_num = data.get('equip_slot', 1)
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4 FROM users WHERE id = ?", (callback.from_user.id,))
    if card_id in [user['equip1'], user['equip2'], user['equip3'], user['equip4']]:
        return await callback.answer("❌ Уже экипирована!", show_alert=True)
    await execute_db(f"UPDATE users SET equip{slot_num} = ? WHERE id = ?", (card_id, callback.from_user.id))
    card = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
    await callback.message.edit_text(f"✅ Карта <b>{card['name']}</b> установлена в Слот {slot_num}!")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "eq_clear")
async def equip_clear_callback(callback: types.CallbackQuery):
    await execute_db("UPDATE users SET equip1=0, equip2=0, equip3=0, equip4=0 WHERE id = ?", (callback.from_user.id,))
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4, extra_slot FROM users WHERE id = ?", (callback.from_user.id,))
    await callback.message.edit_text("✅ Все слоты очищены.", reply_markup=get_equip_main_keyboard(user, {}))
    await callback.answer()

async def get_team_data(user_id: int):
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4, extra_slot FROM users WHERE id = ?", (user_id,))
    team = []
    slots = ['equip1', 'equip2', 'equip3']
    if user['extra_slot']: slots.append('equip4')
    
    for slot in slots:
        if user[slot] != 0:
            card = await fetch_one("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE id = ?", (user[slot],))
            if card:
                invs = await fetch_all("SELECT mutation, serial_number FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, card['id']))
                muts = [i['mutation'] for i in invs]
                mult = 1.0
                mut_type = "Normal"
                if "Rainbow" in muts: mult = 1.2; mut_type = "Rainbow"
                elif "Gold" in muts: mult = 1.1; mut_type = "Gold"
                
                best_serial = 0
                for item in invs:
                    if item['mutation'] == mut_type and item['serial_number'] > 0:
                        best_serial = item['serial_number']
                        break
                
                card['damage'] = int(card['damage'] * mult)
                card['hp'] = int(card['hp'] * mult)
                if card['class_type'] == 'Booster':
                    card['booster_dmg_mult'] = round(card['booster_dmg_mult'] * mult, 2)
                    card['booster_hp_mult'] = round(card['booster_hp_mult'] * mult, 2)
                    
                card['mutation'] = mut_type
                card['serial_number'] = best_serial
                card['max_hp'] = card['hp']
                card['poison'] = 0     
                card['dmg_buff'] = 0 
                card['stun'] = 0
                team.append(card)
    return team

async def get_bot_team(user_id: int, difficulty_mult: float, rank_name: str, has_extra_slot: bool = False):
    all_cards = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE rarity != 'Leaderboard'")
    if len(all_cards) < 3: return []
    
    by_rarity = {}
    for c in all_cards:
        by_rarity.setdefault(c['rarity'], []).append(c)
        
    base_rank = rank_name.split()[0]
    team_selection = []
    
    team_size = 4 if has_extra_slot else 3
    for _ in range(team_size):
        r = random.random()
        small_chance = min(0.3, 0.05 * difficulty_mult)
        pool = []
        
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
            pool = all_cards
            
        team_selection.append(random.choice(pool))
        
    team_copies = []
    for c in team_selection:
        c_copy = dict(c)
        c_copy['max_hp'] = c_copy['hp']
        
        mut_chance = random.random()
        if difficulty_mult >= 1.0: 
            if mut_chance < 0.15 * difficulty_mult: 
                c_copy['mutation'] = "Rainbow"
                c_copy['damage'] = int(c_copy['damage'] * 1.2)
                c_copy['hp'] = int(c_copy['hp'] * 1.2)
            elif mut_chance < 0.45 * difficulty_mult: 
                c_copy['mutation'] = "Gold"
                c_copy['damage'] = int(c_copy['damage'] * 1.1)
                c_copy['hp'] = int(c_copy['hp'] * 1.1)
            else: 
                c_copy['mutation'] = "Normal"
        else:
            c_copy['mutation'] = "Normal"
            
        c_copy['max_hp'] = c_copy['hp']
        c_copy['poison'] = 0
        c_copy['dmg_buff'] = 0
        c_copy['stun'] = 0
        c_copy['serial_number'] = 0
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
        if c.get('poison', 0) > 0: status += "🧪"
        if c.get('stun', 0) > 0: status += "💫"
        if c.get('dmg_buff', 0) > 0: status += "✨"
        if c['class_type'] == 'Booster': status += "🔋"
        s_str = f" [#{c['serial_number']:04d}]" if c.get('serial_number', 0) > 0 else ""
        dmg = c['damage'] + c.get('dmg_buff', 0)
        res.append(f"• {c['name']}{s_str}{status} (⚔️{dmg} | ❤️{c['hp']}/{c['max_hp']})")
    return "\n".join(res)

def build_battle_header(p1_name, t1, p2_name, t2):
    return (
        f"⚔️ <b>БИТВА</b> ⚔️\n\n"
        f"🔵 <b>Команда {p1_name}:</b>\n{format_combat_team_vertical(t1)}\n\n"
        f"🔴 <b>Команда {p2_name}:</b>\n{format_combat_team_vertical(t2)}\n\n"
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

async def process_poisons(team, team_name, log):
    for c in team:
        if c['hp'] > 0 and c.get('poison', 0) > 0:
            c['hp'] -= c['poison']
            log_str = f"🧪 {team_name}: <b>{c['name']}</b> получает {c['poison']} урона от яда!"
            if c['hp'] <= 0:
                c['hp'] = 0
                log_str += " ☠️ <i>Мертв от яда!</i>"
            log.append(log_str)
            c['poison'] = 0

async def execute_turn(atk_team, def_team, atk_name, def_name, log, fast_mode=False, weak_mult=1.0):
    await process_poisons(atk_team, atk_name, log)
    
    atk_alive = [c for c in atk_team if c['hp'] > 0]
    def_alive = [c for c in def_team if c['hp'] > 0]
    if not atk_alive or not def_alive: return False
    
    atk_can_act = []
    for c in atk_alive:
        if c.get('stun', 0) > 0:
            c['stun'] -= 1
            log.append(f"💫 {atk_name}: <b>{c['name']}</b> пропускает ход из-за оглушения!")
        else:
            atk_can_act.append(c)
            
    if not atk_can_act: return True # Turn consumed by stuns
    
    attackers = atk_can_act if fast_mode else [random.choice(atk_can_act)]
    
    for atk in attackers:
        def_alive = [c for c in def_team if c['hp'] > 0]
        if not def_alive: break
        
        base_dmg = atk['damage'] + atk.get('dmg_buff', 0)
        base_dmg = int(base_dmg * weak_mult)
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
            
        elif c_type == "Poison":
            target = random.choice(def_alive)
            target['hp'] -= base_dmg
            target['poison'] = target.get('poison', 0) + base_dmg
            log_str = f"🧪 {atk_name}: <b>{atk['name']}</b> бьет <b>{target['name']}</b> на {base_dmg} и отравляет!"
            if target['hp'] <= 0: target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
            log.append(log_str)

        elif c_type == "Stunner":
            any_stunned = any(d.get('stun', 0) > 0 for d in def_alive)
            target = random.choice(def_alive)
            target['hp'] -= base_dmg
            log_str = f"⚡ {atk_name}: <b>{atk['name']}</b> наносит {base_dmg} по <b>{target['name']}</b>!"
            if target['hp'] <= 0: target['hp'] = 0; log_str += " ☠️ <i>Мертв!</i>"
            elif not any_stunned:
                target['stun'] = 1
                log_str += " И ОГЛУШАЕТ на следующий ход!"
            log.append(log_str)
            
        else: # Single
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

async def run_battle_loop(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_id: int, p2_name: str, t1: list, t2: list, 
                          trophies_scale: float = 1.0, is_pvp: bool = False, pvp_no_rewards: bool = False,
                          mods: dict = None):
    
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
    
    if not mods: mods = {'e_fast': False, 'p_fast': False, 'p_weak': False}
    p_weak_mult = 0.8 if mods.get('p_weak') else 1.0
    
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

        did_turn = await execute_turn(t1, t2, p1_name, p2_name, log, fast_mode=mods.get('p_fast', False), weak_mult=p_weak_mult)
        if did_turn:
            if len(log) > 6: log = log[-6:]
            await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
            await asyncio.sleep(3)

        t2_alive = [c for c in t2 if c['hp'] > 0]
        if t2_alive:
            did_turn = await execute_turn(t2, t1, p2_name, p1_name, log, fast_mode=mods.get('e_fast', False), weak_mult=1.0)
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

    final_text = f"🏁 <b>ИТОГИ БОЯ: {p1_name} VS {p2_name}</b>\n\n👑 <b>Победитель: {winner}</b>\n\n"
    
    if pvp_no_rewards:
        final_text += "🤝 <b>Дружеская дуэль завершена!</b> Награды и кубки не начислялись."
    elif is_pvp:
        if winner not in ["Ничья", "Ничья по таймауту"]:
            await execute_db("UPDATE users SET trophies = trophies + 15 WHERE id = ?", (winner_id,))
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 10) WHERE id = ?", (loser_id,))
            final_text += f"🏆 Победитель забирает +15 Кубков\n💀 Проигравший теряет -10 Кубков"
    else:
        if winner == p1_name:
            user = await fetch_one("SELECT trophies, is_vip, x2_shekels FROM users WHERE id = ?", (p1_id,))
            rank = await get_user_rank(user['trophies'])
            
            coins_won = int(random.randint(25, 90) * rank['reward_mult'] * trophies_scale * 0.85)
            won_t = await get_dynamic_trophies(rank['name'], trophies_scale)
            
            if user['is_vip']:
                coins_won = int(coins_won * 1.10)
                won_t = int(won_t * 1.10)
            
            _, _, global_sh_mult = await get_active_events(p1_id)
            coins_won = int(coins_won * global_sh_mult)
                
            if user['x2_shekels']:
                coins_won *= 2
            
            await execute_db("UPDATE users SET coins = coins + ?, trophies = trophies + ? WHERE id = ?", (coins_won, won_t, p1_id))
            final_text += f"🎉 Вы получили: <b>{coins_won} 💰 Шекелей</b> и <b>{won_t} 🏆</b>"
        elif winner == p2_name:
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 2) WHERE id = ?", (p1_id,))
            final_text += f"💀 Вы проиграли ИИ и потеряли 2 🏆."
            
    await msg.edit_text(final_text)
    active_combats.discard(p1_id)
    if is_pvp: active_combats.discard(p2_id)

def get_pve_mods_kb(user_id):
    mods = user_battle_mods.get(user_id, {'e_hp': False, 'e_fast': False, 'p_weak': False, 'p_hp': False, 'p_fast': False})
    
    def cb(mod, text):
        return InlineKeyboardButton(text=f"{'✅' if mods[mod] else '❌'} {text}", callback_data=f"mod_toggle_{mod}")
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [cb('e_hp', "Враги x1.5 ХП (+15% 🏆)")],
        [cb('e_fast', "Враги вне очереди (+30% 🏆)")],
        [cb('p_weak', "Мои атаки -20% (+20% 🏆)")],
        [cb('p_hp', "Мои ХП x1.2 (-25% 🏆)")],
        [cb('p_fast', "Мои вне очереди (-50% 🏆)")],
        [InlineKeyboardButton(text="➡️ Перейти к выбору сложности", callback_data="mod_confirm")]
    ])
    return kb

@dp.message(F.text == "⚔️ Поиск боя (боты)")
async def cmd_pve_select(message: types.Message):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats:
        return await message.answer("❌ Вы уже находитесь в бою или в поиске!")
        
    team1 = await get_team_data(message.from_user.id)
    if not team1: return await message.answer("❌ Экипируйте карты в 🛡 Экипировка!")
    
    if message.from_user.id not in user_battle_mods:
        user_battle_mods[message.from_user.id] = {'e_hp': False, 'e_fast': False, 'p_weak': False, 'p_hp': False, 'p_fast': False}
        
    await message.answer("⚔️ <b>Модификаторы боя (ИИ)</b>\nНастройте бой по своему вкусу:", reply_markup=get_pve_mods_kb(message.from_user.id))

@dp.callback_query(F.data.startswith("mod_toggle_"))
async def mod_toggle_cb(callback: types.CallbackQuery):
    mod = callback.data.split("_")[2]
    uid = callback.from_user.id
    if uid not in user_battle_mods: user_battle_mods[uid] = {'e_hp': False, 'e_fast': False, 'p_weak': False, 'p_hp': False, 'p_fast': False}
    user_battle_mods[uid][mod] = not user_battle_mods[uid][mod]
    await callback.message.edit_reply_markup(reply_markup=get_pve_mods_kb(uid))
    await callback.answer()

@dp.callback_query(F.data == "mod_confirm")
async def mod_confirm_cb(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Лёгкий (-40% Кубков)", callback_data="pve_diff_easy")],
        [InlineKeyboardButton(text="🟡 Средний (Стандарт)", callback_data="pve_diff_med")],
        [InlineKeyboardButton(text="🔴 Сложный (+25% Кубков)", callback_data="pve_diff_hard")]
    ])
    await callback.message.edit_text("⚔️ <b>Выберите сложность ИИ:</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("pve_diff_"))
async def cmd_pve_battle(callback: types.CallbackQuery):
    if callback.from_user.id in active_combats:
        return await callback.answer("❌ Вы уже в бою!", show_alert=True)
        
    diff_type = callback.data.split("_")[2]
    power_mult = 1.0
    trophies_scale = 1.0
    diff_name = "Средний"
    
    if diff_type == "easy":
        power_mult = 0.7  
        trophies_scale = 0.6
        diff_name = "Лёгкий"
    elif diff_type == "med":
        power_mult = 1.1  
        trophies_scale = 1.0
        diff_name = "Средний"
    elif diff_type == "hard":
        power_mult = 1.6  
        trophies_scale = 1.25
        diff_name = "Сложный"
        
    mods = user_battle_mods.get(callback.from_user.id, {})
    if mods.get('e_hp'): trophies_scale *= 1.15
    if mods.get('e_fast'): trophies_scale *= 1.30
    if mods.get('p_weak'): trophies_scale *= 1.20
    if mods.get('p_hp'): trophies_scale *= 0.75
    if mods.get('p_fast'): trophies_scale *= 0.50
        
    await callback.message.edit_text(f"⚔️ Ищем бота... Сложность: <b>{diff_name}</b>")
    
    team1 = await get_team_data(callback.from_user.id)
    if mods.get('p_hp'):
        for c in team1:
            c['hp'] = int(c['hp'] * 1.2)
            c['max_hp'] = c['hp']
            
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    rank = await get_user_rank(user['trophies'])
    
    final_diff_mult = rank['difficulty_mult'] * power_mult
    has_e_slot = bool(user['extra_slot'])
    team2 = await get_bot_team(callback.from_user.id, final_diff_mult, rank['name'], has_e_slot)
    
    if not team2: return await callback.message.edit_text("❌ На сервере нет карт для бота.")
    
    if mods.get('e_hp'):
        for c in team2:
            c['hp'] = int(c['hp'] * 1.5)
            c['max_hp'] = c['hp']
            
    p1_name = get_display_name(user)
    active_combats.add(callback.from_user.id)
    
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, callback.from_user.id, p1_name, 0, f"ИИ ({diff_name})", team1, team2, trophies_scale, is_pvp=False, mods=mods))
    await callback.answer()

@dp.message(F.text.startswith('/'))
async def handle_dynamic_commands(message: types.Message):
    cmd = message.text.split()[0].replace('/', '').lower()
    
    if cmd in ['start', 'profile', 'quests', 'top', 'shop', 'getcard', 'index', 'inventory', 'equip', 'admin', 'donate', 'help']:
        return
        
    event = await fetch_one("SELECT * FROM global_event WHERE is_active = 1 AND command = ?", (cmd,))
    if not event: return
    
    args = message.text.split()
    if len(args) < 2: return await message.answer(f"⚠️ <b>Глобальный Ивент:</b> Используйте /{cmd} [сумма]")
        
    try: val = int(args[1])
    except: return await message.answer("Сумма должна быть числом!")
    
    if event['type'] == 'shekels':
        if val < 500: return await message.answer("Минимальный взнос 500 шекелей!")
        user = await fetch_one("SELECT coins FROM users WHERE id = ?", (message.from_user.id,))
        if user['coins'] < val: return await message.answer("Недостаточно шекелей!")
        
        await execute_db("UPDATE users SET coins = coins - ? WHERE id = ?", (val, message.from_user.id))
        await execute_db("INSERT INTO event_donations (user_id, amount) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET amount = amount + ?", (message.from_user.id, val, val))
        await execute_db("UPDATE global_event SET current = current + ? WHERE id = ?", (val, event['id']))
        
        await message.answer(f"✅ Вы успешно пожертвовали {val} 💰 в глобальный ивент!\nСпасибо за участие!")
        
    elif event['type'] == 'mythic':
        if val < 1: return await message.answer("Минимум 1 карта!")
        myths = await fetch_all("SELECT id, count FROM inventory WHERE user_id = ? AND mutation = 'Normal' AND card_id IN (SELECT id FROM cards WHERE rarity = 'Mythic')", (message.from_user.id,))
        
        total_myths = sum(i['count'] for i in myths)
        if total_myths < val: return await message.answer(f"У вас нет {val} обычных Мифических карт!")
        
        to_take = val
        for m in myths:
            if to_take <= 0: break
            take_from_this = min(m['count'], to_take)
            await execute_db("UPDATE inventory SET count = count - ? WHERE id = ?", (take_from_this, m['id']))
            to_take -= take_from_this
            
        await execute_db("DELETE FROM inventory WHERE count <= 0")
        await execute_db("INSERT INTO event_donations (user_id, amount) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET amount = amount + ?", (message.from_user.id, val, val))
        await execute_db("UPDATE global_event SET current = current + ? WHERE id = ?", (val, event['id']))
        
        await message.answer(f"✅ Вы успешно пожертвовали {val} Мифических карт!\nСпасибо за участие!")

@dp.message(Command("help"))
@dp.message(F.text == "🆘 Помощь (/help)")
async def cmd_help(message: types.Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Основы", callback_data="help_basics")],
        [InlineKeyboardButton(text="⚔️ Бой и Классы", callback_data="help_combat")],
        [InlineKeyboardButton(text="🎁 Магазин и Донат", callback_data="help_shop")],
        [InlineKeyboardButton(text="🎉 Ивенты", callback_data="help_events")]
    ])
    await message.answer("🆘 <b>Справочник по боту</b>\nВыберите категорию для изучения:", reply_markup=kb)

@dp.callback_query(F.data.startswith("help_"))
async def cb_help(callback: types.CallbackQuery):
    cat = callback.data.split("_")[1]
    
    if cat == "basics":
        text = "📖 <b>ОСНОВЫ</b>\n\n1. 🎴 Выбивайте карты каждые 4 минуты.\n2. 🛡 Экипируйте лучшие карты в меню Экипировка.\n3. ⚔️ Сражайтесь с ИИ или друзьями, зарабатывайте кубки и шекели.\n4. Выполняйте ежедневные квесты для бонусов."
    elif cat == "combat":
        text = "⚔️ <b>БОЙ И КЛАССЫ</b>\n\n🎯 <b>Single:</b> Бьет одну цель.\n🌪 <b>AOE:</b> Бьет всех врагов.\n🌊 <b>Splash:</b> Бьет цель сильно, остальных слабее.\n🧪 <b>Poison:</b> Наносит урон и отравляет цель (доп. урон каждый ход).\n⚡ <b>Stunner:</b> Оглушает врага (пропуск хода). Не сработает, если кто-то уже оглушен.\n✨ <b>Booster:</b> Усиливает свою команду (урон и хп)."
    elif cat == "shop":
        text = "🎁 <b>МАГАЗИН И ДОНАТ</b>\n\n🛒 В глобальном магазине можно купить карточки и наборы (обновляется каждые 1.5 часа).\n💎 В Донат-магазине за Робуксы (1 R$ = 500 шекелей) вы можете купить VIP (+10% статов, скидка в магазине), x2 Шекели навсегда, +1 слот экипировки и уникальных юнитов!"
    elif cat == "events":
        text = "🎉 <b>ИВЕНТЫ</b>\n\n<b>Lucky Event:</b> Повышает шанс на выпадение редких карт и шанс на мутации (Gold 12%, Rainbow 2%).\n<b>Shekel Event:</b> Умножает получение шекелей в боях.\n<b>Global Event:</b> Игроки собирают общую сумму шекелей или карт с помощью специальной команды от админа. Топ донатеры получают эксклюзив!"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📖 Основы", callback_data="help_basics"), InlineKeyboardButton(text="⚔️ Бой", callback_data="help_combat")],
        [InlineKeyboardButton(text="🎁 Магазин", callback_data="help_shop"), InlineKeyboardButton(text="🎉 Ивенты", callback_data="help_events")]
    ])
    try: await callback.message.edit_text(text, reply_markup=kb)
    except: pass
    await callback.answer()

def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Карты", callback_data="adm_cards"), InlineKeyboardButton(text="👤 Игроки", callback_data="adm_users")],
        [InlineKeyboardButton(text="🎉 Сервер Ивенты", callback_data="adm_events"), InlineKeyboardButton(text="🌍 Глобал Ивенты", callback_data="adm_global_ev")],
        [InlineKeyboardButton(text="💎 Донат Юниты", callback_data="adm_don_units"), InlineKeyboardButton(text="👑 Админы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="🏆 Награды за Топ", callback_data="adm_lb_main")],
        [InlineKeyboardButton(text="📦 Бэкап Базы Данных", callback_data="adm_db")]
    ])

@dp.message(F.text == "⚙️ Админ-панель")
@dp.message(Command("admin"))
async def cmd_admin_panel(message: types.Message):
    if not await is_admin(message.from_user.id): return
    await message.answer("⚙️ <b>Панель Администратора</b>\nВыберите раздел:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_main")
async def cq_adm_main(callback: types.CallbackQuery):
    await callback.message.edit_text("⚙️ <b>Панель Администратора</b>\nВыберите раздел:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_global_ev")
async def adm_global_ev_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать Ивент", callback_data="adm_ge_create")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🌍 <b>Глобальные Ивенты</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_ge_create")
async def adm_ge_create_cmd(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите КОМАНДУ для ивента (без слеша, например: kotik):")
    await state.set_state(AdminGlobalEvent.cmd)
    await callback.answer()

@dp.message(AdminGlobalEvent.cmd)
async def adm_ge_c1(message: types.Message, state: FSMContext):
    await state.update_data(cmd=message.text.strip())
    await message.answer("Тип взносов: 'shekels' или 'mythic' ?")
    await state.set_state(AdminGlobalEvent.etype)

@dp.message(AdminGlobalEvent.etype)
async def adm_ge_c2(message: types.Message, state: FSMContext):
    await state.update_data(etype=message.text.strip().lower())
    await message.answer("Какая ЦЕЛЬ? (число, например 200000):")
    await state.set_state(AdminGlobalEvent.goal)

@dp.message(AdminGlobalEvent.goal)
async def adm_ge_c3(message: types.Message, state: FSMContext):
    await state.update_data(goal=int(message.text))
    await message.answer("Длительность ивента в МИНУТАХ:")
    await state.set_state(AdminGlobalEvent.mins)

@dp.message(AdminGlobalEvent.mins)
async def adm_ge_c4(message: types.Message, state: FSMContext):
    await state.update_data(mins=int(message.text))
    await message.answer("ID Карты для Топ-1 донатера (0 если нет):")
    await state.set_state(AdminGlobalEvent.top_card_id)

@dp.message(AdminGlobalEvent.top_card_id)
async def adm_ge_c5(message: types.Message, state: FSMContext):
    await state.update_data(top_card_id=int(message.text))
    await message.answer("Награда шекелей для остальных участников (0 если нет):")
    await state.set_state(AdminGlobalEvent.part_shekels)

@dp.message(AdminGlobalEvent.part_shekels)
async def adm_ge_c6(message: types.Message, state: FSMContext):
    psh = int(message.text)
    data = await state.get_data()
    end_time = time.time() + (data['mins'] * 60)
    
    await execute_db("UPDATE global_event SET is_active = 0") # Отключаем старые
    await execute_db(
        "INSERT INTO global_event (command, type, goal, current, end_time, top_card_id, part_shekels) VALUES (?, ?, ?, 0, ?, ?, ?)",
        (data['cmd'], data['etype'], data['goal'], end_time, data['top_card_id'], psh)
    )
    await state.clear()
    
    t_str = "Шекелей" if data['etype'] == 'shekels' else "Мифических карт"
    await message.answer(f"✅ Глобальный ивент /{data['cmd']} запущен!\nЦель: {data['goal']} {t_str}\nВремя: {data['mins']} минут.")
    await broadcast_message(f"🌍 <b>ГЛОБАЛЬНЫЙ ИВЕНТ НАЧАЛСЯ!</b>\nАдминистратор запустил новый ивент!\nВведите /{data['cmd']} [сумма] чтобы внести свой вклад.\nЦель: {data['goal']} {t_str}!\nТоп 1 донатер получит эксклюзивную награду!")
    
    await log_admin(message.from_user.id, f"Запущен глобал ивент /{data['cmd']} (Цель: {data['goal']} {data['etype']})")

@dp.callback_query(F.data == "adm_don_units")
async def adm_don_units(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить Юнита", callback_data="adm_du_add")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("💎 <b>Настройка Донат Юнитов</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_du_add")
async def adm_du_add(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID карты для добавления в донат магазин:")
    await state.set_state(AdminDonateUnit.card_id)
    await callback.answer()

@dp.message(AdminDonateUnit.card_id)
async def adm_du_add_c1(message: types.Message, state: FSMContext):
    await state.update_data(card_id=int(message.text))
    await message.answer("Введите цену в Робуксах (R$):")
    await state.set_state(AdminDonateUnit.price)

@dp.message(AdminDonateUnit.price)
async def adm_du_add_c2(message: types.Message, state: FSMContext):
    price = int(message.text)
    data = await state.get_data()
    await execute_db("INSERT INTO donate_units (card_id, price) VALUES (?, ?)", (data['card_id'], price))
    await state.clear()
    await message.answer(f"✅ Юнит {data['card_id']} добавлен в донат магазин за {price} R$!")
    await log_admin(message.from_user.id, f"Добавлен донат юнит {data['card_id']} за {price} R$")

@dp.callback_query(F.data == "adm_events")
async def adm_events_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍀 Lucky Event", callback_data="adm_ev_luck"), InlineKeyboardButton(text="⏳ CD Event", callback_data="adm_ev_cd")],
        [InlineKeyboardButton(text="💰 Shekel Event", callback_data="adm_ev_shekel")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🎉 <b>Серверные Ивенты</b>\nВыберите ивент для запуска:", reply_markup=kb)

@dp.callback_query(F.data == "adm_ev_shekel")
async def adm_ev_shekel(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите множитель шекелей (например, 2.0):")
    await state.set_state(EventShekel.mult)
    await callback.answer()

@dp.message(EventShekel.mult)
async def ev_shekel_m1(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text))
    await message.answer("Введите длительность в минутах:")
    await state.set_state(EventShekel.mins)

@dp.message(EventShekel.mins)
async def ev_shekel_m2(message: types.Message, state: FSMContext):
    mins = int(message.text)
    data = await state.get_data()
    end_t = time.time() + mins * 60
    await execute_db("UPDATE server_settings SET shekel_mult=?, shekel_end=? WHERE id=1", (data['mult'], end_t))
    await state.clear()
    await message.answer(f"✅ Ивент Шекелей запущен! Множитель: x{data['mult']}, Длительность: {mins} мин.")
    await broadcast_message(f"💰 <b>SHEKEL ИВЕНТ НАЧАЛСЯ!</b>\nМножитель шекелей: x{data['mult']} на {mins} минут!")
    await log_admin(message.from_user.id, f"Запущен Shekel ивент x{data['mult']} на {mins}м")

@dp.callback_query(F.data == "adm_ev_luck")
async def adm_ev_luck(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Множитель удачи (например, 2.0):")
    await state.set_state(EventLuck.mult)
    await callback.answer()

@dp.message(EventLuck.mult)
async def ev_luck_m1(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text))
    await message.answer("Длительность (минут):")
    await state.set_state(EventLuck.mins)

@dp.message(EventLuck.mins)
async def ev_luck_m2(message: types.Message, state: FSMContext):
    mins = int(message.text)
    data = await state.get_data()
    end_t = time.time() + mins * 60
    await execute_db("UPDATE server_settings SET luck_mult=?, luck_end=? WHERE id=1", (data['mult'], end_t))
    await state.clear()
    await message.answer(f"✅ Lucky Event запущен: x{data['mult']} на {mins} минут.")
    await broadcast_message(f"🍀 <b>LUCKY EVENT НАЧАЛСЯ!</b>\nШанс на редкие карты и мутации увеличен в {data['mult']} раз на {mins} минут!")
    await log_admin(message.from_user.id, f"Запущен Lucky Event x{data['mult']} на {mins}м")

@dp.callback_query(F.data == "adm_ev_cd")
async def adm_ev_cd(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Делитель КД (например, 2.0 = КД быстрее в 2 раза):")
    await state.set_state(EventCD.mult)
    await callback.answer()

@dp.message(EventCD.mult)
async def ev_cd_m1(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text))
    await message.answer("Длительность (минут):")
    await state.set_state(EventCD.mins)

@dp.message(EventCD.mins)
async def ev_cd_m2(message: types.Message, state: FSMContext):
    mins = int(message.text)
    data = await state.get_data()
    end_t = time.time() + mins * 60
    await execute_db("UPDATE server_settings SET cd_mult=?, cd_end=? WHERE id=1", (data['mult'], end_t))
    await state.clear()
    await message.answer(f"✅ CD Event запущен: деление КД на {data['mult']} в течение {mins} минут.")
    await broadcast_message(f"⏳ <b>COOLDOWN EVENT НАЧАЛСЯ!</b>\nКулдаун на выбивание карт уменьшен в {data['mult']} раз на {mins} минут!")
    await log_admin(message.from_user.id, f"Запущен CD Event /{data['mult']} на {mins}м")

@dp.callback_query(F.data == "adm_cards")
async def adm_cards_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="adm_c_add"), InlineKeyboardButton(text="📝 Изменить", callback_data="adm_c_edit")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🃏 <b>Управление Картами</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_c_add")
async def add_card_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Отправьте фото карты:")
    await state.set_state(AddCard.photo)
    await callback.answer()

@dp.message(AddCard.photo, F.photo)
async def add_card_photo(message: types.Message, state: FSMContext):
    await state.update_data(photo_id=message.photo[-1].file_id)
    await message.answer("Имя карты:")
    await state.set_state(AddCard.name)

@dp.message(AddCard.name)
async def add_card_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Шанс выпадения (например, 20.5):")
    await state.set_state(AddCard.drop_chance)

@dp.message(AddCard.drop_chance)
async def add_card_chance(message: types.Message, state: FSMContext):
    await state.update_data(drop_chance=float(message.text))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=r, callback_data=f"set_rarity_{r}")] for r in RARITY_COLORS.keys()])
    await message.answer("Редкость:", reply_markup=kb)
    await state.set_state(AddCard.rarity)

@dp.callback_query(AddCard.rarity, F.data.startswith("set_rarity_"))
async def add_card_rarity(callback: types.CallbackQuery, state: FSMContext):
    r = callback.data.split("_")[2]
    await state.update_data(rarity=r)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=f"{CLASS_EMOJI[c]} {c}", callback_data=f"set_class_{c}")] for c in CLASSES])
    await callback.message.edit_text("Класс:", reply_markup=kb)
    await state.set_state(AddCard.class_type)

@dp.callback_query(AddCard.class_type, F.data.startswith("set_class_"))
async def add_card_class(callback: types.CallbackQuery, state: FSMContext):
    c = callback.data.split("_")[2]
    await state.update_data(class_type=c)
    if c == "Booster":
        await callback.message.edit_text("Множитель Урона (например 1.25):")
        await state.set_state(AddCard.booster_dmg)
    else:
        await callback.message.edit_text("Урон (целое число):")
        await state.set_state(AddCard.damage)

@dp.message(AddCard.booster_dmg)
async def add_card_bdmg(message: types.Message, state: FSMContext):
    await state.update_data(booster_dmg=float(message.text))
    await message.answer("Множитель ХП (например 1.5):")
    await state.set_state(AddCard.booster_hp)

@dp.message(AddCard.booster_hp)
async def add_card_bhp(message: types.Message, state: FSMContext):
    data = await state.get_data()
    bhp = float(message.text)
    final_photo = await create_bordered_image(bot, data['photo_id'], data['rarity'])
    await execute_db(
        "INSERT INTO cards (name, rarity, class_type, drop_chance, photo_id, booster_dmg_mult, booster_hp_mult) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (data['name'], data['rarity'], data['class_type'], data['drop_chance'], final_photo, data['booster_dmg'], bhp)
    )
    await state.clear()
    await message.answer(f"✅ Бустер {data['name']} добавлен!")
    await log_admin(message.from_user.id, f"Добавлен бустер {data['name']}")

@dp.message(AddCard.damage)
async def add_card_dmg(message: types.Message, state: FSMContext):
    await state.update_data(damage=int(message.text))
    await message.answer("Здоровье (целое число):")
    await state.set_state(AddCard.hp)

@dp.message(AddCard.hp)
async def add_card_hp(message: types.Message, state: FSMContext):
    data = await state.get_data()
    hp = int(message.text)
    final_photo = await create_bordered_image(bot, data['photo_id'], data['rarity'])
    await execute_db(
        "INSERT INTO cards (name, rarity, class_type, drop_chance, photo_id, damage, hp) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (data['name'], data['rarity'], data['class_type'], data['drop_chance'], final_photo, data['damage'], hp)
    )
    await state.clear()
    await message.answer(f"✅ Карта {data['name']} добавлена!")
    await log_admin(message.from_user.id, f"Добавлена карта {data['name']}")

@dp.callback_query(F.data == "adm_users")
async def adm_users_menu(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Выдать Карту", callback_data="adm_u_give"), InlineKeyboardButton(text="💰 Выдать Шекели", callback_data="adm_u_coins")],
        [InlineKeyboardButton(text="🏆 Выдать Кубки", callback_data="adm_u_trophies"), InlineKeyboardButton(text="🔄 Сброс Боя", callback_data="adm_u_reset")],
        [InlineKeyboardButton(text="🔨 Бан / Разбан", callback_data="adm_u_ban")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("👤 <b>Управление Игроками</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_u_reset")
async def adm_reset_battle_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока для сброса боя:")
    await state.set_state(AdminManage.reset_battle_id)
    await callback.answer()

@dp.message(AdminManage.reset_battle_id)
async def adm_reset_battle_do(message: types.Message, state: FSMContext):
    uid = int(message.text)
    active_combats.discard(uid)
    await state.clear()
    await message.answer(f"✅ Статус боя для {uid} сброшен.")
    await log_admin(message.from_user.id, f"Сброшен бой для {uid}")

@dp.callback_query(F.data == "adm_u_coins")
async def adm_give_coins_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока:")
    await state.set_state(AdminManage.give_coins_id)
    await callback.answer()

@dp.message(AdminManage.give_coins_id)
async def adm_give_coins_id(message: types.Message, state: FSMContext):
    await state.update_data(give_coins_id=int(message.text))
    await message.answer("Количество шекелей:")
    await state.set_state(AdminManage.give_coins_amount)

@dp.message(AdminManage.give_coins_amount)
async def adm_give_coins_amount(message: types.Message, state: FSMContext):
    amount = int(message.text)
    data = await state.get_data()
    uid = data['give_coins_id']
    await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (amount, uid))
    await state.clear()
    await message.answer(f"✅ Игроку {uid} выдано {amount} шекелей.")
    await log_admin(message.from_user.id, f"Выдано {amount} монет {uid}")

@dp.callback_query(F.data == "adm_u_trophies")
async def adm_give_tr_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока:")
    await state.set_state(AdminManage.give_trophies_id)
    await callback.answer()

@dp.message(AdminManage.give_trophies_id)
async def adm_give_tr_id(message: types.Message, state: FSMContext):
    await state.update_data(give_trophies_id=int(message.text))
    await message.answer("Количество кубков (+ или -):")
    await state.set_state(AdminManage.give_trophies_amount)

@dp.message(AdminManage.give_trophies_amount)
async def adm_give_tr_amount(message: types.Message, state: FSMContext):
    amount = int(message.text)
    data = await state.get_data()
    uid = data['give_trophies_id']
    await execute_db("UPDATE users SET trophies = MAX(0, trophies + ?) WHERE id = ?", (amount, uid))
    await state.clear()
    await message.answer(f"✅ Кубки игрока {uid} изменены на {amount}.")
    await log_admin(message.from_user.id, f"Кубки {uid} изменены на {amount}")

@dp.callback_query(F.data == "adm_u_give")
async def adm_give_card_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока:")
    await state.set_state(GiveCard.user_id)
    await callback.answer()

@dp.message(GiveCard.user_id)
async def adm_give_card_id(message: types.Message, state: FSMContext):
    await state.update_data(user_id=int(message.text))
    await message.answer("Введите ID карты:")
    await state.set_state(GiveCard.card_id)

@dp.message(GiveCard.card_id)
async def adm_give_card_cid(message: types.Message, state: FSMContext):
    await state.update_data(card_id=int(message.text))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Обычная", callback_data="gc_mut_Normal")],
        [InlineKeyboardButton(text="⭐ Gold", callback_data="gc_mut_Gold"), InlineKeyboardButton(text="🌈 Rainbow", callback_data="gc_mut_Rainbow")]
    ])
    await message.answer("Выберите мутацию:", reply_markup=kb)
    await state.set_state(GiveCard.mutation)

@dp.callback_query(GiveCard.mutation, F.data.startswith("gc_mut_"))
async def adm_give_card_mut(callback: types.CallbackQuery, state: FSMContext):
    mut = callback.data.split("_")[2]
    data = await state.get_data()
    _, serial, _ = await give_card_to_user(data['user_id'], data['card_id'], mut)
    await state.clear()
    await callback.message.edit_text(f"✅ Карта {data['card_id']} ({mut}) выдана игроку {data['user_id']}! Серийник: {serial}")
    await log_admin(callback.from_user.id, f"Выдана карта {data['card_id']} ({mut}) игроку {data['user_id']}")

@dp.callback_query(F.data == "adm_u_ban")
async def adm_u_ban(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID пользователя для бана/разбана:")
    await state.set_state(AdminBan.user_id)
    await callback.answer()

@dp.message(AdminBan.user_id)
async def adm_u_ban_do(message: types.Message, state: FSMContext):
    uid = int(message.text)
    user = await fetch_one("SELECT banned FROM users WHERE id = ?", (uid,))
    if not user:
        return await message.answer("Пользователь не найден.")
    new_status = 0 if user['banned'] else 1
    await execute_db("UPDATE users SET banned = ? WHERE id = ?", (new_status, uid))
    await state.clear()
    await message.answer(f"✅ Статус бана для {uid} изменен на {new_status}.")
    await log_admin(message.from_user.id, f"Изменен бан статус для {uid} на {new_status}")

@dp.message(F.text == "⚔️ PvP Дуэль")
async def cmd_pvp_start(message: types.Message, state: FSMContext):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats:
        return await message.answer("❌ Вы уже находитесь в бою!")
    team1 = await get_team_data(message.from_user.id)
    if not team1:
        return await message.answer("❌ Экипируйте карты в 🛡 Экипировка!")
    await message.answer("⚔️ <b>PvP Дуэль</b>\nВведите ID вашего друга/противника (он тоже не должен быть в бою и должен иметь экипированные карты):")
    await state.set_state(PvPState.waiting_target)

@dp.message(PvPState.waiting_target)
async def cmd_pvp_target(message: types.Message, state: FSMContext):
    try: target_id = int(message.text)
    except: return await message.answer("❌ ID должен быть числом.")
    
    if target_id == message.from_user.id:
        return await message.answer("❌ Нельзя играть с самим собой!")
    if target_id in active_combats:
        return await message.answer("❌ Этот игрок уже в бою!")
        
    team2 = await get_team_data(target_id)
    if not team2:
        return await message.answer("❌ У противника нет экипированных карт!")
        
    team1 = await get_team_data(message.from_user.id)
    p1 = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    p2 = await fetch_one("SELECT * FROM users WHERE id = ?", (target_id,))
    
    if not p2: return await message.answer("❌ Игрок не найден.")
    
    active_combats.add(message.from_user.id)
    active_combats.add(target_id)
    await state.clear()
    
    await message.answer("⚔️ PvP Бой запускается!")
    asyncio.create_task(run_battle_loop(bot, message.chat.id, message.from_user.id, get_display_name(p1), target_id, get_display_name(p2), team1, team2, 1.0, is_pvp=True))

@dp.callback_query(F.data == "adm_lb_main")
async def adm_lb_main(callback: types.CallbackQuery):
    await callback.answer("Управление наградами за топ пока в разработке", show_alert=True)

@dp.callback_query(F.data == "adm_admins")
async def adm_admins_menu(callback: types.CallbackQuery):
    await callback.answer("Управление админами пока в разработке", show_alert=True)

@dp.callback_query(F.data == "adm_c_edit")
async def adm_c_edit(callback: types.CallbackQuery):
    await callback.answer("Редактирование карт в разработке", show_alert=True)

@dp.callback_query(F.data == "adm_db")
async def adm_send_db(callback: types.CallbackQuery):
    try:
        await bot.send_document(SUPER_ADMIN_ID, FSInputFile(DB_NAME))
        await callback.answer("✅ База данных отправлена!")
    except Exception as e:
        await callback.answer(f"❌ Ошибка отправки БД: {e}", show_alert=True)

async def main():
    await check_and_update_schema()
    asyncio.create_task(shop_auto_restock_task())
    asyncio.create_task(global_event_task())
    asyncio.create_task(leaderboard_rewards_task())
    
    await bot.set_my_commands([
        BotCommand(command="start", description="Перезапуск бота"),
        BotCommand(command="profile", description="Мой профиль"),
        BotCommand(command="getcard", description="Выбить карту"),
        BotCommand(command="inventory", description="Инвентарь"),
        BotCommand(command="equip", description="Экипировка"),
        BotCommand(command="shop", description="Магазин"),
        BotCommand(command="top", description="Топ игроков"),
        BotCommand(command="quests", description="Ежедневные квесты"),
        BotCommand(command="donate", description="Донат магазин"),
        BotCommand(command="index", description="Все карты"),
        BotCommand(command="help", description="Руководство по игре")
    ])
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
