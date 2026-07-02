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
BOT_TOKEN = "7725898870:AAHa-6biiZkWuheNzjPl0Tun3XpNyLNq1lE"
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

active_combats = set()
active_trades_users = set()  
active_trades = {}  

# Шансы на появление в магазине существенно увеличены (вероятности от 0.4 до 1.2)
SHOP_PACKAGES = [
    ("1_rnd", "1 Случайная карта", 100, 20, 1.2),
    ("3_rnd", "3 Случайные карты", 275, 20, 1.1),
    ("5_rnd", "5 Случайных карт", 450, 20, 1.0),
    ("10_rnd", "10 Случайных карт", 900, 15, 0.9),
    ("25_rnd", "25 Случайных карт", 2300, 10, 0.8),
    ("50_rnd", "50 Случайных карт", 4500, 3, 0.6),
    ("100_rnd", "100 Случайных карт", 9000, 2, 0.4), # Новая позиция в магазине
    ("rnd_leg", "Случайная Легендарная", 1000, 5, 0.6), 
    ("rnd_myth", "Случайная Мифическая", 10000, 3, 0.35), 
    ("rnd_sup", "Случайная Супер Карта", 75000, 1, 0.2) 
]

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
                equip3 INTEGER DEFAULT 0
            )
        """)
        
        try: await db.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
        except aiosqlite.OperationalError: pass
            
        for col in ['q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys']:
            try: await db.execute(f"ALTER TABLE users ADD COLUMN {col} INTEGER DEFAULT 0")
            except aiosqlite.OperationalError: pass
            
        # Pity и Quests Cooldown
        try: await db.execute("ALTER TABLE users ADD COLUMN pity_mythic INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN pity_super INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE users ADD COLUMN quests_cd REAL DEFAULT 0")
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
                serial_number INTEGER DEFAULT 0
            )
        """)
        
        try: await db.execute("ALTER TABLE inventory ADD COLUMN mutation TEXT DEFAULT 'Normal'")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE inventory ADD COLUMN serial_number INTEGER DEFAULT 0")
        except aiosqlite.OperationalError: pass
        
        await db.execute("UPDATE cards SET rarity = 'Super' WHERE rarity IN ('Godly', 'Secret')")
        
        await db.execute("DROP TABLE IF EXISTS ranks")
        await db.execute("""
            CREATE TABLE ranks (
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
                last_lb_reward REAL DEFAULT 0
            )
        """)
        
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN last_restock REAL DEFAULT 0")
        except aiosqlite.OperationalError: pass
        try: await db.execute("ALTER TABLE server_settings ADD COLUMN last_lb_reward REAL DEFAULT 0")
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
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        
        await db.execute("""
            CREATE TABLE IF NOT EXISTS lb_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bracket TEXT,
                reward_type TEXT,
                amount INTEGER DEFAULT 0,
                card_id INTEGER DEFAULT 0,
                mutation TEXT DEFAULT 'Normal'
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

class AdminAnnounce(StatesGroup):
    content = State()

class TradeState(StatesGroup):
    waiting_target = State()

class PvPState(StatesGroup):
    waiting_target = State()

# ========================================================================
# УТИЛИТЫ И ХЕЛПЕРЫ
# ========================================================================
def get_display_name(user_data: dict) -> str:
    if user_data.get('username'): return f"@{user_data['username']}"
    elif user_data.get('first_name'): return user_data['first_name']
    return f"Игрок {user_data.get('id', '???')}"

# Добавлен 1-часовой кулдаун на выполнение квестов
async def add_quest_progress(user_id: int, field: str, amount: int = 1):
    if field not in ['q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys']:
        return
        
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user: return
    if time.time() < user.get('quests_cd', 0): return # Квесты на кд
    
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
                quests_cd = ?
            WHERE id = ?
        """, (time.time() + 3600, user_id))
        try:
            await bot.send_message(user_id, "🎉 <b>ПОЗДРАВЛЯЕМ!</b>\nВы выполнили все ежедневные квесты и получили <b>900 💰 Шекелей</b>!\nКвесты ушли на перезарядку (1 час)!")
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
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="📜 Квесты")],
        [KeyboardButton(text="🤝 Трейды"), KeyboardButton(text="⚔️ PvP Дуэль")],
        [KeyboardButton(text="🏆 Топ игроков"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="📖 Индекс")]
    ]
    if is_adm: kb.append([KeyboardButton(text="⚙️ Админ-панель")])
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

def roll_mutation(luck_mult: float = 1.0):
    r = random.random()
    if r <= 0.02 * luck_mult: return "Rainbow"
    if r <= 0.12 * luck_mult: return "Gold"
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

# Исключение серийников и подсчета для супер админа
async def give_card_to_user(user_id: int, card_id: int, mutation: str, rarity: str = None) -> tuple:
    if not rarity:
        card = await fetch_one("SELECT rarity FROM cards WHERE id = ?", (card_id,))
        rarity = card['rarity'] if card else 'Basic'
        
    db = await get_db_connection()
    try:
        if user_id != SUPER_ADMIN_ID and needs_serial_number(rarity, mutation):
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

# ========================================================================
# ЛОГИКА ШАНСОВ, PITY И МАГАЗИНА
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
        asyncio.create_task(broadcast_message("🛒 <b>ГЛОБАЛЬНЫЙ МАГАЗИН ОБНОВИЛСЯ!</b>\nЗавезли свежие наборы карт. Количество строго ограничено, успей купить!\n\nИспользуй кнопку в меню или /shop"))

# Изменено на 90 минут
async def shop_auto_restock_task():
    while True:
        try:
            settings = await fetch_one("SELECT last_restock FROM server_settings WHERE id = 1")
            now = time.time()
            if settings and (now - settings['last_restock'] >= 90 * 60):
                await restock_shop()
        except Exception as e:
            logging.error(f"Shop restock error: {e}")
        await asyncio.sleep(60)

async def give_multiple_cards(user_id: int, count: int) -> list:
    luck_mult, _ = await get_active_events()
    all_cards = await fetch_all("SELECT * FROM cards WHERE drop_chance > 0 AND rarity != 'Leaderboard'")
    if not all_cards: return []
    
    user = await fetch_one("SELECT pity_mythic, pity_super FROM users WHERE id = ?", (user_id,))
    pm = user['pity_mythic'] if user else 0
    ps = user['pity_super'] if user else 0
    
    super_cards = [c for c in all_cards if c['rarity'] == 'Super']
    mythic_cards = [c for c in all_cards if c['rarity'] == 'Mythic']
    weights = [c['drop_chance'] * (luck_mult if c['drop_chance'] < 15.0 else 1.0) for c in all_cards]
    
    result = []
    for _ in range(count):
        pm += 1
        ps += 1
        
        if ps >= 10000 and super_cards:
            won_card = random.choice(super_cards)
            ps = 0
        elif pm >= 1000 and mythic_cards:
            won_card = random.choice(mythic_cards)
            pm = 0
        else:
            won_card = random.choices(all_cards, weights=weights, k=1)[0]
            if won_card['rarity'] == 'Super': ps = 0
            if won_card['rarity'] == 'Mythic': pm = 0

        mut = roll_mutation(luck_mult)
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        
        c_copy = dict(won_card)
        c_copy['mutation'] = mut
        c_copy['serial_number'] = serial
        result.append(c_copy)
        
    await execute_db("UPDATE users SET pity_mythic = ?, pity_super = ? WHERE id = ?", (pm, ps, user_id))
    return result

# Принудительная и фоновая выдача топа по кубкам (раз в 2 дня)
async def distribute_lb_rewards(force=False):
    settings = await fetch_one("SELECT last_lb_reward FROM server_settings WHERE id = 1")
    now = time.time()
    
    if force or (settings and (now - settings['last_lb_reward'] >= 2 * 24 * 3600)):
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
                        f"🎉 Поздравляем! По итогам последних дней вы заняли почетное <b>{pos} место</b> в мировом рейтинге по кубкам!\n\n"
                        f"🎁 <b>Вот ваша заслуженная награда:</b>\n" + "\n".join([f"🔸 {m}" for m in reward_msgs]) + "\n\n"
                        f"<i>Спасибо за вашу активность! Рейтинг был сброшен, новые награды через 2 дня!</i>"
                    )
                    try:
                        await bot.send_message(user['id'], msg_text)
                    except: pass
                    
        await execute_db("UPDATE server_settings SET last_lb_reward = ? WHERE id = 1", (now,))
        await execute_db("UPDATE users SET trophies = 0") # Реальный сброс кубков

async def leaderboard_rewards_task():
    while True:
        try:
            await distribute_lb_rewards(force=False)
        except Exception as e:
            logging.error(f"LB Rewards error: {e}")
        await asyncio.sleep(600)

