import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from web import proxy_web as page, web
from tests.test_wifi_web import Handler
from tests.test_wifi_routing import proxy


class ProxyWebTests(unittest.TestCase):
    def setUp(self):
        page._sessions.clear()
        self.save = Mock()
        self.apply_mode = Mock(return_value=True)

    def serve(self, handler):
        page.serve(handler, save=self.save, apply_mode=self.apply_mode)
        return handler

    def form(self, **values):
        self.serve(Handler())
        token = next(reversed(page._sessions))
        return {'session': token, 'csrf': page._sessions[token]['csrf'], 'mode': 'transparent',
                'page_size': '250000',
                'image_start': 'remember', 'image_preset': 'custom',
                'image_width': '200', 'image_height': '150', **values}

    def test_legacy_page_translations_and_current_values(self):
        for lang, label in [('nl', 'Webproxy instellen'), ('en', 'Web proxy settings')]:
            handler = Handler(language=lang)
            handler.settings.update(RETROMODEM_PROXY_PAGE_SIZE='750000', RETROMODEM_PROXY_IMAGE_WIDTH='600')
            self.serve(handler)
            self.assertEqual(handler.code, 200)
            self.assertIn(label, handler.text)
            self.assertIn('value="750000" selected', handler.text)
            self.assertIn('value="600"', handler.text)
            self.assertIn('name="mode"', handler.text)
            self.assertIn('Automatically send all web traffic through the proxy' if lang == 'en' else
                          'Stuur al het webverkeer automatisch over de proxy', handler.text)
            for forbidden in ('<script', '<style', '<button', 'onchange=', 'name="exceptions"'):
                self.assertNotIn(forbidden, handler.text)
            self.assertIn('no-store', handler.response_headers['Cache-Control'])
            self.assertIn('setup.retromodem', handler.text)
        self.save.assert_not_called()

    def test_presets_apply_server_side_and_replay_cannot_save(self):
        form = self.form(image_preset='600x180')
        handler = self.serve(Handler('POST', '/save', form=form))
        self.assertEqual(handler.code, 200)
        self.save.assert_called_once_with({'RETROMODEM_PROXY_PAGE_SIZE': '250000',
                                          'RETROMODEM_PROXY_IMAGE_START': 'remember',
                                          'RETROMODEM_PROXY_IMAGE_WIDTH': '600',
                                          'RETROMODEM_PROXY_IMAGE_HEIGHT': '180',
                                          'RETROMODEM_PROXY_MODE': 'transparent'})
        self.apply_mode.assert_not_called()
        self.assertEqual(self.serve(Handler('POST', '/save', form=form)).code, 403)
        self.assertEqual(self.save.call_count, 1)

    def test_invalid_choices_and_unknown_fields_do_not_save(self):
        for invalid in ({'page_size': '12345'}, {'image_start': 'bad'}, {'image_width': '15'},
                        {'image_height': '4097'}, {'image_preset': 'injected'}, {'mode': 'invalid'},
                        {'image_width': '<x>'}):
            handler = self.serve(Handler('POST', '/save', form=self.form(**invalid)))
            self.assertEqual(handler.code, 400)
        self.save.assert_not_called()

    def test_peer_origin_csrf_and_expiration(self):
        for peer, headers in [('192.168.0.50', {}), ('192.168.0.50', {'X-Retromodem-Client': '192.168.77.2'}), ('127.0.0.1', {})]:
            self.assertEqual(self.serve(Handler(peer=peer, headers=headers)).code, 403)
        self.assertEqual(self.serve(Handler(peer='127.0.0.1', headers={'X-Retromodem-Client': '192.168.77.2'})).code, 200)
        for headers in ({'Origin': 'http://evil.example'}, {'Origin': 'http://proxy.retromodem@evil.example'},
                        {'Transfer-Encoding': 'chunked'}):
            handler = self.serve(Handler('POST', '/save', form=self.form(), headers=headers))
            self.assertIn(handler.code, (400, 403))
        self.assertEqual(self.serve(Handler('POST', '/save', form=self.form(csrf='wrong'))).code, 403)
        form = self.form()
        page._sessions[form['session']]['expires'] = 0
        self.assertEqual(self.serve(Handler('POST', '/save', form=form)).code, 403)
        self.save.assert_not_called()

    def test_duplicate_and_oversized_forms_rejected(self):
        handler = Handler('POST', '/save')
        raw = b'session=a&session=b'
        handler.rfile = io.BytesIO(raw)
        handler.headers['Content-Length'] = str(len(raw))
        self.assertEqual(self.serve(handler).code, 400)
        handler = Handler('POST', '/save', headers={'Content-Length': '4097'})
        self.assertEqual(self.serve(handler).code, 400)

    def test_save_preserves_credentials_and_router_settings_without_service_calls(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(web, 'CONFIG', Path(directory) / 'config.env'), patch.object(web, 'run') as run:
            web.save_config({'RETROMODEM_WEB_PASSWORD': 'private-value', 'RETROMODEM_PROXY_MODE': 'manual',
                             'RETROMODEM_PROXY_EXCEPTIONS': 'example.com'})
            handler = Handler('POST', '/save', form=self.form(mode='manual'))
            handler.settings['RETROMODEM_PROXY_MODE'] = 'manual'
            page.serve(handler, save=web.save_config, apply_mode=lambda: True)
            result = web.load_config()
            self.assertEqual(result['RETROMODEM_WEB_PASSWORD'], 'private-value')
            self.assertEqual(result['RETROMODEM_PROXY_MODE'], 'manual')
            self.assertEqual(result['RETROMODEM_PROXY_EXCEPTIONS'], 'example.com')
            self.assertEqual(result['RETROMODEM_PROXY_PAGE_SIZE'], '250000')
            self.assertNotIn('private-value', handler.text)
            self.assertEqual(web.CONFIG.stat().st_mode & 0o777, 0o600)
            run.assert_not_called()

    def test_mode_change_applies_firewall_and_failure_rolls_back(self):
        handler = Handler('POST', '/save', form=self.form(mode='manual'))
        handler.settings['RETROMODEM_PROXY_MODE'] = 'transparent'
        self.serve(handler)
        self.assertEqual(handler.code, 200)
        self.apply_mode.assert_called_once_with()

        self.save.reset_mock()
        self.apply_mode.reset_mock()
        self.apply_mode.side_effect = [False, True]
        handler = Handler('POST', '/save', form=self.form(mode='manual'))
        handler.settings['RETROMODEM_PROXY_MODE'] = 'transparent'
        self.serve(handler)
        self.assertEqual(handler.code, 500)
        self.assertEqual(self.save.call_args_list[-1].args[0], {'RETROMODEM_PROXY_MODE': 'transparent'})
        self.assertEqual(self.apply_mode.call_count, 2)

    def test_sessions_are_bounded(self):
        for _ in range(70):
            self.serve(Handler())
        self.assertEqual(len(page._sessions), 64)

    def test_routing_for_get_and_post_and_dns_installer(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('address=/proxy.retromodem/192.168.77.1', (root / 'config/dnsmasq-retromodem.conf').read_text())
        self.assertIn('"$PROJECT_DIR/web/proxy_web.py"', (root / 'install.sh').read_text())
        for method in ('do_GET', 'do_POST'):
            handler = object.__new__(web.Handler)
            handler.config = lambda: {}
            handler.headers = {'Host': 'proxy.retromodem'}
            handler.serve_retro_proxy = Mock()
            getattr(handler, method)()
            handler.serve_retro_proxy.assert_called_once()
            relay = object.__new__(proxy.Handler)
            relay.path = 'http://proxy.retromodem/'
            relay.headers = {'Host': 'proxy.retromodem'}
            relay.client_address = ('192.168.77.2', 1)
            relay.relay_local = Mock()
            with patch.object(proxy, 'settings', return_value={}), patch.object(proxy, 'session_image_mode', return_value='inline'):
                getattr(relay, method)()
            relay.relay_local.assert_called_once_with(relay.path, 'proxy.retromodem')
