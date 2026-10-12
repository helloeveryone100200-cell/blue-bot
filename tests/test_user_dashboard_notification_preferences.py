"""Regression checks for persisted notification preferences and delivery filters."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UserDashboardNotificationPreferenceTests(unittest.TestCase):
    def test_preferences_ui_exposes_three_accessible_categories(self):
        html = (ROOT / "user_app" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="notification-preferences-heading"',
            'id="pref-new-content"',
            'id="pref-referral-updates"',
            'id="pref-system-updates"',
            'id="notification-notice"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_preferences_api_authenticates_and_validates_updates(self):
        api = (ROOT / "admin_dashboard.py").read_text(encoding="utf-8")
        route = api[api.index('if path == "/app/api/notification-preferences":'):api.index('if path == "/app/api/background":')]
        self.assertIn("_read_user_payload(handler)", route)
        self.assertIn('type(payload.get("enabled")) is not bool', route)
        self.assertIn('"$set": {f"notification_preferences.{category}": payload["enabled"]}', route)
        self.assertIn('stored.get(key) is not False', route)

    def test_delivery_paths_respect_preferences_but_default_to_enabled(self):
        bot = (ROOT / "bot.py").read_text(encoding="utf-8")
        self.assertIn('return preferences.get(category) is not False', bot)
        self.assertIn('"notification_preferences.new_content": {"$ne": False}', bot)
        self.assertIn('"notification_preferences.system_updates": {"$ne": False}', bot)
        self.assertIn('user_notification_enabled(referrer, "referral_updates")', bot)
        self.assertIn('total = users.count_documents({"notification_preferences.system_updates": {"$ne": False}})', bot)


if __name__ == "__main__":
    unittest.main()