# ========================================================================
# ОСНОВНЫЕ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ
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
    active_trades_users.discard(message.from_user.id)
    
    broken_trades = []
    for t_id, t_data in active_trades.items():
        if t_data['p1'] == message.from_user.id or t_data['p2'] == message.from_user.id:
            broken_trades.append(t_id)
            other_p = t_data['p2'] if t_data['p1'] == message.from_user.id else t_data['p1']
            active_trades_users.discard(other_p)
            try: await bot.send_message(other_p, "⚠️ Трейд был отменен, так как ваш напарник перезапустил бота.")
            except: pass
    for t_id in broken_trades:
        active_trades.pop(t_id, None)

    adm = await is_admin(message.from_user.id)
    await message.answer(
        "👋 <b>Добро пожаловать в Card Battle Bot!</b>\n\n"
        "Собери свою колоду уникальных юнитов, выставляй их в бой, поднимай кубки и обменивайся картами с другими игроками!\n\n"
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
    
    text = (
        f"👤 <b>Профиль игрока {name}</b>\n\n"
        f"🎖 <b>Ранг:</b> {rank['name']}\n"
        f"🏆 <b>Кубки:</b> {user['trophies']}\n"
        f"💰 <b>Шекели:</b> {user['coins']}\n"
        f"🃏 <b>Всего карт:</b> {total_cards['s'] or 0}\n\n"
        f"🎰 <b>Жалость (Pity):</b>\n"
        f"🔴 Мифик: {user.get('pity_mythic', 0)} / 1000\n"
        f"🌈 Супер: {user.get('pity_super', 0)} / 10000\n\n"
        f"⚔️ <b>Экипировка:</b>\n"
    )
    
    for i, slot in enumerate(['equip1', 'equip2', 'equip3'], 1):
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

@dp.message(Command("quests"))
@dp.message(F.text == "📜 Квесты")
async def cmd_quests(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    now = time.time()
    cd = user.get('quests_cd', 0)
    
    if now < cd:
        left = int(cd - now)
        mins, secs = divmod(left, 60)
        return await message.answer(f"⏳ <b>Квесты выполнены!</b>\nВозвращайтесь через {mins} мин. {secs} сек.")
    
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
        
    text += "\n🎁 <b>Награды за Топ (выдаются каждые 2 дня):</b>\n"
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
            text += f"{bracket_names[b]}: {', '.join(r_strs)}\n"
            
    if not has_rewards:
        text += "<i>Награды пока не настроены администратором.</i>"
        
    await message.answer(text)

@dp.message(Command("shop"))
@dp.message(F.text == "🛒 Магазин")
async def cmd_shop(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (message.from_user.id,))
    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    
    if not items:
        return await message.answer("🛒 Магазин пока пуст. Ближайший завоз скоро!")
        
    text = f"🛒 <b>Глобальный Магазин</b>\n💰 Твой баланс: {user['coins']} шекелей\n<i>(Товары общие для всех. Успей купить!)</i>\n\n"
    
    kb = []
    for i, item in enumerate(items, 1):
        text += f"📦 <b>{item['name']}</b>\n💵 Цена: <b>{item['price']} 💰</b>\n📉 Осталось в мире: {item['stock']} шт.\n\n"
        kb.append([InlineKeyboardButton(text=f"Купить: {item['name']} ({item['price']} 💰)", callback_data=f"buy_shop_{item['id']}")])
        
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_shop_"))
async def callback_buy_shop(callback: types.CallbackQuery):
    shop_id = int(callback.data.split("_")[2])
    user_id = callback.from_user.id
    
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (user_id,))
    item = await fetch_one("SELECT * FROM shop_items WHERE id = ?", (shop_id,))
    
    if not item or item['stock'] <= 0: return await callback.answer("❌ Этот товар закончился!", show_alert=True)
    if user['coins'] < item['price']: return await callback.answer("❌ Недостаточно шекелей!", show_alert=True)
    
    await execute_db("UPDATE users SET coins = coins - ? WHERE id = ?", (item['price'], user_id))
    await execute_db("UPDATE shop_items SET stock = stock - 1 WHERE id = ?", (shop_id,))
    
    await add_quest_progress(user_id, 'q_shop_buys', 1)
    
    i_type = item['item_type']
    luck_mult, _ = await get_active_events()
    
    if i_type.endswith("_rnd"):
        count = int(i_type.split("_")[0])
        won = await give_multiple_cards(user_id, count)
        
        await add_quest_progress(user_id, 'q_cards_opened', count)
        if any(c['rarity'] == 'Rare' for c in won):
            await add_quest_progress(user_id, 'q_rare_obtained', 1)
            
        if count == 1: 
            mut_str = "🌈 " if won[0]['mutation'] == 'Rainbow' else ("⭐ " if won[0]['mutation'] == 'Gold' else "")
            msg = f"🛍 <b>Покупка успешна!</b>\nВы выбили: {mut_str}{format_card_name(won[0])}"
        else: msg = f"🛍 <b>Успешно! Вы открыли пак из {count} карт!</b>\nПосмотрите новинки в 🎒 Инвентаре."
        await callback.message.answer(msg)
        
    elif i_type.startswith("rnd_"):
        rarity_map = {"rnd_leg": "Legendary", "rnd_myth": "Mythic", "rnd_sup": "Super"}
        target_rarity = rarity_map[i_type]
        
        all_cards = await fetch_all("SELECT * FROM cards WHERE rarity = ?", (target_rarity,))
        if not all_cards:
            await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (item['price'], user_id))
            return await callback.message.answer("❌ Ошибка: В базе нет карт такой редкости! Шекели возвращены.")
            
        won_card = random.choice(all_cards)
        mut = roll_mutation(luck_mult)
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        won_card['serial_number'] = serial
        
        await add_quest_progress(user_id, 'q_cards_opened', 1)
        if won_card['rarity'] == 'Rare':
            await add_quest_progress(user_id, 'q_rare_obtained', 1)
        
        mut_str = "🌈 Радужная" if mut == 'Rainbow' else ("⭐ Золотая" if mut == 'Gold' else "Обычная")
        await callback.message.answer(f"🛍 <b>Покупка успешна!</b>\nГарантированная редкость {target_rarity}!\nВы выбили: {format_card_name(won_card)}\nМутация: {mut_str}")

    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    if not items:
        await callback.message.edit_text("🛒 <b>Магазин полностью распродан!</b>\nЖдите следующего завоза.")
    else:
        text = f"🛒 <b>Глобальный Магазин</b>\n💰 Твой баланс: {user['coins'] - item['price']} шекелей\n\n"
        kb = []
        for i, itm in enumerate(items, 1):
            text += f"📦 <b>{itm['name']}</b>\n💵 Цена: <b>{itm['price']} 💰</b>\n📉 Осталось в мире: {itm['stock']} шт.\n\n"
            kb.append([InlineKeyboardButton(text=f"Купить: {itm['name']} ({itm['price']} 💰)", callback_data=f"buy_shop_{itm['id']}")])
        try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        except: pass
    
    await callback.answer()

