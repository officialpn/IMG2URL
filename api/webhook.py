import os
import logging
import base64
import asyncio
import requests
from upstash_redis import Redis

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    filters,
    ContextTypes,
)

# ────────── CONFIG ──────────
BOT_TOKEN     = os.environ.get("BOT_TOKEN")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY")
ADMIN_ID      = int(os.environ.get("ADMIN_ID", "0"))
WEBHOOK_URL   = os.environ.get("WEBHOOK_URL")   # e.g. https://your-app.vercel.app
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "supersecret")

redis = Redis(
    url=os.environ["UPSTASH_REDIS_REST_URL"],
    token=os.environ["UPSTASH_REDIS_REST_TOKEN"],
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ────────── REDIS HELPERS ──────────
USERS_KEY = "bot:user_ids"
BCAST_KEY = "bot:broadcast_mode"

def add_user(uid: int):
    try:
        redis.sadd(USERS_KEY, str(uid))
    except Exception as e:
        logger.warning(f"redis add_user fail: {e}")

def get_users():
    try:
        return [int(x) for x in (redis.smembers(USERS_KEY) or [])]
    except Exception:
        return []

def set_broadcast(uid: int, on: bool):
    try:
        if on: redis.sadd(BCAST_KEY, str(uid))
        else:  redis.srem(BCAST_KEY, str(uid))
    except Exception as e:
        logger.warning(f"redis set_broadcast fail: {e}")

def is_broadcasting(uid: int) -> bool:
    try:
        return redis.sismember(BCAST_KEY, str(uid))
    except Exception:
        return False

# ────────── STYLISH FONT ──────────
SMALL_CAPS = {
    "a":"ᴀ","b":"ʙ","c":"ᴄ","d":"ᴅ","e":"ᴇ","f":"ꜰ","g":"ɢ","h":"ʜ",
    "i":"ɪ","j":"ᴊ","k":"ᴋ","l":"ʟ","m":"ᴍ","n":"ɴ","o":"ᴏ","p":"ᴘ",
    "q":"ǫ","r":"ʀ","s":"ꜱ","t":"ᴛ","u":"ᴜ","v":"ᴠ","w":"ᴡ","x":"x",
    "y":"ʏ","z":"ᴢ",
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

def norm(t: str) -> str:
    reverse = {v: k for k, v in SMALL_CAPS.items()}
    out = ""
    for ch in t:
        out += reverse.get(ch, ch.lower())
    return out.lower().strip()

# ────────── KEYBOARDS ──────────
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

# ────────── HANDLERS ──────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id)
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
    await update.message.reply_text(s("Use the buttons below 👇"),
                                    reply_markup=main_keyboard(is_admin))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    add_user(user.id)
    is_admin = user.id == ADMIN_ID
    cmd = norm(text)

    # ───── Broadcast flow ─────
    if is_broadcasting(user.id):
        if cmd == "cancel":
            set_broadcast(user.id, False)
            await update.message.reply_text(s("Broadcast cancelled."),
                                            reply_markup=main_keyboard(is_admin))
            return

        users = get_users()
        success, failed = 0, 0
        status_msg = await update.message.reply_text(s(f"Sending to {len(users)} users..."))

        for uid in users:
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
        await update.message.reply_text(s("Back to menu 👇"),
                                        reply_markup=main_keyboard(is_admin))
        return

    # ───── Menu ─────
    if cmd in ["upload photo", "upload", "photo"]:
        await update.message.reply_text(
            f"📸 <b>{s('Send me a photo')}</b>\n"
            f"<i>{s('I will convert it into a direct link.')}</i>",
            parse_mode="HTML",
        )
    elif cmd == "help":
        await update.message.reply_text(
            f"📖 <b>{s('Help Menu')}</b>\n\n"
            f"• {s('Send a photo')} → {s('Get a link')}\n"
            f"• {s('Use buttons below')}\n\n"
            f"💡 <i>{s('Tip: High quality photos = best results')}</i>",
            parse_mode="HTML",
        )
    elif cmd == "about":
        await update.message.reply_text(
            f"ℹ️ <b>{s('About This Bot')}</b>\n\n"
            f"🤖 <b>{s('Name')}:</b> {s('Photo Link Bot')}\n"
            f"👨‍💻 <b>{s('Developer')}:</b> @PR4MOD_DM_bot\n"
            f"🚀 <b>{s('Hosting')}:</b> Vᴇʀᴄᴇʟ + Iᴍɢʙʙ\n"
            f"🌐 <b>{s('Language')}:</b> Pʏᴛʜᴏɴ\n\n"
            f"<i>{s('Made with love')} ❤️</i>",
            parse_mode="HTML",
        )
    elif cmd == "broadcast" and is_admin:
        set_broadcast(user.id, True)
        await update.message.reply_text(
            f"📢 <b>{s('Broadcast Mode')}</b>\n\n"
            f"{s('Send any message or photo')}\n"
            f"{s('It will be sent to all users')}\n\n"
            f"<i>{s('Tap Cancel button to cancel')}</i>",
            parse_mode="HTML",
            reply_markup=cancel_keyboard(),
        )
    elif cmd == "cancel":
        await update.message.reply_text(s("Nothing to cancel."),
                                        reply_markup=main_keyboard(is_admin))


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id)
    is_admin = user.id == ADMIN_ID

    if is_broadcasting(user.id):
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
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(s("Open Link"), url=direct_link)]])
        await update.message.reply_photo(photo=thumb, caption=caption,
                                         parse_mode="HTML", reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(
            f"❌ <b>{s('Oops! Something went wrong')}.</b>\n"
            f"<i>{s('Please try again in a moment')}.</i>",
            parse_mode="HTML",
            reply_markup=main_keyboard(is_admin),
        )

# ────────── APP (build once per cold start) ──────────
_app = None

def get_app() -> Application:
    global _app
    if _app is None:
        _app = Application.builder().token(BOT_TOKEN).updater(None).build()
        _app.add_handler(CommandHandler("start", start))
        _app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
        _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return _app

# ────────── VERCEL ENTRY POINT ──────────
from http.server import BaseHTTPRequestHandler
import json

class handler(BaseHTTPRequestHandler):
    def _process(self, body: bytes):
        try:
            update = Update.de_json(json.loads(body.decode("utf-8")), get_app().bot)
            asyncio.run(get_app().process_update(update))
        except Exception as e:
            logger.exception(f"process_update failed: {e}")

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self._process(body)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_GET(self):
        # Setup webhook on first GET
        try:
            url = f"{WEBHOOK_URL}/api/webhook"
            requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                params={"url": url, "secret_token": WEBHOOK_SECRET},
                timeout=15,
            ).json()
        except Exception as e:
            logger.exception(e)
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive")
