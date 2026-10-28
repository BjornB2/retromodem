import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('pagination_proxy', ROOT / 'scripts/retroweb-proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
TOKEN = 'a' * 64


class ProxyPaginationTests(unittest.TestCase):
    def setUp(self):
        proxy._image_sessions.clear()
        self.addCleanup(proxy._image_sessions.clear)
        preferences = tempfile.TemporaryDirectory()
        self.addCleanup(preferences.cleanup)
        patcher = patch.object(proxy, 'IMAGE_CHOICE_FILE', Path(preferences.name) / 'choice.json')
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fixed_start_mode_applies_once_per_ppp_session(self):
        values = {'RETROMODEM_PROXY_IMAGE_START': 'inline'}
        with patch.object(proxy, 'image_session_key', return_value=('192.168.77.2', '11')):
            self.assertEqual(proxy.session_image_mode(values, '192.168.77.2'), 'inline')
            self.assertEqual(proxy.session_image_mode(values, '192.168.77.2', 'links'), 'links')
            self.assertEqual(proxy.session_image_mode(dict(values), '192.168.77.2'), 'links')
        with patch.object(proxy, 'image_session_key', return_value=('192.168.77.2', '12')):
            self.assertEqual(proxy.session_image_mode(values, '192.168.77.2'), 'inline')

    def test_links_start_and_legacy_default(self):
        self.assertEqual(proxy.session_image_mode({'RETROMODEM_PROXY_IMAGE_START': 'links'}, '192.168.77.2'), 'links')
        self.assertEqual(proxy.session_image_mode({'RETROMODEM_PROXY_IMAGE_MODE': 'links'}, '192.168.0.2'), 'links')

    def test_remembered_explicit_choice_survives_process_session(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(proxy, 'IMAGE_CHOICE_FILE', Path(folder) / 'choice.json'):
            values = {'RETROMODEM_PROXY_IMAGE_START': 'remember'}
            self.assertEqual(proxy.session_image_mode(values, '192.168.77.2'), 'inline')
            self.assertFalse(proxy.IMAGE_CHOICE_FILE.exists())
            self.assertEqual(proxy.session_image_mode(values, '192.168.77.2', 'links'), 'links')
            self.assertEqual(json.loads(proxy.IMAGE_CHOICE_FILE.read_text()), {'mode': 'links'})
            self.assertEqual(proxy.IMAGE_CHOICE_FILE.stat().st_mode & 0o777, 0o600)
            proxy._image_sessions.clear()
            self.assertEqual(proxy.session_image_mode(values, '192.168.77.2'), 'links')
            self.assertEqual(proxy.session_image_mode(values, '192.168.77.2', 'inline'), 'inline')
            self.assertEqual(json.loads(proxy.IMAGE_CHOICE_FILE.read_text()), {'mode': 'inline'})

    def test_no_preference_persistence_for_normal_requests_or_local_checks(self):
        with patch.object(proxy, 'remember_image_mode') as persist:
            proxy.session_image_mode({'RETROMODEM_PROXY_IMAGE_START': 'remember'}, '127.0.0.1')
            proxy.session_image_mode({'RETROMODEM_PROXY_IMAGE_START': 'inline'}, '127.0.0.1', 'links')
            proxy.session_image_mode({'RETROMODEM_PROXY_IMAGE_START': 'remember'}, '192.168.77.2')
        persist.assert_not_called()

    def test_last_choice_survives_policy_change_but_fixed_start_still_wins(self):
        fixed = {'RETROMODEM_PROXY_IMAGE_START': 'inline'}
        remembered = {'RETROMODEM_PROXY_IMAGE_START': 'remember'}
        with patch.object(proxy, 'image_session_key', return_value=('192.168.77.2', '11')):
            self.assertEqual(proxy.session_image_mode(fixed, '192.168.77.2'), 'inline')
            proxy.session_image_mode(fixed, '192.168.77.2', 'links')
            self.assertEqual(json.loads(proxy.IMAGE_CHOICE_FILE.read_text()), {'mode': 'links'})
        with patch.object(proxy, 'image_session_key', return_value=('192.168.77.2', '12')):
            self.assertEqual(proxy.session_image_mode(remembered, '192.168.77.2'), 'links')
        with patch.object(proxy, 'image_session_key', return_value=('192.168.77.2', '13')):
            self.assertEqual(proxy.session_image_mode(fixed, '192.168.77.2'), 'inline')
            self.assertEqual(json.loads(proxy.IMAGE_CHOICE_FILE.read_text()), {'mode': 'links'})

    def test_untrusted_forwarded_identity_is_ignored(self):
        handler = self.handler('/')
        handler.client_address = ('192.168.77.2', 999)
        handler.headers['X-Retromodem-Client'] = '192.168.0.10'
        self.assertEqual(proxy.image_client(handler), '192.168.77.2')
        handler.client_address = ('127.0.0.1', 999)
        self.assertEqual(proxy.image_client(handler), '192.168.0.10')
        handler.headers['X-Retromodem-Client'] = 'not an address'
        self.assertEqual(proxy.image_client(handler), '127.0.0.1')

    def test_bad_preference_file_is_ignored_without_following_symlink(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(proxy, 'IMAGE_CHOICE_FILE', Path(folder) / 'choice.json'):
            target = Path(folder) / 'private.json'
            target.write_text('{"mode":"links"}')
            proxy.IMAGE_CHOICE_FILE.symlink_to(target)
            self.assertEqual(proxy.remembered_image_mode(), 'inline')
            with self.assertRaises(OSError):
                proxy.remember_image_mode('inline')
            self.assertEqual(target.read_text(), '{"mode":"links"}')
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

    def test_snapshot_variant_and_logical_position_are_preserved(self):
        source = f'<a href="http://127.0.0.1:8090/proxy.php?document={TOKEN}&amp;part=7&amp;img=links&amp;block=b37#b37">As links</a>'
        result = proxy.rewrite_retroweb_html(source.encode()).decode()
        self.assertIn(f'/__retroweb/page?document={TOKEN}&amp;part=7&amp;img=links&amp;block=b37#b37', result)
        self.assertEqual(proxy.pagination_parameters(f'document={TOKEN}&part=7&img=links&block=b37'),
                         {'document': TOKEN, 'part': '7', 'img': 'links', 'block': 'b37'})

    def test_navigation_with_image_choice_is_not_removed(self):
        source = f'<p><a href="http://127.0.0.1:8090/index.php">RetroWEB</a> Images: <a href="http://127.0.0.1:8090/proxy.php?document={TOKEN}&amp;part=1&amp;img=links">As links</a></p><hr><p>Body</p>'
        result = proxy.rewrite_retroweb_html(source.encode()).decode()
        self.assertIn('Images:', result)
        self.assertIn('As links', result)
        self.assertIn('/__retroweb/page?', result)

    def test_asset_urls_keep_both_display_dimensions(self):
        remote = 'https://example.org/photo.jpg?part=2&document=source'
        query = proxy.urllib.parse.urlencode({'url': remote, 'w': '16', 'h': '12'})
        source = '<img src="http://127.0.0.1:8090/image_cruncher.php?' + query + '">'
        result = proxy.rewrite_retroweb_html(source.encode()).decode()
        self.assertIn('http://search.retromodem/__retroweb/image?', result)
        self.assertIn('&amp;w=16&amp;h=12', result)
        self.assertIn('part%3D2%26document%3Dsource', result)

    def test_invalid_asset_reference_is_not_rewritten_as_origin_url(self):
        source = '<img src="http://127.0.0.1:8090/image_cruncher.php?url=javascript%3Aalert%281%29&w=16">'
        self.assertIn('#invalid-image-reference', proxy.rewrite_retroweb_html(source.encode()).decode())

    def test_invalid_asset_parameters_are_rejected(self):
        for query in ('url=ftp%3A%2F%2Fexample.org%2Fa', 'url=http%3A%2F%2Fu%3Ap%40example.org%2Fa',
                      'url=https%3A%2F%2Fexample.org%2Fa&w=0', 'url=https%3A%2F%2Fexample.org%2Fa&h=4097',
                      'url=https%3A%2F%2Fexample.org%2Fa&w=16&w=32', 'url=https%3A%2F%2Fexample.org%2Fa&other=1',
                      'url=https%3A%2F%2Fexample.org%2Fa%0aevil', 'url='):
            with self.subTest(query=query), self.assertRaises(ValueError):
                proxy.image_parameters(query)

    def test_original_website_query_is_not_confused_with_pagination(self):
        address = 'https://example.org/article?part=7&document=original&img=keep&encoded=%26'
        source = '<a href="http://127.0.0.1:8090/proxy.php?' + proxy.urllib.parse.urlencode({'url': address, 'img': 'inline'}) + '">Source</a>'
        result = proxy.rewrite_retroweb_html(source.encode()).decode()
        self.assertIn('http://example.org/article?part=7&amp;document=original&amp;img=keep&amp;encoded=%26', result)
        self.assertNotIn('/__retroweb/page', result)

    def test_invalid_snapshot_queries_rejected(self):
        for query in ('document=../file&part=1', f'document={TOKEN}&part=0',
                      f'document={TOKEN}&part=2&url=http://other', f'document={TOKEN}&part=2&part=3',
                      f'document={TOKEN}&part=2&img=other', f'document={TOKEN}&part=2&img=inline&img=links',
                      f'document={TOKEN}&part=2&block=../../', f'document={TOKEN}&part=2&block=b0'):
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

    def test_successful_variant_selection_carries_into_next_origin_request(self):
        handler = self.handler(f'/__retroweb/page?document={TOKEN}&part=2&img=links')
        handler.client_address = ('192.168.77.2', 999)
        with patch.object(proxy, 'settings', return_value={'RETROMODEM_PROXY_IMAGE_START': 'inline'}), patch.object(proxy, 'fetch_retroweb_part', return_value=(b'part two', 'text/html')):
            handler.do_GET()
        handler.path = 'http://example.org/article'
        handler.reply_retroweb_live = lambda url, values: setattr(handler, 'chosen_mode', values['RETROMODEM_PROXY_IMAGE_MODE'])
        with patch.object(proxy, 'settings', return_value={'RETROMODEM_PROXY_IMAGE_START': 'inline'}), patch.object(proxy, 'is_excluded', return_value=False):
            handler.do_GET()
        self.assertEqual(handler.chosen_mode, 'links')

    def test_failed_variant_request_does_not_change_current_choice(self):
        handler = self.handler(f'/__retroweb/page?document={TOKEN}&part=2&img=links')
        handler.client_address = ('192.168.77.2', 999)
        error = urllib.error.HTTPError('http://127.0.0.1', 404, 'expired', {}, io.BytesIO())
        with patch.object(proxy, 'settings', return_value={'RETROMODEM_PROXY_IMAGE_START': 'inline'}), patch.object(proxy, 'fetch_retroweb_part', side_effect=error):
            handler.do_GET()
        self.assertEqual(proxy.session_image_mode({'RETROMODEM_PROXY_IMAGE_START': 'inline'}, '192.168.77.2'), 'inline')

    def test_expired_snapshot_returns_404_not_a_successful_search_page(self):
        handler = self.handler(f'/__retroweb/page?document={TOKEN}&part=2')
        error = urllib.error.HTTPError('http://127.0.0.1', 404, 'expired', {}, io.BytesIO())
        with patch.object(proxy, 'settings', return_value={}), patch.object(proxy, 'fetch_retroweb_part', side_effect=error):
            handler.do_GET()
        self.assertEqual(handler.result[0], 404)

    def test_local_asset_route_fetches_image_without_search_or_simplification(self):
        query = proxy.urllib.parse.urlencode({'url': 'https://example.org/photo.jpg', 'w': '16', 'h': '12'})
        handler = self.handler('/__retroweb/image?' + query)
        with patch.object(proxy, 'settings', return_value={}), patch.object(proxy, 'fetch_retroweb_image', return_value=(b'GIF89a', 'image/gif')) as fetch, patch.object(proxy, 'search_page') as search, patch.object(proxy, 'fetch_retroweb') as simplify:
            handler.do_GET()
        self.assertEqual(handler.result, (200, b'GIF89a'))
        fetch.assert_called_once_with({'url': 'https://example.org/photo.jpg', 'w': '16', 'h': '12'})
        search.assert_not_called()
        simplify.assert_not_called()

    def test_asset_fetch_uses_image_endpoint_directly_and_preserves_bytes(self):
        response = io.BytesIO(b'GIF89a\x00\xff')
        response.headers = {'Content-Type': 'image/gif'}
        with patch.object(proxy.urllib.request, 'urlopen', return_value=response) as fetch:
            result = proxy.fetch_retroweb_image({'url': 'https://example.org/photo.jpg', 'w': '16', 'h': '12'})
        self.assertEqual(result, (b'GIF89a\x00\xff', 'image/gif'))
        endpoint = proxy.urllib.parse.urlsplit(fetch.call_args.args[0])
        self.assertEqual(endpoint.path, '/image_cruncher.php')
        self.assertEqual(proxy.urllib.parse.parse_qs(endpoint.query)['w'], ['16'])
        self.assertEqual(proxy.urllib.parse.parse_qs(endpoint.query)['h'], ['12'])

    def test_asset_body_size_is_bounded(self):
        response = io.BytesIO(b'123456')
        response.headers = {'Content-Type': 'image/gif'}
        with patch.object(proxy, 'MAX_DOCUMENT', 5), patch.object(proxy.urllib.request, 'urlopen', return_value=response):
            with self.assertRaisesRegex(ValueError, 'processed image too large'):
                proxy.fetch_retroweb_image({'url': 'https://example.org/photo.jpg'})

    def test_origin_path_resembling_asset_route_does_not_become_internal_route(self):
        handler = self.handler('http://example.org/__retroweb/image?url=original&w=source')
        with patch.object(proxy, 'settings', return_value={}), patch.object(proxy, 'fetch_retroweb_image') as image, patch.object(proxy, 'is_excluded', return_value=False):
            handler.reply_retroweb_live = lambda url, values: setattr(handler, 'origin', url)
            handler.do_GET()
        image.assert_not_called()
        self.assertEqual(handler.origin, 'https://example.org/__retroweb/image?url=original&w=source')
