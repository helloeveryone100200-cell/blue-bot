import os
import re
import time
import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from pymongo import MongoClient

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

ensure_video_counter()

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

# ─── BOT INIT ─────────────────────────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# Fetch bot username dynamically from Telegram (no env var needed)
BOT_USERNAME = bot.get_me().username

# ─── IN-MEMORY STATE ──────────────────────────────────────────────────────────
# Tracks media groups being buffered: {media_group_id: {"file_ids": [], "caption": "", "processed": bool}}
album_buffer = defaultdict(lambda: {"file_ids": [], "caption": "", "processed": False})
album_lock   = threading.Lock()

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
        KeyboardButton("👤 Profile"),
        KeyboardButton("🔗 Share & Refer"),
    )
    markup.add(
        KeyboardButton("📹 Videos Update"),
        KeyboardButton("📞 Contact Owner"),
    )
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ Cancel"))
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

def send_welcome(chat_id, user_id):
    total = get_total_videos()
    text = (
        "welcome from Blue Bot\n\n"
        "ဒီbotက မင်းရဲ့စိတ်ကိုဖြေလျော့ဖို့အတွက်အလွယ်တကူ videosများရှာဖွေကြည့်ရှုနိုင်ပါတယ်။\n\n"
        f"📹 လက်ရှိ Videos အရေအတွက်: {total} ခု\n"
        f"videos ရှာလိုပါက v1, v2, v3 စသဖြင့် v အနောက်တွင် နံပါတ်ထည့်ပြီး ရိုက်ရှာနိုင်ပါသည်။\n\n"
        "📹 Videos Update ခလုတ်ဖြင့် နောက်ဆုံး videos အရေအတွက် update ကို အချိန်မရွေး စစ်ဆေးနိုင်ပါသည်။"
    )
    bot.send_message(chat_id, text,
                     reply_markup=welcome_markup(user_id))

