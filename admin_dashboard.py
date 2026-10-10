"""Authenticated, read-only admin dashboard routes for Blue Bot.

The dashboard is disabled unless both ADMIN_DASHBOARD_PASSWORD and ADMIN_SESSION_SECRET
meet the configured length policy. Short session secrets reduce cryptographic security.
No Telegram handlers or database writes live here.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ADMIN_DIR = Path(__file__).resolve().parent / "admin"
COOKIE_NAME = "bluebot_admin_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
MAX_LOGIN_BODY = 4096
_LOGIN_FAILURES = {}


def _configuration():
    password = os.environ.get("ADMIN_DASHBOARD_PASSWORD", "")
    secret = os.environ.get("ADMIN_SESSION_SECRET", "")
    if not 6 <= len(password) <= 16 or not 6 <= len(secret) <= 20:
        return None
    return password, secret.encode("utf-8")


def _make_session_token(secret, timestamp=None):
    issued_at = int(time.time() if timestamp is None else timestamp)
    payload = str(issued_at) + "." + secrets.token_urlsafe(24)
    signature = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()
    return payload + "." + signature


def _verify_session_token(token, secret, now=None):
    if not token:
        return False
    parts = token.split(".", 2)
    if len(parts) != 3:
        return False
    timestamp_text, nonce, signature = parts
    if (not timestamp_text.isascii() or not timestamp_text.isdigit()
            or not nonce.isascii() or not nonce
            or len(signature) != 64
            or any(char not in "0123456789abcdef" for char in signature)):
        return False
    issued_at = int(timestamp_text)
    current_time = int(time.time() if now is None else now)
    if issued_at > current_time + 60 or current_time - issued_at > SESSION_TTL_SECONDS:
        return False
    payload = timestamp_text + "." + nonce
    expected = hmac.new(secret, payload.encode("ascii"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def _has_session(handler, secret):
    cookie_header = handler.headers.get("Cookie", "")
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
        morsel = cookie.get(COOKIE_NAME)
        return bool(morsel and _verify_session_token(morsel.value, secret))
    except (ValueError, TypeError):
        return False


def _send(handler, status, body=b"", content_type="text/plain; charset=utf-8", headers=None):
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "DENY")
    handler.send_header("Referrer-Policy", "no-referrer")
    handler.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; img-src 'self' data:")
    for key, value in (headers or {}).items():
        handler.send_header(key, value)
    handler.end_headers()
    if body and getattr(handler, "command", "GET") != "HEAD":
        handler.wfile.write(body)


def _json(handler, status, payload, headers=None):
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    _send(handler, status, body, "application/json; charset=utf-8", headers)


def _login_page(message=""):
    safe_message = message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    return ("""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="dark">
