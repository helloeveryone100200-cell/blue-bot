import os
import re
import time
import json
import threading
from datetime import date
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
from types import SimpleNamespace
from urllib.parse import urlparse

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from pymongo import MongoClient

def h(s):
    """Escape HTML special characters in dynamic content."""
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

# ─── CONFIGURATION (set these as environment variables on Render) ─────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
MONGO_URI      = os.environ.get("MONGO_URI", "YOUR_MONGODB_URI")
_owner_ids_env = os.environ.get("OWNER_IDS") or os.environ.get("OWNER_ID")
if not _owner_ids_env:
    raise RuntimeError("OWNER_IDS environment variable is not set.")
OWNER_IDS = {int(x.strip()) for x in _owner_ids_env.split(",") if x.strip()}
if not OWNER_IDS:
    raise RuntimeError("OWNER_IDS contains no valid IDs.")
# ─── MONGODB SETUP ────────────────────────────────────────────────────────────
client   = MongoClient(MONGO_URI)
db       = client["BlueBotDB"]
users    = db["users"]
videos   = db["videos"]
settings = db["settings"]

def ensure_video_counter():
    if settings.find_one({"_id": "video_counter"}) is None:
        settings.insert_one({"_id": "video_counter", "count": 0})

def ensure_z_video_counter():
    if settings.find_one({"_id": "z_video_counter"}) is None:
        settings.insert_one({"_id": "z_video_counter", "count": 0})

ensure_video_counter()
ensure_z_video_counter()

def ensure_photo_counter():
    if settings.find_one({"_id": "photo_counter"}) is None:
        settings.insert_one({"_id": "photo_counter", "count": 0})

def ensure_z_photo_counter():
    if settings.find_one({"_id": "z_photo_counter"}) is None:
        settings.insert_one({"_id": "z_photo_counter", "count": 0})

ensure_photo_counter()
ensure_z_photo_counter()

def get_broadcast_new_video() -> bool:
    """Return True if auto-broadcast of new public videos is enabled (default: on)."""
    doc = settings.find_one({"_id": "broadcast_new_video"})
    return doc.get("enabled", True) if doc else True

def set_broadcast_new_video(enabled: bool):
    settings.update_one(
        {"_id": "broadcast_new_video"},
        {"$set": {"enabled": enabled}},
        upsert=True
    )


def get_admin_group_id():
    """Return the designated admin group ID stored in MongoDB, or None if not set."""
    doc = settings.find_one({"_id": "admin_group"})
    return doc["chat_id"] if doc else None

def set_admin_group_id(chat_id: int):
    settings.update_one(
        {"_id": "admin_group"},
        {"$set": {"chat_id": chat_id}},
        upsert=True
    )

def get_private_admin_group_id():
    """Return the private admin group ID stored in MongoDB, or None if not set."""
    doc = settings.find_one({"_id": "private_admin_group"})
    return doc["chat_id"] if doc else None

def set_private_admin_group_id(chat_id: int):
    settings.update_one(
        {"_id": "private_admin_group"},
        {"$set": {"chat_id": chat_id}},
        upsert=True
    )

def get_accepted_user_ids() -> set:
    """Return set of user IDs accepted for the private group."""
    doc = settings.find_one({"_id": "accepted_users"})
    return set(doc["ids"]) if doc else set()

def accept_user(user_id: int):
    settings.update_one(
        {"_id": "accepted_users"},
        {"$addToSet": {"ids": user_id}},
        upsert=True
    )

def remove_accepted_user(user_id: int):
    settings.update_one(
        {"_id": "accepted_users"},
        {"$pull": {"ids": user_id}}
    )

def is_user_accepted(user_id: int) -> bool:
    if user_id in OWNER_IDS:
        return True
    ids = get_accepted_user_ids()
    return user_id in ids

def get_total_z_videos():
    counter = settings.find_one({"_id": "z_video_counter"})
    return counter["count"] if counter else 0

def get_total_photos():
    counter = settings.find_one({"_id": "photo_counter"})
    return counter["count"] if counter else 0

def get_total_z_photos():
    counter = settings.find_one({"_id": "z_photo_counter"})
    return counter["count"] if counter else 0

# ─── BOT INIT ─────────────────────────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# Fetch bot username dynamically from Telegram (no env var needed)
BOT_USERNAME = bot.get_me().username

# ─── IN-MEMORY STATE ──────────────────────────────────────────────────────────
# Tracks media groups being buffered: {media_group_id: {"file_ids": [], "photo_ids": [], "caption": "", "processed": bool}}
album_buffer   = defaultdict(lambda: {"file_ids": [], "photo_ids": [], "caption": "", "processed": False})
album_lock     = threading.Lock()

# Same buffer for private group z-videos
z_album_buffer = defaultdict(lambda: {"file_ids": [], "photo_ids": [], "caption": "", "processed": False})
z_album_lock   = threading.Lock()

# Tracks owner /broadcast step: {owner_id: target_user_id}
broadcast_targets = {}

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def get_or_create_user(user):
    doc = users.find_one({"_id": user.id})
    if doc is None:
        doc = {
            "_id":        user.id,
            "username":   user.username or "",
            "first_name": user.first_name or "",
            "limit":      15,
            "shares":     0,
            "is_free":    False,
            "is_banned":  False,
            "gender":     None,
            "state":      "normal",
        }
        users.insert_one(doc)
    return doc

def get_total_videos():
    counter = settings.find_one({"_id": "video_counter"})
    return counter["count"] if counter else 0

def main_menu_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("👤 Profile", style="success"),
        KeyboardButton("🔗 Share & Refer", style="primary"),
    )
    markup.add(
        KeyboardButton("📹 Videos Update", style="danger"),
        KeyboardButton("📞 Contact Owner", style="success"),
    )
    markup.add(
        KeyboardButton("🏆 Top Videos", style="primary"),
    )
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ Cancel", style="danger"))
    return markup

def welcome_markup(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}?start={user_id}"
    markup.add(
        InlineKeyboardButton("👤 Profile", callback_data="view_profile"),
        InlineKeyboardButton("🔗 Share",   url=share_url),
    )
    return markup

def share_markup(user_id):
    markup = InlineKeyboardMarkup()
    share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}?start={user_id}"
    markup.add(InlineKeyboardButton("🔗 Share", url=share_url))
    return markup

def gender_selection_markup():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("👨 Male",   callback_data="gender_male"),
        InlineKeyboardButton("👩 Female", callback_data="gender_female"),
    )
    return markup

def is_user_banned(user_id: int) -> bool:
    if user_id in OWNER_IDS:
        return False
    doc = users.find_one({"_id": user_id}, {"is_banned": 1})
    return bool(doc and doc.get("is_banned"))

def get_required_channel():
    return settings.find_one({"_id": "required_channel"})

def parse_public_channel_link(raw_link: str):
    raw_link = raw_link.strip()
    if raw_link.startswith("@"):
        username = raw_link[1:]
    else:
        parsed = urlparse(raw_link)
        if (
            parsed.scheme not in ("http", "https")
            or parsed.netloc.lower() not in ("t.me", "www.t.me", "telegram.me", "www.telegram.me")
        ):
            return None
        username = parsed.path.strip("/").split("/")[0]

    if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", username):
        return None

    return {
        "chat_id": f"@{username}",
        "link": f"https://t.me/{username}"
    }

def is_user_channel_joined(user_id: int) -> bool:
    if user_id in OWNER_IDS:
        return True

    channel = get_required_channel()
    if not channel or not channel.get("chat_id") or not channel.get("link"):
        return False

    try:
        member = bot.get_chat_member(channel["chat_id"], user_id)
        if member.status in ("creator", "administrator", "member"):
            return True
        return member.status == "restricted" and bool(getattr(member, "is_member", False))
    except Exception:
        return False

def channel_join_markup():
    channel = get_required_channel()
    markup = InlineKeyboardMarkup(row_width=1)
    if channel:
        markup.add(InlineKeyboardButton(
            "✅ Channel Join လုပ်ရန်",
            url=channel["link"],
            style="success"
        ))
    else:
        markup.add(InlineKeyboardButton(
            "⚠️ Channel မသတ်မှတ်ရသေးပါ",
            callback_data="channel_not_configured",
            style="danger"
        ))
    markup.add(InlineKeyboardButton(
        "🔄 Join ပြီးပါပြီ — စစ်ဆေးမည်",
        callback_data="check_channel_join",
        style="primary"
    ))
    return markup

def send_channel_join_prompt(chat_id, reply_to_message_id=None):
    channel = get_required_channel()
    text = "ဇာတ်ကားကြည့်ရန် Channel အရင် Join ပေးပါ။"
    if not channel:
        text += "\n\n⚠️ Owner က Channel link ကို အရင်သတ်မှတ်ပေးရပါမည်။"
    bot.send_message(
        chat_id,
        text,
        reply_markup=channel_join_markup(),
        reply_to_message_id=reply_to_message_id
    )

def send_welcome(chat_id, user_id):
    total = get_total_videos()
    text = (
        "<b>𝐖𝐞𝐥𝐜𝐨𝐦𝐞 𝐟𝐫𝐨𝐦 𝗕𝗹𝘂𝗲 𝗕𝗼𝘁</b>\n\n"
        "<blockquote>"
        "ဒီ 𝗕𝗼𝘁 က မင်းရဲ့စိတ်ကို ဖြေလျော့ဖို့အတွက် အလွယ်တကူ 𝗩𝗶𝗱𝗲𝗼𝘀 များ ရှာဖွေကြည့်ရှုနိုင်ပါတယ်။\n\n"
        "<b>⚡️ 𝗟𝗮𝘁𝗲𝘀𝘁 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀</b>\n"
        f"• လက်ရှိ ဗီဒီယိုအရေအတွက် ——— 𝟎{total} ခု\n\n"
        "<b>🔍 𝗛𝗼𝘄 𝘁𝗼 𝗦𝗲𝗮𝗿𝗰𝗵</b> <i>(ရှာဖွေနည်း)</i>\n"
        "• ဗီဒီယိုများ ရှာလိုပါက v1, v2, v3 စသဖြင့် v အနောက်တွင် နံပါတ်ထည့်ပြီး ရိုက်ရှာနိုင်ပါသည်။\n\n"
        "<b>🔄 𝗩𝗶𝗱𝗲𝗼𝘀 𝗨𝗽𝗱𝗮𝘁𝗲</b>\n"
        "• [ 📹 Videos Update ] ခလုတ်ကို နှိပ်ပြီး နောက်ဆုံး ဗီဒီယိုအရေအတွက်ကို အချိန်မရွေး စစ်ဆေးနိုင်ပါသည်။"
        "</blockquote>"
    )
    bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=welcome_markup(user_id))

# ─── DAILY BONUS ──────────────────────────────────────────────────────────────

def check_daily_bonus(user_id: int) -> bool:
    """Award +2 limit if user hasn't claimed today. Returns True if awarded."""
    if user_id in OWNER_IDS:
        return False
    today = str(date.today())
    doc = users.find_one({"_id": user_id}, {"last_daily": 1, "is_banned": 1})
    if not doc or doc.get("is_banned"):
        return False
    if doc.get("last_daily") == today:
        return False
    users.update_one(
        {"_id": user_id},
        {"$set": {"last_daily": today}, "$inc": {"limit": 2}}
    )
    return True

# ─── RATING MARKUP ────────────────────────────────────────────────────────────

def rating_markup(vid_id: str) -> InlineKeyboardMarkup:
    vid_doc  = videos.find_one({"_id": vid_id}, {"likes": 1, "dislikes": 1, "views": 1})
    likes    = vid_doc.get("likes",    0) if vid_doc else 0
    dislikes = vid_doc.get("dislikes", 0) if vid_doc else 0
    views    = vid_doc.get("views",    0) if vid_doc else 0
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton(f"👍 {likes}",    callback_data=f"rate_{vid_id}_like", style="success"),
        InlineKeyboardButton(f"👎 {dislikes}", callback_data=f"rate_{vid_id}_dislike", style="danger"),
        InlineKeyboardButton(f"👁 {views}",    callback_data="noop", style="primary"),
    )
    return markup

# ─── BROADCAST NEW CONTENT ────────────────────────────────────────────────────

def broadcast_new_content(vid_id: str):
    """Notify all non-banned users about new public video in background thread."""
    if not get_broadcast_new_video():
        return
    def _send():
        all_ids = [u["_id"] for u in users.find({"is_banned": {"$ne": True}}, {"_id": 1})]
        for uid in all_ids:
            try:
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton(
                    f"▶️ ကြည့်ရှု ({vid_id})",
                    url=f"https://t.me/{BOT_USERNAME}?start={uid}",
                    style="success"
                ))
                bot.send_message(
                    uid,
                    f"<b>🆕 အသစ် ထည့်သွင်းလိုက်ပြီ!</b>\n\n"
                    f"<blockquote>📹 <b>{vid_id}</b> ကို ယခုမှ ကြည့်ရှုနိုင်ပါပြီ။\n"
                    f"• Group/Private တွင် <code>{vid_id}</code> ရိုက်ပြီး ရှာနိုင်သည်။</blockquote>",
                    parse_mode='HTML',
                    reply_markup=markup
                )
            except Exception:
                pass
    threading.Thread(target=_send, daemon=True).start()

# ─── TOP VIDEOS TEXT ──────────────────────────────────────────────────────────

