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

# Рекламные каналы и боты
REQUIRED_CHANNELS = [
    {"name": "Канал с играми", "username": "minesplaying", "url": "https://t.me/minesplaying"}
]
REQUIRED_BOTS = [
    {"name": "Бот с бонусами", "username": "BabkaShura_bot", "url": "https://t.me/BabkaShura_bot"}
]

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
        
        # Таблица для отслеживания рекламных подписок
        conn.execute('''CREATE TABLE IF NOT EXISTS subscriptions 
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id INTEGER,
                       channel_username TEXT,
                       subscribed INTEGER DEFAULT 0,
                       checked_date INTEGER)''')
        
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

# ============================================
# ПРОВЕРКА РЕКЛАМНЫХ ПОДПИСОК (БЕЗ ПРОВЕРКИ КАНАЛА)
# ============================================
async def check_subscriptions(user_id: int) -> bool:
    """Проверяет только запуск бота (разные базы)"""
    try:
        # Проверяем только наличие пользователя в базе
        user = get_user(user_id)
        return user is not None
    except Exception as e:
        print(f"Ошибка проверки подписок: {e}")
        return False

def get_subscription_keyboard():
    """Создает клавиатуру для рекламных подписок"""
    kb = InlineKeyboardBuilder()
    
    # Добавляем кнопки для каналов
    for channel in REQUIRED_CHANNELS:
        kb.row(InlineKeyboardButton(
            text=f"📢 {channel['name']}",
            url=channel["url"]
        ))
    
    # Добавляем кнопки для ботов
    for bot_item in REQUIRED_BOTS:
        kb.row(InlineKeyboardButton(
            text=f"🤖 {bot_item['name']}",
            url=bot_item["url"]
        ))
    
    # Кнопка проверки
    kb.row(InlineKeyboardButton(
        text="✅ Я выполнил условия",
        callback_data="check_subs"
    ))
    
    return kb.as_markup()

# ============================================
# МИДЛВАРЬ ДЛЯ ПРОВЕРКИ РЕКЛАМЫ
# ============================================
@dp.message.outer_middleware()
async def ad_check_middleware(handler, event: types.Message, data):
    uid = event.from_user.id
    
    # Пропускаем владельца
    if uid == OWNER_ID:
        return await handler(event, data)
    
    # Пропускаем команду /start (чтобы можно было зарегистрироваться)
    if event.text and event.text.startswith('/start'):
        return await handler(event, data)
    
    # Пропускаем callback-запросы
    if hasattr(event, 'callback_query') and event.callback_query:
        return await handler(event, data)
    
    # Проверяем подписки
    if not await check_subscriptions(uid):
        await event.answer(
            "⛔ **Доступ ограничен**\n\n"
            "Для использования бота необходимо:\n"
            "1️⃣ Подписаться на канал @minesplaying\n"
            "2️⃣ Запустить бота @BabkaShura_bot\n\n"
            "После выполнения нажми кнопку проверки.",
            reply_markup=get_subscription_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    return await handler(event, data)

@dp.callback_query(F.data == "check_subs")
async def check_subs_callback(c: types.CallbackQuery):
    """Проверка подписок по кнопке"""
    uid = c.from_user.id
    
    if await check_subscriptions(uid):
        await c.message.edit_text(
            "✅ **Подписка подтверждена!**\n"
            "Теперь вы можете пользоваться ботом.\n"
            "Отправьте /start для начала."
        )
    else:
        await c.message.edit_text(
            "❌ **Подписка не найдена**\n\n"
            "Убедитесь, что вы запустили бота @BabkaShura_bot и написали ему /start.\n\n"
            "После выполнения нажмите кнопку проверки.",
            reply_markup=get_subscription_keyboard()
        )
    
    await c.answer()

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
# КОМАНДА GIVE
# ============================================
@dp.message(Command("give"))
async def cmd_give(m: types.Message):
    """Выдать монеты пользователю (только для админов)"""
    
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    parts = m.text.split()
    
    if len(parts) < 3:
        return await m.answer(
            "📝 **Формат команды /give:**\n"
            "• `/give ID сумма` — выдать по ID\n"
            "• Ответ на сообщение: `/give сумма`"
        )
    
    if m.reply_to_message:
        target_id = m.reply_to_message.from_user.id
        try:
            amount = int(parts[1])
        except:
            return await m.answer("❌ Неверная сумма!")
    else:
        try:
            target_id = int(parts[1])
            amount = int(parts[2])
        except:
            return await m.answer("❌ Неверный ID или сумма!")
    
    if amount <= 0:
        return await m.answer("❌ Сумма должна быть больше 0!")
    
    target_user = get_user(target_id)
    if not target_user:
        return await m.answer("❌ Пользователь не найден!")
    
    add_balance(target_id, amount)
    
    await m.answer(
        f"✅ **Монеты выданы!**\n\n"
        f"👤 Пользователь: `{target_id}`\n"
        f"💰 Сумма: {amount} {CURRENCY_NAME}\n"
        f"💳 Новый баланс: {get_balance(target_id)} {CURRENCY_NAME}"
    )
    
    try:
        await bot.send_message(
            target_id,
            f"🎁 Администратор выдал вам {amount} {CURRENCY_NAME}!\n"
            f"💰 Новый баланс: {get_balance(target_id)} {CURRENCY_NAME}"
        )
    except:
        pass

# ============================================
# ОСНОВНЫЕ КОМАНДЫ
# ============================================
@dp.message(Command("start"))
async def start_handler(m: types.Message, command: CommandObject = None):
    uid = m.from_user.id
    username = m.from_user.first_name or "Игрок"
    ref_id = None
    check_activated = False
    
    # Проверка рекламных подписок (кроме владельца) - ТОЛЬКО ПРИ ПЕРВОМ ЗАПУСКЕ
    if uid != OWNER_ID:
        user = get_user(uid)
        if not user:
            # Если пользователя нет в базе, показываем рекламу
            await m.answer(
                "👋 **Добро пожаловать!**\n\n"
                "Для использования бота необходимо:\n"
                "1️⃣ Подписаться на канал @minesplaying\n"
                "2️⃣ Запустить бота @BabkaShura_bot\n\n"
                "После выполнения нажми кнопку проверки.",
                reply_markup=get_subscription_keyboard(),
                parse_mode="Markdown"
            )
            return
    
    if command and command.args:
        if command.args.startswith("check_"):
            check_id = command.args[6:]
            with get_db() as conn:
                check = conn.execute(
                    "SELECT * FROM check_links WHERE id = ? AND is_active = 1",
                    (check_id,)
                ).fetchone()
                
                if check:
                    already_claimed = conn.execute(
                        "SELECT * FROM check_claims WHERE check_id = ? AND user_id = ?",
                        (check_id, uid)
                    ).fetchone()
                    
                    if already_claimed:
                        await m.answer("❌ Вы уже активировали этот чек!")
                        return
                    
                    if check['used_count'] >= check['max_uses']:
                        conn.execute("UPDATE check_links SET is_active = 0 WHERE id = ?", (check_id,))
                        conn.commit()
                        await m.answer("❌ Чек-ссылка уже использована!")
                        return
                    
                    user = get_user(uid)
                    if not user:
                        create_user(uid, username, None)
                    
                    add_balance(uid, check['amount'])
                    
                    conn.execute(
                        "INSERT INTO check_claims (check_id, user_id, date) VALUES (?, ?, ?)",
                        (check_id, uid, int(time.time()))
                    )
                    
                    conn.execute(
                        "UPDATE check_links SET used_count = used_count + 1 WHERE id = ?",
                        (check_id,)
                    )
                    
                    if check['used_count'] + 1 >= check['max_uses']:
                        conn.execute("UPDATE check_links SET is_active = 0 WHERE id = ?", (check_id,))
                    
                    conn.commit()
                    await m.answer(f"✅ Чек-ссылка активирована! +{check['amount']} {CURRENCY_NAME}!")
                    check_activated = True
                else:
                    await m.answer("❌ Чек-ссылка не найдена или неактивна!")
        else:
            try:
                ref_id = int(command.args)
                if ref_id == uid:
                    ref_id = None
            except:
                ref_id = None
    
    if not check_activated:
        user = get_user(uid)
        
        if not user:
            create_user(uid, username, ref_id)
            add_balance(uid, 40000)
            await m.answer(f"🎁 Добро пожаловать! Вы получили 40 000 PLCOINS!")
        else:
            await m.answer(f"👋 С возвращением, {username}!")
        
        user = get_user(uid)
        await m.answer(
            f"💰 Баланс: {user['balance']} PLCOINS\n"
            f"💎 GPM: {user['premium_balance']}\n"
            f"👥 Рефералов: {user['refs_count']}",
            reply_markup=ReplyKeyboardRemove()
        )

@dp.message(Command("profile"))
async def profile(m: types.Message):
    uid = m.from_user.id
    user = get_user(uid)
    if not user:
        return await m.answer("❌ Сначала /start")
    
    check_status = "✅ Есть" if has_check_access(uid) else "❌ Нет"
    profit = user['total_win'] - user['total_bet']
    profit_sign = "+" if profit >= 0 else ""
    
    text = f"👤 Профиль\n\n"
    text += f"🆔 ID: {uid}\n"
    text += f"💰 {CURRENCY_NAME}: {user['balance']:,}\n"
    text += f"💎 GPM: {user['premium_balance']}\n"
    text += f"⭐ Звезд получено: {user['stars_received']}\n"
    text += f"👥 Рефералов: {user['refs_count']}\n"
    text += f"🎫 Доступ к чекам: {check_status}\n"
    text += f"🎮 Игр сыграно: {user['games_played']}\n"
    text += f"🏆 Побед: {user['wins']}\n\n"
    text += f"📊 СТАТИСТИКА:\n"
    text += f"   💸 Всего поставлено: {user['total_bet']:,} {CURRENCY_NAME}\n"
    text += f"   💰 Всего выиграно: {user['total_win']:,} {CURRENCY_NAME}\n"
    text += f"   📈 Чистый профит: {profit_sign}{profit:,} {CURRENCY_NAME}"
    
    await m.answer(text)

@dp.message(Command("balance"))
async def balance(m: types.Message):
    uid = m.from_user.id
    user = get_user(uid)
    if not user:
        return await m.answer("❌ Сначала /start")
    
    profit = user['total_win'] - user['total_bet']
    profit_sign = "+" if profit >= 0 else ""
    
    await m.answer(
        f"💰 **Баланс:** {user['balance']:,} {CURRENCY_NAME}\n"
        f"💎 **GPM:** {user['premium_balance']}\n\n"
        f"📊 **Статистика игр:**\n"
        f"💸 Всего поставлено: {user['total_bet']:,} {CURRENCY_NAME}\n"
        f"💰 Всего выиграно: {user['total_win']:,} {CURRENCY_NAME}\n"
        f"📈 Чистый профит: {profit_sign}{profit:,} {CURRENCY_NAME}"
    )

# --- ПОКУПКА ЗА ЗВЕЗДЫ ---
@dp.message(Command("buy_stars"))
async def cmd_buy_stars(m: types.Message):
    uid = m.from_user.id
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⭐ 10 звезд = 10,000 PLCOINS", callback_data="buy_stars_10"),
        InlineKeyboardButton(text="⭐ 50 звезд = 50,000 PLCOINS", callback_data="buy_stars_50")
    )
    builder.row(
        InlineKeyboardButton(text="⭐ 100 звезд = 100,000 PLCOINS", callback_data="buy_stars_100"),
        InlineKeyboardButton(text="⭐ 500 звезд = 500,000 PLCOINS", callback_data="buy_stars_500")
    )
    builder.row(
        InlineKeyboardButton(text="⭐ 1000 звезд = 1,000,000 PLCOINS", callback_data="buy_stars_1000")
    )
    await m.answer(
        f"⭐ **Покупка {CURRENCY_NAME} за звезды Telegram**\n\n"
        f"Курс: 1 звезда = {STARS_TO_COINS} {CURRENCY_NAME}\n"
        f"Ваш баланс: {get_balance(uid):,} {CURRENCY_NAME}\n\n"
        f"Выберите количество звезд для покупки:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("buy_stars_"))
async def process_stars_purchase(c: types.CallbackQuery):
    uid = c.from_user.id
    stars = int(c.data.split("_")[2])
    coins = stars * STARS_TO_COINS
    prices = [LabeledPrice(label=f"{stars} звезд", amount=stars)]
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"⭐ Оплатить {stars} звезд", pay=True))
    await c.message.answer_invoice(
        title=f"Покупка {CURRENCY_NAME}",
        description=f"Купить {coins:,} {CURRENCY_NAME} за {stars} звезд",
        payload=f"buy_coins_{coins}",
        provider_token="",
        currency="XTR",
        prices=prices,
        reply_markup=builder.as_markup()
    )
    await c.answer()

