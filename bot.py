import os
import re
import time
import json
import threading
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from collections import defaultdict
from types import SimpleNamespace
from urllib.parse import urlparse, quote

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from pymongo import MongoClient
from admin_dashboard import handle_admin_request

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

# Telegram's default menu remains the standard Commands button for all users.
# Only configured OWNER_IDS receive the Web App menu button in their private chat.
ADMIN_WEBAPP_URL = os.environ.get("ADMIN_WEBAPP_URL", "").strip()

USER_WEBAPP_URL = os.environ.get("USER_WEBAPP_URL", "").strip()


def resolve_user_webapp_url(base_url: str = "") -> str:
    """Return the HTTPS User Mini App URL without changing the Owner app URL."""
    configured = USER_WEBAPP_URL
    if configured:
        if not configured.startswith("https://"):
            return ""
        parsed = urlparse(configured)
        path = parsed.path.rstrip("/")
        if path == "/app":
            return configured.rstrip("/") + "/"
        if path in ("", "/"):
            return configured.rstrip("/") + "/app/"
        return configured

    candidate = (
        base_url
        or os.environ.get("WEBHOOK_URL", "")
        or os.environ.get("RENDER_EXTERNAL_URL", "")
    ).strip()
    if not candidate.startswith("https://"):
        return ""
    parsed = urlparse(candidate)
    path = parsed.path.rstrip("/")
    if path.endswith("/webhook"):
        path = path[:-len("/webhook")]
    return f"{parsed.scheme}://{parsed.netloc}{path}/app/"




def resolve_admin_webapp_url(base_url: str = "") -> str:
    """Return the HTTPS Mini App URL, normalizing a base or webhook URL."""
    configured = ADMIN_WEBAPP_URL
    if configured:
        if not configured.startswith("https://"):
            return ""
        parsed = urlparse(configured)
        path = parsed.path.rstrip("/")
        if path == "/admin":
            return configured.rstrip("/") + "/"
        if path in ("", "/"):
            return configured.rstrip("/") + "/admin/"
        return configured

    candidate = (
        base_url
        or os.environ.get("WEBHOOK_URL", "")
        or os.environ.get("RENDER_EXTERNAL_URL", "")
    ).strip()
    if not candidate.startswith("https://"):
        return ""
    parsed = urlparse(candidate)
    path = parsed.path.rstrip("/")
    if path.endswith("/webhook"):
        path = path[:-len("/webhook")]
    return f"{parsed.scheme}://{parsed.netloc}{path}/admin/"


def configure_telegram_menu_buttons(base_url: str):
    """Expose the Mini App menu button only in configured owners' private chats."""
    try:
        bot.set_chat_menu_button(menu_button=telebot.types.MenuButtonCommands())
    except Exception as exc:
        print(f"Could not set default Telegram menu button: {exc}")

    webapp_url = resolve_admin_webapp_url(base_url)
    if not webapp_url.startswith("https://"):
        print("Owner Mini App menu button skipped: configure an HTTPS ADMIN_WEBAPP_URL or RENDER_EXTERNAL_URL.")
        return

    for owner_id in OWNER_IDS:
        try:
            bot.set_chat_menu_button(
                chat_id=owner_id,
                menu_button=telebot.types.MenuButtonWebApp(
                    text="Admin Panel",
                    web_app=telebot.types.WebAppInfo(url=webapp_url),
                ),
            )
            print(f"Owner Mini App menu button configured for OWNER_IDS entry {owner_id}.")
        except Exception as exc:
            print(f"Could not configure owner menu button for {owner_id}: {exc}")



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

# Mini App broadcast jobs are kept in memory only; they are not part of user data.
owner_broadcast_jobs = {}
owner_broadcast_jobs_lock = threading.Lock()


def _valid_owner_target_id(raw_value):
    if not isinstance(raw_value, (str, int)) or isinstance(raw_value, bool):
        raise ValueError("invalid_user_id")
    raw = str(raw_value)
    if not re.fullmatch(r"[0-9]{1,20}", raw):
        raise ValueError("invalid_user_id")
    target_id = int(raw)
    if target_id <= 0 or target_id > 9_223_372_036_854_775_807:
        raise ValueError("invalid_user_id")
    return target_id


def _start_owner_broadcast(owner_id, target, message_text):
    if not isinstance(message_text, str) or not message_text.strip() or len(message_text) > 4000:
        raise ValueError("invalid_broadcast_message")
    if target == "all":
        target_ids = None
        total = users.count_documents({})
    else:
        target_ids = [_valid_owner_target_id(target)]
        total = 1
    job_id = str(time.time_ns())
    job = {"id": job_id, "total": total, "sent": 0, "failed": 0, "status": "running"}
    with owner_broadcast_jobs_lock:
        if len(owner_broadcast_jobs) >= 100:
            for old_id, old_job in list(owner_broadcast_jobs.items()):
                if old_job.get("status") != "running":
                    owner_broadcast_jobs.pop(old_id, None)
                if len(owner_broadcast_jobs) < 80:
                    break
            if len(owner_broadcast_jobs) >= 100:
                raise ValueError("too_many_broadcast_jobs")
        owner_broadcast_jobs[job_id] = job

    def send_messages():
        try:
            if target_ids is None:
                recipients = (
                    doc["_id"] for doc in users.find({}, {"_id": 1})
                    if isinstance(doc.get("_id"), int) and not isinstance(doc.get("_id"), bool)
                )
            else:
                recipients = iter(target_ids)
            for target_id in recipients:
                try:
                    bot.send_message(target_id, message_text)
                    with owner_broadcast_jobs_lock:
                        job["sent"] += 1
                except Exception:
                    with owner_broadcast_jobs_lock:
                        job["failed"] += 1
                time.sleep(0.04)
        except Exception:
            # A database cursor failure must not leave the progress indicator stuck forever.
            with owner_broadcast_jobs_lock:
                job["failed"] += max(0, job["total"] - job["sent"] - job["failed"])
        finally:
            with owner_broadcast_jobs_lock:
                job["status"] = "completed"

    threading.Thread(target=send_messages, daemon=True).start()
    return {"jobId": job_id, "total": job["total"], "status": "running"}


