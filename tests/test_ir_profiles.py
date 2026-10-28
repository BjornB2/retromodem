import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('profile_web', Path(__file__).resolve().parents[1] / 'web/web.py')
web = importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)


class ProfileTests(unittest.TestCase):
    def submit(self, selected, rate='9600', power=False):
        config = {'RETROMODEM_ADAPTER': 'ming-yuan-my018', 'RETROMODEM_IRDA_BITRATE': '9600', 'RETROMODEM_IRDA_DIALUP_BITRATE': '57600'}
        if power:
            config['RETROMODEM_MY018_POWER_CYCLE'] = '1'
        handler = object.__new__(web.Handler)
        handler.path = '/modem/settings'
        handler.config = Mock(return_value=config)
        handler.require_auth = Mock(return_value=True)
        handler.valid_csrf = Mock(return_value=True)
        handler.form = Mock(return_value={
            'transport': 'irda', 'line_mode': 'ppp', 'irda_adapter': selected,
            'my018_bitrate': rate, 'my018_dialup_bitrate': '57600',
            'ma620_bitrate': '19200', 'ma620_dialup_bitrate': '38400',
            'serial_bitrate': '115200', 'serial_dialup_bitrate': '57600',
        })
        handler.send_error = Mock()
        handler.redirect = Mock()
        with patch.object(web, 'save_config') as save, patch.object(web, 'run') as run:
            handler.do_POST()
        return handler, save, run

    def test_switch_to_usb_preserves_both_profiles(self):
        handler, save, run = self.submit('mobile-action-ma620')
        handler.send_error.assert_not_called()
        values = save.call_args.args[0]
        self.assertEqual(values['RETROMODEM_TTY'], 'auto')
        self.assertEqual(values['RETROMODEM_DONGLE'], 'ma600')
        self.assertEqual(values['RETROMODEM_IRDA_BITRATE'], '19200')
        self.assertEqual(values['RETROMODEM_MY018_BITRATE'], '9600')
        self.assertEqual(values['RETROMODEM_MA620_DIALUP_BITRATE'], '38400')
        run.assert_called_once()

    def test_gpio_uses_no_usb_dongle_driver(self):
        handler, save, run = self.submit('ming-yuan-my018')
        handler.send_error.assert_not_called()
        values = save.call_args.args[0]
        self.assertEqual(values['RETROMODEM_TTY'], '/dev/serial0')
        self.assertEqual(values['RETROMODEM_DONGLE'], '')
        self.assertEqual(values['RETROMODEM_IRDA_DIALUP_BITRATE'], '57600')

    def test_gpio_rejects_unsupported_physical_speed(self):
        handler, save, run = self.submit('ming-yuan-my018', '115200')
        handler.send_error.assert_called_once()
        save.assert_not_called()
        run.assert_not_called()

    def test_modified_gpio_accepts_each_supported_limit(self):
        for rate in web.ALLOWED_BITRATES:
            with self.subTest(rate=rate):
                handler, save, run = self.submit('ming-yuan-my018', rate, power=True)
                handler.send_error.assert_not_called()
                self.assertEqual(save.call_args.args[0]['RETROMODEM_MY018_BITRATE'], rate)
                self.assertEqual(save.call_args.args[0]['RETROMODEM_IRDA_BITRATE'], rate)
                run.assert_called_once()

    def test_modified_profile_labels_and_conditional_warning(self):
        rendered = web.ir_adapter_settings({'RETROMODEM_ADAPTER': 'ming-yuan-my018',
                    'RETROMODEM_MY018_POWER_CYCLE': '1', 'RETROMODEM_MY018_BITRATE': '115200'}, 'nl')
        self.assertIn('57600 — getest, aanbevolen', rendered)
        self.assertIn('38400 — nog niet getest', rendered)
        self.assertIn('115200 — experimenteel, waarschuwing', rendered)
        self.assertIn('data-speed-warning="115200" role="status" >', rendered)
        self.assertIn('Dit is geen algemene IrDA-limiet', rendered)
        self.assertIn('Maximale fysieke IrDA-linksnelheid', rendered)

    def test_warning_initially_hidden_at_57600(self):
        rendered = web.ir_adapter_settings({'RETROMODEM_ADAPTER': 'ming-yuan-my018',
                    'RETROMODEM_MY018_POWER_CYCLE': '1', 'RETROMODEM_MY018_BITRATE': '57600'}, 'nl')
        self.assertIn('data-speed-warning="115200" role="status" hidden', rendered)

    def test_guide_adapter_facts_and_transfer_estimates(self):
        for language in ('nl', 'en'):
            guide = web.guides_page(language)
            self.assertIn('MY018', guide)
            self.assertIn('115k2:' if language == 'nl' else '115k2:', guide)
            self.assertIn('23,91' if language == 'nl' else '23.91', guide)
            self.assertNotIn('Voor IR: infrarode mobiele telefoon, 9600 bit/s.', guide)
        config = {'RETROMODEM_ADAPTER': 'ming-yuan-my018', 'RETROMODEM_IRDA_BITRATE': '57600'}
        self.assertIn('(57600 bit/s)', web.transfer_estimate(79026, 'palm', config))
        config['RETROMODEM_ADAPTER'] = 'mobile-action-ma620'
        self.assertIn('(9600 bit/s)', web.transfer_estimate(79026, 'palm', config))
