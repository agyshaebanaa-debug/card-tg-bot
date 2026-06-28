import asyncio
import logging
import random
import time
import io
import os
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
    from PIL import Image, ImageOps
except ImportError:
    raise ImportError("Установите Pillow: pip install Pillow")

import aiosqlite

# ========================================================================
# КОНФИГУРАЦИЯ БОТА
# ========================================================================
BOT_TOKEN = "7725898870:AAHa-6biiZkWuheNzjPl0Tun3XpNyLNq1lE" # Замени на свой токен
SUPER_ADMIN_ID = 5341904332 # Замени на свой Telegram ID (тут будут логи)
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
    "Godly": "darkblue",
    "Secret": "black",
    "Exclusive": "lightpink"
}

RARITY_EMOJI = {
    "Basic": "⚪",
    "Uncommon": "🟢",
    "Rare": "🔵",
    "Epic": "🟣",
    "Legendary": "🟡",
    "Mythic": "🔴",
    "Godly": "🌌",
    "Secret": "⚫",
    "Exclusive": "🌸"
}

CLASS_EMOJI = {
    "AOE": "🌪",
    "Splash": "🌊",
    "Booster": "✨",
    "Single": "🎯",
    "Fire": "🔥"
}

CLASSES = list(CLASS_EMOJI.keys())

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
    """Умная проверка БД. Добавит нужные колонки для Бустеров."""
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
        
        # Таблица cards (Добавлены booster_dmg_mult и booster_hp_mult)
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
        
        # Пытаемся добавить колонки бустеров, если это старая БД
        try:
            await db.execute("ALTER TABLE cards ADD COLUMN booster_dmg_mult REAL DEFAULT 1.0")
            await db.execute("ALTER TABLE cards ADD COLUMN booster_hp_mult REAL DEFAULT 1.0")
        except aiosqlite.OperationalError:
            pass # Колонки уже есть
            
        # Таблица inventory
        await db.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                card_id INTEGER,
                count INTEGER DEFAULT 1
            )
        """)
        
        # Таблица ranks
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ranks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                min_trophies INTEGER,
                difficulty_mult REAL DEFAULT 1.0,
                reward_mult REAL DEFAULT 1.0
            )
        """)
        
        # Таблица настроек сервера (ивенты)
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
# ЛОГИКА НОРМАЛИЗАЦИИ ШАНСОВ (ВСЕГДА 100%)
# ========================================================================
async def normalize_chances():
    """Суммирует все шансы и пропорционально подгоняет их под 100%"""
    cards = await fetch_all("SELECT id, drop_chance FROM cards")
    if not cards: return
    
    total = sum(c['drop_chance'] for c in cards)
    db = await get_db_connection()
    try:
        if total <= 0:
            # Если шансы сломаны, распределяем поровну
            eq = 100.0 / len(cards)
            for c in cards:
                await db.execute("UPDATE cards SET drop_chance = ? WHERE id = ?", (eq, c['id']))
        else:
            # Вычисляем фактор масштабирования
            factor = 100.0 / total
            for c in cards:
                new_val = round(c['drop_chance'] * factor, 4)
                await db.execute("UPDATE cards SET drop_chance = ? WHERE id = ?", (new_val, c['id']))
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
    # Ветка для обычных классов
    damage = State()
    hp = State()
    # Ветка для бустеров
    booster_dmg = State()
    booster_hp = State()

class EditCard(StatesGroup):
    card_id = State()
    waiting_new_value = State()

class GiveCard(StatesGroup):
    user_id = State()
    card_id = State()

class AdminBan(StatesGroup):
    user_id = State()
    
class AdminGiveTrophies(StatesGroup):
    user_id = State()
    amount = State()

class EventLuck(StatesGroup):
    mult = State()
    mins = State()

class EventCD(StatesGroup):
    mult = State()
    mins = State()

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

async def notify_super_admin(text: str):
    """Отправляет лог главному админу"""
    try:
        await bot.send_message(SUPER_ADMIN_ID, f"⚠️ <b>АДМИН-ЛОГ:</b>\n{text}")
    except Exception as e:
        logging.error(f"Не удалось отправить лог главному админу: {e}")

