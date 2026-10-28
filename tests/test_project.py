import json
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_button_module():
    path = ROOT / "scripts/button-control.py"
    spec = importlib.util.spec_from_file_location("retromodem_button", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class InstallationTests(unittest.TestCase):
    def test_installer_contains_every_runtime_component(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        required = [
            "scripts/modem-backend.py",
            "scripts/apply-mode",
            "scripts/dialup-ppp",
            "scripts/selftest",
            "scripts/verify-install",
            "scripts/button-control.py",
            "openobex-apps",
            "web/static/software/",
            "systemd/retromodem-mode.service",
            "systemd/retromodem-tcpser.service",
            "systemd/retromodem-button.service",
            "config/xinetd-retromodem-ppp",
        ]
        for component in required:
            with self.subTest(component=component):
                self.assertIn(component, installer)

    def test_clean_install_verifier_checks_defaults_and_drift(self):
        verifier = (ROOT / "scripts/verify-install").read_text(encoding="utf-8")
        self.assertIn('"5559000"', verifier)
        self.assertIn('"5551000"', verifier)
        self.assertIn("install-manifest.sha256", verifier)
        self.assertIn("sha256sum -c", verifier)
        self.assertIn("retromodem-web.service", verifier)

    def test_installer_preserves_imager_ssh_account(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('admin_user=${SUDO_USER:-}', installer)
        self.assertNotIn("useradd", installer)
        self.assertNotIn("chpasswd", installer)
        self.assertIn("install.json", installer)
        self.assertIn("ssh.service", installer)

    def test_installer_rejects_non_bookworm_images(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("VERSION_ID=", installer)
        self.assertIn("Legacy Bookworm", installer)
        self.assertIn("exit 1", installer)

    def test_button_controls_mode_and_clean_shutdown(self):
        button = (ROOT / "scripts/button-control.py").read_text(encoding="utf-8")
        unit = (ROOT / "systemd/retromodem-button.service").read_text(encoding="utf-8")
        defaults = (ROOT / "config/retromodem.env").read_text(encoding="utf-8")
        self.assertIn('new_mode = "dialup" if current == "ppp" else "ppp"', button)
        self.assertIn('["/usr/bin/systemctl", "poweroff"]', button)
        self.assertIn('RETROMODEM_BUTTON_HOLD_SECONDS', button)
        self.assertIn('RETROMODEM_BUTTON_HOLD_SECONDS=3.0', defaults)
        self.assertIn('Restart=on-failure', unit)

    def test_front_led_daemon_covers_network_and_power_states(self):
        status_leds = (ROOT / "scripts/status-leds.py").read_text(encoding="utf-8")
        unit = (ROOT / "systemd/retromodem-leds.service").read_text(encoding="utf-8")
        defaults = (ROOT / "config/retromodem.env").read_text(encoding="utf-8")
        self.assertIn('network == "hotspot"', status_leds)
        self.assertIn('network == "connecting"', status_leds)
        self.assertIn('modem == "starting"', status_leds)
        self.assertIn('process_has_modem_tty', status_leds)
        self.assertIn('MINIMUM_START_INDICATION = 3.0', status_leds)
        self.assertIn('int(match.group(1), 16) & 0x1', status_leds)
        self.assertIn('ExecStart=/usr/bin/python3 /usr/local/lib/retromodem/status-leds.py', unit)
        self.assertIn('RETROMODEM_WIFI_FALLBACK_SECONDS=10', defaults)

    def test_mode_led_setter_reads_persisted_mode_itself(self):
        setter = (ROOT / "scripts/set-mode-leds").read_text(encoding="utf-8")
        self.assertIn('. /etc/retromodem/retromodem.env', setter)

    def test_button_understands_pinctrl_levels(self):
        button = load_button_module()
        self.assertTrue(button.parse_level("16: ip pu | hi // GPIO16 = input"))
        self.assertFalse(button.parse_level("16: ip pu | lo // GPIO16 = input"))
        self.assertTrue(button.parse_level("gpio16 level=1"))

    def test_acceptance_plan_separates_automatic_and_physical_tests(self):
        plan = (ROOT / "docs/CLEAN-INSTALL-ACCEPTANCE.md").read_text(encoding="utf-8")
        self.assertIn("sudo retromodem-verify", plan)
        self.assertIn("Psion 5mx, direct PPP via IrDA", plan)
        self.assertIn("Palm IIIc, direct PPP via IrDA", plan)
        self.assertIn("tweede uitvoering van de installer", plan)

    def test_external_sources_are_pinned_to_full_commits(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertRegex(installer, r"IRDA_COMMIT=[0-9a-f]{40}\n")
        self.assertRegex(installer, r"TCPSER_COMMIT=[0-9a-f]{40}\n")

    def test_tcpser_starts_from_valid_termios_state(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        patch = (ROOT / "patches/tcpser-initialize-termios.patch").read_text(encoding="utf-8")
        self.assertIn("tcpser-initialize-termios.patch", installer)
        self.assertIn("tcgetattr(fd, &tio)", patch)

    def test_retroweb_proxy_is_toggleable_and_transparent(self):
        unit = (ROOT / "systemd/retromodem-proxy.service").read_text(encoding="utf-8")
        firewall = (ROOT / "scripts/proxy-firewall").read_text(encoding="utf-8")
        proxy = (ROOT / "scripts/retroweb-proxy.py").read_text(encoding="utf-8")
        core = (ROOT / "proxy/retroweb/lib/ContentExtractor.php").read_text(encoding="utf-8")
        self.assertIn("ExecCondition=/usr/local/lib/retromodem/proxy-enabled", unit)
        self.assertIn("proxy-firewall apply", unit)
        self.assertIn("tcp dport 80 redirect to :8080", firewall)
        self.assertIn("ip daddr != 192.168.77.1", firewall)
        self.assertIn("tcp dport 8080 iifname != ppp0 ip saddr != 127.0.0.1 drop", firewall)
        self.assertIn("fetch_retroweb", proxy)
        self.assertIn("class HybridExtractor", core)
        self.assertIn("/proxy.php", proxy)
        self.assertIn("RETROMODEM_PROXY_IMAGE_MODE", proxy)
        self.assertNotIn("Processed page size", proxy)
        defaults = (ROOT / "config/retromodem.env").read_text(encoding="utf-8")
        self.assertIn("retroweb.bjrno.com", defaults)

    def test_ppp_profile_answers_legacy_wins_requests(self):
        profile = (ROOT / "config/ppp/retromodem").read_text(encoding="utf-8")
        self.assertEqual(profile.count("ms-wins 192.168.77.1"), 2)
        backend = (ROOT / "scripts/modem-backend.py").read_text(encoding="utf-8")
        self.assertEqual(backend.count('"ms-wins", "192.168.77.1"'), 2)
        dialup = (ROOT / "scripts/dialup-ppp").read_text(encoding="utf-8")
        self.assertEqual(dialup.count("ms-wins 192.168.77.1"), 2)

    def test_irda_dialup_tracks_carrier_without_hardware_flow_control(self):
        backend = (ROOT / "scripts/modem-backend.py").read_text(encoding="utf-8")
        self.assertIn('init = "e1&c1&k0" if', backend)
        self.assertNotIn('init = "e1&c0&k0" if', backend)

    def test_irda_service_advertises_a_windows_modem(self):
        helper = (ROOT / "src/irda-modem-hints.c").read_text(encoding="utf-8")
        launcher = (ROOT / "scripts/start-irda").read_text(encoding="utf-8")
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("HINT_MODEM", helper)
        self.assertIn("HINT_COMM << 8", helper)
        self.assertIn("irda-modem-hints &", launcher)
        self.assertIn('"$PROJECT_DIR/src/irda-modem-hints.c"', installer)

    def test_dialup_ppp_uses_raw_xinetd_socket_without_telnet_negotiation(self):
        xinetd = (ROOT / "config/xinetd-retromodem-ppp").read_text(encoding="utf-8")
        dialup = (ROOT / "scripts/dialup-ppp").read_text(encoding="utf-8")
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("server      = /usr/local/lib/retromodem/dialup-ppp", xinetd)
        self.assertNotIn("telnetd", xinetd)
        self.assertIn("pppd notty nodetach", dialup)
        self.assertNotIn("inetutils-telnetd", installer)

    def test_transfer_verifies_modem_recovery(self):
        transfer = (ROOT / "scripts/transfer.py").read_text(encoding="utf-8")
        self.assertIn("def restore_modem_mode", transfer)
        self.assertIn('systemctl", "is-active", "--quiet", expected', transfer)
        self.assertIn("restore_error = restore_modem_mode(values)", transfer)

    def test_transfer_terminal_phase_matches_failure_state(self):
        transfer = (ROOT / "scripts/transfer.py").read_text(encoding="utf-8")
        self.assertIn('phase = "finished" if state == "complete" else state', transfer)

    def test_palm_beam_is_wired_end_to_end(self):
        transfer = (ROOT / "scripts/transfer.py").read_text(encoding="utf-8")
        web = (ROOT / "web/web.py").read_text(encoding="utf-8")
        self.assertIn('"/usr/bin/irobex_palm3"', transfer)
        self.assertIn('palm_creator_id(path)', transfer)
        self.assertIn('command = ["/usr/bin/irobex_palm3"]', transfer)
        self.assertIn('<option value="palm">Palm Beam', web)
        self.assertIn('"eudoraweb-2.1"', web)
        self.assertIn('"mocha-telnet-3.0"', web)
        self.assertTrue((ROOT / "web/static/software/EudoraWeb_2.1.prc").is_file())
        self.assertTrue((ROOT / "web/static/software/MochaTelnet_3.0.prc").is_file())

    def test_windows_wireless_link_is_wired_end_to_end(self):
        transfer = (ROOT / "scripts/transfer.py").read_text(encoding="utf-8")
        web = (ROOT / "web/web.py").read_text(encoding="utf-8")
        verifier = (ROOT / "scripts/verify-install").read_text(encoding="utf-8")
        self.assertIn('["/usr/bin/ircp", path.name]', transfer)
        self.assertIn('["/usr/bin/ircp", "-r", str(received_dir)]', transfer)
        self.assertEqual(web.count('<option value="windows">Windows Wireless Link'), 2)
        self.assertIn('irobex_palm3 ircp', verifier)

    def test_uploaded_guide_library_is_persistent_and_downloadable(self):
        web = (ROOT / "web/web.py").read_text(encoding="utf-8")
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('LIBRARY_ROOT = Path("/var/lib/retromodem/software-library")', web)
        self.assertIn('action="/guides/upload"', web)
        self.assertIn('path == "/library/download"', web)
        self.assertIn('software_catalog().get(software_id)', web)
        self.assertIn('/var/lib/retromodem/software-library', installer)

    def test_quickstart_contains_every_access_route(self):
        guide = (ROOT / "docs/QUICKSTART.md").read_text(encoding="utf-8")
        self.assertIn('`http://10.42.0.1`', guide)
        self.assertIn('ssh JOUW_GEBRUIKERSNAAM@retromodem.local', guide)
        self.assertIn('Raspberry Pi Imager', guide)
        self.assertIn('`retromodem` / `retromodem`', guide)

    def test_irda_service_applies_adapter_qos_ceilings(self):
        unit = (ROOT / "systemd/retromodem-irda.service").read_text(encoding="utf-8")
        self.assertIn("RETROMODEM_IRDA_MAX_TX_DATA_SIZE", unit)
        self.assertIn("RETROMODEM_IRDA_MAX_TX_WINDOW", unit)
        defaults = (ROOT / "config/retromodem.env").read_text(encoding="utf-8")
        self.assertIn("RETROMODEM_IRDA_MAX_TX_DATA_SIZE=2042", defaults)
        self.assertIn("RETROMODEM_IRDA_MAX_TX_WINDOW=7", defaults)


class CapabilityTests(unittest.TestCase):
    def test_every_adapter_declares_protocol_capabilities(self):
        document = json.loads((ROOT / "config/hardware/adapters.json").read_text(encoding="utf-8"))
        required = {
            "ircomm_ppp", "ircomm_hayes", "serial_file_transfer",
            "epoc_eikonir_send", "epoc_eikonir_receive", "irobex", "raw_hpsir",
        }
        for adapter in document["adapters"]:
            with self.subTest(adapter=adapter["id"]):
                self.assertEqual(set(adapter["capabilities"]), required)


if __name__ == "__main__":
    unittest.main()