def _execute_owner_action(owner, payload):
    """Execute an allowlisted Owner Control Panel action after Mini App authentication."""
    if not isinstance(owner, dict) or type(owner.get("id")) is not int or owner["id"] not in OWNER_IDS:
        raise ValueError("owner_access_denied")
    action = payload.get("action")
    if not isinstance(action, str):
        raise ValueError("invalid_action")

    if action == "set_auto_broadcast":
        enabled = payload.get("enabled")
        if type(enabled) is not bool:
            raise ValueError("invalid_enabled_value")
        set_broadcast_new_video(enabled)
        return {"ok": True, "enabled": get_broadcast_new_video()}

    if action in ("set_required_channel", "remove_required_channel"):
        if action == "remove_required_channel":
            result = settings.delete_one({"_id": "required_channel"})
            return {"ok": True, "removed": bool(result.deleted_count)}
        raw_link = payload.get("channelLink")
        if not isinstance(raw_link, str) or len(raw_link) > 300:
            raise ValueError("invalid_channel_link")
        channel = parse_public_channel_link(raw_link)
        if not channel:
            raise ValueError("invalid_channel_link")
        try:
            chat = bot.get_chat(channel["chat_id"])
            if chat.type != "channel":
                raise ValueError("not_a_channel")
            member = bot.get_chat_member(channel["chat_id"], bot.get_me().id)
            if member.status not in ("administrator", "creator"):
                raise ValueError("bot_must_be_channel_admin")
        except ValueError:
            raise
        except Exception:
            raise ValueError("channel_validation_failed")
        settings.update_one(
            {"_id": "required_channel"},
            {"$set": {"chat_id": channel["chat_id"], "link": channel["link"], "title": chat.title or channel["chat_id"]}},
            upsert=True,
        )
        return {"ok": True, "channel": str(chat.title or channel["chat_id"]), "link": channel["link"]}

    if action in ("set_public_admin_group", "set_private_admin_group"):
        raw_group = payload.get("groupId")
        if not isinstance(raw_group, str) or len(raw_group.strip()) > 100 or not raw_group.strip():
            raise ValueError("invalid_group_id")
        try:
            chat = bot.get_chat(raw_group.strip())
        except Exception:
            raise ValueError("group_not_found")
        if chat.type not in ("group", "supergroup"):
            raise ValueError("target_is_not_group")
        try:
            member = bot.get_chat_member(chat.id, bot.get_me().id)
            if member.status in ("left", "kicked"):
                raise ValueError("bot_not_in_group")
        except ValueError:
            raise
        except Exception:
            raise ValueError("bot_not_in_group")
        if action == "set_public_admin_group":
            set_admin_group_id(chat.id)
        else:
            set_private_admin_group_id(chat.id)
        return {"ok": True, "groupId": str(chat.id), "groupName": str(chat.title or chat.id)}

    if action in ("ban_user", "unban_user"):
        target_id = _valid_owner_target_id(payload.get("userId"))
        if action == "ban_user" and target_id in OWNER_IDS:
            raise ValueError("cannot_ban_owner")
        result = users.find_one_and_update(
            {"_id": target_id},
            {"$set": {"is_banned": action == "ban_user"}},
            return_document=True,
        )
        if not result:
            raise ValueError("user_not_found")
        name = str(result.get("username") or result.get("first_name") or target_id)[:128]
        try:
            bot.send_message(
                target_id,
                "🚫 You have been blocked from using this bot." if action == "ban_user"
                else "✅ Your ban has been lifted. You can use the bot again.",
            )
        except Exception:
            pass
        return {"ok": True, "userId": str(target_id), "name": name, "banned": action == "ban_user"}

    if action in ("grant_private_access", "revoke_private_access"):
        target_id = _valid_owner_target_id(payload.get("userId"))
        if action == "grant_private_access":
            doc = users.find_one({"_id": target_id})
            if not doc:
                raise ValueError("user_not_found")
            accept_user(target_id)
            try:
                bot.send_message(
                    target_id,
                    "<b>🔓 𝗣𝗿𝗶𝘃𝗮𝘁𝗲 𝗔𝗰𝗰𝗲𝘀𝘀 𝗚𝗿𝗮𝗻𝘁𝗲𝗱!</b>\n\n"
                    "<blockquote>• The owner has granted you access to the private group ✅\n"
                    "• You can post videos in the private group and z1, z2, z3 … ဖြင့် ရှာဖွေနိုင်မည်ဖြစ်သည်။</blockquote>",
                    parse_mode="HTML",
                )
            except Exception:
                pass
            return {"ok": True, "userId": str(target_id), "access": True}
        remove_accepted_user(target_id)
        try:
            bot.send_message(
                target_id,
                "<b>🔒 𝗔𝗰𝗰𝗲𝘀𝘀 𝗥𝗲𝘃𝗼𝗸𝗲𝗱</b>\n\n"
                "<blockquote>• The owner has revoked your private-group access.</blockquote>",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return {"ok": True, "userId": str(target_id), "access": False}

    if action == "delete_media":
        kind = payload.get("kind")
        media_id = payload.get("mediaId")
        patterns = {
            "public_video": (r"v[0-9]+", "video_counter", "Public video"),
            "private_video": (r"z[0-9]+", "z_video_counter", "Private video"),
            "public_photo": (r"p[0-9]+", "photo_counter", "Public photo"),
            "private_photo": (r"zp[0-9]+", "z_photo_counter", "Private photo"),
        }
        if kind not in patterns or not isinstance(media_id, str):
            raise ValueError("invalid_media_target")
        pattern, counter_id, label = patterns[kind]
        media_id = media_id.lower()
        if not re.fullmatch(pattern, media_id):
            raise ValueError("invalid_media_id")
        result = videos.delete_one({"_id": media_id})
        if result.deleted_count == 0:
            raise ValueError("media_not_found")
        settings.update_one({"_id": counter_id}, {"$inc": {"count": -1}})
        return {"ok": True, "mediaId": media_id, "deleted": True, "label": label}

    if action == "set_thumbnail":
        media_id = payload.get("mediaId")
        file_id = payload.get("fileId")
        if not isinstance(media_id, str) or not re.fullmatch(r"[vz][0-9]+", media_id.lower()):
            raise ValueError("invalid_media_id")
        if not isinstance(file_id, str) or not file_id.strip() or len(file_id) > 1024:
            raise ValueError("invalid_thumbnail_file_id")
        media_id = media_id.lower()
        try:
            bot.get_file(file_id.strip())
        except Exception:
            raise ValueError("invalid_thumbnail_file_id")
        result = videos.update_one({"_id": media_id}, {"$set": {"thumbnail": file_id.strip()}})
        if result.matched_count == 0:
            raise ValueError("media_not_found")
        return {"ok": True, "mediaId": media_id}

    if action == "remove_thumbnail":
        media_id = payload.get("mediaId")
        if not isinstance(media_id, str) or not re.fullmatch(r"[vz][0-9]+", media_id.lower()):
            raise ValueError("invalid_media_id")
        media_id = media_id.lower()
        result = videos.update_one({"_id": media_id}, {"$unset": {"thumbnail": ""}})
        if result.matched_count == 0:
            raise ValueError("media_not_found")
        return {"ok": True, "mediaId": media_id}

    if action == "create_referral_link":
        media_id = payload.get("mediaId")
        if not isinstance(media_id, str) or not re.fullmatch(r"v[0-9]+", media_id.lower()):
            raise ValueError("invalid_media_id")
        media_id = media_id.lower()
        if not videos.find_one({"_id": media_id}, {"_id": 1}):
            raise ValueError("media_not_found")
        link = f"https://t.me/{BOT_USERNAME}?start=ref_{media_id}"
        return {"ok": True, "mediaId": media_id, "link": link, "shareUrl": f"https://t.me/share/url?url={link}"}

    if action == "broadcast_start":
        target = payload.get("target")
        if target != "all":
            target = _valid_owner_target_id(target)
        return _start_owner_broadcast(owner["id"], target, payload.get("message"))

    if action == "broadcast_status":
        job_id = payload.get("jobId")
        if not isinstance(job_id, str) or len(job_id) > 40:
            raise ValueError("invalid_job_id")
        with owner_broadcast_jobs_lock:
            job = owner_broadcast_jobs.get(job_id)
            if not job:
                raise ValueError("broadcast_job_not_found")
            return dict(job)

    if action == "panel_stats":
        total_users = users.count_documents({})
        banned_users = users.count_documents({"is_banned": True})
        total_shares = sum(
            value for doc in users.find({}, {"shares": 1})
            for value in [doc.get("shares", 0)]
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        )
        return {
            "ok": True, "users": total_users, "bannedUsers": banned_users,
            "shares": total_shares, "publicVideos": get_total_videos(),
            "publicPhotos": get_total_photos(), "privateVideos": get_total_z_videos(),
            "privatePhotos": get_total_z_photos(), "autoBroadcast": get_broadcast_new_video(),
        }

    raise ValueError("unsupported_action")


def _record_owner_action(owner, payload, outcome):
    """Keep a bounded audit trail without storing broadcast message contents or secrets."""
    try:
        action = payload.get("action", "unknown")
        target = (
            payload.get("userId") or payload.get("mediaId") or payload.get("groupId")
            or payload.get("channelLink") or payload.get("target")
        )
        if target is None and "enabled" in payload:
            target = "enabled" if payload.get("enabled") is True else "disabled"
        event = {
            "owner_id": owner["id"],
            "action": str(action)[:64],
            "target": str(target)[:160] if target is not None else "",
            "outcome": outcome,
            "timestamp": int(time.time()),
        }
        settings.update_one(
            {"_id": "owner_action_audit"},
            {"$push": {"events": {"$each": [event], "$slice": -500}}},
            upsert=True,
        )
    except Exception as exc:
        # A logging failure must not turn a completed mutation into a false client error.
        print(f"Owner action audit write failed: {type(exc).__name__}")


OWNER_MUTATING_ACTIONS = frozenset({
    "set_auto_broadcast", "set_required_channel", "remove_required_channel",
    "set_public_admin_group", "set_private_admin_group", "ban_user", "unban_user",
    "grant_private_access", "revoke_private_access", "delete_media", "set_thumbnail",
    "remove_thumbnail", "broadcast_start",
})


def handle_owner_action(owner, payload):
    """Validate owner identity and audit only state-changing Owner Control Panel actions."""
    if not isinstance(owner, dict) or type(owner.get("id")) is not int or owner["id"] not in OWNER_IDS:
        raise ValueError("owner_access_denied")
    if not isinstance(payload, dict):
        raise ValueError("invalid_action")
    if payload.get("action") not in OWNER_MUTATING_ACTIONS:
        return _execute_owner_action(owner, payload)
    try:
        result = _execute_owner_action(owner, payload)
    except Exception:
        _record_owner_action(owner, payload, "failed")
        raise
    _record_owner_action(owner, payload, "success")
    return result


# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def get_or_create_user(user):
    doc = users.find_one({"_id": user.id})
    if doc is None:
        doc = {
            "_id":        user.id,
            "username":   user.username or "",
            "first_name": user.first_name or "",
            "shares":     0,
            "is_banned":  False,
            "gender":     None,
            "state":      "normal",
        }
        users.insert_one(doc)
    return doc

def get_total_videos():
    counter = settings.find_one({"_id": "video_counter"})
    return counter["count"] if counter else 0

def main_menu_keyboard(user_id=None):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("👤 Profile", style="success"),
        KeyboardButton("🔗 𝗦𝗵𝗮𝗿𝗲 & 𝗥𝗲𝗳𝗲𝗿", style="primary"),
    )
    markup.add(
        KeyboardButton("📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿", style="success"),
    )
    markup.add(
        KeyboardButton("🏆 𝗧𝗼𝗽 𝗩𝗶𝗱𝗲𝗼𝘀 (Most Liked)", style="primary"),
    )
    if user_id in OWNER_IDS:
        markup.add(
            KeyboardButton("⚙️ Control Panel", style="success"),
        )
    return markup