# ========================================================================
# СИСТЕМА ГАЧИ (ВЫБИВАНИЕ КАРТ) И МУТАЦИИ
# ========================================================================
@dp.message(Command("getcard"))
@dp.message(F.text == "🎴 Выбить карту")
async def cmd_getcard(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    luck_mult, cd_mult = await get_active_events()
    # Кулдаун уменьшен до 4 минут
    base_cooldown = 4 * 60
    actual_cooldown = int(base_cooldown / cd_mult)
    
    now = time.time()
    passed = now - user['last_getcard']
    
    if passed < actual_cooldown:
        left = int(actual_cooldown - passed)
        mins, secs = divmod(left, 60)
        return await message.answer(f"⏳ <b>Колода перемешивается!</b>\nВозвращайся через {mins} мин. {secs} сек.")
        
    all_cards = await fetch_all("SELECT * FROM cards WHERE drop_chance > 0 AND rarity != 'Leaderboard'")
    if not all_cards: return await message.answer("😔 В базе пока нет доступных для выбивания карт.")
        
    weights = [c['drop_chance'] * (luck_mult if c['drop_chance'] < 15.0 else 1.0) for c in all_cards]
    
    # Расчет Pity при выбивании одной карты
    pm, ps = user.get('pity_mythic', 0), user.get('pity_super', 0)
    pm += 1
    ps += 1
    
    super_cards = [c for c in all_cards if c['rarity'] == 'Super']
    mythic_cards = [c for c in all_cards if c['rarity'] == 'Mythic']
    
    if ps >= 10000 and super_cards:
        won_card = random.choice(super_cards)
        ps = 0
    elif pm >= 1000 and mythic_cards:
        won_card = random.choice(mythic_cards)
        pm = 0
    else:
        won_card = random.choices(all_cards, weights=weights, k=1)[0]
        if won_card['rarity'] == 'Super': ps = 0
        if won_card['rarity'] == 'Mythic': pm = 0
    
    mutation = roll_mutation(luck_mult)
    _, serial, _ = await give_card_to_user(user['id'], won_card['id'], mutation, won_card['rarity'])
    won_card['serial_number'] = serial
        
    await execute_db("UPDATE users SET last_getcard = ?, pity_mythic = ?, pity_super = ? WHERE id = ?", (now, pm, ps, user['id']))
    
    await add_quest_progress(user['id'], 'q_cards_opened', 1)
    if won_card['rarity'] == 'Rare':
        await add_quest_progress(user['id'], 'q_rare_obtained', 1)
    
    n_fmt = format_card_name(won_card)
    rarity_text = format_rarity_display(won_card['rarity'])
    
    mult = get_mutation_multiplier(mutation)
    mut_str = ""
    if mutation == "Gold": mut_str = "⭐ <b>ЗОЛОТАЯ! (+10% Статов)</b>\n"
    elif mutation == "Rainbow": mut_str = "🌈 <b>РАДУЖНАЯ! (+20% Статов)</b>\n"
    
    msg = f"🎉 <b>ВЫ ВЫБИЛИ КАРТУ!</b>\n\n{mut_str}🃏 {n_fmt}\n💎 <b>Редкость:</b> {rarity_text}\n"
    
    if won_card['class_type'] == 'Booster': 
        msg += f"✨ <b>БУСТЕР</b>\n⚔️ Урон: x{round(won_card['booster_dmg_mult']*mult, 2)} | ❤️ ХП: x{round(won_card['booster_hp_mult']*mult, 2)}\n\n"
    else: 
        msg += f"⚔️ <b>Урон:</b> {int(won_card['damage']*mult)} | ❤️ <b>Здоровье:</b> {int(won_card['hp']*mult)}\n\n"
        
    if luck_mult > 1.0 and won_card['drop_chance'] < 15.0:
        msg += f"🍀 <i>Сработал ивент удачи!</i>\n"
        
    await message.answer_photo(photo=won_card['photo_id'], caption=msg)

# ========================================================================
# ПАГИНАЦИЯ ИНДЕКСА И ИНВЕНТАРЯ
# ========================================================================
async def get_index_text(user_id: int, page: int = 0, items_per_page: int = 8):
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
    
    text = f"📖 <b>Мировой Индекс Карт (Стр. {page+1}/{total_pages})</b>\n"
    if luck_mult > 1.0: text += f"🍀 <b>ИВЕНТ УДАЧИ АКТИВЕН (x{luck_mult})! Шансы пересчитаны!</b>\n"
    text += "\n"
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = all_cards[start_idx:end_idx]
    
    for i, c in enumerate(page_items, start_idx + 1):
        # Исключаем суперадмина из общего подсчета существующих карт!
        inv_stats = await fetch_all("SELECT mutation, SUM(count) as c FROM inventory WHERE card_id = ? AND user_id != ? GROUP BY mutation", (c['id'], SUPER_ADMIN_ID))
        total_exists = sum(item['c'] for item in inv_stats if item['c'])
        
        mut_texts = []
        for st in inv_stats:
            if st['mutation'] == 'Gold' and st['c'] > 0: mut_texts.append(f"⭐ Золотых: {st['c']}")
            if st['mutation'] == 'Rainbow' and st['c'] > 0: mut_texts.append(f"🌈 Радужных: {st['c']}")
            
        mut_str = f"\n  └ <i>Из них: {', '.join(mut_texts)}</i>" if mut_texts else ""
        
        n_fmt = format_card_name(c)
        r_fmt = format_rarity_display(c['rarity'])
        
        real_chance = (weights_dict.get(c['id'], 0) / total_w) * 100 if total_w > 0 else 0
        chance_str = f"Шанс выпадения: {real_chance:.4f}%" if c['rarity'] != 'Leaderboard' else "Выдается только за Топ!"
        
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
        n_fmt = format_card_name(item)
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

# ========================================================================
# ЭКИПИРОВКА (ИНЛАЙН)
# ========================================================================
def get_equip_main_keyboard(user_info, cards_info):
    kb = []
    for i, slot in enumerate(['equip1', 'equip2', 'equip3'], 1):
        c_id = user_info[slot]
        text = f"Слот {i} [Пусто]" if c_id == 0 else f"Слот {i} [{cards_info.get(c_id, f'ID: {c_id}')}]"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"eq_select_{i}")])
    kb.append([InlineKeyboardButton(text="❌ Снять всё", callback_data="eq_clear")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("equip"))
@dp.message(F.text == "🛡 Экипировка")
async def cmd_equip(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (message.from_user.id,))
    c_ids = [c for c in [user['equip1'], user['equip2'], user['equip3']] if c != 0]
    cards_info = {}
    if c_ids:
        c_list = ",".join(map(str, c_ids))
        res = await fetch_all(f"SELECT id, name FROM cards WHERE id IN ({c_list})")
        for r in res: cards_info[r['id']] = r['name']
    await message.answer("🛡 <b>Настройка Боевой Колоды</b>\n\nНажмите на слот (мутации применяются в бою автоматически):", reply_markup=get_equip_main_keyboard(user, cards_info))

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
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (callback.from_user.id,))
    if card_id in [user['equip1'], user['equip2'], user['equip3']]:
        return await callback.answer("❌ Уже экипирована!", show_alert=True)
    await execute_db(f"UPDATE users SET equip{slot_num} = ? WHERE id = ?", (card_id, callback.from_user.id))
    card = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
    await callback.message.edit_text(f"✅ Карта <b>{card['name']}</b> установлена в Слот {slot_num}!")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "eq_clear")
async def equip_clear_callback(callback: types.CallbackQuery):
    await execute_db("UPDATE users SET equip1=0, equip2=0, equip3=0 WHERE id = ?", (callback.from_user.id,))
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (callback.from_user.id,))
    await callback.message.edit_text("✅ Все слоты очищены.", reply_markup=get_equip_main_keyboard(user, {}))
    await callback.answer()

# ========================================================================
# БОЕВОЙ ДВИЖОК И БАЛАНС
# ========================================================================
async def get_team_data(user_id: int):
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (user_id,))
    team = []
    for slot in ['equip1', 'equip2', 'equip3']:
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
                card['burn'] = 0     
                card['dmg_buff'] = 0 
                team.append(card)
    return team

# бронза: Basic, Uncommon, rare Rare
# сильвер: Uncommon, Rare, rare Epic
# голд: Rare, Epic, rare Legendary
# платина: Epic, Legendary, rare Mythic
# даймонд: Legendary, Mythic, rare Super
# рубин: Mythic, Super
async def get_bot_team(user_id: int, difficulty_mult: float):
    user = await fetch_one("SELECT trophies FROM users WHERE id = ?", (user_id,))
    rank = await get_user_rank(user['trophies'])
    rank_base = rank['name'].split()[0]
    
    rank_rarities = {
        "Bronze": [("Basic", 0.6), ("Uncommon", 0.35), ("Rare", 0.05)],
        "Silver": [("Uncommon", 0.6), ("Rare", 0.35), ("Epic", 0.05)],
        "Gold": [("Rare", 0.6), ("Epic", 0.35), ("Legendary", 0.05)],
        "Platina": [("Epic", 0.6), ("Legendary", 0.35), ("Mythic", 0.05)],
        "Diamond": [("Legendary", 0.6), ("Mythic", 0.35), ("Super", 0.05)],
        "Ruby": [("Mythic", 0.7), ("Super", 0.3)]
    }
    
    base_chances = rank_rarities.get(rank_base, rank_rarities["Bronze"])
    
    adjusted_chances = []
    for r_name, r_chance in base_chances:
        if r_chance < 0.5:
            adj = r_chance * (difficulty_mult ** 1.5)
        else:
            adj = r_chance
        adjusted_chances.append((r_name, adj))
        
    total_w = sum(c[1] for c in adjusted_chances)
    final_chances = [(c[0], c[1]/total_w) for c in adjusted_chances]

    all_cards_db = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE rarity != 'Leaderboard'")
    if len(all_cards_db) < 3: return []
    
    cards_by_rarity = {}
    for c in all_cards_db:
        cards_by_rarity.setdefault(c['rarity'], []).append(c)
        
    team_copies = []
    for _ in range(3):
        r = random.random()
        cumulative = 0.0
        chosen_rarity = final_chances[0][0]
        for r_name, r_chance in final_chances:
            cumulative += r_chance
            if r <= cumulative:
                chosen_rarity = r_name
                break
                
        if not cards_by_rarity.get(chosen_rarity):
            flat_list = [c for sub in cards_by_rarity.values() for c in sub]
            if flat_list: chosen_card = random.choice(flat_list)
            else: return []
        else:
            chosen_card = random.choice(cards_by_rarity[chosen_rarity])
            
        c_copy = dict(chosen_card)
        c_copy['max_hp'] = c_copy['hp']

        mut_chance = random.random()
        diff_factor = max(1.0, difficulty_mult)
        if mut_chance < 0.15 * diff_factor:
            c_copy['mutation'] = "Rainbow"
            c_copy['damage'] = int(c_copy['damage'] * 1.2)
            c_copy['hp'] = int(c_copy['hp'] * 1.2)
        elif mut_chance < 0.45 * diff_factor:
            c_copy['mutation'] = "Gold"
            c_copy['damage'] = int(c_copy['damage'] * 1.1)
            c_copy['hp'] = int(c_copy['hp'] * 1.1)
        else:
            c_copy['mutation'] = "Normal"

        c_copy['max_hp'] = c_copy['hp']
        c_copy['burn'] = 0
        c_copy['dmg_buff'] = 0
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
        if c.get('burn', 0) > 0: status += "🔥"
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

async def run_battle_loop(bot: Bot, chat_id: int, p1_id: int, p1_name: str, p2_id: int, p2_name: str, t1: list, t2: list, diff_trophies_scale: float = 1.0, is_pvp: bool = False, pvp_no_rewards: bool = False):
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
            user = await fetch_one("SELECT trophies FROM users WHERE id = ?", (p1_id,))
            rank = await get_user_rank(user['trophies'])
            
            # Получение монет на 15% сложнее (применен множитель 0.85)
            coins_won = int(random.randint(25, 90) * rank['reward_mult'] * diff_trophies_scale * 0.85)
            won_t = await get_dynamic_trophies(rank['name'], diff_trophies_scale)
            
            await execute_db("UPDATE users SET coins = coins + ?, trophies = trophies + ? WHERE id = ?", (coins_won, won_t, p1_id))
            final_text += f"🎉 Вы получили: <b>{coins_won} 💰 Шекелей</b> и <b>{won_t} 🏆</b>"
        elif winner == p2_name:
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 2) WHERE id = ?", (p1_id,))
            final_text += f"💀 Вы проиграли ИИ и потеряли 2 🏆."
            
    await msg.edit_text(final_text)
    active_combats.discard(p1_id)
    if is_pvp: active_combats.discard(p2_id)