async def log_admin(admin_id: int, action: str):
    await execute_db("INSERT INTO admin_logs (admin_id, action) VALUES (?, ?)", (admin_id, action))
    admin_info = await fetch_one("SELECT username FROM users WHERE id = ?", (admin_id,))
    name = admin_info['username'] if admin_info else f"ID {admin_id}"
    await notify_super_admin(f"Админ: <b>{name}</b> ({admin_id})\nДействие: {action}")

async def broadcast_message(text: str):
    """Отправляет сообщение всем зарегистрированным пользователям"""
    users = await fetch_all("SELECT id FROM users WHERE banned = 0")
    success = 0
    for u in users:
        try:
            await bot.send_message(u['id'], text)
            success += 1
            await asyncio.sleep(0.05) # Лимиты Telegram
        except:
            pass
    await notify_super_admin(f"📢 <b>Рассылка завершена.</b>\nДоставлено: {success}/{len(users)}")

def get_main_keyboard(is_adm: bool = False):
    kb = [
        [KeyboardButton(text="🎴 Выбить карту"), KeyboardButton(text="⚔️ Поиск боя (боты)")],
        [KeyboardButton(text="🎒 Инвентарь"), KeyboardButton(text="🛡 Экипировка")],
        [KeyboardButton(text="👤 Профиль"), KeyboardButton(text="🏆 Топ игроков")],
        [KeyboardButton(text="📖 Индекс")]
    ]
    if is_adm:
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

