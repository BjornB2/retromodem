import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
from web import web

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wifi_route_proxy', ROOT / 'scripts/retroweb-proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class WifiRoutingTests(unittest.TestCase):
    def test_dns_and_installer_have_local_route_and_modules(self):
        self.assertIn('address=/wifi.retromodem/192.168.77.1', (ROOT / 'config/dnsmasq-retromodem.conf').read_text())
        install = (ROOT / 'install.sh').read_text()
        for name in ('wifi_web.py', 'wifi_network.py'):
            self.assertIn('"$PROJECT_DIR/web/' + name + '"', install)
            self.assertIn('usr/local/lib/retromodem/' + name, install)

    def test_direct_web_routes_before_admin_ui_for_both_methods(self):
        for method in ('do_GET', 'do_POST'):
            handler = object.__new__(web.Handler)
            handler.config = lambda: {}
            handler.headers = {'Host': 'wifi.retromodem'}
            handler.serve_retro_wifi = lambda: setattr(handler, 'routed', True)
            getattr(handler, method)()
            self.assertTrue(handler.routed)

    def test_proxy_routes_get_and_post_before_upstream_or_search(self):
        for method in ('do_GET', 'do_POST'):
            handler = object.__new__(proxy.Handler)
            handler.path = 'http://wifi.retromodem/scan'
            handler.headers = {'Host': 'wifi.retromodem'}
            handler.client_address = ('192.168.77.2', 1234)
            handler.relay_local = lambda url, host: setattr(handler, 'relayed', host)
            with patch.object(proxy, 'settings', return_value={}), patch.object(proxy, 'session_image_mode', return_value='inline'):
                getattr(handler, method)()
            self.assertEqual(handler.relayed, 'wifi.retromodem')

    def test_relay_replaces_forged_peer_and_preserves_origin(self):
        handler = object.__new__(proxy.Handler)
        handler.headers = {'Content-Length': '0', 'X-Retromodem-Client': '192.168.77.2',
                           'Origin': 'http://evil.example'}
        handler.client_address = ('192.168.0.42', 1234)
        handler.command = 'GET'
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        handler.send_response = lambda *_: None
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None
        with patch.object(proxy.http.client, 'HTTPConnection') as connection:
            response = connection.return_value.getresponse.return_value
            response.status = 403
            response.read1.return_value = b''
            handler.relay_local('http://wifi.retromodem/', 'wifi.retromodem')
            headers = connection.return_value.request.call_args.kwargs['headers']
            self.assertEqual(headers['X-Retromodem-Client'], '192.168.0.42')
            self.assertEqual(headers['Origin'], 'http://evil.example')

    def test_oversize_wifi_relay_rejected_before_read(self):
        handler = object.__new__(proxy.Handler)
        handler.headers = {'Content-Length': '4097'}
        handler.send_error = lambda code: setattr(handler, 'error', code)
        handler.relay_local('http://wifi.retromodem/connect', 'wifi.retromodem')
        self.assertEqual(handler.error, 413)
