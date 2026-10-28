import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from web import web


class ConfigTests(unittest.TestCase):
    def test_connection_mode_labels_keep_existing_two_backends(self):
        source = Path(web.__file__).read_text()
        self.assertIn("Direct internet (PPP)", source)
        self.assertIn("Inbelmodem (Dial-Up) en BBS", source)
        self.assertIn('<option value="ppp"', source)
        self.assertIn('<option value="dialup"', source)
        self.assertNotIn('<option value="bbs"', source)

    def test_combined_budget_and_translated_settings(self):
        dutch = web.proxy_settings_card("nl", {})
        english = web.proxy_settings_card("en", {})
        self.assertNotIn('name="image_pixels"', dutch)
        self.assertIn("Geschatte paginagrootte per deel", dutch)
        self.assertIn("byte per weergegeven pixel", dutch)
        self.assertIn("Afbeeldingen: Afbeeldingen laten zien | Als links", dutch)
        self.assertNotIn("Images: Inline", dutch)
        self.assertIn("Estimated page size per part", english)
        self.assertIn("inclusief uitgepakte afbeeldingen", dutch)
        self.assertIn('value="2000000"', dutch)

    def test_config_round_trip_preserves_spaces_and_shell_characters(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "retromodem.env"
            with mock.patch.object(web, "CONFIG", config), mock.patch.dict(os.environ, {}, clear=True):
                web.save_config({
                    "RETROMODEM_AP_SSID": "Retro netwerk",
                    "RETROMODEM_AP_PASSWORD": "test!123",
                })
                self.assertEqual(web.load_config()["RETROMODEM_AP_SSID"], "Retro netwerk")
                self.assertEqual(web.load_config()["RETROMODEM_AP_PASSWORD"], "test!123")

    def test_environment_is_only_a_default_for_file_values(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "retromodem.env"
            config.write_text("RETROMODEM_BITRATE=9600\n", encoding="utf-8")
            with mock.patch.object(web, "CONFIG", config), mock.patch.dict(
                os.environ, {"RETROMODEM_BITRATE": "57600"}, clear=True
            ):
                self.assertEqual(web.load_config()["RETROMODEM_BITRATE"], "9600")


class WifiTests(unittest.TestCase):
    def test_scan_deduplicates_and_orders_by_signal(self):
        output = "Weak:20:WPA2\nStrong:90:WPA2\nWeak:45:WPA2\nCafe\\:retro:60:--\n"
        completed = subprocess.CompletedProcess([], 0, output, "")
        with mock.patch.object(web, "run", return_value=completed):
            self.assertEqual(
                web.scan_wifi({"RETROMODEM_WIFI_INTERFACE": "wlan0"}),
                [("Strong", 90, "WPA2"), ("Cafe:retro", 60, "--"), ("Weak", 45, "WPA2")],
            )


class PhonebookTests(unittest.TestCase):
    def test_phonebook_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            phonebook = Path(directory) / "phonebook.json"
            entries = [{"number": "5551000", "label": "Test", "kind": "bbs", "host": "bbs.example.org", "port": 23}]
            with mock.patch.object(web, "PHONEBOOK", phonebook):
                web.save_phonebook(entries)
                self.assertEqual(web.load_phonebook(), entries)

    def test_phonebook_entry_validates_and_converts_port(self):
        entry = web.phonebook_entry({
            "number": "5551008", "label": "300 baud", "kind": "bbs",
            "host": "300baud.dynu.net", "port": "2525",
        })
        self.assertEqual(entry["port"], 2525)

    def test_phonebook_entry_rejects_shell_style_host(self):
        with self.assertRaises(ValueError):
            web.phonebook_entry({
                "number": "5551010", "label": "Bad", "kind": "bbs",
                "host": "example.org;reboot", "port": "23",
            })

    def test_phonebook_page_has_separate_system_and_bbs_sections(self):
        entries = [
            {"number": "5559000", "label": "Internet", "kind": "ppp", "host": "127.0.0.1", "port": 2323},
            {"number": "5551000", "label": "Test BBS", "kind": "bbs", "host": "bbs.example.org", "port": 23},
            {"number": "5559999", "label": "ChatGPT", "kind": "chatgpt", "host": "127.0.0.1", "port": 2324},
        ]
        with mock.patch.object(web, "load_phonebook", return_value=entries), \
             mock.patch.object(web.openai_auth, "connection_status", return_value={"connected": True}):
            rendered = web.phonebook_page("nl")
        self.assertIn("5559000", rendered)
        self.assertIn("5551000", rendered)
        self.assertIn("5559999", rendered)
        self.assertIn('/settings#chatgpt', rendered)
        self.assertIn('<code>user</code>', rendered)
        self.assertIn('Leeg laten', rendered)
        self.assertNotIn('Vaste PPP-internetverbinding', rendered)
        self.assertNotIn('Fixed PPP internet connection', rendered)
        self.assertEqual(rendered.count('action="/phonebook/update"'), 1)


class InterfaceStructureTests(unittest.TestCase):
    def test_psion_guide_contains_complete_ppp_and_bbs_setup(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn("Mobile Connectivity Update 3.10", source)
        self.assertIn("Terminal detect en Carrier detect uit", source)
        self.assertIn("Configuratiescherm → Bellen", source)
        self.assertNotIn("Configuratiescherm → Locatie", source)
        self.assertIn("ANSI/ANSI-BBS", source)
        self.assertIn("http://10.42.0.1", source)
        self.assertIn('/static/guides/psion/setup-remote-link.gif', source)
        self.assertIn('/static/guides/psion/setup-internet-service.gif', source)

    def test_psion_guide_images_are_bundled(self):
        static = Path(web.__file__).parent / "static" / "guides" / "psion"
        for name in (
            "setup-remote-link.gif",
            "setup-internet-service.gif",
            "hermes-settings.jpg",
            "pi-login.jpg",
        ):
            self.assertTrue((static / name).is_file(), name)

    def test_phonebook_has_its_own_navigation_tab(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn('(\"/phonebook\", tr(language, \"Telefoonboek\"', source)
        self.assertIn('elif path == "/phonebook"', source)

    def test_windows_xp_ir_dialup_is_marked_tested(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn("'winxp':[['verified'", source)
        self.assertIn('Fysiek getest met Windows XP', source)

    def test_daily_button_help_is_visible_on_status(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn("Knop op het apparaat", source)
        self.assertIn("Laat los wanneer beide leds knipperen", source)

    def test_library_management_is_part_of_settings(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn("def library_upload_form", source)
        self.assertIn("{library_upload_form(language)}", source)

    def test_chatgpt_conversation_mode_toggle_is_in_settings(self):
        disconnected = {"connected": False, "email": "", "scopes": []}
        with mock.patch.object(web.openai_auth, "connection_status", return_value=disconnected):
            rendered = web.chatgpt_settings_card("nl", {"RETROMODEM_CHATGPT_CONTINUE": "1", "RETROMODEM_CHATGPT_AGENT": "1"})
        self.assertIn('action="/settings/chatgpt"', rendered)
        self.assertIn('name="continue_conversation"', rendered)
        self.assertIn('name="allow_agent"', rendered)
        self.assertIn('Netwerkagent toestaan', rendered)
        self.assertIn('checked', rendered)

    def test_retroweb_proxy_toggle_is_in_settings(self):
        rendered = web.proxy_settings_card("nl", {"RETROMODEM_PROXY_MODE": "manual"})
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn('action="/settings/proxy"', rendered)
        self.assertIn('name="mode"', rendered)
        self.assertNotIn('value="off"', rendered)
        self.assertIn('value="transparent"', rendered)
        self.assertIn('value="manual" selected', rendered)
        self.assertIn('Uitzonderingen', rendered)
        self.assertIn('retroweb.bjrno.com', rendered)
        self.assertIn('RetroWEB', rendered)
        self.assertIn('name="image_start"', rendered)
        self.assertNotIn('name="preview_kb"', rendered)
        self.assertIn('name="exceptions"', rendered)
        self.assertIn('name="image_width"', rendered)
        self.assertIn('name="image_height"', rendered)
        self.assertIn('Psion 5mx (640×240)', rendered)
        self.assertIn('Palm classic (160×160)', rendered)
        self.assertIn('path == "/settings/proxy"', source)

    def test_epoc_receive_is_offered_as_experimental(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        receive = source.split('data-protocol="receive"', 1)[1].split('</select>', 1)[0]
        self.assertIn('value="epoc"', receive)

    def test_received_files_update_without_page_refresh(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn('status["received"]', source)
        self.assertIn('function renderReceived(files)', source)
        self.assertIn('path == "/transfer/delete"', source)
        self.assertIn('id="received-list"', source)

    def test_removed_saved_protocol_cannot_clear_select(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn("s.querySelector('option[value=", source)
        self.assertIn("select&&select.querySelector('option[value=", source)

    def test_guide_shortcut_selects_its_own_transfer_protocol(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn('self.redirect(f"/transfer?protocol={protocol}")', source)
        self.assertIn("requestedProtocol=new URLSearchParams(location.search).get('protocol')", source)

    def test_guide_downloads_show_size_and_effective_transfer_estimate(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn("def transfer_estimate", source)
        self.assertIn("metadata.append(human_size(size))", source)
        self.assertIn("min(configured, 9600)", source)

    def test_palm_transfer_offers_stuck_exchange_manager_recovery(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        self.assertIn("Palm gevonden maar ‘unable to connect’?", source)
        self.assertIn("10–30 cm", source)
        self.assertIn("soft reset van de Palm", source)

    def test_status_does_not_force_full_page_refresh(self):
        source = Path(web.__file__).read_text(encoding="utf-8")
        status_route = source.split('if path == "/":', 1)[1].split('elif path == "/modem":', 1)[0]
        self.assertNotIn('refresh=10', status_route)


if __name__ == "__main__":
    unittest.main()