def format_card_name(c):
    r_em = RARITY_EMOJI.get(c['rarity'], "⚪")
    c_em = CLASS_EMOJI.get(c['class_type'], "🎯")
    return f"{r_em} {c_em} <b>{c['name']}</b>"

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
        "/getcard - Выбить случайную карту\n"
        "/inventory - Ваш инвентарь юнитов\n"
        "/equip - Настройка боевой колоды\n"
        "/duel - Вызвать игрока на бой (в ответе на сообщение)\n"
        "/top - Топ 20 игроков\n"
        "/index - Энциклопедия карт\n"
        "/profile - Посмотреть свой профиль\n"
    )
    if await is_admin(message.from_user.id):
        text += "\n👑 <b>Админ:</b> Используйте кнопку ⚙️ Админ-панель в меню."
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
            card = await fetch_one("SELECT name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE id = ?", (user[slot],))
            if card:
                n = format_card_name(card)
                if card['class_type'] == 'Booster':
                    text += f"{i}. {n} (Урон x{card['booster_dmg_mult']} | ХП x{card['booster_hp_mult']})\n"
                else:
                    text += f"{i}. {n} (⚔️{card['damage']} | ❤️{card['hp']})\n"
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
        
    # Шансы берутся напрямую из БД. Нормализация гарантирует, что они равны 100%.
    weights = []
    for c in all_cards:
        chance = c['drop_chance']
        if chance < 15.0: chance *= luck_mult # Удача работает на редкие карты
        weights.append(chance)
        
    won_card = random.choices(all_cards, weights=weights, k=1)[0]
    
    inv_item = await fetch_one("SELECT id FROM inventory WHERE user_id = ? AND card_id = ?", (user['id'], won_card['id']))
    if inv_item:
        await execute_db("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
    else:
        await execute_db("INSERT INTO inventory (user_id, card_id) VALUES (?, ?)", (user['id'], won_card['id']))
        
    await execute_db("UPDATE users SET last_getcard = ? WHERE id = ?", (now, user['id']))
    
    n_fmt = format_card_name(won_card)
    msg = f"🎉 <b>ПОЗДРАВЛЯЕМ! ВЫ ВЫБИЛИ КАРТУ!</b>\n\n🃏 {n_fmt}\n💎 <b>Редкость:</b> {won_card['rarity']}\n"
    
    if won_card['class_type'] == 'Booster':
        msg += f"✨ <b>БУСТЕР:</b> Усиливает союзников!\n⚔️ Урон: x{won_card['booster_dmg_mult']} | ❤️ ХП: x{won_card['booster_hp_mult']}\n\n"
    else:
        msg += f"⚔️ <b>Урон:</b> {won_card['damage']} | ❤️ <b>Здоровье:</b> {won_card['hp']}\n\n"
        
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
    
    if not all_cards: return await message.answer("Индекс пуст.")
        
    text = "📖 <b>Мировой Индекс Карт (Сумма шансов 100%):</b>\n\n"
    for i, c in enumerate(all_cards, 1):
        exists = await fetch_one("SELECT SUM(count) as s FROM inventory WHERE card_id = ?", (c['id'],))
        total_exists = exists['s'] if exists and exists['s'] else 0
        n_fmt = format_card_name(c)
        
        if c['id'] in user_card_ids:
            text += f"{i}. {n_fmt} [ID: {c['id']}]\n"
            text += f"💎 Шанс: {round(c['drop_chance'], 2)}%\n"
            if c['class_type'] == 'Booster':
                text += f"✨ Бафф: DMG x{c['booster_dmg_mult']} // HP x{c['booster_hp_mult']}\n"
            else:
                text += f"⚔️ Урон: {c['damage']} // ❤️ Здоровье: {c['hp']}\n"
            text += f"🌍 Существует: {total_exists} шт.\n\n"
        else:
            text += f"{i}. <b>???</b> (У вас нет этой карты)\n"
            text += f"💎 Шанс: {round(c['drop_chance'], 2)}%\n"
            text += f"🌍 Существует: {total_exists} шт.\n\n"
            
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
    
    if not inv: return await message.answer("🎒 Ваш инвентарь пуст. Используйте /getcard")
        
    text = "🎒 <b>Ваш Инвентарь:</b>\n\n"
    for item in inv:
        n_fmt = format_card_name(item)
        text += f"[ID: {item['id']}] {n_fmt} — {item['count']} шт.\n"
        
    text += "\n<i>Используйте ID карты (в квадратных скобках) для экипировки.</i>"
    
    for x in range(0, len(text), 4000):
        await message.answer(text[x:x+4000])

# ========================================================================
# ЭКИПИРОВКА
# ========================================================================
def equip_keyboard(user_info):
    kb = []
    for i, slot in enumerate(['equip1', 'equip2', 'equip3'], 1):
        c_id = user_info[slot]
        text = f"Слот {i} [Пусто]" if c_id == 0 else f"Слот {i} [ID: {c_id}]"
        kb.append(InlineKeyboardButton(text=text, callback_data=f"equip_slot_{i}"))
        
    return InlineKeyboardMarkup(inline_keyboard=[
        kb,
        [InlineKeyboardButton(text="❌ Снять всё", callback_data="equip_clear")]
    ])

@dp.message(Command("equip"))
@dp.message(F.text == "🛡 Экипировка")
async def cmd_equip(message: types.Message):
    if await check_ban(message.from_user.id): return
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (message.from_user.id,))
    await message.answer("🛡 <b>Настройка Боевой Колоды</b>\n\nВыберите слот, который хотите изменить:", reply_markup=equip_keyboard(user))

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
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (callback.from_user.id,))
    await callback.message.edit_text("✅ Все слоты экипировки очищены.", reply_markup=equip_keyboard(user))
    await callback.answer()

# ========================================================================
# БОЕВОЙ ДВИЖОК (ПЕРЕРАБОТАННЫЕ КЛАССЫ И ЛОГИКА)
# ========================================================================
async def get_team_data(user_id: int):
    user = await fetch_one("SELECT equip1, equip2, equip3 FROM users WHERE id = ?", (user_id,))
    team = []
    for slot in ['equip1', 'equip2', 'equip3']:
        if user[slot] != 0:
            card = await fetch_one("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards WHERE id = ?", (user[slot],))
            if card:
                # Базовые параметры для боя
                card['max_hp'] = card['hp']
                card['burn'] = 0     
                card['dmg_buff'] = 0 
                team.append(card)
    return team

async def get_bot_team(difficulty_mult: float):
    all_cards = await fetch_all("SELECT id, name, rarity, class_type, damage, hp, booster_dmg_mult, booster_hp_mult FROM cards")
    if len(all_cards) < 3: return []
    
    team = random.sample(all_cards, 3)
    for c in team:
        c['damage'] = int(c['damage'] * difficulty_mult)
        c['hp'] = int(c['hp'] * difficulty_mult)
        c['max_hp'] = c['hp']
        c['burn'] = 0
        c['dmg_buff'] = 0
    return team