def get_top_videos_text(n: int = 10) -> str:
    top = list(videos.find(
        {"_id": {"$regex": r"^v\d+$"}, "likes": {"$gt": 0}},
        {"_id": 1, "likes": 1, "dislikes": 1, "views": 1}
    ).sort("likes", -1).limit(n))
    if not top:
        return (
            "<b>🏆 𝗧𝗼𝗽 𝗩𝗶𝗱𝗲𝗼𝘀</b>\n\n"
            "<blockquote>• မဲပေးမှု မရှိသေးပါ။\n"
            "• Video ကြည့်ပြီးနောက် 👍 / 👎 နှိပ်ပြီး မဲပေးနိုင်ပါသည်။</blockquote>"
        )
    medals = ["🥇","🥈","🥉"] + ["🏅"] * 7
    lines  = []
    for i, v in enumerate(top):
        lines.append(
            f"{medals[i]} <b>{v['_id']}</b>  👍 {v.get('likes',0)}  "
            f"👎 {v.get('dislikes',0)}  👁 {v.get('views',0)}"
        )
    return (
        "<b>🏆 𝗧𝗼𝗽 𝗩𝗶𝗱𝗲𝗼𝘀 (Most Liked)</b>\n\n"
        f"<blockquote>{'%0A'.join(lines).replace('%0A', chr(10))}</blockquote>"
    )

# ─── Owner /autobroadcast ────────────────────────────────────────────────────
# /autobroadcast on   → enable auto-notify when new public video is added
# /autobroadcast off  → disable auto-notify
# /autobroadcast      → show current status

@bot.message_handler(commands=["autobroadcast"])
def cmd_autobroadcast(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2 or parts[1].lower() not in ("on", "off"):
        current = get_broadcast_new_video()
        status  = "✅ ON (ဖွင့်ထား)" if current else "❌ OFF (ပိတ်ထား)"
        bot.send_message(
            message.chat.id,
            "<b>📡 Auto Broadcast New Video</b>\n\n"
            f"<blockquote>• လက်ရှိ အခြေအနေ ——— {status}\n\n"
            "• /autobroadcast on  — ဖွင့်မည်\n"
            "• /autobroadcast off — ပိတ်မည်</blockquote>",
            parse_mode='HTML'
        )
        return
    toggle  = parts[1].lower()
    enabled = (toggle == "on")
    set_broadcast_new_video(enabled)
    if enabled:
        bot.send_message(
            message.chat.id,
            "✅ <b>Auto Broadcast ဖွင့်လိုက်ပါပြီ။</b>\n\n"
            "<blockquote>• Video အသစ်တင်တိုင်း Users အားလုံးကို\n"
            "  အလိုအလျောက် Notify ပေးပို့မည်။</blockquote>",
            parse_mode='HTML'
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ <b>Auto Broadcast ပိတ်လိုက်ပါပြီ။</b>\n\n"
            "<blockquote>• Video အသစ်တင်သော်လည်း\n"
            "  Users များကို Notify မပေးပို့တော့ပါ။</blockquote>",
            parse_mode='HTML'
        )


# ─── Owner /ref ──────────────────────────────────────────────────────────────
# Usage: /ref v1  → create a deep link that opens this public video in PM

@bot.message_handler(commands=["ref"])
def cmd_ref(message):
    if message.from_user.id not in OWNER_IDS:
        return

    parts = message.text.split()
    if len(parts) != 2 or not re.fullmatch(r"v\d+", parts[1].strip(), re.IGNORECASE):
        bot.send_message(
            message.chat.id,
            "<b>အသုံးပြုပုံ</b>\n\n"
            "<code>/ref v1</code>\n"
            "<code>/ref v2</code>",
            parse_mode='HTML'
        )
        return

    vid_id = parts[1].strip().lower()
    if not videos.find_one({"_id": vid_id}, {"_id": 1}):
        bot.send_message(
            message.chat.id,
            f"❌ <b>{h(vid_id)}</b> ကို Video database ထဲမှာ မတွေ့ပါ။",
            parse_mode='HTML'
        )
        return

    deep_link = f"https://t.me/{BOT_USERNAME}?start=ref_{vid_id}"
    share_url  = f"https://t.me/share/url?url={deep_link}"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔗 Link Share လုပ်မည်", url=share_url))
    bot.send_message(
        message.chat.id,
        "<b>🔗 Video Referral Link</b>\n\n"
        f"• Video — <code>{h(vid_id)}</code>\n"
        f"• Link —\n<code>{h(deep_link)}</code>\n\n"
        "ဤ link ကိုနှိပ်သူများသည် Bot PM ထဲတွင်\n"
        f"<code>{h(vid_id)}</code> ကို တိုက်ရိုက်ရရှိပါမည်။",
        parse_mode='HTML',
        reply_markup=markup
    )


# ─── Owner /setchannel and /removechannel ────────────────────────────────────

@bot.message_handler(commands=["setchannel"])
def cmd_setchannel(message):
    if message.from_user.id not in OWNER_IDS:
        return
    if message.chat.type != "private":
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.send_message(
            message.chat.id,
            "အသုံးပြုပုံ:\n<code>/setchannel https://t.me/your_channel</code>\n\n"
            "Channel သည် public ဖြစ်ရမည်ဖြစ်ပြီး Bot ကို Channel ထဲတွင် Admin ပေးထားပါ။",
            parse_mode='HTML'
        )
        return

    channel = parse_public_channel_link(parts[1])
    if not channel:
        bot.send_message(
            message.chat.id,
            "❌ Public Channel link မမှန်ကန်ပါ။\n"
            "ဥပမာ: <code>https://t.me/your_channel</code>",
            parse_mode='HTML'
        )
        return

    try:
        chat = bot.get_chat(channel["chat_id"])
        if chat.type != "channel":
            raise ValueError("ပေးထားသော link သည် Channel link မဟုတ်ပါ။")
        bot_member = bot.get_chat_member(channel["chat_id"], bot.get_me().id)
        if bot_member.status not in ("administrator", "creator"):
            raise ValueError("Bot ကို Channel ထဲတွင် Administrator ပေးထားရပါမည်။")
    except Exception as e:
        bot.send_message(
            message.chat.id,
            "❌ Channel ကို မတွေ့ပါ။ Link မှန်ကန်ကြောင်းနှင့်\n"
            "Bot ကို Channel ထဲတွင် ထည့်ထားကြောင်း စစ်ဆေးပေးပါ။\n\n"
            f"<code>{h(str(e))}</code>",
            parse_mode='HTML'
        )
        return

    settings.update_one(
        {"_id": "required_channel"},
        {"$set": {
            "chat_id": channel["chat_id"],
            "link": channel["link"],
            "title": chat.title or channel["chat_id"]
        }},
        upsert=True
    )
    bot.send_message(
        message.chat.id,
        "✅ <b>Join လုပ်ရန် Channel သတ်မှတ်ပြီးပါပြီ။</b>\n\n"
        f"• Channel — <b>{h(chat.title or channel['chat_id'])}</b>\n"
        f"• Link — <code>{h(channel['link'])}</code>\n\n"
        "Bot သည် User များ၏ Channel Join အခြေအနေကို စစ်ဆေးပါမည်။",
        parse_mode='HTML'
    )

@bot.message_handler(commands=["removechannel"])
def cmd_removechannel(message):
    if message.from_user.id not in OWNER_IDS:
        return
    if message.chat.type != "private":
        return

    result = settings.delete_one({"_id": "required_channel"})
    if result.deleted_count:
        bot.send_message(
            message.chat.id,
            "✅ Join လုပ်ရန် Channel သတ်မှတ်ချက်ကို ပယ်ဖျက်ပြီးပါပြီ။"
        )
    else:
        bot.send_message(
            message.chat.id,
            "ℹ️ သတ်မှတ်ထားသော Channel မရှိသေးပါ။"
        )


# ─── /start ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    args     = message.text.split()
    new_user = message.from_user
    doc      = users.find_one({"_id": new_user.id})
    is_new   = doc is None
    resumed_new_user = bool(getattr(message, "_channel_was_new", False))
    ref_video_id = None

    if len(args) > 1:
        start_param = args[1].strip().lower()
        if start_param.startswith("ref_"):
            candidate = start_param[4:]
            if re.fullmatch(r"v\d+", candidate, re.IGNORECASE):
                ref_video_id = candidate

    if is_new:
        get_or_create_user(new_user)

    # Referral logic (works from any chat)
    if len(args) > 1 and is_new and ref_video_id is None:
        try:
            referrer_id = int(args[1])
            if referrer_id != new_user.id:
                referrer = users.find_one({"_id": referrer_id})
                if referrer:
                    users.update_one(
                        {"_id": referrer_id},
                        {"$inc": {"limit": 5, "shares": 1}}
                    )
                    try:
                        bot.send_message(
                            referrer_id,
                            "<b>🎉 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹 𝗦𝘂𝗰𝗰𝗲𝘀𝘀!</b>\n\n"
                            "<blockquote>• သူငယ်ချင်းတစ်ဦး Bot ကို Join ဝင်သဖြင့်\n"
                            "  ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 +𝟱 ခု ထပ်ရပါပြီ! ✅</blockquote>",
                            parse_mode='HTML'
                        )
                    except Exception:
                        pass
        except (ValueError, TypeError):
            pass

    users.update_one({"_id": new_user.id}, {"$set": {"state": "normal"}})

    if message.chat.type == "private":
        # Ban check
        if is_user_banned(new_user.id):
            bot.send_message(
                message.chat.id,
                "🚫 သင်သည် ဤ Bot ကို အသုံးပြုခွင့် ပိတ်ဆို့ထားပါသည်။"
            )
            return

        if not is_user_channel_joined(new_user.id):
            users.update_one(
                {"_id": new_user.id},
                {"$set": {
                    "pending_channel_action": message.text,
                    "pending_channel_new_user": is_new or resumed_new_user
                }}
            )
            send_channel_join_prompt(message.chat.id)
            return

        # Referral links should only show the welcome messages to new users.
        # Existing users can go straight to the requested video.
        show_welcome = is_new or resumed_new_user or ref_video_id is None
        if show_welcome:
            bot.send_message(
                message.chat.id,
                "<b>𝗕𝗹𝘂𝗲 𝗕𝗼𝘁 တွင် ကြိုဆိုပါသည်! 🎉</b>",
                parse_mode='HTML',
                reply_markup=main_menu_keyboard()
            )
            send_welcome(message.chat.id, new_user.id)

        # Daily bonus check
        if not is_new:
            bonus = check_daily_bonus(new_user.id)
            if bonus:
                bot.send_message(
                    message.chat.id,
                    "<b>🎁 𝗗𝗮𝗶𝗹𝘆 𝗕𝗼𝗻𝘂𝘀!</b>\n\n"
                    "<blockquote>• ယနေ့ Bot ဝင်ရောက်သဖြင့်\n"
                    "  ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 +𝟮 ရပါပြီ! ✅</blockquote>",
                    parse_mode='HTML'
                )

        # Gender selection — only ask if not yet selected
        doc_check = users.find_one({"_id": new_user.id}, {"gender": 1})
        if not doc_check or not doc_check.get("gender"):
            if ref_video_id:
                users.update_one(
                    {"_id": new_user.id},
                    {"$set": {"pending_ref_video": ref_video_id}}
                )
            bot.send_message(
                message.chat.id,
                "<b>🔞 𝗔𝗴𝗲 𝗩𝗲𝗿𝗶𝗳𝗶𝗰𝗮𝘁𝗶𝗼𝗻</b>\n\n"
                "<blockquote>• Bot ကို အသုံးပြုရန် လိင်ကို ရွေးချယ်ပေးပါ ခင်ဗျာ။</blockquote>",
                parse_mode='HTML',
                reply_markup=gender_selection_markup()
            )
            return

        if ref_video_id:
            message.text = ref_video_id
            handle_text(message)
            return
    else:
        total  = get_total_videos()
        fname  = new_user.first_name or new_user.username or str(new_user.id)
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "🤖 Private တွင် Bot ဖွင့်မည်",
            url=f"https://t.me/{BOT_USERNAME}?start={new_user.id}"
        ))
        bot.send_message(
            message.chat.id,
            f"<b>𝗕𝗹𝘂𝗲 𝗕𝗼𝘁 — မှတ်ပုံတင်ပြီးပါပြီ ✅</b>\n\n"
            f"<blockquote><b>👋 𝗛𝗲𝗹𝗹𝗼, {h(fname)}!</b>\n\n"
            f"<b>⚡️ 𝗟𝗮𝘁𝗲𝘀𝘁 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀</b>\n"
            f"• လက်ရှိ ဗီဒီယိုအရေအတွက် ——— {total} ခု\n\n"
            f"<b>🔍 𝗛𝗼𝘄 𝘁𝗼 𝗦𝗲𝗮𝗿𝗰𝗵</b>\n"
            f"• v1, v2, v3 … ရိုက်ပြီး ဤ Group တွင် ရှာနိုင်ပါသည်။\n\n"
            f"<i>💡 Profile / Share / Contact ကို 𝗣𝗿𝗶𝘃𝗮𝘁𝗲 𝗖𝗵𝗮𝘁 တွင်သာ သုံးနိုင်ပါသည်။</i>"
            f"</blockquote>",
            parse_mode='HTML',
            reply_markup=markup
        )