@dp.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_q: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_q.id, ok=True)

@dp.message(F.successful_payment)
async def successful_payment_handler(m: types.Message):
    uid = m.from_user.id
    payment = m.successful_payment
    coins = int(payment.invoice_payload.split("_")[2])
    stars = payment.total_amount
    
    add_balance(uid, coins)
    
    with get_db() as conn:
        conn.execute(
            "INSERT INTO star_purchases (user_id, amount_coins, amount_stars, date, telegram_payment_id) VALUES (?, ?, ?, ?, ?)",
            (uid, coins, stars, int(time.time()), payment.telegram_payment_charge_id)
        )
        conn.commit()
    
    with get_db() as conn:
        conn.execute(
            "INSERT INTO bot_stars (date, user_id, amount_stars, amount_coins, description) VALUES (?, ?, ?, ?, ?)",
            (int(time.time()), uid, stars, coins, f"Покупка {coins} {CURRENCY_NAME}")
        )
        conn.commit()
    
    await m.answer(
        f"✅ **Оплата прошла успешно!**\n\n"
        f"⭐ Потрачено звезд: {stars}\n"
        f"💰 Получено {CURRENCY_NAME}: {coins:,}\n"
        f"💳 Новый баланс: {get_balance(uid):,} {CURRENCY_NAME}",
        parse_mode="Markdown"
    )

# --- GPM (ПРЕМИУМ ВАЛЮТА) ---
@dp.message(Command("premium"))
async def cmd_premium(m: types.Message):
    uid = m.from_user.id
    text = (
        f"💎 **ВАЛЮТА GPM**\n\n"
        f"1 GPM = {PREMIUM_RATE:,} {CURRENCY_NAME}\n\n"
        f"**Ваш баланс:**\n"
        f"💰 {CURRENCY_NAME}: {get_balance(uid):,}\n"
        f"💎 GPM: {get_premium(uid)}\n\n"
        f"**Купить за {CURRENCY_NAME}:**\n"
        f"`/buy_premium [количество]`\n"
        f"Пример: `/buy_premium 100`"
    )
    await m.answer(text, parse_mode="Markdown")

@dp.message(Command("buy_premium"))
async def cmd_buy_premium(m: types.Message):
    uid = m.from_user.id
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer(f"📝 Формат: `/buy_premium [количество]`", parse_mode="Markdown")
    try:
        amount = int(parts[1])
        if amount <= 0:
            return await m.answer("❌ Количество должно быть больше 0!")
    except:
        return await m.answer("❌ Неверное количество!")
    price = amount * PREMIUM_RATE
    if get_balance(uid) < price:
        return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Нужно: {price:,}")
    take_balance(uid, price)
    add_premium(uid, amount)
    await m.answer(
        f"✅ **Покупка успешна!**\n\n"
        f"💰 Потрачено: {price:,} {CURRENCY_NAME}\n"
        f"💎 Получено: {amount} GPM\n"
        f"📊 Баланс GPM: {get_premium(uid)}",
        parse_mode="Markdown"
    )

# --- ЧЕКИ ---
@dp.message(Command("check"))
async def cmd_check(m: types.Message):
    uid = m.from_user.id
    role = get_role(uid)
    if role >= 2 or has_check_access(uid):
        status = "✅ У вас есть доступ к созданию чеков"
    else:
        status = f"❌ Нет доступа. Стоимость: {CHECK_ACCESS_PRICE:,} {CURRENCY_NAME} (единоразово)"
    text = (
        "🎫 **ЧЕКИ**\n\n"
        f"**Статус:** {status}\n\n"
        "**Как получить доступ:**\n"
        f"• `/buy_check_access` - купить доступ за {CHECK_ACCESS_PRICE:,} {CURRENCY_NAME}\n"
        "• Админам доступ бесплатно\n\n"
        "**Если доступ есть:**\n"
        "• `/create_check [сумма]` - создать чек на PLCOINS\n"
        "• `/create_premium_check [количество]` - создать чек на GPM\n"
        "• `/create_check_link [сумма]` - создать одноразовую чек-ссылку\n\n"
        "**Для всех:**\n"
        "• `/claim [код]` - активировать чек\n"
        "• Перейти по ссылке и нажать /start - активировать чек-ссылку"
    )
    await m.answer(text, parse_mode="Markdown")

@dp.message(Command("buy_check_access"))
async def cmd_buy_check_access(m: types.Message):
    uid = m.from_user.id
    if get_role(uid) >= 2:
        return await m.answer("✅ Администраторам доступ бесплатно!")
    if has_check_access(uid):
        return await m.answer("✅ Доступ уже есть!")
    if get_balance(uid) < CHECK_ACCESS_PRICE:
        return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Нужно: {CHECK_ACCESS_PRICE:,}")
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_check_access"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_check_access")
    )
    await m.answer(
        f"💰 **Покупка доступа к чекам**\n\n"
        f"Стоимость: {CHECK_ACCESS_PRICE:,} {CURRENCY_NAME}\n"
        f"Это единоразовый платеж, доступ навсегда!\n\n"
        f"Подтверждаете?",
        reply_markup=builder.as_markup()
    )