def format_combat_hp(c):
    status = ""
    if c.get('burn', 0) > 0: status += "🔥"
    if c.get('dmg_buff', 0) > 0: status += "✨"
    if c['class_type'] == 'Booster': status += "🔋"
    return f"{c['name']}{status} (❤️{c['hp']}/{c['max_hp']})"

def build_battle_header(p1_name, t1, p2_name, t2):
    t1_text = " | ".join([format_combat_hp(c) for c in t1])
    t2_text = " | ".join([format_combat_hp(c) for c in t2])
    
    return (
        f"⚔️ <b>БИТВА НАЧАЛАСЬ</b> ⚔️\n\n"
        f"🔵 <b>Команда {p1_name}:</b>\n{t1_text or 'Все мертвы'}\n\n"
        f"🔴 <b>Команда {p2_name}:</b>\n{t2_text or 'Все мертвы'}\n\n"
        f"📜 <b>Лог боя:</b>\n"
    )

def apply_boosters(team, team_name, log):
    """Единоразовое применение баффов от бустеров в начале боя"""
    boosters = [c for c in team if c['class_type'] == 'Booster']
    if not boosters: return
    
    for b in boosters:
        d_mult = b['booster_dmg_mult']
        h_mult = b['booster_hp_mult']
        log.append(f"✨ <b>{team_name}:</b> Бустер <b>{b['name']}</b> усиливает команду! (Урон x{d_mult}, ХП x{h_mult})")
        
        for c in team:
            # Увеличиваем ХП
            bonus_hp = int(c['hp'] * h_mult) - c['hp']
            if bonus_hp > 0:
                c['hp'] += bonus_hp
                c['max_hp'] += bonus_hp
            
            # Если это не бустер, даем ему бафф к урону
            if c['class_type'] != 'Booster':
                c['dmg_buff'] += int(c['damage'] * d_mult) - c['damage']

async def process_burns(team, team_name, log):
    """Урон от горения в начале хода"""
    for c in team:
        if c['hp'] > 0 and c.get('burn', 0) > 0:
            c['hp'] -= c['burn']
            log_str = f"🔥 {team_name}: <b>{c['name']}</b> получает {c['burn']} урона от горения!"
            if c['hp'] <= 0:
                c['hp'] = 0
                log_str += " ☠️ <i>Сгорел дотла!</i>"
            log.append(log_str)
            c['burn'] = 0 # Спадает после 1 тика

