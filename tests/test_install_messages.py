import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallSummaryTests(unittest.TestCase):
    def summary(self, reboot):
        return subprocess.run(['sh', str(ROOT / 'scripts/install-summary'), reboot, 'own-user'],
                              capture_output=True, text=True)

    def test_reboot_action_precedes_post_reboot_checks(self):
        result = self.summary('1')
        self.assertEqual(result.returncode, 0)
        text = result.stdout
        self.assertIn('REBOOT THE RASPBERRY PI NOW', text)
        self.assertLess(text.index('sudo reboot'), text.index('AFTER THE REBOOT'))
        self.assertLess(text.index('AFTER THE REBOOT'), text.index('sudo retromodem-diagnose'))
        self.assertLess(text.index('AFTER THE REBOOT'), text.index('sudo retromodem-verify'))
        self.assertIn('own-user', text)

    def test_without_reboot_checks_are_immediate(self):
        result = self.summary('0')
        self.assertEqual(result.returncode, 0)
        self.assertNotIn('sudo reboot', result.stdout)
        self.assertIn('sudo retromodem-verify', result.stdout)


class DiagnosticAdapterTests(unittest.TestCase):
    def diagnose(self, adapter, transport, usb_id=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'config'
            config.write_text(f'RETROMODEM_ADAPTER={adapter}\nRETROMODEM_TRANSPORT={transport}\nRETROMODEM_LINE_MODE=ppp\n')
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            scripts = {
                'lsusb': '#!/bin/sh\n[ "$2" = "$FAKE_USB_ID" ] && echo "Bus 001 Device 001"\n',
                'readlink': '#!/bin/sh\necho /dev/ttyAMA0\n',
                'vcgencmd': '#!/bin/sh\necho throttled=0x0\n',
            }
            for name in ('modinfo', 'systemctl', 'nft', 'ip', 'journalctl'):
                scripts[name] = '#!/bin/sh\nexit 0\n'
            for name, source in scripts.items():
                path = bin_dir / name
                path.write_text(source)
                path.chmod(0o755)
            env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
                       RETROMODEM_CONFIG=str(config), FAKE_USB_ID=usb_id)
            result = subprocess.run(['sh', str(ROOT / 'scripts/diagnose')], env=env,
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

    def test_my018_does_not_require_ma620(self):
        text = self.diagnose('ming-yuan-my018', 'irda')
        self.assertIn('[INFO] MA-620 fallback not connected; it is not required for MY018.', text)
        self.assertNotIn('[FAIL] Selected MA-620', text)
        self.assertIn('[OK]   MY018 uses the PL011 UART', text)

    def test_selected_ma620_is_checked(self):
        missing = self.diagnose('mobile-action-ma620', 'irda')
        self.assertIn('[FAIL] Selected MA-620 infrared fallback found', missing)
        present = self.diagnose('mobile-action-ma620', 'irda', '0df7:0620')
        self.assertIn('[OK]   Selected MA-620 infrared fallback found', present)

    def test_serial_does_not_require_irda_or_ma620(self):
        text = self.diagnose('ming-yuan-my018', 'serial', '067b:2303')
        self.assertIn('[OK]   Selected Prolific RS-232 adapter found', text)
        self.assertNotIn('IrDA service active', text)
        self.assertNotIn('IrCOMM device present', text)
