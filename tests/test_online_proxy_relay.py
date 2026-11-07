import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('online_proxy', ROOT / 'scripts/retroweb-proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


class OnlineProxyRelayTests(unittest.TestCase):
    def test_exceptions_match_domain_and_subdomains_only(self):
        values = {'RETROMODEM_PROXY_EXCEPTIONS': 'example.org, old.example'}
        self.assertTrue(proxy.is_excluded('example.org', values))
        self.assertTrue(proxy.is_excluded('www.example.org', values))
        self.assertFalse(proxy.is_excluded('notexample.org', values))

    def test_retroweb_can_never_be_a_direct_exception(self):
        values = {'RETROMODEM_PROXY_EXCEPTIONS': 'retroweb.bjrno.com'}
        self.assertFalse(proxy.is_excluded('retroweb.bjrno.com', values))
        self.assertFalse(proxy.is_excluded('www.retroweb.bjrno.com', values))

    def relay(self, url, exceptions=''):
        handler = object.__new__(proxy.Handler)
        handler.path = url
        handler.command = 'GET'
        handler.headers = {'Host': 'ignored'}
        handler.rfile = io.BytesIO()
        handler.wfile = io.BytesIO()
        handler.send_response = lambda *_: None
        handler.send_header = lambda *_: None
        handler.end_headers = lambda: None
        response = type('Response', (), {'status': 200, 'reason': 'OK', 'getheaders': lambda self: [],
                                          'read': lambda self, size: b''})()
        with patch.object(proxy, 'settings', return_value={'RETROMODEM_PROXY_EXCEPTIONS': exceptions}), \
             patch.object(proxy.http.client, 'HTTPConnection') as connection:
            connection.return_value.getresponse.return_value = response
            handler.relay()
            return connection

    def test_normal_request_uses_public_proxy_and_absolute_url(self):
        connection = self.relay('http://example.org/page?q=1')
        connection.assert_called_once_with('retroweb.bjrno.com', 8081, timeout=60)
        self.assertEqual(connection.return_value.request.call_args.args[1], 'http://example.org/page?q=1')
        self.assertEqual(connection.return_value.request.call_args.kwargs['headers']['Host'], 'example.org')

    def test_exception_connects_directly(self):
        connection = self.relay('http://example.org/page?q=1', 'example.org')
        connection.assert_called_once_with('example.org', 80, timeout=60)
        self.assertEqual(connection.return_value.request.call_args.args[1], '/page?q=1')