async def execute_turn(atk_team, def_team, atk_name, def_name, log):
    await process_burns(atk_team, atk_name, log)
    
    atk_alive = [c for c in atk_team if c['hp'] > 0]
    def_alive = [c for c in def_team if c['hp'] > 0]
    
    if not atk_alive or not def_alive: return False
    
    atk = random.choice(atk_alive)
    base_dmg = atk['damage'] + atk.get('dmg_buff', 0)
    c_type = atk['class_type']
    
    if c_type == "Booster":
        # Бустеры уже раздали баффы, теперь они просто бьют слабым дефолтным ударом (например, 10% от макс хп врага)
        target = random.choice(def_alive)
        dmg = max(10, int(target['max_hp'] * 0.1))
        target['hp'] -= dmg
        log_str = f"🔋 {atk_name}: <b>{atk['name']}</b> (Booster) пускает заряд в <b>{target['name']}</b> на {dmg}!"
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
        log_str = f"🔥 {atk_name}: <b>{atk['name']}</b> бьет <b>{target['name']}</b> на {base_dmg} и поджигает его!"
        if target['hp'] <= 0:
            target['hp'] = 0; log_str += f" ☠️ <i>Мертв!</i>"
        log.append(log_str)
        
    else: # Single
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
    await msg.edit_text(f"⚔️ Бой начнется через 2 секунды!")
    await asyncio.sleep(1)
    await msg.edit_text(f"⚔️ Бой начнется через 1 секунду!")
    
    log = []
    # Фаза Бустеров (единоразово)
    apply_boosters(t1, p1_name, log)
    apply_boosters(t2, p2_name, log)
    
    if log:
        await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
        await asyncio.sleep(3)

    turn = 1
    
    while True:
        t1_alive = [c for c in t1 if c['hp'] > 0]
        t2_alive = [c for c in t2 if c['hp'] > 0]
        
        if not t1_alive and not t2_alive:
            winner = "Ничья"
            break
        elif not t1_alive:
            winner = p2_name; winner_id = p2_id; loser_id = p1_id
            break
        elif not t2_alive:
            winner = p1_name; winner_id = p1_id; loser_id = p2_id
            break
            
        if turn > 30:
            winner = "Ничья по таймауту"
            break

        # Ход 1 Команды
        did_turn = await execute_turn(t1, t2, p1_name, p2_name, log)
        if did_turn:
            if len(log) > 6: log = log[-6:]
            await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
            await asyncio.sleep(3)

        # Ход 2 Команды
        t2_alive = [c for c in t2 if c['hp'] > 0]
        if t2_alive:
            did_turn = await execute_turn(t2, t1, p2_name, p1_name, log)
            if did_turn:
                if len(log) > 6: log = log[-6:]
                await msg.edit_text(build_battle_header(p1_name, t1, p2_name, t2) + "\n".join(log))
                await asyncio.sleep(3)
        turn += 1

    # Замена логов на красивый экран итогов
    final_text = f"🏁 <b>ИТОГИ БОЯ: {p1_name} VS {p2_name}</b>\n\n👑 <b>Победитель: {winner}</b>\n\n"
    
    settings = await fetch_one("SELECT * FROM server_settings WHERE id = 1")
    if is_pvp:
        if winner not in ["Ничья", "Ничья по таймауту"]:
            await execute_db("UPDATE users SET trophies = trophies + 15 WHERE id = ?", (winner_id,))
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 10) WHERE id = ?", (loser_id,))
            final_text += f"🏆 Победитель забирает +15 Кубков\n💀 Проигравший теряет -10 Кубков"
    else:
        if winner == p1_name:
            user = await fetch_one("SELECT trophies FROM users WHERE id = ?", (p1_id,))
            rank = await get_user_rank(user['trophies'])
            
            coins_won = int(random.randint(settings['min_coins'], settings['max_coins']) * rank['reward_mult'])
            await execute_db("UPDATE users SET coins = coins + ?, trophies = trophies + 5 WHERE id = ?", (coins_won, p1_id))
            final_text += f"🎉 Вы получили: <b>{coins_won} 💰</b> и <b>5 🏆</b>"
        elif winner == p2_name:
            await execute_db("UPDATE users SET trophies = MAX(0, trophies - 2) WHERE id = ?", (p1_id,))
            final_text += f"💀 Вы проиграли ИИ и потеряли 2 🏆."
            
    await msg.edit_text(final_text)

@dp.message(F.text == "⚔️ Поиск боя (боты)")
async def cmd_pve_battle(message: types.Message):
    if await check_ban(message.from_user.id): return
    team1 = await get_team_data(message.from_user.id)
    if not team1: return await message.answer("❌ Экипируйте карты в /equip!")
        
    user = await fetch_one("SELECT trophies FROM users WHERE id = ?", (message.from_user.id,))
    rank = await get_user_rank(user['trophies'])
    
    team2 = await get_bot_team(rank['difficulty_mult'])
    if not team2: return await message.answer("❌ На сервере нет карт для бота.")
        
    asyncio.create_task(run_battle_loop(bot, message.chat.id, message.from_user.id, message.from_user.username or "Игрок", 0, f"ИИ ({rank['name']})", team1, team2, is_pvp=False))

# ========================================================================
# ДУЭЛИ (PvP В ГРУППАХ)
# ========================================================================
active_duels = {}

@dp.message(Command("duel"))
async def cmd_duel(message: types.Message):
    if message.chat.type not in ["group", "supergroup"]:
        return await message.answer("❌ Дуэли только в группах!")
    if not message.reply_to_message:
        return await message.answer("❌ Ответьте на сообщение игрока командой /duel")
        
    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id or target_id == bot.id:
        return await message.answer("❌ Нельзя вызвать себя или бота.")
        
    team1 = await get_team_data(message.from_user.id)
    if not team1: return await message.answer("❌ Вы не экипированы!")
    team2 = await get_team_data(target_id)
    if not team2: return await message.answer("❌ Противник не экипирован!")
        
    duel_id = f"{message.from_user.id}_{target_id}_{time.time()}"
    active_duels[duel_id] = {
        "p1_id": message.from_user.id, "p1_name": message.from_user.username or "Игрок 1",
        "p2_id": target_id, "p2_name": message.reply_to_message.from_user.username or "Игрок 2",
        "t1": team1, "t2": team2
    }
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⚔️ ПРИНЯТЬ", callback_data=f"accept_duel_{duel_id}")]])
    await message.answer(f"🥊 {active_duels[duel_id]['p1_name']} вызывает {active_duels[duel_id]['p2_name']} на дуэль!", reply_markup=kb)