def owner_panel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("/panel", style="primary"),
        KeyboardButton("/ownerhelp", style="primary"),
    )
    markup.add(
        KeyboardButton("/autobroadcast", style="success"),
        KeyboardButton("/ref", style="primary"),
    )
    markup.add(
        KeyboardButton("/setchannel", style="success"),
        KeyboardButton("/removechannel", style="danger"),
    )
    markup.add(
        KeyboardButton("/userinfo", style="primary"),
        KeyboardButton("/userlist", style="primary"),
    )
    markup.add(
        KeyboardButton("/ban", style="danger"),
        KeyboardButton("/unban", style="success"),
    )
    markup.add(
        KeyboardButton("/broadcast", style="primary"),
        KeyboardButton("/accept", style="success"),
    )
    markup.add(
        KeyboardButton("/setadmingroup", style="success"),
        KeyboardButton("/setadmingroup_private", style="success"),
    )
    markup.add(
        KeyboardButton("/deletevideo", style="danger"),
        KeyboardButton("/deletephoto", style="danger"),
    )
    markup.add(
        KeyboardButton("/deleteprivatevideo", style="danger"),
        KeyboardButton("/deleteprivatephoto", style="danger"),
    )
    markup.add(
        KeyboardButton("/setthumb", style="primary"),
        KeyboardButton("/removethumb", style="danger"),
    )
    markup.add(KeyboardButton("⬅️ Back", style="primary"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    markup.add(KeyboardButton("❌ Cancel", style="danger"))
    return markup

def welcome_markup(user_id):
    markup = InlineKeyboardMarkup(row_width=2)
    share_url = f"https://t.me/share/url?url=https://t.me/{BOT_USERNAME}?start={user_id}"
    # Profile is available from the persistent reply keyboard; keep Share here.
    markup.add(InlineKeyboardButton("🔗 Share", url=share_url))
    # User Mini App is available to regular users; owner controls remain separately gated.
    user_app_url = resolve_user_webapp_url()
    if user_app_url:
        markup.add(InlineKeyboardButton(
            "📱 User Dashboard",
            web_app=telebot.types.WebAppInfo(url=user_app_url),
        ))
    # Direct Mini App entry for owners; regular users retain the existing owner-only gate.
    if user_id in OWNER_IDS:
        webapp_url = resolve_admin_webapp_url()
        if webapp_url:
            markup.add(InlineKeyboardButton(
                "⚙️ Admin Panel",
                web_app=telebot.types.WebAppInfo(url=webapp_url),
            ))
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
    # No required channel means the join gate is disabled.
    if not channel:
        return True
    # A partially configured record is invalid; fail closed instead of bypassing the gate.
    if not channel.get("chat_id") or not channel.get("link"):
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
            "✅ Join Channel",
            url=channel["link"],
            style="success"
        ))
    else:
        markup.add(InlineKeyboardButton(
            "⚠️ No channel configured yet",
            callback_data="channel_not_configured",
            style="danger"
        ))
    markup.add(InlineKeyboardButton(
        "🔄 Refresh",
        callback_data="refresh_channel",
        style="primary"
    ))
    return markup