@dp.callback_query(F.data == "confirm_check_access")
async def confirm_check_access(c: types.CallbackQuery):
    uid = c.from_user.id
    if has_check_access(uid):
        await c.message.edit_text("✅ Доступ уже есть!")
        return await c.answer()
    if get_balance(uid) < CHECK_ACCESS_PRICE:
        await c.message.edit_text(f"❌ Недостаточно {CURRENCY_NAME}!")
        return await c.answer()
    take_balance(uid, CHECK_ACCESS_PRICE)
    grant_check_access(uid)
    await c.message.edit_text(
        f"✅ **Доступ куплен!**\n\n"
        f"💰 Списано: {CHECK_ACCESS_PRICE:,} {CURRENCY_NAME}\n"
        f"🎫 Теперь вы можете создавать чеки"
    )
    await c.answer()

@dp.callback_query(F.data == "cancel_check_access")
async def cancel_check_access(c: types.CallbackQuery):
    await c.message.edit_text("❌ Покупка отменена")
    await c.answer()

@dp.message(Command("create_check"))
async def cmd_create_check(m: types.Message):
    uid = m.from_user.id
    if get_role(uid) < 2 and not has_check_access(uid):
        return await m.answer(f"❌ Нет доступа! Купите: /buy_check_access")
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("📝 Формат: `/create_check [сумма]`", parse_mode="Markdown")
    try:
        amount = int(parts[1])
        if amount <= 0:
            return await m.answer("❌ Сумма должна быть больше 0!")
    except:
        return await m.answer("❌ Неверная сумма!")
    if get_balance(uid) < amount:
        return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Нужно: {amount:,}")
    take_balance(uid, amount)
    check_id = str(uuid.uuid4())[:8].upper()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO checks (check_id, creator_id, amount, is_premium, created) VALUES (?, ?, ?, ?, ?)",
            (check_id, uid, amount, 0, int(time.time()))
        )
        conn.commit()
    await m.answer(
        f"✅ **Чек создан!**\n\n"
        f"🎫 Код: `{check_id}`\n"
        f"💰 Сумма: {amount:,} {CURRENCY_NAME}\n\n"
        f"`/claim {check_id}`",
        parse_mode="Markdown"
    )

@dp.message(Command("create_premium_check"))
async def cmd_create_premium_check(m: types.Message):
    uid = m.from_user.id
    if get_role(uid) < 2 and not has_check_access(uid):
        return await m.answer(f"❌ Нет доступа! Купите: /buy_check_access")
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("📝 Формат: `/create_premium_check [количество]`", parse_mode="Markdown")
    try:
        amount = int(parts[1])
        if amount <= 0:
            return await m.answer("❌ Количество должно быть больше 0!")
    except:
        return await m.answer("❌ Неверное количество!")
    if get_premium(uid) < amount:
        return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
    take_premium(uid, amount)
    check_id = str(uuid.uuid4())[:8].upper()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO checks (check_id, creator_id, amount, is_premium, created) VALUES (?, ?, ?, ?, ?)",
            (check_id, uid, amount, 1, int(time.time()))
        )
        conn.commit()
    await m.answer(
        f"✅ **Премиум чек создан!**\n\n"
        f"🎫 Код: `{check_id}`\n"
        f"💎 Сумма: {amount} GPM\n\n"
        f"`/claim {check_id}`",
        parse_mode="Markdown"
    )

@dp.message(Command("claim"))
async def cmd_claim(m: types.Message):
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("📝 Формат: `/claim [код]`", parse_mode="Markdown")
    check_id = parts[1].upper()
    uid = m.from_user.id
    with get_db() as conn:
        check = conn.execute(
            "SELECT * FROM checks WHERE check_id = ? AND claimed_by IS NULL",
            (check_id,)
        ).fetchone()
        if not check:
            return await m.answer("❌ Чек не найден или уже активирован!")
        if check['is_premium']:
            add_premium(uid, check['amount'])
            reward_text = f"{check['amount']} GPM"
        else:
            add_balance(uid, check['amount'])
            reward_text = f"{check['amount']:,} {CURRENCY_NAME}"
        conn.execute(
            "UPDATE checks SET claimed_by = ?, claimed_time = ? WHERE check_id = ?",
            (uid, int(time.time()), check_id)
        )
        conn.commit()
    await m.answer(f"✅ **Чек активирован!**\n\n💰 Вы получили: {reward_text}", parse_mode="Markdown")

# --- ИГРЫ: Мины ---
SIZE = 5
MINES_MULTIPLIERS = {
    1: 1.2, 2: 1.4, 3: 1.6, 4: 1.9,
    5: 2.3, 6: 2.8, 7: 3.5, 8: 5.0
}

def get_mines_kb(uid, done=False):
    builder = InlineKeyboardBuilder()
    g = games[uid]
    for r in range(SIZE):
        for c in range(SIZE):
            text = ("💣" if g['board'][r][c] == -1 else "✅") if g['revealed'][r][c] else "🟦"
            builder.button(text=text, callback_data=f"mine_{r}_{c}")
    builder.adjust(SIZE)
    if not done and 'bet' in g:
        builder.row(InlineKeyboardButton(
            text=f"💰 Забрать {int(g['bet'] * g['multiplier'])} {CURRENCY_NAME}", 
            callback_data="mine_take"
        ))
    return builder.as_markup()

@dp.message(Command("mines"))
@dp.message(F.text.lower().startswith("мины"))
async def mines_game(m: types.Message):
    uid = m.from_user.id
    parts = m.text.lower().split()
    if len(parts) < 2:
        return await m.answer(
            f"💣 **МИНЫ**\n\nФормат: `Мины [ставка] [мин]`\nПример: `Мины 100 3`\nСокращения: `100к`, `5кк`, `1ккк`"
        )
    bet, is_premium = parse_bet(uid, m.text, allow_premium=True)
    if not bet or bet <= 0:
        return await m.answer("❌ Неверная ставка!")
    
    mines_count = 3
    if len(parts) >= 3:
        try:
            mines_count = int(parts[2])
            if mines_count < 1 or mines_count > 8:
                return await m.answer("❌ Мин должно быть 1-8")
        except:
            pass
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    base_mult = MINES_MULTIPLIERS.get(mines_count, 1.6)
    if is_premium:
        base_mult *= 1.5
    
    board = [[0]*SIZE for _ in range(SIZE)]
    positions = random.sample(range(SIZE*SIZE), mines_count)
    for pos in positions:
        r, c = divmod(pos, SIZE)
        board[r][c] = -1
    
    games[uid] = {
        'board': board,
        'revealed': [[False]*SIZE for _ in range(SIZE)],
        'bet': bet_value,
        'bet_premium': bet if is_premium else 0,
        'is_premium': is_premium,
        'multiplier': 1.0,
        'base_mult': base_mult,
        'mines_count': mines_count,
        'cells_opened': 0
    }
    await m.answer(
        f"💣 Мины | Мин: {mines_count} | База: x{base_mult}\n"
        f"💰 Ставка: {bet if is_premium else bet_value} {'GPM' if is_premium else CURRENCY_NAME}",
        reply_markup=get_mines_kb(uid)
    )

@dp.callback_query(F.data.startswith("mine_"))
async def mine_click(c: types.CallbackQuery):
    uid = c.from_user.id
    if uid not in games:
        return await c.answer("Игра не найдена")
    g = games[uid]
    
    if c.data == "mine_take":
        win = int(g['bet'] * g['multiplier'])
        if g.get('is_premium'):
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            await c.message.edit_text(f"💰 Забрал {win_premium} GPM!")
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            await c.message.edit_text(f"💰 Забрал {win} {CURRENCY_NAME}!")
        del games[uid]
        return await c.answer()
    
    _, r, col = c.data.split("_")
    r, col = int(r), int(col)
    
    if g['revealed'][r][col]:
        return await c.answer("Уже открыто")
    
    if g['board'][r][col] == -1:
        if g.get('is_premium'):
            await c.message.edit_text(f"💥 Бум! Проиграно: {g['bet_premium']} GPM")
        else:
            await c.message.edit_text(f"💥 Бум! Проиграно: {g['bet']} {CURRENCY_NAME}")
        del games[uid]
        return await c.answer()
    
    g['revealed'][r][col] = True
    g['cells_opened'] += 1
    g['multiplier'] = round(1.0 + (g['cells_opened'] * 0.1 * g['base_mult']), 2)
    
    total_safe = SIZE*SIZE - g['mines_count']
    if g['cells_opened'] >= total_safe:
        win = int(g['bet'] * g['multiplier'] * 1.5)
        if g.get('is_premium'):
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            await c.message.edit_text(f"🏆 ПОБЕДА! +{win_premium} GPM")
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            await c.message.edit_text(f"🏆 ПОБЕДА! +{win} {CURRENCY_NAME}")
        del games[uid]
        return await c.answer()
    
    await c.message.edit_text(
        f"✅ Открыто: {g['cells_opened']}/{total_safe} | x{g['multiplier']}",
        reply_markup=get_mines_kb(uid)
    )
    await c.answer()