@dp.callback_query(F.data.startswith("accept_duel_"))
async def accept_duel_callback(callback: types.CallbackQuery):
    duel_id = callback.data.replace("accept_duel_", "")
    if duel_id not in active_duels: return await callback.answer("Устарело.", show_alert=True)
        
    duel = active_duels[duel_id]
    if callback.from_user.id != duel['p2_id']: return await callback.answer("Это не вам!", show_alert=True)
        
    await callback.message.delete()
    del active_duels[duel_id]
    asyncio.create_task(run_battle_loop(bot, callback.message.chat.id, duel['p1_id'], duel['p1_name'], duel['p2_id'], duel['p2_name'], duel['t1'], duel['t2'], is_pvp=True))

# ========================================================================
# ПАНЕЛЬ АДМИНИСТРАТОРА (INLINE)
# ========================================================================
def get_admin_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🃏 Управление Картами", callback_data="adm_cards")],
        [InlineKeyboardButton(text="👤 Управление Игроками", callback_data="adm_users")],
        [InlineKeyboardButton(text="🎉 Ивенты", callback_data="adm_events")],
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

# --- РАЗДЕЛ: КАРТЫ ---
@dp.callback_query(F.data == "adm_cards")
async def cq_adm_cards(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать карту", callback_data="adm_card_add")],
        [InlineKeyboardButton(text="✏️ Редактировать карту", callback_data="adm_card_edit")],
        [InlineKeyboardButton(text="🗑 Удалить карту", callback_data="adm_card_del")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🃏 <b>Управление Картами</b>\n<i>Любое изменение шансов автоматически нормализует всю БД до 100%.</i>", reply_markup=kb)

# --- СОЗДАНИЕ КАРТЫ (С РАЗВЕТВЛЕНИЕМ НА БУСТЕРЫ) ---
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
    await message.answer("Введи желаемый шанс (бот сам подгонит всё под 100%):")
    await state.set_state(AddCard.drop_chance)

@dp.message(AddCard.drop_chance)
async def add_card_chance(message: types.Message, state: FSMContext):
    try:
        chance = float(message.text)
        await state.update_data(drop_chance=chance)
        kb = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=r)] for r in RARITY_COLORS.keys()], resize_keyboard=True)
        await message.answer("Выбери редкость (для косметики):", reply_markup=kb)
        await state.set_state(AddCard.rarity)
    except:
        await message.answer("❌ Должно быть число!")

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
        await state.update_data(booster_dmg_mult=float(message.text), damage=0)
        await message.answer("Введи множитель ХП (например, 1.2):")
        await state.set_state(AddCard.booster_hp)
    except: await message.answer("❌ Число!")

@dp.message(AddCard.booster_hp)
async def add_card_boost_hp(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        hp_mult = float(message.text)
        await message.answer("⏳ Генерирую рамку редкости для карты, подождите...")
        
        new_photo_id = await create_bordered_image(bot, data['photo'], data['rarity'])
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id, booster_dmg_mult, booster_hp_mult) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data['name'], data['rarity'], data['class_type'], 0, 0, data['drop_chance'], new_photo_id, data['booster_dmg_mult'], hp_mult)
        )
        
        await normalize_chances()
        await log_admin(message.from_user.id, f"Создан БУСТЕР: {data['name']}")
        
        await message.answer_photo(new_photo_id, caption=f"✅ <b>Бустер {data['name']} создан!</b>\nШансы нормализованы до 100%.", reply_markup=get_main_keyboard(True))
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
        await message.answer("⏳ Генерирую рамку редкости для карты, подождите...")
        
        new_photo_id = await create_bordered_image(bot, data['photo'], data['rarity'])
        await execute_db(
            "INSERT INTO cards (name, rarity, class_type, damage, hp, drop_chance, photo_id, booster_dmg_mult, booster_hp_mult) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data['name'], data['rarity'], data['class_type'], data['damage'], hp, data['drop_chance'], new_photo_id, 1.0, 1.0)
        )
        
        await normalize_chances()
        await log_admin(message.from_user.id, f"Создана карта: {data['name']}")
        
        await message.answer_photo(new_photo_id, caption=f"✅ <b>Карта {data['name']} создана!</b>\nШансы нормализованы до 100%.", reply_markup=get_main_keyboard(True))
        await state.clear()
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}"); await state.clear()

