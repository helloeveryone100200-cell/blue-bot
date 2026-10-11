"""Telegram Mini App assets and owner-authenticated read-only API for Blue Bot."""
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ADMIN_DIR = Path(__file__).resolve().parent / "admin"
USER_APP_DIR = Path(__file__).resolve().parent / "user_app"
MAX_API_BODY = 16 * 1024
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60
MAX_USER_PAGE_SIZE = 50


def _owner_ids():
    raw = os.environ.get("OWNER_IDS") or os.environ.get("OWNER_ID", "")
    return {int(item.strip()) for item in raw.split(",") if item.strip().isdigit()}


def validate_telegram_init_data(init_data, bot_token, owner_ids=None, now=None):
    """Return Telegram user details only when initData is valid and the user is an owner."""
    if not isinstance(init_data, str) or not init_data or len(init_data) > MAX_API_BODY:
        return None
    if not bot_token or bot_token == "YOUR_BOT_TOKEN":
        return None
    try:
        # initData is small and normally contains only a handful of fields.
        # Cap parsed fields to bound CPU/memory work for malformed signed payloads.
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
        values = {}
        for key, value in pairs:
            if key in values:
                return None
            values[key] = value
        received_hash = values.pop("hash", "")
        if len(received_hash) != 64 or any(c not in "0123456789abcdef" for c in received_hash):
            return None
        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received_hash, expected_hash):
            return None
        auth_date = int(values.get("auth_date", "0"))
        current_time = int(time.time() if now is None else now)
        if auth_date <= 0 or auth_date > current_time + 60 or current_time - auth_date > INIT_DATA_MAX_AGE_SECONDS:
            return None
        user = json.loads(values.get("user", ""))
        if not isinstance(user, dict) or type(user.get("id")) is not int:
            return None
        authorized_ids = _owner_ids() if owner_ids is None else set(owner_ids)
        return user if user["id"] in authorized_ids else None
    except (ValueError, TypeError, UnicodeError):
        return None


def validate_telegram_user_init_data(init_data, bot_token, now=None):
    """Return a Telegram user only when the signed initData is valid and fresh."""
    if not isinstance(init_data, str) or not init_data or len(init_data) > MAX_API_BODY:
        return None
    if not bot_token or bot_token == "YOUR_BOT_TOKEN":
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=64)
        values = {}
        for key, value in pairs:
            if key in values:
                return None
            values[key] = value
        received_hash = values.pop("hash", "")
        if len(received_hash) != 64 or any(c not in "0123456789abcdef" for c in received_hash):
            return None
        data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(received_hash, expected_hash):
            return None
        auth_date = int(values.get("auth_date", "0"))
        current_time = int(time.time() if now is None else now)
        if auth_date <= 0 or auth_date > current_time + 60 or current_time - auth_date > INIT_DATA_MAX_AGE_SECONDS:
            return None
        user = json.loads(values.get("user", ""))
        if not isinstance(user, dict) or type(user.get("id")) is not int:
            return None
        return user
    except (ValueError, TypeError, UnicodeError):
        return None


def _read_user_payload(handler):
    """Read a bounded JSON request and authenticate any Telegram user via initData."""
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except (TypeError, ValueError):
        length = MAX_API_BODY + 1
    if length <= 0 or length > MAX_API_BODY:
        _json(handler, 413, {"error": "invalid_request_size"})
        return None, False
    try:
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _json(handler, 400, {"error": "invalid_json"})
        return None, False
    if not isinstance(payload, dict):
        _json(handler, 400, {"error": "invalid_request"})
        return None, False
    user = validate_telegram_user_init_data(payload.get("initData"), os.environ.get("BOT_TOKEN", ""))
    if user is None:
        _json(handler, 403, {"error": "telegram_authentication_failed"})
        return None, False
    return (user, payload), True