# --- ИГРЫ: Башня ---
TOWER_LEVELS = 10

def get_tower_kb(uid, done=False):
    builder = InlineKeyboardBuilder()
    g = games[uid]
    if not done:
        for col in range(5): 
            builder.button(text="❓", callback_data=f"tower_{g['step']}_{col}")
    builder.adjust(5)
    if not done and g['step'] > 0:
        builder.row(InlineKeyboardButton(
            text=f"💰 Забрать {int(g['bet'] * g['multiplier'])} {CURRENCY_NAME}", 
            callback_data="tower_take"
        ))
    return builder.as_markup()

@dp.message(Command("tower"))
@dp.message(F.text.lower().startswith("башня"))
async def tower_game(m: types.Message):
    uid = m.from_user.id
    bet, is_premium = parse_bet(uid, m.text, allow_premium=True)
    if not bet or bet <= 0:
        return await m.answer("❌ Ошибка ставки! Формат: `Башня 100`")
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    board = [[-1 if j == random.randint(0,4) else 0 for j in range(5)] for _ in range(TOWER_LEVELS)]
    games[uid] = {
        'board': board,
        'step': 0,
        'bet': bet_value,
        'bet_premium': bet if is_premium else 0,
        'is_premium': is_premium,
        'multiplier': 1.0,
        'done': False
    }
    await m.answer(
        f"🗼 Башня | Ставка: {bet if is_premium else bet_value} {'GPM' if is_premium else CURRENCY_NAME} | Этаж: 1/{TOWER_LEVELS}",
        reply_markup=get_tower_kb(uid)
    )

@dp.callback_query(F.data.startswith("tower_"))
async def tower_click(c: types.CallbackQuery):
    uid = c.from_user.id
    if uid not in games or games[uid]['done']:
        return await c.answer("Игра не найдена")
    g = games[uid]
    
    if c.data == "tower_take":
        win = int(g['bet'] * g['multiplier'])
        if g.get('is_premium'):
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            await c.message.edit_text(f"💰 Забрал {win_premium} GPM!")
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            await c.message.edit_text(f"💰 Забрал {win} {CURRENCY_NAME}!")
        del games[uid]
        return await c.answer()
    
    lvl, col = map(int, c.data.split("_")[1:])
    
    if g['board'][lvl][col] == -1:
        if g.get('is_premium'):
            await c.message.edit_text(f"💥 МИНА! Проиграно: {g['bet_premium']} GPM")
        else:
            await c.message.edit_text(f"💥 МИНА! Проиграно: {g['bet']} {CURRENCY_NAME}")
        del games[uid]
        return await c.answer()
    
    g['step'] += 1
    g['multiplier'] = round(g['multiplier'] * 1.5, 1)
    
    if g['step'] == TOWER_LEVELS:
        win = int(g['bet'] * g['multiplier'])
        if g.get('is_premium'):
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            await c.message.edit_text(f"🏆 ПОБЕДА! +{win_premium} GPM!")
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            await c.message.edit_text(f"🏆 ПОБЕДА! +{win} {CURRENCY_NAME}!")
        del games[uid]
        return await c.answer()
    
    await c.message.edit_text(
        f"🗼 Этаж {g['step']+1}/{TOWER_LEVELS} | x{g['multiplier']}",
        reply_markup=get_tower_kb(uid)
    )
    await c.answer()

# --- ИГРЫ: Слоты ---
@dp.message(Command("slots"))
@dp.message(F.text.lower().startswith("слот"))
async def slots_game(m: types.Message):
    uid = m.from_user.id
    bet, is_premium = parse_bet(uid, m.text, allow_premium=True)
    if not bet or bet <= 0:
        bet = 100
        is_premium = False
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    if is_premium:
        symbols = ["💎", "👑", "🌟", "⚡", "🔥"]
        mults = {"💎": 3, "👑": 5, "🌟": 8, "⚡": 10, "🔥": 15}
    else:
        symbols = ["🍒", "🍋", "🍊", "7️⃣", "💎"]
        mults = {"🍒": 2, "🍋": 3, "🍊": 4, "7️⃣": 5, "💎": 10}
    
    r1, r2, r3 = random.choice(symbols), random.choice(symbols), random.choice(symbols)
    
    msg = await m.answer("🎰 Крутим...")
    await asyncio.sleep(1)
    
    result = f"🎰 | {r1} | {r2} | {r3} |\n\n"
    win = 0
    
    if r1 == r2 == r3:
        win_mult = mults.get(r1, 2)
        win = bet_value * win_mult
        result += f"🎉 ДЖЕКПОТ! x{win_mult}\n"
    elif r1 == r2 or r2 == r3 or r1 == r3:
        win = bet_value
        result += f"👍 ПОЧТИ! x1\n"
    else:
        result += f"😢 Проигрыш\n"
    
    if win > 0:
        if is_premium:
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            result += f"💰 +{win_premium} GPM"
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            result += f"💰 +{win} {CURRENCY_NAME}"
    
    await msg.edit_text(result)

# --- ИГРЫ: Рулетка (ИСПРАВЛЕННАЯ) ---
@dp.message(Command("roulette"))
@dp.message(F.text.lower().startswith("рулетка"))
async def roulette_game(m: types.Message):
    uid = m.from_user.id
    parts = m.text.lower().split()
    if len(parts) < 3:
        return await m.answer(
            "🎯 Рулетка\nФормат: `Рулетка красное 100` или `Рулетка 7 100`"
        )
    
    bet_type = parts[1]
    bet, is_premium = parse_bet(uid, f"рулетка {parts[2]}", allow_premium=True)
    if not bet or bet <= 0:
        return await m.answer("❌ Неверная ставка")
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    number = random.randint(0, 36)
    red = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    color = "красное" if number in red else "черное" if number != 0 else "зеленое"
    
    result = f"🎯 Выпало: **{number} {color}**\n\n"
    win = 0
    
    if bet_type.isdigit():
        guess = int(bet_type)
        if guess == number:
            win = bet_value * 36
            result += f"🎉 **ПОБЕДА!** x36\n"
        else:
            result += f"😢 Проигрыш\n"
    elif bet_type == "красное":
        if color == "красное":
            win = bet_value * 2
            result += f"🎉 **КРАСНОЕ!** x2\n"
        else:
            result += f"😢 Проигрыш\n"
    elif bet_type == "черное":
        if color == "черное":
            win = bet_value * 2
            result += f"🎉 **ЧЕРНОЕ!** x2\n"
        else:
            result += f"😢 Проигрыш\n"
    elif bet_type in ["чет", "четное"]:
        if number != 0 and number % 2 == 0:
            win = bet_value * 2
            result += f"🎉 **ЧЕТНОЕ!** x2\n"
        else:
            result += f"😢 Проигрыш\n"
    elif bet_type in ["нечет", "нечетное"]:
        if number % 2 == 1:
            win = bet_value * 2
            result += f"🎉 **НЕЧЕТНОЕ!** x2\n"
        else:
            result += f"😢 Проигрыш\n"
    elif bet_type == "число":
        result += f"❌ Укажите конкретное число (0-36), например: `рулетка 7 100`\n"
        win = 0
    else:
        result += f"❌ Неверный тип ставки. Используй: красное, черное, чет, нечет или число.\n"
        win = 0
    
    if win > 0:
        if is_premium:
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            result += f"💰 +{win_premium} GPM"
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            result += f"💰 +{win} {CURRENCY_NAME}"
    
    result += f"\n\n💳 Баланс: {get_balance(uid)} {CURRENCY_NAME} | 💎 GPM: {get_premium(uid)}"
    
    await m.answer(result, parse_mode="Markdown")