# --- РЕДАКТИРОВАНИЕ КАРТЫ ---
@dp.callback_query(F.data == "adm_card_edit")
async def adm_card_edit_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи ID карты для редактирования:")
    await state.set_state(EditCard.card_id)
    await callback.answer()

@dp.message(EditCard.card_id)
async def adm_card_edit_select(message: types.Message, state: FSMContext):
    try:
        c_id = int(message.text)
        card = await fetch_one("SELECT * FROM cards WHERE id = ?", (c_id,))
        if not card: return await message.answer("❌ Карта не найдена.")
        
        await state.update_data(edit_id=c_id)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Имя", callback_data="edit_val_name"), InlineKeyboardButton(text="✏️ Шанс", callback_data="edit_val_chance")],
            [InlineKeyboardButton(text="✏️ Урон (если не бустер)", callback_data="edit_val_dmg"), InlineKeyboardButton(text="✏️ ХП", callback_data="edit_val_hp")],
            [InlineKeyboardButton(text="✏️ Буст Урон", callback_data="edit_val_bdmg"), InlineKeyboardButton(text="✏️ Буст ХП", callback_data="edit_val_bhp")]
        ])
        await message.answer(f"Редактирование <b>{card['name']}</b> (ID: {c_id})\nЧто меняем?", reply_markup=kb)
        await state.set_state(EditCard.waiting_new_value)
    except: await message.answer("❌ Число!")

@dp.callback_query(EditCard.waiting_new_value, F.data.startswith("edit_val_"))
async def adm_card_edit_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split("_")[2]
    await state.update_data(edit_field=field)
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
        "bdmg": ("booster_dmg_mult", float), "bhp": ("booster_hp_mult", float)
    }
    
    col, cast_fn = col_map[field]
    try:
        val = cast_fn(val)
        await execute_db(f"UPDATE cards SET {col} = ? WHERE id = ?", (val, c_id))
        if field == "chance": await normalize_chances() # Нормализуем если меняли шанс
        
        await log_admin(message.from_user.id, f"Edited card ID {c_id}, {col} = {val}")
        await message.answer(f"✅ Изменено!")
        await state.clear()
    except: await message.answer("❌ Неверный формат значения.")

# --- УДАЛЕНИЕ КАРТЫ (С КАСКАДОМ) ---
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
        # Каскадное удаление
        await execute_db("DELETE FROM inventory WHERE card_id = ?", (c_id,))
        for slot in ['equip1', 'equip2', 'equip3']:
            await execute_db(f"UPDATE users SET {slot} = 0 WHERE {slot} = ?", (c_id,))
            
        await normalize_chances() # Пересчет шансов
        await log_admin(message.from_user.id, f"DELETED card ID {c_id}")
        await message.answer(f"✅ Карта {c_id} полностью удалена, шансы пересчитаны.")
    except: await message.answer("❌ Число.")
    await state.clear()

