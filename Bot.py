import asyncio
import logging
import random
import time
import io
import os
import math
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Any, Optional

from aiogram import Bot, Dispatcher, F, types
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, StateFilter, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    FSInputFile, BotCommand, Message
)
from aiogram.exceptions import TelegramAPIError

try:
    from PIL import Image, ImageOps, ImageDraw
except ImportError:
    raise ImportError("Критическая ошибка: Установите Pillow (pip install Pillow) для генерации рамок карт.")

import aiosqlite

# ========================================================================
# 1. КОНФИГУРАЦИЯ БОТА И БАЗОВЫЕ НАСТРОЙКИ
# ========================================================================
BOT_TOKEN = "7725898870:AAHa-6biiZkWuheNzjPl0Tun3XpNyLNq1lE"
SUPER_ADMIN_ID = 5341904332
DB_NAME = "cards_database_v2.db"

# Настройка подробного логирования для мониторинга всех процессов
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

bot = Bot(
    token=BOT_TOKEN, 
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()

# Множество для отслеживания игроков, находящихся в активном бою (во избежание спама и дюпов)
active_combats = set()

# ========================================================================
# 2. КОНСТАНТЫ, ЭМОДЗИ И БАЛАНС
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

# Новые классы: Poison (Яд) вместо Fire, и Stunner (Оглушение)
CLASS_EMOJI = {
    "AOE": "🌪",
    "Splash": "🌊",
    "Booster": "✨",
    "Single": "🎯",
    "Poison": "🧪",    # Заменил Fire на Poison
    "Stunner": "⚡"    # Новый класс - Оглушает врагов
}

CLASSES = list(CLASS_EMOJI.keys())

# Обновленные цены в глобальном магазине согласно ТЗ
SHOP_PACKAGES = [
    ("1_rnd", "1 Случайная карта", 100, 20, 1.0),
    ("3_rnd", "3 Случайные карты", 275, 20, 1.0),
    ("5_rnd", "5 Случайных карт", 450, 20, 0.9),
    ("10_rnd", "10 Случайных карт", 900, 15, 0.8),
    ("25_rnd", "25 Случайных карт", 2300, 10, 0.7),
    ("50_rnd", "50 Случайных карт", 4500, 3, 0.6),
    ("100_rnd", "100 Случайных карт", 9000, 2, 0.4),
    ("rnd_leg", "Случайная Легендарная", 1750, 5, 0.7), # Цена изменена на 1750
    ("rnd_myth", "Случайная Мифическая", 20000, 3, 0.4), # Цена изменена на 20000
    ("rnd_sup", "Случайная Супер Карта", 150000, 1, 0.2) # Цена изменена на 150000
]

# ========================================================================
# 3. БАЗА ДАННЫХ И СМАРТ-МИГРАЦИИ (ПОЛНЫЙ SQL)
# ========================================================================
async def get_db_connection() -> aiosqlite.Connection:
    """Устанавливает соединение с базой данных SQLite."""
    db = await aiosqlite.connect(DB_NAME)
    db.row_factory = aiosqlite.Row
    return db

async def execute_db(query: str, params: tuple = ()) -> None:
    """Выполняет запрос на изменение (INSERT, UPDATE, DELETE) без возврата результата."""
    db = await get_db_connection()
    try:
        await db.execute(query, params)
        await db.commit()
    finally:
        await db.close()

async def fetch_one(query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    """Выполняет запрос SELECT и возвращает одну строку в виде словаря."""
    db = await get_db_connection()
    try:
        async with db.execute(query, params) as cursor:
            result = await cursor.fetchone()
            return dict(result) if result else None
    finally:
        await db.close()

async def fetch_all(query: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Выполняет запрос SELECT и возвращает все найденные строки в виде списка словарей."""
    db = await get_db_connection()
    try:
        async with db.execute(query, params) as cursor:
            result = await cursor.fetchall()
            return [dict(row) for row in result]
    finally:
        await db.close()

async def check_and_update_schema() -> None:
    """
    Проверяет структуру базы данных и автоматически добавляет отсутствующие таблицы и колонки.
    Гарантирует, что старые пользователи не потеряют прогресс при обновлении бота.
    """
    db = await get_db_connection()
    try:
        # Таблица пользователей: добавлены robux, is_vip, has_x2_coins, equip4
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
                has_x2_coins INTEGER DEFAULT 0
            )
        """)
        
        # Интеллектуальная миграция колонок для старых БД
        columns_to_check = {
            'first_name': 'TEXT',
            'q_cards_opened': 'INTEGER DEFAULT 0',
            'q_rare_obtained': 'INTEGER DEFAULT 0',
            'q_wins': 'INTEGER DEFAULT 0',
            'q_battles': 'INTEGER DEFAULT 0',
            'q_shop_buys': 'INTEGER DEFAULT 0',
            'quests_cooldown': 'REAL DEFAULT 0',
            'pity_mythic': 'INTEGER DEFAULT 0',
            'pity_super': 'INTEGER DEFAULT 0',
            'equip4': 'INTEGER DEFAULT 0',
            'robux': 'INTEGER DEFAULT 0',
            'is_vip': 'INTEGER DEFAULT 0',
            'has_x2_coins': 'INTEGER DEFAULT 0'
        }
        
        for col, col_type in columns_to_check.items():
            try:
                await db.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            except aiosqlite.OperationalError:
                pass # Колонка уже существует

        # Таблица карт
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
        
        # Таблица инвентаря
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
        
        # Обновление старых редкостей до Super (если были Godly или Secret)
        await db.execute("UPDATE cards SET rarity = 'Super' WHERE rarity IN ('Godly', 'Secret')")
        
        # Таблица рангов
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
        
        # Настройки сервера
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

        # Магазин предметов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS shop_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT,
                name TEXT,
                price INTEGER,
                stock INTEGER
            )
        """)
        
        # Донат-Магазин (Robux Shop)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS donate_shop (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id INTEGER,
                price_robux INTEGER
            )
        """)
        
        # Глобальные Ивенты
        await db.execute("""
            CREATE TABLE IF NOT EXISTS global_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT,
                target_amount INTEGER,
                current_amount INTEGER DEFAULT 0,
                end_time REAL,
                is_active INTEGER DEFAULT 1
            )
        """)
        
        # Участники Глобальных Ивентов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS event_participants (
                event_id INTEGER,
                user_id INTEGER,
                contributed INTEGER DEFAULT 0,
                PRIMARY KEY(event_id, user_id)
            )
        """)

        # Логи админов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                action TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Права администраторов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY
            )
        """)
        
        # Награды за лидерборд
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
        
        # Генерация базовых рангов
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
# 4. FSM СОСТОЯНИЯ ДЛЯ ДИАЛОГОВ И ИВЕНТОВ
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

class AdminManage(StatesGroup):
    add_id = State()
    del_id = State()

class EventLuck(StatesGroup):
    mult = State()
    mins = State()

class GlobalEventCreate(StatesGroup):
    command = State()
    goal = State()
    hours = State()

class DonateShopAdd(StatesGroup):
    card_id = State()
    price_robux = State()

class PvPState(StatesGroup):
    waiting_target = State()
    
class PvEModifiers(StatesGroup):
    choosing = State()

# ========================================================================
# 5. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И УТИЛИТЫ (ХЕЛПЕРЫ)
# ========================================================================
def get_display_name(user_data: dict) -> str:
    """Форматирует имя пользователя: приоритет на @username, затем first_name, затем ID."""
    if user_data.get('username'): return f"@{user_data['username']}"
    elif user_data.get('first_name'): return user_data['first_name']
    return f"Игрок {user_data.get('id', '???')}"

async def is_admin(user_id: int) -> bool:
    """Проверяет, обладает ли пользователь правами администратора."""
    if user_id == SUPER_ADMIN_ID: return True
    res = await fetch_one("SELECT 1 FROM admins WHERE user_id = ?", (user_id,))
    return bool(res)

async def check_ban(user_id: int) -> bool:
    """Проверяет наличие бана у пользователя."""
    res = await fetch_one("SELECT banned FROM users WHERE id = ?", (user_id,))
    return bool(res and res['banned'] == 1)

async def notify_super_admin(text: str) -> None:
    """Отправляет важное уведомление Супер-Администратору."""
    try: await bot.send_message(SUPER_ADMIN_ID, f"⚠️ <b>АДМИН-ЛОГ:</b>\n{text}")
    except Exception as e: logger.error(f"Не удалось отправить лог админу: {e}")

async def log_admin(admin_id: int, action: str) -> None:
    """Записывает действие администратора в базу и уведомляет владельца."""
    await execute_db("INSERT INTO admin_logs (admin_id, action) VALUES (?, ?)", (admin_id, action))
    admin_info = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (admin_id,))
    name = get_display_name(admin_info) if admin_info else f"ID {admin_id}"
    await notify_super_admin(f"Админ: <b>{name}</b> ({admin_id})\nДействие: {action}")

