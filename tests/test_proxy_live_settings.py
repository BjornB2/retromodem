"""Real PHP requests must observe new image sizes without a process restart."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import unittest
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('php'), 'PHP unavailable')
class LivePHPSettingsTests(unittest.TestCase):
    def test_image_limits_reload_in_same_php_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copyfile(ROOT / 'proxy/retroweb/config.php', root / 'config.php')
            config = root / 'retromodem.env'
            config.write_text('RETROMODEM_PROXY_IMAGE_WIDTH=300\nRETROMODEM_PROXY_IMAGE_HEIGHT=180\n')
            (root / 'index.php').write_text("<?php require __DIR__.'/config.php'; echo json_encode([MAX_IMAGE_WIDTH,MAX_IMAGE_HEIGHT,getmypid()]);")
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            environment = dict(os.environ, RETROMODEM_CONFIG_FILE=str(config),
                               RETROMODEM_PROXY_IMAGE_WIDTH='200', RETROMODEM_PROXY_IMAGE_HEIGHT='150')
            server = subprocess.Popen(['php', '-S', f'127.0.0.1:{port}', '-t', str(root)],
                                      env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                def request():
                    for attempt in range(50):
                        try:
                            with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=2) as response:
                                return json.load(response)
                        except OSError:
                            if attempt == 49:
                                raise
                            time.sleep(0.02)
                first = request()
                self.assertEqual(first[:2], [300, 180])
                config.write_text("RETROMODEM_PROXY_IMAGE_WIDTH='144'\nRETROMODEM_PROXY_IMAGE_HEIGHT=120\n")
                changed = request()
                self.assertEqual(changed[:2], [144, 120])
                self.assertEqual(changed[2], first[2])
                config.write_text('RETROMODEM_PROXY_IMAGE_WIDTH=$(false)\nRETROMODEM_PROXY_IMAGE_HEIGHT=99999\n')
                invalid = request()
                self.assertEqual(invalid[:2], [200, 150])
                self.assertEqual(invalid[2], first[2])
            finally:
                server.terminate()
                server.wait(timeout=5)
