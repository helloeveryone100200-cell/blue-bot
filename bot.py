import os
import re
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import defaultdict

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# ─── CONFIGURATION (set these as environment variables on Render) ─────────────
BOT_TOKEN      = os.environ.get("BOT_TOKEN", "YOUR_BOT_TOKEN")
MONGO_URI      = os.environ.get("MONGO_URI", "YOUR_MONGODB_URI")
OWNER_ID       = int(os.environ.get("OWNER_ID", "1827336632"))
ADMIN_GROUP_ID = int(os.environ.get("ADMIN_GROUP_ID", "-1001234567890"))
BOT_USERNAME   = os.environ.get("BOT_USERNAME", "YourBotUsername")

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

# ─── BOT INIT ─────────────────────────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

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
        "ဒီbotက မင်းရဲ့စိတ်ကိုဖြေလျော့ဖို့အတွက်အလွယ်တကူ videosများရှာဖွေကြည့်ရှုနိုင်ပါတယ်။\n"
        f"videos ({total})ရှိတဲ့အတွက် videos ရှာလိုပါက v1,v2,v3 စသဖြင့် "
        "v အနောက်တွင် နံပါတ်ထည့်ပြီး ရိုက်ရှာနိုင်ပါသည်။"
    )
    bot.send_message(chat_id, text, reply_markup=welcome_markup(user_id))

# ─── /start ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    if message.chat.type != "private":
        return

    args     = message.text.split()
    new_user = message.from_user
    doc      = users.find_one({"_id": new_user.id})
    is_new   = doc is None

    if is_new:
        get_or_create_user(new_user)

    # Referral logic
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

    # Reset state and show welcome
    users.update_one({"_id": new_user.id}, {"$set": {"state": "normal"}})
    send_welcome(message.chat.id, new_user.id)

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
        "စာသားများကို ရိုက်နှိပ်ပေးပို့နိုင်ပါပြီ ခင်ဗျာ။"
    )

# ─── Owner /panel ─────────────────────────────────────────────────────────────

@bot.message_handler(commands=["panel"])
def cmd_panel(message):
    if message.from_user.id != OWNER_ID:
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

# ─── Owner /free ──────────────────────────────────────────────────────────────

@bot.message_handler(commands=["free"])
def cmd_free(message):
    if message.from_user.id != OWNER_ID:
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

# ─── Owner /broadcast ─────────────────────────────────────────────────────────

@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if message.from_user.id != OWNER_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "Usage: /broadcast {user_id}")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        bot.send_message(message.chat.id, "Invalid user_id.")
        return
    broadcast_targets[OWNER_ID] = target_id
    bot.send_message(
        message.chat.id,
        f"📨 User {target_id} ထံပေးပို့မည့် စာသားကို ရိုက်ထည့်ပေးပါ:"
    )

# ─── Admin video ingestion (from ADMIN_GROUP_ID) ──────────────────────────────

@bot.message_handler(content_types=["video"], chat_id=[ADMIN_GROUP_ID])
def handle_admin_video(message):
    if message.chat.id != ADMIN_GROUP_ID:
        return

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

# ─── General message handler (private) ───────────────────────────────────────

@bot.message_handler(func=lambda m: m.chat.type == "private", content_types=["text"])
def handle_text(message):
    user_id  = message.from_user.id
    text     = message.text.strip()
    doc      = users.find_one({"_id": user_id})

    if doc is None:
        doc = get_or_create_user(message.from_user)

    state = doc.get("state", "normal")

    # ── Owner broadcast reply step ────────────────────────────────────────────
    if user_id == OWNER_ID and user_id in broadcast_targets:
        target_id = broadcast_targets.pop(user_id)
        try:
            bot.send_message(
                target_id,
                "📩 Owner ထံမှ စာပြန်လာပါသည်\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                + text
            )
            bot.send_message(message.chat.id, f"✅ User {target_id} ထံ သတင်းပေးပို့ပြီးပါပြီ။")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ ပေးပို့မှု မအောင်မြင်ပါ: {e}")
        return

    # ── Contact state ─────────────────────────────────────────────────────────
    if state == "waiting_contact":
        users.update_one({"_id": user_id}, {"$set": {"state": "normal"}})
        bot.send_message(
            message.chat.id,
            "✅ လူကြီးမင်းပေးပို့သော စာသားသည် Owner ထံသို့ အောင်မြင်စွာ ရောက်ရှိသွားပါပြီ။"
        )
        uname = doc.get("username") or ""
        fname = doc.get("first_name") or ""
        bot.send_message(
            OWNER_ID,
            f"📩 Message from user\n"
            f"Name: {fname}\n"
            f"Username: @{uname}\n"
            f"ID: {user_id}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"စာသား: {text}"
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


# ─── WEB SERVER (UptimeRobot keep-alive) ──────────────────────────────────────

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"Blue Bot is Alive and Running Always On!"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # silence access logs


def start_web_server():
    port   = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), PingHandler)
    server.serve_forever()


# ─── ENTRY POINT ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()
    print("Blue Bot started. Web server running on port 8080.")
    bot.infinity_polling(timeout=60, long_polling_timeout=30)
