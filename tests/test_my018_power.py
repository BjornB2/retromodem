import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/my018-power-cycle'


class PowerSequenceTests(unittest.TestCase):
    def run_sequence(self, rate, fail_on=''):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock = root / 'pinctrl'
            mock.write_text('#!/bin/sh\necho "$*" >> "$CALL_LOG"\n'
                            '[ -z "$FAIL_ON" ] || [ "$*" != "$FAIL_ON" ]\n')
            mock.chmod(0o755)
            log = root / 'calls'
            environment = dict(os.environ, MY018_PINCTRL=str(mock),
                               MY018_SLEEP='/usr/bin/true',
                               MY018_FLOCK='/usr/bin/true',
                               MY018_LOCKFILE=str(root / 'lock'),
                               CALL_LOG=str(log), FAIL_ON=fail_on)
            result = subprocess.run(['/bin/sh', str(SCRIPT), str(rate)],
                                    env=environment, capture_output=True, text=True)
            calls = log.read_text().splitlines() if log.exists() else []
            return result, calls

    def test_all_speeds_release_signals_before_off_and_select_before_on(self):
        for rate, high in [(9600, []), (19200, [17]), (38400, [27]),
                           (57600, [17, 27]), (115200, [22])]:
            with self.subTest(rate=rate):
                result, calls = self.run_sequence(rate)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, ['set 14,15,17,27,22 ip pn', 'set 25 op dl']
                                 + [f'set {pin} op dh' for pin in high]
                                 + ['set 25 op dh', 'set 14,15 a0'])

    def test_invalid_speed_does_not_touch_any_gpio(self):
        result, calls = self.run_sequence(12345)
        self.assertEqual(result.returncode, 64)
        self.assertEqual(calls, [])

    def test_failure_restores_ground_before_uart(self):
        result, calls = self.run_sequence(19200, fail_on='set 17 op dh')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls[-3:], ['set 14,15,17,27,22 ip pn',
                                     'set 25 op dh', 'set 14,15 a0'])


if __name__ == '__main__':
    unittest.main()
