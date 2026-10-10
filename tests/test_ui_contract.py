"""Static regression guards for presentation-only changes.

These tests intentionally parse bot.py instead of importing it, because importing
the bot initializes environment-dependent Telegram and MongoDB clients.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_PATH = ROOT / "bot.py"
SOURCE = BOT_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE, filename=str(BOT_PATH))


def find_function(name):
    for node in TREE.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Required function not found: {name}")


def call_names(node):
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


class WelcomeUiContractTests(unittest.TestCase):
    def test_welcome_function_signature_is_preserved(self):
        fn = find_function("send_welcome")
        self.assertEqual([arg.arg for arg in fn.args.args], ["chat_id", "user_id"])

    def test_welcome_keeps_dynamic_video_count_and_keyboard(self):
        fn = find_function("send_welcome")
        names = call_names(fn)
        self.assertIn("get_total_videos", names)
        self.assertIn("welcome_markup", names)
        self.assertIn("send_message", names)

    def test_welcome_keeps_html_parse_mode(self):
        fn = find_function("send_welcome")
        send_calls = [
            node for node in ast.walk(fn)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_message"
        ]
        self.assertEqual(len(send_calls), 1)
        parse_modes = {
            keyword.value.value
            for call in send_calls
            for keyword in call.keywords
            if keyword.arg == "parse_mode"
            and isinstance(keyword.value, ast.Constant)
        }
        self.assertIn("HTML", parse_modes)

    def test_critical_existing_flows_remain_declared(self):
        required_functions = (
            "is_user_channel_joined",
            "resume_pending_channel_action",
            "owner_panel_keyboard",
            "welcome_markup",
        )
        for name in required_functions:
            with self.subTest(function=name):
                find_function(name)

    def test_existing_callback_identifiers_remain_in_source(self):
        for callback in (
            "view_profile",
            "channel_not_configured",
            "gender_male",
            "gender_female",
            "noop",
        ):
            with self.subTest(callback=callback):
                self.assertIn(callback, SOURCE)



class DashboardPrototypeTests(unittest.TestCase):
    def setUp(self):
        self.html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        self.css = (ROOT / "admin" / "styles.css").read_text(encoding="utf-8")
        self.js = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")

    def test_dashboard_is_explicitly_marked_as_preview(self):
        self.assertIn("Limited live integration", self.html)
        self.assertIn("Charts remain illustrative", self.html)
        self.assertIn('href="/admin/styles.css"', self.html)
        self.assertIn('src="/admin/app.js"', self.html)

    def test_dashboard_uses_premium_dark_design_tokens(self):
        self.assertIn("--bg:#080d1a", self.css)
        self.assertIn("--indigo:#7775ff", self.css)
        self.assertIn("@media(max-width:600px)", self.css)
        self.assertIn("prefers-reduced-motion", self.css)

    def test_dashboard_uses_only_authenticated_same_origin_read_only_api(self):
        self.assertNotIn("XMLHttpRequest", self.js)
        self.assertNotIn("WebSocket", self.js)
        self.assertIn("fetch('/admin/api/overview'", self.js)
        self.assertIn("credentials: 'same-origin'", self.js)
        self.assertIn("cache: 'no-store'", self.js)
        self.assertIn("requests_today == null", self.js)

if __name__ == "__main__":
    unittest.main()
