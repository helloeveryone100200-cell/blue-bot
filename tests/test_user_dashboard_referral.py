"""Regression checks for the User Dashboard Referral Center."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UserDashboardReferralTests(unittest.TestCase):
    def test_referral_center_controls_are_present_and_accessible(self):
        html = (ROOT / "user_app" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="referral-heading"',
            'id="referral-success-count"',
            'id="referral-link"',
            'id="copy-referral-link"',
            'id="share-referral-link"',
            'id="referral-notice"',
            'aria-live="polite"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_referral_center_uses_verified_profile_data_and_existing_bot_link(self):
        js = (ROOT / "user_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("byId('referral-success-count').textContent = safeCount(profile.shares)", js)
        self.assertIn("byId('referral-link').value = botUrl", js)
        self.assertIn("navigator.clipboard.writeText(botUrl)", js)
        self.assertIn("encodeURIComponent(botUrl)", js)
        self.assertNotIn("innerHTML", js)

    def test_profile_api_already_returns_referral_count_and_personal_link(self):
        api = (ROOT / "admin_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('"shares": shares', api)
        self.assertIn('"bot_url": bot_url', api)
        self.assertIn('f"https://t.me/{user_bot_username}?start={user_id}"', api)


if __name__ == "__main__":
    unittest.main()