def send_channel_join_prompt(chat_id, reply_to_message_id=None):
    channel = get_required_channel()
    text = (
        "Please join the channel before watching videos.\n\n"
        "After joining, tap Refresh below to watch videos."
    )
    if not channel:
        text += "\n\n⚠️ The owner must configure the channel link first."
    bot.send_message(
        chat_id,
        text,
        reply_markup=channel_join_markup(),
        reply_to_message_id=reply_to_message_id
    )

def send_welcome(chat_id, user_id):
    total = get_total_videos()
    text = (
        "<b>🔹 BLUE BOT</b>\n"
        "<i>Your Personal Video Hub</i>\n\n"
        "👋 Welcome to <b>Blue Bot</b>!\n"
        "Explore videos, manage your profile, and share content with friends — all in one place.\n\n"
        "<b>✨ WHAT YOU CAN DO</b>\n"
        "👤 <b>My Profile</b> — View your account information.\n"
        "🏆 <b>Top Videos</b> — Explore the most popular videos.\n"
        "🔗 <b>Share &amp; Refer</b> — Invite friends and share your link.\n"
        "📞 <b>Contact Owner</b> — Get help when you need it.\n\n"
        "<b>📚 VIDEO LIBRARY</b>\n"
        f"Available videos: <b>{total}</b>\n\n"
        "<b>🔎 HOW TO FIND A VIDEO</b>\n"
        "Send a video ID such as <code>v1</code>, <code>v2</code>, or <code>v3</code> to find it.\n\n"
        "🚀 <i>Select an option from the menu below to get started.</i>"
    )
    bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=welcome_markup(user_id))

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
                    f"<b>🆕 New video added!</b>\n\n"
                    f"<blockquote>📹 <b>{vid_id}</b> is now available to watch.\n"
                    f"• Group/Private တွင် <code>{vid_id}</code> ရိုက်ပြီး ရှာနိုင်သည်။</blockquote>",
                    parse_mode='HTML',
                    reply_markup=markup
                )
            except Exception:
                pass
    threading.Thread(target=_send, daemon=True).start()

# ─── TOP VIDEOS TEXT ──────────────────────────────────────────────────────────

