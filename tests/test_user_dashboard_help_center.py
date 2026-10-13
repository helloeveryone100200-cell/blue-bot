"""Regression checks for the User Dashboard Help & Support Center."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UserDashboardHelpCenterTests(unittest.TestCase):
    def test_help_center_contains_faq_and_contact_owner_form(self):
        html = (ROOT / "user_app" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="help-center-heading"', html)
        self.assertIn('id="contact-owner-form"', html)
        self.assertIn('id="contact-category"', html)
        self.assertIn('id="contact-message"', html)
        self.assertIn('id="send-contact-message"', html)
        self.assertIn('id="contact-owner-notice"', html)
        self.assertIn("<details>", html)
        self.assertIn("<summary>How do I save a video for later?</summary>", html)
        self.assertIn("<summary>When does a referral count?</summary>", html)
        self.assertIn('aria-labelledby="help-center-heading"', html)
        self.assertIn('aria-live="polite"', html)

    def test_contact_owner_uses_authenticated_api_and_safe_dom_apis(self):
        js = (ROOT / "user_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("fetch('/app/api/contact-owner'", js)
        self.assertIn("body: JSON.stringify({initData: signedData, category, message})", js)
        self.assertIn("credentials: 'omit'", js)
        self.assertIn("Please wait a moment before sending another support request.", js)
        self.assertNotIn("innerHTML", js)


if __name__ == "__main__":
    unittest.main()