async def broadcast_message(text: str) -> None:
    """Выполняет рассылку сообщения всем незабаненным пользователям."""
    users = await fetch_all("SELECT id FROM users WHERE banned = 0")
    success = 0
    for u in users:
        try:
            await bot.send_message(u['id'], text)
            success += 1
            await asyncio.sleep(0.05) # Защита от FloodWait
        except TelegramAPIError: pass
    await notify_super_admin(f"📢 <b>Рассылка завершена.</b>\nДоставлено: {success}/{len(users)}")

def get_main_keyboard(is_adm: bool = False) -> ReplyKeyboardMarkup:
    """Генерирует главную клавиатуру пользователя."""
    kb = [
        [KeyboardButton(text="🎴 Выбить карту"), KeyboardButton(text="⚔️ Поиск боя (боты)")],
        [KeyboardButton(text="🎒 Инвентарь"), KeyboardButton(text="🛡 Экипировка")],
        [KeyboardButton(text="🛒 Магазин"), KeyboardButton(text="📜 Квесты")],
        [KeyboardButton(text="⚔️ PvP Дуэль"), KeyboardButton(text="🏆 Топ игроков")],
        [KeyboardButton(text="💎 Донат-Магазин"), KeyboardButton(text="📖 Индекс")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🆘 Помощь (/help)")]
    ]
    if is_adm: kb.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

async def get_user_rank(trophies: int) -> dict:
    """Определяет ранг игрока по количеству трофеев."""
    ranks = await fetch_all("SELECT * FROM ranks ORDER BY min_trophies DESC")
    for r in ranks:
        if trophies >= r['min_trophies']: return r
    return {"name": "Bronze I", "difficulty_mult": 0.8, "reward_mult": 1.0}

async def get_active_events() -> Tuple[float, float]:
    """Возвращает текущие активные глобальные множители (удача, кулдаун)."""
    settings = await fetch_one("SELECT * FROM server_settings WHERE id = 1")
    now = time.time()
    luck = settings['luck_mult'] if settings['luck_end'] > now else 1.0
    cd = settings['cd_mult'] if settings['cd_end'] > now else 1.0
    return luck, cd

def roll_mutation(luck_mult: float = 1.0) -> str:
    """
    Бросает кубик на мутацию карты при выпадении.
    Ивент Удачи (luck_mult) увеличивает шанс на мутации.
    """
    r = random.random()
    # Базовые шансы: 2% Rainbow, 12% Gold. Умножаем на множитель удачи.
    rainbow_chance = 0.02 * luck_mult
    gold_chance = 0.12 * luck_mult
    
    if r <= rainbow_chance: return "Rainbow"
    if r <= (rainbow_chance + gold_chance): return "Gold"
    return "Normal"

def get_mutation_multiplier(mutation: str) -> float:
    """Возвращает множитель статов в зависимости от мутации."""
    if mutation == "Rainbow": return 1.2
    if mutation == "Gold": return 1.1
    return 1.0

def needs_serial_number(rarity: str, mutation: str) -> bool:
    """Определяет, нужен ли карте уникальный серийный номер."""
    if rarity == 'Leaderboard': return True
    if rarity in ['Mythic', 'Super']: return True
    if rarity == 'Legendary' and mutation != 'Normal': return True
    return False

async def give_card_to_user(user_id: int, card_id: int, mutation: str, rarity: str = None) -> Tuple[int, int, bool]:
    """
    Добавляет карту в инвентарь пользователя.
    Возвращает (inventory_id, serial_number, is_new_entry).
    """
    if not rarity:
        card = await fetch_one("SELECT rarity FROM cards WHERE id = ?", (card_id,))
        rarity = card['rarity'] if card else 'Basic'
        
    db = await get_db_connection()
    try:
        # Супер-Админ не расходует глобальные серийники
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

async def create_bordered_image(bot_instance: Bot, photo_id: str, rarity: str) -> str:
    """Скачивает изображение, накладывает рамку цвета редкости и загружает обратно в Telegram."""
    color = RARITY_COLORS.get(rarity, "gray")
    file = await bot_instance.get_file(photo_id)
    file_bytes = await bot_instance.download_file(file.file_path)
    
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
    
    msg = await bot_instance.send_photo(chat_id=SUPER_ADMIN_ID, photo=types.BufferedInputFile(bio.read(), filename="card.jpg"), caption=f"Сгенерирована рамка: {rarity}")
    return msg.photo[-1].file_id

def format_card_name(c: dict) -> str:
    """Генерирует красивое текстовое представление имени карты."""
    r_em = RARITY_EMOJI.get(c['rarity'], "⚪")
    c_em = CLASS_EMOJI.get(c['class_type'], "🎯")
    name = f"{r_em} {c_em} <b>{c['name']}</b>"
    if c.get('serial_number', 0) > 0:
        name += f" <b>[#{c['serial_number']:04d}]</b>"
    return name

def format_rarity_display(rarity: str) -> str:
    r_em = RARITY_EMOJI.get(rarity, "⚪")
    return f"{r_em} <b>{rarity.upper()}</b> {r_em}"

def get_pagination_keyboard(items: list, page: int, prefix: str, columns: int = 2, items_per_page: int = 8) -> InlineKeyboardMarkup:
    """Универсальная функция генерации инлайн-клавиатуры с пагинацией."""
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
# 6. КВЕСТЫ
# ========================================================================
async def add_quest_progress(user_id: int, field: str, amount: int = 1) -> None:
    """Добавляет прогресс в ежедневный квест игрока и выдает награду при выполнении всех."""
    if field not in ['q_cards_opened', 'q_rare_obtained', 'q_wins', 'q_battles', 'q_shop_buys']:
        return
        
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    if not user or user['quests_cooldown'] > time.time():
        return
        
    await execute_db(f"UPDATE users SET {field} = {field} + ? WHERE id = ?", (amount, user_id))
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    
    # Проверка выполнения всех квестов
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
        """, (time.time() + 3600, user_id)) # Кулдаун 1 час
        
        try:
            await bot.send_message(user_id, "🎉 <b>ПОЗДРАВЛЯЕМ!</b>\nВы выполнили все ежедневные квесты и получили <b>900 💰 Шекелей</b>!\nВозвращайтесь через 1 час за новыми заданиями!")
        except TelegramAPIError: pass

# ========================================================================
# 7. ЛОГИКА ШАНСОВ, ГАРАНТОВ И GACHA-СИСТЕМЫ
# ========================================================================
async def calculate_chance_weights(luck_mult: float = 1.0) -> Tuple[Dict[int, float], float]:
    """Рассчитывает веса для рулетки выпадения карт."""
    all_cards = await fetch_all("SELECT * FROM cards WHERE drop_chance > 0 AND rarity != 'Leaderboard'")
    if not all_cards: return {}, 0
    total_weight = 0.0
    weights_dict = {}
    
    for c in all_cards:
        weight = float(c['drop_chance'])
        if weight < 15.0: weight *= luck_mult
        weights_dict[c['id']] = weight
        total_weight += weight
        
    return weights_dict, total_weight

async def give_multiple_cards(user_id: int, count: int) -> list:
    """
    Выдает игроку указанное количество случайных карт с учетом Pity-системы.
    Шанс на пити изменен: 700 (вместо 1000).
    """
    luck_mult, _ = await get_active_events()
    user = await fetch_one("SELECT pity_mythic, pity_super, is_vip FROM users WHERE id=?", (user_id,))
    
    pm = user['pity_mythic']
    ps = user['pity_super']
    
    # VIP дает +10% к удаче
    actual_luck = luck_mult * 1.1 if user['is_vip'] else luck_mult

    all_cards = await fetch_all("SELECT * FROM cards WHERE drop_chance > 0 AND rarity != 'Leaderboard'")
    if not all_cards: return []
    
    super_cards = [c for c in all_cards if c['rarity'] == 'Super']
    mythic_cards = [c for c in all_cards if c['rarity'] == 'Mythic']
    weights = [c['drop_chance'] * (actual_luck if c['drop_chance'] < 15.0 else 1.0) for c in all_cards]
    
    results = []
    for _ in range(count):
        card = random.choices(all_cards, weights=weights, k=1)[0]
        is_pity = False
        p_type = None

        # PITY REBALANCE: Гарант на Мифик 700, на Супер 7000 (пропорционально)
        if ps + 1 >= 7000 and card['rarity'] != 'Super' and super_cards:
            card = random.choice(super_cards)
            is_pity = True
            p_type = 'Super'
        elif pm + 1 >= 700 and card['rarity'] not in ['Mythic', 'Super'] and mythic_cards:
            card = random.choice(mythic_cards)
            is_pity = True
            p_type = 'Mythic'

        # Сброс и накопление счетчиков Pity
        if card['rarity'] == 'Super': 
            ps = 0; pm += 1
        elif card['rarity'] == 'Mythic': 
            pm = 0; ps += 1
        else: 
            ps += 1; pm += 1

        mut = roll_mutation(actual_luck)
        _, serial, _ = await give_card_to_user(user_id, card['id'], mut, card['rarity'])

        c_copy = dict(card)
        c_copy['mutation'] = mut
        c_copy['serial_number'] = serial
        c_copy['is_pity'] = is_pity
        c_copy['pity_type'] = p_type
        results.append(c_copy)

    await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
    return results

# ========================================================================
# 8. МАГАЗИН И АВТОРЕСТОК
# ========================================================================
async def restock_shop() -> None:
    """Обновляет ассортимент глобального магазина за шекели."""
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

async def shop_auto_restock_task() -> None:
    """Фоновая задача автообновления магазина."""
    while True:
        try:
            settings = await fetch_one("SELECT last_restock FROM server_settings WHERE id = 1")
            now = time.time()
            if settings and (now - settings['last_restock'] >= 1.5 * 3600):
                await restock_shop()
        except Exception as e:
            logger.error(f"Shop restock error: {e}")
        await asyncio.sleep(60)

# ========================================================================
# 9. ГЛОБАЛЬНЫЕ ИВЕНТЫ
# ========================================================================
async def check_global_events() -> None:
    """Проверяет статусы глобальных ивентов, завершает истекшие и выдает награды."""
    events = await fetch_all("SELECT * FROM global_events WHERE is_active = 1")
    now = time.time()
    for ev in events:
        if now >= ev['end_time'] or ev['current_amount'] >= ev['target_amount']:
            # Завершение ивента
            await execute_db("UPDATE global_events SET is_active = 0 WHERE id = ?", (ev['id'],))
            
            participants = await fetch_all("SELECT * FROM event_participants WHERE event_id = ? ORDER BY contributed DESC LIMIT 10", (ev['id'],))
            
            msg = f"🎉 <b>ГЛОБАЛЬНЫЙ ИВЕНТ ЗАВЕРШЕН!</b>\nКоманда {ev['command']} больше неактивна.\n\n"
            msg += f"🎯 Цель: {ev['target_amount']} | Собрано: {ev['current_amount']}\n\n"
            
            if ev['current_amount'] >= ev['target_amount']:
                msg += "✅ <b>ЦЕЛЬ ДОСТИГНУТА!</b> Топ участники получают награды:\n"
                for idx, p in enumerate(participants, 1):
                    usr = await fetch_one("SELECT username, first_name FROM users WHERE id = ?", (p['user_id'],))
                    name = get_display_name(usr) if usr else "Неизвестный"
                    msg += f"{idx}. {name} — Внес: {p['contributed']}\n"
                    
                    # Награды в зависимости от места (пример)
                    reward_sh = 50000 if idx == 1 else (25000 if idx <= 3 else 10000)
                    await execute_db("UPDATE users SET coins = coins + ? WHERE id = ?", (reward_sh, p['user_id']))
                    try: await bot.send_message(p['user_id'], f"🎁 Спасибо за участие в глобальном ивенте!\nВы заняли {idx} место и получаете {reward_sh} 💰!")
                    except TelegramAPIError: pass
            else:
                msg += "❌ <b>Цель не была достигнута вовремя.</b>\nСпасибо всем за участие!"
                
            await broadcast_message(msg)

async def global_event_task() -> None:
    """Фоновый цикл проверки ивентов."""
    while True:
        try: await check_global_events()
        except Exception as e: logger.error(f"Global event check error: {e}")
        await asyncio.sleep(60)

# ========================================================================
# 10. ОСНОВНЫЕ КОМАНДЫ ПОЛЬЗОВАТЕЛЯ
# ========================================================================
@dp.message(Command("start"))
async def cmd_start(message: types.Message) -> None:
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
        "👋 <b>Добро пожаловать в обновленный Card Battle Bot!</b>\n\n"
        "Собери свою колоду уникальных юнитов, выставляй их в бой и поднимай кубки!\n\n"
        "Используй меню снизу для навигации. Если ты новичок, обязательно напиши /help",
        reply_markup=get_main_keyboard(adm)
    )

@dp.message(Command("profile"), F.chat.type == "private")
@dp.message(F.text == "👤 Профиль")
async def cmd_profile(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    rank = await get_user_rank(user['trophies'])
    total_cards = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE user_id = ?", (user['id'],))
    name = get_display_name(user)
    
    vip_str = "💎 <b>VIP АКТИВЕН</b>\n" if user['is_vip'] else ""
    x2_str = "🪙 <b>Активен множитель Х2 Шекели</b>\n" if user['has_x2_coins'] else ""
    
    text = (
        f"👤 <b>Профиль игрока {name}</b>\n\n"
        f"{vip_str}{x2_str}"
        f"🎖 <b>Ранг:</b> {rank['name']}\n"
        f"🏆 <b>Кубки:</b> {user['trophies']}\n"
        f"💰 <b>Шекели:</b> {user['coins']}\n"
        f"💵 <b>Робуксы:</b> {user['robux']}\n"
        f"🃏 <b>Всего карт:</b> {total_cards['s'] or 0}\n\n"
        f"🔮 <b>Pity (Гарант на Мифик):</b> {user['pity_mythic']}/700\n"
        f"🌠 <b>Pity (Гарант на Супер):</b> {user['pity_super']}/7000\n\n"
        f"⚔️ <b>Экипировка:</b>\n"
    )
    
    slots = ['equip1', 'equip2', 'equip3']
    if user['equip4'] > 0 or user['is_vip']: 
        slots.append('equip4') # Показывать 4 слот, если куплен или VIP
        
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
            else: text += f"{i}. [Удаленная карта]\n"
        else: text += f"{i}. [Пусто]\n"
            
    await message.answer(text)

@dp.message(Command("quests"))
@dp.message(F.text == "📜 Квесты")
async def cmd_quests(message: types.Message) -> None:
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
async def cmd_top(message: types.Message) -> None:
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

# ========================================================================
# 11. ГЛОБАЛЬНЫЙ МАГАЗИН И ПОКУПКИ
# ========================================================================
@dp.message(Command("shop"))
@dp.message(F.text == "🛒 Магазин")
async def cmd_shop(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT coins, is_vip FROM users WHERE id = ?", (message.from_user.id,))
    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    
    if not items:
        return await message.answer("🛒 Магазин пока пуст. Ближайший завоз скоро!")
        
    text = f"🛒 <b>Глобальный Магазин</b>\n💰 Твой баланс: {user['coins']} шекелей\n<i>(Товары общие для всех. Успей купить!)</i>\n\n"
    
    kb = []
    for i, item in enumerate(items, 1):
        price = int(item['price'] * 0.9) if user['is_vip'] else item['price']
        disc_text = " (VIP -10%)" if user['is_vip'] else ""
        
        text += f"📦 <b>{item['name']}</b>\n💵 Цена: <b>{price} 💰</b>{disc_text}\n📉 Осталось: {item['stock']} шт.\n\n"
        kb.append([InlineKeyboardButton(text=f"Купить: {item['name']} ({price} 💰)", callback_data=f"buy_shop_{item['id']}")])
        
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_shop_"))
async def callback_buy_shop(callback: types.CallbackQuery) -> None:
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
        luck_mult, _ = await get_active_events()
        actual_luck = luck_mult * 1.1 if user['is_vip'] else luck_mult
        
        mut = roll_mutation(actual_luck)
        _, serial, _ = await give_card_to_user(user_id, won_card['id'], mut, won_card['rarity'])
        won_card['serial_number'] = serial
        
        await add_quest_progress(user_id, 'q_cards_opened', 1)
        if won_card['rarity'] == 'Rare':
            await add_quest_progress(user_id, 'q_rare_obtained', 1)
            
        # Pity logic for guaranteed shop packs
        pm = user['pity_mythic']
        ps = user['pity_super']
        if target_rarity == 'Super': ps = 0; pm += 1
        elif target_rarity == 'Mythic': pm = 0; ps += 1
        else: ps += 1; pm += 1
        await execute_db("UPDATE users SET pity_mythic=?, pity_super=? WHERE id=?", (pm, ps, user_id))
        
        mut_str = "🌈 Радужная" if mut == 'Rainbow' else ("⭐ Золотая" if mut == 'Gold' else "Обычная")
        await callback.message.answer(f"🛍 <b>Покупка успешна!</b>\nГарантированная редкость {target_rarity}!\nВы выбили: {format_card_name(won_card)}\nМутация: {mut_str}")

    # Обновляем сообщение магазина
    items = await fetch_all("SELECT * FROM shop_items WHERE stock > 0")
    if not items:
        await callback.message.edit_text("🛒 <b>Магазин полностью распродан!</b>\nЖдите следующего завоза.")
    else:
        new_coins = user['coins'] - price
        text = f"🛒 <b>Глобальный Магазин</b>\n💰 Твой баланс: {new_coins} шекелей\n\n"
        kb = []
        for i, itm in enumerate(items, 1):
            p = int(itm['price'] * 0.9) if user['is_vip'] else itm['price']
            text += f"📦 <b>{itm['name']}</b>\n💵 Цена: <b>{p} 💰</b>\n📉 Осталось: {itm['stock']} шт.\n\n"
            kb.append([InlineKeyboardButton(text=f"Купить: {itm['name']} ({p} 💰)", callback_data=f"buy_shop_{itm['id']}")])
        try: await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
        except TelegramAPIError: pass
    
    await callback.answer()

# ========================================================================
# 12. ДОНАТ МАГАЗИН (Robux) И ОБМЕН ВАЛЮТ
# ========================================================================
@dp.message(Command("exchange"))
async def cmd_exchange(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await message.answer("ℹ️ <b>Обмен валюты</b>\nКурс: 500 Шекелей = 1 Робукс\nИспользование: `/exchange <количество_робуксов>`\nНапример: `/exchange 10` (спишет 5000 шекелей)")
        
    amount = int(args[1])
    if amount <= 0: return await message.answer("❌ Количество должно быть больше нуля.")
    
    cost = amount * 500
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (message.from_user.id,))
    if user['coins'] < cost:
        return await message.answer(f"❌ У вас недостаточно Шекелей!\nВам нужно {cost} 💰, а у вас {user['coins']} 💰.")
        
    await execute_db("UPDATE users SET coins = coins - ?, robux = robux + ? WHERE id = ?", (cost, amount, message.from_user.id))
    await message.answer(f"✅ <b>Успешный обмен!</b>\nСписано: {cost} 💰 Шекелей.\nЗачислено: {amount} 💵 Робуксов.")

@dp.message(Command("donate"))
@dp.message(F.text == "💎 Донат-Магазин")
async def cmd_donate(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT robux, is_vip, has_x2_coins, equip4 FROM users WHERE id = ?", (message.from_user.id,))
    
    text = f"💎 <b>ДОНАТ МАГАЗИН</b>\n💵 Твой баланс: <b>{user['robux']} Робуксов</b>\n\n"
    text += "<i>Здесь ты можешь приобрести премиум статусы и уникальных юнитов за Робуксы.</i>\n\n"
    
    kb = []
    
    # 1. VIP Статус
    if user['is_vip']:
        text += "👑 <b>VIP Статус</b> - УЖЕ КУПЛЕН ✅\n"
    else:
        text += "👑 <b>VIP Статус</b> (399 R$)\n<i>+10% ко всем наградам, +10% к удачи, -10% цены в магазине.</i>\n\n"
        kb.append([InlineKeyboardButton(text="Купить VIP (399 R$)", callback_data="buy_don_vip")])
        
    # 2. X2 Шекели
    if user['has_x2_coins']:
        text += "🪙 <b>X2 Шекели</b> - УЖЕ КУПЛЕН ✅\n"
    else:
        text += "🪙 <b>X2 Шекели навсегда</b> (199 R$)\n<i>Все получаемые шекели умножаются на 2.</i>\n\n"
        kb.append([InlineKeyboardButton(text="Купить X2 Шекели (199 R$)", callback_data="buy_don_x2")])
        
    # 3. +1 Слот Экипировки
    if user['equip4'] > 0 or user['is_vip']:
        text += "🎒 <b>+1 Слот Экипировки</b> - УЖЕ РАЗБЛОКИРОВАН ✅\n"
    else:
        text += "🎒 <b>Дополнительный (+4) Слот Экипировки</b> (449 R$)\n<i>Позволяет брать в бой 4 карты!</i>\n\n"
        kb.append([InlineKeyboardButton(text="Купить Слот (449 R$)", callback_data="buy_don_slot")])

    # 4. Кастомные юниты от админа
    custom_units = await fetch_all("SELECT d.id, d.price_robux, c.name, c.rarity FROM donate_shop d JOIN cards c ON d.card_id = c.id")
    if custom_units:
        text += "\n🃏 <b>УНИКАЛЬНЫЕ ЮНИТЫ АДМИНА:</b>\n<i>Шансы мутации: 20% Золотая, 10% Радужная.</i>\n"
        for cu in custom_units:
            text += f"• <b>{cu['name']}</b> ({cu['rarity']}) — <b>{cu['price_robux']} R$</b>\n"
            kb.append([InlineKeyboardButton(text=f"Купить {cu['name']} ({cu['price_robux']} R$)", callback_data=f"buy_don_unit_{cu['id']}")])
            
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(F.data.startswith("buy_don_"))
async def callback_donate_buy(callback: types.CallbackQuery) -> None:
    action = callback.data.split("_")[2]
    user_id = callback.from_user.id
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (user_id,))
    
    if action == "vip":
        if user['is_vip']: return await callback.answer("Уже куплено!", show_alert=True)
        if user['robux'] < 399: return await callback.answer("Недостаточно Робуксов!", show_alert=True)
        await execute_db("UPDATE users SET robux = robux - 399, is_vip = 1 WHERE id = ?", (user_id,))
        await callback.message.answer("🎉 <b>Поздравляем!</b> Вы успешно приобрели <b>VIP Статус</b>!")
        
    elif action == "x2":
        if user['has_x2_coins']: return await callback.answer("Уже куплено!", show_alert=True)
        if user['robux'] < 199: return await callback.answer("Недостаточно Робуксов!", show_alert=True)
        await execute_db("UPDATE users SET robux = robux - 199, has_x2_coins = 1 WHERE id = ?", (user_id,))
        await callback.message.answer("🎉 <b>Успех!</b> Теперь вы будете получать <b>в 2 раза больше Шекелей</b>!")
        
    elif action == "slot":
        # Логика слота (если есть VIP, слот может быть и так доступен, но дадим возможность купить если нет)
        if user['equip4'] != 0: return await callback.answer("Слот уже разблокирован!", show_alert=True)
        if user['robux'] < 449: return await callback.answer("Недостаточно Робуксов!", show_alert=True)
        await execute_db("UPDATE users SET robux = robux - 449, equip4 = -1 WHERE id = ?", (user_id,)) # -1 значит разблокирован, но пуст
        await callback.message.answer("🎉 <b>Успех!</b> Разблокирован 4-й слот экипировки! Настрой его в /equip")
        
    elif action == "unit":
        don_id = int(callback.data.split("_")[3])
        unit_data = await fetch_one("SELECT d.card_id, d.price_robux, c.name, c.rarity FROM donate_shop d JOIN cards c ON d.card_id = c.id WHERE d.id = ?", (don_id,))
        if not unit_data: return await callback.answer("Товар не найден!", show_alert=True)
        
        if user['robux'] < unit_data['price_robux']: return await callback.answer("Недостаточно Робуксов!", show_alert=True)
        
        # Специальные шансы мутации для донат-магазина
        r = random.random()
        if r < 0.10: mut = "Rainbow"
        elif r < 0.30: mut = "Gold" # 20%
        else: mut = "Normal"
        
        await execute_db("UPDATE users SET robux = robux - ? WHERE id = ?", (unit_data['price_robux'], user_id))
        _, serial, _ = await give_card_to_user(user_id, unit_data['card_id'], mut, unit_data['rarity'])
        
        mut_str = "🌈 РАДУЖНАЯ!" if mut == 'Rainbow' else ("⭐ ЗОЛОТАЯ!" if mut == 'Gold' else "Обычная")
        await callback.message.answer(f"🎉 <b>ПОКУПКА УСПЕШНА!</b>\nВы приобрели донат-юнита <b>{unit_data['name']}</b>!\nМутация: {mut_str}")
        
    # Перерисовываем меню
    await cmd_donate(callback.message)
    await callback.message.delete()
    await callback.answer()

# ========================================================================
# 13. ГАЧА: ВЫБИВАНИЕ КАРТ (/getcard)
# ========================================================================
@dp.message(Command("getcard"))
@dp.message(F.text == "🎴 Выбить карту")
async def cmd_getcard(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (message.from_user.id,))
    if not user: return await message.answer("Напишите /start")
    
    luck_mult, cd_mult = await get_active_events()
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
        
    actual_luck = luck_mult * 1.1 if user['is_vip'] else luck_mult
    if actual_luck > 1.0 and won_card['drop_chance'] < 15.0:
        msg += f"🍀 <i>Шанс был увеличен (Удача: x{round(actual_luck, 2)})!</i>"
        
    await message.answer_photo(photo=won_card['photo_id'], caption=msg)

# ========================================================================
# 14. ИНДЕКС И ИНВЕНТАРЬ
# ========================================================================
async def get_index_text(user_id: int, page: int = 0, items_per_page: int = 8) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
    all_cards = await fetch_all("SELECT * FROM cards")
    user_inv = await fetch_all("SELECT DISTINCT card_id FROM inventory WHERE user_id = ?", (user_id,))
    user_card_ids = [item['card_id'] for item in user_inv]
    
    if not all_cards: return "Индекс пуст.", None
    
    luck_mult, _ = await get_active_events()
    user = await fetch_one("SELECT is_vip FROM users WHERE id = ?", (user_id,))
    actual_luck = luck_mult * 1.1 if (user and user['is_vip']) else luck_mult
    weights_dict, total_w = await calculate_chance_weights(actual_luck)
    
    def index_sort_key(c):
        if c['rarity'] == 'Leaderboard': return -1
        return weights_dict.get(c['id'], 9999)
        
    all_cards.sort(key=index_sort_key)
    
    total_pages = max(1, math.ceil(len(all_cards) / items_per_page))
    page = max(0, min(page, total_pages - 1))
    
    text = f"📖 <b>Мировой Индекс Карт (Стр. {page+1}/{total_pages})</b>\n"
    if actual_luck > 1.0: text += f"🍀 <b>Ваша удача: x{round(actual_luck, 2)}. Шансы пересчитаны!</b>\n"
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
        chance_str = f"Шанс: {real_chance:.4f}%" if c['rarity'] != 'Leaderboard' else "Только за Топ!"
        
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
            
    kb = get_pagination_keyboard(all_cards, page, "idx", columns=2, items_per_page=items_per_page)
    return text, kb

@dp.message(Command("index"))
@dp.message(F.text == "📖 Индекс")
async def cmd_index(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    text, kb = await get_index_text(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("idx_page_"))
async def callback_index_page(callback: types.CallbackQuery) -> None:
    page = int(callback.data.split("_")[2])
    text, kb = await get_index_text(callback.from_user.id, page)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

async def get_inventory_text_and_kb(user_id: int, page: int = 0, items_per_page: int = 30) -> Tuple[str, Optional[InlineKeyboardMarkup]]:
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
        mut_emoji = "⭐ " if item['mutation'] == "Gold" else ("🌈 " if item['mutation'] == "Rainbow" else "")
        text += f"• {mut_emoji}{n_fmt} — {item['count']} шт.\n"
        
    kb = get_pagination_keyboard(inv, page, "inv", columns=2, items_per_page=items_per_page)
    return text, kb

@dp.message(Command("inventory"))
@dp.message(F.text == "🎒 Инвентарь")
async def cmd_inventory(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    text, kb = await get_inventory_text_and_kb(message.from_user.id, 0)
    await message.answer(text, reply_markup=kb)

@dp.callback_query(F.data.startswith("inv_page_"))
async def callback_inventory_page(callback: types.CallbackQuery) -> None:
    page = int(callback.data.split("_")[2])
    text, kb = await get_inventory_text_and_kb(callback.from_user.id, page)
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()

# ========================================================================
# 15. ЭКИПИРОВКА
# ========================================================================
def get_equip_main_keyboard(user_info: dict, cards_info: dict) -> InlineKeyboardMarkup:
    kb = []
    slots = ['equip1', 'equip2', 'equip3']
    if user_info['equip4'] != 0 or user_info['is_vip']:
        slots.append('equip4')
        
    for i, slot in enumerate(slots, 1):
        c_id = user_info.get(slot, 0)
        if c_id in [0, -1]:
            text = f"Слот {i} [Пусто]"
        else:
            text = f"Слот {i} [{cards_info.get(c_id, f'ID: {c_id}')}]"
        kb.append([InlineKeyboardButton(text=text, callback_data=f"eq_select_{i}")])
        
    kb.append([InlineKeyboardButton(text="❌ Снять всё", callback_data="eq_clear")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.message(Command("equip"))
@dp.message(F.text == "🛡 Экипировка")
async def cmd_equip(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4, is_vip FROM users WHERE id = ?", (message.from_user.id,))
    c_ids = [c for c in [user['equip1'], user['equip2'], user['equip3'], user.get('equip4', 0)] if c not in [0, -1]]
    cards_info = {}
    if c_ids:
        c_list = ",".join(map(str, c_ids))
        res = await fetch_all(f"SELECT id, name FROM cards WHERE id IN ({c_list})")
        for r in res: cards_info[r['id']] = r['name']
    await message.answer("🛡 <b>Настройка Боевой Колоды</b>\n\nНажмите на слот для изменения:", reply_markup=get_equip_main_keyboard(user, cards_info))

@dp.callback_query(F.data.startswith("eq_select_"))
async def equip_slot_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
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
async def equip_paginate_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    page = int(callback.data.split("_")[3])
    data = await state.get_data()
    kb = get_pagination_keyboard(data.get('equip_items', []), page, "eq_set", columns=1, items_per_page=8)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("eq_set_"))
async def equip_set_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if "page" in callback.data: return 
    card_id = int(callback.data.split("_")[2])
    data = await state.get_data()
    slot_num = data.get('equip_slot', 1)
    
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4 FROM users WHERE id = ?", (callback.from_user.id,))
    current_equips = [user['equip1'], user['equip2'], user['equip3']]
    if user.get('equip4') not in [0, -1]: current_equips.append(user['equip4'])
    
    if card_id in current_equips:
        return await callback.answer("❌ Эта карта уже экипирована в другом слоте!", show_alert=True)
        
    await execute_db(f"UPDATE users SET equip{slot_num} = ? WHERE id = ?", (card_id, callback.from_user.id))
    card = await fetch_one("SELECT name FROM cards WHERE id = ?", (card_id,))
    await callback.message.edit_text(f"✅ Карта <b>{card['name']}</b> успешно установлена в Слот {slot_num}!")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "eq_clear")
async def equip_clear_callback(callback: types.CallbackQuery) -> None:
    user = await fetch_one("SELECT equip4, is_vip FROM users WHERE id = ?", (callback.from_user.id,))
    eq4_val = -1 if (user['equip4'] != 0 or user['is_vip']) else 0
    await execute_db("UPDATE users SET equip1=0, equip2=0, equip3=0, equip4=? WHERE id = ?", (eq4_val, callback.from_user.id))
    
    new_user = await fetch_one("SELECT equip1, equip2, equip3, equip4, is_vip FROM users WHERE id = ?", (callback.from_user.id,))
    await callback.message.edit_text("✅ Все слоты очищены.", reply_markup=get_equip_main_keyboard(new_user, {}))
    await callback.answer()

# ========================================================================
# 16. БОЕВОЙ ДВИЖОК: ИИ И ДУЭЛИ
# ========================================================================
async def get_team_data(user_id: int) -> list:
    """Собирает команду игрока для боя, применяя мутации к статам."""
    user = await fetch_one("SELECT equip1, equip2, equip3, equip4, is_vip FROM users WHERE id = ?", (user_id,))
    team = []
    slots = ['equip1', 'equip2', 'equip3']
    if user['equip4'] not in [0, -1] or user['is_vip']:
        slots.append('equip4')
        
    for slot in slots:
        if user.get(slot, 0) not in [0, -1]:
            card = await fetch_one("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE id = ?", (user[slot],))
            if card:
                invs = await fetch_all("SELECT mutation, serial_number FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, card['id']))
                if not invs: continue
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
                card['stunned'] = False
                team.append(card)
    return team

async def get_bot_team(user_id: int, difficulty_mult: float, rank_name: str, team_size: int = 3) -> list:
    """Генерирует сбалансированную команду ботов на основе ранга игрока и сложности."""
    all_cards = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE rarity != 'Leaderboard'")
    if len(all_cards) < team_size: return []
    
    by_rarity = {}
    for c in all_cards:
        by_rarity.setdefault(c['rarity'], []).append(c)
        
    base_rank = rank_name.split()[0]
    team_selection = []
    
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
        
        if not pool: pool = all_cards
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
        c_copy['stunned'] = False
        c_copy['serial_number'] = 0
        team_copies.append(c_copy)
        
    return team_copies

def format_combat_team_vertical(team: list) -> str:
    """Форматирует визуальное отображение команды в бою."""
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
        if c.get('stunned', False): status += "⚡"
        if c.get('dmg_buff', 0) > 0: status += "✨"
        if c['class_type'] == 'Booster': status += "🔋"
        s_str = f" [#{c['serial_number']:04d}]" if c.get('serial_number', 0) > 0 else ""
        dmg = c['damage'] + c.get('dmg_buff', 0)
        res.append(f"• {c['name']}{s_str}{status} (⚔️{dmg} | ❤️{c['hp']}/{c['max_hp']})")
    return "\n".join(res)

def build_battle_header(p1_name: str, t1: list, p2_name: str, t2: list) -> str:
    return (
        f"⚔️ <b>БИТВА</b> ⚔️\n\n"
        f"🔵 <b>Команда {p1_name}:</b>\n{format_combat_team_vertical(t1)}\n\n"
        f"🔴 <b>Команда {p2_name}:</b>\n{format_combat_team_vertical(t2)}\n\n"
        f"📜 <b>Лог боя:</b>\n"
    )

def apply_boosters(team: list, team_name: str, log: list) -> None:
    """Применяет эффекты Бустеров ко всей команде перед началом битвы."""
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

async def process_poisons(team: list, team_name: str, log: list) -> None:
    """Обрабатывает урон от яда в начале хода."""
    for c in team:
        if c['hp'] > 0 and c.get('poison', 0) > 0:
            c['hp'] -= c['poison']
            log_str = f"🧪 {team_name}: <b>{c['name']}</b> получает {c['poison']} урона от яда!"
            if c['hp'] <= 0:
                c['hp'] = 0
                log_str += " ☠️ <i>Скончался!</i>"
            log.append(log_str)
            c['poison'] = 0 # Яд действует один ход, либо уменьшается. Сделаем спадение.

async def execute_turn(atk_team: list, def_team: list, atk_name: str, def_name: str, log: list, dmg_mult: float = 1.0) -> bool:
    """Выполняет один ход (атаку) команды. Обрабатывает новые классы."""
    await process_poisons(atk_team, atk_name, log)
    atk_alive = [c for c in atk_team if c['hp'] > 0]
    def_alive = [c for c in def_team if c['hp'] > 0]
    if not atk_alive or not def_alive: return False
    
    atk = random.choice(atk_alive)
    
    # Обработка Оглушения
    if atk.get('stunned', False):
        atk['stunned'] = False
        log.append(f"🌀 {atk_name}: <b>{atk['name']}</b> пропускает ход из-за оглушения!")
        return True # Ход потрачен
        
    base_dmg = int((atk['damage'] + atk.get('dmg_buff', 0)) * dmg_mult)
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
        
    elif c_type == "Poison": # Бывший Fire
        target = random.choice(def_alive)
        target['hp'] -= base_dmg
        target['poison'] = target.get('poison', 0) + int(base_dmg * 0.5)
        log_str = f"🧪 {atk_name}: <b>{atk['name']}</b> бьет <b>{target['name']}</b> на {base_dmg} и отравляет!"
        if target['hp'] <= 0: target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
        log.append(log_str)
        
    elif c_type == "Stunner": # Новый класс Оглушитель
        is_anyone_stunned = any(e.get('stunned', False) for e in def_alive)
        target = random.choice(def_alive)
        
        if not is_anyone_stunned:
            target['stunned'] = True
            stun_dmg = int(base_dmg * 0.5)
            target['hp'] -= stun_dmg
            log_str = f"⚡ {atk_name}: <b>{atk['name']}</b> оглушает <b>{target['name']}</b> и наносит {stun_dmg}!"
        else:
            target['hp'] -= base_dmg
            log_str = f"⚡ {atk_name}: <b>{atk['name']}</b> бьет <b>{target['name']}</b> на {base_dmg} (оглушение недоступно)!"
            
        if target['hp'] <= 0: target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
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

async def run_battle_loop(
    bot_instance: Bot, chat_id: int, 
    p1_id: int, p1_name: str, 
    p2_id: int, p2_name: str, 
    t1: list, t2: list, 
    diff_trophies_scale: float = 1.0, 
    is_pvp: bool = False, pvp_no_rewards: bool = False,
    mods: dict = {} # Модификаторы боя для PvE
):
    """Ядро боевой системы, обрабатывающее пошаговый бой и применение всех эффектов."""
    msg = await bot_instance.send_message(chat_id, f"⚔️ Бой <b>{p1_name}</b> VS <b>{p2_name}</b> начнется через 3 сек!")
    await asyncio.sleep(1)
    await msg.edit_text(f"⚔️ Бой начнется через 2 сек!")
    await asyncio.sleep(1)
    await msg.edit_text(f"⚔️ Бой начнется через 1 сек!")
    
    log = []
    apply_boosters(t1, p1_name, log)
    apply_boosters(t2, p2_name, log)
    
    # Применение модификаторов ХП (PvE)
    if not is_pvp:
        if mods.get('bot_hp_15'):
            for c in t2:
                c['max_hp'] = int(c['max_hp'] * 1.5)
                c['hp'] = c['max_hp']
        if mods.get('player_hp_12'):
            for c in t1:
                c['max_hp'] = int(c['max_hp'] * 1.2)
                c['hp'] = c['max_hp']
    
    if log:
        await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
        await asyncio.sleep(3)

    turn = 1
    winner = None
    
    player_dmg_mult = 0.8 if mods.get('player_weak') else 1.0
    
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

        # Ход 1-го игрока
        did_turn = await execute_turn(t1, t2, p1_name, p2_name, log, player_dmg_mult)
        
        # Доп ход игрока от модификатора
        if mods.get('player_fast') and any(c['hp'] > 0 for c in t2):
            did_turn = await execute_turn(t1, t2, f"{p1_name} (Вне очереди)", p2_name, log, player_dmg_mult)
            
        if did_turn:
            if len(log) > 6: log = log[-6:]
            await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
            await asyncio.sleep(3)

        # Проверка смерти после хода 1-го
        t2_alive = [c for c in t2 if c['hp'] > 0]
        if t2_alive:
            # Ход 2-го игрока (бота)
            did_turn = await execute_turn(t2, t1, p2_name, p1_name, log)
            
            # Доп ход бота от модификатора
            if mods.get('bot_fast') and any(c['hp'] > 0 for c in t1):
                did_turn = await execute_turn(t2, t1, f"{p2_name} (Вне очереди)", p1_name, log)
                
            if did_turn:
                if len(log) > 6: log = log[-6:]
                await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
                await asyncio.sleep(3)
        turn += 1

    # Завершение и награды
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
            user = await fetch_one("SELECT trophies, is_vip, has_x2_coins FROM users WHERE id = ?", (p1_id,))
            rank = await get_user_rank(user['trophies'])
            
            coins_won = int(random.randint(25, 90) * rank['reward_mult'] * diff_trophies_scale * 0.85)
            won_t = await get_dynamic_trophies(rank['name'], diff_trophies_scale)
            
            # VIP и X2 бонусы
            if user['is_vip']: 
                coins_won = int(coins_won * 1.1)
                won_t = int(won_t * 1.1)
            if user['has_x2_coins']:
                coins_won *= 2
            
            await execute_db("UPDATE users SET coins = coins + ?, trophies = trophies + ? WHERE id = ?", (coins_won, won_t, p1_id))
            final_text += f"🎉 Вы получили: <b>{coins_won} 💰 Шекелей</b> и <b>{won_t} 🏆</b>"
        elif winner == p2_name:
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 2) WHERE id = ?", (p1_id,))
            final_text += f"💀 Вы проиграли ИИ и потеряли 2 🏆."
            
    await msg.edit_text(final_text)
    active_combats.discard(p1_id)
    if is_pvp: active_combats.discard(p2_id)

# ========================================================================
# 17. СИСТЕМА МОДИФИКАТОРОВ БОЯ PvE
# ========================================================================
@dp.message(F.text == "⚔️ Поиск боя (боты)")
async def cmd_pve_select(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    if message.from_user.id in active_combats:
        return await message.answer("❌ Вы уже находитесь в бою или в поиске!")
        
    team1 = await get_team_data(message.from_user.id)
    if not team1: return await message.answer("❌ Экипируйте карты в 🛡 Экипировка!")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Лёгкий (-40% Наград)", callback_data="pve_diff_easy")],
        [InlineKeyboardButton(text="🟡 Средний (Стандарт)", callback_data="pve_diff_med")],
        [InlineKeyboardButton(text="🔴 Сложный (+25% Наград)", callback_data="pve_diff_hard")]
    ])
    await message.answer("⚔️ <b>Выберите сложность ИИ:</b>", reply_markup=kb)

def get_modifiers_keyboard(mods: dict) -> InlineKeyboardMarkup:
    """Генерирует клавиатуру-чекбоксы для модификаторов PvE боя."""
    def cb(key, text):
        icon = "✅" if mods.get(key) else "❌"
        return [InlineKeyboardButton(text=f"{icon} {text}", callback_data=f"pve_mod_{key}")]

    kb = [
        cb('bot_hp_15', "1.5x ХП Врагов (+15% Наград)"),
        cb('bot_fast', "Враг атакует дважды (+30%)"),
        cb('player_weak', "Ваш урон -20% (+20% Наград)"),
        cb('player_hp_12', "1.2x Ваше ХП (-25% Наград)"),
        cb('player_fast', "Вы атакуете дважды (-50%)"),
        [InlineKeyboardButton(text="▶️ НАЧАТЬ БОЙ ▶️", callback_data="pve_start_battle")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=kb)

@dp.callback_query(F.data.startswith("pve_diff_"))
async def cmd_pve_diff_select(callback: types.CallbackQuery, state: FSMContext) -> None:
    diff_type = callback.data.split("_")[2]
    
    await state.update_data(
        pve_diff=diff_type,
        mods={'bot_hp_15': False, 'bot_fast': False, 'player_weak': False, 'player_hp_12': False, 'player_fast': False}
    )
    
    await callback.message.edit_text(
        "⚙️ <b>Настройка Модификаторов Боя</b>\n\nВы можете усложнить или упростить бой, чтобы изменить множитель наград. Нажмите на модификатор для переключения:",
        reply_markup=get_modifiers_keyboard({})
    )
    await state.set_state(PvEModifiers.choosing)
    await callback.answer()

@dp.callback_query(PvEModifiers.choosing, F.data.startswith("pve_mod_"))
async def cmd_pve_mod_toggle(callback: types.CallbackQuery, state: FSMContext) -> None:
    mod_key = callback.data.replace("pve_mod_", "")
    data = await state.get_data()
    mods = data.get('mods', {})
    
    mods[mod_key] = not mods.get(mod_key, False)
    await state.update_data(mods=mods)
    
    await callback.message.edit_reply_markup(reply_markup=get_modifiers_keyboard(mods))
    await callback.answer()

@dp.callback_query(PvEModifiers.choosing, F.data == "pve_start_battle")
async def cmd_pve_battle_start(callback: types.CallbackQuery, state: FSMContext) -> None:
    if callback.from_user.id in active_combats:
        await state.clear()
        return await callback.answer("❌ Вы уже в бою!", show_alert=True)
        
    data = await state.get_data()
    diff_type = data.get('pve_diff', 'med')
    mods = data.get('mods', {})
    await state.clear()
    
    # Базовые множители из ТЗ
    if diff_type == "easy":
        power_mult = 0.7  
        trophies_scale = 0.6  # -40%
        diff_name = "Лёгкий"
    elif diff_type == "med":
        power_mult = 1.1  
        trophies_scale = 1.0
        diff_name = "Средний"
    elif diff_type == "hard":
        power_mult = 1.6  
        trophies_scale = 1.25 # +25%
        diff_name = "Сложный"
        
    # Применяем модификаторы к scale
    if mods.get('bot_hp_15'): trophies_scale += 0.15
    if mods.get('bot_fast'): trophies_scale += 0.30
    if mods.get('player_weak'): trophies_scale += 0.20
    if mods.get('player_hp_12'): trophies_scale -= 0.25
    if mods.get('player_fast'): trophies_scale -= 0.50
    
    # Не даем наградам упасть ниже 10% от базы
    trophies_scale = max(0.1, trophies_scale)
    
    await callback.message.edit_text(f"⚔️ Ищем бота... Сложность: <b>{diff_name}</b>\nМножитель наград: <b>x{round(trophies_scale, 2)}</b>")
    
    team1 = await get_team_data(callback.from_user.id)
    user = await fetch_one("SELECT * FROM users WHERE id = ?", (callback.from_user.id,))
    
    team_size = len(team1) if len(team1) > 0 else 3
    rank = await get_user_rank(user['trophies'])
    
    final_diff_mult = rank['difficulty_mult'] * power_mult
    team2 = await get_bot_team(callback.from_user.id, final_diff_mult, rank['name'], team_size=team_size)
    
    if not team2: return await callback.message.edit_text("❌ На сервере нет карт для бота.")
        
    p1_name = get_display_name(user)
    active_combats.add(callback.from_user.id)
    
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, callback.from_user.id, p1_name, 0, f"ИИ ({diff_name})", team1, team2, trophies_scale, is_pvp=False, mods=mods))
    await callback.answer()

# ========================================================================
# 18. ПОЛНОЕ РУКОВОДСТВО ПОМОЩИ (/help)
# ========================================================================
HELP_TEXTS = {
    "base": (
        "📚 <b>БАЗОВЫЕ МЕХАНИКИ</b>\n\n"
        "Вы попали в мир <b>Card Battle Bot</b>! Ваша цель — собирать крутые карты и побеждать врагов.\n\n"
        "• <b>🎴 Выбить карту</b>: Каждые 4 минуты (в базе) вы можете получать новую карту.\n"
        "• <b>🎒 Инвентарь</b>: Все ваши юниты хранятся здесь.\n"
        "• <b>🛡 Экипировка</b>: Обязательно установите до 3 (или 4 с VIP) юнитов в слоты перед боем!\n"
        "• <b>📜 Квесты</b>: Выполняйте 5 заданий в день, чтобы забрать 900 Шекелей.\n"
        "• <b>🔮 Гаранты (Pity)</b>: Если вам долго не падает Мифик (700 круток) или Супер (7000), вы получите их гарантированно!\n"
    ),
    "combat": (
        "⚔️ <b>БОЕВАЯ СИСТЕМА И КЛАССЫ</b>\n\n"
        "Юниты в бою бьют рандомные цели, но классы меняют правила:\n\n"
        "🎯 <b>Single</b> - Бьет мощно по 1 цели.\n"
        "🌪 <b>AOE</b> - Бьет всех врагов разом.\n"
        "🌊 <b>Splash</b> - Основной урон в одну цель, половина урона — в остальных.\n"
        "⚡ <b>Stunner</b> - Оглушает врага на 1 ход, заставляя его пропустить атаку. Наносит 50% урона. Если кто-то уже оглушен, бьет обычным уроном (100%).\n"
        "🧪 <b>Poison</b> - Наносит урон и отравляет врага (яд наносит доп. урон в начале хода врага).\n"
        "✨ <b>Booster</b> - Не атакует в лоб! Вместо этого перед боем он умножает урон и ХП всей вашей команды.\n"
    ),
    "events": (
        "🎉 <b>ИВЕНТЫ И МУТАЦИИ</b>\n\n"
        "Иногда Админ запускает Глобальные Ивенты (например на Х2 Удачу).\n"
        "Удача умножает шансы выбить редкую карту и повышает шансы на <b>Мутации</b>:\n\n"
        "⭐ <b>Золотая мутация</b>: Дает +10% к Урону и ХП юнита.\n"
        "🌈 <b>Радужная мутация</b>: Дает +20% к Урону и ХП.\n\n"
        "🌐 <b>Глобальные Цели</b>: Админ может объявить сбор Шекелей через особую команду (например, `/kotik`). Донатьте шекели, и если цель выполнится, Топ-участники получат огромные награды!"
    ),
    "donate": (
        "💎 <b>ДОНАТ МАГАЗИН И РОБУКСЫ</b>\n\n"
        "Вы можете обменять игровые 💰Шекели на 💵Робуксы с помощью команды:\n"
        "`/exchange <количество>` (Курс 500 шк = 1 РБ).\n\n"
        "В <b>Донат-Магазине</b> продаются:\n"
        "👑 <b>VIP Статус</b> - +10% ко всем наградам, УДАЧЕ и скидка в магазинах!\n"
        "🪙 <b>X2 Шекели</b> - Пассивный буст на весь аккаунт.\n"
        "🎒 <b>4-й Слот</b> - Возможность брать 4-ю карту в бой!\n"
        "🃏 Эксклюзивные донат-карты с повышенным шансом мутации (20% Голд, 10% Радуга)."
    )
}

def get_help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 База", callback_data="help_base"), InlineKeyboardButton(text="⚔️ Бои", callback_data="help_combat")],
        [InlineKeyboardButton(text="🎉 Ивенты/Мутации", callback_data="help_events"), InlineKeyboardButton(text="💎 Донат", callback_data="help_donate")]
    ])

@dp.message(Command("help"))
@dp.message(F.text == "🆘 Помощь (/help)")
async def cmd_help(message: types.Message) -> None:
    if await check_ban(message.from_user.id): return
    await message.answer(
        "🆘 <b>ГЛОБАЛЬНОЕ РУКОВОДСТВО</b>\n\nВыберите категорию, чтобы узнать больше:",
        reply_markup=get_help_keyboard()
    )

@dp.callback_query(F.data.startswith("help_"))
async def callback_help(callback: types.CallbackQuery) -> None:
    cat = callback.data.split("_")[1]
    text = HELP_TEXTS.get(cat, "Категория не найдена.")
    await callback.message.edit_text(text, reply_markup=get_help_keyboard())
    await callback.answer()

# ========================================================================
# 19. ПАНЕЛЬ АДМИНИСТРАТОРА И УПРАВЛЕНИЕ ГЛОБАЛЬНЫМИ ИВЕНТАМИ
# ========================================================================
def get_admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Карты", callback_data="adm_cards"), InlineKeyboardButton(text="👤 Игроки", callback_data="adm_users")],
        [InlineKeyboardButton(text="🎉 Ивенты (Удача/КД)", callback_data="adm_events"), InlineKeyboardButton(text="🌐 Глобал Ивенты", callback_data="adm_global")],
        [InlineKeyboardButton(text="💎 Донат Шоп", callback_data="adm_donshop"), InlineKeyboardButton(text="👑 Админы", callback_data="adm_admins")],
        [InlineKeyboardButton(text="📦 Бэкап БД", callback_data="adm_db")]
    ])

@dp.message(F.text == "⚙️ Админ-панель")
@dp.message(Command("admin"))
async def cmd_admin_panel(message: types.Message) -> None:
    if not await is_admin(message.from_user.id): return
    await message.answer("⚙️ <b>Панель Администратора</b>\nВыберите раздел:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_main")
async def cq_adm_main(callback: types.CallbackQuery) -> None:
    await callback.message.edit_text("⚙️ <b>Панель Администратора</b>\nВыберите раздел:", reply_markup=get_admin_main_kb())

@dp.callback_query(F.data == "adm_db")
async def cq_adm_db(callback: types.CallbackQuery) -> None:
    if callback.from_user.id != SUPER_ADMIN_ID: return await callback.answer("Только для Супер-Админа!", show_alert=True)
    try:
        await callback.message.answer_document(FSInputFile(DB_NAME), caption="📦 Актуальный бэкап базы данных.")
        await log_admin(callback.from_user.id, "Скачал бэкап БД.")
    except Exception as e:
        await callback.message.answer(f"Ошибка: {e}")
    await callback.answer()

@dp.callback_query(F.data == "adm_donshop")
async def cq_adm_donshop(callback: types.CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("💎 <b>Добавление карты в Донат-Шоп</b>\nВведите ID Карты:")
    await state.set_state(DonateShopAdd.card_id)
    await callback.answer()

@dp.message(DonateShopAdd.card_id)
async def cq_adm_don_card(message: types.Message, state: FSMContext) -> None:
    try:
        cid = int(message.text)
        await state.update_data(card_id=cid)
        await message.answer("Введите цену в <b>Робуксах</b>:")
        await state.set_state(DonateShopAdd.price_robux)
    except ValueError:
        await message.answer("Ошибка! Ожидалось число.")

@dp.message(DonateShopAdd.price_robux)
async def cq_adm_don_price(message: types.Message, state: FSMContext) -> None:
    try:
        price = int(message.text)
        data = await state.get_data()
        await execute_db("INSERT INTO donate_shop (card_id, price_robux) VALUES (?, ?)", (data['card_id'], price))
        await message.answer("✅ Карта добавлена в Донат-Магазин!")
        await log_admin(message.from_user.id, f"Добавлена карта ID {data['card_id']} в донат за {price} R$")
        await state.clear()
    except ValueError:
        await message.answer("Ошибка! Ожидалось число.")

@dp.callback_query(F.data == "adm_global")
async def cq_adm_global(callback: types.CallbackQuery, state: FSMContext) -> None:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать Ивент", callback_data="adm_global_create")],
        [InlineKeyboardButton(text="🛑 Остановить текущий", callback_data="adm_global_stop")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🌐 <b>Управление Глобальными Ивентами (Сборы)</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_global_create")
async def cq_adm_global_create(callback: types.CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("Придумайте команду ивента (напр. /kotik):")
    await state.set_state(GlobalEventCreate.command)
    await callback.answer()

@dp.message(GlobalEventCreate.command)
async def cq_global_cmd(message: types.Message, state: FSMContext) -> None:
    if not message.text.startswith('/'): return await message.answer("Команда должна начинаться с /")
    await state.update_data(command=message.text.strip())
    await message.answer("Введите цель сбора (число шекелей):")
    await state.set_state(GlobalEventCreate.goal)

@dp.message(GlobalEventCreate.goal)
async def cq_global_goal(message: types.Message, state: FSMContext) -> None:
    try:
        await state.update_data(goal=int(message.text))
        await message.answer("Сколько часов будет идти ивент?")
        await state.set_state(GlobalEventCreate.hours)
    except: await message.answer("Число!")

@dp.message(GlobalEventCreate.hours)
async def cq_global_hours(message: types.Message, state: FSMContext) -> None:
    try:
        hours = float(message.text)
        data = await state.get_data()
        end_time = time.time() + (hours * 3600)
        
        await execute_db("INSERT INTO global_events (command, target_amount, end_time) VALUES (?, ?, ?)", 
                         (data['command'], data['goal'], end_time))
                         
        await broadcast_message(
            f"🌟 <b>ВНИМАНИЕ! ЗАПУЩЕН НОВЫЙ ГЛОБАЛЬНЫЙ ИВЕНТ!</b> 🌟\n\n"
            f"Мы собираем <b>{data['goal']}</b> Шекелей!\n"
            f"Команда: `{data['command']} <сумма>` (минимум 500).\n"
            f"⏳ Время: {hours} часов.\n"
            f"Участвуйте, чтобы получить щедрые призы в конце!"
        )
        await message.answer("✅ Глобальный ивент запущен!")
        await state.clear()
    except: await message.answer("Число!")

@dp.callback_query(F.data == "adm_global_stop")
async def cq_adm_global_stop(callback: types.CallbackQuery) -> None:
    await execute_db("UPDATE global_events SET is_active = 0 WHERE is_active = 1")
    await callback.answer("Все активные сборы остановлены.", show_alert=True)

# ========================================================================
# 20. ДИНАМИЧЕСКИЙ ПЕРЕХВАТЧИК ДЛЯ ГЛОБАЛЬНЫХ ИВЕНТОВ
# ========================================================================
@dp.message(F.text.startswith('/'))
async def fallback_global_event_handler(message: types.Message) -> None:
    """Перехватывает неизвестные команды и проверяет, не являются ли они активным ивентом."""
    if await check_ban(message.from_user.id): return
    args = message.text.split()
    command = args[0]
    
    # Ищем активный ивент с такой командой
    event = await fetch_one("SELECT * FROM global_events WHERE is_active = 1 AND command = ?", (command,))
    if not event:
        # Если это не ивент, игнорируем (возможно, опечатка юзера)
        return
        
    if len(args) != 2 or not args[1].isdigit():
        return await message.answer(f"ℹ️ Использование ивента: `{command} <сумма>`\nМинимум: 500 шекелей.")
        
    amount = int(args[1])
    if amount < 500: return await message.answer("❌ Минимальный взнос в ивент: 500 шекелей!")
    
    user = await fetch_one("SELECT coins FROM users WHERE id = ?", (message.from_user.id,))
    if user['coins'] < amount: return await message.answer("❌ Недостаточно шекелей!")
    
    # Списываем шекели
    await execute_db("UPDATE users SET coins = coins - ? WHERE id = ?", (amount, message.from_user.id))
    
    # Записываем участника
    await execute_db("""
        INSERT INTO event_participants (event_id, user_id, contributed) 
        VALUES (?, ?, ?) 
        ON CONFLICT(event_id, user_id) 
        DO UPDATE SET contributed = contributed + ?
    """, (event['id'], message.from_user.id, amount, amount))
    
    # Обновляем прогресс ивента
    await execute_db("UPDATE global_events SET current_amount = current_amount + ? WHERE id = ?", (amount, event['id']))
    
    await message.answer(f"✅ Вы успешно пожертвовали <b>{amount} 💰</b> в глобальный ивент!\nСпасибо за участие!")

# ========================================================================
# 21. ИНИЦИАЛИЗАЦИЯ И ЗАПУСК БОТА
# ========================================================================
async def main() -> None:
    """Точка входа. Настраивает БД и запускает фоновые таски."""
    logger.info("Initializing Database...")
    await check_and_update_schema()
    
    logger.info("Starting Background Tasks...")
    asyncio.create_task(shop_auto_restock_task())
    asyncio.create_task(global_event_task())
    
    logger.info("Bot is ready. Starting Polling...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        logger.info("Shutting down cleanly...")
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot execution stopped by user.")