<title>Blue Bot — Secure Admin Login</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:#080d1a;color:#eef2ff;font:14px system-ui,sans-serif;padding:24px}
main{width:min(100%,410px);padding:32px;border:1px solid #202c42;border-radius:18px;background:#10182a;box-shadow:0 24px 80px #0005}
.brand{color:#a19eff;font-weight:800;letter-spacing:.16em;font-size:12px}h1{font-size:25px;margin:20px 0 8px}p{color:#94a3b8;line-height:1.6}label{display:block;margin:24px 0 8px;color:#cbd5e1}
input{width:100%;padding:13px;border-radius:9px;border:1px solid #334155;background:#080d1a;color:#fff;font:inherit}
button{width:100%;margin-top:16px;padding:13px;border:0;border-radius:9px;background:#6865ee;color:white;font-weight:700;font:inherit;cursor:pointer}
.error{color:#fca5a5;font-size:13px}small{display:block;margin-top:20px;color:#64748b;line-height:1.5}
</style></head><body><main><div class="brand">BLUE BOT · ADMIN CONSOLE</div><h1>Sign in securely</h1>
<p>This dashboard is restricted to authorized administrators.</p>""" +
        (f'<p class="error">{safe_message}</p>' if safe_message else "") +
        """<form method="post" action="/admin/login" autocomplete="on"><label for="password">Dashboard password</label>
<input id="password" name="password" type="password" required minlength="6" maxlength="16" autocomplete="current-password" autofocus>
<button type="submit">Continue to dashboard</button></form>
<small>Use HTTPS. Access is disabled until the server administrator configures dashboard credentials.</small></main></body></html>""").encode("utf-8")


def _client_key(handler):
    try:
        return str(handler.client_address[0])
    except (AttributeError, IndexError, TypeError):
        return "unknown"


def handle_admin_request(handler, users, videos, settings, head_only=False):
    """Handle /admin routes; return True when the request was consumed."""
    parsed = urlsplit(handler.path)
    path = parsed.path
    if path != "/admin" and not path.startswith("/admin/"):
        return False

    config = _configuration()
    if config is None:
        _send(handler, 503, b"Admin dashboard is disabled: configure strong dashboard credentials.")
        return True
    password, secret = config
    method = "HEAD" if head_only else handler.command

    if path == "/admin/logout":
        if method != "POST":
            _send(handler, 405, b"Method not allowed.", headers={"Allow": "POST"})
            return True
        _send(handler, 303, b"", headers={
            "Location": "/admin/login",
            "Set-Cookie": f"{COOKIE_NAME}=; Path=/admin; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; Secure; SameSite=Strict"
        })
        return True

    if path == "/admin/login":
        if method == "GET":
            _send(handler, 200, _login_page(), "text/html; charset=utf-8")
            return True
        if method != "POST":
            _send(handler, 405, b"Method not allowed.", headers={"Allow": "GET, POST"})
            return True
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            length = MAX_LOGIN_BODY + 1
        if length < 0 or length > MAX_LOGIN_BODY:
            _send(handler, 413, b"Request too large.")
            return True
        raw = handler.rfile.read(length)
        content_type = handler.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/x-www-form-urlencoded":
            _send(handler, 415, b"Unsupported content type.")
            return True
        try:
            submitted = parse_qs(raw.decode("utf-8"), keep_blank_values=True).get("password", [""])[0]
        except (UnicodeDecodeError, ValueError):
            submitted = ""
        now = time.time()
        key = _client_key(handler)
        failures, reset_at = _LOGIN_FAILURES.get(key, (0, now + 900))
        if now >= reset_at:
            failures, reset_at = 0, now + 900
        if failures >= 5:
            _LOGIN_FAILURES[key] = (failures, reset_at)
            _send(handler, 429, b"Too many login attempts. Try again later.")
            return True
        if not hmac.compare_digest(submitted.encode("utf-8"), password.encode("utf-8")):
            _LOGIN_FAILURES[key] = (failures + 1, reset_at)
            _send(handler, 401, _login_page("Sign-in failed. Check your password and try again."), "text/html; charset=utf-8")
            return True
        _LOGIN_FAILURES.pop(key, None)
        token = _make_session_token(secret)
        _send(handler, 303, b"", headers={
            "Location": "/admin",
            "Set-Cookie": f"{COOKIE_NAME}={token}; Path=/admin; Max-Age={SESSION_TTL_SECONDS}; HttpOnly; Secure; SameSite=Strict"
        })
        return True

    if path in ("/admin", "/admin/"):
        if method not in ("GET", "HEAD"):
            _send(handler, 405, b"Method not allowed.", headers={"Allow": "GET, HEAD"})
            return True
        if not _has_session(handler, secret):
            _send(handler, 303, b"", headers={"Location": "/admin/login"})
            return True
        try:
            body = (ADMIN_DIR / "index.html").read_bytes()
        except OSError:
            _send(handler, 503, b"Dashboard assets are unavailable.")
            return True
        _send(handler, 200, body, "text/html; charset=utf-8")
        return True

    if path in ("/admin/styles.css", "/admin/app.js"):
        if method not in ("GET", "HEAD"):
            _send(handler, 405, b"Method not allowed.", headers={"Allow": "GET, HEAD"})
            return True
        if not _has_session(handler, secret):
            _send(handler, 401, b"Authentication required.")
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
        if method not in ("GET", "HEAD"):
            _json(handler, 405, {"error": "method_not_allowed"}, {"Allow": "GET, HEAD"})
            return True
        if not _has_session(handler, secret):
            _json(handler, 401, {"error": "authentication_required"})
            return True
        try:
            total_users = users.count_documents({})
            total_media = videos.count_documents({})
            total_photos = videos.count_documents({"type": "photo_only"})
            total_videos = max(0, total_media - total_photos)
        except Exception:
            _json(handler, 503, {"error": "metrics_unavailable"})
            return True
        _json(handler, 200, {
            "users": total_users,
            "media": total_media,
            "videos": total_videos,
            "photos": total_photos,
            "requests_today": None,
            "status": "connected"
        })
        return True

    _send(handler, 404, b"Not found.")
    return True