@dp.message(F.text == "⚔️ Поиск боя (боты)")
async def cmd_pve_select(message: types.Message):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats:
        return await message.answer("❌ Вы уже находитесь в бою или в поиске!")
        
    team1 = await get_team_data(message.from_user.id)
    if not team1: return await message.answer("❌ Экипируйте карты в 🛡 Экипировка!")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Лёгкий (-50% Кубков)", callback_data="pve_diff_easy")],
        [InlineKeyboardButton(text="🟡 Средний (Стандарт)", callback_data="pve_diff_med")],
        [InlineKeyboardButton(text="🔴 Сложный (+50% Кубков)", callback_data="pve_diff_hard")]
    ])
    await message.answer("⚔️ <b>Выберите сложность ИИ:</b>", reply_markup=kb)

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
        trophies_scale = 0.5
        diff_name = "Лёгкий"
    elif diff_type == "med":
        power_mult = 1.1  
        trophies_scale = 1.0
        diff_name = "Средний"
    elif diff_type == "hard":
        power_mult = 1.6  
        trophies_scale = 1.5
        diff_name = "Сложный"
        
    await callback.message.edit_text(f"⚔️ Ищем бота... Сложность: <b>{diff_name}</b>")
    
    team1 = await get_team_data(callback.from_user.id)
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    rank = await get_user_rank(user['trophies'])
    
    final_diff_mult = rank['difficulty_mult'] * power_mult
    team2 = await get_bot_team(callback.from_user.id, final_diff_mult)
    
    if not team2: return await callback.message.edit_text("❌ На сервере нет карт для бота.")
        
    p1_name = get_display_name(user)
    active_combats.add(callback.from_user.id)
    
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, callback.from_user.id, p1_name, 0, f"ИИ ({diff_name})", team1, team2, trophies_scale, is_pvp=False))
    await callback.answer()

# ========================================================================
# ДУЭЛИ (PVP) СИНХРОННЫЕ
# ========================================================================
@dp.message(F.text == "⚔️ PvP Дуэль")
async def cmd_pvp_request_start(message: types.Message, state: FSMContext):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats:
        return await message.answer("❌ Вы уже в бою!")
    await message.answer("⚔️ <b>PvP Дуэль</b>\nВведите @username или ID игрока, которого вы хотите вызвать на дружескую дуэль:")
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
        
    if target_user['id'] in active_combats:
        await state.clear()
        return await message.answer("❌ Игрок сейчас находится в бою!")

    if target_user['id'] in active_trades_users:
        await state.clear()
        return await message.answer("❌ Игрок занят обменом!")
        
    challenger = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    challenger_name = get_display_name(challenger)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⚔️ Принять дуэль", callback_data=f"pvp_accept_{challenger['id']}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pvp_decline_{challenger['id']}")
        ]
    ])
    
    try:
        await bot.send_message(
            target_user['id'], 
            f"⚔️ Игрок <b>{challenger_name}</b> вызывает вас на дружескую дуэль!\n\nУ вас должна быть экипирована колода.",
            reply_markup=kb
        )
        await message.answer(f"📨 Вызов отправлен игроку {get_display_name(target_user)}. Ждем ответа...")
    except Exception:
        await message.answer("❌ Не удалось отправить уведомление игроку (возможно, бот заблокирован).")
    await state.clear()

@dp.callback_query(F.data.startswith("pvp_accept_"))
async def callback_pvp_accept(callback: types.CallbackQuery):
    challenger_id = int(callback.data.split("_")[2])
    target_id = callback.from_user.id
    
    if target_id in active_combats or challenger_id in active_combats:
        return await callback.answer("❌ One of the players is busy!", show_alert=True)
        
    t1 = await get_team_data(challenger_id)
    t2 = await get_team_data(target_id)
    
    if not t1:
        return await callback.message.edit_text("❌ У вызывающего игрока пустая колода экипировки! Дуэль отменена.")
    if not t2:
        return await callback.message.edit_text("❌ У вас не экипирована колода! Экипируйте карты в 🛡 Экипировка и примите вызов заново.")
        
    challenger = await fetch_one("SELECT * FROM users WHERE id = ?", (challenger_id,))
    target = await fetch_one("SELECT * FROM users WHERE id = ?", (target_id,))
    
    p1_name = get_display_name(challenger)
    p2_name = get_display_name(target)
    
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
    msg2 = await bot.send_message(p2_id, f"⚔️ Дуэль против <b>{p1_name}</b> начнется через 3... сек!")
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
        f"🏁 <b>ИТОГИ ДУЭЛИ: {p1_name} VS {p2_name}</b>\n\n"
        f"👑 <b>Победитель: {winner}</b>\n\n"
        f"🤝 Награды и кубки за товарищеский бой отсутствуют!"
    )
    
    try: await msg1.edit_text(final_text)
    except: pass
    try: await msg2.edit_text(final_text)
    except: pass
    
    active_combats.discard(p1_id)
    active_combats.discard(p2_id)

# ========================================================================
# СИСТЕМА ОБМЕНА КАРТАМИ (ТРЕЙДЫ) - ОПТИМИЗИРОВАНО
# ========================================================================
@dp.message(F.text == "🤝 Трейды")
async def cmd_trade_start(message: types.Message, state: FSMContext):
    if await check_ban(message.from_user.id): return
    
    now_ts = time.time()
    stale_trades = []
    for t_id, t_data in list(active_trades.items()):
        if now_ts - t_data.get('created_at', 0) > 300: 
            stale_trades.append(t_id)
    for t_id in stale_trades:
        t_data = active_trades.get(t_id)
        if t_data:
            p1 = t_data['p1']
            p2 = t_data['p2']
            active_trades_users.discard(p1)
            active_trades_users.discard(p2)
            active_trades.pop(t_id, None)
            try: await bot.send_message(p1, "⏳ Время сессии обмена вышло (5 минут). Обмен аннулирован.")
            except: pass
            try: await bot.send_message(p2, "⏳ Время сессии обмена вышло (5 минут). Обмен аннулирован.")
            except: pass

    is_in_any_active_trade = False
    for t_data in active_trades.values():
        if message.from_user.id in [t_data['p1'], t_data['p2']]:
            is_in_any_active_trade = True
            break
    if message.from_user.id in active_trades_users and not is_in_any_active_trade:
        active_trades_users.discard(message.from_user.id)

    if message.from_user.id in active_trades_users or message.from_user.id in active_combats:
        return await message.answer("❌ Вы не можете начать обмен в данный момент (вы уже заняты обменом или боем)!")
        
    await message.answer("🤝 <b>Предложение обмена</b>\nВведите @username или ID игрока, с которым вы хотите провести трейд:")
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
        return await message.answer("❌ Этот игрок не найден в базе данных.")
        
    if target_user['id'] == message.from_user.id:
        await state.clear()
        return await message.answer("❌ Вы не можете торговать с самим собой!")

    is_target_in_any_trade = False
    for t_data in active_trades.values():
        if target_user['id'] in [t_data['p1'], t_data['p2']]:
            is_target_in_any_trade = True
            break
    if target_user['id'] in active_trades_users and not is_target_in_any_trade:
        active_trades_users.discard(target_user['id'])
        
    if target_user['id'] in active_trades_users or target_user['id'] in active_combats:
        await state.clear()
        return await message.answer("❌ Игрок сейчас занят другим обменом или боем.")
        
    initiator = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    initiator_name = get_display_name(initiator)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🤝 Принять трейд", callback_data=f"tr_invite_accept_{initiator['id']}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"tr_invite_decline_{initiator['id']}")
        ]
    ])
    
    try:
        await bot.send_message(
            target_user['id'], 
            f"🤝 Игрок <b>{initiator_name}</b> предлагает вам совершить обмен карточками!",
            reply_markup=kb
        )
        await message.answer(f"📨 Предложение обмена успешно отправлено игроку {get_display_name(target_user)}. Ждем его согласия...")
    except Exception:
        await message.answer("❌ Не удалось отправить предложение (возможно, игрок заблокировал бота).")
    await state.clear()

@dp.callback_query(F.data.startswith("tr_invite_accept_"))
async def callback_trade_invite_accept(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[3])
    p2_id = callback.from_user.id
    
    if p1_id in active_trades_users or p2_id in active_trades_users:
        return await callback.answer("❌ Один из участников обмена уже занят другим трейдом!", show_alert=True)
        
    active_trades_users.add(p1_id)
    active_trades_users.add(p2_id)
    
    trade_id = f"{p1_id}_{p2_id}"
    
    p1_user = await fetch_one("SELECT * FROM users WHERE id = ?", (p1_id,))
    p2_user = await fetch_one("SELECT * FROM users WHERE id = ?", (p2_id,))
    
    active_trades[trade_id] = {
        "p1": p1_id,
        "p2": p2_id,
        "p1_name": get_display_name(p1_user),
        "p2_name": get_display_name(p2_user),
        "p1_cards": {}, 
        "p2_cards": {}, 
        "p1_accepted": False,
        "p2_accepted": False,
        "p1_msg_id": None,
        "p2_msg_id": None,
        "created_at": time.time()
    }
    
    await callback.message.delete()
    
    await send_trade_boards(trade_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_invite_decline_"))
async def callback_trade_invite_decline(callback: types.CallbackQuery):
    p1_id = int(callback.data.split("_")[3])
    p2_name = get_display_name(await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,)))
    try:
        await bot.send_message(p1_id, f"❌ Игрок <b>{p2_name}</b> отклонил ваше предложение обмена.")
    except: pass
    await callback.message.edit_text("❌ Вы отклонили предложение обмена.")
    await callback.answer()