# --- ИГРЫ: Монетка (ИСПРАВЛЕННАЯ) ---
@dp.message(Command("coin"))
@dp.message(F.text.lower().startswith("монетка"))
@dp.message(F.text.lower().startswith("орел"))
@dp.message(F.text.lower().startswith("решка"))
async def coin_game(m: types.Message):
    uid = m.from_user.id
    parts = m.text.lower().split()
    if len(parts) < 2:
        return await m.answer("🪙 Монетка\nФормат: `Орел 100` или `Решка 100`")
    
    choice = parts[0]
    
    if choice == "монетка":
        choice = random.choice(["орел", "решка"])
    
    bet, is_premium = parse_bet(uid, m.text, allow_premium=True)
    if not bet or bet <= 0:
        return await m.answer("❌ Неверная ставка")
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    result = random.choice(["орел", "решка"])
    
    msg = await m.answer("🪙 Подбрасываем...")
    await asyncio.sleep(1)
    
    text = f"🪙 Выпало: {result.upper()}\n\n"
    
    if choice == result:
        win = bet_value * 2
        if is_premium:
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            text += f"🎉 ПОБЕДА! +{win_premium} GPM"
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            text += f"🎉 ПОБЕДА! +{win} {CURRENCY_NAME}"
    else:
        text += f"😢 Проигрыш"
    
    await msg.edit_text(text)

# --- ИГРЫ: Кости ---
@dp.message(Command("dice"))
@dp.message(F.text.lower().startswith("кости"))
async def dice_game(m: types.Message):
    uid = m.from_user.id
    parts = m.text.lower().split()
    if len(parts) < 3:
        return await m.answer("🎲 Кости\nФормат: `Кости больше 100` или `Кости 7 100`")
    
    bet_type = parts[1]
    bet, is_premium = parse_bet(uid, f"кости {parts[2]}", allow_premium=True)
    if not bet or bet <= 0:
        return await m.answer("❌ Неверная ставка")
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    d1, d2 = random.randint(1,6), random.randint(1,6)
    total = d1 + d2
    
    msg = await m.answer("🎲 Бросаем...")
    await asyncio.sleep(1)
    
    result = f"🎲 {d1} + {d2} = {total}\n\n"
    win = 0
    
    if bet_type == "больше" and total > 7:
        win = bet_value * 2
        result += f"🎉 БОЛЬШЕ! x2\n"
    elif bet_type == "меньше" and total < 7:
        win = bet_value * 2
        result += f"🎉 МЕНЬШЕ! x2\n"
    elif bet_type == "7" and total == 7:
        win = bet_value * 5
        result += f"🎉 РОВНО 7! x5\n"
    elif bet_type.isdigit() and int(bet_type) == total:
        win = bet_value * 10
        result += f"🎉 ТОЧНО! x10\n"
    else:
        result += f"😢 Проигрыш\n"
    
    if win > 0:
        if is_premium:
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            result += f"💰 +{win_premium} GPM"
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            result += f"💰 +{win} {CURRENCY_NAME}"
    
    await msg.edit_text(result)

# --- ИГРЫ: Очко (21) ---
@dp.message(Command("blackjack"))
@dp.message(F.text.lower().startswith("очко"))
async def blackjack_game(m: types.Message):
    uid = m.from_user.id
    bet, is_premium = parse_bet(uid, m.text, allow_premium=True)
    if not bet or bet <= 0:
        return await m.answer("🃏 Очко\nФормат: `Очко 100`")
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    deck = [2,3,4,5,6,7,8,9,10,10,10,10,11] * 4
    random.shuffle(deck)
    p_cards = [deck.pop(), deck.pop()]
    
    games[uid] = {
        'type': 'bj',
        'bet': bet_value,
        'is_premium': is_premium,
        'bet_premium': bet if is_premium else 0,
        'deck': deck,
        'p_cards': p_cards,
        'done': False
    }
    
    kb = InlineKeyboardBuilder()
    kb.button(text="🃏 Еще", callback_data="bj_more")
    kb.button(text="🛑 Стоп", callback_data="bj_stop")
    
    await m.answer(
        f"🃏 Очко\nСумма: {sum(p_cards)} | Карты: {p_cards}",
        reply_markup=kb.as_markup()
    )

@dp.callback_query(F.data.startswith("bj_"))
async def bj_callback(c: types.CallbackQuery):
    uid = c.from_user.id
    g = games.get(uid)
    if not g or g['done']:
        return await c.answer("Игра не найдена")
    
    if c.data == "bj_more":
        g['p_cards'].append(g['deck'].pop())
        p_sum = sum(g['p_cards'])
        
        if p_sum > 21:
            g['done'] = True
            await c.message.edit_text(f"💥 ПЕРЕБОР! Сумма: {p_sum}")
        elif p_sum == 21:
            g['done'] = True
            win = g['bet'] * 2
            if g.get('is_premium'):
                win_premium = win // PREMIUM_RATE
                add_premium(uid, win_premium)
                add_total_win(uid, win)
                await c.message.edit_text(f"🎉 21! +{win_premium} GPM")
            else:
                add_balance(uid, win)
                add_total_win(uid, win)
                await c.message.edit_text(f"🎉 21! +{win} {CURRENCY_NAME}")
        else:
            await c.message.edit_text(
                f"🃏 Сумма: {p_sum} | Карты: {g['p_cards']}",
                reply_markup=c.message.reply_markup
            )
    else:
        g['done'] = True
        d_sum = random.randint(17, 23)
        p_sum = sum(g['p_cards'])
        
        if d_sum > 21 or p_sum > d_sum:
            win = g['bet'] * 2
            if g.get('is_premium'):
                win_premium = win // PREMIUM_RATE
                add_premium(uid, win_premium)
                add_total_win(uid, win)
                res = f"🎉 ПОБЕДА! +{win_premium} GPM (Дилер: {d_sum})"
            else:
                add_balance(uid, win)
                add_total_win(uid, win)
                res = f"🎉 ПОБЕДА! +{win} {CURRENCY_NAME} (Дилер: {d_sum})"
        else:
            res = f"❌ ПРОИГРЫШ! Дилер: {d_sum}"
        
        await c.message.edit_text(f"🃏 ИТОГ\nВы: {p_sum} | Дилер: {d_sum}\n{res}")
    await c.answer()

# --- ИГРЫ: Кейсы ---
CASES = {
    "базовый": {"price": 1000, "items": [100, 200, 300, 500, 1000, 2000]},
    "серебряный": {"price": 5000, "items": [500, 1000, 2000, 5000, 10000, 25000]},
    "золотой": {"price": 25000, "items": [1000, 5000, 10000, 25000, 50000, 100000]},
    "алмазный": {"price": 100000, "items": [10000, 25000, 50000, 100000, 250000, 500000]}
}

@dp.message(Command("cases"))
@dp.message(F.text.lower().startswith("кейс"))
async def cases_game(m: types.Message):
    uid = m.from_user.id
    parts = m.text.lower().split()
    if len(parts) < 2:
        cases_list = "\n".join([f"• {name.capitalize()} - {data['price']:,} {CURRENCY_NAME}" for name, data in CASES.items()])
        return await m.answer(
            f"🎁 КЕЙСЫ\n\nДоступные кейсы:\n{cases_list}\n\nФормат: `Кейс базовый`"
        )
    
    case_name = parts[1]
    if case_name not in CASES:
        return await m.answer("❌ Такого кейса нет!")
    
    case = CASES[case_name]
    price = case['price']
    
    if get_balance(uid) < price:
        return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Нужно: {price:,}")
    
    take_balance(uid, price)
    add_total_bet(uid, price)
    
    msg = await m.answer(f"🎁 Открываем {case_name} кейс...")
    await asyncio.sleep(1.5)
    
    win = random.choice(case['items'])
    add_balance(uid, win)
    add_total_win(uid, win)
    
    result = f"🎁 {case_name.upper()} КЕЙС\n\n"
    result += f"💰 Вы получили: {win:,} {CURRENCY_NAME}!\n\n"
    
    if win > price:
        result += f"🔥 Прибыль: +{win - price:,} {CURRENCY_NAME}!"
    elif win < price:
        result += f"😢 Убыток: -{price - win:,} {CURRENCY_NAME}"
    else:
        result += f"🤝 В ноль"
    
    result += f"\n\n💰 Баланс: {get_balance(uid):,} {CURRENCY_NAME}"
    
    await msg.edit_text(result)

