"""Static regression guards for the Mini App and presentation-only changes."""
import ast
import os
import unittest
from urllib.parse import urlparse
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


def load_url_resolver(configured_url=""):
    fn = find_function("resolve_admin_webapp_url")
    module = ast.Module(body=[fn], type_ignores=[])
    namespace = {"os": os, "urlparse": urlparse, "ADMIN_WEBAPP_URL": configured_url}
    exec(compile(module, "<admin-url-resolver>", "exec"), namespace)
    return namespace["resolve_admin_webapp_url"]


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
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "send_message"
        ]
        self.assertEqual(len(send_calls), 1)
        parse_modes = {
            keyword.value.value for call in send_calls for keyword in call.keywords
            if keyword.arg == "parse_mode" and isinstance(keyword.value, ast.Constant)
        }
        self.assertIn("HTML", parse_modes)

    def test_critical_existing_flows_remain_declared(self):
        for name in ("is_user_channel_joined", "resume_pending_channel_action", "owner_panel_keyboard", "welcome_markup"):
            with self.subTest(function=name):
                find_function(name)

    def test_telegram_mini_app_menu_button_is_owner_scoped(self):
        fn = find_function("configure_telegram_menu_buttons")
        source = ast.get_source_segment(SOURCE, fn)
        self.assertIn("MenuButtonCommands", source)
        self.assertIn("MenuButtonWebApp", source)
        self.assertIn("OWNER_IDS", source)
        self.assertIn("ADMIN_WEBAPP_URL", source)
        self.assertIn("startswith(\"https://\")", source)
        self.assertIn("chat_id=owner_id", source)

    def test_start_welcome_exposes_mini_app_only_to_owners(self):
        fn = find_function("welcome_markup")
        source = ast.get_source_segment(SOURCE, fn)
        self.assertIn("user_id in OWNER_IDS", source)
        self.assertIn("resolve_admin_webapp_url", source)
        self.assertIn("WebAppInfo", source)
        self.assertIn("Admin Panel", source)

    def test_mini_app_url_resolver_requires_https_and_normalizes_webhook_path(self):
        fn = find_function("resolve_admin_webapp_url")
        source = ast.get_source_segment(SOURCE, fn)
        self.assertIn('startswith("https://")', source)
        self.assertIn('path.endswith("/webhook")', source)
        self.assertIn('"/admin/"', source)

        resolve_url = load_url_resolver()
        self.assertEqual(resolve_url("https://blue-bot.example"), "https://blue-bot.example/admin/")
        self.assertEqual(resolve_url("https://blue-bot.example/webhook"), "https://blue-bot.example/admin/")
        self.assertEqual(resolve_url("http://blue-bot.example"), "")

    def test_explicit_admin_url_is_normalized_and_non_https_is_rejected(self):
        self.assertEqual(
            load_url_resolver("https://blue-bot.example/admin")(),
            "https://blue-bot.example/admin/",
        )
        self.assertEqual(load_url_resolver("http://blue-bot.example/admin")(), "")

    def test_existing_callback_identifiers_remain_in_source(self):
        for callback in ("view_profile", "channel_not_configured", "gender_male", "gender_female", "noop"):
            with self.subTest(callback=callback):
                self.assertIn(callback, SOURCE)


class MiniAppUiContractTests(unittest.TestCase):
    def test_mini_app_loads_telegram_sdk_and_no_browser_login(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn("telegram.org/js/telegram-web-app.js", html)
        self.assertIn("TELEGRAM MINI APP", html)
        self.assertNotIn("Sign in securely", html)
        self.assertNotIn("/admin/logout", html)
        self.assertIn("browser-blocked", html)
        js = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        css = (ROOT / "admin" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("telegram-ready", js)
        self.assertIn("body.telegram-ready .app-shell{display:block}", css)

    def test_mini_app_authenticates_api_with_telegram_init_data(self):
        js = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        self.assertIn("webApp.initData", js)
        self.assertIn("method: 'POST'", js)
        self.assertIn("credentials: 'omit'", js)
        self.assertNotIn("bluebot_admin_session", js)

    def test_no_fabricated_metrics_or_activity_are_rendered(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="metric-users">—', html)
        self.assertIn('id="metric-media">—', html)
        self.assertNotIn("12,846", html)
        self.assertNotIn("Illustrative analytics", html)
        self.assertNotIn("user_10482", html)

    def test_user_directory_is_read_only_and_uses_authenticated_api(self):
        html = (ROOT / "admin" / "index.html").read_text(encoding="utf-8")
        js = (ROOT / "admin" / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="user-management-view"', html)
        self.assertIn('id="user-search"', html)
        self.assertIn("read-only", html)
        self.assertIn("/admin/api/users", js)
        self.assertIn("credentials: 'omit'", js)
        self.assertIn("textContent", js)
        self.assertNotIn("innerHTML", js)
        self.assertIn("usersPages", js)

    def test_mini_app_uses_premium_dark_mobile_tokens(self):
        css = (ROOT / "admin" / "styles.css").read_text(encoding="utf-8")
        self.assertIn("--bg:#080d1a", css)
        self.assertIn("--indigo:#7775ff", css)
        self.assertIn("env(safe-area-inset-bottom)", css)
        self.assertIn("@media(min-width:520px)", css)


if __name__ == "__main__":
    unittest.main()