# ─── /start ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    args     = message.text.split()
    new_user = message.from_user
    doc      = users.find_one({"_id": new_user.id})
    is_new   = doc is None

    if is_new:
        get_or_create_user(new_user)

    # Referral logic (works from any chat)
    if len(args) > 1 and is_new:
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
                            "🎉 အဖွဲ့ဝင်အသစ်တစ်ယောက် ဖိတ်ခေါ်မှုအောင်မြင်သဖြင့် "
                            "ကြည့်ရှုခွင့် Limit 5 ခု တိုးပေးလိုက်ပါပြီ။"
                        )
                    except Exception:
                        pass
        except (ValueError, TypeError):
            pass

    users.update_one({"_id": new_user.id}, {"$set": {"state": "normal"}})

    if message.chat.type == "private":
        # Private: show full persistent keyboard + welcome
        bot.send_message(message.chat.id, "🎉 Blue Bot へ ကြိုဆိုပါတယ်!", reply_markup=main_menu_keyboard())
        send_welcome(message.chat.id, new_user.id)
    else:
        # Group: register confirmation + usage hint (no keyboard spam)
        total   = get_total_videos()
        fname   = new_user.first_name or new_user.username or str(new_user.id)
        markup  = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton(
            "🤖 Bot ကို Private တွင် ဖွင့်မည်",
            url=f"https://t.me/{BOT_USERNAME}?start={new_user.id}"
        ))
        bot.send_message(
            message.chat.id,
            f"👋 {fname} မင်္ဂလာပါ! Blue Bot တွင် မှတ်ပုံတင်ပြီးပါပြီ။\n\n"
            f"📹 Video {total} ခု ရှိပါသည်။\n"
            f"ဤ group တွင် v1, v2, v3 … ရိုက်ပြီး video ရှာနိုင်ပါသည်။\n\n"
            f"👤 Profile / Share / Contact — Private chat တွင်သာ ရနိုင်ပါသည်။",
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
    limit_str    = "Infinity" if doc.get("is_free") else str(doc.get("limit", 0))

    text = (
        "My Profile (unique)\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n\n"
        f"အမည်: {display_name}\n\n"
        f"အကောင့် ID: {user_id}\n\n"
        f"limit: {limit_str}\n\n"
        f"Share: {doc.get('shares', 0)}"
    )
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, text)

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
    total_users  = users.count_documents({})
    total_shares = sum(d.get("shares", 0) for d in users.find({}, {"shares": 1}))
    total_vids   = get_total_videos()
    bot.send_message(
        message.chat.id,
        f"📊 Bot Stats\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: {total_users}\n"
        f"🔗 Total Shares: {total_shares}\n"
        f"🎬 Total Videos: {total_vids}"
    )

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
        f"✅ User {target_id} limit {action} ထည့်ပြီးပါပြီ။\n"
        f"New limit: {new_limit}"
    )
    try:
        bot.send_message(
            target_id,
            f"🎁 Owner မှ ကြည့်ရှုခွင့် Limit {action} ခု ထည့်ပေးလိုက်ပါပြီ။\n"
            f"လက်ရှိ Limit: {new_limit}"
        )
    except Exception:
        pass

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
                })
                bot.send_message(
                    chat_id,
                    f"✅ စနစ်ထဲသို့ {vid_id} ဖြင့် အလိုအလျောက်သိမ်းဆည်းပြီးပါပြီ။"
                )

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
        })
        bot.send_message(
            message.chat.id,
            f"✅ စနစ်ထဲသို့ {vid_id} ဖြင့် အလိုအလျောက်သိမ်းဆည်းပြီးပါပြီ။"
        )

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
            f"⚠️ {message.from_user.first_name or 'User'}, ကြည့်ရှုခွင့် Limit ကုန်ဆုံးပါပြီ။\n"
            "သူငယ်ချင်းများ ဖိတ်ခေါ်ပြီး Limit ထပ်ရယူနိုင်ပါသည်။",
            reply_to_message_id=message.message_id,
            reply_markup=markup
        )
        return

    vid_doc = videos.find_one({"_id": text})
    if not vid_doc:
        bot.send_message(
            message.chat.id,
            f"❌ {text} နံပါတ်ဖြင့် ဗီဒီယို ရှာမတွေ့ပါ။",
            reply_to_message_id=message.message_id
        )
        return

    # Loading animation
    bot.send_chat_action(message.chat.id, "upload_video")
    loading_msg = bot.send_message(
        message.chat.id, "⏳ Please wait... ⬜ 0%",
        reply_to_message_id=message.message_id
    )
    time.sleep(1.5)
    try:
        bot.edit_message_text("⏳ Please wait... 🟨🟨🟨 50%", message.chat.id, loading_msg.message_id)
    except Exception:
        pass
    time.sleep(1.5)
    try:
        bot.edit_message_text("⏳ Please wait... 🟩🟩🟩🟩🟩 100%", message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # Deduct limit
    if not is_free:
        users.update_one({"_id": user_id}, {"$inc": {"limit": -1}})

    # Send video(s) in the group
    caption  = vid_doc.get("caption", "")
    file_ids = vid_doc.get("video_ids", [])
    try:
        if vid_doc["type"] == "single":
            bot.send_video(message.chat.id, file_ids[0], caption=caption)
        else:
            media_group = [
                telebot.types.InputMediaVideo(fid, caption=caption if i == 0 else "")
                for i, fid in enumerate(file_ids)
            ]
            bot.send_media_group(message.chat.id, media_group)
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Video ပေးပို့ရာတွင် အမှားဖြစ်သည်: {e}")

    try:
        bot.delete_message(message.chat.id, loading_msg.message_id)
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
                        "📢 Bot မှ အသိပေးချက်\n"
                        "━━━━━━━━━━━━━━━━━━━━\n\n"
                        + text
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
                    "📩 Owner ထံမှ သတင်းစကား\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    + text
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
            "✅ လူကြီးမင်းပေးပို့သော စာသားသည် Owner ထံသို့ အောင်မြင်စွာ ရောက်ရှိသွားပါပြီ။",
            reply_markup=main_menu_keyboard()
        )
        uname = doc.get("username") or ""
        fname = doc.get("first_name") or ""
        for oid in OWNER_IDS:
            try:
                bot.send_message(
                    oid,
                    f"📩 Message from user\n"
                    f"Name: {fname}\n"
                    f"Username: @{uname}\n"
                    f"ID: {user_id}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"စာသား: {text}"
                )
            except Exception:
                pass
        return

    # ── Menu button: 👤 Profile ───────────────────────────────────────────────
    if text == "👤 Profile":
        display_name = doc.get("username") or doc.get("first_name") or str(user_id)
        limit_str    = "Infinity" if doc.get("is_free") else str(doc.get("limit", 0))
        bot.send_message(
            message.chat.id,
            "My Profile (unique)\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n\n"
            f"အမည်: {display_name}\n\n"
            f"အကောင့် ID: {user_id}\n\n"
            f"limit: {limit_str}\n\n"
            f"Share: {doc.get('shares', 0)}"
        )
        return

    # ── Menu button: 🔗 Share & Refer ─────────────────────────────────────────
    if text == "🔗 Share & Refer":
        share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}?start={user_id}"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔗 Share Link ကူးယူပါ", url=share_url))
        bot.send_message(
            message.chat.id,
            f"🔗 သူငယ်ချင်းများကို ဖိတ်ခေါ်ပါ!\n\n"
            f"တစ်ယောက် join ဖြစ်တိုင်း Limit +5 ခု ရမည်။\n\n"
            f"သင့် Referral Link:\n"
            f"https://t.me/{BOT_USERNAME}?start={user_id}",
            reply_markup=markup
        )
        return

    # ── Menu button: 📹 Videos Update ────────────────────────────────────────
    if text == "📹 Videos Update":
        total = get_total_videos()
        bot.send_message(
            message.chat.id,
            f"📹 Videos Update\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"လက်ရှိ Bot တွင် Videos စုစုပေါင်း {total} ခု ရှိပါသည်။\n\n"
            f"v1 မှ v{total} အထိ ရှာဖွေနိုင်ပါသည်။"
        )
        return

    # ── Menu button: 📞 Contact Owner ─────────────────────────────────────────
    if text == "📞 Contact Owner":
        users.update_one({"_id": user_id}, {"$set": {"state": "waiting_contact"}})
        bot.send_message(
            message.chat.id,
            "📞 လူကြီးမင်းအနေဖြင့် Bot Owner ထံ ပြောကြားလိုသည့် "
            "စာသားများကို ရိုက်နှိပ်ပေးပို့နိုင်ပါပြီ ခင်ဗျာ။\n\n"
            "မပို့လိုပါက ❌ Cancel ကိုနှိပ်ပါ။",
            reply_markup=cancel_keyboard()
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
                "⚠️ လူကြီးမင်း၏ ဗီဒီယိုကြည့်ရှုခွင့် Limit ကုန်ဆုံးသွားပါပြီ။ "
                "ဆက်လက်ကြည့်ရှုရန် အောက်ပါ ခလုတ်မှတစ်ဆင့် Share ပေးပါရန်။",
                reply_markup=share_markup(user_id)
            )
            return

        vid_doc = videos.find_one({"_id": vid_key})
        if not vid_doc:
            bot.send_message(message.chat.id, "❌ ထိုနံပါတ်ဖြင့် ဗီဒီယို ရှာမတွေ့ပါ ခင်ဗျာ။")
            return

        # Anti-spam animation
        bot.send_chat_action(message.chat.id, "upload_video")
        loading_msg = bot.send_message(message.chat.id, "⏳ Please wait a moment... ⬜ 0%")

        time.sleep(1.5)
        try:
            bot.edit_message_text(
                "⏳ Please wait a moment... 🟨🟨🟨 50%",
                message.chat.id, loading_msg.message_id
            )
        except Exception:
            pass

        time.sleep(1.5)
        try:
            bot.edit_message_text(
                "⏳ Please wait a moment... 🟩🟩🟩🟩🟩 100%",
                message.chat.id, loading_msg.message_id
            )
        except Exception:
            pass

        # Deduct limit
        if not is_free:
            users.update_one({"_id": user_id}, {"$inc": {"limit": -1}})

        # Send video(s)
        caption = vid_doc.get("caption", "")
        file_ids = vid_doc.get("video_ids", [])

        if vid_doc["type"] == "single":
            bot.send_video(message.chat.id, file_ids[0], caption=caption)
        else:
            media_group = [
                telebot.types.InputMediaVideo(fid, caption=caption if i == 0 else "")
                for i, fid in enumerate(file_ids)
            ]
            bot.send_media_group(message.chat.id, media_group)

        # Delete loading message
        try:
            bot.delete_message(message.chat.id, loading_msg.message_id)
        except Exception:
            pass

        return

    # ── Fallback: show welcome ─────────────────────────────────────────────────
    send_welcome(message.chat.id, user_id)


# ─── WEBHOOK + KEEP-ALIVE SERVER ──────────────────────────────────────────────
# Webhook mode: Telegram POSTs updates to /webhook.
# No polling → no 409 Conflict even when Render spins up a new instance.
# GET / → UptimeRobot keep-alive (always returns 200).

class WebhookHandler(BaseHTTPRequestHandler):

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

    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"Blue Bot webhook server running on port {port}.")
    server.serve_forever()
