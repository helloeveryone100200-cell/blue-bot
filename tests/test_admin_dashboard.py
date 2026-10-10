"""Security contract tests for the read-only admin dashboard."""
import io
import json
import os
import unittest
from unittest.mock import Mock, patch

import admin_dashboard




class FakeHandler:
    def __init__(self, path="/admin", command="GET", headers=None, body=b"", client_ip="127.0.0.1"):
        self.path = path
        self.command = command
        self.headers = headers or {}
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.client_address = (client_ip, 12345)
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


class SessionTokenTests(unittest.TestCase):
    def setUp(self):
        self.secret = b"x" * 40

    def test_valid_session_token(self):
        token = admin_dashboard._make_session_token(self.secret, timestamp=1000)
        self.assertTrue(admin_dashboard._verify_session_token(token, self.secret, now=1000))

    def test_sessions_created_at_same_time_are_unique(self):
        first = admin_dashboard._make_session_token(self.secret, timestamp=1000)
        second = admin_dashboard._make_session_token(self.secret, timestamp=1000)
        self.assertNotEqual(first, second)
        self.assertTrue(admin_dashboard._verify_session_token(first, self.secret, now=1000))
        self.assertTrue(admin_dashboard._verify_session_token(second, self.secret, now=1000))

    def test_tampered_session_token_is_rejected(self):
        token = admin_dashboard._make_session_token(self.secret, timestamp=1000)
        replacement = "0" if token[-1] != "0" else "1"
        self.assertFalse(admin_dashboard._verify_session_token(token[:-1] + replacement, self.secret, now=1000))

    def test_expired_session_token_is_rejected(self):
        token = admin_dashboard._make_session_token(self.secret, timestamp=1000)
        self.assertFalse(admin_dashboard._verify_session_token(token, self.secret, now=1000 + admin_dashboard.SESSION_TTL_SECONDS + 1))

    def test_malformed_non_ascii_token_is_rejected(self):
        self.assertFalse(admin_dashboard._verify_session_token("١.bad." + "f" * 64, self.secret, now=1000))

    def test_future_session_token_is_rejected(self):
        token = admin_dashboard._make_session_token(self.secret, timestamp=2000)
        self.assertFalse(admin_dashboard._verify_session_token(token, self.secret, now=1000))

    def test_credentials_below_minimum_disable_dashboard(self):
        with patch.dict(os.environ, {"ADMIN_DASHBOARD_PASSWORD": "abcde", "ADMIN_SESSION_SECRET": "12345"}, clear=False):
            self.assertIsNone(admin_dashboard._configuration())

    def test_credentials_above_maximum_disable_dashboard(self):
        with patch.dict(os.environ, {"ADMIN_DASHBOARD_PASSWORD": "p" * 17, "ADMIN_SESSION_SECRET": "s" * 21}, clear=False):
            self.assertIsNone(admin_dashboard._configuration())

    def test_requested_credential_lengths_enable_dashboard(self):
        with patch.dict(os.environ, {"ADMIN_DASHBOARD_PASSWORD": "pass123", "ADMIN_SESSION_SECRET": "abc123"}, clear=False):
            config = admin_dashboard._configuration()
            self.assertIsNotNone(config)
            self.assertEqual(config[0], "pass123")

    def test_maximum_credential_lengths_enable_dashboard(self):
        with patch.dict(os.environ, {"ADMIN_DASHBOARD_PASSWORD": "p" * 16, "ADMIN_SESSION_SECRET": "s" * 20}, clear=False):
            config = admin_dashboard._configuration()
            self.assertIsNotNone(config)
            self.assertEqual(config[0], "p" * 16)


class AdminRouteAuthorizationTests(unittest.TestCase):
    def setUp(self):
        self.users = Mock()
        self.videos = Mock()
        self.settings = Mock()
        self.users.count_documents.return_value = 12
        self.videos.count_documents.side_effect = lambda query: 5 if query == {} else 2

    def test_dashboard_fails_closed_without_credentials(self):
        handler = FakeHandler("/admin")
        with patch.dict(os.environ, {"ADMIN_DASHBOARD_PASSWORD": "", "ADMIN_SESSION_SECRET": ""}, clear=False):
            handled = admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertTrue(handled)
        self.assertEqual(handler.status, 503)
        self.users.count_documents.assert_not_called()

    def test_anonymous_overview_request_is_denied(self):
        handler = FakeHandler("/admin/api/overview")
        with patch.dict(os.environ, {"ADMIN_DASHBOARD_PASSWORD": "pass123", "ADMIN_SESSION_SECRET": "secret123"}, clear=False):
            handled = admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertTrue(handled)
        self.assertEqual(handler.status, 401)
        self.assertEqual(json.loads(handler.response_body), {"error": "authentication_required"})
        self.users.count_documents.assert_not_called()
        self.videos.count_documents.assert_not_called()

    def test_authenticated_overview_returns_only_aggregate_allowlisted_fields(self):
        secret = "secret123"
        token = admin_dashboard._make_session_token(secret.encode("utf-8"))
        handler = FakeHandler(
            "/admin/api/overview",
            headers={"Cookie": f"{admin_dashboard.COOKIE_NAME}={token}"},
        )
        with patch.dict(os.environ, {"ADMIN_DASHBOARD_PASSWORD": "pass123", "ADMIN_SESSION_SECRET": secret}, clear=False):
            handled = admin_dashboard.handle_admin_request(handler, self.users, self.videos, self.settings)
        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        payload = json.loads(handler.response_body)
        self.assertEqual(set(payload), {"users", "media", "videos", "photos", "requests_today", "status"})
        self.assertEqual(payload["users"], 12)
        self.assertEqual(payload["media"], 5)
        self.assertEqual(payload["videos"], 3)
        self.assertEqual(payload["photos"], 2)
        self.assertIsNone(payload["requests_today"])
        self.assertEqual(payload["status"], "connected")

    def test_login_form_enforces_requested_password_length_in_browser(self):
        page = admin_dashboard._login_page().decode("utf-8")
        self.assertIn('minlength="6"', page)
        self.assertIn('maxlength="16"', page)


if __name__ == "__main__":
    unittest.main()