async def get_trade_board_text_and_kb(trade_id: str, current_user_id: int):
    trade = active_trades.get(trade_id)
    if not trade:
        return "❌ Обмен не найден или завершен.", None
        
    p1_id = trade['p1']
    p2_id = trade['p2']
    
    p1_offer_strs = []
    if trade['p1_cards']:
        inv_ids = ",".join(map(str, trade['p1_cards'].keys()))
        rows = await fetch_all(f"SELECT i.id, c.name, c.rarity, i.mutation, i.serial_number FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.id IN ({inv_ids})")
        for r in rows:
            count = trade['p1_cards'][r['id']]
            n_fmt = format_card_name(r)
            p1_offer_strs.append(f"• {n_fmt} — {count} шт.")
    else:
        p1_offer_strs.append("<i>Ничего не предложено</i>")
        
    p2_offer_strs = []
    if trade['p2_cards']:
        inv_ids = ",".join(map(str, trade['p2_cards'].keys()))
        rows = await fetch_all(f"SELECT i.id, c.name, c.rarity, i.mutation, i.serial_number FROM inventory i JOIN cards c ON i.card_id = c.id WHERE i.id IN ({inv_ids})")
        for r in rows:
            count = trade['p2_cards'][r['id']]
            n_fmt = format_card_name(r)
            p2_offer_strs.append(f"• {n_fmt} — {count} шт.")
    else:
        p2_offer_strs.append("<i>Ничего не предложено</i>")
        
    st_p1 = "✅ Подтвердил" if trade['p1_accepted'] else "⏳ Подготавливает предложение"
    st_p2 = "✅ Подтвердил" if trade['p2_accepted'] else "⏳ Подготавливает предложение"
    
    text = (
        f"🤝 <b>ОБМЕН КАРТАМИ В РЕАЛЬНОМ ВРЕМЕНИ</b>\n\n"
        f"🔵 <b>Игрок {trade['p1_name']}:</b>\n" + "\n".join(p1_offer_strs) + f"\n└ Статус: <i>{st_p1}</i>\n\n"
        f"🔴 <b>Игрок {trade['p2_name']}:</b>\n" + "\n".join(p2_offer_strs) + f"\n└ Статус: <i>{st_p2}</i>\n\n"
        f"⚠️ Любое изменение сбрасывает статус вашего подтверждения."
    )
    
    btn_confirm_text = "✅ Подтвердить обмен" if not ((current_user_id == p1_id and trade['p1_accepted']) or (current_user_id == p2_id and trade['p2_accepted'])) else "⏳ Отменить подтверждение"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить карточку", callback_data=f"tr_addlist_{trade_id}_0")],
        [InlineKeyboardButton(text="🧹 Очистить мое предложение", callback_data=f"tr_clear_{trade_id}")],
        [InlineKeyboardButton(text=btn_confirm_text, callback_data=f"tr_confirm_{trade_id}")],
        [InlineKeyboardButton(text="⛔ Отклонить трейд", callback_data=f"tr_decline_{trade_id}")]
    ])
    
    return text, kb

async def send_trade_boards(trade_id: str):
    trade = active_trades.get(trade_id)
    if not trade: return
    
    t1, k1 = await get_trade_board_text_and_kb(trade_id, trade['p1'])
    t2, k2 = await get_trade_board_text_and_kb(trade_id, trade['p2'])
    
    m1 = await bot.send_message(trade['p1'], t1, reply_markup=k1)
    m2 = await bot.send_message(trade['p2'], t2, reply_markup=k2)
    
    trade['p1_msg_id'] = m1.message_id
    trade['p2_msg_id'] = m2.message_id

async def update_trade_boards(trade_id: str):
    trade = active_trades.get(trade_id)
    if not trade: return
    
    for role in ['p1', 'p2']:
        user_id = trade[role]
        msg_id = trade[f"{role}_msg_id"]
        text, kb = await get_trade_board_text_and_kb(trade_id, user_id)
        
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=msg_id, text=text, reply_markup=kb)
        except TelegramAPIError as e:
            if "message is not modified" in str(e).lower():
                continue
            try:
                new_m = await bot.send_message(chat_id=user_id, text=text, reply_markup=kb)
                trade[f"{role}_msg_id"] = new_m.message_id
            except Exception as ex:
                logging.error(f"Не удалось воссоздать панель трейда для {user_id}: {ex}")