def _send(handler, status, body=b"", content_type="text/plain; charset=utf-8"):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "SAMEORIGIN")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' https://telegram.org; connect-src 'self'; img-src 'self' data: https://t.me; font-src 'self' data:")
    handler.end_headers()
    if body and getattr(handler, "command", "GET") != "HEAD":
        handler.wfile.write(body)


def _json(handler, status, payload):
    _send(handler, status, json.dumps(payload, separators=(",", ":")).encode("utf-8"), "application/json; charset=utf-8")


def _safe_nonnegative_int(value):
    """Return only a non-negative, non-boolean integer from stored metadata."""
    return value if type(value) is int and value >= 0 else 0


def _parse_pagination(payload):
    """Validate JSON pagination fields without coercing booleans, floats, or strings."""
    page = payload.get("page", 1)
    page_size = payload.get("pageSize", 20)
    if type(page) is not int or type(page_size) is not int:
        return None
    if page < 1 or page > 1_000_000:
        return None
    return page, min(max(page_size, 1), MAX_USER_PAGE_SIZE)


def _read_owner_payload(handler):
    """Read a bounded JSON request and authenticate its Telegram owner initData."""
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except (TypeError, ValueError):
        length = MAX_API_BODY + 1
    if length <= 0 or length > MAX_API_BODY:
        _json(handler, 413, {"error": "invalid_request_size"})
        return None, False
    try:
        payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        _json(handler, 400, {"error": "invalid_json"})
        return None, False
    if not isinstance(payload, dict):
        _json(handler, 400, {"error": "invalid_request"})
        return None, False
    user = validate_telegram_init_data(payload.get("initData"), os.environ.get("BOT_TOKEN", ""))
    if user is None:
        _json(handler, 403, {"error": "telegram_owner_authentication_failed"})
        return None, False
    return (user, payload), True


