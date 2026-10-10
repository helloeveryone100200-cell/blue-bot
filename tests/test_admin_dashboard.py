"""Security contract tests for the Telegram Mini App API."""
import hashlib
import hmac
import io
import json
import os
import unittest
from urllib.parse import urlencode
from unittest.mock import MagicMock, Mock, patch

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

    def test_boolean_user_id_is_rejected_even_when_owner_id_is_one(self):
        data = make_init_data(user_id=True)
        self.assertIsNone(admin_dashboard.validate_telegram_init_data(data, BOT_TOKEN, {1}, now=1800000000))

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

    def authed_request(self, path, payload):
        body = json.dumps({"initData": make_init_data(), **payload}).encode()
        handler = FakeHandler(path, command="POST", headers={"Content-Length": str(len(body))}, body=body)
        with patch.dict(os.environ, {"BOT_TOKEN": BOT_TOKEN, "OWNER_IDS": "1234"}, clear=False), patch(
            "admin_dashboard.time.time", return_value=1800000000
        ):
            admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        return handler

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
        handler = self.authed_request("/admin/api/overview", {})
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

    def test_owner_user_directory_returns_only_allowlisted_fields(self):
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.__iter__ = Mock(return_value=iter([{
            "_id": 1234, "username": "blue_owner", "first_name": "Blue",
            "shares": 7, "is_banned": False, "secret": "must-not-leak",
        }]))
        self.users.find.return_value = cursor
        self.users.count_documents.return_value = 1

        handler = self.authed_request("/admin/api/users", {"query": "Blue", "page": 1, "pageSize": 20})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertEqual(payload["total"], 1)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["pages"], 1)
        self.assertEqual(payload["items"], [{
            "id": "1234", "username": "blue_owner", "first_name": "Blue",
            "shares": 7, "is_banned": False,
        }])
        self.assertNotIn("secret", handler.response_body.decode())
        self.users.find.assert_called_once_with(
            {"$or": [
                {"username": {"$regex": "Blue", "$options": "i"}},
                {"first_name": {"$regex": "Blue", "$options": "i"}},
            ]},
            {"_id": 1, "username": 1, "first_name": 1, "shares": 1, "is_banned": 1},
        )
        cursor.sort.assert_called_once_with("_id", -1)
        cursor.skip.assert_called_once_with(0)
        cursor.limit.assert_called_once_with(20)

    def test_user_search_escapes_regex_and_matches_numeric_id_exactly(self):
        self.users.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
        handler = self.authed_request("/admin/api/users", {"query": "1234", "page": 1, "pageSize": 500})
        self.assertEqual(handler.status, 200)
        query = self.users.find.call_args.args[0]
        self.assertEqual(query["$or"][-1], {"_id": 1234})
        self.assertEqual(query["$or"][0]["username"]["$regex"], "1234")
        self.users.find.return_value.sort.return_value.skip.return_value.limit.assert_called_once_with(50)

        self.users.find.reset_mock()
        self.users.count_documents.return_value = 0
        self.authed_request("/admin/api/users", {"query": ".*", "page": 1})
        query = self.users.find.call_args.args[0]
        self.assertEqual(query["$or"][0]["username"]["$regex"], r"\.\*")

    def test_user_directory_clamps_page_before_database_skip(self):
        self.users.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
        handler = self.authed_request("/admin/api/users", {"page": 999999, "pageSize": 5})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertEqual(payload["page"], 3)
        self.assertEqual(payload["pages"], 3)
        self.users.find.return_value.sort.return_value.skip.assert_called_once_with(10)

    def test_media_directory_clamps_page_before_database_skip(self):
        self.videos.count_documents.side_effect = None
        self.videos.count_documents.return_value = 51
        self.videos.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
        handler = self.authed_request("/admin/api/media", {"page": 999999, "pageSize": 20})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertEqual(payload["page"], 3)
        self.assertEqual(payload["pages"], 3)
        self.videos.find.return_value.sort.return_value.skip.assert_called_once_with(40)

    def test_user_directory_rejects_invalid_pagination(self):
        handler = self.authed_request("/admin/api/users", {"page": 0})
        self.assertEqual(handler.status, 400)
        self.users.find.assert_not_called()

    def test_user_directory_database_failure_returns_service_unavailable(self):
        self.users.find.side_effect = RuntimeError("database unavailable")
        handler = self.authed_request("/admin/api/users", {})
        self.assertEqual(handler.status, 503)
        self.assertEqual(json.loads(handler.response_body), {"error": "users_unavailable"})

    def test_user_detail_returns_only_allowlisted_fields(self):
        self.users.find_one.return_value = {
            "_id": 1234, "username": "blue_owner", "first_name": "Blue",
            "shares": 7, "referrals": 3, "is_banned": False, "state": "normal",
            "joined_at": "2026-10-01", "gender": "must-not-leak", "secret": "must-not-leak",
        }
        handler = self.authed_request("/admin/api/user-detail", {"userId": "1234"})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertEqual(payload, {
            "id": "1234", "username": "blue_owner", "first_name": "Blue",
            "shares": 7, "referrals": 3, "is_banned": False, "state": "normal",
            "joined_at": "2026-10-01",
        })
        self.assertNotIn("gender", handler.response_body.decode())
        self.assertNotIn("secret", handler.response_body.decode())
        self.users.find_one.assert_called_once_with(
            {"_id": 1234},
            {"_id": 1, "username": 1, "first_name": 1, "shares": 1,
             "is_banned": 1, "referrals": 1, "state": 1, "joined_at": 1},
        )

    def test_user_detail_does_not_treat_string_false_as_banned(self):
        self.users.find_one.return_value = {"_id": 1234, "is_banned": "false"}
        handler = self.authed_request("/admin/api/user-detail", {"userId": "1234"})
        self.assertEqual(handler.status, 200)
        self.assertFalse(json.loads(handler.response_body)["is_banned"])

    def test_user_detail_rejects_invalid_ids(self):
        handler = self.authed_request("/admin/api/user-detail", {"userId": "12x"})
        self.assertEqual(handler.status, 400)
        self.assertEqual(json.loads(handler.response_body), {"error": "invalid_user_id"})
        self.users.find_one.assert_not_called()

    def test_user_detail_returns_not_found_for_unknown_user(self):
        self.users.find_one.return_value = None
        handler = self.authed_request("/admin/api/user-detail", {"userId": "9876"})
        self.assertEqual(handler.status, 404)
        self.assertEqual(json.loads(handler.response_body), {"error": "user_not_found"})

    def test_user_detail_database_failure_returns_generic_error(self):
        self.users.find_one.side_effect = RuntimeError("database secret")
        handler = self.authed_request("/admin/api/user-detail", {"userId": "1234"})
        self.assertEqual(handler.status, 503)
        self.assertEqual(json.loads(handler.response_body), {"error": "user_detail_unavailable"})
        self.assertNotIn("database secret", handler.response_body.decode())

    def test_media_directory_returns_metadata_without_telegram_file_ids(self):
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.__iter__.return_value = iter([{
            "_id": "v8", "type": "album", "caption": "Example title",
            "video_ids": ["secret-video-file-id"], "photo_ids": ["secret-photo-file-id"],
            "likes": 4, "dislikes": 1, "views": 99,
        }])
        self.videos.find.return_value = cursor
        self.videos.count_documents.return_value = 1

        handler = self.authed_request("/admin/api/media", {"query": "Example", "kind": "videos", "page": 1})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertEqual(payload["items"], [{
            "id": "v8", "kind": "video", "visibility": "public", "caption": "Example title",
            "likes": 4, "dislikes": 1, "views": 99, "video_parts": 1, "photo_parts": 1,
        }])
        self.assertNotIn("secret-video-file-id", handler.response_body.decode())
        self.assertNotIn("secret-photo-file-id", handler.response_body.decode())
        self.assertEqual(self.videos.find.call_args.args[0], {
            "$and": [
                {"_id": {"$regex": "^[vz][0-9]+$"}},
                {"$or": [
                    {"_id": {"$regex": "Example", "$options": "i"}},
                    {"caption": {"$regex": "Example", "$options": "i"}},
                ]},
            ],
        })
        cursor.sort.assert_called_once_with("_id", -1)
        cursor.limit.assert_called_once_with(20)

    def test_media_directory_filters_photos_and_escapes_search(self):
        self.videos.find.return_value.sort.return_value.skip.return_value.limit.return_value = []
        handler = self.authed_request("/admin/api/media", {"query": ".*", "kind": "photos", "pageSize": 100})
        self.assertEqual(handler.status, 200)
        filters = self.videos.find.call_args.args[0]
        self.assertEqual(filters["$and"][0], {"type": "photo_only"})
        self.assertEqual(filters["$and"][1]["$or"][0]["_id"]["$regex"], r"\.\*")
        self.videos.find.return_value.sort.return_value.skip.return_value.limit.assert_called_once_with(50)

    def test_media_directory_rejects_invalid_kind(self):
        handler = self.authed_request("/admin/api/media", {"kind": "delete"})
        self.assertEqual(handler.status, 400)
        self.videos.find.assert_not_called()

    def test_media_directory_database_failure_returns_service_unavailable(self):
        self.videos.find.side_effect = RuntimeError("database unavailable")
        handler = self.authed_request("/admin/api/media", {})
        self.assertEqual(handler.status, 503)
        self.assertEqual(json.loads(handler.response_body), {"error": "media_unavailable"})

    def test_settings_endpoint_returns_only_safe_configuration_status(self):
        documents = {
            "required_channel": {"_id": "required_channel", "chat_id": "@example", "link": "https://t.me/example", "title": "Example channel"},
            "admin_group": {"_id": "admin_group", "chat_id": -100123},
            "private_admin_group": {"_id": "private_admin_group", "chat_id": -100456},
            "broadcast_new_video": {"_id": "broadcast_new_video", "enabled": False},
            "accepted_users": {"_id": "accepted_users", "ids": [10, 20, 30]},
        }
        self.settings.find_one.side_effect = lambda query, projection=None: documents.get(query["_id"])
        handler = self.authed_request("/admin/api/settings", {})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertEqual(payload, {
            "channel_gate": {"enabled": True, "title": "Example channel"},
            "public_media_group_configured": True,
            "private_media_group_configured": True,
            "auto_broadcast_new_video": False,
            "private_access_users": 3,
        })
        self.assertNotIn("@example", handler.response_body.decode())
        self.assertNotIn("-100123", handler.response_body.decode())
        self.assertNotIn('"ids"', handler.response_body.decode())

    def test_settings_endpoint_defaults_auto_broadcast_to_enabled(self):
        self.settings.find_one.return_value = None
        handler = self.authed_request("/admin/api/settings", {})
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertTrue(payload["auto_broadcast_new_video"])
        self.assertFalse(payload["channel_gate"]["enabled"])
        self.assertEqual(payload["private_access_users"], 0)

    def test_settings_endpoint_database_failure_returns_service_unavailable(self):
        self.settings.find_one.side_effect = RuntimeError("database unavailable")
        handler = self.authed_request("/admin/api/settings", {})
        self.assertEqual(handler.status, 503)
        self.assertEqual(json.loads(handler.response_body), {"error": "settings_unavailable"})

    def test_metrics_database_failure_returns_service_unavailable(self):
        self.users.count_documents.side_effect = RuntimeError("database unavailable")
        handler = self.authed_request("/admin/api/overview", {})
        self.assertEqual(handler.status, 503)
        self.assertEqual(json.loads(handler.response_body), {"error": "metrics_unavailable"})
        self.videos.count_documents.assert_not_called()

    def test_oversized_api_body_is_rejected_before_reading_or_database_access(self):
        handler = FakeHandler(
            "/admin/api/overview",
            command="POST",
            headers={"Content-Length": str(admin_dashboard.MAX_API_BODY + 1)},
        )
        admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertEqual(handler.status, 413)
        self.users.count_documents.assert_not_called()
        self.videos.count_documents.assert_not_called()

    def test_assets_are_public_but_do_not_expose_api_data(self):
        handler = FakeHandler("/admin/app.js")
        admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertEqual(handler.status, 200)
        self.assertIn(b"Telegram.WebApp", handler.response_body)
        self.users.count_documents.assert_not_called()


if __name__ == "__main__":
    unittest.main()
