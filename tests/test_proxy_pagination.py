import importlib.util
import io
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pagination_proxy', ROOT / 'scripts/retroweb-proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
TOKEN = 'a' * 64


class ProxyPaginationTests(unittest.TestCase):
    def test_server_has_larger_handshake_queue(self):
        self.assertEqual(proxy.RetroWebHTTPServer.request_queue_size, 128)
    def test_settings_forwarded_to_core(self):
        response = io.BytesIO(b'<html>ok</html>')
        response.headers = {'Content-Type': 'text/html'}
        with patch.object(proxy.urllib.request, 'urlopen', return_value=response) as fetch:
            proxy._fetch_retroweb('https://example.org', {'RETROMODEM_PROXY_PAGE_SIZE': '12000', 'RETROMODEM_PROXY_PAGE_IMAGES': '2'})
        query = proxy.urllib.parse.parse_qs(proxy.urllib.parse.urlsplit(fetch.call_args.args[0].full_url).query)
        self.assertEqual(query['page_size'], ['12000'])
        self.assertEqual(query['page_images'], ['2'])

    def test_cache_separates_pagination_settings(self):
        proxy._cache.clear()
        proxy._pending.clear()
        self.addCleanup(proxy._cache.clear)
        with patch.object(proxy, '_fetch_retroweb', return_value=(b'ok', 'text/html')) as fetch:
            proxy.fetch_retroweb('https://example.org', {})
            proxy.fetch_retroweb('https://example.org', {})
            proxy.fetch_retroweb('https://example.org', {'RETROMODEM_PROXY_PAGE_SIZE': '12000'})
            proxy.fetch_retroweb('https://example.org', {'RETROMODEM_PROXY_PAGE_IMAGES': '2'})
        self.assertEqual(fetch.call_count, 3)

    def test_snapshot_links_keep_part_and_use_local_search_route(self):
        source = (f'<a href="http://127.0.0.1:8090/proxy.php?document={TOKEN}&amp;part=2">Next</a>'
                  f'<a href="http://127.0.0.1:8090/proxy.php?document={TOKEN}&amp;part=all">All</a>').encode()
        result = proxy.rewrite_retroweb_html(source).decode()
        self.assertIn(f'http://search.retromodem/__retroweb/page?document={TOKEN}&amp;part=2', result)
        self.assertIn('&amp;part=all', result)
        self.assertNotIn('127.0.0.1:8090', result)

    def test_snapshot_anchor_is_preserved(self):
        source = f'<a href="http://127.0.0.1:8090/proxy.php?document={TOKEN}&amp;part=2#section">Jump</a>'
        self.assertIn('&amp;part=2#section', proxy.rewrite_retroweb_html(source.encode()).decode())

    def test_original_website_query_is_not_confused_with_pagination(self):
        address = 'https://example.org/article?part=7&document=original&img=keep&encoded=%26'
        source = '<a href="http://127.0.0.1:8090/proxy.php?' + proxy.urllib.parse.urlencode({'url': address, 'img': 'inline'}) + '">Source</a>'
        result = proxy.rewrite_retroweb_html(source.encode()).decode()
        self.assertIn('http://example.org/article?part=7&amp;document=original&amp;img=keep&amp;encoded=%26', result)
        self.assertNotIn('/__retroweb/page', result)

    def test_invalid_snapshot_queries_rejected(self):
        for query in ('document=../file&part=1', f'document={TOKEN}&part=0',
                      f'document={TOKEN}&part=2&url=http://other', f'document={TOKEN}&part=2&part=3'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                proxy.pagination_parameters(query)

    def handler(self, path):
        handler = object.__new__(proxy.Handler)
        handler.path = path
        handler.headers = {'Host': 'search.retromodem'}
        handler.reply = lambda data, content_type, status=200: setattr(handler, 'result', (status, data))
        handler.send_error = lambda status, *args: setattr(handler, 'result', (status, b''))
        return handler

    def test_local_route_fetches_snapshot_instead_of_search_or_origin(self):
        handler = self.handler(f'/__retroweb/page?document={TOKEN}&part=2')
        with patch.object(proxy, 'settings', return_value={}), patch.object(proxy, 'fetch_retroweb_part', return_value=(b'part two', 'text/html')) as fetch, patch.object(proxy, 'search_page') as search:
            handler.do_GET()
        self.assertEqual(handler.result, (200, b'part two'))
        fetch.assert_called_once_with({'document': TOKEN, 'part': '2'})
        search.assert_not_called()

    def test_expired_snapshot_returns_404_not_a_successful_search_page(self):
        handler = self.handler(f'/__retroweb/page?document={TOKEN}&part=2')
        error = urllib.error.HTTPError('http://127.0.0.1', 404, 'expired', {}, io.BytesIO())
        with patch.object(proxy, 'settings', return_value={}), patch.object(proxy, 'fetch_retroweb_part', side_effect=error):
            handler.do_GET()
        self.assertEqual(handler.result[0], 404)
