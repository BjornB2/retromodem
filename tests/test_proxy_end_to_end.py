"""Real Python HTTP bridge + real PHP snapshots, without external websites."""
import html
import http.client
import importlib.util
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('php'), 'PHP unavailable')
class ProxyEndToEndTests(unittest.TestCase):
    def test_toggle_and_asset_through_both_real_servers(self):
        spec = importlib.util.spec_from_file_location('end_to_end_proxy', ROOT / 'scripts/retroweb-proxy.py')
        proxy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(proxy)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copyfile(ROOT / 'proxy/retroweb/lib/PagePaginator.php', root / 'PagePaginator.php')
            (root / 'proxy.php').write_text('''<?php
require __DIR__.'/PagePaginator.php';
$p=new RetroWebPagePaginator(__DIR__.'/cache',100000);
$mode=$_GET['img']??'inline';
header('Content-Type: text/html; charset=iso-8859-1');
if(isset($_GET['document'])) {
  $r=$p->read($_GET['document'],$_GET['part'],$mode,$_GET['block']??null);
  http_response_code($r['status']); echo $r['html'];
} else {
  $c='<p>Article start</p>'.str_repeat('<p>Article text.</p>',1000);
  for($i=0;$i<49;$i++) $c.='<img src="http://127.0.0.1:8090/image_cruncher.php?url=https%3A%2F%2Fimages.example%2F'.$i.'.gif&amp;w=12&amp;h=9" alt="icon '.$i.'">';
  echo $p->first($c,'Fixture','','','http://127.0.0.1:8090',$mode);
}
''')
            (root / 'image_cruncher.php').write_text("<?php header('Content-Type: image/gif'); echo base64_decode('R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==');")
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            php = subprocess.Popen(['php', '-S', f'127.0.0.1:{port}', '-t', str(root)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            server = proxy.RetroWebHTTPServer(('127.0.0.1', 0), proxy.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            real_open = urllib.request.urlopen
            core_requests = []

            def core_open(request, **kwargs):
                url = request.full_url if isinstance(request, urllib.request.Request) else request
                if url.startswith('http://127.0.0.1:8090/'):
                    core_requests.append(url)
                    target = url.replace(':8090/', f':{port}/', 1)
                    request = urllib.request.Request(target, headers=dict(request.header_items())) if isinstance(request, urllib.request.Request) else target
                return real_open(request, **kwargs)

            def get(path, host='search.retromodem'):
                client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                try:
                    client.request('GET', path, headers={'Host': host})
                    response = client.getresponse()
                    body = response.read()
                    self.assertEqual(response.status, 200, body[:200])
                    return body.decode('iso-8859-1')
                finally:
                    client.close()
            try:
                for attempt in range(50):
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=1):
                            break
                    except OSError:
                        if attempt == 49: raise
                        time.sleep(0.02)
                with patch.object(proxy, 'settings', return_value={'RETROMODEM_PROXY_IMAGE_START': 'inline'}), patch.object(proxy.urllib.request, 'urlopen', side_effect=core_open):
                    first = get('http://origin.example/article', 'origin.example')
                    self.assertEqual(first.count('<img'), 49)
                    toggle = re.search(r'href="([^"]+)"[^>]*>As links</a>', first).group(1)
                    links = get(urllib.parse.urlsplit(html.unescape(toggle)).path + '?' + urllib.parse.urlsplit(html.unescape(toggle)).query)
                    self.assertNotIn('<img', links)
                    self.assertIn('icon 48', links)
                    self.assertEqual(sum('/proxy.php?url=' in request for request in core_requests), 1)
                    asset = re.search(r'href="(http://search.retromodem/__retroweb/image[^\"]+)"', links).group(1)
                    parsed = urllib.parse.urlsplit(html.unescape(asset))
                    image = get(parsed.path + '?' + parsed.query)
                    self.assertTrue(image.startswith('GIF89a'))
                    self.assertIn('&w=12&h=9', core_requests[-1])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
                php.terminate()
                php.wait(timeout=5)