# --- ИГРЫ: Краш ---
@dp.message(Command("crash"))
@dp.message(F.text.lower().startswith("краш"))
async def crash_game(m: types.Message):
    uid = m.from_user.id
    bet, is_premium = parse_bet(uid, m.text, allow_premium=True)
    if not bet or bet <= 0:
        return await m.answer("📈 Краш\nФормат: `Краш 100`")
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    r = random.random()
    crash_point = round(1.1 + 3.9 * (r * r), 2)
    
    game_id = f"crash_{uid}_{bet_value}_{crash_point}_{int(time.time())}"
    
    kb = InlineKeyboardBuilder()
    kb.button(text="💰 ЗАБРАТЬ", callback_data=game_id)
    
    msg = await m.answer(
        f"📈 КРАШ\n💰 Ставка: {bet if is_premium else bet_value} {'GPM' if is_premium else CURRENCY_NAME}\n\nМножитель: 1.0",
        reply_markup=kb.as_markup()
    )
    
    curr_mult = 1.0
    games[uid] = {
        "type": "crash",
        "active": True,
        "bet": bet_value,
        "is_premium": is_premium,
        "bet_premium": bet if is_premium else 0
    }
    
    while curr_mult < crash_point:
        await asyncio.sleep(1.5)
        curr_mult = round(curr_mult + 0.3, 1)
        if uid not in games or not games[uid].get("active"):
            return
        if curr_mult >= crash_point:
            break
        try:
            await msg.edit_text(
                f"📈 КРАШ\n💰 Ставка: {bet if is_premium else bet_value} {'GPM' if is_premium else CURRENCY_NAME}\n\nМножитель: {curr_mult}",
                reply_markup=kb.as_markup()
            )
        except:
            break
    
    if uid in games and games[uid].get("active"):
        games[uid]["active"] = False
        await msg.edit_text(
            f"💥 КРАШ! x{crash_point}\n💰 Проиграно: {bet if is_premium else bet_value} {'GPM' if is_premium else CURRENCY_NAME}"
        )

@dp.callback_query(F.data.startswith("crash_"))
async def crash_callback(c: types.CallbackQuery):
    uid = c.from_user.id
    data = c.data.split("_")
    owner_id = int(data[1])
    bet = int(data[2])
    
    if uid != owner_id:
        return await c.answer("❌ Это не ваша игра!", show_alert=True)
    
    if uid not in games or not games[uid].get("active"):
        return await c.answer("⚠️ Игра уже завершена!")
    
    try:
        current_mult = float(c.message.text.split("\n")[-1].split(" ")[-1])
    except:
        current_mult = 1.0
    
    games[uid]["active"] = False
    win = int(bet * current_mult)
    
    if games[uid].get("is_premium"):
        win_premium = win // PREMIUM_RATE
        add_premium(uid, win_premium)
        add_total_win(uid, win)
        win_msg = f"💰 Выигрыш: {win_premium} GPM"
    else:
        add_balance(uid, win)
        add_total_win(uid, win)
        win_msg = f"💰 Выигрыш: {win} {CURRENCY_NAME}"
    
    await c.message.edit_text(f"💰 УСПЕХ!\nЗабрал на x{current_mult}\n{win_msg}")
    await c.answer()

# --- ИГРЫ: Спорт ---
async def play_sport(m, emoji, wins):
    uid = m.from_user.id
    bet, is_premium = parse_bet(uid, m.text, allow_premium=True)
    if not bet or bet <= 0:
        return await m.answer("❌ Ошибка ставки!")
    
    if is_premium:
        if bet > get_premium(uid):
            return await m.answer(f"❌ Недостаточно GPM! Баланс: {get_premium(uid)}")
        take_premium(uid, bet)
        bet_value = bet * PREMIUM_RATE
        add_total_bet(uid, bet_value)
    else:
        if bet > get_balance(uid):
            return await m.answer(f"❌ Недостаточно {CURRENCY_NAME}! Баланс: {get_balance(uid):,}")
        take_balance(uid, bet)
        bet_value = bet
        add_total_bet(uid, bet)
    
    res = await m.answer_dice(emoji=emoji)
    await asyncio.sleep(4)
    
    if res.dice.value in wins:
        win = bet_value * 3
        if is_premium:
            win_premium = win // PREMIUM_RATE
            add_premium(uid, win_premium)
            add_total_win(uid, win)
            await m.answer(f"🎉 ПОБЕДА! +{win_premium} GPM")
        else:
            add_balance(uid, win)
            add_total_win(uid, win)
            await m.answer(f"🎉 ПОБЕДА! +{win} {CURRENCY_NAME}")
    else:
        await m.answer(f"❌ ПРОИГРЫШ!")

@dp.message(Command("football"))
@dp.message(F.text.lower().startswith("футбол"))
async def sport_f(m: types.Message): 
    await play_sport(m, "⚽", [3, 4, 5])

@dp.message(Command("basketball"))
@dp.message(F.text.lower().startswith("баскет"))
async def sport_b(m: types.Message): 
    await play_sport(m, "🏀", [4, 5])

@dp.message(Command("bowling"))
@dp.message(F.text.lower().startswith("боулинг"))
async def sport_bow(m: types.Message): 
    await play_sport(m, "🎳", [6])

@dp.message(Command("darts"))
@dp.message(F.text.lower().startswith("дартс"))
async def sport_d(m: types.Message): 
    await play_sport(m, "🎯", [6])

# --- ТОП ---
@dp.message(Command("top"))
async def cmd_top(m: types.Message):
    with get_db() as conn:
        top = conn.execute("SELECT username, balance FROM users WHERE banned = 0 ORDER BY balance DESC LIMIT 10").fetchall()
    if not top:
        return await m.answer("📭 Топ пуст")
    text = "🏆 ТОП-10\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, u in enumerate(top):
        medal = medals[i] if i < len(medals) else f"{i+1}."
        name = u['username'] or f"Игрок {i+1}"
        text += f"{medal} {name} — {u['balance']} {CURRENCY_NAME}\n"
    await m.answer(text)

# --- ЛОТЕРЕЯ ---
@dp.message(Command("lottery"))
async def lottery(m: types.Message):
    uid = m.from_user.id
    user = get_user(uid)
    if not user:
        return await m.answer("❌ Сначала /start")
    
    last_lottery = user.get('last_lottery', 0)
    if int(time.time()) - last_lottery < 86400:
        remaining = 86400 - (int(time.time()) - last_lottery)
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        return await m.answer(f"⏳ Следующий розыгрыш через {hours}ч {minutes}м")
    
    price = 100
    if get_balance(uid) < price:
        return await m.answer(f"❌ Билет стоит {price} {CURRENCY_NAME}!")
    
    take_balance(uid, price)
    add_total_bet(uid, price)
    
    win = random.randint(50, 5000)
    add_balance(uid, win)
    add_total_win(uid, win)
    
    with get_db() as conn:
        conn.execute("UPDATE users SET last_lottery = ? WHERE uid = ?", (int(time.time()), uid))
        conn.commit()
    
    if win >= 1000:
        emoji = "🔥 ДЖЕКПОТ!"
    elif win >= 500:
        emoji = "🎉 КРУТО!"
    elif win >= 200:
        emoji = "👍 НЕПЛОХО!"
    else:
        emoji = "👎 В следующий раз"
    
    await m.answer(f"🎲 ЛОТЕРЕЯ\n\n💰 Выигрыш: {win} {CURRENCY_NAME}!\n{emoji}")

# --- ПОМОЩЬ ---
@dp.message(Command("help"))
async def help_cmd(m: types.Message):
    text = (
        "❓ **ПОМОЩЬ**\n\n"
        "**🎮 ИГРЫ (пиши словами или через /):**\n"
        "• `Слоты 100` или `/slots 100` — 🎰 слоты\n"
        "• `Мины 100 5` или `/mines 100 5` — 💣 мины\n"
        "• `Рулетка красное 100` или `/roulette красное 100` — 🎯 рулетка\n"
        "• `Монетка 100` или `/coin 100` — 🪙 монетка\n"
        "• `Кости больше 100` или `/dice больше 100` — 🎲 кости\n"
        "• `Башня 100` или `/tower 100` — 🗼 башня\n"
        "• `Очко 100` или `/blackjack 100` — 🃏 очко\n"
        "• `Кейс базовый` или `/cases базовый` — 🎁 кейсы\n"
        "• `Краш 100` или `/crash 100` — 📈 краш\n"
        "• `Футбол 100` или `/football 100` — ⚽ футбол\n"
        "• `Баскет 100` или `/basketball 100` — 🏀 баскет\n"
        "• `Боулинг 100` или `/bowling 100` — 🎳 боулинг\n"
        "• `Дартс 100` или `/darts 100` — 🎯 дартс\n\n"
        
        "**💰 СИСТЕМА МЕР:**\n"
        "• `100к` = 100 000\n"
        "• `5кк` = 5 000 000\n"
        "• `2ккк` = 2 000 000 000\n"
        "• `1кккк` = 1 000 000 000 000\n"
        "• `все` — поставить всё\n"
        "• `все pm` — поставить весь GPM\n\n"
        
        "**💎 GPM:**\n"
        "• `/premium` — информация о GPM\n"
        "• `/buy_premium [количество]` — купить GPM\n"
        "• Ставки с `pm`: `Слоты 5pm`\n\n"
        
        "**💰 ПЕРЕВОДЫ:**\n"
        "• `/send @username 1000` — перевести по юзернейму\n"
        "• `/send 123456789 1000` — перевести по ID\n"
        "• Ответ на сообщение: `/send 1000`\n\n"
        
        "**🎫 ПРОМОКОДЫ:**\n"
        "• `/create_promo [сумма] [активации]` — создать промокод (админ)\n"
        "• `/activate [код]` — активировать промокод\n\n"
        
        "**🔗 ЧЕКИ-ССЫЛКИ (одноразовые):**\n"
        "• `/create_check_link [сумма]` — создать чек-ссылку (админ)\n"
        "• Переходи по ссылке и нажимай /start\n\n"
        
        "**🎫 ЧЕКИ:**\n"
        f"• `/buy_check_access` — доступ к чекам ({CHECK_ACCESS_PRICE:,} {CURRENCY_NAME})\n"
        "• `/create_check [сумма]` — создать чек\n"
        "• `/create_premium_check [количество]` — чек на GPM\n"
        "• `/claim [код]` — активировать чек\n\n"
        
        f"**⭐ ПОКУПКА {CURRENCY_NAME}:**\n"
        "• `/buy_stars` — купить PLCOINS за звёзды\n\n"
        
        "**👤 ПРОФИЛЬ:**\n"
        "• `/profile` — информация\n"
        "• `/balance` — баланс и статистика\n"
        "• `/lottery` — ежедневный розыгрыш\n"
        "• `/top` — топ игроков"
    )
    await m.answer(text, parse_mode="Markdown")

