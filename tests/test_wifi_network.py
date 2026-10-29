import io
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from web import wifi_network as wifi

PROFILE = '[connection]\nuuid=new-uuid\nid=Target\ntype=wifi\n\n[wifi]\nssid=Target\nmode=infrastructure\n'


class WifiNetworkTests(unittest.TestCase):
    def setUp(self):
        wifi._operation = threading.Lock()
        wifi._set_job('')

    def test_status_distinguishes_hotspot_from_client(self):
        for mode, expected in [('ap', 'hotspot'), ('infrastructure', 'connected')]:
            with patch.object(wifi, '_run', side_effect=['100 (connected)\nactive-uuid\n', 'Network\n' + mode + '\n']):
                result = wifi.status({})
            self.assertEqual(result['state'], expected)
            self.assertEqual(result['ssid'], 'Network')

    def test_status_errors_are_generic(self):
        with patch.object(wifi.subprocess, 'run', side_effect=OSError('secret-password')):
            result = wifi.status({})
        self.assertNotIn('secret-password', str(result))
        self.assertEqual(result['message'], 'Wi-Fi status unavailable')

    def test_scan_unescapes_deduplicates_bounds_and_does_not_disconnect_ap(self):
        output = 'A\\:B:30:WPA2\nA\\:B:70:WPA2\nPath\\\\Name:50:--\nretromodem:99:WPA2\n'
        output += ''.join('Net%d:%d:WPA2\n' % (i, i % 101) for i in range(100))
        with patch.object(wifi, '_run', return_value=output) as run:
            rows = wifi.scan({})
        self.assertEqual(len(rows), 64)
        self.assertIn(('A:B', 70, 'WPA2'), rows)
        self.assertIn(('Path\\Name', 50, '--'), rows)
        self.assertNotIn('retromodem', [row[0] for row in rows])
        self.assertEqual(run.call_args.kwargs['timeout'], 20)
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('down', run.call_args.args)

    def test_scan_failure_does_not_leak_nmcli_output_or_hold_lock(self):
        response = subprocess.CompletedProcess([], 1, 'ssid password secret', 'secret again')
        with patch.object(wifi.subprocess, 'run', return_value=response):
            with self.assertRaisesRegex(RuntimeError, '^Wi-Fi operation failed$'):
                wifi.scan({})
        self.assertFalse(wifi._operation.locked())

    def test_connect_is_async_serialized_and_never_puts_password_in_argv(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(wifi, 'RUNTIME', Path(directory)), \
                patch.object(wifi.threading, 'Thread') as thread:
            wifi.connect({}, 'Target', 'a-secret-password')
            self.assertEqual(thread.call_count, 1)
            thread.return_value.start.assert_called_once()
            with self.assertRaisesRegex(RuntimeError, 'in progress'):
                wifi.connect({}, 'Second', 'second-secret')
            args = thread.call_args.kwargs['args']
            self.assertEqual(args[:3], ('wlan0', 'Target', 'a-secret-password'))
            # Simulate completion of the async worker with a fake NetworkManager.
            calls = []

            def run(*arguments, **kwargs):
                calls.append((arguments, kwargs))
                return PROFILE if '--offline' in arguments else ''

            with patch.object(wifi, '_run', side_effect=run), patch.object(wifi.time, 'sleep'), \
                    patch.object(wifi, 'PROFILES', Path(directory) / 'profiles'), \
                    patch.object(wifi.uuid, 'uuid4', return_value='new-uuid'), \
                    patch.object(wifi, '_actual', side_effect=[
                        {'uuid': 'old-uuid', 'state': 'connected', 'ssid': 'Old'},
                        {'uuid': 'new-uuid', 'state': 'connected', 'ssid': 'Target'}]):
                wifi._worker(*args)
            self.assertFalse(wifi._operation.locked())
            self.assertFalse((Path(directory) / 'wifi-transition').exists())
            for arguments, kwargs in calls:
                self.assertNotIn('a-secret-password', str(arguments))
            up = [call for call in calls if 'up' in call[0]][0]
            self.assertIn('new-uuid', up[0])
            stored = Path(directory) / 'profiles/retromodem-new-uuid.nmconnection'
            self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
            self.assertIn('psk=a-secret-password\n', stored.read_text())
            self.assertIn('psk-flags=0', stored.read_text())
            self.assertEqual(wifi._job['state'], 'connected')
            self.assertNotIn('a-secret-password', str(wifi._job))

    def test_failed_attempt_restores_original_and_only_deletes_own_profile(self):
        calls = []

        def run(*arguments, **kwargs):
            calls.append(arguments)
            if 'up' in arguments and 'new-uuid' in arguments:
                raise RuntimeError('secret should not escape')
            return PROFILE if '--offline' in arguments else ''

        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'wifi-transition'
            marker.touch()
            wifi._operation.acquire()
            with patch.object(wifi, '_actual', return_value={'uuid': 'old-uuid'}), \
                    patch.object(wifi, 'PROFILES', Path(directory) / 'profiles'), \
                    patch.object(wifi.uuid, 'uuid4', return_value='new-uuid'), \
                    patch.object(wifi.time, 'sleep'), patch.object(wifi, '_run', side_effect=run):
                wifi._worker('wlan0', 'Target', 'a-secret-password', io.StringIO(), marker)
            self.assertFalse((Path(directory) / 'profiles/retromodem-new-uuid.nmconnection').exists())
        self.assertIn(('connection', 'delete', 'uuid', 'new-uuid'), calls)
        self.assertNotIn(('connection', 'delete', 'uuid', 'old-uuid'), calls)
        self.assertTrue(any('up' in call and 'old-uuid' in call for call in calls))
        self.assertEqual(wifi._job['state'], 'failed')
        self.assertNotIn('secret', wifi._job['message'])
        self.assertFalse(wifi._operation.locked())

    def test_recovery_uses_setup_ap_if_previous_profile_cannot_start(self):
        with patch.object(wifi, '_run', side_effect=[RuntimeError('failure'), '']) as run, \
                patch.object(wifi.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as configure:
            wifi._restore('wlan0', 'old-uuid')
        configure.assert_called_once()
        self.assertIn('/usr/local/lib/retromodem/configure-ap', configure.call_args.args[0])
        self.assertIn('retromodem-ap', run.call_args.args)

    def test_unsafe_ssid_password_and_interface_rejected_before_spawn(self):
        with patch.object(wifi.threading, 'Thread') as thread:
            for ssid, password in [('X\nY', 'password'), ('X', 'password\r'), ('', 'password'), ('X', 'short')]:
                with self.assertRaises(ValueError):
                    wifi.connect({}, ssid, password)
            with self.assertRaises(ValueError):
                wifi.connect({'RETROMODEM_WIFI_INTERFACE': ';unsafe'}, 'X', 'password')
        thread.assert_not_called()

    def test_existing_transition_is_not_removed_by_rejected_request(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(wifi, 'RUNTIME', Path(directory)):
            marker = Path(directory) / 'wifi-transition'
            marker.touch()
            with self.assertRaisesRegex(RuntimeError, '^Wi-Fi connection could not be started$'):
                wifi.connect({}, 'Target', '')
            self.assertTrue(marker.exists())
            self.assertFalse(wifi._operation.locked())

    def test_owned_stale_marker_is_recovered_but_live_owner_is_not(self):
        import json
        with tempfile.TemporaryDirectory() as directory, patch.object(wifi, 'RUNTIME', Path(directory)):
            marker = Path(directory) / 'wifi-transition'
            marker.write_text(json.dumps({'owner': 'wifi-network-v1', 'pid': 123, 'identity': 'old-boot:start'}))
            with patch.object(wifi, '_process_identity', return_value='old-boot:start'):
                wifi.recover()
            self.assertTrue(marker.exists())
            with patch.object(wifi, '_process_identity', return_value='new-boot:start'):
                wifi.recover()
            self.assertFalse(marker.exists())

    def test_utf8_password_bytes_and_keyfile_escaping(self):
        with self.assertRaises(ValueError):
            wifi.connect({}, 'Target', 'é' * 40)
        with tempfile.TemporaryDirectory() as directory, patch.object(wifi, 'PROFILES', Path(directory)):
            stored = wifi._write_profile(PROFILE, ' pass\\word ', 'new-uuid')
            self.assertIn('psk=\\spass\\\\word\\s', stored.read_text())
            self.assertEqual(stored.stat().st_mode & 0o777, 0o600)