@dp.callback_query(F.data.startswith("tr_addlist_"))
async def callback_trade_addlist(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    trade_id = f"{parts[2]}_{parts[3]}"
    page = int(parts[4])
    
    trade = active_trades.get(trade_id)
    if not trade:
        return await callback.answer("❌ Обмен завершен или отменен.", show_alert=True)
        
    user_id = callback.from_user.id
    
    inv_items = await fetch_all("""
        SELECT i.id, c.name, c.rarity, i.count, i.mutation, i.serial_number 
        FROM inventory i JOIN cards c ON i.card_id = c.id 
        WHERE i.user_id = ?
    """, (user_id,))
    
    if not inv_items:
        return await callback.answer("🎒 Ваш инвентарь пуст!", show_alert=True)
        
    btn_items = []
    for item in inv_items:
        user_offers = trade['p1_cards'] if user_id == trade['p1'] else trade['p2_cards']
        in_trade = user_offers.get(item['id'], 0)
        available = item['count'] - in_trade
        
        if available <= 0:
            continue
            
        r_em = RARITY_EMOJI.get(item['rarity'], "⚪")
        mut_emoji = "⭐ " if item['mutation'] == 'Gold' else ("🌈 " if item['mutation'] == 'Rainbow' else "")
        s_str = f" [#{item['serial_number']:04d}]" if item['serial_number'] > 0 else ""
        
        btn_items.append({
            "id": item['id'],
            "btn_text": f"{mut_emoji}{r_em} {item['name']}{s_str} (Доступно: {available})"
        })
        
    if not btn_items:
        return await callback.answer("❌ Вы выставили на обмен максимум копий всех своих карт!", show_alert=True)
        
    items_per_page = 6
    total_pages = max(1, math.ceil(len(btn_items) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = btn_items[start_idx:end_idx]
    
    kb_list = []
    for item in page_items:
        kb_list.append([InlineKeyboardButton(text=item['btn_text'], callback_data=f"tr_addcard_{trade_id}_{item['id']}")])
        
    nav_row = []
    if page > 0: nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"tr_addlist_{trade_id}_{page-1}"))
    if total_pages > 1: nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1: nav_row.append(InlineKeyboardButton(text="Вперед ➡️", callback_data=f"tr_addlist_{trade_id}_{page+1}"))
    if nav_row: kb_list.append(nav_row)
    
    kb_list.append([InlineKeyboardButton(text="🔙 Назад к доске трейда", callback_data=f"tr_board_{trade_id}")])
    
    await callback.message.edit_text("👇 Выберите карточку для добавления в трейд:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_list))
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_addcard_"))
async def callback_trade_addcard(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    trade_id = f"{parts[2]}_{parts[3]}"
    inv_id = int(parts[4])
    
    trade = active_trades.get(trade_id)
    if not trade:
        return await callback.answer("❌ Обмен завершен или отменен.", show_alert=True)
        
    user_id = callback.from_user.id
    offers = trade['p1_cards'] if user_id == trade['p1'] else trade['p2_cards']
    
    inv_row = await fetch_one("SELECT count FROM inventory WHERE id = ? AND user_id = ?", (inv_id, user_id))
    if not inv_row:
        return await callback.answer("❌ Ошибка владения карточкой.", show_alert=True)
        
    current_in_trade = offers.get(inv_id, 0)
    if current_in_trade >= inv_row['count']:
        return await callback.answer("❌ У вас больше нет копий этой карты!", show_alert=True)
        
    offers[inv_id] = current_in_trade + 1
    
    trade['p1_accepted'] = False
    trade['p2_accepted'] = False
    
    await update_trade_boards(trade_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_board_"))
async def callback_trade_board_return(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    trade_id = f"{parts[2]}_{parts[3]}"
    
    trade = active_trades.get(trade_id)
    if not trade:
        return await callback.message.edit_text("❌ Обмен завершен или отменен.")
        
    await update_trade_boards(trade_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_clear_"))
async def callback_trade_clear(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    trade_id = f"{parts[2]}_{parts[3]}"
    
    trade = active_trades.get(trade_id)
    if not trade: return await callback.answer("❌ Трейд завершен.", show_alert=True)
    
    user_id = callback.from_user.id
    if user_id == trade['p1']:
        trade['p1_cards'].clear()
    else:
        trade['p2_cards'].clear()
        
    trade['p1_accepted'] = False
    trade['p2_accepted'] = False
    
    await update_trade_boards(trade_id)
    await callback.answer("🧹 Ваше предложение полностью очищено.")

@dp.callback_query(F.data.startswith("tr_decline_"))
async def callback_trade_decline(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    trade_id = f"{parts[2]}_{parts[3]}"
    
    trade = active_trades.get(trade_id)
    if not trade: return await callback.answer()
    
    p1 = trade['p1']
    p2 = trade['p2']
    
    active_trades_users.discard(p1)
    active_trades_users.discard(p2)
    active_trades.pop(trade_id, None)
    
    try: await bot.send_message(p1, "❌ Обмен картами отменен одним из игроков.")
    except: pass
    try: await bot.send_message(p2, "❌ Обмен картами отменен одним из игроков.")
    except: pass
    
    try: await bot.delete_message(p1, trade['p1_msg_id'])
    except: pass
    try: await bot.delete_message(p2, trade['p2_msg_id'])
    except: pass
    
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_confirm_"))
async def callback_trade_confirm(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    trade_id = f"{parts[2]}_{parts[3]}"
    
    trade = active_trades.get(trade_id)
    if not trade: return await callback.answer("❌ Обмен не найден.", show_alert=True)
    
    user_id = callback.from_user.id
    if user_id == trade['p1']:
        trade['p1_accepted'] = not trade['p1_accepted']
    else:
        trade['p2_accepted'] = not trade['p2_accepted']
        
    if trade['p1_accepted'] and trade['p2_accepted']:
        p1 = trade['p1']
        p2 = trade['p2']
        
        db = await get_db_connection()
        try:
            for inv_id, count in list(trade['p1_cards'].items()):
                cursor = await db.execute("SELECT * FROM inventory WHERE id = ? AND user_id = ?", (inv_id, p1))
                row = await cursor.fetchone()
                if not row or row['count'] < count:
                    raise ValueError("Ошибка валидации трейда: Недостаточно карт.")
                
                card_id = row['card_id']
                mutation = row['mutation']
                serial = row['serial_number']
                
                if row['count'] == count:
                    await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
                    for slot in ['equip1', 'equip2', 'equip3']:
                        await db.execute(f"UPDATE users SET {slot} = 0 WHERE id = ? AND {slot} = ?", (p1, card_id))
                else:
                    await db.execute("UPDATE inventory SET count = count - ? WHERE id = ?", (count, inv_id))
                
                if serial > 0:
                    await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, ?, ?, ?)", (p2, card_id, count, mutation, serial))
                else:
                    target_row = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0", (p2, card_id, mutation))
                    t_item = await target_row.fetchone()
                    if t_item:
                        await db.execute("UPDATE inventory SET count = count + ? WHERE id = ?", (count, t_item['id']))
                    else:
                        await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, ?, ?, 0)", (p2, card_id, count, mutation))
                        
            for inv_id, count in list(trade['p2_cards'].items()):
                cursor = await db.execute("SELECT * FROM inventory WHERE id = ? AND user_id = ?", (inv_id, p2))
                row = await cursor.fetchone()
                if not row or row['count'] < count:
                    raise ValueError("Ошибка валидации трейда: Недостаточно карт.")
                
                card_id = row['card_id']
                mutation = row['mutation']
                serial = row['serial_number']
                
                if row['count'] == count:
                    await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
                    for slot in ['equip1', 'equip2', 'equip3']:
                        await db.execute(f"UPDATE users SET {slot} = 0 WHERE id = ? AND {slot} = ?", (p2, card_id))
                else:
                    await db.execute("UPDATE inventory SET count = count - ? WHERE id = ?", (count, inv_id))
                
                if serial > 0:
                    await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, ?, ?, ?)", (p1, card_id, count, mutation, serial))
                else:
                    target_row = await db.execute("SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0", (p1, card_id, mutation))
                    t_item = await target_row.fetchone()
                    if t_item:
                        await db.execute("UPDATE inventory SET count = count + ? WHERE id = ?", (count, t_item['id']))
                    else:
                        await db.execute("INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, ?, ?, 0)", (p1, card_id, count, mutation))
                        
            await db.commit()
            
            active_trades_users.discard(p1)
            active_trades_users.discard(p2)
            active_trades.pop(trade_id, None)
            
            try: await bot.send_message(p1, "✅ Обмен успешно завершен! Карты добавлены в инвентарь.")
            except: pass
            try: await bot.send_message(p2, "✅ Обмен успешно завершен! Карты добавлены в инвентарь.")
            except: pass
            
            try: await bot.delete_message(p1, trade['p1_msg_id'])
            except: pass
            try: await bot.delete_message(p2, trade['p2_msg_id'])
            except: pass
            
        except Exception as e:
            await db.rollback()
            logging.error(f"Trade Error: {e}")
            active_trades_users.discard(p1)
            active_trades_users.discard(p2)
            active_trades.pop(trade_id, None)
            try: await bot.send_message(p1, "❌ Произошла ошибка во время транзакции обмена. Трейд отменен в целях безопасности.")
            except: pass
            try: await bot.send_message(p2, "❌ Произошла ошибка во время транзакции обмена. Трейд отменен в целях безопасности.")
            except: pass
        finally:
            await db.close()
    else:
        await update_trade_boards(trade_id)
        await callback.answer()

# ========================================================================
# АДМИН ПАНЕЛЬ И УПРАВЛЕНИЕ
# ========================================================================
@dp.message(Command("forcerewards"))
async def cmd_force_rewards(message: types.Message):
    if not await is_admin(message.from_user.id): return
    await message.answer("🏆 Принудительная выдача наград за Топ инициирована...")
    await distribute_lb_rewards(force=True)
    await message.answer("✅ Награды выданы, таймер сброшен на 2 дня заново, кубки игроков обнулены!")
    await log_admin(message.from_user.id, "Принудительно выдал награды за топ")

@dp.message(Command("admin"))
@dp.message(F.text == "⚙️ Админ-панель")
async def cmd_admin(message: types.Message):
    if not await is_admin(message.from_user.id): return
    
    stats = await fetch_one("SELECT (SELECT COUNT(*) FROM users) as users, (SELECT COUNT(*) FROM cards) as cards")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить карту", callback_data="adm_add_card"), InlineKeyboardButton(text="✏️ Изменить карту", callback_data="adm_edit_card")],
        [InlineKeyboardButton(text="❌ Удалить карту", callback_data="adm_del_card"), InlineKeyboardButton(text="🎁 Выдать карту", callback_data="adm_give_card")],
        [InlineKeyboardButton(text="💰 Выдать монеты", callback_data="adm_give_coins"), InlineKeyboardButton(text="🏆 Выдать кубки", callback_data="adm_give_trophies")],
        [InlineKeyboardButton(text="⛔ Бан / Разбан", callback_data="adm_ban"), InlineKeyboardButton(text="📢 Рассылка", callback_data="adm_announce")],
        [InlineKeyboardButton(text="🍀 Ивент Удачи", callback_data="adm_luck"), InlineKeyboardButton(text="⏳ Ивент КД", callback_data="adm_cd")],
        [InlineKeyboardButton(text="⚙️ Награды Топ-Игроков", callback_data="adm_lb_settings")],
        [InlineKeyboardButton(text="🔄 Сбросить бой/трейд", callback_data="adm_reset_user")],
        [InlineKeyboardButton(text="🛒 Насильно обновить магазин", callback_data="adm_force_restock")]
    ])
    
    text = (
        "⚙️ <b>Панель Администратора</b>\n\n"
        f"👥 Всего пользователей: {stats['users']}\n"
        f"🎴 Всего видов карт: {stats['cards']}\n\n"
        "<i>Используйте кнопки ниже для управления сервером:</i>"
    )
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data == "adm_force_restock")
async def callback_force_restock(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    await restock_shop()
    await callback.answer("✅ Магазин принудительно обновлен!", show_alert=True)
    await log_admin(callback.from_user.id, "Принудительное обновление магазина")

@dp.callback_query(F.data == "adm_reset_user")
async def callback_adm_reset_user(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введите ID пользователя, которому нужно принудительно сбросить статус боя/трейда (освободить):")
    await state.set_state(AdminManage.reset_battle_id)
    await callback.answer()

@dp.message(AdminManage.reset_battle_id)
async def process_adm_reset_user(message: types.Message, state: FSMContext):
    val = message.text.strip()
    if not val.isdigit(): return await message.answer("❌ Неверный ID")
    uid = int(val)
    
    active_combats.discard(uid)
    active_trades_users.discard(uid)
    
    await log_admin(message.from_user.id, f"Сбросил статус (бой/трейд) пользователю {uid}")
    await message.answer(f"✅ Статусы пользователя {uid} сброшены.")
    await state.clear()

@dp.callback_query(F.data == "adm_add_card")
async def adm_add_card(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Отправьте фото для новой карты (сжатое фото):")
    await state.set_state(AddCard.photo)
    await callback.answer()

@dp.message(AddCard.photo, F.photo)
async def process_add_photo(message: types.Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await state.update_data(photo=photo_id)
    await message.answer("Введите название карты:")
    await state.set_state(AddCard.name)

@dp.message(AddCard.name)
async def process_add_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите шанс выпадения (от 0 до 100, например 1.5):")
    await state.set_state(AddCard.drop_chance)

@dp.message(AddCard.drop_chance)
async def process_add_chance(message: types.Message, state: FSMContext):
    try: chance = float(message.text.replace(",", "."))
    except: return await message.answer("Число должно быть дробным.")
    await state.update_data(chance=chance)
    
    kb = ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=r) for r in ["Basic", "Uncommon", "Rare"]],
        [KeyboardButton(text=r) for r in ["Epic", "Legendary", "Mythic"]],
        [KeyboardButton(text=r) for r in ["Super", "Exclusive", "Leaderboard"]]
    ], resize_keyboard=True)
    await message.answer("Выберите редкость:", reply_markup=kb)
    await state.set_state(AddCard.rarity)

@dp.message(AddCard.rarity)
async def process_add_rarity(message: types.Message, state: FSMContext):
    if message.text not in RARITY_COLORS: return await message.answer("Неверная редкость.")
    await state.update_data(rarity=message.text)
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c) for c in CLASSES]], resize_keyboard=True)
    await message.answer("Выберите класс:", reply_markup=kb)
    await state.set_state(AddCard.class_type)

