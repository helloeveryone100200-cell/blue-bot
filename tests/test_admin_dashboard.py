"""Security contract tests for the read-only admin dashboard."""
import os
import unittest
from unittest.mock import patch

import admin_dashboard


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


if __name__ == "__main__":
    unittest.main()