def handle_admin_request(handler, users, videos, settings, head_only=False, action_handler=None, user_bot_username=""):
    """Serve the separate owner and user Telegram Mini Apps with role-specific APIs."""
    path = urlsplit(handler.path).path
    is_user_app = path == "/app" or path.startswith("/app/")
    is_admin_app = path == "/admin" or path.startswith("/admin/")
    if not is_admin_app and not is_user_app:
        return False
    method = "HEAD" if head_only else handler.command
    app_dir = USER_APP_DIR if is_user_app else ADMIN_DIR

    if path in ("/app", "/app/", "/admin", "/admin/"):
        if method not in ("GET", "HEAD"):
            _send(handler, 405, b"Method not allowed.")
            return True
        try:
            body = (app_dir / "index.html").read_bytes()
        except OSError:
            _send(handler, 503, b"Mini App assets are unavailable.")
            return True
        _send(handler, 200, body, "text/html; charset=utf-8")
        return True

    if path in ("/admin/styles.css", "/admin/app.js", "/app/styles.css", "/app/app.js"):
        if method not in ("GET", "HEAD"):
            _send(handler, 405, b"Method not allowed.")
            return True
        asset_name = "styles.css" if path.endswith(".css") else "app.js"
        try:
            body = (app_dir / asset_name).read_bytes()
        except OSError:
            _send(handler, 404, b"Not found.")
            return True
        content_type = "text/css; charset=utf-8" if asset_name.endswith(".css") else "text/javascript; charset=utf-8"
        _send(handler, 200, body, content_type)
        return True

    if path == "/app/api/profile":
        if method != "POST":
            _json(handler, 405, {"error": "method_not_allowed"})
            return True
        authenticated, valid = _read_user_payload(handler)
        if not valid:
            return True
        telegram_user, _payload = authenticated
        user_id = telegram_user["id"]
        try:
            doc = users.find_one(
                {"_id": user_id},
                {"_id": 1, "username": 1, "first_name": 1, "shares": 1, "is_banned": 1},
            )
            if not doc:
                _json(handler, 404, {"error": "user_not_found"})
                return True
            accepted = settings.find_one({"_id": "accepted_users"}, {"ids": 1})
            accepted_ids = accepted.get("ids", []) if accepted else []
            if not isinstance(accepted_ids, list):
                accepted_ids = []
            private_access = user_id in _owner_ids() or user_id in accepted_ids
            public_videos = videos.count_documents({"_id": {"$regex": "^v[0-9]+$"}})
            public_photos = videos.count_documents({
                "_id": {"$regex": "^p[0-9]+$"}, "type": "photo_only"
            })
        except Exception:
            _json(handler, 503, {"error": "profile_unavailable"})
            return True
        username = str(telegram_user.get("username") or doc.get("username") or "")[:64]
        first_name = str(telegram_user.get("first_name") or doc.get("first_name") or "")[:128]
        shares = doc.get("shares", 0)
        if type(shares) is not int or shares < 0:
            shares = 0
        bot_url = ""
        if isinstance(user_bot_username, str) and re.fullmatch(r"[A-Za-z0-9_]{5,32}", user_bot_username):
            bot_url = f"https://t.me/{user_bot_username}?start={user_id}"
        _json(handler, 200, {
            "profile": {
                "id": str(user_id),
                "username": username,
                "first_name": first_name,
                "shares": shares,
                "is_banned": doc.get("is_banned") is True,
                "private_access": private_access,
            },
            "library": {"public_videos": public_videos, "public_photos": public_photos},
            "bot_url": bot_url,
        })
        return True

    if path in ("/admin/api/overview", "/admin/api/users", "/admin/api/user-detail", "/admin/api/media", "/admin/api/settings", "/admin/api/action"):
        if method != "POST":
            _json(handler, 405, {"error": "method_not_allowed"})
            return True
        authenticated, valid = _read_owner_payload(handler)
        if not valid:
            return True
        owner, payload = authenticated

        if path == "/admin/api/action":
            if action_handler is None:
                _json(handler, 503, {"error": "owner_actions_unavailable"})
                return True
            try:
                result = action_handler(owner, payload)
            except ValueError as exc:
                error_code = str(exc)[:80] or "invalid_action"
                _json(handler, 400, {"error": error_code})
                return True
            except Exception:
                _json(handler, 503, {"error": "owner_action_failed"})
                return True
            if not isinstance(result, dict):
                _json(handler, 503, {"error": "invalid_action_result"})
                return True
            _json(handler, 200, result)
            return True

        if path == "/admin/api/users":
            raw_query = payload.get("query", "")
            if not isinstance(raw_query, str) or len(raw_query) > 80:
                _json(handler, 400, {"error": "invalid_query"})
                return True
            pagination = _parse_pagination(payload)
            if pagination is None:
                _json(handler, 400, {"error": "invalid_pagination"})
                return True
            page, page_size = pagination
            query = raw_query.strip()
            filters = {}
            if query:
                escaped_query = re.escape(query)
                filters = {"$or": [
                    {"username": {"$regex": escaped_query, "$options": "i"}},
                    {"first_name": {"$regex": escaped_query, "$options": "i"}},
                ]}
                # User IDs are stored as integers by get_or_create_user().
                if query.isdigit():
                    # MongoDB integer _id values use signed 64-bit BSON integers.
                    # Keep oversized digit strings as text searches instead of letting
                    # int64 serialization fail the entire user-directory request.
                    numeric_id = int(query)
                    if numeric_id <= 9_223_372_036_854_775_807:
                        filters["$or"].append({"_id": numeric_id})
            try:
                total = users.count_documents(filters)
                # Clamp out-of-range pages before applying MongoDB skip().
                page = min(page, max(1, (total + page_size - 1) // page_size))
                cursor = users.find(
                    filters,
                    {"_id": 1, "username": 1, "first_name": 1, "shares": 1, "is_banned": 1},
                ).sort("_id", -1).skip((page - 1) * page_size).limit(page_size)
                items = []
                for doc in cursor:
                    user_id = doc.get("_id")
                    if not isinstance(user_id, (str, int)) or isinstance(user_id, bool):
                        continue
                    shares = doc.get("shares", 0)
                    if not isinstance(shares, int) or isinstance(shares, bool) or shares < 0:
                        shares = 0
                    items.append({
                        "id": str(user_id),
                        "username": str(doc.get("username") or "")[:64],
                        "first_name": str(doc.get("first_name") or "")[:128],
                        "shares": shares,
                        "is_banned": doc.get("is_banned") is True,
                    })
            except Exception:
                _json(handler, 503, {"error": "users_unavailable"})
                return True
            _json(handler, 200, {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": max(1, (total + page_size - 1) // page_size),
            })
            return True

        if path == "/admin/api/user-detail":
            raw_user_id = payload.get("userId", "")
            if not isinstance(raw_user_id, str) or not re.fullmatch(r"[0-9]{1,20}", raw_user_id):
                _json(handler, 400, {"error": "invalid_user_id"})
                return True
            # User _id values are stored as BSON signed 64-bit integers.
            if int(raw_user_id) > 9_223_372_036_854_775_807:
                _json(handler, 400, {"error": "invalid_user_id"})
                return True
            try:
                user_id = int(raw_user_id)
                doc = users.find_one(
                    {"_id": user_id},
                    {"_id": 1, "username": 1, "first_name": 1, "shares": 1,
                     "is_banned": 1, "referrals": 1, "state": 1, "joined_at": 1},
                )
            except Exception:
                _json(handler, 503, {"error": "user_detail_unavailable"})
                return True
            if not doc:
                _json(handler, 404, {"error": "user_not_found"})
                return True
            def safe_count(value):
                return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
            joined_at = doc.get("joined_at", "—")
            if not isinstance(joined_at, (str, int, float)):
                joined_at = "—"
            _json(handler, 200, {
                "id": str(doc.get("_id")),
                "username": str(doc.get("username") or "")[:64],
                "first_name": str(doc.get("first_name") or "")[:128],
                "shares": safe_count(doc.get("shares", 0)),
                "referrals": safe_count(doc.get("referrals", 0)),
                "is_banned": doc.get("is_banned") is True,
                "state": str(doc.get("state") or "normal")[:64],
                "joined_at": str(joined_at)[:80],
            })
            return True

        if path == "/admin/api/media":
            raw_query = payload.get("query", "")
            kind = payload.get("kind", "all")
            if not isinstance(raw_query, str) or len(raw_query) > 80:
                _json(handler, 400, {"error": "invalid_query"})
                return True
            if kind not in ("all", "videos", "photos"):
                _json(handler, 400, {"error": "invalid_media_kind"})
                return True
            pagination = _parse_pagination(payload)
            if pagination is None:
                _json(handler, 400, {"error": "invalid_pagination"})
                return True
            page, page_size = pagination
            filters = {}
            if kind == "videos":
                filters["_id"] = {"$regex": "^[vz][0-9]+$"}
            elif kind == "photos":
                filters["type"] = "photo_only"
            query = raw_query.strip()
            if query:
                escaped_query = re.escape(query)
                search_filter = {"$or": [
                    {"_id": {"$regex": escaped_query, "$options": "i"}},
                    {"caption": {"$regex": escaped_query, "$options": "i"}},
                ]}
                filters = {"$and": [filters, search_filter]} if filters else search_filter
            try:
                total = videos.count_documents(filters)
                # Clamp out-of-range pages before applying MongoDB skip().
                page = min(page, max(1, (total + page_size - 1) // page_size))
                cursor = videos.find(
                    filters,
                    {"_id": 1, "type": 1, "caption": 1, "private": 1, "likes": 1,
                     "dislikes": 1, "views": 1, "video_ids": 1, "photo_ids": 1},
                ).sort("_id", -1).skip((page - 1) * page_size).limit(page_size)
                items = []
                for doc in cursor:
                    media_id = doc.get("_id")
                    if not isinstance(media_id, str) or not re.fullmatch(r"(?:v|z|p|zp)[0-9]+", media_id):
                        continue
                    is_photo = doc.get("type") == "photo_only"
                    items.append({
                        "id": media_id,
                        "kind": "photo" if is_photo else "video",
                        "visibility": "private" if doc.get("private") is True or media_id.startswith(("z", "zp")) else "public",
                        "caption": str(doc.get("caption") or "")[:180],
                        "likes": _safe_nonnegative_int(doc.get("likes", 0)),
                        "dislikes": _safe_nonnegative_int(doc.get("dislikes", 0)),
                        "views": _safe_nonnegative_int(doc.get("views", 0)),
                        "video_parts": len(doc.get("video_ids", [])) if isinstance(doc.get("video_ids", []), list) else 0,
                        "photo_parts": len(doc.get("photo_ids", [])) if isinstance(doc.get("photo_ids", []), list) else 0,
                    })
            except Exception:
                _json(handler, 503, {"error": "media_unavailable"})
                return True
            _json(handler, 200, {
                "items": items,
                "page": page,
                "page_size": page_size,
                "total": total,
                "pages": max(1, (total + page_size - 1) // page_size),
            })
            return True

        if path == "/admin/api/settings":
            try:
                channel = settings.find_one({"_id": "required_channel"}, {"chat_id": 1, "link": 1, "title": 1})
                public_group = settings.find_one({"_id": "admin_group"}, {"chat_id": 1})
                private_group = settings.find_one({"_id": "private_admin_group"}, {"chat_id": 1})
                broadcast = settings.find_one({"_id": "broadcast_new_video"}, {"enabled": 1})
                accepted = settings.find_one({"_id": "accepted_users"}, {"ids": 1})
                accepted_ids = accepted.get("ids", []) if accepted else []
                if not isinstance(accepted_ids, list):
                    accepted_ids = []
            except Exception:
                _json(handler, 503, {"error": "settings_unavailable"})
                return True
            channel_enabled = bool(channel and channel.get("chat_id") and channel.get("link"))
            # The stored setting is Boolean. Treat malformed values as the default
            # enabled state instead of truthiness-coercing strings such as "false".
            broadcast_value = broadcast.get("enabled", True) if broadcast else True
            broadcast_enabled = broadcast_value if isinstance(broadcast_value, bool) else True
            _json(handler, 200, {
                "channel_gate": {
                    "enabled": channel_enabled,
                    "title": str(channel.get("title") or "Required channel")[:120] if channel_enabled else "",
                },
                "public_media_group_configured": bool(public_group and public_group.get("chat_id") is not None),
                "private_media_group_configured": bool(private_group and private_group.get("chat_id") is not None),
                "auto_broadcast_new_video": broadcast_enabled,
                "private_access_users": len(accepted_ids),
            })
            return True

        try:
            total_users = users.count_documents({})
            # Video IDs use vN (public) and zN (private); photo-only IDs use pN/zpN.
            # Count by the existing document schema instead of treating every non-public
            # photo as a video or exposing a misleading total.
            total_videos = videos.count_documents({"_id": {"$regex": "^[vz][0-9]+$"}})
            total_photos = videos.count_documents({"type": "photo_only"})
            total_media = total_videos + total_photos
        except Exception:
            _json(handler, 503, {"error": "metrics_unavailable"})
            return True
        _json(handler, 200, {
            "owner": {"id": owner["id"], "name": owner.get("first_name", "Owner")},
            "users": total_users,
            "media": total_media,
            "videos": total_videos,
            "photos": total_photos,
            "requests_today": None,
            "status": "connected",
        })
        return True

    _send(handler, 404, b"Not found.")
    return True
