import asyncio, random, sqlite3, time, os, logging, uuid, json
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import BotCommand, KeyboardButton, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery, ReplyKeyboardRemove
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

# Настройка логирования
logging.basicConfig(level=logging.INFO)

# --- НАСТРОЙКИ ---
API_TOKEN = '8731782761:AAFUWukkkqY02Ft4qTf3T8kYpFbs7Bwunyc'
OWNER_ID = 7916002515 
REFERRAL_REWARD = 1000 

# Название основной валюты
CURRENCY_NAME = "PLCOINS"

# Премиум валюта GPM
PREMIUM_RATE = 5000  # 1 GPM = 5000 PLCOINS

# Доступ к чекам
CHECK_ACCESS_PRICE = 1_000_000

# Курс звезд
STARS_TO_COINS = 1000  # 1 звезда = 1000 PLCOINS

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
games = {}
users_data = {}  # Хранилище временных данных (для рассылки)
ROLE_NAMES = {0: "Игрок", 1: "Модератор", 2: "Администратор", 3: "Владелец"}

# --- БАЗА ДАННЫХ ---
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users 
                      (uid INTEGER PRIMARY KEY, 
                       username TEXT, 
                       balance INTEGER DEFAULT 1000,
                       premium_balance INTEGER DEFAULT 0,
                       stars_received INTEGER DEFAULT 0,
                       check_access INTEGER DEFAULT 0,
                       last_bonus INTEGER DEFAULT 0, 
                       last_lottery INTEGER DEFAULT 0,
                       role INTEGER DEFAULT 0,
                       referrer_id INTEGER DEFAULT NULL, 
                       refs_count INTEGER DEFAULT 0,
                       banned INTEGER DEFAULT 0, 
                       ban_reason TEXT DEFAULT NULL,
                       games_played INTEGER DEFAULT 0,
                       wins INTEGER DEFAULT 0,
                       total_bet INTEGER DEFAULT 0,
                       total_win INTEGER DEFAULT 0)''')
        
        conn.execute('''CREATE TABLE IF NOT EXISTS checks 
                      (check_id TEXT PRIMARY KEY,
                       creator_id INTEGER,
                       amount INTEGER,
                       is_premium INTEGER DEFAULT 0,
                       created INTEGER,
                       claimed_by INTEGER DEFAULT NULL,
                       claimed_time INTEGER DEFAULT NULL)''')
        
        conn.execute('''CREATE TABLE IF NOT EXISTS star_purchases 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       amount_coins INTEGER,
                       amount_stars INTEGER,
                       date INTEGER,
                       telegram_payment_id TEXT)''')
        
        # Таблица для промокодов
        conn.execute('''CREATE TABLE IF NOT EXISTS promocodes 
                      (code TEXT PRIMARY KEY,
                       creator_id INTEGER,
                       amount INTEGER,
                       max_uses INTEGER,
                       used_count INTEGER DEFAULT 0,
                       created INTEGER,
                       is_active INTEGER DEFAULT 1)''')
        
        # Таблица для чеков-ссылок (одноразовые)
        conn.execute('''CREATE TABLE IF NOT EXISTS check_links 
                      (id TEXT PRIMARY KEY,
                       creator_id INTEGER,
                       amount INTEGER,
                       max_uses INTEGER DEFAULT 1,
                       used_count INTEGER DEFAULT 0,
                       created INTEGER,
                       is_active INTEGER DEFAULT 1)''')
        
        # Таблица для отслеживания активаций чеков (кто и когда активировал)
        conn.execute('''CREATE TABLE IF NOT EXISTS check_claims 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       check_id TEXT,
                       user_id INTEGER,
                       date INTEGER)''')
        
        # Таблица для звезд бота
        conn.execute('''CREATE TABLE IF NOT EXISTS bot_stars 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       date INTEGER,
                       user_id INTEGER,
                       amount_stars INTEGER,
                       amount_coins INTEGER,
                       description TEXT)''')
        
        conn.commit()
        
        owner = conn.execute("SELECT * FROM users WHERE uid = ?", (OWNER_ID,)).fetchone()
        if not owner:
            conn.execute("INSERT INTO users (uid, username, balance, premium_balance, role) VALUES (?, ?, ?, ?, ?)",
                        (OWNER_ID, "Owner", 10000000, 10000, 3))
            conn.commit()
            print(f"✅ Владелец {OWNER_ID} добавлен")

def get_user(uid):
    with get_db() as conn:
        res = conn.execute("SELECT * FROM users WHERE uid = ?", (uid,)).fetchone()
    
    if res:
        user_dict = dict(res)
        if 'banned' not in user_dict:
            user_dict['banned'] = 0
        if 'ban_reason' not in user_dict:
            user_dict['ban_reason'] = None
        if 'premium_balance' not in user_dict:
            user_dict['premium_balance'] = 0
        if 'stars_received' not in user_dict:
            user_dict['stars_received'] = 0
        if 'check_access' not in user_dict:
            user_dict['check_access'] = 0
        if 'games_played' not in user_dict:
            user_dict['games_played'] = 0
        if 'wins' not in user_dict:
            user_dict['wins'] = 0
        if 'total_bet' not in user_dict:
            user_dict['total_bet'] = 0
        if 'total_win' not in user_dict:
            user_dict['total_win'] = 0
        return user_dict
    return None

def create_user(uid, username, referrer_id=None):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (uid, username) VALUES (?, ?)", (uid, username))
        conn.commit()
        if referrer_id:
            conn.execute("UPDATE users SET balance = balance + ?, refs_count = refs_count + 1 WHERE uid = ?", 
                        (REFERRAL_REWARD, referrer_id))
            conn.commit()

def set_balance(uid, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = ? WHERE uid = ?", (amount, uid))
        conn.commit()

def add_balance(uid, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE uid = ?", (amount, uid))
        conn.commit()

def take_balance(uid, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance - ? WHERE uid = ?", (amount, uid))
        conn.commit()

def get_balance(uid):
    u = get_user(uid)
    return u['balance'] if u else 0

def add_premium(uid, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET premium_balance = premium_balance + ? WHERE uid = ?", (amount, uid))
        conn.commit()

def take_premium(uid, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET premium_balance = premium_balance - ? WHERE uid = ?", (amount, uid))
        conn.commit()

def get_premium(uid):
    u = get_user(uid)
    return u['premium_balance'] if u else 0

def add_total_bet(uid, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET total_bet = total_bet + ? WHERE uid = ?", (amount, uid))
        conn.commit()

def add_total_win(uid, amount):
    with get_db() as conn:
        conn.execute("UPDATE users SET total_win = total_win + ? WHERE uid = ?", (amount, uid))
        conn.commit()

def has_check_access(uid):
    u = get_user(uid)
    return u and (u['check_access'] == 1 or u['role'] >= 2)

def grant_check_access(uid):
    with get_db() as conn:
        conn.execute("UPDATE users SET check_access = 1 WHERE uid = ?", (uid,))
        conn.commit()

def get_role(uid):
    if uid == OWNER_ID:
        return 3
    u = get_user(uid)
    return u['role'] if u else 0

def is_banned(uid):
    u = get_user(uid)
    return u and u['banned'] == 1

def ban_user(uid, reason=None):
    with get_db() as conn:
        conn.execute("UPDATE users SET banned = 1, ban_reason = ? WHERE uid = ?", (reason, uid))
        conn.commit()

def unban_user(uid):
    with get_db() as conn:
        conn.execute("UPDATE users SET banned = 0, ban_reason = NULL WHERE uid = ?", (uid,))
        conn.commit()

# --- МИДЛВАРЬ ДЛЯ ПРОВЕРКИ БАНА ---
@dp.message.outer_middleware()
async def ban_check_middleware(handler, event: types.Message, data):
    uid = event.from_user.id
    if uid == OWNER_ID:
        return await handler(event, data)
    if is_banned(uid):
        u = get_user(uid)
        reason = u['ban_reason'] if u and u['ban_reason'] else "Не указана"
        await event.answer(f"⛔ **ВЫ ЗАБЛОКИРОВАНЫ**\n\nПричина: {reason}", parse_mode="Markdown")
        return
    return await handler(event, data)

@dp.callback_query.outer_middleware()
async def ban_check_callback_middleware(handler, event: types.CallbackQuery, data):
    uid = event.from_user.id
    if uid == OWNER_ID:
        return await handler(event, data)
    if is_banned(uid):
        await event.answer("⛔ Вы заблокированы!", show_alert=True)
        return
    return await handler(event, data)

# --- ПАРСЕР СТАВОК (с системой мер) ---
def parse_bet(uid, text, allow_premium=False):
    parts = text.split()
    if len(parts) < 2: 
        return None, False
    
    bal = get_balance(uid)
    premium_bal = get_premium(uid)
    arg = parts[1].lower()
    
    # Проверка на премиум ставку (pm)
    is_premium = False
    if arg.endswith("pm") or arg.endswith("пм"):
        is_premium = True
        arg = arg[:-2]
    
    if arg in ["все", "всё"]:
        if is_premium and allow_premium:
            return premium_bal, True
        return bal, False
    
    # Система мер: к, кк, ккк, кккк
    multiplier = 1
    if arg.endswith("кккк") or arg.endswith("kkkk"):
        multiplier = 1_000_000_000_000  # 1 трлн
        val = arg.replace("кккк", "").replace("kkkk", "")
    elif arg.endswith("ккк") or arg.endswith("kkk"):
        multiplier = 1_000_000_000  # 1 млрд
        val = arg.replace("ккк", "").replace("kkk", "")
    elif arg.endswith("кк") or arg.endswith("kk"):
        multiplier = 1_000_000  # 1 млн
        val = arg.replace("кк", "").replace("kk", "")
    elif arg.endswith("к") or arg.endswith("k"):
        multiplier = 1_000  # 1 тыс
        val = arg.replace("к", "").replace("k", "")
    else:
        val = arg

    try:
        if val == "": 
            val = "1"
        amount = int(float(val.replace(",", ".")) * multiplier)
        if is_premium and allow_premium:
            return amount, True
        return amount, False
    except:
        return None, False

# ============================================
# КОМАНДА GIVE (ВЫДАЧА ПО РЕПЛЕЮ)
# ============================================
@dp.message(Command("give"))
async def cmd_give(m: types.Message):
    """Выдать монеты пользователю (по реплею или ID)"""
    
    # Проверка прав (только админ)
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    # Если это ответ на сообщение
    if m.reply_to_message:
        target_id = m.reply_to_message.from_user.id
        parts = m.text.split()
        
        if len(parts) < 2:
            return await m.answer("📝 Формат при ответе: /give [сумма]")
        
        try:
            amount = int(parts[1])
        except:
            return await m.answer("❌ Неверная сумма!")
        
        if amount <= 0:
            return await m.answer("❌ Сумма должна быть больше 0!")
        
        target_user = get_user(target_id)
        if not target_user:
            return await m.answer("❌ Пользователь не найден!")
        
        add_balance(target_id, amount)
        await m.answer(f"✅ Выдано {amount} {CURRENCY_NAME} пользователю {target_id}")
        
        try:
            await bot.send_message(target_id, f"🎁 Администратор выдал вам {amount} {CURRENCY_NAME}!")
        except:
            pass
        
        return
    
    # Если не реплей, используем старую логику с ID
    parts = m.text.split()
    if len(parts) < 3:
        return await m.answer(f"📝 Формат: /give ID сумма\nИли ответь на сообщение: /give сумма")
    
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except:
        return await m.answer("❌ Неверный ID или сумма")
    
    if amount <= 0:
        return await m.answer("❌ Сумма должна быть больше 0!")
    
    target_user = get_user(target_id)
    if not target_user:
        return await m.answer("❌ Пользователь не найден!")
    
    add_balance(target_id, amount)
    await m.answer(f"✅ Выдано {amount} {CURRENCY_NAME} пользователю {target_id}")
    
    try:
        await bot.send_message(target_id, f"🎁 Администратор выдал вам {amount} {CURRENCY_NAME}!")
    except:
        pass

# ============================================
# ОБМЕННИК ВАЛЮТ
# ============================================
@dp.message(Command("exchange"))
async def cmd_exchange(m: types.Message):
    """Обмен валют: PLCOINS ↔ GPM ↔ Звезды"""
    uid = m.from_user.id
    user = get_user(uid)
    
    if not user:
        return await m.answer("❌ Сначала /start")
    
    text = (
        f"💱 **ОБМЕННИК ВАЛЮТ**\n\n"
        f"**Твой баланс:**\n"
        f"💰 PLCOINS: {user['balance']:,}\n"
        f"💎 GPM: {user['premium_balance']}\n"
        f"⭐ Звезд: {user['stars_received']}\n\n"
        f"**Доступные операции:**\n"
        f"• Купить GPM за PLCOINS: `/buy_gpm [количество]`\n"
        f"• Продать GPM за PLCOINS: `/sell_gpm [количество]`\n"
        f"• Купить PLCOINS за звёзды: `/buy_coins [сумма]`\n\n"
        f"**Курс:**\n"
        f"1 GPM = {PREMIUM_RATE} PLCOINS\n"
        f"1 ⭐ = {STARS_TO_COINS} PLCOINS"
    )
    
    kb = InlineKeyboardBuilder()
    kb.row(
        InlineKeyboardButton(text="💎 Купить GPM", callback_data="exchange_buy_gpm"),
        InlineKeyboardButton(text="💎 Продать GPM", callback_data="exchange_sell_gpm")
    )
    kb.row(
        InlineKeyboardButton(text="⭐ Купить PLCOINS", callback_data="exchange_buy_coins")
    )
    
    await m.answer(text, parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("exchange_"))
async def exchange_callback(c: types.CallbackQuery):
    """Обработка кнопок обменника"""
    action = c.data.split("_")[1:]
    
    if action[0] == "buy" and action[1] == "gpm":
        await c.message.answer(
            f"📝 Введите количество GPM для покупки:\n"
            f"Например: `/buy_gpm 10`"
        )
    
    elif action[0] == "sell" and action[1] == "gpm":
        await c.message.answer(
            f"📝 Введите количество GPM для продажи:\n"
            f"Например: `/sell_gpm 10`"
        )
    
    elif action[0] == "buy" and action[1] == "coins":
        await c.message.answer(
            f"📝 Введите сумму PLCOINS для покупки за звёзды:\n"
            f"Например: `/buy_coins 10000`\n"
            f"1 ⭐ = {STARS_TO_COINS} PLCOINS"
        )
    
    await c.answer()

@dp.message(Command("buy_gpm"))
async def cmd_buy_gpm(m: types.Message):
    """Купить GPM за PLCOINS"""
    uid = m.from_user.id
    parts = m.text.split()
    
    if len(parts) < 2:
        return await m.answer(f"📝 Формат: `/buy_gpm [количество]`\nПример: `/buy_gpm 10`")
    
    try:
        amount = int(parts[1])
    except:
        return await m.answer("❌ Неверное количество!")
    
    if amount <= 0:
        return await m.answer("❌ Количество должно быть больше 0!")
    
    price = amount * PREMIUM_RATE
    user = get_user(uid)
    
    if user['balance'] < price:
        return await m.answer(f"❌ Недостаточно PLCOINS! Нужно: {price:,}")
    
    take_balance(uid, price)
    add_premium(uid, amount)
    
    await m.answer(
        f"✅ Куплено {amount} GPM за {price:,} PLCOINS!\n\n"
        f"💰 PLCOINS: {get_balance(uid):,}\n"
        f"💎 GPM: {get_premium(uid)}"
    )

@dp.message(Command("sell_gpm"))
async def cmd_sell_gpm(m: types.Message):
    """Продать GPM за PLCOINS"""
    uid = m.from_user.id
    parts = m.text.split()
    
    if len(parts) < 2:
        return await m.answer(f"📝 Формат: `/sell_gpm [количество]`\nПример: `/sell_gpm 10`")
    
    try:
        amount = int(parts[1])
    except:
        return await m.answer("❌ Неверное количество!")
    
    if amount <= 0:
        return await m.answer("❌ Количество должно быть больше 0!")
    
    user = get_user(uid)
    
    if user['premium_balance'] < amount:
        return await m.answer(f"❌ Недостаточно GPM! Баланс: {user['premium_balance']}")
    
    profit = amount * PREMIUM_RATE
    take_premium(uid, amount)
    add_balance(uid, profit)
    
    await m.answer(
        f"✅ Продано {amount} GPM за {profit:,} PLCOINS!\n\n"
        f"💰 PLCOINS: {get_balance(uid):,}\n"
        f"💎 GPM: {get_premium(uid)}"
    )

@dp.message(Command("buy_coins"))
async def cmd_buy_coins(m: types.Message):
    """Купить PLCOINS за звёзды"""
    uid = m.from_user.id
    parts = m.text.split()
    
    if len(parts) < 2:
        return await m.answer(f"📝 Формат: `/buy_coins [сумма]`\nПример: `/buy_coins 10000`")
    
    try:
        amount = int(parts[1])
    except:
        return await m.answer("❌ Неверная сумма!")
    
    if amount <= 0:
        return await m.answer("❌ Сумма должна быть больше 0!")
    
    # Проверяем, что сумма кратна курсу
    if amount % STARS_TO_COINS != 0:
        return await m.answer(f"❌ Сумма должна быть кратна {STARS_TO_COINS} PLCOINS!")
    
    stars_needed = amount // STARS_TO_COINS
    user = get_user(uid)
    
    if user['stars_received'] < stars_needed:
        return await m.answer(f"❌ Недостаточно звёзд! Нужно: {stars_needed}")
    
    # Списываем звёзды
    with get_db() as conn:
        conn.execute("UPDATE users SET stars_received = stars_received - ? WHERE uid = ?", (stars_needed, uid))
        conn.commit()
    
    add_balance(uid, amount)
    
    await m.answer(
        f"✅ Куплено {amount:,} PLCOINS за {stars_needed} ⭐!\n\n"
        f"💰 PLCOINS: {get_balance(uid):,}\n"
        f"⭐ Звёзд: {get_user(uid)['stars_received']}"
    )

# ============================================
# ОСТАЛЬНЫЕ ИГРЫ И КОМАНДЫ
# ============================================

# (Здесь весь остальной код бота с играми, профилем, балансом и т.д.)

# ============================================
# MAIN
# ============================================
async def main():
    init_db()
    
    await bot.set_my_commands([
        BotCommand(command="start", description="🏠 Старт"),
        BotCommand(command="profile", description="👤 Профиль"),
        BotCommand(command="balance", description="💰 Баланс"),
        BotCommand(command="premium", description="💎 GPM"),
        BotCommand(command="exchange", description="💱 Обменник"),
        BotCommand(command="buy_stars", description="⭐ Купить PLCOINS"),
        BotCommand(command="lottery", description="🎲 Лотерея"),
        BotCommand(command="top", description="🏆 Топ"),
        BotCommand(command="send", description="💰 Перевести PLCOINS"),
        BotCommand(command="help", description="❓ Помощь"),
        
        # ИГРЫ
        BotCommand(command="slots", description="🎰 Слоты"),
        BotCommand(command="mines", description="💣 Мины"),
        BotCommand(command="roulette", description="🎯 Рулетка"),
        BotCommand(command="coin", description="🪙 Монетка"),
        BotCommand(command="dice", description="🎲 Кости"),
        BotCommand(command="tower", description="🗼 Башня"),
        BotCommand(command="blackjack", description="🃏 Очко"),
        BotCommand(command="cases", description="🎁 Кейсы"),
        BotCommand(command="crash", description="📈 Краш"),
        BotCommand(command="football", description="⚽ Футбол"),
        BotCommand(command="basketball", description="🏀 Баскетбол"),
        BotCommand(command="bowling", description="🎳 Боулинг"),
        BotCommand(command="darts", description="🎯 Дартс"),
        
        # Админские команды
        BotCommand(command="give", description="💰 Выдать PLCOINS (админ)"),
        BotCommand(command="give_premium", description="💎 Выдать GPM (админ)"),
        BotCommand(command="give_check_access", description="🎫 Выдать доступ к чекам (админ)"),
        BotCommand(command="users", description="👥 Список игроков (админ)"),
        BotCommand(command="banlist", description="⛔ Бан-лист (админ)"),
        BotCommand(command="stats", description="📊 Статистика (админ)"),
        BotCommand(command="broadcast", description="📢 Рассылка (админ)"),
        BotCommand(command="create_promo", description="🏷 Создать промокод (админ)"),
        BotCommand(command="create_check_link", description="🔗 Создать чек-ссылку (админ)"),
        BotCommand(command="bot_stars", description="⭐ Статистика звёзд (владелец)"),
    ])
    
    print("🚀 Бот запущен!")
    print(f"💰 {CURRENCY_NAME} | 💎 GPM: 1={PREMIUM_RATE} {CURRENCY_NAME}")
    print(f"🎫 Доступ к чекам: {CHECK_ACCESS_PRICE} {CURRENCY_NAME}")
    print(f"⭐ 1 звезда = {STARS_TO_COINS} {CURRENCY_NAME}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())