@dp.message(AddCard.class_type)
async def process_add_class(message: types.Message, state: FSMContext):
    if message.text not in CLASSES: return await message.answer("Неверный класс.")
    await state.update_data(class_type=message.text)
    
    if message.text == 'Booster':
        await message.answer("Введите множитель урона для Бустера (например 1.25):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(AddCard.booster_dmg)
    else:
        await message.answer("Введите базовый урон:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(AddCard.damage)

@dp.message(AddCard.booster_dmg)
async def process_add_b_dmg(message: types.Message, state: FSMContext):
    try: b_dmg = float(message.text.replace(",", "."))
    except: return await message.answer("Число должно быть дробным.")
    await state.update_data(damage=0, b_dmg=b_dmg)
    await message.answer("Введите множитель ХП для Бустера (например 1.15):")
    await state.set_state(AddCard.booster_hp)

@dp.message(AddCard.booster_hp)
async def process_add_b_hp(message: types.Message, state: FSMContext):
    try: b_hp = float(message.text.replace(",", "."))
    except: return await message.answer("Число должно быть дробным.")
    
    data = await state.get_data()
    msg = await message.answer("⏳ Генерация рамки (Бустер)...")
    try:
        final_photo = await create_bordered_image(bot, data['photo'], data['rarity'])
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id, booster_dmg_mult, booster_hp_mult) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data['name'], data['rarity'], data['class_type'], 0, 0, data['chance'], final_photo, data['b_dmg'], b_hp)
        )
        await log_admin(message.from_user.id, f"Создал карту-бустер {data['name']}")
        await msg.edit_text("✅ Карта-Бустер добавлена!")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка генерации: {e}")
    finally:
        await state.clear()

@dp.message(AddCard.damage)
async def process_add_dmg(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("Введите целое число.")
    await state.update_data(damage=int(message.text))
    await message.answer("Введите здоровье (ХП):")
    await state.set_state(AddCard.hp)

@dp.message(AddCard.hp)
async def process_add_hp(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("Введите целое число.")
    data = await state.get_data()
    
    msg = await message.answer("⏳ Генерирую красивую рамку...")
    try:
        final_photo = await create_bordered_image(bot, data['photo'], data['rarity'])
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (data['name'], data['rarity'], data['class_type'], data['damage'], int(message.text), data['chance'], final_photo)
        )
        await log_admin(message.from_user.id, f"Создал карту {data['name']}")
        await msg.edit_text("✅ Карта успешно добавлена в базу!")
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {e}")
    finally:
        await state.clear()

@dp.callback_query(F.data == "adm_edit_card")
async def callback_edit_card_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    if not cards: return await callback.answer("В базе нет карт!", show_alert=True)
    
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '⚪')} {c['name']} (ID:{c['id']})"} for c in cards]
    await state.update_data(adm_edit_items=items)
    
    kb = get_pagination_keyboard(items, 0, "adm_ed_c", columns=1, items_per_page=8)
    await callback.message.edit_text("👇 Выберите карту для редактирования:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_ed_c_page_"))
async def callback_edit_card_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[4])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('adm_edit_items', []), page, "adm_ed_c", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("adm_ed_c_"))
async def callback_edit_card_select(callback: types.CallbackQuery, state: FSMContext):
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
async def callback_edit_field_select(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[2]
    await state.update_data(edit_field=field)
    
    if field == "class":
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=c)] for c in CLASSES], resize_keyboard=True)
        await callback.message.answer("Выберите новый класс с клавиатуры:", reply_markup=kb)
    else:
        await callback.message.answer(f"Отправь новое значение для параметра {field}:")
    await callback.answer()

@dp.message(EditCard.waiting_new_value)
async def process_edit_card_save(message: types.Message, state: FSMContext):
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
        await message.answer(reply, reply_markup=get_main_keyboard(True))
        await state.clear()
    except: await message.answer("❌ Неверный формат значения.")

@dp.callback_query(F.data == "adm_del_card")
async def callback_del_card_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введите ID карты для удаления:")
    await state.set_state("waiting_del_id")
    await callback.answer()

@dp.message(StateFilter("waiting_del_id"))
async def process_del_card_finish(message: types.Message, state: FSMContext):
    try:
        c_id = int(message.text)
        await execute_db("DELETE FROM cards WHERE id = ?", (c_id,))
        await execute_db("DELETE FROM inventory WHERE card_id = ?", (c_id,))
        for slot in ['equip1', 'equip2', 'equip3']:
            await execute_db(f"UPDATE users SET {slot} = 0 WHERE {slot} = ?", (c_id,))
        await log_admin(message.from_user.id, f"DELETED card ID {c_id}")
        await message.answer(f"✅ Карта {c_id} полностью удалена.")
    except: await message.answer("❌ Число.")
    await state.clear()

