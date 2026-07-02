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
active_trades_users = set()  # Хранит ID пользователей, занятых трейдом
active_trades = {}  # Хранит структуры активных трейдов

SHOP_PACKAGES = [
    ("1_rnd", "1 Случайная карта", 100, 20, 1.0),
    ("3_rnd", "3 Случайные карты", 275, 20, 0.9),
    ("5_rnd", "5 Случайных карт", 450, 20, 0.8),
    ("10_rnd", "10 Случайных карт", 900, 15, 0.7),
    ("25_rnd", "25 Случайных карт", 2300, 10, 0.6),
    ("50_rnd", "50 Случайных карт", 4500, 3, 0.4),
    ("rnd_leg", "Случайная Легендарная", 1000, 5, 0.5), 
    ("rnd_myth", "Случайная Мифическая", 10000, 3, 0.25), 
    ("rnd_sup", "Случайная Супер Карта", 75000, 1, 0.125) 
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
        
        # Обновление и чистка рангов
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
        
        # Заполнение новой таблицы рангов (Diamond V убран, добавлены Ruby I-V)
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

# Новые состояния для трейдов и PvP
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

async def add_quest_progress(user_id: int, field: str, amount: int = 1):
    if field not in ['q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys']:
        return
    await execute_db(f"UPDATE users SET {field} = {field} + ? WHERE id = ?", (amount, user_id))
    
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user: return
    
    if (user['q_cards_opened'] >= 10 and
        user['q_rare_obtained'] >= 1 and
        user['q_wins'] >= 3 and
        user['q_battles'] >= 5 and
        user['q_shop_buys'] >= 1):
        
        await execute_db("""
            UPDATE users SET
                coins = coins + 1500,
                q_cards_opened = 0,
                q_rare_obtained = 0,
                q_wins = 0,
                q_battles = 0,
                q_shop_buys = 0
            WHERE id = ?
        """, (user_id,))
        try:
            await bot.send_message(user_id, "🎉 <b>ПОЗДРАВЛЯЕМ!</b>\nВы выполнили все ежедневные квесты и получили <b>1500 💰 Шекелей</b>!\nВсе квесты успешно сброшены, можете выполнять их снова!")
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

def roll_mutation():
    r = random.random()
    if r <= 0.02: return "Rainbow"
    if r <= 0.12: return "Gold"
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

# ========================================================================
# ЛОГИКА ШАНСОВ И МАГАЗИНА
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

async def shop_auto_restock_task():
    while True:
        try:
            settings = await fetch_one("SELECT last_restock FROM server_settings WHERE id = 1")
            now = time.time()
            if settings and (now - settings['last_restock'] >= 2 * 3600):
                await restock_shop()
        except Exception as e:
            logging.error(f"Shop restock error: {e}")
        await asyncio.sleep(60)

async def give_multiple_cards(user_id: int, count: int) -> list:
    luck_mult, _ = await get_active_events()
    all_cards = await fetch_all("SELECT * FROM cards WHERE drop_chance > 0 AND rarity != 'Leaderboard'")
    if not all_cards: return []
    
    weights = [c['drop_chance'] * (luck_mult if c['drop_chance'] < 15.0 else 1.0) for c in all_cards]
    won_cards = random.choices(all_cards, weights=weights, k=count)
    
    result = []
    for c in won_cards:
        mut = roll_mutation()
        _, serial, _ = await give_card_to_user(user_id, c['id'], mut, c['rarity'])
        
        c_copy = dict(c)
        c_copy['mutation'] = mut
        c_copy['serial_number'] = serial
        result.append(c_copy)
    return result

async def leaderboard_rewards_task():
    while True:
        try:
            settings = await fetch_one("SELECT last_lb_reward FROM server_settings WHERE id = 1")
            now = time.time()
            if settings and (now - settings['last_lb_reward'] >= 3 * 24 * 3600):
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
                                f"🎉 Поздравляем! По итогам последних 3 дней вы заняли почетное <b>{pos} место</b> в мировом рейтинге по кубкам!\n\n"
                                f"🎁 <b>Вот ваша заслуженная награда:</b>\n" + "\n".join([f"🔸 {m}" for m in reward_msgs]) + "\n\n"
                                f"<i>Спасибо за вашу активность! Рейтинг был сброшен, новые награды через 3 дня! Удачи на арене!</i>"
                            )
                            try:
                                await bot.send_message(user['id'], msg_text)
                            except: pass
                            
                await execute_db("UPDATE server_settings SET last_lb_reward = ? WHERE id = 1", (now,))
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
    
    c_op = min(10, user['q_cards_opened'])
    r_ob = min(1, user['q_rare_obtained'])
    w_win = min(3, user['q_wins'])
    b_pl = min(5, user['q_battles'])
    s_bu = min(1, user['q_shop_buys'])
    
    text = (
        "📜 <b>ЕЖЕДНЕВНЫЕ КВЕСТЫ</b>\n"
        "<i>Выполни все задания, чтобы получить 1500 💰 Шекелей!</i>\n\n"
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
        
    text += "\n🎁 <b>Награды за Топ (выдаются каждые 3 дня):</b>\n"
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
        mut = roll_mutation()
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
    base_cooldown = 5 * 60
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
    won_card = random.choices(all_cards, weights=weights, k=1)[0]
    
    mutation = roll_mutation()
    _, serial, _ = await give_card_to_user(user['id'], won_card['id'], mutation, won_card['rarity'])
    won_card['serial_number'] = serial
        
    await execute_db("UPDATE users SET last_getcard = ? WHERE id = ?", (now, user['id']))
    
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
        msg += f"🍀 <i>Сработал ивент удачи!</i>"
        
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
        inv_stats = await fetch_all("SELECT mutation, SUM(count) as c FROM inventory WHERE card_id = ? GROUP BY mutation", (c['id'],))
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

async def get_bot_team(user_id: int, difficulty_mult: float):
    user_team = await get_team_data(user_id)
    user_power = sum(c['damage'] + c['hp'] for c in user_team) if user_team else 300
    avg_card_power = max(50, user_power / 3)
    
    # AI теперь не может использовать Leaderboard карты!
    all_cards = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE rarity != 'Leaderboard'")
    if len(all_cards) < 3: return []
    
    # Снизили порог силы ИИ, сделав бои капельку легче (3.0 вместо 3.5)
    valid_cards = [c for c in all_cards if (c['damage'] + c['hp']) <= avg_card_power * 3.0 * difficulty_mult or c['class_type'] == 'Booster']
    if len(valid_cards) < 3: valid_cards = all_cards
    
    team_selection = random.sample(valid_cards, min(3, len(valid_cards)))
    if len(team_selection) < 3:
        team_selection += random.choices(all_cards, k=3-len(team_selection))
        
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
            
            # Усложнили получение монет: уменьшили базовый рандом до 25-90 монет
            coins_won = int(random.randint(25, 90) * rank['reward_mult'] * diff_trophies_scale)
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
    
    # Облегчили матчи: уменьшили силу ИИ во всех трёх режимах
    if diff_type == "easy":
        power_mult = 0.7  # было 0.8
        trophies_scale = 0.5
        diff_name = "Лёгкий"
    elif diff_type == "med":
        power_mult = 1.1  # было 1.3
        trophies_scale = 1.0
        diff_name = "Средний"
    elif diff_type == "hard":
        power_mult = 1.6  # было 2.0
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
        return await callback.answer("❌ Один из игроков уже находится в бою!", show_alert=True)
        
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
    
    # Запускаем трансляцию PvP для ОБОИХ игроков в их личные сообщения синхронно!
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
    # Создаем стартовые сообщения у обоих игроков
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
# СИСТЕМА ОБМЕНА КАРТАМИ (ТРЕЙДЫ)
# ========================================================================
@dp.message(F.text == "🤝 Трейды")
async def cmd_trade_start(message: types.Message, state: FSMContext):
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_trades_users or message.from_user.id in active_combats:
        return await message.answer("❌ Вы не можете начать обмен в данный момент (вы заняты трейдом или боем)!")
        
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
    
    # Инициализация структуры трейда
    active_trades[trade_id] = {
        "p1": p1_id,
        "p2": p2_id,
        "p1_name": get_display_name(p1_user),
        "p2_name": get_display_name(p2_user),
        "p1_cards": {}, # dict {inventory_id: count_in_trade}
        "p2_cards": {}, # dict {inventory_id: count_in_trade}
        "p1_accepted": False,
        "p2_accepted": False,
        "p1_msg_id": None,
        "p2_msg_id": None
    }
    
    await callback.message.delete()
    
    # Отправляем интерфейс трейда обоим игрокам
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
    
    # Формируем списки предложенных карт
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
    
    # Клавиатура управления трейдом
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
    
    # Доски для p1 и p2
    t1, k1 = await get_trade_board_text_and_kb(trade_id, trade['p1'])
    t2, k2 = await get_trade_board_text_and_kb(trade_id, trade['p2'])
    
    m1 = await bot.send_message(trade['p1'], t1, reply_markup=k1)
    m2 = await bot.send_message(trade['p2'], t2, reply_markup=k2)
    
    trade['p1_msg_id'] = m1.message_id
    trade['p2_msg_id'] = m2.message_id

async def update_trade_boards(trade_id: str):
    trade = active_trades.get(trade_id)
    if not trade: return
    
    t1, k1 = await get_trade_board_text_and_kb(trade_id, trade['p1'])
    t2, k2 = await get_trade_board_text_and_kb(trade_id, trade['p2'])
    
    try: await bot.edit_message_text(chat_id=trade['p1'], message_id=trade['p1_msg_id'], text=t1, reply_markup=k1)
    except: pass
    
    try: await bot.edit_message_text(chat_id=trade['p2'], message_id=trade['p2_msg_id'], text=t2, reply_markup=k2)
    except: pass

@dp.callback_query(F.data.startswith("tr_addlist_"))
async def callback_trade_addlist(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    trade_id = f"{parts[2]}_{parts[3]}"
    page = int(parts[4])
    
    trade = active_trades.get(trade_id)
    if not trade:
        return await callback.answer("❌ Обмен завершен или отменен.", show_alert=True)
        
    user_id = callback.from_user.id
    
    # Получаем инвентарь игрока
    inv_items = await fetch_all("""
        SELECT i.id, c.name, c.rarity, i.count, i.mutation, i.serial_number 
        FROM inventory i JOIN cards c ON i.card_id = c.id 
        WHERE i.user_id = ?
    """, (user_id,))
    
    if not inv_items:
        return await callback.answer("🎒 Ваш инвентарь пуст!", show_alert=True)
        
    # Формируем кнопки для выбора
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
    
    # Проверка наличия
    inv_row = await fetch_one("SELECT count FROM inventory WHERE id = ? AND user_id = ?", (inv_id, user_id))
    if not inv_row:
        return await callback.answer("❌ Ошибка владения карточкой.", show_alert=True)
        
    current_in_trade = offers.get(inv_id, 0)
    if current_in_trade >= inv_row['count']:
        return await callback.answer("❌ У вас больше нет копий этой карты!", show_alert=True)
        
    offers[inv_id] = current_in_trade + 1
    
    # Любое изменение в обмене сбрасывает подтверждения
    trade['p1_accepted'] = False
    trade['p2_accepted'] = False
    
    await callback.message.delete()
    await update_trade_boards(trade_id)
    await callback.answer()

@dp.callback_query(F.data.startswith("tr_board_"))
async def callback_trade_board_return(callback: types.CallbackQuery):
    parts = callback.data.split("_")
    trade_id = f"{parts[2]}_{parts[3]}"
    
    trade = active_trades.get(trade_id)
    if not trade:
        return await callback.message.edit_text("❌ Обмен завершен или отменен.")
        
    await callback.message.delete()
    # Воссоздаем доски
    t_u, k_u = await get_trade_board_text_and_kb(trade_id, callback.from_user.id)
    new_m = await bot.send_message(callback.from_user.id, t_u, reply_markup=k_u)
    
    if callback.from_user.id == trade['p1']:
        trade['p1_msg_id'] = new_m.message_id
    else:
        trade['p2_msg_id'] = new_m.message_id
        
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
        # Оба согласились! Проводим безопасный транзакционный обмен!
        p1 = trade['p1']
        p2 = trade['p2']
        
        db = await get_db_connection()
        try:
            # 1. Передаем карты от игрока 1 игроку 2
            for inv_id, count in list(trade['p1_cards'].items()):
                # Получаем детали строки
                cursor = await db.execute("SELECT * FROM inventory WHERE id = ? AND user_id = ?", (inv_id, p1))
                row = await cursor.fetchone()
                if not row or row['count'] < count:
                    raise ValueError("Ошибка валидации трейда: Недостаточно карт.")
                
                card_id = row['card_id']
                mutation = row['mutation']
                serial = row['serial_number']
                
                # Вычитаем у игрока 1
                if row['count'] == count:
                    await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
                    # Сбрасываем экипировку, если карт этой категории не осталось
                    for slot in ['equip1', 'equip2', 'equip3']:
                        await db.execute(f"UPDATE users SET {slot} = 0 WHERE id = ? AND {slot} = ?", (p1, card_id))
                else:
                    await db.execute("UPDATE inventory SET count = count - ? WHERE id = ?", (count, inv_id))
                
                # Добавляем игроку 2
                card_row = await db.execute("SELECT rarity FROM cards WHERE id = ?", (card_id,))
                card_res = await card_row.fetchone()
                rarity = card_res['rarity'] if card_res else 'Basic'
                
                if needs_serial_number(rarity, mutation):
                    # Принудительно вставляем с прежним серийником
                    await db.execute(
                        "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, ?, ?, ?)",
                        (p2, card_id, count, mutation, serial)
                    )
                else:
                    # Стакаем обычные копии
                    m_cursor = await db.execute(
                        "SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0",
                        (p2, card_id, mutation)
                    )
                    m_row = await m_cursor.fetchone()
                    if m_row:
                        await db.execute("UPDATE inventory SET count = count + ? WHERE id = ?", (count, m_row['id']))
                    else:
                        await db.execute(
                            "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, ?, ?, 0)",
                            (p2, card_id, count, mutation)
                        )
            
            # 2. Передаем карты от игрока 2 игроку 1
            for inv_id, count in list(trade['p2_cards'].items()):
                cursor = await db.execute("SELECT * FROM inventory WHERE id = ? AND user_id = ?", (inv_id, p2))
                row = await cursor.fetchone()
                if not row or row['count'] < count:
                    raise ValueError("Ошибка валидации трейда: Недостаточно карт.")
                
                card_id = row['card_id']
                mutation = row['mutation']
                serial = row['serial_number']
                
                # Вычитаем у игрока 2
                if row['count'] == count:
                    await db.execute("DELETE FROM inventory WHERE id = ?", (inv_id,))
                    for slot in ['equip1', 'equip2', 'equip3']:
                        await db.execute(f"UPDATE users SET {slot} = 0 WHERE id = ? AND {slot} = ?", (p2, card_id))
                else:
                    await db.execute("UPDATE inventory SET count = count - ? WHERE id = ?", (count, inv_id))
                
                # Добавляем игроку 1
                card_row = await db.execute("SELECT rarity FROM cards WHERE id = ?", (card_id,))
                card_res = await card_row.fetchone()
                rarity = card_res['rarity'] if card_res else 'Basic'
                
                if needs_serial_number(rarity, mutation):
                    await db.execute(
                        "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, ?, ?, ?)",
                        (p1, card_id, count, mutation, serial)
                    )
                else:
                    m_cursor = await db.execute(
                        "SELECT id FROM inventory WHERE user_id = ? AND card_id = ? AND mutation = ? AND serial_number = 0",
                        (p1, card_id, mutation)
                    )
                    m_row = await m_cursor.fetchone()
                    if m_row:
                        await db.execute("UPDATE inventory SET count = count + ? WHERE id = ?", (count, m_row['id']))
                    else:
                        await db.execute(
                            "INSERT INTO inventory (user_id, card_id, count, mutation, serial_number) VALUES (?, ?, ?, ?, 0)",
                            (p1, card_id, count, mutation)
                        )
            await db.commit()
            
            # Успешное логирование сделки
            success_text = "🎉 <b>Трейд успешно завершен!</b> Предложенные карточки перенесены в инвентарь участников обмена."
            try: await bot.send_message(p1, success_text)
            except: pass
            try: await bot.send_message(p2, success_text)
            except: pass
            
        except Exception as e:
            await db.rollback()
            try: await bot.send_message(p1, "❌ Трейд завершился аварийным сбоем. База данных восстановлена до исходного состояния.")
            except: pass
            try: await bot.send_message(p2, "❌ Трейд завершился аварийным сбоем. База данных восстановлена до исходного состояния.")
            except: pass
            logging.error(f"Error during execution of secure trade transaction: {e}")
            
        finally:
            await db.close()
            
        # Удаляем сообщения досок и чистим кэш обмена
        try: await bot.delete_message(p1, trade['p1_msg_id'])
        except: pass
        try: await bot.delete_message(p2, trade['p2_msg_id'])
        except: pass
        
        active_trades_users.discard(p1)
        active_trades_users.discard(p2)
        active_trades.pop(trade_id, None)
        
    else:
        # Просто обновляем доски
        await update_trade_boards(trade_id)
        await callback.answer()

# ========================================================================
# ПАНЕЛЬ АДМИНИСТРАТОРА
# ========================================================================
def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Карты", callback_data="adm_cards"), InlineKeyboardButton(text="👤 Игроки", callback_data="adm_users")],
        [InlineKeyboardButton(text="🎉 Ивенты", callback_data="adm_events"), InlineKeyboardButton(text="👑 Админы", callback_data="adm_admins")],
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
        await message.answer_photo(new_photo_id, caption=f"✅ <b>Бустер {data['name']} создан!</b>", reply_markup=get_main_keyboard(True))
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
        await message.answer_photo(new_photo_id, caption=f"✅ <b>Карта {data['name']} создана!</b>", reply_markup=get_main_keyboard(True))
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
        await message.answer(reply, reply_markup=get_main_keyboard(True))
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
        await execute_db("DELETE FROM inventory WHERE card_id = ?", (c_id,))
        for slot in ['equip1', 'equip2', 'equip3']:
            await execute_db(f"UPDATE users SET {slot} = 0 WHERE {slot} = ?", (c_id,))
        await log_admin(message.from_user.id, f"DELETED card ID {c_id}")
        await message.answer(f"✅ Карта {c_id} полностью удалена.")
    except: await message.answer("❌ Число.")
    await state.clear()

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
    await callback.message.answer("Введите ID игрока для сброса состояния боя:")
    await state.set_state(AdminManage.reset_battle_id)
    await callback.answer()

@dp.message(AdminManage.reset_battle_id)
async def adm_usr_reset_battle_finish(message: types.Message, state: FSMContext):
    try:
        uid = int(message.text)
        if uid in active_combats:
            active_combats.discard(uid)
            await message.answer(f"✅ Бой для игрока {uid} успешно сброшен.")
            await log_admin(message.from_user.id, f"Сбросил состояние боя для {uid}")
        else:
            await message.answer("ℹ️ Этот игрок не находится в активном поиске или бою.")
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
    await callback.message.edit_text("🏆 <b>Настройка наград за Лидерборд</b>\nВыберите позицию для редактирования наград (выдаются каждые 3 дня):", reply_markup=kb)

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
        asyncio.create_task(broadcast_message(f"🍀 <b>ГЛОБАЛЬНЫЙ ИВЕНТ УДАЧИ!</b>\nШанс на редкие карты увеличен в {data['mult']} раз на {mins} минут! Зайди в /index, чтобы увидеть новые шансы!\n\nБегом крутить гачу: /getcard"))
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
        asyncio.create_task(broadcast_message(f"⏳ <b>ГЛОБАЛЬНЫЙ ИВЕНТ СКОРОСТИ!</b>\nТаймер выбивания карт ускорен в {data['mult']} раз на {mins} минут!\n\nКрути гачу быстрее: /getcard"))
    except: await message.answer("Ошибка ввода.")

@dp.message(Command("announce"))
async def cmd_announce(message: types.Message, state: FSMContext):
    if not await is_admin(message.from_user.id): return
    await message.answer("📢 <b>Глобальная Рассылка</b>\nОтправьте сообщение (текст, фото или видео с текстом), которое нужно разослать всем игрокам:")
    await state.set_state(AdminAnnounce.content)

@dp.message(AdminAnnounce.content)
async def process_announce(message: types.Message, state: FSMContext):
    users = await fetch_all("SELECT id FROM users WHERE banned = 0")
    success = 0
    await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
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
    
    logging.info("🤖 Карточный бот запущен (Версия с трейдами и Ruby-рангами)!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
