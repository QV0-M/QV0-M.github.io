import os
import random
import sqlite3
import time
from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# =========================================================
# CONFIG
# =========================================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")

if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD not found")
DB_PATH = os.getenv("DB_PATH", "bot.db")

STAR_COOLDOWN = 15 * 60
TELESCOPE_COOLDOWN = 24 * 60 * 60

if not TOKEN:
    raise RuntimeError("BOT_TOKEN not found in .env")


# =========================================================
# DATABASE
# =========================================================

db = sqlite3.connect(DB_PATH, check_same_thread=False)
db.row_factory = sqlite3.Row


def init_db():
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',
            stars INTEGER DEFAULT 0,
            last_star REAL DEFAULT 0,
            last_telescope REAL DEFAULT 0
        )
    """)

    # Migration for old databases
    try:
        db.execute(
            "ALTER TABLE users ADD COLUMN last_telescope REAL DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass

    db.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_file_id TEXT NOT NULL,
            name TEXT NOT NULL,
            ability TEXT NOT NULL,
            uploader TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            code TEXT NOT NULL,
            price INTEGER NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            card_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            purchased_at REAL NOT NULL
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS owned_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            card_id INTEGER NOT NULL,
            code TEXT NOT NULL,
            purchased_at REAL NOT NULL
        )
    """)

    db.commit()


init_db()


# =========================================================
# STATES
# =========================================================

pending_admin = {}
add_flow = {}


# =========================================================
# HELPERS
# =========================================================

def save_user(user):
    db.execute("""
        INSERT OR IGNORE INTO users
        (user_id, username, first_name, stars, last_star, last_telescope)
        VALUES (?, ?, ?, 0, 0, 0)
    """, (
        user.id,
        user.username or "",
        user.first_name or "",
    ))

    db.execute("""
        UPDATE users
        SET username = ?, first_name = ?
        WHERE user_id = ?
    """, (
        user.username or "",
        user.first_name or "",
        user.id,
    ))

    db.commit()


def is_admin(user_id):
    return db.execute(
        "SELECT 1 FROM admins WHERE user_id = ?",
        (user_id,)
    ).fetchone() is not None


def is_group(update):
    return bool(
        update.effective_chat
        and update.effective_chat.type in ("group", "supergroup")
    )


def get_cards():
    return db.execute("""
        SELECT *
        FROM cards
        WHERE quantity > 0
        ORDER BY id DESC
    """).fetchall()


def card_caption(card):
    return (
        f"🃏 <b>{card['name']}</b>\n\n"
        f"⚡ قابلیت: {card['ability']}\n"
        f"👤 آپلودکننده: {card['uploader']}\n"
        f"📦 تعداد: {card['quantity']}\n"
        f"⭐ قیمت: {card['price']} ستاره"
    )


def card_keyboard(index, total):
    previous_index = (index - 1) % total
    next_index = (index + 1) % total

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "◀️ قبلی",
                callback_data=f"card_prev:{previous_index}"
            ),
            InlineKeyboardButton(
                "🛒 خرید",
                callback_data=f"card_buy:{index}"
            ),
            InlineKeyboardButton(
                "بعدی ▶️",
                callback_data=f"card_next:{next_index}"
            ),
        ]
    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    save_user(update.effective_user)

    me = await context.bot.get_me()

    keyboard = [
        [
            InlineKeyboardButton(
                "🃏 دیدن کارت‌های موجود",
                callback_data="show_cards"
            )
        ],
        [
            InlineKeyboardButton(
                "🔐 پنل ادمین",
                callback_data="open_admin"
            )
        ],
        [
            InlineKeyboardButton(
                "➕ اضافه کردن به گروه",
                url=f"https://t.me/{me.username}?startgroup=true"
            )
        ],
    ]

    await update.message.reply_text(
        "🌌✨ یه دنیای کوچیک پر از ستاره و کارت منتظرته!\n\n"
        "برای اضافه کردن من به گروه، دکمه زیر رو بزن.\n"
        "بعد از اضافه کردن، دکمه Start رو بزن.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# NORMAL COMMANDS
# =========================================================

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "/start\n"
        "/cards\n"
        "/balance\n"
        "/point\n"
        "/admin"
    )


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)

    row = db.execute("""
        SELECT stars
        FROM users
        WHERE user_id = ?
    """, (update.effective_user.id,)).fetchone()

    await update.message.reply_text(
        f"⭐ موجودی شما: {row['stars']} ستاره"
    )


