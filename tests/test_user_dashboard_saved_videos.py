"""Regression checks for authenticated, per-user Saved Videos."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UserDashboardSavedVideosTests(unittest.TestCase):
    def test_saved_videos_ui_is_present_and_accessible(self):
        html = (ROOT / "user_app" / "index.html").read_text(encoding="utf-8")
        for marker in (
            'id="saved-videos-heading"',
            'id="saved-video-count"',
            'id="saved-video-notice"',
            'id="saved-video-grid"',
            'aria-live="polite"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, html)

    def test_saved_video_actions_use_authenticated_api_and_safe_dom_apis(self):
        js = (ROOT / "user_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("'/app/api/saved-videos'", js)
        self.assertIn("action: shouldSave ? 'save' : 'remove'", js)
        self.assertIn("renderVideos(items, 'saved-video-grid')", js)
        self.assertIn("document.createElement('button')", js)
        self.assertNotIn("innerHTML", js)

    def test_saved_video_api_requires_telegram_auth_and_limits_collection(self):
        api = (ROOT / "admin_dashboard.py").read_text(encoding="utf-8")
        route = api[api.index('if path == "/app/api/saved-videos":'):api.index('if path == "/app/api/background":')]
        self.assertIn("_read_user_payload(handler)", route)
        self.assertIn('user_doc.get("is_banned") is True', route)
        self.assertIn('re.fullmatch(r"v[0-9]{1,18}", media_id)', route)
        self.assertIn('len(saved_ids) >= 100', route)
        self.assertIn('$addToSet', route)
        self.assertIn('$pull', route)
        self.assertIn('"savedIds": valid_ids', route)


if __name__ == "__main__":
    unittest.main()
