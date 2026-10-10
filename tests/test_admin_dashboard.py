"""Security contract tests for the Telegram Mini App API."""
import hashlib
import hmac
import io
import json
import os
import unittest
from urllib.parse import urlencode
from unittest.mock import Mock, patch

import admin_dashboard

BOT_TOKEN = "123456:TEST_TOKEN"


def make_init_data(user_id=1234, token=BOT_TOKEN, now=1800000000):
    values = {
        "auth_date": str(now),
        "query_id": "AAE-test-query",
        "user": json.dumps({"id": user_id, "first_name": "Owner"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret_key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class FakeHandler:
    def __init__(self, path="/admin", command="GET", headers=None, body=b""):
        self.path = path
        self.command = command
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.client_address = ("127.0.0.1", 12345)
        self.status = None
        self.response_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass

    @property
    def response_body(self):
        return self.wfile.getvalue()


class TelegramInitDataTests(unittest.TestCase):
    def test_valid_owner_init_data_is_accepted(self):
        user = admin_dashboard.validate_telegram_init_data(make_init_data(), BOT_TOKEN, {1234}, now=1800000000)
        self.assertEqual(user["id"], 1234)

    def test_tampered_init_data_is_rejected(self):
        data = make_init_data().replace("Owner", "Intruder")
        self.assertIsNone(admin_dashboard.validate_telegram_init_data(data, BOT_TOKEN, {1234}, now=1800000000))

    def test_non_owner_is_rejected(self):
        data = make_init_data(user_id=9999)
        self.assertIsNone(admin_dashboard.validate_telegram_init_data(data, BOT_TOKEN, {1234}, now=1800000000))

    def test_expired_init_data_is_rejected(self):
        data = make_init_data()
        now = 1800000000 + admin_dashboard.INIT_DATA_MAX_AGE_SECONDS + 1
        self.assertIsNone(admin_dashboard.validate_telegram_init_data(data, BOT_TOKEN, {1234}, now=now))

    def test_future_init_data_is_rejected(self):
        data = make_init_data(now=1800000100)
        self.assertIsNone(admin_dashboard.validate_telegram_init_data(data, BOT_TOKEN, {1234}, now=1800000000))

    def test_duplicate_parameters_are_rejected(self):
        data = make_init_data() + "&auth_date=1800000000"
        self.assertIsNone(admin_dashboard.validate_telegram_init_data(data, BOT_TOKEN, {1234}, now=1800000000))

    def test_missing_bot_token_is_rejected(self):
        self.assertIsNone(admin_dashboard.validate_telegram_init_data(make_init_data(), "", {1234}, now=1800000000))


class MiniAppRouteTests(unittest.TestCase):
    def setUp(self):
        self.users = Mock()
        self.videos = Mock()
        self.settings = Mock()
        self.users.count_documents.return_value = 12
        self.videos.count_documents.side_effect = lambda query: (
            3 if query == {"_id": {"$regex": "^[vz][0-9]+$"}}
            else 2 if query == {"type": "photo_only"}
            else 0
        )

    def test_mini_app_shell_is_served_without_browser_password(self):
        handler = FakeHandler("/admin/")
        self.assertTrue(admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings))
        self.assertEqual(handler.status, 200)
        self.assertIn(b"telegram-web-app.js", handler.response_body)
        self.assertNotIn(b"Sign in securely", handler.response_body)

    def test_api_rejects_get_requests(self):
        handler = FakeHandler("/admin/api/overview", command="GET")
        admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertEqual(handler.status, 405)
        self.users.count_documents.assert_not_called()

    def test_api_rejects_invalid_owner_init_data(self):
        body = json.dumps({"initData": make_init_data(user_id=9999)}).encode()
        handler = FakeHandler("/admin/api/overview", command="POST", headers={"Content-Length": str(len(body))}, body=body)
        with patch.dict(os.environ, {"BOT_TOKEN": BOT_TOKEN, "OWNER_IDS": "1234"}, clear=False), patch("admin_dashboard.time.time", return_value=1800000000):
            admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertEqual(handler.status, 403)
        self.users.count_documents.assert_not_called()

    def test_owner_receives_only_aggregate_metrics(self):
        body = json.dumps({"initData": make_init_data()}).encode()
        handler = FakeHandler("/admin/api/overview", command="POST", headers={"Content-Length": str(len(body))}, body=body)
        with patch.dict(os.environ, {"BOT_TOKEN": BOT_TOKEN, "OWNER_IDS": "1234"}, clear=False), patch("admin_dashboard.time.time", return_value=1800000000):
            admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertEqual(set(payload), {"owner", "users", "media", "videos", "photos", "requests_today", "status"})
        self.assertEqual(payload["owner"]["id"], 1234)
        self.assertEqual(payload["users"], 12)
        self.assertEqual(payload["media"], 5)
        self.assertEqual(payload["videos"], 3)
        self.assertEqual(payload["photos"], 2)
        self.assertEqual(
            self.videos.count_documents.call_args_list,
            [
                unittest.mock.call({"_id": {"$regex": "^[vz][0-9]+$"}}),
                unittest.mock.call({"type": "photo_only"}),
            ],
        )
        self.assertIsNone(payload["requests_today"])

    def test_assets_are_public_but_do_not_expose_api_data(self):
        handler = FakeHandler("/admin/app.js")
        admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertEqual(handler.status, 200)
        self.assertIn(b"Telegram.WebApp", handler.response_body)
        self.users.count_documents.assert_not_called()


if __name__ == "__main__":
    unittest.main()