# ============================================
# ПЕРЕВОДЫ МЕЖДУ ИГРОКАМИ
# ============================================
@dp.message(Command("send"))
async def cmd_send(m: types.Message):
    uid = m.from_user.id
    sender = get_user(uid)
    
    if not sender:
        return await m.answer("❌ Сначала /start")
    
    parts = m.text.split()
    target_id = None
    amount = 0
    
    if m.reply_to_message:
        target_id = m.reply_to_message.from_user.id
        if len(parts) < 2:
            return await m.answer("📝 Формат при ответе: /send [сумма]")
        try:
            amount = int(parts[1])
        except:
            return await m.answer("❌ Неверная сумма!")
    
    elif len(parts) >= 3 and parts[1].startswith('@'):
        username = parts[1][1:]
        with get_db() as conn:
            user = conn.execute(
                "SELECT uid FROM users WHERE username = ?",
                (username,)
            ).fetchone()
            if not user:
                return await m.answer(f"❌ Пользователь @{username} не найден в базе!")
            target_id = user['uid']
        try:
            amount = int(parts[2])
        except:
            return await m.answer("❌ Неверная сумма!")
    
    elif len(parts) >= 3 and parts[1].isdigit():
        target_id = int(parts[1])
        try:
            amount = int(parts[2])
        except:
            return await m.answer("❌ Неверная сумма!")
    
    else:
        return await m.answer(
            "📝 **Форматы команды /send:**\n"
            "• `/send @username 1000` — по юзернейму\n"
            "• `/send 123456789 1000` — по ID\n"
            "• Ответ на сообщение: `/send 1000`"
        )
    
    if target_id == uid:
        return await m.answer("❌ Нельзя перевести самому себе!")
    
    if amount <= 0:
        return await m.answer("❌ Сумма должна быть больше 0!")
    
    if sender['balance'] < amount:
        return await m.answer(f"❌ Недостаточно средств! Баланс: {sender['balance']} {CURRENCY_NAME}")
    
    target = get_user(target_id)
    if not target:
        return await m.answer("❌ Получатель не найден в базе!")
    
    take_balance(uid, amount)
    add_balance(target_id, amount)
    
    await m.answer(
        f"✅ Перевод выполнен!\n\n"
        f"💸 Отправлено: {amount} {CURRENCY_NAME}\n"
        f"👤 Получатель: {target['username'] or target_id}\n"
        f"💰 Ваш баланс: {get_balance(uid)} {CURRENCY_NAME}"
    )
    
    try:
        await bot.send_message(
            target_id,
            f"💰 Вам перевели {amount} {CURRENCY_NAME}!\n"
            f"👤 Отправитель: {sender['username'] or uid}\n"
            f"💳 Новый баланс: {get_balance(target_id)} {CURRENCY_NAME}"
        )
    except:
        pass

# ============================================
# ПРОМОКОДЫ
# ============================================
@dp.message(Command("create_promo"))
async def cmd_create_promo(m: types.Message):
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    parts = m.text.split()
    if len(parts) < 3:
        return await m.answer("📝 Формат: /create_promo [сумма] [количество активаций]\nПример: /create_promo 1000 5")
    
    try:
        amount = int(parts[1])
        max_uses = int(parts[2])
    except:
        return await m.answer("❌ Неверные параметры!")
    
    if amount <= 0 or max_uses <= 0:
        return await m.answer("❌ Сумма и количество активаций должны быть больше 0!")
    
    code = str(uuid.uuid4())[:8].upper()
    
    with get_db() as conn:
        conn.execute(
            "INSERT INTO promocodes (code, creator_id, amount, max_uses, created) VALUES (?, ?, ?, ?, ?)",
            (code, m.from_user.id, amount, max_uses, int(time.time()))
        )
        conn.commit()
    
    await m.answer(
        f"✅ **Промокод создан!**\n\n"
        f"🎫 Код: `{code}`\n"
        f"💰 Сумма: {amount} {CURRENCY_NAME}\n"
        f"👥 Лимит активаций: {max_uses}\n\n"
        f"Активация: `/activate {code}`"
    )

@dp.message(Command("activate"))
async def cmd_activate_promo(m: types.Message):
    uid = m.from_user.id
    parts = m.text.split()
    
    if len(parts) < 2:
        return await m.answer("📝 Формат: `/activate [код]`")
    
    code = parts[1].upper()
    
    with get_db() as conn:
        promo = conn.execute(
            "SELECT * FROM promocodes WHERE code = ? AND is_active = 1",
            (code,)
        ).fetchone()
        
        if not promo:
            return await m.answer("❌ Промокод не найден или неактивен!")
        
        if promo['used_count'] >= promo['max_uses']:
            conn.execute("UPDATE promocodes SET is_active = 0 WHERE code = ?", (code,))
            conn.commit()
            return await m.answer("❌ Промокод уже использован максимальное количество раз!")
        
        add_balance(uid, promo['amount'])
        
        conn.execute(
            "UPDATE promocodes SET used_count = used_count + 1 WHERE code = ?",
            (code,)
        )
        
        if promo['used_count'] + 1 >= promo['max_uses']:
            conn.execute("UPDATE promocodes SET is_active = 0 WHERE code = ?", (code,))
        
        conn.commit()
    
    await m.answer(f"✅ Промокод активирован! +{promo['amount']} {CURRENCY_NAME}")

# ============================================
# ЧЕКИ-ССЫЛКИ (одноразовые)
# ============================================
@dp.message(Command("create_check_link"))
async def cmd_create_check_link(m: types.Message):
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer("📝 Формат: /create_check_link [сумма]\nПример: /create_check_link 1000")
    
    try:
        amount = int(parts[1])
    except:
        return await m.answer("❌ Неверная сумма!")
    
    if amount <= 0:
        return await m.answer("❌ Сумма должна быть больше 0!")
    
    check_id = str(uuid.uuid4())[:8].upper()
    
    with get_db() as conn:
        conn.execute(
            "INSERT INTO check_links (id, creator_id, amount, max_uses, created) VALUES (?, ?, ?, ?, ?)",
            (check_id, m.from_user.id, amount, 1, int(time.time()))
        )
        conn.commit()
    
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start=check_{check_id}"
    
    await m.answer(
        f"✅ **Чек-ссылка создана!**\n\n"
        f"🔗 Ссылка: {link}\n"
        f"💰 Сумма: {amount} {CURRENCY_NAME}\n"
        f"👥 Может активировать только 1 раз\n\n"
        f"При переходе по ссылке и команде /start бот автоматически активирует чек."
    )

# ============================================
# АДМИН КОМАНДЫ
# ============================================
@dp.message(Command("give_premium"))
async def cmd_give_premium(m: types.Message):
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    parts = m.text.split()
    if len(parts) < 3:
        return await m.answer(f"📝 Формат: /give_premium ID количество")
    
    try:
        target_id = int(parts[1])
        amount = int(parts[2])
    except:
        return await m.answer("❌ Неверный ID или количество")
    
    if amount <= 0:
        return await m.answer("❌ Количество должно быть больше 0!")
    
    target_user = get_user(target_id)
    if not target_user:
        return await m.answer("❌ Пользователь не найден!")
    
    add_premium(target_id, amount)
    await m.answer(f"✅ Выдано {amount} GPM пользователю {target_id}")
    
    try:
        await bot.send_message(target_id, f"🎁 Администратор выдал вам {amount} GPM!")
    except:
        pass

