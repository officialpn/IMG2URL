import os
import json
import base64
import asyncio
import logging
from http.server import BaseHTTPRequestHandler
from datetime import datetime

import requests
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes,
)

# ───── CONFIG ─────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY", "d3a64cfd0fbdc79f28c37704ce6677f2")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
DATABASE_URL = os.environ.get("DATABASE_URL", "")
HAS_DB = bool(DATABASE_URL)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ───── DATABASE (Postgres) ─────
def get_db():
    import psycopg2
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    if not HAS_DB: return
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS plb_users (
            user_id BIGINT PRIMARY KEY, username TEXT,
            first_name TEXT, joined_date TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS plb_broadcast (
            user_id BIGINT PRIMARY KEY, active BOOLEAN)""")
        conn.commit(); conn.close()
    except Exception as e:
        logger.error(f"init_db: {e}")

def add_user(uid, uname, fname):
    if not HAS_DB: return
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("""INSERT INTO plb_users (user_id, username, first_name, joined_date)
                     VALUES (%s,%s,%s,%s) ON CONFLICT (user_id) DO NOTHING""",
                  (uid, uname, fname, datetime.now().isoformat()))
        conn.commit(); conn.close()
    except Exception as e:
        logger.error(f"add_user: {e}")

def get_all_users():
    if not HAS_DB: return []
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT user_id FROM plb_users")
        rows = [r[0] for r in c.fetchall()]; conn.close()
        return rows
    except Exception as e:
        logger.error(f"get_all_users: {e}"); return []

def set_broadcast(uid, active):
    if not HAS_DB: return
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("""INSERT INTO plb_broadcast (user_id, active) VALUES (%s,%s)
                     ON CONFLICT (user_id) DO UPDATE SET active=%s""",
                  (uid, active, active))
        conn.commit(); conn.close()
    except Exception as e:
        logger.error(f"set_broadcast: {e}")

def is_broadcasting(uid):
    if not HAS_DB: return False
    try:
        conn = get_db(); c = conn.cursor()
        c.execute("SELECT active FROM plb_broadcast WHERE user_id=%s", (uid,))
        r = c.fetchone(); conn.close()
        return bool(r[0]) if r else False
    except: return False

init_db()

# ───── STYLISH FONT ─────
SMALL_CAPS = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ",
    "g": "ɢ", "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ",
    "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ", "q": "ǫ", "r": "ʀ",
    "s": "ꜱ", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x",
    "y": "ʏ", "z": "ᴢ",
}

def s(text: str) -> str:
    result = []
    for word in text.split(" "):
        if not word:
            result.append(word); continue
        first = word[0].upper()
        rest = "".join(SMALL_CAPS.get(c.lower(), c) for c in word[1:])
        result.append(first + rest)
    return " ".join(result)

# ───── KEYBOARDS ─────
def main_keyboard(is_admin: bool = False):
    buttons = [
        [KeyboardButton(s("Upload Photo")), KeyboardButton(s("Help"))],
        [KeyboardButton(s("About"))],
    ]
    if is_admin:
        buttons.insert(2, [KeyboardButton(s("Broadcast"))])
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True, one_time_keyboard=False)

def cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton(s("Cancel"))]], resize_keyboard=True)

# ───── HANDLERS ─────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username or "", user.first_name or "")
    is_admin = user.id == ADMIN_ID

    text = (
        f"👋 <b>{s('Hey')} {user.first_name}!</b>\n\n"
        f"✨ <b>{s('Photo Link Bot')}</b> ✨\n\n"
        f"📸 <b>{s('How to use')}:</b>\n"
        f"• {s('Send me any photo')}\n"
        f"• {s('I will give you a direct link')}\n\n"
        f"🚀 <i>{s('Powered by ImgBB')}</i>"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(s("Channel"), url="https://t.me/+8_c74E2vC8llOTJl")]
    ])
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)
    await update.message.reply_text(s("Use the buttons below 👇"), reply_markup=main_keyboard(is_admin))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    add_user(user.id, user.username or "", user.first_name or "")
    is_admin = user.id == ADMIN_ID

    def norm(t):
        reverse = {v: k for k, v in SMALL_CAPS.items()}
        out = ""
        for ch in t:
            out += reverse.get(ch, ch.lower())
        return out.lower().strip()

    cmd = norm(text)

    # ───── Broadcast Flow ─────
    if user.id == ADMIN_ID and is_broadcasting(user.id):
        if cmd == "cancel":
            set_broadcast(user.id, False)
            await update.message.reply_text(
                s("Broadcast cancelled."), reply_markup=main_keyboard(is_admin)
            )
            return

        user_list = get_all_users()
        success, failed = 0, 0
        status_msg = await update.message.reply_text(
            s(f"Sending to {len(user_list)} users...")
        )

        for uid in user_list:
            try:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=update.effective_chat.id,
                    message_id=update.message.message_id,
                )
                success += 1
                await asyncio.sleep(0.05)
            except Exception as e:
                failed += 1
                logger.warning(f"Broadcast failed for {uid}: {e}")

        set_broadcast(user.id, False)
        await status_msg.edit_text(
            f"✅ <b>{s('Broadcast Complete')}</b>\n\n"
            f"✔ {s('Sent')}: <b>{success}</b>\n"
            f"✖ {s('Failed')}: <b>{failed}</b>",
            parse_mode="HTML",
        )
        await update.message.reply_text(s("Back to menu 👇"), reply_markup=main_keyboard(is_admin))
        return

    # ───── Menu Buttons ─────
    if cmd in ["upload photo", "upload", "photo"]:
        await update.message.reply_text(
            f"📸 <b>{s('Send me a photo')}</b>\n"
            f"<i>{s('I will convert it into a direct link.')}</i>",
            parse_mode="HTML",
        )

    elif cmd == "help":
        help_text = (
            f"📖 <b>{s('Help Menu')}</b>\n\n"
            f"• {s('Send a photo')} → {s('Get a link')}\n"
            f"• {s('Use buttons below')}\n\n"
            f"💡 <i>{s('Tip: High quality photos = best results')}</i>"
        )
        await update.message.reply_text(help_text, parse_mode="HTML")

    elif cmd == "about":
        about_text = (
            f"ℹ️ <b>{s('About This Bot')}</b>\n\n"
            f"🤖 <b>{s('Name')}:</b> {s('Photo Link Bot')}\n"
            f"👨‍💻 <b>{s('Developer')}:</b> @PR4MOD_DM_bot\n"
            f"🚀 <b>{s('Hosting')}:</b> Iᴍɢʙʙɪᴍɢʙʙ Aᴘɪ\n"
            f"🌐 <b>{s('Language')}:</b> Pʏᴛʜᴏɴ\n\n"
            f"<i>{s('Made with love')} ❤️</i>"
        )
        await update.message.reply_text(about_text, parse_mode="HTML")

    elif cmd == "broadcast" and is_admin:
        set_broadcast(user.id, True)
        await update.message.reply_text(
            f"📢 <b>{s('Broadcast Mode')}</b>\n\n"
            f"{s('Send any message or photo')}\n"
            f"{s('It will be sent to all users')}\n\n"
            f"<i>{s('Send')} {s('Cancel')} {s('to cancel')}</i>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )

    elif cmd == "cancel":
        await update.message.reply_text(
            s("Nothing to cancel."), reply_markup=main_keyboard(is_admin)
        )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username or "", user.first_name or "")
    is_admin = user.id == ADMIN_ID

    # Admin broadcasting → treat photo as broadcast
    if user.id == ADMIN_ID and is_broadcasting(user.id):
        return await handle_text(update, context)

    try:
        loading = await update.message.reply_text(
            f"⏳ <b>{s('Processing')}...</b>\n"
            f"<i>{s('Uploading your photo')}...</i>",
            parse_mode="HTML",
        )

        photo = update.message.photo[-1]
        tg_file = await context.bot.get_file(photo.file_id)
        file_bytes = await tg_file.download_as_bytearray()
        base64_image = base64.b64encode(file_bytes).decode("utf-8")

        response = requests.post(
            f"https://api.imgbb.com/1/upload?key={IMGBB_API_KEY}",
            data={"image": base64_image},
            timeout=30,
        )
        result = response.json()

        if not result.get("success"):
            raise Exception("ImgBB upload failed")

        data = result["data"]
        direct_link = data["url"]
        thumb = data.get("thumb", {}).get("url", data["display_url"])
        size_kb = data["size"] / 1024
        ext = data["image"]["extension"].upper()
        width, height = data["width"], data["height"]

        await loading.delete()

        caption = (
            f"✅ <b>{s('Upload Successful')}!</b>\n\n"
            f"🔗 <b>{s('Direct Link')}:</b>\n<code>{direct_link}</code>\n\n"
            f"📊 <b>{s('Size')}:</b> {size_kb:.2f} KB\n"
            f"🖼 <b>{s('Format')}:</b> {ext}\n"
            f"📐 <b>{s('Dimensions')}:</b> {width}x{height}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(s("Open Link"), url=direct_link)]
        ])
        await update.message.reply_photo(
            photo=thumb, caption=caption,
            parse_mode="HTML", reply_markup=keyboard,
        )

    except Exception as e:
        logger.error(f"Photo error: {e}", exc_info=True)
        await update.message.reply_text(
            f"❌ <b>{s('Oops! Something went wrong')}.</b>\n"
            f"<i>{s('Please try again in a moment')}.</i>",
            parse_mode="HTML",
            reply_markup=main_keyboard(is_admin),
        )


# ───── APP (persistent across warm invocations) ─────
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)
_app = None


async def _get_app():
    global _app
    if _app is None:
        _app = Application.builder().token(BOT_TOKEN).build()
        _app.add_handler(CommandHandler("start", start))
        _app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        await _app.initialize()
        logger.info("Application initialized.")
    return _app


async def _process_update(update_data):
    app = await _get_app()
    update = Update.de_json(update_data, app.bot)
    await app.process_update(update)


# ───── VERCEL HANDLER ─────
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body.decode("utf-8"))
            _loop.run_until_complete(_process_update(data))
        except Exception as e:
            logger.error(f"handler POST error: {e}", exc_info=True)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Photo Link Bot is running!")