async def cards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_card(update.message, 0)


# =========================================================
# CARD VIEW
# =========================================================

async def send_card(message, index=0):
    cards = get_cards()

    if not cards:
        await message.reply_text(
            "🃏 فعلاً هیچ کارتی موجود نیست."
        )
        return

    index %= len(cards)
    card = cards[index]

    await message.reply_photo(
        photo=card["image_file_id"],
        caption=card_caption(card),
        parse_mode="HTML",
        reply_markup=card_keyboard(
            index,
            len(cards)
        )
    )


async def edit_card(query, index):
    cards = get_cards()

    if not cards:
        await query.answer(
            "❌ هیچ کارتی موجود نیست.",
            show_alert=True
        )
        return

    index %= len(cards)
    card = cards[index]

    await query.message.edit_media(
        media=InputMediaPhoto(
            media=card["image_file_id"],
            caption=card_caption(card),
            parse_mode="HTML"
        ),
        reply_markup=card_keyboard(
            index,
            len(cards)
        )
    )


# =========================================================
# GROUP MENU
# =========================================================

async def group_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not is_group(update):
        return

    if (update.message.text or "").strip() != "منو":
        return

    keyboard = [
        [
            InlineKeyboardButton(
                "⭐ شکار ستاره",
                callback_data="hunt_star"
            )
        ],
        [
            InlineKeyboardButton(
                "🔭 تلسکوپ",
                callback_data="telescope"
            )
        ],
        [
            InlineKeyboardButton(
                "📦 کالکشن‌ها",
                callback_data="collection"
            )
        ],
        [
            InlineKeyboardButton(
                "🛒 خرید کارت",
                callback_data="show_cards"
            )
        ],
    ]

    await update.message.reply_text(
        "🌌 <b>منو</b>\n\n"
        "⭐ شکار ستاره — هر ۱۵ دقیقه\n"
        "🔭 تلسکوپ — هر ۲۴ ساعت\n"
        "📦 کالکشن‌ها\n"
        "🛒 خرید کارت",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# STAR REWARD
# =========================================================

async def give_star_reward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    if not is_group(update):
        return

    user = update.effective_user
    save_user(user)

    row = db.execute("""
        SELECT stars, last_star
        FROM users
        WHERE user_id = ?
    """, (user.id,)).fetchone()

    now = time.time()

    remaining = STAR_COOLDOWN - (
        now - (row["last_star"] or 0)
    )

    if remaining > 0:
        minutes = int(remaining // 60) + 1

        await update.message.reply_text(
            f"⏳ هنوز آماده نیست!\n"
            f"{minutes} دقیقه دیگه دوباره امتحان کن."
        )
        return

    reward = random.randint(2, 20)

    db.execute("""
        UPDATE users
        SET stars = stars + ?, last_star = ?
        WHERE user_id = ?
    """, (
        reward,
        now,
        user.id,
    ))

    db.commit()

    # First message: only one star emoji
    await update.message.reply_text("⭐")

    # Second message: congratulation
    await update.message.reply_text(
        f"🎉 تبریک!\n"
        f"شما {reward} ستاره دریافت کردید!"
    )


# =========================================================
# /POINT
# =========================================================

async def point_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_group(update):
        await update.message.reply_text(
            "⭐ این دستور فقط داخل گروه قابل استفاده است."
        )
        return

    await give_star_reward(update, context)


# =========================================================
# TELESCOPE
# =========================================================

async def use_telescope(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_group(update):
        await query.answer(
            "🔭 تلسکوپ فقط داخل گروه قابل استفاده است.",
            show_alert=True
        )
        return

    await query.answer()

    user = query.from_user
    save_user(user)

    row = db.execute("""
        SELECT last_telescope
        FROM users
        WHERE user_id = ?
    """, (user.id,)).fetchone()

    now = time.time()

    remaining = TELESCOPE_COOLDOWN - (
        now - (row["last_telescope"] or 0)
    )

    if remaining > 0:
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)

        await query.message.reply_text(
            f"⏳ تلسکوپ هنوز آماده نیست.\n"
            f"{hours} ساعت و {minutes} دقیقه دیگه."
        )
        return

    # Probability:
    # 2%   -> planet = 1000
    # 20%  -> comet = 100
    # 78%  -> small stars = 50

    chance = random.random()

    if chance < 0.02:
        result = "🪐 سیاره"
        reward = 1000

    elif chance < 0.22:
        result = "☄️ ستاره دنباله‌دار"
        reward = 100

    else:
        result = "✨ ستاره‌های کوچولو"
        reward = 50

    db.execute("""
        UPDATE users
        SET stars = stars + ?, last_telescope = ?
        WHERE user_id = ?
    """, (
        reward,
        now,
        user.id,
    ))

    db.commit()

    total = db.execute("""
        SELECT stars
        FROM users
        WHERE user_id = ?
    """, (user.id,)).fetchone()["stars"]

    await query.message.reply_text(
        f"🔭 <b>تلسکوپ!</b>\n\n"
        f"{result} پیدا کردی!\n"
        f"💰 ارزش: {reward} ⭐\n"
        f"⭐ موجودی: {total}",
        parse_mode="HTML"
    )


# =========================================================
# COLLECTION
# =========================================================

async def show_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not is_group(update):
        await query.answer(
            "📦 کالکشن فقط داخل گروه قابل استفاده است.",
            show_alert=True
        )
        return

    await query.answer()

    user = query.from_user
    save_user(user)

    stars = db.execute("""
        SELECT stars
        FROM users
        WHERE user_id = ?
    """, (user.id,)).fetchone()["stars"]

    owned_cards = db.execute("""
        SELECT
            c.id,
            c.name,
            COUNT(*) AS count
        FROM owned_cards o
        JOIN cards c ON c.id = o.card_id
        WHERE o.user_id = ?
        GROUP BY c.id, c.name
        ORDER BY c.id DESC
    """, (user.id,)).fetchall()

    text = (
        f"📦 <b>کالکشن شما</b>\n\n"
        f"⭐ ستاره‌ها: {stars}\n\n"
        f"🃏 <b>کارت‌ها:</b>\n"
    )

    if owned_cards:
        text += "\n".join(
            f"• {card['name']} × {card['count']}"
            for card in owned_cards
        )
    else:
        text += "• هنوز هیچ کارتی نداری."

    keyboard = [
        [
            InlineKeyboardButton(
                "💰 فروش کارت",
                callback_data="sell_menu"
            )
        ],
        [
            InlineKeyboardButton(
                "🛒 خرید کارت",
                callback_data="show_cards"
            )
        ],
    ]

    await query.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# SELL MENU
# =========================================================

async def show_sell_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    save_user(user)

    rows = db.execute("""
        SELECT
            c.id,
            c.name,
            COUNT(*) AS count
        FROM owned_cards o
        JOIN cards c ON c.id = o.card_id
        WHERE o.user_id = ?
        GROUP BY c.id, c.name
        ORDER BY c.id DESC
    """, (user.id,)).fetchall()

    if not rows:
        await query.message.reply_text(
            "❌ هنوز کارتی نداری."
        )
        return

    keyboard = []

    for row in rows:
        keyboard.append([
            InlineKeyboardButton(
                f"💰 فروش {row['name']} ×{row['count']}",
                callback_data=f"sell:{row['id']}"
            )
        ])

    await query.message.reply_text(
        "🃏 کارت موردنظر برای فروش را انتخاب کن:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# SELL CARD
# =========================================================

async def sell_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    try:
        card_id = int(
            query.data.split(":")[1]
        )
    except Exception:
        return

    user = query.from_user
    save_user(user)

    owned = db.execute("""
        SELECT id
        FROM owned_cards
        WHERE user_id = ? AND card_id = ?
        ORDER BY id
        LIMIT 1
    """, (
        user.id,
        card_id,
    )).fetchone()

    card = db.execute("""
        SELECT name, price
        FROM cards
        WHERE id = ?
    """, (card_id,)).fetchone()

    if not owned or not card:
        await query.answer(
            "❌ این کارت را نداری.",
            show_alert=True
        )
        return

    # Half of purchase price
    sell_price = max(
        1,
        card["price"] // 2
    )

    db.execute("""
        DELETE FROM owned_cards
        WHERE id = ?
    """, (owned["id"],))

    db.execute("""
        UPDATE users
        SET stars = stars + ?
        WHERE user_id = ?
    """, (
        sell_price,
        user.id,
    ))

    db.commit()

    await query.message.reply_text(
        f"✅ کارت «{card['name']}» فروخته شد.\n\n"
        f"💰 +{sell_price} ⭐"
    )


# =========================================================
# BUY CARD
# =========================================================

async def buy_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    try:
        index = int(
            query.data.split(":")[1]
        )
    except Exception:
        await query.answer(
            "❌ خطا",
            show_alert=True
        )
        return

    cards = get_cards()

    if not cards:
        await query.answer(
            "❌ هیچ کارتی موجود نیست.",
            show_alert=True
        )
        return

    index %= len(cards)

    card_id = cards[index]["id"]

    user = query.from_user
    save_user(user)

    card = db.execute("""
        SELECT *
        FROM cards
        WHERE id = ?
    """, (card_id,)).fetchone()

    if not card or card["quantity"] <= 0:
        await query.answer(
            "❌ این کارت دیگر موجود نیست.",
            show_alert=True
        )
        return

    stars = db.execute("""
        SELECT stars
        FROM users
        WHERE user_id = ?
    """, (user.id,)).fetchone()["stars"]

    if stars < card["price"]:
        await query.answer(
            f"❌ ستاره کافی نیست.\n"
            f"موجودی: {stars} ⭐",
            show_alert=True
        )
        return

    now = time.time()

    # Spend stars
    db.execute("""
        UPDATE users
        SET stars = stars - ?
        WHERE user_id = ?
    """, (
        card["price"],
        user.id,
    ))

    # Decrease stock
    db.execute("""
        UPDATE cards
        SET quantity = quantity - 1
        WHERE id = ? AND quantity > 0
    """, (card_id,))

    # Purchase history
    db.execute("""
        INSERT INTO purchases
        (user_id, card_id, code, purchased_at)
        VALUES (?, ?, ?, ?)
    """, (
        user.id,
        card_id,
        card["code"],
        now,
    ))

    # Add to user's collection
    db.execute("""
        INSERT INTO owned_cards
        (user_id, card_id, code, purchased_at)
        VALUES (?, ?, ?, ?)
    """, (
        user.id,
        card_id,
        card["code"],
        now,
    ))

    db.commit()

    remaining_stars = db.execute("""
        SELECT stars
        FROM users
        WHERE user_id = ?
    """, (user.id,)).fetchone()["stars"]

    await query.answer(
        "✅ خرید موفق!",
        show_alert=True
    )

    remaining_cards = get_cards()

    # No cards left
    if not remaining_cards:
        try:
            await query.message.edit_caption(
                caption=(
                    f"✅ <b>خرید موفق!</b>\n\n"
                    f"🃏 کارت: {card['name']}\n"
                    f"🔑 کد: {card['code']}\n"
                    f"⭐ هزینه: {card['price']}\n"
                    f"💰 موجودی: {remaining_stars} ⭐\n\n"
                    f"❌ دیگر کارتی موجود نیست."
                ),
                parse_mode="HTML",
                reply_markup=None
            )
        except Exception:
            pass

        return

    new_index = min(
        index,
        len(remaining_cards) - 1
    )

    new_card = remaining_cards[new_index]

    try:
        await query.message.edit_media(
            media=InputMediaPhoto(
                media=new_card["image_file_id"],
                caption=(
                    card_caption(new_card)
                    + f"\n\n💰 موجودی شما: {remaining_stars} ⭐"
                ),
                parse_mode="HTML"
            ),
            reply_markup=card_keyboard(
                new_index,
                len(remaining_cards)
            )
        )
    except Exception:
        pass


# =========================================================
# ADMIN
# =========================================================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)

    if is_admin(update.effective_user.id):
        await show_admin_panel(
            update,
            context
        )
        return

    pending_admin[
        update.effective_user.id
    ] = True

    await update.message.reply_text(
        "🔐 رمز عبور پنل ادمین را وارد کنید:"
    )


async def show_admin_panel(update, context):
    keyboard = [
        [
            InlineKeyboardButton(
                "➕ افزودن کارت",
                callback_data="admin_add"
            )
        ],
        [
            InlineKeyboardButton(
                "🃏 لیست کارت‌ها",
                callback_data="admin_list"
            )
        ],
        [
            InlineKeyboardButton(
                "📊 آمار",
                callback_data="admin_stats"
            )
        ],
    ]

    text = "🔐 <b>پنل ادمین</b>"

    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except Exception:
            await update.callback_query.message.reply_text(
                text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    else:
        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


# =========================================================
# ADMIN PHOTO
# =========================================================

async def admin_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    uid = user.id

    if not is_admin(uid):
        return

    if uid not in add_flow:
        return

    if add_flow[uid]["step"] != "image":
        return

    add_flow[uid]["image"] = (
        update.message.photo[-1].file_id
    )

    add_flow[uid]["step"] = "name"

    await update.message.reply_text(
        "📝 نام کارت:"
    )


# =========================================================
# ADMIN TEXT
# =========================================================

async def admin_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    uid = user.id

    text = update.message.text or ""

    # -----------------------------------------
    # Admin password
    # -----------------------------------------

    if pending_admin.get(uid):

        pending_admin.pop(uid, None)

        if text == ADMIN_PASSWORD:

            db.execute("""
                INSERT OR IGNORE INTO admins(user_id)
                VALUES (?)
            """, (uid,))

            db.commit()

            await update.message.reply_text(
                "✅ رمز صحیح است."
            )

            await show_admin_panel(
                update,
                context
            )

        else:
            await update.message.reply_text(
                "❌ رمز اشتباه است."
            )

        return

    # -----------------------------------------
    # Add card flow
    # -----------------------------------------

    if uid not in add_flow:
        return

    if not is_admin(uid):
        add_flow.pop(uid, None)
        return

    data = add_flow[uid]
    step = data["step"]

    if step == "name":

        data["name"] = text
        data["step"] = "ability"

        await update.message.reply_text(
            "⚡ قابلیت کاراکتر:"
        )

    elif step == "ability":

        data["ability"] = text
        data["step"] = "uploader"

        await update.message.reply_text(
            "👤 آپلودکننده:"
        )

    elif step == "uploader":

        data["uploader"] = text
        data["step"] = "quantity"

        await update.message.reply_text(
            "📦 تعداد:"
        )

    elif step == "quantity":

        try:
            quantity = int(text)

            if quantity < 1:
                raise ValueError

        except ValueError:

            await update.message.reply_text(
                "❌ تعداد باید عدد صحیح بزرگ‌تر از صفر باشد."
            )
            return

        data["quantity"] = quantity
        data["step"] = "code"

        await update.message.reply_text(
            "🔑 کد کارت:"
        )

    elif step == "code":

        data["code"] = text
        data["step"] = "price"

        await update.message.reply_text(
            "⭐ قیمت کارت به ستاره:"
        )

    elif step == "price":

        try:
            price = int(text)

            if price < 0:
                raise ValueError

        except ValueError:

            await update.message.reply_text(
                "❌ قیمت باید عدد باشد."
            )
            return

        data["price"] = price

        db.execute("""
            INSERT INTO cards(
                image_file_id,
                name,
                ability,
                uploader,
                quantity,
                code,
                price
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data["image"],
            data["name"],
            data["ability"],
            data["uploader"],
            data["quantity"],
            data["code"],
            data["price"],
        ))

        db.commit()

        add_flow.pop(uid, None)

        await update.message.reply_text(
            "✅ کارت با موفقیت اضافه شد."
        )

        await show_admin_panel(
            update,
            context
        )


# =========================================================
# CALLBACKS
# =========================================================

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    uid = query.from_user.id

    # -----------------------------------------
    # ADMIN OPEN
    # -----------------------------------------

    if data == "open_admin":

        await query.answer()

        if is_admin(uid):

            await show_admin_panel(
                update,
                context
            )

        else:

            pending_admin[uid] = True

            await query.message.reply_text(
                "🔐 رمز عبور پنل ادمین را وارد کنید:"
            )

        return

    # -----------------------------------------
    # SHOW CARDS
    # -----------------------------------------

    if data == "show_cards":

        await query.answer()

        await send_card(
            query.message,
            0
        )

        return

    # -----------------------------------------
    # PREVIOUS
    # -----------------------------------------

    if data.startswith("card_prev:"):

        await query.answer()

        try:
            index = int(
                data.split(":")[1]
            )
        except Exception:
            return

        await edit_card(
            query,
            index
        )

        return

    # -----------------------------------------
    # NEXT
    # -----------------------------------------

    if data.startswith("card_next:"):

        await query.answer()

        try:
            index = int(
                data.split(":")[1]
            )
        except Exception:
            return

        await edit_card(
            query,
            index
        )

        return

    # -----------------------------------------
    # BUY
    # -----------------------------------------

    if data.startswith("card_buy:"):

        await buy_card(
            update,
            context
        )

        return

    # -----------------------------------------
    # HUNT STAR
    # -----------------------------------------

    if data == "hunt_star":

        await query.answer()

        if not is_group(update):

            await query.message.reply_text(
                "⭐ فقط داخل گروه قابل استفاده است."
            )
            return

        user = query.from_user
        save_user(user)

        row = db.execute("""
            SELECT stars,last_star
            FROM users
            WHERE user_id = ?
        """, (user.id,)).fetchone()

        now = time.time()

        remaining = STAR_COOLDOWN - (
            now - (row["last_star"] or 0)
        )

        if remaining > 0:

            minutes = int(
                remaining // 60
            ) + 1

            await query.message.reply_text(
                f"⏳ شکار ستاره هنوز آماده نیست.\n"
                f"{minutes} دقیقه دیگه."
            )
            return

        reward = random.randint(
            2,
            20
        )

        db.execute("""
            UPDATE users
            SET stars = stars + ?, last_star = ?
            WHERE user_id = ?
        """, (
            reward,
            now,
            user.id,
        ))

        db.commit()

        await query.message.reply_text(
            "⭐"
        )

        await query.message.reply_text(
            f"🎉 تبریک!\n"
            f"شما {reward} ستاره دریافت کردید!"
        )

        return

    # -----------------------------------------
    # TELESCOPE
    # -----------------------------------------

    if data == "telescope":

        await use_telescope(
            update,
            context
        )

        return

    # -----------------------------------------
    # COLLECTION
    # -----------------------------------------

    if data == "collection":

        await show_collection(
            update,
            context
        )

        return

    # -----------------------------------------
    # SELL MENU
    # -----------------------------------------

    if data == "sell_menu":

        await show_sell_menu(
            update,
            context
        )

        return

    # -----------------------------------------
    # SELL
    # -----------------------------------------

    if data.startswith("sell:"):

        await sell_card(
            update,
            context
        )

        return

    # -----------------------------------------
    # ADMIN ADD
    # -----------------------------------------

    if data == "admin_add":

        await query.answer()

        if not is_admin(uid):

            await query.message.reply_text(
                "⛔ دسترسی ندارید."
            )
            return

        add_flow[uid] = {
            "step": "image"
        }

        await query.edit_message_text(
            "📸 عکس کارت را ارسال کنید."
        )

        return

    # -----------------------------------------
    # ADMIN LIST
    # -----------------------------------------

    if data == "admin_list":

        await query.answer()

        if not is_admin(uid):

            await query.message.reply_text(
                "⛔ دسترسی ندارید."
            )
            return

        rows = db.execute("""
            SELECT
                id,
                name,
                quantity,
                price,
                code
            FROM cards
            ORDER BY id DESC
        """).fetchall()

        if not rows:

            await query.edit_message_text(
                "🃏 هیچ کارتی ثبت نشده."
            )
            return

        text = "🃏 <b>لیست کارت‌ها</b>\n\n"

        for row in rows:

            text += (
                f"#{row['id']} — {row['name']}\n"
                f"📦 تعداد: {row['quantity']}\n"
                f"⭐ قیمت: {row['price']}\n"
                f"🔑 کد: {row['code']}\n\n"
            )

        await query.edit_message_text(
            text,
            parse_mode="HTML"
        )

        return

    # -----------------------------------------
    # ADMIN STATS
    # -----------------------------------------

    if data == "admin_stats":

        await query.answer()

        if not is_admin(uid):

            await query.message.reply_text(
                "⛔ دسترسی ندارید."
            )
            return

        users = db.execute(
            "SELECT COUNT(*) FROM users"
        ).fetchone()[0]

        card_count = db.execute(
            "SELECT COUNT(*) FROM cards"
        ).fetchone()[0]

        purchases = db.execute(
            "SELECT COUNT(*) FROM purchases"
        ).fetchone()[0]

        stars = db.execute(
            "SELECT COALESCE(SUM(stars), 0) FROM users"
        ).fetchone()[0]

        await query.edit_message_text(
            f"📊 <b>آمار</b>\n\n"
            f"👥 کاربران: {users}\n"
            f"🃏 کارت‌ها: {card_count}\n"
            f"🛒 خریدها: {purchases}\n"
            f"⭐ مجموع ستاره‌ها: {stars}",
            parse_mode="HTML"
        )

        return

    await query.answer()


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("ERROR:", repr(context.error))


# =========================================================
# MAIN
# =========================================================

def main():

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # Commands
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CommandHandler(
            "cards",
            cards_command
        )
    )

    app.add_handler(
        CommandHandler(
            "balance",
            balance_command
        )
    )

    app.add_handler(
        CommandHandler(
            "point",
            point_command
        )
    )

    app.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    # All buttons
    app.add_handler(
        CallbackQueryHandler(
            callbacks
        )
    )

    # Admin image upload
    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            admin_photo
        )
    )

    # Group menu
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.Regex(r"^\s*منو\s*$"),
            group_menu
        )
    )

    # "sta" in groups
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND
            & filters.Regex(
                r"^\s*sta\s*$"
            ),
            lambda update, context: give_star_reward(
                update,
                context
            )
        )
    )

    # Admin password + card fields
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            admin_text
        )
    )

    app.add_error_handler(
        error_handler
    )

    print("Bot is running...")

    app.run_polling()


if __name__ == "__main__":
    main()