@dp.message(Command("give_check_access"))
async def cmd_give_check_access(m: types.Message):
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    parts = m.text.split()
    if len(parts) < 2:
        return await m.answer(f"📝 Формат: /give_check_access ID")
    
    try:
        target_id = int(parts[1])
    except:
        return await m.answer("❌ Неверный ID!")
    
    target_user = get_user(target_id)
    if not target_user:
        return await m.answer("❌ Пользователь не найден!")
    
    grant_check_access(target_id)
    await m.answer(f"✅ Выдан доступ к чекам пользователю {target_id}")
    
    try:
        await bot.send_message(target_id, f"🎁 Администратор выдал вам доступ к чекам!")
    except:
        pass

@dp.message(Command("users"))
async def cmd_users(m: types.Message):
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    with get_db() as conn:
        users = conn.execute("SELECT uid, username, balance, premium_balance, role, banned FROM users ORDER BY balance DESC LIMIT 50").fetchall()
    
    if not users:
        return await m.answer("📭 Нет пользователей")
    
    text = "👥 **СПИСОК ИГРОКОВ**\n\n"
    for u in users:
        status = "🔴" if u['banned'] else "🟢"
        admin = "👑" if u['role'] >= 2 else ""
        text += f"{status} `{u['uid']}` | {u['username'] or 'Нет'} | {u['balance']} {CURRENCY_NAME} | 💎{u['premium_balance']} GPM {admin}\n"
        
        if len(text) > 3000:
            await m.answer(text, parse_mode="Markdown")
            text = ""
    
    if text:
        await m.answer(text, parse_mode="Markdown")

@dp.message(Command("banlist"))
async def cmd_banlist(m: types.Message):
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    with get_db() as conn:
        banned = conn.execute("SELECT uid, username, ban_reason FROM users WHERE banned = 1").fetchall()
    
    if not banned:
        return await m.answer("📋 Бан-лист пуст")
    
    text = "⛔ **БАН-ЛИСТ**\n\n"
    for u in banned:
        text += f"• `{u['uid']}` | {u['username'] or 'Нет'}\n"
        if u['ban_reason']:
            text += f"  Причина: {u['ban_reason']}\n"
    
    await m.answer(text, parse_mode="Markdown")

@dp.message(Command("stats"))
async def cmd_stats(m: types.Message):
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM users").fetchone()['cnt']
        active = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE banned = 0").fetchone()['cnt']
        banned = conn.execute("SELECT COUNT(*) as cnt FROM users WHERE banned = 1").fetchone()['cnt']
        total_balance = conn.execute("SELECT SUM(balance) as sum FROM users").fetchone()['sum'] or 0
        total_premium = conn.execute("SELECT SUM(premium_balance) as sum FROM users").fetchone()['sum'] or 0
        checks = conn.execute("SELECT COUNT(*) as cnt FROM checks").fetchone()['cnt']
        promos = conn.execute("SELECT COUNT(*) as cnt FROM promocodes").fetchone()['cnt']
        check_links = conn.execute("SELECT COUNT(*) as cnt FROM check_links").fetchone()['cnt']
        total_bet = conn.execute("SELECT SUM(total_bet) as sum FROM users").fetchone()['sum'] or 0
        total_win = conn.execute("SELECT SUM(total_win) as sum FROM users").fetchone()['sum'] or 0
    
    text = (
        f"📊 **СТАТИСТИКА**\n\n"
        f"👥 Всего игроков: {total}\n"
        f"✅ Активных: {active}\n"
        f"🔴 Забанено: {banned}\n"
        f"💰 Всего {CURRENCY_NAME}: {total_balance:,}\n"
        f"💎 Всего GPM: {total_premium}\n"
        f"🎫 Создано чеков: {checks}\n"
        f"🏷 Промокодов: {promos}\n"
        f"🔗 Чеков-ссылок: {check_links}\n"
        f"💸 Всего поставлено: {total_bet:,} {CURRENCY_NAME}\n"
        f"💰 Всего выиграно: {total_win:,} {CURRENCY_NAME}\n"
        f"📈 Общий профит: {total_win - total_bet:,} {CURRENCY_NAME}"
    )
    await m.answer(text, parse_mode="Markdown")

# --- РАССЫЛКА (BROADCAST) ---
@dp.message(Command("broadcast"))
async def cmd_broadcast(m: types.Message):
    """Начать рассылку сообщения всем пользователям"""
    if get_role(m.from_user.id) < 2:
        return await m.answer("⛔ Только для администраторов!")
    
    await m.answer(
        "📢 **Режим рассылки активирован**\n\n"
        "Отправьте сообщение, которое хотите разослать ВСЕМ пользователям бота.\n"
        "Поддерживаются: текст, фото, видео, документы\n\n"
        "🔴 Для отмены отправьте /cancel",
        parse_mode="Markdown"
    )
    
    users_data[m.from_user.id] = {'state': 'waiting_for_broadcast'}

@dp.message(F.text == "/cancel")
async def cmd_cancel(m: types.Message):
    """Отмена текущего действия"""
    if m.from_user.id in users_data:
        del users_data[m.from_user.id]
        await m.answer("✅ Действие отменено")
    else:
        await m.answer("❌ Нет активного действия")

@dp.message()
async def handle_broadcast_message(m: types.Message):
    """Обработка сообщения для рассылки"""
    if m.text and m.text.startswith('/'):
        return
    
    # Пропускаем слова-команды
    if m.text:
        text_lower = m.text.lower()
        if any(text_lower.startswith(word) for word in ["слот", "мин", "рулетк", "монетк", "орел", "решк", "кост", "башн", "очк", "кейс", "краш", "футбол", "баскет", "боулинг", "дартс"]):
            return
    
    if m.from_user.id not in users_data or users_data[m.from_user.id].get('state') != 'waiting_for_broadcast':
        return
    
    if get_role(m.from_user.id) < 2:
        del users_data[m.from_user.id]
        return
    
    with get_db() as conn:
        users = conn.execute("SELECT uid FROM users WHERE banned = 0").fetchall()
    
    if not users:
        await m.answer("❌ Нет пользователей для рассылки")
        del users_data[m.from_user.id]
        return
    
    total = len(users)
    success = 0
    failed = 0
    
    status_msg = await m.answer(
        f"📢 **Начинаю рассылку...**\n"
        f"👥 Всего получателей: {total}\n"
        f"⏳ 0/{total} отправлено",
        parse_mode="Markdown"
    )
    
    for i, user in enumerate(users, 1):
        try:
            await m.copy_to(
                chat_id=user['uid'],
                caption=m.caption,
                parse_mode="Markdown"
            )
            success += 1
        except Exception as e:
            failed += 1
            print(f"❌ Ошибка отправки пользователю {user['uid']}: {e}")
        
        if i % 10 == 0:
            await status_msg.edit_text(
                f"📢 **Рассылка...**\n"
                f"👥 Всего: {total}\n"
                f"✅ Отправлено: {success}\n"
                f"❌ Ошибок: {failed}\n"
                f"⏳ Прогресс: {i}/{total}",
                parse_mode="Markdown"
            )
        
        await asyncio.sleep(0.05)
    
    await status_msg.edit_text(
        f"📢 **Рассылка завершена!**\n\n"
        f"👥 Всего получателей: {total}\n"
        f"✅ Успешно: {success}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="Markdown"
    )
    
    del users_data[m.from_user.id]

# ============================================
# КОМАНДА: bot_stars
# ============================================
@dp.message(Command("bot_stars"))
async def cmd_bot_stars(m: types.Message):
    if m.from_user.id != OWNER_ID:
        return await m.answer("⛔ Только для владельца!")
    
    with get_db() as conn:
        total_stars = conn.execute("SELECT SUM(amount_stars) as total FROM bot_stars").fetchone()['total'] or 0
        total_purchases = conn.execute("SELECT COUNT(*) as cnt FROM bot_stars").fetchone()['cnt'] or 0
        last_purchase = conn.execute("SELECT date, amount_stars, user_id FROM bot_stars ORDER BY date DESC LIMIT 1").fetchone()
    
    text = f"⭐ **СТАТИСТИКА ЗВЕЗД БОТА**\n\n"
    text += f"💰 Всего получено звезд: **{total_stars}**\n"
    text += f"📊 Количество покупок: **{total_purchases}**\n\n"
    
    if last_purchase:
        from datetime import datetime
        date_str = datetime.fromtimestamp(last_purchase['date']).strftime('%d.%m.%Y %H:%M')
        text += f"🕐 Последняя покупка:\n"
        text += f"   • Дата: {date_str}\n"
        text += f"   • Звезд: {last_purchase['amount_stars']}\n"
        text += f"   • Пользователь: `{last_purchase['user_id']}`\n"
    
    text += f"\n📌 Минимальная сумма вывода: 1000 звезд\n"
    text += f"🔗 Вывод через Fragment: fragment.com"
    
    await m.answer(text, parse_mode="Markdown")

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