def get_top_videos_text(n: int = 10) -> str:
    """Build a readable leaderboard using the existing public-video rating data."""
    top = list(videos.find(
        {"_id": {"$regex": r"^v\d+$"}, "likes": {"$gt": 0}},
        {"_id": 1, "likes": 1, "dislikes": 1, "views": 1}
    ).sort([("likes", -1), ("views", -1), ("_id", 1)]).limit(max(1, min(n, 10))))
    if not top:
        return (
            "<b>🏆 𝗧𝗼𝗽 𝗩𝗶𝗱𝗲𝗼𝘀 (Most Liked)</b>\n"
            "<i>Community leaderboard</i>\n\n"
            "<blockquote>📊 <b>Leaderboard is waiting for its first vote.</b>\n\n"
            "• Public videos with at least one 👍 vote will appear here.\n"
            "• After watching a video, you can rate it with 👍 / 👎.</blockquote>"
        )
    medals = ["🥇", "🥈", "🥉"] + ["🏅"] * 7
    lines = []
    for i, video in enumerate(top):
        video_id = h(video.get("_id", ""))
        likes = max(0, int(video.get("likes", 0) or 0))
        dislikes = max(0, int(video.get("dislikes", 0) or 0))
        views = max(0, int(video.get("views", 0) or 0))
        lines.append(
            f"{medals[i]} <b>{video_id}</b>\n"
            f"   👍 <b>{likes}</b> likes  ·  👎 {dislikes}  ·  👁 {views} views"
        )
    return (
        "<b>🏆 𝗧𝗼𝗽 𝗩𝗶𝗱𝗲𝗼𝘀 (Most Liked)</b>\n"
        "<i>Community leaderboard · ranked by likes</i>\n\n"
        f"<blockquote>{chr(10).join(lines)}</blockquote>\n\n"
        "<i>Tip: Send a video ID such as <code>v1</code> to watch it.</i>"
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
        status  = "✅ ON (Enabled)" if current else "❌ OFF (Disabled)"
        bot.send_message(
            message.chat.id,
            "<b>📡 Auto Broadcast New Video</b>\n\n"
            f"<blockquote>• Current status ——— {status}\n\n"
            "• /autobroadcast on  — Enable\n"
            "• /autobroadcast off — Disable</blockquote>",
            parse_mode='HTML'
        )
        return
    toggle  = parts[1].lower()
    enabled = (toggle == "on")
    set_broadcast_new_video(enabled)
    if enabled:
        bot.send_message(
            message.chat.id,
            "✅ <b>Auto Broadcast has been enabled.</b>\n\n"
            "<blockquote>• All users will be notified automatically whenever a new video is added.\n"
            "  </blockquote>",
            parse_mode='HTML'
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ <b>Auto Broadcast has been disabled.</b>\n\n"
            "<blockquote>• New videos will no longer trigger\n"
            "  notifications to users.</blockquote>",
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
            "<b>How to use</b>\n\n"
            "<code>/ref v1</code>\n"
            "<code>/ref v2</code>",
            parse_mode='HTML'
        )
        return

    vid_id = parts[1].strip().lower()
    if not videos.find_one({"_id": vid_id}, {"_id": 1}):
        bot.send_message(
            message.chat.id,
            f"❌ <b>{h(vid_id)}</b> was not found in the video database.",
            parse_mode='HTML'
        )
        return

    deep_link = f"https://t.me/{BOT_USERNAME}?start=ref_{vid_id}"
    share_url  = f"https://t.me/share/url?url={deep_link}"
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🔗 Share Link", url=share_url))
    bot.send_message(
        message.chat.id,
        "<b>🔗 Video Referral Link</b>\n\n"
        f"• Video — <code>{h(vid_id)}</code>\n"
        f"• Link —\n<code>{h(deep_link)}</code>\n\n"
        "Anyone who opens this link will receive the video directly in the bot’s private chat:\n"
        f"<code>{h(vid_id)}</code> ",
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
            "How to use:\n<code>/setchannel https://t.me/your_channel</code>\n\n"
            "The channel must be public, and the bot must be an administrator in that channel.",
            parse_mode='HTML'
        )
        return

    channel = parse_public_channel_link(parts[1])
    if not channel:
        bot.send_message(
            message.chat.id,
            "❌ Invalid public channel link.\n"
            "Example: <code>https://t.me/your_channel</code>",
            parse_mode='HTML'
        )
        return

    try:
        chat = bot.get_chat(channel["chat_id"])
        if chat.type != "channel":
            raise ValueError("The provided link is not a channel link.")
        bot_member = bot.get_chat_member(channel["chat_id"], bot.get_me().id)
        if bot_member.status not in ("administrator", "creator"):
            raise ValueError("The bot must be an administrator in the channel.")
    except Exception as e:
        bot.send_message(
            message.chat.id,
            "❌ Channel not found. Verify that the link is correct and\n"
            "that the bot has been added to the channel.\n\n"
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
        "✅ <b>The required-membership channel has been configured.</b>\n\n"
        f"• Channel — <b>{h(chat.title or channel['chat_id'])}</b>\n"
        f"• Link — <code>{h(channel['link'])}</code>\n\n"
        "The bot will check whether users have joined the channel.",
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
            "✅ The required-channel setting has been removed."
        )
    else:
        bot.send_message(
            message.chat.id,
            "ℹ️ No channel has been configured yet."
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
                        {"$inc": {"shares": 1}}
                    )
                    try:
                        bot.send_message(
                            referrer_id,
                            "<b>🎉 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹 𝗦𝘂𝗰𝗰𝗲𝘀𝘀!</b>\n\n"
                            "<blockquote>• A friend has joined the bot ✅</blockquote>",
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
                "🚫 You are blocked from using this bot."
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
                "<b>𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗕𝗹𝘂𝗲 𝗕𝗼𝘁! 🎉</b>",
                parse_mode='HTML',
                reply_markup=main_menu_keyboard(new_user.id)
            )
            send_welcome(message.chat.id, new_user.id)

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
                "<blockquote>• Please select your gender to continue.</blockquote>",
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
            "🤖 Open Bot in Private Chat",
            url=f"https://t.me/{BOT_USERNAME}?start={new_user.id}"
        ))
        bot.send_message(
            message.chat.id,
            f"<b>𝗕𝗹𝘂𝗲 𝗕𝗼𝘁 — Registration Complete ✅</b>\n\n"
            f"<blockquote><b>👋 𝗛𝗲𝗹𝗹𝗼, {h(fname)}!</b>\n\n"
            f"<b>⚡️ 𝗟𝗮𝘁𝗲𝘀𝘁 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀</b>\n"
            f"• Total videos ——— {total} ခု\n\n"
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
    text = (
        "<b>👤 MY PROFILE</b>\n"
        "<i>Your Blue Bot account at a glance</i>\n\n"
        "<blockquote>"
        "<b>ACCOUNT DETAILS</b>\n"
        f"👤 <b>Name</b>\n<code>{h(display_name)}</code>\n\n"
        f"🆔 <b>Telegram ID</b>\n<code>{user_id}</code>\n\n"
        "<b>VIDEO ACCESS</b>\n"
        "🎬 <b>Unlimited</b>\n\n"
        "<b>SHARING ACTIVITY</b>\n"
        f"🔗 <b>Total shares:</b> {doc.get('shares', 0)}"
        "</blockquote>\n\n"
        "<i>Your account information is shown above.</i>"
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
    channel = get_required_channel()

    # If the required channel was removed while the user was waiting,
    # the join gate is disabled and the pending action can continue.
    if channel and not is_user_channel_joined(user_id):
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

    if channel:
        bot.answer_callback_query(call.id, "✅ Channel membership confirmed.")
    else:
        bot.answer_callback_query(
            call.id,
            "ℹ️ Required channel membership is disabled."
        )
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
def cb_refresh_channel(call):
    resume_pending_channel_action(call)

@bot.callback_query_handler(func=lambda c: c.data == "channel_not_configured")
def cb_channel_not_configured(call):
    bot.answer_callback_query(
        call.id,
        "The owner must configure a channel link with /setchannel.",
        show_alert=True
    )


@bot.callback_query_handler(func=lambda c: c.data == "gender_male")
def cb_gender_male(call):
    user_id = call.from_user.id
    users.update_one({"_id": user_id}, {"$set": {"gender": "male"}})
    bot.answer_callback_query(call.id, "👨 Male selected.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(
        call.message.chat.id,
        "<b>🔞 𝗔𝗱𝘂𝗹𝘁 𝗖𝗼𝗻𝘁𝗲𝗻𝘁 𝗡𝗼𝘁𝗶𝗰𝗲</b>\n\n"
        "<blockquote>⚠️ This bot provides access to 𝗔𝗱𝘂𝗹𝘁 𝗠𝗼𝘃𝗶𝗲𝘀.\n"
        "\n\n"
        "• • You must be 18 or older to use this bot.\n"
        "• Bot ကို ဆက်လက် အသုံးပြုနိုင်ပါပြီ ✅</blockquote>",
        parse_mode='HTML'
    )
    send_pending_ref_video(call)

@bot.callback_query_handler(func=lambda c: c.data == "gender_female")
def cb_gender_female(call):
    user_id = call.from_user.id
    users.update_one({"_id": user_id}, {"$set": {"gender": "female"}})
    bot.answer_callback_query(call.id, "👩 Female selected.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(
        call.message.chat.id,
        "<b>🔞 𝗔𝗱𝘂𝗹𝘁 𝗖𝗼𝗻𝘁𝗲𝗻𝘁 𝗡𝗼𝘁𝗶𝗰𝗲</b>\n\n"
        "<blockquote>⚠️ This bot provides access to 𝗔𝗱𝘂𝗹𝘁 𝗠𝗼𝘃𝗶𝗲𝘀.\n"
        "\n\n"
        "• • You are not required to use this bot.\n"
        "• • The choice to use this bot is entirely yours.\n\n"
        "<i>💬 If you choose to continue, you may use the bot\n"
        "   at your own discretion. You are free to decide. ✅</i></blockquote>",
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
        "Type and send your message to the bot owner.",
        reply_markup=cancel_keyboard()
    )

# ─── Owner /panel ─────────────────────────────────────────────────────────────

@bot.message_handler(commands=["panel"])
def cmd_panel(message):
    if message.from_user.id not in OWNER_IDS:
        return
    total_users   = users.count_documents({})
    banned_users  = users.count_documents({"is_banned": True})
    total_shares  = sum(d.get("shares", 0) for d in users.find({}, {"shares": 1}))
    total_vids    = get_total_videos()
    total_photos  = get_total_photos()
    total_zvids   = get_total_z_videos()
    total_zphotos = get_total_z_photos()
    broadcast_on  = get_broadcast_new_video()
    bc_status     = "✅ ON (Enabled)" if broadcast_on else "❌ OFF (Disabled)"
    bot.send_message(
        message.chat.id,
        "<b>📊 𝗕𝗼𝘁 𝗦𝘁𝗮𝘁𝗶𝘀𝘁𝗶𝗰𝘀</b>\n\n"
        f"<blockquote>👥 𝗧𝗼𝘁𝗮𝗹 𝗨𝘀𝗲𝗿𝘀  ——  {total_users} ဦး\n"
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
        "• User အားလုံးသည် Video ကို Unlimited ကြည့်နိုင်ပါသည်။\n\n"
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
        bot.send_message(message.chat.id, "❌ Invalid user ID.")
        return
    if target_id in OWNER_IDS:
        bot.send_message(message.chat.id, "❌ The owner cannot be banned.")
        return
    result = users.find_one_and_update(
        {"_id": target_id},
        {"$set": {"is_banned": True}},
        return_document=True
    )
    if not result:
        bot.send_message(message.chat.id, f"❌ User {target_id} was not found in the database.")
        return
    uname = result.get("username") or result.get("first_name") or str(target_id)
    bot.send_message(
        message.chat.id,
        f"🚫 User {target_id} ({uname}) has been banned.\n"
        f"• This user can no longer use the bot."
    )
    try:
        bot.send_message(
            target_id,
            "🚫 You have been blocked from using this bot."
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
        bot.send_message(message.chat.id, "❌ Invalid user ID.")
        return
    result = users.find_one_and_update(
        {"_id": target_id},
        {"$set": {"is_banned": False}},
        return_document=True
    )
    if not result:
        bot.send_message(message.chat.id, f"❌ User {target_id} was not found in the database.")
        return
    uname = result.get("username") or result.get("first_name") or str(target_id)
    bot.send_message(
        message.chat.id,
        f"✅ User {target_id} ({uname}) has been unbanned.\n"
        f"• This user can use the bot again."
    )
    try:
        bot.send_message(
            target_id,
            "✅ Your ban has been lifted. You can use the bot again."
        )
    except Exception:
        pass


# ─── Legacy limit commands ─────────────────────────────────────────────────────

@bot.message_handler(commands=["addlimit"])
def cmd_addlimit(message):
    if message.from_user.id not in OWNER_IDS:
        return
    bot.send_message(message.chat.id, "ℹ️ The limit system has been removed. All users have unlimited access.")

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
    shares   = doc.get("shares", 0)
    referrals = doc.get("referrals", 0)
    state    = doc.get("state", "normal")
    joined   = doc.get("joined_at", "—")

    bot.send_message(
        message.chat.id,
        "<b>👤 𝗨𝘀𝗲𝗿 𝗜𝗻𝗳𝗼</b>\n\n"
        f"<blockquote>• 𝗡𝗮𝗺𝗲  ——  {h(fname)}\n"
        f"• 𝗨𝘀𝗲𝗿𝗻𝗮𝗺𝗲  ——  @{h(uname)}\n"
        f"• 𝗜𝗗  ——  {target_id}\n\n"
        "• 𝗩𝗶𝗱𝗲𝗼 𝗔𝗰𝗰𝗲𝘀𝘀  ——  ∞ Unlimited\n"
        f"• 𝗦𝗵𝗮𝗿𝗲  ——  {shares} ကြိမ် Share ခဲ့သည်\n"
        f"• 𝗥𝗲𝗳𝗲𝗿𝗿𝗮𝗹𝘀  ——  {referrals} ဦး ဖိတ်ခဲ့သည်\n\n"
        f"• 𝗦𝘁𝗮𝘁𝗲  ——  {h(state)}\n"
        f"• 𝗝𝗼𝗶𝗻𝗲𝗱  ——  {h(str(joined))}</blockquote>",
        parse_mode='HTML'
    )

# ─── Legacy /free command ──────────────────────────────────────────────────────

@bot.message_handler(commands=["free"])
def cmd_free(message):
    if message.from_user.id not in OWNER_IDS:
        return
    bot.send_message(message.chat.id, "ℹ️ The limit system has been removed. All users have unlimited access.")

# ─── Owner /userlist ──────────────────────────────────────────────────────────

@bot.message_handler(commands=["userlist"])
def cmd_userlist(message):
    if message.from_user.id not in OWNER_IDS:
        return

    all_users = list(users.find({}, {"_id": 1, "username": 1, "first_name": 1}))
    if not all_users:
        bot.send_message(message.chat.id, "📋 No users found.")
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
        prefix = header if i == 0 else f"(Continued... {i+1}/{len(chunks)})\n\n"
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
            "Tap ❌ Cancel to stop.",
            reply_markup=cancel_keyboard()
        )
    else:
        try:
            target_id = int(arg)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Invalid user ID.\nUsage: /broadcast {user_id} or /broadcast all")
            return
        broadcast_targets[owner_id] = target_id
        bot.send_message(
            message.chat.id,
            f"📨 User {target_id} ထံ ပေးပို့မည့် စာသားကို ရိုက်ထည့်ပေးပါ:\n\n"
            "Tap ❌ Cancel to stop.",
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
            "⚠️ This command can only be used in a group.\n"
            "Add the bot to the group, then run /setadmingroup there."
        )
        return

    chat_id   = message.chat.id
    chat_name = message.chat.title or str(chat_id)
    set_admin_group_id(chat_id)
    bot.send_message(
        message.chat.id,
        f"✅ This group is now configured as the public video storage group.\n\n"
        f"Group: {chat_name}\n"
        f"ID: {chat_id}\n\n"
        f"Videos sent by the owner to this group will now be saved to the database automatically."
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
            "⚠️ This command can only be used in a group.\n"
            "Add the bot to the group, then run /setadmingroup_private there."
        )
        return

    chat_id   = message.chat.id
    chat_name = message.chat.title or str(chat_id)
    set_private_admin_group_id(chat_id)
    bot.send_message(
        message.chat.id,
        f"🔒 This group is now configured as the private video group.\n\n"
        f"Group: {chat_name}\n"
        f"ID: {chat_id}\n\n"
        f"• Only the owner and users approved with /accept\n"
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
            bot.send_message(message.chat.id, "❌ Invalid user ID.")
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
                "<blockquote>• The owner has revoked your private-group access.</blockquote>",
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
        bot.send_message(message.chat.id, "❌ Invalid user ID.")
        return

    doc = users.find_one({"_id": target_id})
    if not doc:
        bot.send_message(message.chat.id, f"❌ User {target_id} was not found in the database.")
        return

    accept_user(target_id)
    uname = doc.get("username") or doc.get("first_name") or str(target_id)
    bot.send_message(
        message.chat.id,
        f"✅ User {target_id} ({uname}) ကို Private Group ခွင့်ပြုပြီးပါပြီ။\n"
        f"• ထို User သည် ယခု You can post videos in the private group and\n"
        f"  z1, z2, z3 … ဖြင့် ရှာဖွေနိုင်မည်။"
    )
    try:
        bot.send_message(
            target_id,
            "<b>🔓 𝗣𝗿𝗶𝘃𝗮𝘁𝗲 𝗔𝗰𝗰𝗲𝘀𝘀 𝗚𝗿𝗮𝗻𝘁𝗲𝗱!</b>\n\n"
            "<blockquote>• The owner has granted you access to the private group ✅\n"
            "• You can post videos in the private group and\n"
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
        bot.send_message(message.chat.id, "❌ Invalid video ID. Example: /deletevideo v5")
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
        bot.send_message(message.chat.id, "❌ Invalid video ID. Example: /deleteprivatevideo z5")
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
        bot.send_message(message.chat.id, "❌ Invalid photo ID. Example: /deletephoto p3")
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
        bot.send_message(message.chat.id, "❌ Invalid photo ID. Example: /deleteprivatephoto zp3")
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
                    f"✅ စနစ်ထဲသို့ {vid_id} was saved automatically."
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
            f"✅ စနစ်ထဲသို့ {vid_id} was saved automatically."
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
            "⚠️ To use the bot, open a private chat and send /start, then\n"
            "select your gender to continue.",
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
        bot.send_message(message.chat.id, f"❌ Error sending photo: {e}")


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
            "🔒 You do not have permission to view these photos.",
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
        bot.send_message(message.chat.id, f"❌ Error sending photo: {e}")


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
            "⚠️ To use the bot, open a private chat and send /start, then\n"
            "select your gender to continue.",
            reply_to_message_id=message.message_id
        )
        return

    vid_doc = videos.find_one({"_id": text})
    if not vid_doc:
        bot.send_message(
            message.chat.id,
            "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
            f"<blockquote>• 𝗩𝗶𝗱𝗲𝗼 {h(text)} ကို ရှာမတွေ့ပါ။\n"
            "• Check the ID and try again.</blockquote>",
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
        bot.send_message(message.chat.id, f"❌ Error sending video: {e}")

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
            bot.send_message(message.chat.id, f"❌ Error sending photo: {e}")

    try:
        bot.delete_message(message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # Rating buttons
    try:
        bot.send_message(
            message.chat.id,
            f"<b>⭐ {h(text)}</b> — You can rate this item",
            parse_mode='HTML',
            reply_markup=rating_markup(text)
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
            "🔒 You do not have permission to view these videos.",
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
            "• Check the ID and try again.</blockquote>",
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
        bot.send_message(message.chat.id, f"❌ Error sending video: {e}")

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
            bot.send_message(message.chat.id, f"❌ Error sending photo: {e}")

    try:
        bot.delete_message(message.chat.id, loading_msg.message_id)
    except Exception:
        pass

    # Rating buttons for group z-video
    try:
        bot.send_message(
            message.chat.id,
            f"<b>⭐ {h(text)}</b> — You can rate this item",
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
            "🚫 You are blocked from using this bot."
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
            "🏠 Returned to the main menu.",
            reply_markup=main_menu_keyboard(user_id)
        )
        send_welcome(message.chat.id, user_id)
        return

    # ── Owner menu: ⚙️ Control Panel ───────────────────────────────────────────
    if text == "⚙️ Control Panel":
        if user_id not in OWNER_IDS:
            return
        bot.send_message(
            message.chat.id,
            "<b>⚙️ 𝗢𝘄𝗻𝗲𝗿 𝗖𝗼𝗻𝘁𝗿𝗼𝗹 𝗣𝗮𝗻𝗲𝗹</b>\n\n"
            "<blockquote>Choose an owner command using the keyboard buttons below.\n"
            "Enter the required user ID, video ID, or link after the command.</blockquote>",
            parse_mode='HTML',
            reply_markup=owner_panel_keyboard()
        )
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
                f"⏳ Sending... 0 / {len(all_ids)}"
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
                            f"⏳ Sending... {i} / {len(all_ids)}",
                            message.chat.id, status_msg.message_id
                        )
                    except Exception:
                        pass
            try:
                bot.edit_message_text(
                    f"✅ Broadcast completed\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"✔ Sent successfully: {sent_ok} ဦး\n"
                    f"✘ Failed: {sent_fail} ဦး",
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
                    reply_markup=main_menu_keyboard(user_id)
                )
            except Exception as e:
                bot.send_message(
                    message.chat.id,
                    f"❌ Failed to send: {e}",
                    reply_markup=main_menu_keyboard(user_id)
                )
        return

    # ── Contact state ─────────────────────────────────────────────────────────
    if state == "waiting_contact":
        users.update_one({"_id": user_id}, {"$set": {"state": "normal"}})
        bot.send_message(
            message.chat.id,
            "<b>✅ 𝗦𝗲𝗻𝘁 𝗦𝘂𝗰𝗰𝗲𝘀𝘀𝗳𝘂𝗹𝗹𝘆</b>\n\n"
            "<blockquote>• Your message has been\n"
            "  forwarded to the 𝗕𝗼𝘁 𝗢𝘄𝗻𝗲𝗿 ✅</blockquote>",
            parse_mode='HTML',
            reply_markup=main_menu_keyboard(user_id)
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
        profile_text = (
            "<b>👤 MY PROFILE</b>\n"
            "<i>Your Blue Bot account at a glance</i>\n\n"
            "<blockquote>"
            "<b>ACCOUNT DETAILS</b>\n"
            f"👤 <b>Name</b>\n<code>{h(display_name)}</code>\n\n"
            f"🆔 <b>Telegram ID</b>\n<code>{user_id}</code>\n\n"
            "<b>VIDEO ACCESS</b>\n"
            "🎬 <b>Unlimited</b>\n\n"
            "<b>SHARING ACTIVITY</b>\n"
            f"🔗 <b>Total shares:</b> {doc.get('shares', 0)}"
            "</blockquote>\n\n"
            "<i>Your account information is shown above.</i>"
        )
        bot.send_message(message.chat.id, profile_text, parse_mode='HTML')
        return

    # ── Menu button: 🔗 Share & Refer ─────────────────────────────────────────
    if text == "🔗 𝗦𝗵𝗮𝗿𝗲 & 𝗥𝗲𝗳𝗲𝗿":
        referral_link = f"https://t.me/{BOT_USERNAME}?start={user_id}"
        share_url = f"https://t.me/share/url?url={quote(referral_link, safe='')}"
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📤 Share referral link", url=share_url, style="primary"))
        bot.send_message(
            message.chat.id,
            "<b>🔗 𝗦𝗵𝗮𝗿𝗲 &amp; 𝗥𝗲𝗳𝗲𝗿</b>\n"
            "<i>Invite friends to discover Blue Bot</i>\n\n"
            "<blockquote><b>YOUR PERSONAL REFERRAL LINK</b>\n"
            f"<code>{h(referral_link)}</code>\n\n"
            "• Share this link with friends.\n"
            "• When they open it, Telegram will take them to Blue Bot.\n"
            "• Your personal link helps identify referrals.</blockquote>\n\n"
            "👇 <i>Tap the button below to share your link.</i>",
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
            f"<blockquote>• Total videos ——— 𝟬{total} ခု\n\n"
            f"• v1 မှ v{total} are available to search.</blockquote>",
            parse_mode='HTML'
        )
        return

    # ── Menu button: 📞 Contact Owner ─────────────────────────────────────────
    if text == "📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿":
        if message.chat.type != "private":
            return
        users.update_one({"_id": user_id}, {"$set": {"state": "waiting_contact"}})
        bot.send_message(
            message.chat.id,
            "<b>📞 𝗖𝗼𝗻𝘁𝗮𝗰𝘁 𝗢𝘄𝗻𝗲𝗿</b>\n"
            "<i>Blue Bot Support</i>\n\n"
            "<blockquote>Have a question or need help? Send us a message, and we'll make sure it reaches the bot owner.\\n\\n"
            "• Type and send your message below.\\n"
            "• Your message will be forwarded directly to the bot owner.\\n"
            "• To cancel, tap ❌ Cancel.</blockquote>",
            parse_mode='HTML',
            reply_markup=cancel_keyboard()
        )
        return

    # ── Menu button: 🏆 Top Videos ────────────────────────────────────────────
    if text == "🏆 𝗧𝗼𝗽 𝗩𝗶𝗱𝗲𝗼𝘀 (Most Liked)":
        bot.send_message(
            message.chat.id,
            get_top_videos_text(10),
            parse_mode='HTML'
        )
        return

    # ── Video search (vN pattern) ─────────────────────────────────────────────
    if re.fullmatch(r"v\d+", text, re.IGNORECASE):
        vid_key = text.lower()

        vid_doc = videos.find_one({"_id": vid_key})
        if not vid_doc:
            bot.send_message(
                message.chat.id,
                "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
                f"<blockquote>• 𝗩𝗶𝗱𝗲𝗼 {h(vid_key)} was not found.\n"
                "• Check the ID and try again.</blockquote>",
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
                bot.send_message(message.chat.id, f"❌ Error sending photo: {e}")

        # Delete loading message
        try:
            bot.delete_message(message.chat.id, loading_msg.message_id)
        except Exception:
            pass

        # Rating buttons
        try:
            bot.send_message(
                message.chat.id,
                f"<b>⭐ {h(vid_key)}</b> — You can rate this item",
                parse_mode='HTML',
                reply_markup=rating_markup(vid_key)
            )
        except Exception:
            pass

        return

    # ── Private video search (zN pattern) — owner + accepted users only ─────────
    if re.fullmatch(r"z\d+", text, re.IGNORECASE):
        if not is_user_accepted(user_id):
            bot.send_message(
                message.chat.id,
                "🔒 You do not have permission to view these videos."
            )
            return

        vid_key = text.lower()
        vid_doc = videos.find_one({"_id": vid_key})
        if not vid_doc:
            bot.send_message(
                message.chat.id,
                "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
                f"<blockquote>• 𝗩𝗶𝗱𝗲𝗼 {h(vid_key)} was not found.\n"
                "• Check the ID and try again.</blockquote>",
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
                bot.send_message(message.chat.id, f"❌ Error sending photo: {e}")

        try:
            bot.delete_message(message.chat.id, loading_msg.message_id)
        except Exception:
            pass

        # Rating buttons for private zN
        try:
            bot.send_message(
                message.chat.id,
                f"<b>⭐ {h(vid_key)}</b> — You can rate this item",
                parse_mode='HTML',
                reply_markup=rating_markup(vid_key)
            )
        except Exception:
            pass

        return

    # ── Public photo search (pN pattern) ─────────────────────────────────────
    if re.fullmatch(r"p\d+", text, re.IGNORECASE):
        pid_key = text.lower()
        pid_doc = videos.find_one({"_id": pid_key})
        if not pid_doc or pid_doc.get("type") != "photo_only":
            bot.send_message(
                message.chat.id,
                "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
                f"<blockquote>• Photo {h(pid_key)} was not found.</blockquote>",
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
            bot.send_message(message.chat.id, f"❌ Error sending photo: {e}")
        return

    # ── Private photo search (zpN pattern) — owner + accepted users only ─────
    if re.fullmatch(r"zp\d+", text, re.IGNORECASE):
        if not is_user_accepted(user_id):
            bot.send_message(
                message.chat.id,
                "🔒 You do not have permission to view these photos."
            )
            return
        pid_key = text.lower()
        pid_doc = videos.find_one({"_id": pid_key})
        if not pid_doc or pid_doc.get("type") != "photo_only":
            bot.send_message(
                message.chat.id,
                "<b>❌ 𝗡𝗼𝘁 𝗙𝗼𝘂𝗻𝗱</b>\n\n"
                f"<blockquote>• Photo {h(pid_key)} was not found.</blockquote>",
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
            bot.send_message(message.chat.id, f"❌ Error sending photo: {e}")
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
        bot.answer_callback_query(call.id, "❌ Video not found")
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
    bot.answer_callback_query(call.id, f"{emoji} Your vote has been recorded!")

# ─── WEBHOOK + KEEP-ALIVE SERVER ──────────────────────────────────────────────
# Webhook mode: Telegram POSTs updates to /webhook.
# No polling → no 409 Conflict even when Render spins up a new instance.
# GET / → UptimeRobot keep-alive (always returns 200).

class WebhookHandler(BaseHTTPRequestHandler):

    def do_HEAD(self):
        if handle_admin_request(self, users, videos, settings, head_only=True, action_handler=handle_owner_action, user_bot_username=BOT_USERNAME):
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def do_GET(self):
        if handle_admin_request(self, users, videos, settings, action_handler=handle_owner_action, user_bot_username=BOT_USERNAME):
            return
        body = b"Blue Bot is Alive!"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if handle_admin_request(self, users, videos, settings, action_handler=handle_owner_action, user_bot_username=BOT_USERNAME):
            return
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

    # Set a non-Web-App default for everyone, then add the Web App only per owner.
    configure_telegram_menu_buttons(base_url)

    # Register webhook with Telegram (replaces any previous polling session).
    bot.remove_webhook()
    time.sleep(1)
    bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
    print(f"Webhook set → {webhook_url}")

    server = ThreadingHTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"Blue Bot webhook server running on port {port}.")
    server.serve_forever()