# ─── Profile callback ─────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "view_profile")
def cb_profile(call):
    user_id = call.from_user.id
    doc = users.find_one({"_id": user_id})
    if not doc:
        doc = get_or_create_user(call.from_user)

    display_name = doc.get("username") or doc.get("first_name") or str(user_id)
    limit_str    = "∞ Unlimited" if doc.get("is_free") else str(doc.get("limit", 0))

    text = (
        "<b>👤 𝗠𝘆 𝗣𝗿𝗼𝗳𝗶𝗹𝗲</b>\n\n"
        f"<blockquote>• 𝗡𝗮𝗺𝗲  ——  {h(display_name)}\n"
        f"• 𝗜𝗗  ——  {user_id}\n"
        f"• 𝗟𝗶𝗺𝗶𝘁  ——  {h(limit_str)}\n"
        f"• 𝗦𝗵𝗮𝗿𝗲𝘀  ——  {doc.get('shares', 0)} ဦး</blockquote>"
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text, parse_mode='HTML')

# ─── Gender callbacks ─────────────────────────────────────────────────────────

def send_pending_ref_video(call):
    user_id = call.from_user.id
    pending_doc = users.find_one({"_id": user_id}, {"pending_ref_video": 1})
    vid_id = pending_doc.get("pending_ref_video") if pending_doc else None
    if not vid_id or not re.fullmatch(r"v\d+", vid_id, re.IGNORECASE):
        return

    users.update_one(
        {"_id": user_id},
        {"$unset": {"pending_ref_video": ""}}
    )
    pending_message = SimpleNamespace(
        text=vid_id,
        from_user=call.from_user,
        chat=call.message.chat
    )
    handle_text(pending_message)

def resume_pending_channel_action(call):
    user_id = call.from_user.id
    if not get_required_channel():
        bot.answer_callback_query(
            call.id,
            "Owner က Channel link ကို အရင်သတ်မှတ်ပေးရပါမည်။",
            show_alert=True
        )
        return
    if not is_user_channel_joined(user_id):
        bot.answer_callback_query(
            call.id,
            "Channel ကို အရင် Join ပေးပါ။",
            show_alert=True
        )
        return

    pending_doc = users.find_one(
        {"_id": user_id},
        {"pending_channel_action": 1, "pending_channel_new_user": 1}
    )
    pending_action = pending_doc.get("pending_channel_action") if pending_doc else None
    pending_new_user = bool(pending_doc and pending_doc.get("pending_channel_new_user"))
    users.update_one(
        {"_id": user_id},
        {"$unset": {
            "pending_channel_action": "",
            "pending_channel_new_user": ""
        }}
    )
    bot.answer_callback_query(call.id, "✅ Channel Join အတည်ပြုပြီးပါပြီ။")
    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
    except Exception:
        pass

    if not pending_action:
        return

    pending_message = SimpleNamespace(
        text=pending_action,
        from_user=call.from_user,
        chat=call.message.chat
    )
    if pending_action.startswith("/start"):
        pending_message._channel_was_new = pending_new_user
        cmd_start(pending_message)
    else:
        handle_text(pending_message)

@bot.callback_query_handler(func=lambda c: c.data == "check_channel_join")
def cb_check_channel_join(call):
    resume_pending_channel_action(call)

@bot.callback_query_handler(func=lambda c: c.data == "channel_not_configured")
def cb_channel_not_configured(call):
    bot.answer_callback_query(
        call.id,
        "Owner က /setchannel ဖြင့် Channel link သတ်မှတ်ပေးရပါမည်။",
        show_alert=True
    )


@bot.callback_query_handler(func=lambda c: c.data == "gender_male")
def cb_gender_male(call):
    user_id = call.from_user.id
    users.update_one({"_id": user_id}, {"$set": {"gender": "male"}})
    bot.answer_callback_query(call.id, "👨 Male ရွေးချယ်ပြီးပါပြီ")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(
        call.message.chat.id,
        "<b>🔞 𝗔𝗱𝘂𝗹𝘁 𝗖𝗼𝗻𝘁𝗲𝗻𝘁 𝗡𝗼𝘁𝗶𝗰𝗲</b>\n\n"
        "<blockquote>⚠️ ဤ Bot သည် 𝗔𝗱𝘂𝗹𝘁 𝗠𝗼𝘃𝗶𝗲𝘀 (လူကြီးကားများ)\n"
        "ကြည့်ရှုနိုင်သည့် Bot ဖြစ်ပါသည်။\n\n"
        "• အသက် 𝟭𝟴+ သာ အသုံးပြုခွင့်ရှိပါသည်။\n"
        "• Bot ကို ဆက်လက် အသုံးပြုနိုင်ပါပြီ ✅</blockquote>",
        parse_mode='HTML'
    )
    send_pending_ref_video(call)

@bot.callback_query_handler(func=lambda c: c.data == "gender_female")
def cb_gender_female(call):
    user_id = call.from_user.id
    users.update_one({"_id": user_id}, {"$set": {"gender": "female"}})
    bot.answer_callback_query(call.id, "👩 Female ရွေးချယ်ပြီးပါပြီ")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(
        call.message.chat.id,
        "<b>🔞 𝗔𝗱𝘂𝗹𝘁 𝗖𝗼𝗻𝘁𝗲𝗻𝘁 𝗡𝗼𝘁𝗶𝗰𝗲</b>\n\n"
        "<blockquote>⚠️ ဤ Bot သည် 𝗔𝗱𝘂𝗹𝘁 𝗠𝗼𝘃𝗶𝗲𝘀 (လူကြီးကားများ)\n"
        "ကြည့်ရှုနိုင်သည့် Bot ဖြစ်ပါသည်။\n\n"
        "• ဤ Bot ကို အသုံးပြုရန် အတင်းအကြပ် မတိုက်တွန်းပါ။\n"
        "• အတင်းအကြပ် မတောင်းဆိုပါ အသုံးပြုသည်မပြုသည်ကို ကိုယ်တိုင်ဆုံးဖြတ်ပါ။\n\n"
        "<i>💬 ကိုယ်ပိုင်ဆန္ဒဖြင့် ဆက်လက်ကြည့်ရှုလိုပါက Bot ကို\n"
        "   အသုံးပြုနိုင်ပါသည် — မည်သို့မျှ မတားမြစ်ပါ ✅</i></blockquote>",
        parse_mode='HTML'
    )
    send_pending_ref_video(call)


# ─── /contact_to_owner ────────────────────────────────────────────────────────

@bot.message_handler(commands=["contact_to_owner"])
def cmd_contact(message):
    if message.chat.type != "private":
        return
    users.update_one({"_id": message.from_user.id}, {"$set": {"state": "waiting_contact"}})
    bot.send_message(
        message.chat.id,
        "📞 လူကြီးမင်းအနေဖြင့် Bot Owner ထံ ပြောကြားလိုသည့် "
        "စာသားများကို ရိုက်နှိပ်ပေးပို့နိုင်ပါပြီ ခင်ဗျာ။",
        reply_markup=cancel_keyboard()
    )

# ─── Owner /panel ─────────────────────────────────────────────────────────────

@bot.message_handler(commands=["panel"])
def cmd_panel(message):
    if message.from_user.id not in OWNER_IDS:
        return
    total_users   = users.count_documents({})
    free_users    = users.count_documents({"is_free": True})
    banned_users  = users.count_documents({"is_banned": True})
    total_shares  = sum(d.get("shares", 0) for d in users.find({}, {"shares": 1}))
    total_vids    = get_total_videos()
    total_photos  = get_total_photos()
    total_zvids   = get_total_z_videos()
    total_zphotos = get_total_z_photos()
    broadcast_on  = get_broadcast_new_video()
    bc_status     = "✅ ON (ဖွင့်ထား)" if broadcast_on else "❌ OFF (ပိတ်ထား)"
    bot.send_message(
        message.chat.id,
        "<b>📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀</b>\n\n"
        f"<blockquote>👥 𝗧𝗼𝘁𝗮𝗹 𝗨𝘀𝗲𝗿𝘀  ——  {total_users} ဦး\n"
        f"✅ 𝗙𝗿𝗲𝗲 𝗨𝘀𝗲𝗿𝘀    ——  {free_users} ဦး\n"
        f"🚫 𝗕𝗮𝗻𝗻𝗲𝗱 𝗨𝘀𝗲𝗿𝘀  ——  {banned_users} ဦး\n"
        f"🔗 𝗧𝗼𝘁𝗮𝗹 𝗦𝗵𝗮𝗿𝗲𝘀  ——  {total_shares} ကြိမ်\n\n"
        f"🎬 𝗣𝘂𝗯𝗹𝗶𝗰 𝗩𝗶𝗱𝗲𝗼𝘀  ——  {total_vids} ခု\n"
        f"🖼 𝗣𝘂𝗯𝗹𝗶𝗰 𝗣𝗵𝗼𝘁𝗼𝘀  ——  {total_photos} ပုံ\n"
        f"🔒 𝗣𝗿𝗶𝘃𝗮𝘁𝗲 𝗩𝗶𝗱𝗲𝗼𝘀  ——  {total_zvids} ခု\n"
        f"🔒 𝗣𝗿𝗶𝘃𝗮𝘁𝗲 𝗣𝗵𝗼𝘁𝗼𝘀  ——  {total_zphotos} ပုံ\n\n"
        f"📡 𝗔𝘂𝘁𝗼 𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁  ——  {bc_status}</blockquote>",
        parse_mode='HTML'
    )

# ─── Owner /ownerhelp ─────────────────────────────────────────────────────────

@bot.message_handler(commands=["ownerhelp"])
def cmd_ownerhelp(message):
    if message.from_user.id not in OWNER_IDS:
        return
    bot.send_message(
        message.chat.id,
        "<b>👑 𝗢𝘄𝗻𝗲𝗿 𝗖𝗼𝗺𝗺𝗮𝗻𝗱𝘀</b>\n\n"
        "<blockquote>"
        "<b>📊 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀</b>\n"
        "• /panel — Bot စာရင်းအင်းများ ကြည့်ရန်\n\n"
        "<b>👥 𝗨𝘀𝗲𝗿 𝗠𝗮𝗻𝗮𝗴𝗲𝗺𝗲𝗻𝘁</b>\n"
        "• /userinfo {user_id} — User အချက်အလက်\n"
        "• /userlist — User အားလုံး စာရင်း\n"
        "• /addlimit {user_id} {amount} — Limit ထည့်/နှုတ်\n"
        "• /free {user_id} on|off — Unlimited toggle\n\n"
        "<b>📨 𝗕𝗿𝗼𝗮𝗱𝗰𝗮𝘀𝘁</b>\n"
        "• /broadcast all — User အားလုံးထံ ပေးပို့\n"
        "• /broadcast {user_id} — တစ်ဦးထဲ ပေးပို့\n\n"
        "<b>🎬 𝗩𝗶𝗱𝗲𝗼 (𝗣𝘂𝗯𝗹𝗶𝗰)</b>\n"
        "• /setadmingroup — Public video group သတ်မှတ် (group ထဲ)\n"
        "• /deletevideo v5 — Public video ဖျက်\n"
        "• /deletephoto p3 — Public photo ဖျက်\n\n"
        "<b>🔒 𝗣𝗿𝗶𝘃𝗮𝘁𝗲 𝗩𝗶𝗱𝗲𝗼/𝗣𝗵𝗼𝘁𝗼</b>\n"
        "• /setadmingroup_private — Private video group သတ်မှတ် (group ထဲ)\n"
        "• /accept {user_id} — User ကို private access ပေး\n"
        "• /accept remove {user_id} — Private access ရုပ်သိမ်း\n"
        "• /deleteprivatevideo z5 — Private video ဖျက်\n"
        "• /deleteprivatephoto zp3 — Private photo ဖျက်\n\n"
        "<b>🖼 𝗧𝗵𝘂𝗺𝗯𝗻𝗮𝗶𝗹</b>\n"
        "• /setthumb v3 — Video v3 အတွက် thumbnail သတ်မှတ် (ပုံ caption ထဲ)\n"
        "• /setthumb z3 — Private video z3 thumbnail\n"
        "• /removethumb v3 — Thumbnail ဖျက်\n\n"
        "<b>🚫 𝗨𝘀𝗲𝗿 𝗕𝗮𝗻</b>\n"
        "• /ban {user_id} — User ကို Ban ချ\n"
        "• /unban {user_id} — User ကို Ban ဖြုတ်\n\n"
        "<i>• /ownerhelp — ဤ menu ပြန်ကြည့်ရန်</i>"
        "</blockquote>",
        parse_mode='HTML'
    )


# ─── Owner /ban & /unban ──────────────────────────────────────────────────────

@bot.message_handler(commands=["ban"])
def cmd_ban(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /ban {user_id}")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ User ID မမှန်ကန်ပါ။")
        return
    if target_id in OWNER_IDS:
        bot.send_message(message.chat.id, "❌ Owner ကို Ban မချနိုင်ပါ။")
        return
    result = users.find_one_and_update(
        {"_id": target_id},
        {"$set": {"is_banned": True}},
        return_document=True
    )
    if not result:
        bot.send_message(message.chat.id, f"❌ User {target_id} database တွင် မတွေ့ပါ။")
        return
    uname = result.get("username") or result.get("first_name") or str(target_id)
    bot.send_message(
        message.chat.id,
        f"🚫 User {target_id} ({uname}) ကို Ban ချပြီးပါပြီ။\n"
        f"• Bot ကို ဆက်လက် အသုံးပြုနိုင်တော့မည် မဟုတ်ပါ။"
    )
    try:
        bot.send_message(
            target_id,
            "🚫 သင်သည် ဤ Bot ကို အသုံးပြုခွင့် ပိတ်ဆို့ပြီးပါပြီ။"
        )
    except Exception:
        pass


