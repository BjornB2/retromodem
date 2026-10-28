"""Adapter/boot installation tests run only against disposable directory trees."""
import importlib.util
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_configure", ROOT / "scripts/install-configure.py")
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)


class InstallationConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "etc/retromodem/retromodem.env"
        self.boot = self.root / "boot/firmware"
        self.boot.mkdir(parents=True)
        (self.boot / "config.txt").write_text("# original\n[pi4]\ndtoverlay=vc4-kms-v3d\n")
        (self.boot / "cmdline.txt").write_text("console=serial0,115200 console=tty1 root=PARTUUID=123 rootwait quiet\n")

    def write_config(self, values):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text("".join(f"{k}={shlex.quote(v)}\n" for k, v in values.items()))

    def test_my018_confirmation_precedes_all_writes(self):
        before = {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        with self.assertRaisesRegex(ValueError, "wiring"):
            configure.apply_plan(self.root)
        self.assertFalse(self.config.exists())
        self.assertEqual(before, {p: p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_fresh_my018_selects_57600_and_boots_pl011_idempotently(self):
        self.assertTrue(configure.apply_plan(self.root, confirmed=True))
        values = configure.read_config(self.config)
        self.assertEqual(values["RETROMODEM_ADAPTER"], "ming-yuan-my018")
        self.assertEqual(values["RETROMODEM_TTY"], "/dev/serial0")
        self.assertEqual(values["RETROMODEM_DONGLE"], "")
        self.assertEqual(values["RETROMODEM_MY018_POWER_CYCLE"], "1")
        self.assertEqual(values["RETROMODEM_IRDA_BITRATE"], "57600")
        self.assertEqual(values["RETROMODEM_MY018_BITRATE"], "57600")
        self.assertEqual(values["RETROMODEM_IRDA_DIALUP_BITRATE"], "115200")
        self.assertEqual(values["RETROMODEM_MY018_DIALUP_BITRATE"], "115200")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        boot = (self.boot / "retromodem-my018.txt").read_text()
        self.assertIn("dtoverlay=disable-bt", boot)
        self.assertIn("enable_uart=1", boot)
        self.assertIn("gpio=25=op,dh", boot)
        cmdline = (self.boot / "cmdline.txt").read_text()
        self.assertNotIn("console=serial0", cmdline)
        self.assertIn("console=tty1 root=PARTUUID=123 rootwait quiet", cmdline)
        self.assertTrue((self.boot / "config.txt.pre-retromodem").exists())
        self.assertFalse(configure.apply_plan(self.root))
        self.assertEqual((self.boot / "config.txt").read_text().count("include retromodem-my018.txt"), 1)

    def test_ma620_and_serial_do_not_touch_uart_or_enable_power(self):
        for adapter in ("ma620", "serial"):
            with self.subTest(adapter=adapter), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)  # No boot directory at all is required for USB.
                self.assertFalse(configure.apply_plan(root, adapter))
                values = configure.read_config(root / "etc/retromodem/retromodem.env")
                self.assertEqual(values["RETROMODEM_MY018_POWER_CYCLE"], "0")
                self.assertEqual(values["RETROMODEM_IRDA_DIALUP_BITRATE"], "115200")
                self.assertEqual(values["RETROMODEM_SERIAL_DIALUP_BITRATE"], "115200")
                self.assertFalse((root / "boot").exists())
                if adapter == "ma620":
                    self.assertEqual(values["RETROMODEM_IRDA_BITRATE"], "9600")
                    self.assertEqual(values["RETROMODEM_DONGLE"], "ma600")
                    self.assertEqual(values["RETROMODEM_TTY"], "auto")
                else:
                    self.assertEqual(values["RETROMODEM_TRANSPORT"], "serial")
                    self.assertEqual(values["RETROMODEM_SERIAL_USB_ID"], "067b:2303")

    def test_existing_my018_and_serial_virtual_rates_survive_update(self):
        self.write_config({"RETROMODEM_ADAPTER": "ming-yuan-my018", "RETROMODEM_TRANSPORT": "irda",
                           "RETROMODEM_MY018_POWER_CYCLE": "1", "RETROMODEM_IRDA_BITRATE": "57600",
                           "RETROMODEM_IRDA_DIALUP_BITRATE": "38400", "RETROMODEM_SERIAL_DIALUP_BITRATE": "19200"})
        configure.apply_plan(self.root)
        after = configure.read_config(self.config)
        self.assertEqual(after["RETROMODEM_IRDA_DIALUP_BITRATE"], "38400")
        self.assertEqual(after["RETROMODEM_MY018_DIALUP_BITRATE"], "38400")
        self.assertEqual(after["RETROMODEM_SERIAL_DIALUP_BITRATE"], "19200")

    def test_reinstall_preserves_custom_settings_and_adapter(self):
        values = {"RETROMODEM_ADAPTER": "mobile-action-ma620", "RETROMODEM_TRANSPORT": "irda",
                  "RETROMODEM_IRDA_BITRATE": "9600", "RETROMODEM_IRDA_DIALUP_BITRATE": "19200",
                  "RETROMODEM_WEB_PASSWORD": "a $tricky ' password",
                  "RETROMODEM_AP_SSID": "My custom AP", "RETROMODEM_LINE_MODE": "dialup",
                  "RETROMODEM_SERIAL_BITRATE": "19200", "RETROMODEM_CUSTOM": "keep me"}
        self.write_config(values)
        configure.apply_plan(self.root)
        after = configure.read_config(self.config)
        for key, value in values.items():
            self.assertEqual(after[key], value)
        self.assertFalse((self.boot / "retromodem-my018.txt").exists())

    def test_switching_to_usb_keeps_confirmed_my018_support_and_profile(self):
        configure.apply_plan(self.root, confirmed=True)
        configure.apply_plan(self.root, "serial")
        after = configure.read_config(self.config)
        self.assertEqual(after["RETROMODEM_TRANSPORT"], "serial")
        self.assertEqual(after["RETROMODEM_MY018_POWER_CYCLE"], "1")
        self.assertEqual(after["RETROMODEM_MY018_BITRATE"], "57600")
        configure.apply_plan(self.root, "ma620")
        self.assertEqual(configure.read_config(self.config)["RETROMODEM_IRDA_BITRATE"], "9600")
        configure.apply_plan(self.root, "my018")
        self.assertEqual(configure.read_config(self.config)["RETROMODEM_IRDA_BITRATE"], "57600")

    def test_bad_boot_layout_and_symlinks_do_not_change_config(self):
        (self.boot / "cmdline.txt").unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            configure.apply_plan(self.root, confirmed=True)
        self.assertFalse(self.config.exists())
        (self.boot / "cmdline.txt").write_text("console=tty1 rootwait\n")
        (self.boot / "config.txt").unlink()
        original = self.root / "outside.txt"
        original.write_text("keep me\n")
        (self.boot / "config.txt").symlink_to(original)
        with self.assertRaisesRegex(ValueError, "symlink"):
            configure.apply_plan(self.root, confirmed=True)
        self.assertFalse(self.config.exists())
        self.assertEqual(original.read_text(), "keep me\n")

    def test_console_cleanup_preserves_unrelated_parameters(self):
        (self.boot / "cmdline.txt").write_text("console=ttyAMA0,115200 console=ttyS0 console=tty1 foo=bar rootwait\n")
        configure.apply_plan(self.root, confirmed=True)
        self.assertEqual((self.boot / "cmdline.txt").read_text(), "console=tty1 foo=bar rootwait\n")

    def test_unquoted_hash_inside_password_is_preserved(self):
        self.config.parent.mkdir(parents=True)
        self.config.write_text("RETROMODEM_ADAPTER=mobile-action-ma620\nRETROMODEM_WEB_PASSWORD=foo#bar\n")
        configure.apply_plan(self.root)
        self.assertEqual(configure.read_config(self.config)["RETROMODEM_WEB_PASSWORD"], "foo#bar")

    def test_installer_help_and_invalid_option_do_not_require_root(self):
        for args, expected in ((["--help"], 0), (["--invalid"], 2), (["--adapter", "bogus"], 2)):
            result = subprocess.run(["sh", str(ROOT / "install.sh"), *args], capture_output=True)
            self.assertEqual(result.returncode, expected)
