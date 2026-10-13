"""Isolated static route handler for the Kingdom Builder Mini App."""
from pathlib import Path

GAME_DIR = Path(__file__).resolve().parent / "user_app" / "game"

# Explicit allowlist: game routes cannot expose arbitrary files from the app tree.
_GAME_ASSETS = {
    "/app/game/game.css": ("game.css", "text/css; charset=utf-8"),
    "/app/game/game.js": ("game.js", "text/javascript; charset=utf-8"),
}


def handle_request(handler, path, method, send):
    """Handle only Kingdom Builder pages/assets; return False for unrelated routes."""
    if path not in ("/app/game", "/app/game/") and path not in _GAME_ASSETS:
        return False

    if method not in ("GET", "HEAD"):
        send(handler, 405, b"Method not allowed.")
        return True

    if path in ("/app/game", "/app/game/"):
        filename, content_type = "index.html", "text/html; charset=utf-8"
    else:
        filename, content_type = _GAME_ASSETS[path]

    try:
        body = (GAME_DIR / filename).read_bytes()
    except OSError:
        status, body = (503, b"Game assets are unavailable.") if filename == "index.html" else (404, b"Not found.")
        send(handler, status, body)
        return True

    send(handler, 200, body, content_type)
    return True
