"""Telegram Mini App assets and owner-authenticated read-only API for Blue Bot."""
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

ADMIN_DIR = Path(__file__).resolve().parent / "admin"
MAX_API_BODY = 16 * 1024
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60


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
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
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
        if not isinstance(user, dict) or not isinstance(user.get("id"), int):
            return None
        authorized_ids = _owner_ids() if owner_ids is None else set(owner_ids)
        return user if user["id"] in authorized_ids else None
    except (ValueError, TypeError, UnicodeError):
        return None


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


def handle_admin_request(handler, users, videos, settings, head_only=False):
    """Serve the Telegram Mini App shell and a Telegram-owner-authenticated API."""
    path = urlsplit(handler.path).path
    if path != "/admin" and not path.startswith("/admin/"):
        return False
    method = "HEAD" if head_only else handler.command

    if path in ("/admin", "/admin/"):
        if method not in ("GET", "HEAD"):
            _send(handler, 405, b"Method not allowed.")
            return True
        try:
            body = (ADMIN_DIR / "index.html").read_bytes()
        except OSError:
            _send(handler, 503, b"Mini App assets are unavailable.")
            return True
        _send(handler, 200, body, "text/html; charset=utf-8")
        return True

    if path in ("/admin/styles.css", "/admin/app.js"):
        if method not in ("GET", "HEAD"):
            _send(handler, 405, b"Method not allowed.")
            return True
        asset_name = "styles.css" if path.endswith(".css") else "app.js"
        try:
            body = (ADMIN_DIR / asset_name).read_bytes()
        except OSError:
            _send(handler, 404, b"Not found.")
            return True
        content_type = "text/css; charset=utf-8" if asset_name.endswith(".css") else "text/javascript; charset=utf-8"
        _send(handler, 200, body, content_type)
        return True

    if path == "/admin/api/overview":
        if method != "POST":
            _json(handler, 405, {"error": "method_not_allowed"})
            return True
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            length = MAX_API_BODY + 1
        if length <= 0 or length > MAX_API_BODY:
            _json(handler, 413, {"error": "invalid_request_size"})
            return True
        try:
            payload = json.loads(handler.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _json(handler, 400, {"error": "invalid_json"})
            return True
        if not isinstance(payload, dict):
            _json(handler, 400, {"error": "invalid_request"})
            return True
        user = validate_telegram_init_data(payload.get("initData"), os.environ.get("BOT_TOKEN", ""))
        if user is None:
            _json(handler, 403, {"error": "telegram_owner_authentication_failed"})
            return True
        try:
            total_users = users.count_documents({})
            total_media = videos.count_documents({})
            total_photos = videos.count_documents({"type": "photo_only"})
        except Exception:
            _json(handler, 503, {"error": "metrics_unavailable"})
            return True
        _json(handler, 200, {
            "owner": {"id": user["id"], "name": user.get("first_name", "Owner")},
            "users": total_users,
            "media": total_media,
            "videos": max(0, total_media - total_photos),
            "photos": total_photos,
            "requests_today": None,
            "status": "connected",
        })
        return True

    _send(handler, 404, b"Not found.")
    return True
