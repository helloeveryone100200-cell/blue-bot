"""Security and UI contract tests for the separate regular-user Mini App."""
import hashlib
import hmac
import io
import json
import os
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import Mock, patch

import admin_dashboard

BOT_TOKEN = "123456:TEST_TOKEN"
NOW = 1800000000
ROOT = Path(__file__).resolve().parents[1]


def make_init_data(user_id=5678, token=BOT_TOKEN, now=NOW, username="regular_user", first_name="Regular"):
    values = {
        "auth_date": str(now),
        "query_id": "AAE-user-test",
        "user": json.dumps(
            {"id": user_id, "first_name": first_name, "username": username},
            separators=(",", ":"),
        ),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class FakeHandler:
    def __init__(self, path="/app", command="GET", headers=None, body=b""):
        self.path = path
        self.command = command
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.status = None
        self.response_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass


class UserMiniAppTests(unittest.TestCase):
    def setUp(self):
        self.users = Mock()
        self.videos = Mock()
        self.settings = Mock()
        self.users.find_one.return_value = {
            "_id": 5678, "username": "regular_user", "first_name": "Regular",
            "shares": 4, "is_banned": False, "secret": "never-return-this",
            "gender": "private-field",
        }
        self.settings.find_one.return_value = {"ids": [5678]}
        self.videos.count_documents.side_effect = lambda query: (
            8 if query == {"_id": {"$regex": "^v[0-9]+$"}}
            else 3 if query == {"_id": {"$regex": "^p[0-9]+$"}, "type": "photo_only"}
            else 0
        )

    def request(self, path="/app/api/profile", payload=None, user_id=5678, method="POST"):
        body = json.dumps({"initData": make_init_data(user_id=user_id), **(payload or {})}).encode()
        handler = FakeHandler(path, command=method, headers={"Content-Length": str(len(body))}, body=body)
        with patch.dict(os.environ, {"BOT_TOKEN": BOT_TOKEN, "OWNER_IDS": "1234"}, clear=False), patch(
            "admin_dashboard.time.time", return_value=NOW
        ):
            admin_dashboard.handle_admin_request(
                handler, self.users, self.videos, self.settings, user_bot_username="BlueBotTest"
            )
        return handler

    def test_user_app_shell_and_assets_are_served_separately(self):
        shell = FakeHandler("/app/")
        self.assertTrue(admin_dashboard.handle_admin_request(shell, self.users, self.videos, self.settings))
        self.assertEqual(shell.status, 200)
        self.assertIn(b"User Dashboard", shell.wfile.getvalue())
        self.assertNotIn(b"OWNER CONSOLE", shell.wfile.getvalue())

        for path, expected_type in (
            ("/app/styles.css", "text/css; charset=utf-8"),
            ("/app/app.js", "text/javascript; charset=utf-8"),
        ):
            with self.subTest(path=path):
                handler = FakeHandler(path)
                admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
                self.assertEqual(handler.status, 200)
                self.assertEqual(handler.response_headers["Content-Type"], expected_type)

    def test_valid_non_owner_can_read_only_their_own_profile(self):
        handler = self.request(payload={"userId": "9999"})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.wfile.getvalue())
        self.assertEqual(payload["profile"], {
            "id": "5678", "username": "regular_user", "first_name": "Regular",
            "shares": 4, "is_banned": False, "private_access": True,
        })
        self.assertEqual(payload["library"], {"public_videos": 8, "public_photos": 3})
        self.assertEqual(payload["bot_url"], "https://t.me/BlueBotTest?start=5678")
        self.users.find_one.assert_called_once_with(
            {"_id": 5678},
            {"_id": 1, "username": 1, "first_name": 1, "shares": 1, "is_banned": 1},
        )
        self.assertNotIn("never-return-this", handler.wfile.getvalue().decode())
        self.assertNotIn("private-field", handler.wfile.getvalue().decode())
        self.assertNotIn("file_id", handler.wfile.getvalue().decode())

    def test_public_video_api_returns_only_public_metadata_and_deep_links(self):
        self.videos.find.return_value.sort.return_value.skip.return_value.limit.return_value = [
            {"_id": "v12", "caption": "Public title", "views": 7, "likes": 3, "dislikes": 1,
             "video_ids": ["secret-telegram-file-id"]},
            {"_id": "z12", "caption": "Private title", "video_ids": ["private-file-id"]},
        ]
        handler = self.request(path="/app/api/videos", payload={"page": 1, "pageSize": 12})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.wfile.getvalue())
        self.assertEqual(payload["total"], 8)
        self.assertEqual(payload["items"], [{
            "id": "v12", "title": "Public title", "views": 7, "likes": 3, "dislikes": 1,
            "watch_url": "https://t.me/BlueBotTest?start=ref_v12",
        }])
        self.videos.find.assert_called_once_with(
            {"_id": {"$regex": "^v[0-9]+$"}},
            {"_id": 1, "caption": 1, "views": 1, "likes": 1, "dislikes": 1},
        )
        response_text = handler.wfile.getvalue().decode()
        self.assertNotIn("secret-telegram-file-id", response_text)
        self.assertNotIn("private-file-id", response_text)
        self.assertNotIn("Private title", response_text)

    def test_public_video_api_requires_valid_telegram_authentication(self):
        body = json.dumps({"initData": "forged", "page": 1, "pageSize": 12}).encode()
        handler = FakeHandler("/app/api/videos", "POST", {"Content-Length": str(len(body))}, body)
        with patch.dict(os.environ, {"BOT_TOKEN": BOT_TOKEN, "OWNER_IDS": "1234"}, clear=False), patch(
            "admin_dashboard.time.time", return_value=NOW
        ):
            admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertEqual(handler.status, 403)
        self.videos.find.assert_not_called()
        self.videos.count_documents.assert_not_called()

    def test_public_video_api_rejects_banned_accounts(self):
        self.users.find_one.return_value = {"_id": 5678, "is_banned": True}
        handler = self.request(path="/app/api/videos")
        self.assertEqual(handler.status, 403)
        self.assertEqual(json.loads(handler.wfile.getvalue()), {"error": "account_restricted"})
        self.videos.find.assert_not_called()

    def test_signed_telegram_user_identity_not_client_supplied_user_id_is_used(self):
        self.request(payload={"userId": "1234"})
        self.users.find_one.assert_called_once()
        self.assertEqual(self.users.find_one.call_args.args[0], {"_id": 5678})

    def test_invalid_init_data_is_rejected_before_database_access(self):
        body = json.dumps({"initData": make_init_data().replace("Regular", "Forged")}).encode()
        handler = FakeHandler("/app/api/profile", "POST", {"Content-Length": str(len(body))}, body)
        with patch.dict(os.environ, {"BOT_TOKEN": BOT_TOKEN, "OWNER_IDS": "1234"}, clear=False), patch(
            "admin_dashboard.time.time", return_value=NOW
        ):
            admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertEqual(handler.status, 403)
        self.users.find_one.assert_not_called()
        self.videos.count_documents.assert_not_called()

    def test_profile_endpoint_rejects_get_and_unknown_mutation_routes(self):
        get_handler = FakeHandler("/app/api/profile", "GET")
        admin_dashboard.handle_admin_request(get_handler, self.users, self.videos, self.settings)
        self.assertEqual(get_handler.status, 405)
        unknown = self.request(path="/app/api/action")
        self.assertEqual(unknown.status, 404)
        for collection in (self.users, self.videos, self.settings):
            for method in ("insert_one", "update_one", "replace_one", "delete_one", "find_one_and_update"):
                getattr(collection, method).assert_not_called()

    def test_missing_user_returns_not_found_without_creating_record(self):
        self.users.find_one.return_value = None
        handler = self.request()
        self.assertEqual(handler.status, 404)
        self.assertEqual(json.loads(handler.wfile.getvalue()), {"error": "user_not_found"})
        self.users.insert_one.assert_not_called()

    def test_private_access_and_ban_status_are_normalized(self):
        self.settings.find_one.return_value = {"ids": []}
        self.users.find_one.return_value = {
            "_id": 5678, "username": "regular_user", "first_name": "Regular",
            "shares": -3, "is_banned": "false",
        }
        handler = self.request()
        payload = json.loads(handler.wfile.getvalue())
        self.assertEqual(payload["profile"]["shares"], 0)
        self.assertFalse(payload["profile"]["is_banned"])
        self.assertFalse(payload["profile"]["private_access"])

    
    def test_user_app_has_a_separate_https_resolver_and_regular_user_button(self):
        bot_source = (ROOT / "bot.py").read_text(encoding="utf-8")
        tree = __import__("ast").parse(bot_source, filename="bot.py")
        functions = {
            node.name: node for node in tree.body
            if isinstance(node, (__import__("ast").FunctionDef, __import__("ast").AsyncFunctionDef))
        }
        self.assertIn("resolve_user_webapp_url", functions)
        resolver_source = __import__("ast").get_source_segment(
            bot_source, functions["resolve_user_webapp_url"]
        )
        welcome_source = __import__("ast").get_source_segment(
            bot_source, functions["welcome_markup"]
        )
        self.assertIn('startswith("https://")', resolver_source)
        self.assertIn('"/app/"', resolver_source)
        self.assertIn("resolve_user_webapp_url", welcome_source)
        self.assertIn("Open Blue Bot", welcome_source)
        self.assertIn("OWNER_IDS", welcome_source)
        self.assertIn("ADMIN_WEBAPP_URL", bot_source)


    def test_18_plus_welcome_screen_precedes_dashboard_and_respects_reduced_motion(self):
        root = ROOT / "user_app"
        html = (root / "index.html").read_text(encoding="utf-8")
        css = (root / "styles.css").read_text(encoding="utf-8")
        js = (root / "app.js").read_text(encoding="utf-8")

        intro_position = html.index('id="intro-screen"')
        dashboard_position = html.index('class="app-shell"')
        self.assertLess(intro_position, dashboard_position)
        self.assertIn('aria-label="Welcome to 18+ Blue Bot"', html)
        self.assertIn('class="intro-age-number">18<span>+</span>', html)
        self.assertIn('class="intro-title"><span>WELCOME TO</span><strong>BLUE BOT</strong>', html)
        self.assertIn('.telegram-ready .app-shell { display: none; }', css)
        self.assertIn('.telegram-ready.welcome-complete .app-shell', css)
        self.assertIn('@media (prefers-reduced-motion: reduce)', css)
        self.assertIn("window.matchMedia('(prefers-reduced-motion: reduce)')", js)
        self.assertIn("document.body.classList.add('welcome-complete')", js)


    def test_dashboard_organic_contour_borders_cover_primary_surfaces(self):
        css = (ROOT / "user_app" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("--organic-border:", css)
        self.assertIn("border-radius: 27% 31% 24% 29% / 17% 20% 16% 19%;", css)
        for selector in (
            ".profile-card", ".metric-card", ".video-card", ".action-item",
            ".referral-panel", ".activity-panel", ".notification-panel",
            ".privacy-panel", ".support-contact-card", ".dashboard-bottom-nav",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector, css)
        self.assertIn(".video-card::after", css)
        self.assertIn("width: 16px;", css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)


if __name__ == "__main__":
    unittest.main()
