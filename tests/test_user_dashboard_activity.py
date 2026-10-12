"""Regression checks for truthful, account-scoped dashboard activity history."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UserDashboardActivityTests(unittest.TestCase):
    def test_activity_panel_is_present_and_accessible(self):
        html = (ROOT / "user_app" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="activity-heading"', html)
        self.assertIn('id="activity-list"', html)
        self.assertIn('id="activity-notice"', html)
        self.assertIn('id="clear-activity"', html)
        self.assertIn('aria-live="polite"', html)

    def test_activity_is_scoped_to_verified_user_and_bounded_locally(self):
        js = (ROOT / "user_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("activityUserId = typeof profile.id === 'string'", js)
        self.assertIn("'bluebot.activity.v1.' + activityUserId", js)
        self.assertIn("slice(0, 20)", js)
        self.assertIn("localStorage.setItem", js)
        self.assertIn("localStorage.removeItem", js)
        self.assertIn("textContent = entry.label", js)
        self.assertNotIn("innerHTML", js)

    def test_only_observed_dashboard_actions_are_recorded(self):
        js = (ROOT / "user_app" / "app.js").read_text(encoding="utf-8")
        for event in (
            "Dashboard opened",
            "Dashboard refreshed",
            "Opened video ",
            "Saved video ",
            "Removed saved video ",
            "Searched public video library",
            "Copied personal referral link",
            "Shared personal referral link",
            "Opened support chat",
        ):
            with self.subTest(event=event):
                self.assertIn(event, js)
        self.assertIn("It is not a complete record of activity in the bot.", (ROOT / "user_app" / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