# --- РАЗДЕЛ: ИГРОКИ ---
@dp.callback_query(F.data == "adm_users")
async def cq_adm_users(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Выдать карту", callback_data="adm_usr_givecard")],
        [InlineKeyboardButton(text="🏆 Выдать кубки", callback_data="adm_usr_cups")],
        [InlineKeyboardButton(text="🔨 Бан / Разбан", callback_data="adm_usr_ban")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("👤 <b>Управление Игроками</b>", reply_markup=kb)

@dp.callback_query(F.data == "adm_usr_givecard")
async def adm_usr_give(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введите ID игрока:")
    await state.set_state(GiveCard.user_id)
    await callback.answer()

@dp.message(GiveCard.user_id)
async def adm_usr_give_user(message: types.Message, state: FSMContext):
    await state.update_data(user_id=int(message.text))
    await message.answer("Введите ID карты для выдачи:")
    await state.set_state(GiveCard.card_id)

@dp.message(GiveCard.card_id)
async def adm_usr_give_finish(message: types.Message, state: FSMContext):
    try:
        card_id = int(message.text)
        data = await state.get_data()
        user_id = data['user_id']
        
        inv_item = await fetch_one("SELECT id FROM inventory WHERE user_id = ? AND card_id = ?", (user_id, card_id))
        if inv_item:
            await execute_db("UPDATE inventory SET count = count + 1 WHERE id = ?", (inv_item['id'],))
        else:
            await execute_db("INSERT INTO inventory (user_id, card_id) VALUES (?, ?)", (user_id, card_id))
            
        await log_admin(message.from_user.id, f"GAVE card ID {card_id} to User {user_id}")
        await message.answer(f"✅ Карта выдана игроку {user_id}!")
    except Exception as e: await message.answer(f"❌ Ошибка: {e}")
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
    except: pass
    await state.clear()

# --- РАЗДЕЛ: ИВЕНТЫ ---
@dp.callback_query(F.data == "adm_events")
async def cq_adm_events(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍀 Ивент Удачи", callback_data="ev_luck"), InlineKeyboardButton(text="⏳ Ивент КД", callback_data="ev_cd")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="adm_main")]
    ])
    await callback.message.edit_text("🎉 <b>Запуск Ивентов</b>\nПри запуске бот сделает массовую рассылку всем игрокам.", reply_markup=kb)

@dp.callback_query(F.data == "ev_luck")
async def ev_luck_start(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Введи множитель (например 2.0 для х2):")
    await state.set_state(EventLuck.mult)
    await callback.answer()

@dp.message(EventLuck.mult)
async def ev_luck_mult(message: types.Message, state: FSMContext):
    await state.update_data(mult=float(message.text))
    await message.answer("На сколько минут запускаем?")
    await state.set_state(EventLuck.mins)

@dp.message(EventLuck.mins)
async def ev_luck_finish(message: types.Message, state: FSMContext):
    try:
        data = await state.get_data()
        mins = int(message.text)
        end = time.time() + (mins * 60)
        
        await execute_db("UPDATE server_settings SET luck_mult = ?, luck_end = ? WHERE id = 1", (data['mult'], end))
        await log_admin(message.from_user.id, f"LUCK EVENT x{data['mult']} for {mins}m")
        await message.answer("✅ Запущено. Начинаю рассылку...")
        await state.clear()
        
        # Запуск асинхронной рассылки
        asyncio.create_task(broadcast_message(f"🍀 <b>ГЛОБАЛЬНЫЙ ИВЕНТ УДАЧИ!</b>\nШанс на редкие карты увеличен в {data['mult']} раз на {mins} минут!\n\nБегом крутить гачу: /getcard"))
    except: await message.answer("Ошибка.")

# --- БЭКАПЫ БД ---
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
    await bot.download_file(file.file_path, DB_NAME)
    
    await check_and_update_schema()
    await normalize_chances()
    await log_admin(message.from_user.id, "DB Upload and Migration")
    await message.answer("✅ <b>БД успешно загружена, структуры и шансы обновлены!</b>")

# ========================================================================
# ЗАПУСК БОТА
# ========================================================================
async def main():
    await check_and_update_schema()
    await normalize_chances() # Перестраховка при старте
    
    commands = [
        BotCommand(command="start", description="Главное меню / Старт"),
        BotCommand(command="getcard", description="Выбить карту (Гача)"),
        BotCommand(command="inventory", description="Инвентарь карт"),
        BotCommand(command="equip", description="Экипировка колоды"),
        BotCommand(command="profile", description="Профиль и статы"),
        BotCommand(command="index", description="Индекс всех карт"),
        BotCommand(command="top", description="Лидерборд"),
        BotCommand(command="help", description="Помощь")
    ]
    await bot.set_my_commands(commands)
    
    logging.info("🤖 Ультимативный Карточный бот запущен!")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен.")
