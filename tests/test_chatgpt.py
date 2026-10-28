import importlib.util
import io
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from web import openai_auth

ROOT = Path(__file__).resolve().parents[1]


def load_bbs_module():
    spec = importlib.util.spec_from_file_location("chatgpt_bbs", ROOT / "scripts/chatgpt-bbs.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AuthorizationTests(unittest.TestCase):
    def test_start_authorization_uses_dynamic_client_pkce_and_plan_scopes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with mock.patch.multiple(
                openai_auth,
                AUTH_ROOT=root,
                HOST_FILE=root / "host.json",
                PENDING_FILE=root / "pending.json",
                CREDENTIALS_FILE=root / "credentials.json",
            ):
                url = openai_auth.start_authorization()
                query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
                self.assertEqual(query["client_id"], ["dynamic_agent_client"])
                self.assertEqual(query["redirect_uri"], [openai_auth.REDIRECT_URI])
                self.assertIn("chatgpt.tokens.use.direct", query["scope"][0])
                self.assertEqual(query["code_challenge_method"], ["S256"])
                pending = json.loads((root / "pending.json").read_text())
                self.assertEqual(query["state"], [pending["state"]])
                self.assertEqual((root / "pending.json").stat().st_mode & 0o777, 0o600)

    def test_complete_rejects_callback_with_wrong_state_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pending = root / "pending.json"
            pending.write_text(json.dumps({
                "state": "right", "created_at": 9999999999, "client_id": "dynamic_agent_client",
                "nonce": "nonce", "code_verifier": "verifier", "redirect_uri": openai_auth.REDIRECT_URI,
            }))
            with mock.patch.multiple(openai_auth, PENDING_FILE=pending, CREDENTIALS_FILE=root / "credentials.json"):
                with mock.patch.object(openai_auth, "_request_json") as request:
                    with self.assertRaises(openai_auth.AuthError):
                        openai_auth.complete_authorization("http://127.0.0.1:1455/auth/callback?state=wrong&code=x")
                    request.assert_not_called()

    def test_complete_saves_only_validated_plan_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pending = root / "pending.json"
            pending.write_text(json.dumps({
                "state": "right", "created_at": 9999999999, "client_id": "dynamic_agent_client",
                "nonce": "nonce", "code_verifier": "verifier", "redirect_uri": openai_auth.REDIRECT_URI,
            }))
            token_response = {
                "access_token": "access", "refresh_token": "refresh", "id_token": "identity",
                "expires_in": 3600, "scope": openai_auth.SCOPES,
            }
            with mock.patch.multiple(
                openai_auth,
                AUTH_ROOT=root,
                HOST_FILE=root / "host.json",
                PENDING_FILE=pending,
                CREDENTIALS_FILE=root / "credentials.json",
            ), mock.patch.object(openai_auth, "_request_json", return_value=token_response), \
                 mock.patch.object(openai_auth, "_validate_id_token", return_value={
                     "iss": "https://auth.openai.com", "sub": "subject", "email": "retro@example.com",
                 }):
                result = openai_auth.complete_authorization(
                    "http://127.0.0.1:1455/auth/callback?state=right&code=once&client_id=oaiapp_test"
                )
                self.assertEqual(result["email"], "retro@example.com")
                self.assertEqual(result["client_id"], "oaiapp_test")
                self.assertEqual((root / "credentials.json").stat().st_mode & 0o777, 0o600)
                self.assertFalse(pending.exists())


class BBSTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bbs = load_bbs_module()

    def test_terminal_text_wraps_and_uses_crlf(self):
        rendered = self.bbs.terminal_text("woord " * 30)
        self.assertIn(b"\r\n", rendered)
        self.assertTrue(all(len(line) <= 76 for line in rendered.split(b"\r\n") if line))

    def test_line_reader_keeps_working_after_cr_only_lines(self):
        class Reader:
            def __init__(self):
                self.rfile = io.BytesIO(b"eerste\rtweede\r")
                self.wfile = io.BytesIO()

        reader = Reader()
        self.assertEqual(self.bbs.ChatHandler.read_line(reader), b"eerste")
        self.assertEqual(self.bbs.ChatHandler.read_line(reader), b"tweede")

    def test_line_reader_distinguishes_blank_line_from_disconnect(self):
        class Reader:
            def __init__(self):
                self.rfile = io.BytesIO(b"\r")
                self.wfile = io.BytesIO()

        reader = Reader()
        self.assertEqual(self.bbs.ChatHandler.read_line(reader), b"")
        self.assertIsNone(self.bbs.ChatHandler.read_line(reader))

    def test_chat_starts_with_ansi_clear_screen(self):
        source = (ROOT / "scripts/chatgpt-bbs.py").read_bytes()
        self.assertIn(b'b"\\x1b[2J\\x1b[H"', source)

    def test_blank_input_redraws_prompt_in_place(self):
        source = (ROOT / "scripts/chatgpt-bbs.py").read_bytes()
        self.assertIn(b'b"\\x1b[1A\\x1b[2K\\r"', source)

    def test_model_selection_prefers_configured_available_model(self):
        models = [{"slug": "one", "display_name": "One"}, {"slug": "two", "display_name": "Two"}]
        with mock.patch.object(self.bbs.openai_auth, "available_models", return_value=models), \
             mock.patch.dict(self.bbs.os.environ, {"RETROMODEM_CHATGPT_MODEL": "two"}):
            self.assertEqual(self.bbs.choose_model(), "two")

    def test_continue_mode_defaults_to_new_conversation(self):
        self.assertFalse(self.bbs.CONTINUE_BETWEEN_CALLS)
        self.assertEqual(self.bbs.ChatServer.shared_history, [])

    def test_network_agent_defaults_off_and_classifies_ssh_changes(self):
        self.assertFalse(self.bbs.ALLOW_NETWORK_AGENT)
        self.assertTrue(self.bbs.ssh_is_read_only("systemctl status ssh"))
        self.assertTrue(self.bbs.ssh_is_read_only("cat /etc/os-release"))
        self.assertFalse(self.bbs.ssh_is_read_only("systemctl restart ssh"))
        self.assertFalse(self.bbs.ssh_is_read_only("rm -rf /tmp/test"))

    def test_mutating_http_requires_confirmation(self):
        arguments = {"operation": "http", "target": "device.local", "port": 80,
                     "url": "http://device.local/api", "method": "POST",
                     "body": "{}", "username": "", "command": ""}
        result = self.bbs.perform_network_action(arguments, lambda description: False)
        self.assertEqual(result, "Geweigerd door gebruiker.")

    def test_local_network_info_is_read_only_and_needs_no_confirmation(self):
        arguments = {"operation": "local_network", "target": "", "port": 1,
                     "url": "", "method": "GET", "body": "", "username": "", "command": ""}
        with mock.patch.object(self.bbs, "_run", side_effect=["addresses", "routes"]):
            result = self.bbs.perform_network_action(
                arguments, lambda description: self.fail("read-only info asked for confirmation"))
        self.assertIn("hostname=", result)
        self.assertIn("addresses", result)
        self.assertIn("routes", result)


class WiringTests(unittest.TestCase):
    def test_reserved_number_and_service_are_installed(self):
        phonebook = json.loads((ROOT / "config/phonebook.json").read_text())
        entry = next(item for item in phonebook["entries"] if item["number"] == "5559999")
        self.assertEqual((entry["host"], entry["port"]), ("127.0.0.1", 2324))
        self.assertEqual(entry["kind"], "chatgpt")
        installer = (ROOT / "install.sh").read_text()
        self.assertIn("retromodem-chatgpt.service", installer)
        self.assertIn("python3-cryptography", installer)


if __name__ == "__main__":
    unittest.main()
