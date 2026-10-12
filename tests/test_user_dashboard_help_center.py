"""Regression checks for the User Dashboard Help & Support Center."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UserDashboardHelpCenterTests(unittest.TestCase):
    def test_help_center_contains_faq_and_support_action(self):
        html = (ROOT / "user_app" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="help-center-heading"', html)
        self.assertIn('id="open-support"', html)
        self.assertIn("<details>", html)
        self.assertIn("<summary>How do I save a video for later?</summary>", html)
        self.assertIn("<summary>When does a referral count?</summary>", html)
        self.assertIn('aria-labelledby="help-center-heading"', html)

    def test_support_button_uses_verified_bot_link_without_referral_parameter(self):
        js = (ROOT / "user_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("byId('open-support').disabled = !botUrl", js)
        self.assertIn("const supportUrl = new URL(botUrl)", js)
        self.assertIn("supportUrl.search = ''", js)
        self.assertIn("openTelegramLink(supportUrl.toString())", js)
        self.assertNotIn("innerHTML", js)


if __name__ == "__main__":
    unittest.main()
