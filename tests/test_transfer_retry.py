import json
import importlib.util
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock
from web import web

spec = importlib.util.spec_from_file_location('transfer_retry_worker', Path(__file__).resolve().parents[1] / 'scripts/transfer.py')
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)


class RetryTests(unittest.TestCase):
    def test_library_send_uses_original_name_and_keeps_duplicate_copies_separate(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory) / 'transfers'), patch.object(web, 'LIBRARY_ROOT', Path(directory) / 'library'), patch.object(web.subprocess, 'Popen') as popen, patch.object(web.threading, 'Thread'):
            web.LIBRARY_ROOT.mkdir()
            stored = web.LIBRARY_ROOT / '0123456789abcdef-Palmscape.prc'
            stored.write_bytes(b'payload')
            catalog = {'browser': {'uploaded': True, 'stored_name': stored.name,
                                  'original_name': 'Palmscape.prc', 'protocol': 'palm'}}
            paths = []
            with patch.object(web, 'software_catalog', return_value=catalog):
                for _ in range(2):
                    handler = self.handler({})
                    handler.path = '/transfer/library-send'
                    handler.form = lambda: {'software': 'browser'}
                    handler.do_POST()
                    handler.send_error.assert_not_called()
                    paths.append(Path(popen.call_args.args[0][-1]))
                    self.assertEqual(web.pending_send()['filename'], 'Palmscape.prc')
            self.assertNotEqual(paths[0], paths[1])
            self.assertTrue(all(path.name == 'Palmscape.prc' and path.read_bytes() == b'payload' for path in paths))
            self.assertEqual(stored.read_bytes(), b'payload')

    def test_payload_progress_and_speed_use_bytes_not_elapsed_estimates(self):
        meter = worker.TransferProgress()
        self.assertEqual(meter.update('Searching for Palm', 10), {})
        self.assertEqual(meter.update('RETROMODEM_PROGRESS 0 10000', 20)['progress'], 0)
        result = meter.update('.RETROMODEM_PROGRESS 4000 10000', 22)
        self.assertEqual(result['progress'], 40)
        self.assertEqual(result['speed_kbytes_sec'], 2)
        self.assertEqual(meter.update('Still waiting', 80), result)
        self.assertEqual(meter.update('RETROMODEM_PROGRESS 10000 10000', 25)['progress'], 99.9)

    def test_epoc_progress_uses_reported_payload_and_transfer_time(self):
        meter = worker.TransferProgress()
        result = meter.update('sent 2783/36876 bytes= 7.5% in 2 sec', 100)
        self.assertAlmostEqual(result['progress'], 2783 / 36876 * 100)
        self.assertEqual(result['speed_kbytes_sec'], 1.3915)
        self.assertEqual(meter.update('Waiting for ACK', 110), result)
        self.assertEqual(meter.update('RETROMODEM_PROGRESS 200 100', 120), result)

    def test_lrzsz_progress_uses_accepted_sectors_excluding_ymodem_header(self):
        meter = worker.TransferProgress(10000)
        self.assertEqual(meter.update('Ymodem sectors/kbytes sent: 1/0k', 0)['bytes_transferred'], 0)
        result = meter.update('Ymodem sectors/kbytes sent: 9/1k', 1)
        self.assertEqual(result['bytes_transferred'], 1024)
        self.assertEqual(result['speed_kbytes_sec'], 1.024)
        self.assertEqual(worker.TransferProgress(10000).update('Xmodem sectors/kbytes sent: 8/1k', 0)['bytes_transferred'], 1024)
        self.assertEqual(meter.update('Bytes Sent: 10112 BPS: 1024', 10)['bytes_transferred'], 10000)
        self.assertEqual(meter.update('Ymodem sectors/kbytes sent: 0/0k', 11)['bytes_transferred'], 10000)

    def test_zmodem_receive_progress(self):
        result = worker.TransferProgress().update('Bytes received: 1024/10000 BPS: 512', 0)
        self.assertEqual(result['bytes_transferred'], 1024)
        self.assertEqual(result['progress'], 10.24)

    def test_clear_selection_removes_work_copy_not_original(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)):
            root = Path(directory)
            original = root / 'original.txt'
            original.write_bytes(b'original')
            work = root / 'work-012345abcdef'
            work.mkdir()
            asset = work / 'original.txt'
            asset.write_bytes(original.read_bytes())
            web.remember_send(asset, 'ymodem')
            handler = self.handler({})
            handler.path = '/transfer/clear-selection'
            handler.form = lambda: {'retry_token': work.name}
            handler.send_response = Mock()
            handler.end_headers = Mock()
            handler.do_POST()
            self.assertIsNone(web.pending_send())
            self.assertFalse(asset.exists())
            self.assertEqual(original.read_bytes(), b'original')
            handler.send_response.assert_called_once_with(204)

    def test_clear_selection_rejects_active_transfer_or_wrong_token(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)), patch.object(web, 'transfer_process_alive', return_value=True):
            root = Path(directory)
            work = root / 'work-012345abcdef'
            work.mkdir()
            asset = work / 'test.txt'
            asset.write_bytes(b'payload')
            web.remember_send(asset, 'ymodem')
            for state in ['running', 'error']:
                (root / 'status.json').write_text(json.dumps({'state': state}))
                handler = self.handler({})
                handler.path = '/transfer/clear-selection'
                handler.form = lambda: {'retry_token': 'wrong'}
                handler.do_POST()
                self.assertEqual(handler.send_error.call_args.args[0], 409)
                self.assertTrue(asset.exists())

    def test_received_selection_only_stages_copy_and_allows_protocol_choice(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)), patch.object(web, 'RECEIVED', Path(directory) / 'received'), patch.object(web.subprocess, 'Popen') as popen:
            web.RECEIVED.mkdir()
            source = web.RECEIVED / 'memo.txt'
            source.write_bytes(b'memo')
            handler = self.handler({})
            handler.path = '/transfer/select-received'
            handler.form = lambda: {'name': 'memo.txt'}
            handler.do_POST()
            selected = web.pending_send()
            self.assertEqual(selected['filename'], 'memo.txt')
            self.assertEqual((web.TRANSFERS / selected['token'] / selected['filename']).read_bytes(), b'memo')
            popen.assert_not_called()
            handler = self.handler({'direction': 'send', 'protocol': 'ascii', 'retry_token': selected['token']})
            with patch.object(web.threading, 'Thread'):
                handler.do_POST()
            self.assertEqual(popen.call_args.args[0][2], 'ascii')
            self.assertEqual(source.read_bytes(), b'memo')

    def test_received_selection_rejects_paths_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)), patch.object(web, 'RECEIVED', Path(directory) / 'received'):
            web.RECEIVED.mkdir()
            (web.RECEIVED / 'link').symlink_to('/etc/hosts')
            for name in ['../outside', 'link', 'missing']:
                handler = self.handler({})
                handler.path = '/transfer/select-received'
                handler.form = lambda: {'name': name}
                handler.do_POST()
                self.assertEqual(handler.send_error.call_args.args[0], 404)

    def test_worker_retains_failed_and_cancelled_payload_until_success(self):
        for outcome, keep in [('error', True), ('cancelled', True), ('complete', False), ('restore-error', True)]:
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                work = root / 'work-012345abcdef'
                work.mkdir()
                asset = work / 'test.prc'
                asset.write_bytes(b'0' * 64 + b'TEST')
                with patch.object(worker, 'ROOT', root), patch.object(worker, 'LOCK', root / 'lock'), patch.object(worker, 'config', return_value={}), patch.object(worker, 'write_status') as status, patch.object(worker, 'restore_modem_mode', return_value='failed' if outcome == 'restore-error' else ''), patch.object(worker.subprocess, 'run'), patch.object(worker.signal, 'signal'), patch.object(worker.sys, 'argv', ['transfer.py', 'send', 'palm', str(asset)]), patch.object(worker, 'execute_device', side_effect=worker.TransferCancelled() if outcome == 'cancelled' else None, return_value=(1, 'bad') if outcome == 'error' else (0, 'OK')):
                    worker.main()
                self.assertEqual(asset.exists(), keep)
                self.assertEqual(status.call_args.args[0], 'error' if outcome == 'restore-error' else outcome)

    def test_rendered_transfer_javascript_parses(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)), patch.object(web, 'RECEIVED', Path(directory) / 'received'):
            handler = self.handler({})
            handler.path = '/transfer'
            handler.send_page = Mock()
            handler.do_GET()
            body = handler.send_page.call_args.args[1]
            script = re.search(r'<script>(.*?)</script>', body, re.S).group(1)
            result = subprocess.run(['node', '--check'], input=script, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            render = re.search(r'function renderStatus\(s\).*?(?=function renderReceived)', script, re.S).group(0)
            harness = '''
const elements = new Map();
function element(id){if(!elements.has(id))elements.set(id,{style:{},classList:{toggle(){}},setAttribute(k,v){this[k]=v},removeAttribute(k){delete this[k]}});return elements.get(id)}
const document={getElementById:element,querySelector:element};
''' + render + '''
renderStatus({state:'running',phase:'transferring',protocol:'palm',progress:40,bytes_transferred:4000,bytes_total:10000,speed_kbytes_sec:2});
if(!element('status-meta').textContent.includes('40% · 4.0 / 10.0 kB · 2.00 kB/s'))throw Error('Missing measured progress');
if(element('#progress span').style.width!=='40%')throw Error('Incorrect bar width');
renderStatus({state:'running',phase:'discovering'});
if(element('status-meta').textContent.includes('%'))throw Error('Fabricated discovery percentage');
if(element('progress')['aria-valuenow']!==undefined)throw Error('Stale progress value');
'''
            result = subprocess.run(['node'], input=harness, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def handler(self, form, filename='', payload=b''):
        handler = web.Handler.__new__(web.Handler)
        handler.path = '/transfer/start'
        handler.config = lambda: {}
        handler.require_auth = lambda _: True
        handler.valid_csrf = lambda _: True
        handler.multipart = lambda: (form, filename, payload)
        handler.redirect = Mock()
        handler.send_error = Mock()
        return handler

    def test_post_upload_then_retry_uses_same_payload_without_upload(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)), patch.object(web.subprocess, 'Popen') as popen, patch.object(web.threading, 'Thread'):
            handler = self.handler({'direction': 'send', 'protocol': 'palm'}, 'test.prc', b'payload')
            handler.do_POST()
            handler.send_error.assert_not_called()
            selected = web.pending_send()
            original = Path(popen.call_args.args[0][-1])
            self.assertEqual(original.read_bytes(), b'payload')
            (Path(directory) / 'status.json').write_text('{"state":"error"}')
            retry = self.handler({'direction': 'send', 'protocol': 'palm', 'retry_token': selected['token']})
            retry.do_POST()
            retry.send_error.assert_not_called()
            self.assertEqual(Path(popen.call_args.args[0][-1]), original)
            self.assertEqual(original.read_bytes(), b'payload')

    def test_bad_retry_token_cannot_launch_transfer(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)), patch.object(web.subprocess, 'Popen') as popen:
            handler = self.handler({'direction': 'send', 'protocol': 'palm', 'retry_token': '../etc/passwd'})
            handler.do_POST()
            self.assertEqual(handler.send_error.call_args.args[0], 400)
            popen.assert_not_called()

    def test_pending_send_survives_failure_and_disappears_after_file_cleanup(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)):
            work = Path(directory) / 'work-012345abcdef'
            work.mkdir()
            asset = work / 'example.prc'
            asset.write_bytes(b'payload')
            web.remember_send(asset, 'palm')
            self.assertEqual(web.pending_send(), {'token': work.name, 'filename': asset.name, 'protocol': 'palm'})
            web.remember_send(asset, 'ymodem')
            self.assertEqual(web.pending_send()['protocol'], 'ymodem')
            self.assertEqual(asset.read_bytes(), b'payload')
            asset.unlink()
            self.assertIsNone(web.pending_send())

    def test_pending_send_rejects_traversal_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)):
            root = Path(directory)
            for token, name in [('../outside', 'x'), ('work-012345abcdef', '../x')]:
                (root / 'pending-send.json').write_text(json.dumps({'token': token, 'filename': name, 'protocol': 'palm'}))
                self.assertIsNone(web.pending_send())
            work = root / 'work-012345abcdef'
            work.mkdir()
            (work / 'link').symlink_to('/etc/hosts')
            web.remember_send(work / 'link', 'palm')
            self.assertIsNone(web.pending_send())

    def test_missing_or_corrupt_manifest_is_safe(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'TRANSFERS', Path(directory)):
            self.assertIsNone(web.pending_send())
            (Path(directory) / 'pending-send.json').write_text('not json')
            self.assertIsNone(web.pending_send())