@bot.message_handler(commands=["unban"])
def cmd_unban(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /unban {user_id}")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ User ID မမှန်ကန်ပါ။")
        return
    result = users.find_one_and_update(
        {"_id": target_id},
        {"$set": {"is_banned": False}},
        return_document=True
    )
    if not result:
        bot.send_message(message.chat.id, f"❌ User {target_id} database တွင် မတွေ့ပါ။")
        return
    uname = result.get("username") or result.get("first_name") or str(target_id)
    bot.send_message(
        message.chat.id,
        f"✅ User {target_id} ({uname}) ၏ Ban ကို ဖြုတ်ပြီးပါပြီ။\n"
        f"• Bot ကို ဆက်လက် အသုံးပြုနိုင်ပါပြီ။"
    )
    try:
        bot.send_message(
            target_id,
            "✅ သင်၏ Ban ကို ဖြုတ်ပေးလိုက်ပါပြီ။ Bot ကို ဆက်လက် အသုံးပြုနိုင်ပါပြီ။"
        )
    except Exception:
        pass


# ─── Owner /addlimit ──────────────────────────────────────────────────────────

@bot.message_handler(commands=["addlimit"])
def cmd_addlimit(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.send_message(message.chat.id, "Usage: /addlimit {user_id} {amount}")
        return
    try:
        target_id = int(parts[1])
        amount    = int(parts[2])
    except ValueError:
        bot.send_message(message.chat.id, "Invalid user_id or amount. Both must be numbers.")
        return
    if amount == 0:
        bot.send_message(message.chat.id, "Amount cannot be 0.")
        return

    result = users.find_one_and_update(
        {"_id": target_id},
        {"$inc": {"limit": amount}},
        return_document=True
    )
    if not result:
        bot.send_message(message.chat.id, f"❌ User {target_id} not found in database.")
        return

    new_limit = result.get("limit", 0)
    action    = f"+{amount}" if amount > 0 else str(amount)
    bot.send_message(
        message.chat.id,
        f"✅ User {target_id} ထံ 𝗟𝗶𝗺𝗶𝘁 {action} ထည့်ပြီးပါပြီ။\n"
        f"• လက်ရှိ 𝗟𝗶𝗺𝗶𝘁: {new_limit}"
    )
    try:
        bot.send_message(
            target_id,
            "<b>🎁 𝗟𝗶𝗺𝗶𝘁 𝗔𝗱𝗱𝗲𝗱!</b>\n\n"
            f"<blockquote>• 𝗢𝘄𝗻𝗲𝗿 မှ ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 {action} ခု ထည့်ပေးလိုက်ပါပြီ 🎉\n"
            f"• လက်ရှိ 𝗟𝗶𝗺𝗶𝘁: {new_limit}</blockquote>",
            parse_mode='HTML'
        )
    except Exception:
        pass

# ─── Owner /userinfo ──────────────────────────────────────────────────────────

@bot.message_handler(commands=["userinfo"])
def cmd_userinfo(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /userinfo {user_id}")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Invalid user_id. Must be a number.")
        return

    doc = users.find_one({"_id": target_id})
    if not doc:
        bot.send_message(message.chat.id, f"❌ User {target_id} not found in database.")
        return

    uname    = doc.get("username") or "—"
    fname    = doc.get("first_name") or "—"
    limit    = doc.get("limit", 0)
    shares   = doc.get("shares", 0)
    is_free  = doc.get("is_free", False)
    referrals = doc.get("referrals", 0)
    state    = doc.get("state", "normal")
    joined   = doc.get("joined_at", "—")

    free_tag = "✅ Free (Unlimited)" if is_free else "❌ Limited"

    bot.send_message(
        message.chat.id,
        "<b>👤 𝗨𝘀𝗲𝗿 𝗜𝗻𝗳𝗼</b>\n\n"
        f"<blockquote>• 𝗡𝗮𝗺𝗲  ——  {h(fname)}\n"
        f"• 𝗨𝘀𝗲𝗿𝗻𝗮𝗺𝗲  ——  @{h(uname)}\n"
        f"• 𝗜𝗗  ——  {target_id}\n\n"
        f"• 𝗟𝗶𝗺𝗶𝘁  ——  {limit} ကြိမ်\n"
        f"• 𝗦𝗵𝗮𝗿𝗲  ——  {shares} ကြိမ် Share ခဲ့သည်\n"
        f"• 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹𝘀  ——  {referrals} ဦး ဖိတ်ခဲ့သည်\n\n"
        f"• 𝗙𝗿𝗲𝗲 𝗠𝗼𝗱𝗲  ——  {h(free_tag)}\n"
        f"• 𝗦𝘁𝗮𝘁𝗲  ——  {h(state)}\n"
        f"• 𝗝𝗼𝗶𝗻𝗲𝗱  ——  {h(str(joined))}</blockquote>",
        parse_mode='HTML'
    )

# ─── Owner /free ──────────────────────────────────────────────────────────────

@bot.message_handler(commands=["free"])
def cmd_free(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.send_message(message.chat.id, "Usage: /free {user_id} on|off")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "Invalid user_id.")
        return
    toggle = parts[2].lower()
    if toggle == "on":
        users.update_one({"_id": target_id}, {"$set": {"is_free": True}})
        bot.send_message(message.chat.id, f"✅ User {target_id} is now FREE (unlimited views).")
    elif toggle == "off":
        users.update_one({"_id": target_id}, {"$set": {"is_free": False}})
        bot.send_message(message.chat.id, f"✅ User {target_id} limit consumption restored.")
    else:
        bot.send_message(message.chat.id, "Usage: /free {user_id} on|off")

# ─── Owner /userlist ──────────────────────────────────────────────────────────

@bot.message_handler(commands=["userlist"])
def cmd_userlist(message):
    if message.from_user.id not in OWNER_IDS:
        return

    all_users = list(users.find({}, {"_id": 1, "username": 1, "first_name": 1}))
    if not all_users:
        bot.send_message(message.chat.id, "📋 User မရှိသေးပါ။")
        return

    # Build lines: "@username 1234567890" or "FirstName 1234567890"
    lines = []
    for u in all_users:
        uid  = u["_id"]
        name = (
            f"@{u['username']}" if u.get("username")
            else (u.get("first_name") or "NoName")
        )
        lines.append(f"{name}  {uid}")

    total = len(lines)
    # Telegram max message length ~4096; split if needed
    chunk, chunks = [], []
    char_count = 0
    header = f"👥 User List — {total} ဦး\n{'━' * 22}\n\n"
    for line in lines:
        if char_count + len(line) + 1 > 3800:
            chunks.append(chunk)
            chunk, char_count = [], 0
        chunk.append(line)
        char_count += len(line) + 1
    if chunk:
        chunks.append(chunk)

    for i, ch in enumerate(chunks):
        prefix = header if i == 0 else f"(ဆက်လက်... {i+1}/{len(chunks)})\n\n"
        bot.send_message(message.chat.id, prefix + "\n".join(ch))


# ─── Owner /broadcast ─────────────────────────────────────────────────────────
# /broadcast all        → sends a message to every registered user
# /broadcast {user_id}  → sends a message to one specific user

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(
            message.chat.id,
            "📨 Broadcast\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Usage:\n"
            "/broadcast all          → Users အားလုံးထံ ပေးပို့မည်\n"
            "/broadcast {user_id}    → တစ်ဦးတည်းထံ ပေးပို့မည်"
        )
        return

    arg = parts[1].strip()
    owner_id = message.from_user.id

    if arg.lower() == "all":
        total = users.count_documents({})
        broadcast_targets[owner_id] = "all"
        bot.send_message(
            message.chat.id,
            f"📨 Users {total} ဦး အားလုံးထံ ပေးပို့မည့် စာသားကို ရိုက်ထည့်ပေးပါ:\n\n"
            "မပို့လိုပါက ❌ Cancel ကိုနှိပ်ပါ။",
            reply_markup=cancel_keyboard()
        )
    else:
        try:
            target_id = int(arg)
        except ValueError:
            bot.send_message(message.chat.id, "❌ User ID မမှန်ကန်ပါ။\nUsage: /broadcast {user_id} or /broadcast all")
            return
        broadcast_targets[owner_id] = target_id
        bot.send_message(
            message.chat.id,
            f"📨 User {target_id} ထံ ပေးပို့မည့် စာသားကို ရိုက်ထည့်ပေးပါ:\n\n"
            "မပို့လိုပါက ❌ Cancel ကိုနှိပ်ပါ။",
            reply_markup=cancel_keyboard()
        )

# ─── Owner /setadmingroup ─────────────────────────────────────────────────────
# Owner sends /setadmingroup inside any group → that group becomes the video
# ingestion group.  Stored in MongoDB so it survives restarts.

@bot.message_handler(commands=["setadmingroup"])
def cmd_setadmingroup(message):
    if message.from_user.id not in OWNER_IDS:
        return
    if message.chat.type not in ("group", "supergroup"):
        bot.send_message(
            message.chat.id,
            "⚠️ ဤ command ကို group ထဲတွင်သာ သုံးနိုင်ပါသည်။\n"
            "Bot ကို group ထဲ add ပြုလုပ်ပြီး group ထဲတွင် /setadmingroup ရိုက်ပါ။"
        )
        return

    chat_id   = message.chat.id
    chat_name = message.chat.title or str(chat_id)
    set_admin_group_id(chat_id)
    bot.send_message(
        message.chat.id,
        f"✅ ဤ group ကို Video သိမ်းဆည်းမည့် Admin Group အဖြစ် သတ်မှတ်ပြီးပါပြီ။\n\n"
        f"Group: {chat_name}\n"
        f"ID: {chat_id}\n\n"
        f"ယခုမှ စတင်ပြီး Owner ဤ group ထဲ video ပို့ပါက အလိုအလျောက် database သိမ်းဆည်းမည်။"
    )


# ─── Owner /setadmingroup_private ────────────────────────────────────────────
# Owner sends /setadmingroup_private inside any group → that group becomes the
# private video ingestion group. Only owner + accepted users can upload & search.

@bot.message_handler(commands=["setadmingroup_private"])
def cmd_setadmingroup_private(message):
    if message.from_user.id not in OWNER_IDS:
        return
    if message.chat.type not in ("group", "supergroup"):
        bot.send_message(
            message.chat.id,
            "⚠️ ဤ command ကို group ထဲတွင်သာ သုံးနိုင်ပါသည်။\n"
            "Bot ကို group ထဲ add ပြုလုပ်ပြီး group ထဲတွင် /setadmingroup_private ရိုက်ပါ။"
        )
        return

    chat_id   = message.chat.id
    chat_name = message.chat.title or str(chat_id)
    set_private_admin_group_id(chat_id)
    bot.send_message(
        message.chat.id,
        f"🔒 ဤ group ကို Private Video Group အဖြစ် သတ်မှတ်ပြီးပါပြီ။\n\n"
        f"Group: {chat_name}\n"
        f"ID: {chat_id}\n\n"
        f"• Owner တစ်ယောက်တည်း (သို့) /accept ဖြင့် ခွင့်ပြုထားသော User များသာ\n"
        f"  ဤ group တွင် video ပေးပို့နိုင်ပြီး z1, z2, z3 … ဖြင့် ရှာဖွေနိုင်မည်။"
    )


# ─── Owner /accept ────────────────────────────────────────────────────────────
# /accept {user_id}   → grant user access to private group upload & z-search
# /accept remove {user_id} → revoke access

@bot.message_handler(commands=["accept"])
def cmd_accept(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()

    # /accept remove {user_id}
    if len(parts) >= 3 and parts[1].lower() == "remove":
        try:
            target_id = int(parts[2])
        except ValueError:
            bot.send_message(message.chat.id, "❌ User ID မမှန်ကန်ပါ။")
            return
        remove_accepted_user(target_id)
        bot.send_message(
            message.chat.id,
            f"✅ User {target_id} ၏ Private Group ခွင့်ပြုချက် ဖျက်သိမ်းပြီးပါပြီ။"
        )
        try:
            bot.send_message(
                target_id,
                "<b>🔒 𝗔𝗰𝗰𝗲𝘀𝘀 𝗥𝗲𝘃𝗼𝗸𝗲𝗱</b>\n\n"
                "<blockquote>• Owner မှ Private Group ခွင့်ပြုချက် ရုပ်သိမ်းလိုက်ပါပြီ။</blockquote>",
                parse_mode='HTML'
            )
        except Exception:
            pass
        return

    # /accept {user_id}
    if len(parts) < 2:
        bot.send_message(
            message.chat.id,
            "Usage:\n"
            "/accept {user_id}          → Private Group ခွင့်ပြုမည်\n"
            "/accept remove {user_id}   → ခွင့်ပြုချက် ဖျက်မည်"
        )
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "❌ User ID မမှန်ကန်ပါ။")
        return

    doc = users.find_one({"_id": target_id})
    if not doc:
        bot.send_message(message.chat.id, f"❌ User {target_id} database တွင် မတွေ့ပါ။")
        return

    accept_user(target_id)
    uname = doc.get("username") or doc.get("first_name") or str(target_id)
    bot.send_message(
        message.chat.id,
        f"✅ User {target_id} ({uname}) ကို Private Group ခွင့်ပြုပြီးပါပြီ။\n"
        f"• ထို User သည် ယခု Private Group တွင် video တင်နိုင်ပြီး\n"
        f"  z1, z2, z3 … ဖြင့် ရှာဖွေနိုင်မည်။"
    )
    try:
        bot.send_message(
            target_id,
            "<b>🔓 𝗣𝗿𝗶𝘃𝗮𝘁𝗲 𝗔𝗰𝗰𝗲𝘀𝘀 𝗚𝗿𝗮𝗻𝘁𝗲𝗱!</b>\n\n"
            "<blockquote>• Owner မှ Private Group ကို ခွင့်ပြုလိုက်ပါပြီ ✅\n"
            "• Private Group တွင် video တင်နိုင်ပြီး\n"
            "  z1, z2, z3 … ဖြင့် ရှာဖွေနိုင်မည်ဖြစ်သည်။</blockquote>",
            parse_mode='HTML'
        )
    except Exception:
        pass


# ─── Owner /deletevideo ───────────────────────────────────────────────────────
# Usage: /deletevideo v5   (removes v5 from DB; does NOT renumber others)

@bot.message_handler(commands=["deletevideo"])
def cmd_deletevideo(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /deletevideo v5")
        return

    vid_id = parts[1].lower()
    if not re.fullmatch(r"v\d+", vid_id):
        bot.send_message(message.chat.id, "❌ Video ID မမှန်ကန်ပါ။ ဥပမာ: /deletevideo v5")
        return

    result = videos.delete_one({"_id": vid_id})
    if result.deleted_count == 0:
        bot.send_message(message.chat.id, f"❌ {vid_id} ကို database တွင် ရှာမတွေ့ပါ။")
        return

    # Decrement the video counter so new uploads don't skip numbers
    settings.update_one({"_id": "video_counter"}, {"$inc": {"count": -1}})
    bot.send_message(
        message.chat.id,
        f"🗑 {vid_id} ကို database မှ ဖျက်ပြီးပါပြီ။"
    )


# ─── Owner /deleteprivatevideo ────────────────────────────────────────────────
# Usage: /deleteprivatevideo z5   (removes z5 from DB)

@bot.message_handler(commands=["deleteprivatevideo"])
def cmd_deleteprivatevideo(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /deleteprivatevideo z5")
        return

    vid_id = parts[1].lower()
    if not re.fullmatch(r"z\d+", vid_id):
        bot.send_message(message.chat.id, "❌ Video ID မမှန်ကန်ပါ။ ဥပမာ: /deleteprivatevideo z5")
        return

    result = videos.delete_one({"_id": vid_id})
    if result.deleted_count == 0:
        bot.send_message(message.chat.id, f"❌ {vid_id} ကို database တွင် ရှာမတွေ့ပါ။")
        return

    settings.update_one({"_id": "z_video_counter"}, {"$inc": {"count": -1}})
    bot.send_message(
        message.chat.id,
        f"🗑 Private Video {vid_id} ကို database မှ ဖျက်ပြီးပါပြီ။"
    )


# ─── Owner /deletephoto ────────────────────────────────────────────────────────
# Usage: /deletephoto p3

@bot.message_handler(commands=["deletephoto"])
def cmd_deletephoto(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /deletephoto p3")
        return
    pid = parts[1].lower()
    if not re.fullmatch(r"p\d+", pid):
        bot.send_message(message.chat.id, "❌ Photo ID မမှန်ကန်ပါ။ ဥပမာ: /deletephoto p3")
        return
    result = videos.delete_one({"_id": pid})
    if result.deleted_count == 0:
        bot.send_message(message.chat.id, f"❌ {pid} ကို database တွင် ရှာမတွေ့ပါ။")
        return
    settings.update_one({"_id": "photo_counter"}, {"$inc": {"count": -1}})
    bot.send_message(message.chat.id, f"🗑 {pid} ကို database မှ ဖျက်ပြီးပါပြီ။")


# ─── Owner /deleteprivatephoto ────────────────────────────────────────────────
# Usage: /deleteprivatephoto zp3

@bot.message_handler(commands=["deleteprivatephoto"])
def cmd_deleteprivatephoto(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /deleteprivatephoto zp3")
        return
    pid = parts[1].lower()
    if not re.fullmatch(r"zp\d+", pid):
        bot.send_message(message.chat.id, "❌ Photo ID မမှန်ကန်ပါ။ ဥပမာ: /deleteprivatephoto zp3")
        return
    result = videos.delete_one({"_id": pid})
    if result.deleted_count == 0:
        bot.send_message(message.chat.id, f"❌ {pid} ကို database တွင် ရှာမတွေ့ပါ။")
        return
    settings.update_one({"_id": "z_photo_counter"}, {"$inc": {"count": -1}})
    bot.send_message(message.chat.id, f"🗑 Private Photo {pid} ကို database မှ ဖျက်ပြီးပါပြီ။")


# ─── Owner /setthumb ──────────────────────────────────────────────────────────
# Send a photo with caption "/setthumb v3" or "/setthumb z3" in the admin group.
# Owner can also use it in private chat.

@bot.message_handler(
    func=lambda m: (
        m.content_type == "photo"
        and m.from_user.id in OWNER_IDS
        and m.caption is not None
        and re.fullmatch(r"/setthumb\s+[vz]\d+", (m.caption or "").strip(), re.IGNORECASE)
    ),
    content_types=["photo"]
)
def cmd_setthumb(message):
    parts    = message.caption.strip().split()
    vid_id   = parts[1].lower()
    photo_id = message.photo[-1].file_id
    result   = videos.update_one({"_id": vid_id}, {"$set": {"thumbnail": photo_id}})
    if result.matched_count == 0:
        bot.send_message(message.chat.id, f"❌ {vid_id} ကို database တွင် ရှာမတွေ့ပါ။")
        return
    bot.send_message(message.chat.id, f"✅ {vid_id} အတွက် thumbnail သတ်မှတ်ပြီးပါပြီ။")


# ─── Owner /removethumb ───────────────────────────────────────────────────────
# Usage: /removethumb v3  or  /removethumb z3

@bot.message_handler(commands=["removethumb"])
def cmd_removethumb(message):
    if message.from_user.id not in OWNER_IDS:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /removethumb v3")
        return
    vid_id = parts[1].lower()
    result = videos.update_one({"_id": vid_id}, {"$unset": {"thumbnail": ""}})
    if result.matched_count == 0:
        bot.send_message(message.chat.id, f"❌ {vid_id} ကို database တွင် ရှာမတွေ့ပါ။")
        return
    bot.send_message(message.chat.id, f"✅ {vid_id} ၏ thumbnail ဖျက်ပြီးပါပြီ။")


# ─── Admin video ingestion (owner only, from the designated admin group) ──────

@bot.message_handler(
    func=lambda m: (
        m.content_type == "video"
        and m.from_user.id in OWNER_IDS
        and m.chat.id == get_admin_group_id()
    ),
    content_types=["video"]
)
def handle_admin_video(message):
    # Sender and group already verified by the func= filter above

    file_id        = message.video.file_id
    media_group_id = getattr(message, "media_group_id", None)
    caption        = message.caption or ""

    if media_group_id:
        with album_lock:
            buf = album_buffer[media_group_id]
            buf["file_ids"].append(file_id)
            if not buf["caption"] and caption:
                buf["caption"] = caption
            already_processing = buf["processed"]
            if not already_processing:
                buf["processed"] = True

        if not already_processing:
            def flush_album(mgid, chat_id):
                time.sleep(1.5)
                with album_lock:
                    b = album_buffer.pop(mgid, None)
                if not b:
                    return
                result = settings.find_one_and_update(
                    {"_id": "video_counter"},
                    {"$inc": {"count": 1}},
                    return_document=True
                )
                new_count = result["count"]
                vid_id    = f"v{new_count}"
                cap_text  = b["caption"] or f"Video {vid_id}"
                videos.insert_one({
                    "_id":            vid_id,
                    "type":           "album",
                    "media_group_id": mgid,
                    "caption":        cap_text,
                    "video_ids":      b["file_ids"],
                    "photo_ids":      b.get("photo_ids", []),
                    "likes":          0,
                    "dislikes":       0,
                    "views":          0,
                })
                photo_count = len(b.get("photo_ids", []))
                bot.send_message(
                    chat_id,
                    f"✅ စနစ်ထဲသို့ {vid_id} ဖြင့် အလိုအလျောက်သိမ်းဆည်းပြီးပါပြီ။"
                    + (f" (ပုံ {photo_count} ပုံ ပါဝင်)" if photo_count else "")
                )
                broadcast_new_content(vid_id)

            t = threading.Thread(target=flush_album, args=(media_group_id, message.chat.id), daemon=True)
            t.start()
    else:
        result = settings.find_one_and_update(
            {"_id": "video_counter"},
            {"$inc": {"count": 1}},
            return_document=True
        )
        new_count = result["count"]
        vid_id    = f"v{new_count}"
        cap_text  = caption or f"Video {vid_id}"
        videos.insert_one({
            "_id":      vid_id,
            "type":     "single",
            "caption":  cap_text,
            "video_ids": [file_id],
            "likes":    0,
            "dislikes": 0,
            "views":    0,
        })
        bot.send_message(
            message.chat.id,
            f"✅ စနစ်ထဲသို့ {vid_id} ဖြင့် အလိုအလျောက်သိမ်းဆည်းပြီးပါပြီ။"
        )
        broadcast_new_content(vid_id)

# ─── Private group video ingestion (owner + accepted users) ──────────────────

@bot.message_handler(
    func=lambda m: (
        m.content_type == "video"
        and is_user_accepted(m.from_user.id)
        and m.chat.id == get_private_admin_group_id()
    ),
    content_types=["video"]
)
def handle_private_admin_video(message):
    file_id        = message.video.file_id
    media_group_id = getattr(message, "media_group_id", None)
    caption        = message.caption or ""

    if media_group_id:
        with z_album_lock:
            buf = z_album_buffer[media_group_id]
            buf["file_ids"].append(file_id)
            if not buf["caption"] and caption:
                buf["caption"] = caption
            already_processing = buf["processed"]
            if not already_processing:
                buf["processed"] = True

        if not already_processing:
            def flush_z_album(mgid, chat_id):
                time.sleep(1.5)
                with z_album_lock:
                    b = z_album_buffer.pop(mgid, None)
                if not b:
                    return
                result = settings.find_one_and_update(
                    {"_id": "z_video_counter"},
                    {"$inc": {"count": 1}},
                    return_document=True
                )
                new_count = result["count"]
                vid_id    = f"z{new_count}"
                cap_text  = b["caption"] or f"Video {vid_id}"
                videos.insert_one({
                    "_id":            vid_id,
                    "type":           "album",
                    "media_group_id": mgid,
                    "caption":        cap_text,
                    "video_ids":      b["file_ids"],
                    "photo_ids":      b.get("photo_ids", []),
                    "private":        True,
                })
                photo_count = len(b.get("photo_ids", []))
                bot.send_message(
                    chat_id,
                    f"🔒 Private Video {vid_id} ကို အလိုအလျောက်သိမ်းဆည်းပြီးပါပြီ။"
                    + (f" (ပုံ {photo_count} ပုံ ပါဝင်)" if photo_count else "")
                )

            t = threading.Thread(target=flush_z_album, args=(media_group_id, message.chat.id), daemon=True)
            t.start()
    else:
        result = settings.find_one_and_update(
            {"_id": "z_video_counter"},
            {"$inc": {"count": 1}},
            return_document=True
        )
        new_count = result["count"]
        vid_id    = f"z{new_count}"
        cap_text  = caption or f"Video {vid_id}"
        videos.insert_one({
            "_id":      vid_id,
            "type":     "single",
            "caption":  cap_text,
            "video_ids": [file_id],
            "private":   True,
        })
        bot.send_message(
            message.chat.id,
            f"🔒 Private Video {vid_id} ကို အလိုအလျောက်သိမ်းဆည်းပြီးပါပြီ။"
        )


# ─── Public admin group photo ingestion (part of album with video) ───────────

@bot.message_handler(
    func=lambda m: (
        m.content_type == "photo"
        and m.from_user.id in OWNER_IDS
        and m.chat.id == get_admin_group_id()
        and getattr(m, "media_group_id", None) is not None
    ),
    content_types=["photo"]
)
def handle_admin_photo(message):
    media_group_id = message.media_group_id
    photo_file_id  = message.photo[-1].file_id  # largest available size
    with album_lock:
        album_buffer[media_group_id]["photo_ids"].append(photo_file_id)
        if not album_buffer[media_group_id]["caption"] and message.caption:
            album_buffer[media_group_id]["caption"] = message.caption


# ─── Private admin group photo ingestion (part of album with video) ──────────

@bot.message_handler(
    func=lambda m: (
        m.content_type == "photo"
        and is_user_accepted(m.from_user.id)
        and m.chat.id == get_private_admin_group_id()
        and getattr(m, "media_group_id", None) is not None
    ),
    content_types=["photo"]
)
def handle_private_admin_photo(message):
    media_group_id = message.media_group_id
    photo_file_id  = message.photo[-1].file_id
    with z_album_lock:
        z_album_buffer[media_group_id]["photo_ids"].append(photo_file_id)
        if not z_album_buffer[media_group_id]["caption"] and message.caption:
            z_album_buffer[media_group_id]["caption"] = message.caption


# ─── Public admin group standalone photo ingestion ────────────────────────────
# Saves solo photos (no media_group_id, no /setthumb caption) as p1, p2 …

@bot.message_handler(
    func=lambda m: (
        m.content_type == "photo"
        and m.from_user.id in OWNER_IDS
        and m.chat.id == get_admin_group_id()
        and getattr(m, "media_group_id", None) is None
        and not re.fullmatch(r"/setthumb\s+[vz]\d+", (m.caption or "").strip(), re.IGNORECASE)
    ),
    content_types=["photo"]
)
def handle_admin_standalone_photo(message):
    photo_file_id = message.photo[-1].file_id
    caption       = message.caption or ""
    result = settings.find_one_and_update(
        {"_id": "photo_counter"},
        {"$inc": {"count": 1}},
        return_document=True
    )
    new_count = result["count"]
    pid       = f"p{new_count}"
    cap_text  = caption or f"Photo {pid}"
    videos.insert_one({
        "_id":      pid,
        "type":     "photo_only",
        "caption":  cap_text,
        "photo_ids": [photo_file_id],
    })
    bot.send_message(
        message.chat.id,
        f"🖼 {pid} ဖြင့် ပုံ သိမ်းဆည်းပြီးပါပြီ။"
    )


# ─── Private admin group standalone photo ingestion ───────────────────────────
# Saves solo photos as zp1, zp2 … (accepted users + owner)

@bot.message_handler(
    func=lambda m: (
        m.content_type == "photo"
        and is_user_accepted(m.from_user.id)
        and m.chat.id == get_private_admin_group_id()
        and getattr(m, "media_group_id", None) is None
        and not re.fullmatch(r"/setthumb\s+[vz]\d+", (m.caption or "").strip(), re.IGNORECASE)
    ),
    content_types=["photo"]
)
def handle_private_admin_standalone_photo(message):
    photo_file_id = message.photo[-1].file_id
    caption       = message.caption or ""
    result = settings.find_one_and_update(
        {"_id": "z_photo_counter"},
        {"$inc": {"count": 1}},
        return_document=True
    )
    new_count = result["count"]
    pid       = f"zp{new_count}"
    cap_text  = caption or f"Photo {pid}"
    videos.insert_one({
        "_id":      pid,
        "type":     "photo_only",
        "caption":  cap_text,
        "photo_ids": [photo_file_id],
        "private":  True,
    })
    bot.send_message(
        message.chat.id,
        f"🔒 {pid} ဖြင့် Private ပုံ သိမ်းဆည်းပြီးပါပြီ။"
    )


# ─── Group photo search handler (pN) ─────────────────────────────────────────
# Handles pN pattern in groups/supergroups for public photos.

@bot.message_handler(
    func=lambda m: m.chat.type in ("group", "supergroup")
                   and m.text is not None
                   and re.fullmatch(r"p\d+", m.text.strip(), re.IGNORECASE) is not None,
    content_types=["text"]
)
def handle_group_photo_search(message):
    user_id = message.from_user.id
    doc     = users.find_one({"_id": user_id})
    if doc is None:
        doc = get_or_create_user(message.from_user)
    if user_id not in OWNER_IDS and doc.get("is_banned"):
        return
    if user_id not in OWNER_IDS and not doc.get("gender"):
        bot.send_message(
            message.chat.id,
            "⚠️ Bot ကို အသုံးပြုရန် ကျေးဇူးပြု၍ Private Chat တွင် /start နှိပ်ပြီး\n"
            "လိင်ရွေးချယ်မှုကို ဦးစွာ ပြုလုပ်ပေးပါ။",
            reply_to_message_id=message.message_id
        )
        return

    is_free = doc.get("is_free", False)
    limit   = doc.get("limit", 0)
    if not is_free and limit <= 0:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "🔗 Referral Link ယူပြီး Limit တိုးမည်",
            url=f"https://t.me/{BOT_USERNAME}?start={user_id}"
        ))
        bot.send_message(
            message.chat.id,
            "<b>⚠️ Limit ကုန်သွားပါပြီ</b>\n\n"
            "<blockquote>• Referral Link မျှဝေ၍ Limit တိုး နိုင်ပါသည်။</blockquote>",
            parse_mode='HTML',
            reply_markup=markup,
            reply_to_message_id=message.message_id
        )
        return

    text    = message.text.strip().lower()
    pid_doc = videos.find_one({"_id": text})
    if not pid_doc or pid_doc.get("type") != "photo_only":
        bot.send_message(
            message.chat.id,
            "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
            f"<blockquote>• Photo {h(text)} ကို ရှာမတွေ့ပါ။</blockquote>",
            parse_mode='HTML',
            reply_to_message_id=message.message_id
        )
        return

    if not is_free:
        users.update_one({"_id": user_id}, {"$inc": {"limit": -1}})

    caption   = pid_doc.get("caption", "")
    photo_ids = pid_doc.get("photo_ids", [])
    try:
        if len(photo_ids) == 1:
            bot.send_photo(message.chat.id, photo_ids[0], caption=caption, has_spoiler=True)
        else:
            grp = [telebot.types.InputMediaPhoto(fid, caption=caption if i == 0 else "", has_spoiler=True)
                   for i, fid in enumerate(photo_ids)]
            bot.send_media_group(message.chat.id, grp)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ ပုံပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")


# ─── Group photo search handler (zpN) ────────────────────────────────────────
# Handles zpN pattern — accepted users + owner only.

@bot.message_handler(
    func=lambda m: m.chat.type in ("group", "supergroup")
                   and m.text is not None
                   and re.fullmatch(r"zp\d+", m.text.strip(), re.IGNORECASE) is not None,
    content_types=["text"]
)
def handle_group_zphooto_search(message):
    user_id = message.from_user.id
    if not is_user_accepted(user_id):
        bot.send_message(
            message.chat.id,
            "🔒 ဤ ပုံများကို ကြည့်ရှုခွင့် မရှိပါ။",
            reply_to_message_id=message.message_id
        )
        return

    text    = message.text.strip().lower()
    pid_doc = videos.find_one({"_id": text})
    if not pid_doc or pid_doc.get("type") != "photo_only":
        bot.send_message(
            message.chat.id,
            "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
            f"<blockquote>• Photo {h(text)} ကို ရှာမတွေ့ပါ။</blockquote>",
            parse_mode='HTML',
            reply_to_message_id=message.message_id
        )
        return

    caption   = pid_doc.get("caption", "")
    photo_ids = pid_doc.get("photo_ids", [])
    try:
        if len(photo_ids) == 1:
            bot.send_photo(message.chat.id, photo_ids[0], caption=caption, has_spoiler=True)
        else:
            grp = [telebot.types.InputMediaPhoto(fid, caption=caption if i == 0 else "", has_spoiler=True)
                   for i, fid in enumerate(photo_ids)]
            bot.send_media_group(message.chat.id, grp)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ ပုံပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")


# ─── Group video search handler ───────────────────────────────────────────────
# Handles vN pattern in groups/supergroups. Profile/Share/Contact stay private.

@bot.message_handler(
    func=lambda m: m.chat.type in ("group", "supergroup")
                   and m.text is not None
                   and re.fullmatch(r"v\d+", m.text.strip(), re.IGNORECASE) is not None,
    content_types=["text"]
)
def handle_group_video_search(message):
    user_id = message.from_user.id
    text    = message.text.strip().lower()
    doc     = users.find_one({"_id": user_id})

    # Auto-register if not yet seen
    if doc is None:
        doc = get_or_create_user(message.from_user)

    # Ban check
    if user_id not in OWNER_IDS and doc.get("is_banned"):
        return

    if not is_user_channel_joined(user_id):
        send_channel_join_prompt(
            message.chat.id,
            reply_to_message_id=message.message_id
        )
        return

    # Gender gate — must have selected gender first (via private chat)
    if user_id not in OWNER_IDS and not doc.get("gender"):
        bot.send_message(
            message.chat.id,
            "⚠️ Bot ကို အသုံးပြုရန် ကျေးဇူးပြု၍ Private Chat တွင် /start နှိပ်ပြီး\n"
            "လိင်ရွေးချယ်မှုကို ဦးစွာ ပြုလုပ်ပေးပါ။",
            reply_to_message_id=message.message_id
        )
        return

    is_free = doc.get("is_free", False)
    limit   = doc.get("limit", 0)

    if not is_free and limit <= 0:
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "🔗 Referral Link ယူပြီး Limit တိုးမည်",
            url=f"https://t.me/{BOT_USERNAME}?start={user_id}"
        ))
        bot.send_message(
            message.chat.id,
            "<b>⚠️ 𝗟𝗶𝗺𝗶𝘁 𝗘𝘅𝗰𝗲𝗲𝗱𝗲𝗱</b>\n\n"
            f"<blockquote>• {h(message.from_user.first_name or 'User')}, ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 ကုန်ဆုံးပါပြီ။\n\n"
            "• သူငယ်ချင်းများ ဖိတ်ခေါ်ပြီး 𝗟𝗶𝗺𝗶𝘁 ထပ်ရယူနိုင်ပါသည်။</blockquote>",
            parse_mode='HTML',
            reply_to_message_id=message.message_id,
            reply_markup=markup
        )
        return

    vid_doc = videos.find_one({"_id": text})
    if not vid_doc:
        bot.send_message(
            message.chat.id,
            "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
            f"<blockquote>• 𝗩𝗶𝗱𝗲𝗼 {h(text)} ကို ရှာမတွေ့ပါ။\n"
            "• ဂဏန်းနံပါတ် မှန်မှန်ထည့်ပြီး ထပ်ကြိုးစားပါ။</blockquote>",
            parse_mode='HTML',
            reply_to_message_id=message.message_id
        )
        return

    # Loading animation
    bot.send_chat_action(message.chat.id, "upload_video")
    loading_msg = bot.send_message(
        message.chat.id,
        "⏳ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  ⬜⬜⬜⬜⬜  𝟬%",
        reply_to_message_id=message.message_id
    )
    time.sleep(1.5)
    try:
        bot.edit_message_text("⏳ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  🟨🟨🟨⬜⬜  𝟱𝟬%", message.chat.id, loading_msg.message_id)
    except Exception:
        pass
    time.sleep(1.5)
    try:
        bot.edit_message_text("✅ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  🟩🟩🟩🟩🟩  𝟭𝟬𝟬%", message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # Increment view count
    videos.update_one({"_id": text}, {"$inc": {"views": 1}})

    # Deduct limit
    if not is_free:
        result_upd = users.find_one_and_update(
            {"_id": user_id},
            {"$inc": {"limit": -1}},
            return_document=True
        )
        remaining = result_upd.get("limit", 0) if result_upd else 0
    else:
        remaining = None

    # Send video(s) in the group
    caption   = vid_doc.get("caption", "")
    file_ids  = vid_doc.get("video_ids", [])
    photo_ids = vid_doc.get("photo_ids", [])
    thumbnail = vid_doc.get("thumbnail")
    if thumbnail:
        try:
            bot.send_photo(message.chat.id, thumbnail, caption=f"🖼 {caption}" if caption else None, has_spoiler=True)
        except Exception:
            pass
    try:
        if vid_doc["type"] == "single":
            bot.send_video(message.chat.id, file_ids[0], caption=caption if not thumbnail else "", has_spoiler=True)
        else:
            media_group = [
                telebot.types.InputMediaVideo(fid, caption=caption if i == 0 and not thumbnail else "", has_spoiler=True)
                for i, fid in enumerate(file_ids)
            ]
            bot.send_media_group(message.chat.id, media_group)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Video ပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")

    if photo_ids:
        try:
            if len(photo_ids) == 1:
                bot.send_photo(message.chat.id, photo_ids[0], has_spoiler=True)
            else:
                photo_group = [
                    telebot.types.InputMediaPhoto(fid, has_spoiler=True)
                    for fid in photo_ids
                ]
                bot.send_media_group(message.chat.id, photo_group)
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ ပုံပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")

    try:
        bot.delete_message(message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # Rating buttons
    try:
        bot.send_message(
            message.chat.id,
            f"<b>⭐ {h(text)}</b> — မဲပေးနိုင်ပါသည်",
            parse_mode='HTML',
            reply_markup=rating_markup(text)
        )
    except Exception:
        pass

    # Limit warning
    if remaining is not None and remaining == 3:
        try:
            bot.send_message(
                message.chat.id,
                "<b>⚠️ 𝗟𝗶𝗺𝗶𝘁 သတိပေးချက်</b>\n\n"
                "<blockquote>• ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 <b>𝟯</b> သာ ကျန်တော့သည်။\n"
                "• သူငယ်ချင်း ဖိတ်ခေါ်ပြီး Limit ထပ်တိုးနိုင်သည်။</blockquote>",
                parse_mode='HTML',
                reply_markup=share_markup(user_id),
                reply_to_message_id=message.message_id
            )
        except Exception:
            pass


# ─── Group z-video search handler (accepted users + owner only) ───────────────
# Handles zN pattern in groups/supergroups for private videos.

@bot.message_handler(
    func=lambda m: m.chat.type in ("group", "supergroup")
                   and m.text is not None
                   and re.fullmatch(r"z\d+", m.text.strip(), re.IGNORECASE) is not None,
    content_types=["text"]
)
def handle_group_z_video_search(message):
    user_id = message.from_user.id
    doc     = users.find_one({"_id": user_id})

    # Ban check
    if user_id not in OWNER_IDS and doc and doc.get("is_banned"):
        return

    # Only owner + accepted users can search z-videos
    if not is_user_accepted(user_id):
        bot.send_message(
            message.chat.id,
            "🔒 ဤ video များကို ကြည့်ရှုခွင့် မရှိပါ။",
            reply_to_message_id=message.message_id
        )
        return

    text    = message.text.strip().lower()
    doc     = users.find_one({"_id": user_id})
    if doc is None:
        doc = get_or_create_user(message.from_user)

    vid_doc = videos.find_one({"_id": text})
    if not vid_doc:
        bot.send_message(
            message.chat.id,
            "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
            f"<blockquote>• 𝗩𝗶𝗱𝗲𝗼 {h(text)} ကို ရှာမတွေ့ပါ။\n"
            "• ဂဏန်းနံပါတ် မှန်မှန်ထည့်ပြီး ထပ်ကြိုးစားပါ။</blockquote>",
            parse_mode='HTML',
            reply_to_message_id=message.message_id
        )
        return

    # Loading animation
    bot.send_chat_action(message.chat.id, "upload_video")
    loading_msg = bot.send_message(
        message.chat.id,
        "⏳ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  ⬜⬜⬜⬜⬜  𝟬%",
        reply_to_message_id=message.message_id
    )
    time.sleep(1.5)
    try:
        bot.edit_message_text("⏳ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  🟨🟨🟨⬜⬜  𝟱𝟬%", message.chat.id, loading_msg.message_id)
    except Exception:
        pass
    time.sleep(1.5)
    try:
        bot.edit_message_text("✅ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  🟩🟩🟩🟩🟩  𝟭𝟬𝟬%", message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # Increment view count
    videos.update_one({"_id": text}, {"$inc": {"views": 1}})

    caption   = vid_doc.get("caption", "")
    file_ids  = vid_doc.get("video_ids", [])
    photo_ids = vid_doc.get("photo_ids", [])
    thumbnail = vid_doc.get("thumbnail")
    if thumbnail:
        try:
            bot.send_photo(message.chat.id, thumbnail, caption=f"🖼 {caption}" if caption else None, has_spoiler=True)
        except Exception:
            pass
    try:
        if vid_doc["type"] == "single":
            bot.send_video(message.chat.id, file_ids[0], caption=caption if not thumbnail else "", has_spoiler=True)
        else:
            media_group = [
                telebot.types.InputMediaVideo(fid, caption=caption if i == 0 and not thumbnail else "", has_spoiler=True)
                for i, fid in enumerate(file_ids)
            ]
            bot.send_media_group(message.chat.id, media_group)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Video ပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")

    if photo_ids:
        try:
            if len(photo_ids) == 1:
                bot.send_photo(message.chat.id, photo_ids[0], has_spoiler=True)
            else:
                photo_group = [
                    telebot.types.InputMediaPhoto(fid, has_spoiler=True)
                    for fid in photo_ids
                ]
                bot.send_media_group(message.chat.id, photo_group)
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ ပုံပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")

    try:
        bot.delete_message(message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # Rating buttons for group z-video
    try:
        bot.send_message(
            message.chat.id,
            f"<b>⭐ {h(text)}</b> — မဲပေးနိုင်ပါသည်",
            parse_mode='HTML',
            reply_markup=rating_markup(text)
        )
    except Exception:
        pass


# ─── General message handler (private) ───────────────────────────────────────

@bot.message_handler(func=lambda m: m.chat.type == "private", content_types=["text"])
def handle_text(message):
    user_id  = message.from_user.id
    text     = message.text.strip()
    doc      = users.find_one({"_id": user_id})

    if doc is None:
        doc = get_or_create_user(message.from_user)

    state = doc.get("state", "normal")

    # ── Ban check ─────────────────────────────────────────────────────────────
    if user_id not in OWNER_IDS and doc.get("is_banned"):
        bot.send_message(
            message.chat.id,
            "🚫 သင်သည် ဤ Bot ကို အသုံးပြုခွင့် ပိတ်ဆို့ထားပါသည်။"
        )
        return

    if not is_user_channel_joined(user_id):
        users.update_one(
            {"_id": user_id},
            {"$set": {
                "pending_channel_action": text
            }}
        )
        send_channel_join_prompt(message.chat.id)
        return

    # ── Daily bonus check ─────────────────────────────────────────────────────
    if check_daily_bonus(user_id):
        bot.send_message(
            message.chat.id,
            "<b>🎁 𝗗𝗮𝗶𝗹𝘆 𝗕𝗼𝗻𝘂𝘀!</b>\n\n"
            "<blockquote>• ယနေ့ Bot ဝင်ရောက်သဖြင့်\n"
            "  ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 +𝟮 ရပါပြီ! ✅</blockquote>",
            parse_mode='HTML'
        )
        doc = users.find_one({"_id": user_id})

    # ── Gender gate — must select before using bot ────────────────────────────
    if user_id not in OWNER_IDS and not doc.get("gender"):
        if text not in ("❌ Cancel", "⬅️ Back"):
            bot.send_message(
                message.chat.id,
                "<b>🔞 𝗔𝗴𝗲 𝗩𝗲𝗿𝗶𝗳𝗶𝗰𝗮𝘁𝗶𝗼𝗻</b>\n\n"
                "<blockquote>• Bot ကို အသုံးပြုရန် အောက်မှ လိင်တစ်ခုခုကို ရွေးချယ်ပေးပါ ခင်ဗျာ။</blockquote>",
                parse_mode='HTML',
                reply_markup=gender_selection_markup()
            )
            return

    # ── ❌ Cancel / ⬅️ Back — exits any active state back to main menu ─────────
    if text in ("❌ Cancel", "⬅️ Back"):
        users.update_one({"_id": user_id}, {"$set": {"state": "normal"}})
        if user_id in broadcast_targets:
            broadcast_targets.pop(user_id)
        bot.send_message(
            message.chat.id,
            "🏠 Main menu သို့ ပြန်ရောက်ပါပြီ။",
            reply_markup=main_menu_keyboard()
        )
        send_welcome(message.chat.id, user_id)
        return

    # ── Owner broadcast reply step ────────────────────────────────────────────
    if user_id in OWNER_IDS and user_id in broadcast_targets:
        target = broadcast_targets.pop(user_id)

        if target == "all":
            # ── Broadcast to every registered user ───────────────────────────
            all_ids    = [u["_id"] for u in users.find({}, {"_id": 1})]
            sent_ok    = 0
            sent_fail  = 0
            status_msg = bot.send_message(
                message.chat.id,
                f"⏳ ပေးပို့နေပါသည်... 0 / {len(all_ids)}"
            )
            for i, uid in enumerate(all_ids, 1):
                try:
                    bot.send_message(
                        uid,
                        "<b>📢 𝗔𝗻𝗻𝗼𝘂𝗻𝗰𝗲𝗺𝗲𝗻𝘁</b>\n\n"
                        + f"<blockquote>{h(text)}</blockquote>",
                        parse_mode='HTML'
                    )
                    sent_ok += 1
                except Exception:
                    sent_fail += 1
                # Update progress every 20 users to avoid flood
                if i % 20 == 0:
                    try:
                        bot.edit_message_text(
                            f"⏳ ပေးပို့နေပါသည်... {i} / {len(all_ids)}",
                            message.chat.id, status_msg.message_id
                        )
                    except Exception:
                        pass
            try:
                bot.edit_message_text(
                    f"✅ Broadcast ပြီးပါပြီ\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"✔ အောင်မြင်: {sent_ok} ဦး\n"
                    f"✘ မအောင်မြင်: {sent_fail} ဦး",
                    message.chat.id, status_msg.message_id
                )
            except Exception:
                pass
        else:
            # ── Broadcast to one specific user ────────────────────────────────
            try:
                bot.send_message(
                    target,
                    "<b>📩 𝗢𝘄𝗻𝗲𝗿 𝗠𝗲𝘀𝘀𝗮𝗴𝗲</b>\n\n"
                    + f"<blockquote>{h(text)}</blockquote>",
                    parse_mode='HTML'
                )
                bot.send_message(
                    message.chat.id,
                    f"✅ User {target} ထံ ပေးပို့ပြီးပါပြီ။",
                    reply_markup=main_menu_keyboard()
                )
            except Exception as e:
                bot.send_message(
                    message.chat.id,
                    f"❌ ပေးပို့မှု မအောင်မြင်ပါ: {e}",
                    reply_markup=main_menu_keyboard()
                )
        return

    # ── Contact state ─────────────────────────────────────────────────────────
    if state == "waiting_contact":
        users.update_one({"_id": user_id}, {"$set": {"state": "normal"}})
        bot.send_message(
            message.chat.id,
            "<b>✅ 𝗦𝗲𝗻𝘁 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆</b>\n\n"
            "<blockquote>• လူကြီးမင်းပေးပို့သော စာသားသည်\n"
            "  𝗕𝗼𝘁 𝗢𝘄𝗻𝗲𝗿 ထံ ရောက်ရှိသွားပါပြီ ✅</blockquote>",
            parse_mode='HTML',
            reply_markup=main_menu_keyboard()
        )
        uname = doc.get("username") or ""
        fname = doc.get("first_name") or ""
        for oid in OWNER_IDS:
            try:
                bot.send_message(
                    oid,
                    "<b>📩 𝗨𝘀𝗲𝗿 𝗠𝗲𝘀𝘀𝗮𝗴𝗲</b>\n\n"
                    f"<blockquote>• 𝗡𝗮𝗺𝗲  ——  {h(fname)}\n"
                    f"• 𝗨𝘀𝗲𝗿𝗻𝗮𝗺𝗲  ——  @{h(uname)}\n"
                    f"• 𝗜𝗗  ——  {user_id}\n\n"
                    f"💬 𝗠𝗲𝘀𝘀𝗮𝗴𝗲:\n{h(text)}</blockquote>",
                    parse_mode='HTML'
                )
            except Exception:
                pass
        return

    # ── Menu button: 👤 Profile ───────────────────────────────────────────────
    if text == "👤 Profile":
        display_name = doc.get("username") or doc.get("first_name") or str(user_id)
        limit_str    = "∞ Unlimited" if doc.get("is_free") else str(doc.get("limit", 0))
        bot.send_message(
            message.chat.id,
            "<b>👤 𝗠𝘆 𝗣𝗿𝗼𝗳𝗶𝗹𝗲</b>\n\n"
            f"<blockquote>• 𝗡𝗮𝗺𝗲  ——  {h(display_name)}\n"
            f"• 𝗜𝗗  ——  {user_id}\n"
            f"• 𝗟𝗶𝗺𝗶𝘁  ——  {h(limit_str)}\n"
            f"• 𝗦𝗵𝗮𝗿𝗲𝘀  ——  {doc.get('shares', 0)} ဦး</blockquote>",
            parse_mode='HTML'
        )
        return

    # ── Menu button: 🔗 Share & Refer ─────────────────────────────────────────
    if text == "🔗 Share & Refer":
        share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}?start={user_id}"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 𝗦𝗵𝗮𝗿𝗲 𝗟𝗶𝗻𝗸 ကူးယူပါ", url=share_url))
        bot.send_message(
            message.chat.id,
            "<b>🔗 𝗦𝗵𝗮𝗿𝗲 &amp; 𝗥𝗲𝗳𝗲𝗿</b>\n\n"
            "<blockquote>• သူငယ်ချင်းများကို ဖိတ်ခေါ်ပြီး\n"
            "  ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 ထပ်ရယူနိုင်ပါသည်။\n\n"
            f"⚡️ တစ်ဦး Join ဖြစ်တိုင်း ——— 𝗟𝗶𝗺𝗶𝘁 +𝟱 ရမည်\n\n"
            f"🔗 𝗬𝗼𝘂𝗿 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹 𝗟𝗶𝗻𝗸:\n"
            f"https://t.me/{BOT_USERNAME}?start={user_id}</blockquote>",
            parse_mode='HTML',
            reply_markup=markup
        )
        return

    # ── Menu button: 📹 Videos Update ────────────────────────────────────────
    if text == "📹 Videos Update":
        total = get_total_videos()
        bot.send_message(
            message.chat.id,
            "<b>🔄 𝗩𝗶𝗱𝗲𝗼𝘀 𝗨𝗽𝗱𝗮𝘁𝗲</b>\n\n"
            f"<blockquote>• လက်ရှိ ဗီဒီယိုအရေအတွက် ——— 𝟬{total} ခု\n\n"
            f"• v1 မှ v{total} အထိ ရှာဖွေနိုင်ပါသည်။</blockquote>",
            parse_mode='HTML'
        )
        return

    # ── Menu button: 📞 Contact Owner ─────────────────────────────────────────
    if text == "📞 Contact Owner":
        users.update_one({"_id": user_id}, {"$set": {"state": "waiting_contact"}})
        bot.send_message(
            message.chat.id,
            "<b>📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿</b>\n\n"
            "<blockquote>• 𝗕𝗼𝘁 𝗢𝘄𝗻𝗲𝗿 ထံ ပေးပို့လိုသည့် စာသားကို\n"
            "  ရိုက်ထည့်ပြီး ပေးပို့နိုင်ပါပြီ ခင်ဗျာ။\n\n"
            "• မပို့လိုပါက ❌ Cancel ကိုနှိပ်ပါ။</blockquote>",
            parse_mode='HTML',
            reply_markup=cancel_keyboard()
        )
        return

    # ── Menu button: 🏆 Top Videos ────────────────────────────────────────────
    if text == "🏆 Top Videos":
        bot.send_message(
            message.chat.id,
            get_top_videos_text(10),
            parse_mode='HTML'
        )
        return

    # ── Video search (vN pattern) ─────────────────────────────────────────────
    if re.fullmatch(r"v\d+", text, re.IGNORECASE):
        vid_key = text.lower()
        is_free = doc.get("is_free", False)
        limit   = doc.get("limit", 0)

        if not is_free and limit <= 0:
            bot.send_message(
                message.chat.id,
                "<b>⚠️ 𝗟𝗶𝗺𝗶𝘁 𝗘𝘅𝗰𝗲𝗲𝗱𝗲𝗱</b>\n\n"
                "<blockquote>• ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 ကုန်ဆုံးသွားပါပြီ။\n\n"
                "• သူငယ်ချင်းများ ဖိတ်ခေါ်ပြီး\n"
                "  𝗟𝗶𝗺𝗶𝘁 ထပ်ရယူနိုင်ပါသည်။</blockquote>",
                parse_mode='HTML',
                reply_markup=share_markup(user_id)
            )
            return

        vid_doc = videos.find_one({"_id": vid_key})
        if not vid_doc:
            bot.send_message(
                message.chat.id,
                "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
                f"<blockquote>• 𝗩𝗶𝗱𝗲𝗼 {h(vid_key)} ကို ရှာမတွေ့ပါ ခင်ဗျာ။\n"
                "• ဂဏန်းနံပါတ် မှန်မှန်ထည့်ပြီး ထပ်ကြိုးစားပါ။</blockquote>",
                parse_mode='HTML'
            )
            return

        # Anti-spam animation
        bot.send_chat_action(message.chat.id, "upload_video")
        loading_msg = bot.send_message(
            message.chat.id,
            "⏳ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  ⬜⬜⬜⬜⬜  𝟬%"
        )
        time.sleep(1.5)
        try:
            bot.edit_message_text(
                "⏳ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  🟨🟨🟨⬜⬜  𝟱𝟬%",
                message.chat.id, loading_msg.message_id
            )
        except Exception:
            pass
        time.sleep(1.5)
        try:
            bot.edit_message_text(
                "✅ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  🟩🟩🟩🟩🟩  𝟭𝟬𝟬%",
                message.chat.id, loading_msg.message_id
            )
        except Exception:
            pass

        # Increment view count
        videos.update_one({"_id": vid_key}, {"$inc": {"views": 1}})

        # Deduct limit
        if not is_free:
            result_upd = users.find_one_and_update(
                {"_id": user_id},
                {"$inc": {"limit": -1}},
                return_document=True
            )
            remaining = result_upd.get("limit", 0) if result_upd else 0
        else:
            remaining = None

        # Send video(s)
        caption   = vid_doc.get("caption", "")
        file_ids  = vid_doc.get("video_ids", [])
        photo_ids = vid_doc.get("photo_ids", [])
        thumbnail = vid_doc.get("thumbnail")
        if thumbnail:
            try:
                bot.send_photo(message.chat.id, thumbnail, caption=f"🖼 {caption}" if caption else None, has_spoiler=True)
            except Exception:
                pass

        if vid_doc["type"] == "single":
            bot.send_video(message.chat.id, file_ids[0], caption=caption if not thumbnail else "", has_spoiler=True)
        else:
            media_group = [
                telebot.types.InputMediaVideo(fid, caption=caption if i == 0 and not thumbnail else "", has_spoiler=True)
                for i, fid in enumerate(file_ids)
            ]
            bot.send_media_group(message.chat.id, media_group)

        if photo_ids:
            try:
                if len(photo_ids) == 1:
                    bot.send_photo(message.chat.id, photo_ids[0], has_spoiler=True)
                else:
                    photo_group = [
                        telebot.types.InputMediaPhoto(fid, has_spoiler=True)
                        for fid in photo_ids
                    ]
                    bot.send_media_group(message.chat.id, photo_group)
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ ပုံပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")

        # Delete loading message
        try:
            bot.delete_message(message.chat.id, loading_msg.message_id)
        except Exception:
            pass

        # Rating buttons
        try:
            bot.send_message(
                message.chat.id,
                f"<b>⭐ {h(vid_key)}</b> — မဲပေးနိုင်ပါသည်",
                parse_mode='HTML',
                reply_markup=rating_markup(vid_key)
            )
        except Exception:
            pass

        # Limit warning
        if remaining is not None and remaining == 3:
            bot.send_message(
                message.chat.id,
                "<b>⚠️ 𝗟𝗶𝗺𝗶𝘁 သတိပေးချက်</b>\n\n"
                "<blockquote>• ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 <b>𝟯</b> သာ ကျန်တော့သည်။\n"
                "• သူငယ်ချင်း ဖိတ်ခေါ်ပြီး Limit ထပ်တိုးနိုင်သည်။</blockquote>",
                parse_mode='HTML',
                reply_markup=share_markup(user_id)
            )

        return

    # ── Private video search (zN pattern) — owner + accepted users only ─────────
    if re.fullmatch(r"z\d+", text, re.IGNORECASE):
        if not is_user_accepted(user_id):
            bot.send_message(
                message.chat.id,
                "🔒 ဤ video များကို ကြည့်ရှုခွင့် မရှိပါ။"
            )
            return

        vid_key = text.lower()
        vid_doc = videos.find_one({"_id": vid_key})
        if not vid_doc:
            bot.send_message(
                message.chat.id,
                "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
                f"<blockquote>• 𝗩𝗶𝗱𝗲𝗼 {h(vid_key)} ကို ရှာမတွေ့ပါ ခင်ဗျာ။\n"
                "• ဂဏန်းနံပါတ် မှန်မှန်ထည့်ပြီး ထပ်ကြိုးစားပါ။</blockquote>",
                parse_mode='HTML'
            )
            return

        bot.send_chat_action(message.chat.id, "upload_video")
        loading_msg = bot.send_message(
            message.chat.id,
            "⏳ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  ⬜⬜⬜⬜⬜  𝟬%"
        )
        time.sleep(1.5)
        try:
            bot.edit_message_text(
                "⏳ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  🟨🟨🟨⬜⬜  𝟱𝟬%",
                message.chat.id, loading_msg.message_id
            )
        except Exception:
            pass
        time.sleep(1.5)
        try:
            bot.edit_message_text(
                "✅ 𝗟𝗼𝗮𝗱𝗶𝗻𝗴...  🟩🟩🟩🟩🟩  𝟭𝟬𝟬%",
                message.chat.id, loading_msg.message_id
            )
        except Exception:
            pass

        caption   = vid_doc.get("caption", "")
        file_ids  = vid_doc.get("video_ids", [])
        photo_ids = vid_doc.get("photo_ids", [])
        thumbnail = vid_doc.get("thumbnail")
        if thumbnail:
            try:
                bot.send_photo(message.chat.id, thumbnail, caption=f"🖼 {caption}" if caption else None, has_spoiler=True)
            except Exception:
                pass

        if vid_doc["type"] == "single":
            bot.send_video(message.chat.id, file_ids[0], caption=caption if not thumbnail else "", has_spoiler=True)
        else:
            media_group = [
                telebot.types.InputMediaVideo(fid, caption=caption if i == 0 and not thumbnail else "", has_spoiler=True)
                for i, fid in enumerate(file_ids)
            ]
            bot.send_media_group(message.chat.id, media_group)

        if photo_ids:
            try:
                if len(photo_ids) == 1:
                    bot.send_photo(message.chat.id, photo_ids[0], has_spoiler=True)
                else:
                    photo_group = [
                        telebot.types.InputMediaPhoto(fid, has_spoiler=True)
                        for fid in photo_ids
                    ]
                    bot.send_media_group(message.chat.id, photo_group)
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ ပုံပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")

        try:
            bot.delete_message(message.chat.id, loading_msg.message_id)
        except Exception:
            pass

        # Rating buttons for private zN
        try:
            bot.send_message(
                message.chat.id,
                f"<b>⭐ {h(vid_key)}</b> — မဲပေးနိုင်ပါသည်",
                parse_mode='HTML',
                reply_markup=rating_markup(vid_key)
            )
        except Exception:
            pass

        return

    # ── Public photo search (pN pattern) ─────────────────────────────────────
    if re.fullmatch(r"p\d+", text, re.IGNORECASE):
        is_free = doc.get("is_free", False)
        limit   = doc.get("limit", 0)
        if not is_free and limit <= 0:
            bot.send_message(
                message.chat.id,
                "<b>⚠️ 𝗟𝗶𝗺𝗶𝘁 𝗘𝘅𝗰𝗲𝗲𝗱𝗲𝗱</b>\n\n"
                "<blockquote>• ကြည့်ရှုခွင့် 𝗟𝗶𝗺𝗶𝘁 ကုန်ဆုံးသွားပါပြီ။\n\n"
                "• သူငယ်ချင်းများ ဖိတ်ခေါ်ပြီး\n"
                "  𝗟𝗶𝗺𝗶𝘁 ထပ်ရယူနိုင်ပါသည်။</blockquote>",
                parse_mode='HTML',
                reply_markup=share_markup(user_id)
            )
            return
        pid_key = text.lower()
        pid_doc = videos.find_one({"_id": pid_key})
        if not pid_doc or pid_doc.get("type") != "photo_only":
            bot.send_message(
                message.chat.id,
                "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
                f"<blockquote>• Photo {h(pid_key)} ကို ရှာမတွေ့ပါ ခင်ဗျာ။</blockquote>",
                parse_mode='HTML'
            )
            return
        if not is_free:
            users.update_one({"_id": user_id}, {"$inc": {"limit": -1}})
        caption   = pid_doc.get("caption", "")
        photo_ids = pid_doc.get("photo_ids", [])
        try:
            if len(photo_ids) == 1:
                bot.send_photo(message.chat.id, photo_ids[0], caption=caption, has_spoiler=True)
            else:
                grp = [telebot.types.InputMediaPhoto(fid, caption=caption if i == 0 else "", has_spoiler=True)
                       for i, fid in enumerate(photo_ids)]
                bot.send_media_group(message.chat.id, grp)
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ ပုံပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")
        return

    # ── Private photo search (zpN pattern) — owner + accepted users only ─────
    if re.fullmatch(r"zp\d+", text, re.IGNORECASE):
        if not is_user_accepted(user_id):
            bot.send_message(
                message.chat.id,
                "🔒 ဤ ပုံများကို ကြည့်ရှုခွင့် မရှိပါ။"
            )
            return
        pid_key = text.lower()
        pid_doc = videos.find_one({"_id": pid_key})
        if not pid_doc or pid_doc.get("type") != "photo_only":
            bot.send_message(
                message.chat.id,
                "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
                f"<blockquote>• Photo {h(pid_key)} ကို ရှာမတွေ့ပါ ခင်ဗျာ။</blockquote>",
                parse_mode='HTML'
            )
            return
        caption   = pid_doc.get("caption", "")
        photo_ids = pid_doc.get("photo_ids", [])
        try:
            if len(photo_ids) == 1:
                bot.send_photo(message.chat.id, photo_ids[0], caption=caption, has_spoiler=True)
            else:
                grp = [telebot.types.InputMediaPhoto(fid, caption=caption if i == 0 else "", has_spoiler=True)
                       for i, fid in enumerate(photo_ids)]
                bot.send_media_group(message.chat.id, grp)
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ ပုံပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")
        return

    # ── Fallback: show welcome ─────────────────────────────────────────────────
    send_welcome(message.chat.id, user_id)


# ─── RATING CALLBACKS ─────────────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda c: c.data == "noop")
def cb_noop(call):
    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda c: c.data.startswith("rate_") and (c.data.endswith("_like") or c.data.endswith("_dislike")))
def cb_rate(call):
    parts   = call.data.split("_")
    action  = parts[-1]
    vid_id  = "_".join(parts[1:-1])
    user_id = call.from_user.id

    if action == "like":
        field = "likes"
    else:
        field = "dislikes"

    result = videos.find_one_and_update(
        {"_id": vid_id},
        {"$inc": {field: 1}},
        return_document=True
    )
    if not result:
        bot.answer_callback_query(call.id, "❌ Video ရှာမတွေ့ပါ")
        return

    likes    = result.get("likes", 0)
    dislikes = result.get("dislikes", 0)
    views    = result.get("views", 0)

    new_markup = InlineKeyboardMarkup(row_width=3)
    new_markup.add(
        InlineKeyboardButton(f"👍 {likes}",    callback_data=f"rate_{vid_id}_like", style="success"),
        InlineKeyboardButton(f"👎 {dislikes}", callback_data=f"rate_{vid_id}_dislike", style="danger"),
        InlineKeyboardButton(f"👁 {views}",    callback_data="noop", style="primary"),
    )
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=new_markup)
    except Exception:
        pass

    emoji = "👍" if action == "like" else "👎"
    bot.answer_callback_query(call.id, f"{emoji} မဲပေးပြီးပါပြီ!")

# ─── WEBHOOK + KEEP-ALIVE SERVER ──────────────────────────────────────────────
# Webhook mode: Telegram POSTs updates to /webhook.
# No polling → no 409 Conflict even when Render spins up a new instance.
# GET / → UptimeRobot keep-alive (always returns 200).

class WebhookHandler(BaseHTTPRequestHandler):

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def do_GET(self):
        body = b"Blue Bot is Alive!"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path == "/webhook":
            length  = int(self.headers.get("Content-Length", 0))
            payload = self.rfile.read(length)
            try:
                update = telebot.types.Update.de_json(json.loads(payload))
                bot.process_new_updates([update])
            except Exception as e:
                print(f"Update processing error: {e}")
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # silence access logs


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))

    # RENDER_EXTERNAL_URL is set automatically by Render, e.g.
    # https://blue-bot-qz5f.onrender.com
    # You can also set WEBHOOK_URL manually in Render env vars.
    base_url    = (
        os.environ.get("WEBHOOK_URL")
        or os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    )
    webhook_url = f"{base_url}/webhook"

    # Register webhook with Telegram (replaces any previous polling session).
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
    print(f"Webhook set → {webhook_url}")

    server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"Blue Bot webhook server running on port {port}.")
    server.serve_forever()
