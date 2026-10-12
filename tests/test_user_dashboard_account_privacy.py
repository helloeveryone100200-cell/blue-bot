"""Regression checks for Account & Privacy transparency UI."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UserDashboardAccountPrivacyTests(unittest.TestCase):
    def test_account_privacy_panel_exposes_actual_account_status_fields(self):
        html = (ROOT / "user_app" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="account-privacy-heading"',
            'id="privacy-account-status"',
            'id="privacy-private-access"',
            'id="privacy-telegram-id"',
            'id="privacy-saved-count"',
            'id="privacy-notification-summary"',
            'href="#notification-preferences-heading"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_privacy_summary_uses_profile_and_loaded_feature_data(self):
        js = (ROOT / "user_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("byId('privacy-account-status').textContent = profile.is_banned ? 'Restricted' : 'Active'", js)
        self.assertIn("byId('privacy-private-access').textContent = profile.private_access ? 'Granted' : 'Standard'", js)
        self.assertIn("byId('privacy-saved-count').textContent = safeCount(items.length)", js)
        self.assertIn("enabledCount + ' of 3 enabled'", js)
        self.assertNotIn("innerHTML", js)


if __name__ == "__main__":
    unittest.main()