@dp.callback_query(F.data == "adm_give_card")
async def adm_give_card(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введите ID пользователя:")
    await state.set_state(GiveCard.user_id)
    await callback.answer()
    
@dp.message(GiveCard.user_id)
async def process_give_uid(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(uid=int(message.text))
    await message.answer("Введите ID карты:")
    await state.set_state(GiveCard.card_id)
    
@dp.message(GiveCard.card_id)
async def process_give_cid(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(cid=int(message.text))
    
    kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Normal"), KeyboardButton(text="Gold"), KeyboardButton(text="Rainbow")]], resize_keyboard=True)
    await message.answer("Выберите мутацию:", reply_markup=kb)
    await state.set_state(GiveCard.mutation)
    
@dp.message(GiveCard.mutation)
async def process_give_mut(message: types.Message, state: FSMContext):
    if message.text not in ["Normal", "Gold", "Rainbow"]: return
    data = await state.get_data()
    
    card = await fetch_one("SELECT rarity, name FROM cards WHERE id = ?", (data['cid'],))
    if not card: 
        await state.clear()
        return await message.answer("❌ Карта не найдена", reply_markup=ReplyKeyboardRemove())
        
    _, serial, _ = await give_card_to_user(data['uid'], data['cid'], message.text, card['rarity'])
    s_str = f" [#{serial}]" if serial > 0 else ""
    await log_admin(message.from_user.id, f"Выдал карту ID {data['cid']} (Мут: {message.text}) пользователю {data['uid']}")
    await message.answer(f"✅ Карта {card['name']}{s_str} выдана игроку {data['uid']}.", reply_markup=ReplyKeyboardRemove())
    await state.clear()

@dp.callback_query(F.data == "adm_give_coins")
async def callback_give_coins_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введите ID игрока для выдачи шекелей:")
    await state.set_state(AdminManage.give_coins_id)
    await callback.answer()

@dp.message(AdminManage.give_coins_id)
async def process_coins_id(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(target_id=uid)
        await message.answer("Сколько шекелей выдать?")
        await state.set_state(AdminManage.give_coins_amount)
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

@dp.message(AdminManage.give_coins_amount)
async def process_coins_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data['target_id']
        await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (amount, uid))
        await log_admin(message.from_user.id, f"Выдал {amount} шекелей игроку {uid}")
        await message.answer(f"✅ Успешно выдано {amount} шекелей игроку {uid}.")
        try: await bot.send_message(uid, f"🎁 Администратор выдал вам <b>{amount} 💰 Шекелей</b>!")
        except: pass
    except ValueError:
        await message.answer("❌ Сумма должна быть числом.")
    await state.clear()

@dp.callback_query(F.data == "adm_give_trophies")
async def callback_give_trophies_start(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введите ID игрока для выдачи кубков:")
    await state.set_state(AdminManage.give_trophies_id)
    await callback.answer()

@dp.message(AdminManage.give_trophies_id)
async def process_trophies_id(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        await state.update_data(target_id=uid)
        await message.answer("Сколько кубков выдать?")
        await state.set_state(AdminManage.give_trophies_amount)
    except ValueError:
        await message.answer("❌ ID должен быть числом.")

@dp.message(AdminManage.give_trophies_amount)
async def process_trophies_amount(message: types.Message, state: FSMContext):
    try:
        amount = int(message.text)
        data = await state.get_data()
        uid = data['target_id']
        await execute_db("UPDATE users SET trophies = trophies + ? WHERE id = ?", (amount, uid))
        await log_admin(message.from_user.id, f"Выдал {amount} кубков игроку {uid}")
        await message.answer(f"✅ Успешно выдано {amount} кубков игроку {uid}.")
        try: await bot.send_message(uid, f"🏆 Администратор выдал вам <b>{amount} 🏆</b>!")
        except: pass
    except ValueError:
        await message.answer("❌ Количество должно быть числом.")
    await state.clear()

@dp.callback_query(F.data == "adm_ban")
async def adm_ban(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введите ID пользователя для бана/разбана:")
    await state.set_state(AdminBan.user_id)
    await callback.answer()

@dp.message(AdminBan.user_id)
async def process_ban(message: types.Message, state: FSMContext):
    if not message.text.isdigit(): return
    uid = int(message.text)
    user = await fetch_one("SELECT banned FROM users WHERE id = ?", (uid,))
    if not user: return await message.answer("Игрок не найден.")
    
    new_val = 0 if user['banned'] == 1 else 1
    await execute_db("UPDATE users SET banned = ? WHERE id = ?", (new_val, uid))
    
    act = "Забанил" if new_val == 1 else "Разбанил"
    await log_admin(message.from_user.id, f"{act} пользователя {uid}")
    await message.answer(f"✅ Пользователь {uid} {'забанен' if new_val == 1 else 'разбанен'}.")
    await state.clear()

@dp.callback_query(F.data == "adm_lb_settings")
async def callback_lb_settings(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🥇 1 Место", callback_data="lb_edit_1")],
        [InlineKeyboardButton(text="🥈 2 Место", callback_data="lb_edit_2")],
        [InlineKeyboardButton(text="🥉 3 Место", callback_data="lb_edit_3")],
        [InlineKeyboardButton(text="🏅 4-9 Места", callback_data="lb_edit_4_9")],
        [InlineKeyboardButton(text="🎖 10-20 Места", callback_data="lb_edit_10_20")],
        [InlineKeyboardButton(text="🏆 Выдать награды принудительно", callback_data="lb_force_trigger")]
    ])
    await callback.message.edit_text("🏆 <b>Настройка наград за Лидерборд</b>\nВыберите позицию для редактирования наград (выдаются каждые 2 дня):", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "lb_force_trigger")
async def callback_lb_force_trigger(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    await distribute_lb_rewards(force=True)
    await callback.message.answer("✅ Награды успешно выданы принудительно, кубки обнулены!")
    await callback.answer()

@dp.callback_query(F.data.startswith("lb_edit_"))
async def callback_lb_edit_bracket(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
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
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_lb_settings")]
    ])
    await callback.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("lb_clear_"))
async def callback_lb_clear_bracket(callback: types.CallbackQuery):
    if not await is_admin(callback.from_user.id): return
    bracket = callback.data.replace("lb_clear_", "")
    await execute_db("DELETE FROM lb_rewards WHERE bracket = ?", (bracket,))
    await callback.answer("✅ Награды очищены!", show_alert=True)
    
    # Reload board view
    await callback_lb_edit_bracket(callback)

@dp.callback_query(F.data.startswith("lb_add_sh_"))
async def callback_lb_add_shekels(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    bracket = callback.data.replace("lb_add_sh_", "")
    await state.update_data(lb_bracket=bracket, lb_reward_type="shekels")
    await callback.message.answer("Введите количество Шекелей для выдачи:")
    await state.set_state(AdminLBRewards.amount)
    await callback.answer()

@dp.message(AdminLBRewards.amount)
async def process_lb_save_shekels(message: types.Message, state: FSMContext):
    try:
        amt = int(message.text)
        data = await state.get_data()
        await execute_db("INSERT INTO lb_rewards (bracket, reward_type, amount) VALUES (?, ?, ?)", (data['lb_bracket'], 'shekels', amt))
        await message.answer(f"✅ Награда {amt} шекелей добавлена для {data['lb_bracket']} места!")
    except: await message.answer("❌ Число!")
    await state.clear()

@dp.callback_query(F.data.startswith("lb_add_cd_"))
async def callback_lb_add_card(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    bracket = callback.data.replace("lb_add_cd_", "")
    await state.update_data(lb_bracket=bracket, lb_reward_type="card")
    
    all_cards = await fetch_all("SELECT id, name, rarity FROM cards ORDER BY id DESC")
    items = [{"id": c['id'], "btn_text": f"{RARITY_EMOJI.get(c['rarity'], '')} {c['name']} (ID:{c['id']})"} for c in all_cards]
    await state.update_data(lb_items=items)
    kb = get_pagination_keyboard(items, 0, "lbc", columns=1, items_per_page=8)
    
    await callback.message.edit_text("Выберите карту для награды:", reply_markup=kb)
    await state.set_state(AdminLBRewards.card_id)

@dp.callback_query(F.data.startswith("lbc_page_"), AdminLBRewards.card_id)
async def callback_lb_c_paginate(callback: types.CallbackQuery, state: FSMContext):
    page = int(callback.data.split("_")[2])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('lb_items', []), page, "lbc", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("lbc_"), AdminLBRewards.card_id)
async def callback_lb_c_select(callback: types.CallbackQuery, state: FSMContext):
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
async def callback_lb_mut_select(callback: types.CallbackQuery, state: FSMContext):
    mutation = callback.data.split("_")[2]
    data = await state.get_data()
    bracket = data['lb_bracket']
    card_id = data['lb_card_id']
    
    await execute_db("INSERT INTO lb_rewards (bracket, reward_type, card_id, mutation) VALUES (?, ?, ?, ?)", (bracket, 'card', card_id, mutation))
    
    await callback.message.edit_text(f"✅ Карта (ID {card_id}, Мутация: {mutation}) добавлена в награды для {bracket} места!")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "adm_luck")
async def adm_luck(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введи множитель УДАЧИ (например 2.0 для х2):")
    await state.set_state(EventLuck.mult)
    await callback.answer()

@dp.message(EventLuck.mult)
async def process_luck_mult(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text.replace(',','.')))
    await message.answer("На сколько МИНУТ запускаем?")
    await state.set_state(EventLuck.mins)

@dp.message(EventLuck.mins)
async def process_luck_finish(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mins = int(message.text)
        end = time.time() + (mins * 60)
        await execute_db("UPDATE server_settings SET luck_mult = ?, luck_end = ? WHERE id = 1", (data['mult'], end))
        await log_admin(message.from_user.id, f"LUCK EVENT x{data['mult']} for {mins}m")
        await message.answer("✅ Ивент Удачи запущен. Начинаю рассылку...")
        await state.clear()
        asyncio.create_task(broadcast_message(f"🍀 <b>ГЛОБАЛЬНЫЙ ИВЕНТ УДАЧИ!</b>\nШанс на редкие карты увеличен в {data['mult']} раз на {mins} минут! Зайди в /index, чтобы увидеть новые шансы!\n\nБегом крутить гачу: /getcard"))
    except: await message.answer("Ошибка ввода.")

@dp.callback_query(F.data == "adm_cd")
async def adm_cd(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Введи множитель СКОРОСТИ (например 2.0 сделает откат в 2 раза быстрее):")
    await state.set_state(EventCD.mult)
    await callback.answer()

@dp.message(EventCD.mult)
async def process_cd_mult(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text.replace(',','.')))
    await message.answer("На сколько МИНУТ запускаем?")
    await state.set_state(EventCD.mins)

@dp.message(EventCD.mins)
async def process_cd_finish(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mins = int(message.text)
        end = time.time() + (mins * 60)
        await execute_db("UPDATE server_settings SET cd_mult = ?, cd_end = ? WHERE id = 1", (data['mult'], end))
        await log_admin(message.from_user.id, f"CD EVENT x{data['mult']} for {mins}m")
        await message.answer("✅ Ивент Скорости запущен. Начинаю рассылку...")
        await state.clear()
        asyncio.create_task(broadcast_message(f"⏳ <b>ГЛОБАЛЬНЫЙ ИВЕНТ СКОРОСТИ!</b>\nТаймер выбивания карт ускорен в {data['mult']} раз на {mins} минут!\n\nКрути гачу быстрее: /getcard"))
    except: await message.answer("Ошибка ввода.")

@dp.callback_query(F.data == "adm_announce")
async def adm_announce(callback: types.CallbackQuery, state: FSMContext):
    if not await is_admin(callback.from_user.id): return
    await callback.message.answer("Отправьте текст для глобальной рассылки (поддерживается HTML):")
    await state.set_state(AdminAnnounce.content)
    await callback.answer()

@dp.message(AdminAnnounce.content)
async def process_announce(message: types.Message, state: FSMContext):
    text = f"📢 <b>Сообщение от Администрации:</b>\n\n{message.html_text}"
    await message.answer("Начинаю рассылку...")
    await log_admin(message.from_user.id, "Запустил глобальную рассылку")
    asyncio.create_task(broadcast_message(text))
    await state.clear()

@dp.message(Command("db"))
async def cmd_db(message: types.Message):
    if not await is_admin(message.from_user.id): return
    file = FSInputFile(DB_NAME)
    await message.answer_document(file, caption="📦 Текущая БД. Отправьте новый .db файл для замены базы.")

@dp.message(F.document)
async def process_db_file(message: types.Message):
    if not await is_admin(message.from_user.id): return
    if not message.document.file_name.endswith(".db"): return
    
    file = await bot.get_file(message.document.file_id)
    
    for ext in ["-wal", "-shm", "-journal"]:
        try: os.remove(f"{DB_NAME}{ext}")
        except OSError: pass
        
    await bot.download_file(file.file_path, DB_NAME)
    await check_and_update_schema()
    await log_admin(message.from_user.id, "Загрузил новую БД")
    await message.answer("✅ <b>База данных успешно заменена!</b>")

# ========================================================================
# ТОЧКА ВХОДА И ФОНОВЫЕ ЗАДАЧИ
# ========================================================================
async def main():
    await check_and_update_schema()
    logging.info("База данных инициализирована.")
    
    shop_exists = await fetch_all("SELECT * FROM shop_items")
    if not shop_exists: await restock_shop()
    
    settings = await fetch_one("SELECT last_lb_reward FROM server_settings WHERE id = 1")
    if settings and settings['last_lb_reward'] == 0:
        await execute_db("UPDATE server_settings SET last_lb_reward = ? WHERE id = 1", (time.time(),))
    
    asyncio.create_task(shop_auto_restock_task())
    asyncio.create_task(leaderboard_rewards_task())
    
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="getcard", description="Выбить карту (Гача)"),
        BotCommand(command="shop", description="Магазин"),
        BotCommand(command="inventory", description="Инвентарь"),
        BotCommand(command="equip", description="Экипировка колоды"),
        BotCommand(command="profile", description="Профиль и статы"),
        BotCommand(command="quests", description="Квесты"),
        BotCommand(command="index", description="Индекс всех карт"),
        BotCommand(command="top", description="Рейтинг игроков"),
        BotCommand(command="admin", description="Админ-панель (для стаффа)"),
        BotCommand(command="forcerewards", description="Раздать топ кубков (Админ)"),
        BotCommand(command="db", description="Загрузить/Скачать базу (Админ)")
    ]
    await bot.set_my_commands(commands)
    
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
