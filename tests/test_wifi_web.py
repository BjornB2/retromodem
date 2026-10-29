import html
import io
import re
import unittest
import urllib.parse
from unittest.mock import Mock, patch

from web import wifi_web


class Handler:
    def __init__(self, method='GET', path='/', peer='192.168.77.2', form=None,
                 language='nl', authenticated=False, headers=None):
        self.command = method
        self.path = path
        self.client_address = (peer, 10000)
        self.headers = dict(headers or {})
        self.settings = {'RETROMODEM_LANGUAGE': language}
        self.auth = authenticated
        body = urllib.parse.urlencode(form or {}, encoding='iso-8859-1').encode()
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.response_headers = {}
        if method == 'POST':
            self.headers.setdefault('Content-Length', str(len(body)))
            self.headers.setdefault('Content-Type', 'application/x-www-form-urlencoded')

    def config(self):
        return self.settings

    def authenticated(self, config):
        return self.auth

    def send_response(self, code):
        self.code = code

    def send_header(self, key, value):
        self.response_headers[key] = value

    def end_headers(self):
        pass

    @property
    def text(self):
        return self.wfile.getvalue().decode('latin1')


class WifiWebTests(unittest.TestCase):
    def setUp(self):
        wifi_web._sessions.clear()
        self.status = Mock(return_value={'state': 'connected', 'ssid': 'Current <wifi>'})
        self.scan = Mock(return_value=[('New network', 80, 'WPA2'), ('Cafe', 60, 'open')])
        self.connect = Mock()

    def serve(self, handler):
        wifi_web.serve(handler, status=self.status, scan=self.scan, connect=self.connect)
        return handler

    def csrf(self, token, path='/scan'):
        return wifi_web._sessions[token]['actions'][path]

    def session(self, **kwargs):
        handler = self.serve(Handler(**kwargs))
        token = re.search(r'name="session" value="([0-9a-f]+)"', handler.text)[1]
        return token, handler

    def scanned(self):
        token, _ = self.session()
        handler = self.serve(Handler('POST', '/scan', form={'session': token, 'csrf': self.csrf(token)}))
        choice = re.search(r'<option value="([0-9a-f]+)"', handler.text)[1]
        return token, choice, handler

    def test_initial_page_shows_status_without_scanning_and_is_legacy_html(self):
        _, handler = self.session()
        self.assertEqual(handler.code, 200)
        self.assertIn('Verbonden met Current &lt;wifi&gt;', handler.text)
        self.assertIn('Scan netwerken', handler.text)
        self.assertNotIn('name="password"', handler.text)
        for forbidden in ('<script', '<style', '<button', '<label', '<meta', 'Set-Cookie'):
            self.assertNotIn(forbidden, handler.text)
        self.scan.assert_not_called()
        self.connect.assert_not_called()
        self.assertIn('no-store', handler.response_headers['Cache-Control'])
        self.assertEqual(handler.response_headers['Referrer-Policy'], 'no-referrer')

    def test_hotspot_not_mistaken_for_external_connection(self):
        self.status.return_value = {'state': 'hotspot', 'ssid': 'retromodem'}
        _, handler = self.session()
        self.assertIn('Hotspot actief; geen externe wifi-verbinding', handler.text)
        self.assertNotIn('Verbonden met retromodem', handler.text)

    def test_failed_job_preserves_actual_restored_connection_and_translates_notice(self):
        self.status.return_value = {'state': 'failed', 'network_state': 'connected',
                                    'ssid': 'Restored', 'message': 'INTERNAL-DIAGNOSTIC password=SECRET'}
        _, handler = self.session(language='en')
        self.assertIn('Connected to Restored', handler.text)
        self.assertIn('The last connection attempt failed', handler.text)
        self.assertNotIn('INTERNAL-DIAGNOSTIC', handler.text)
        self.assertNotIn('SECRET', handler.text)
        self.status.return_value = {'state': 'failed', 'network_state': 'hotspot', 'ssid': 'retromodem'}
        _, handler = self.session()
        self.assertIn('Hotspot actief; geen externe wifi-verbinding', handler.text)
        self.assertIn('laatste verbindingspoging is mislukt', handler.text)

    def test_connecting_job_keeps_actual_network_visible(self):
        self.status.return_value = {'state': 'connecting', 'network_state': 'connected', 'ssid': 'Previous'}
        _, handler = self.session()
        self.assertIn('Verbonden met Previous', handler.text)
        self.assertIn('Bezig met verbinden', handler.text)

    def test_english_and_html_status_escaping(self):
        _, handler = self.session(language='en')
        self.assertIn('Current connection: Connected to', handler.text)
        self.assertIn('Scan networks', handler.text)
        self.assertNotIn('Scan netwerken', handler.text)

    def test_access_gate_does_not_trust_lan_header_or_plain_loopback(self):
        for peer in ('192.168.0.50', '127.0.0.1', '::1'):
            handler = self.serve(Handler(peer=peer))
            self.assertEqual(handler.code, 403)
        spoof = self.serve(Handler(peer='192.168.0.50', headers={'X-Retromodem-Client': '192.168.77.2'}))
        self.assertEqual(spoof.code, 403)
        self.status.assert_not_called()

    def test_trusted_loopback_relay_and_authenticated_admin(self):
        for peer, headers, auth in [('127.0.0.1', {'X-Retromodem-Client': '192.168.77.2'}, False),
                                    ('192.168.0.50', {}, True)]:
            self.assertEqual(self.serve(Handler(peer=peer, headers=headers, authenticated=auth)).code, 200)

    def test_scan_uses_opaque_ids_for_unicode_and_preserves_ssid_spaces(self):
        self.scan.return_value = [(' 日本 <wifi> ', 80, 'WPA2'), ('日本', 70, 'WPA2')]
        token, choice, handler = self.scanned()
        self.assertIn('&#26085;&#26412; &lt;wifi&gt;', handler.text)
        self.assertNotIn('value=" 日本', handler.text)
        sent = self.serve(Handler('POST', '/connect', form={'session': token, 'csrf': self.csrf(token, '/connect'),
                                                          'network': choice, 'password': 'correct horse'}))
        self.assertEqual(sent.code, 200)
        self.connect.assert_called_once_with({'RETROMODEM_LANGUAGE': 'nl'}, ' 日本 <wifi> ', 'correct horse')
        self.assertNotIn('correct horse', sent.text)

    def test_password_never_echoed_on_backend_error(self):
        token, choice, _ = self.scanned()
        self.connect.side_effect = RuntimeError('password=SECRET-PASSWORD')
        handler = self.serve(Handler('POST', '/connect', form={'session': token, 'csrf': self.csrf(token, '/connect'),
                                                             'network': choice, 'password': 'SECRET-PASSWORD'}))
        self.assertNotIn('SECRET-PASSWORD', handler.text)
        self.assertIn('Verbinden kon niet worden gestart', handler.text)

    def test_csrf_missing_wrong_or_nonascii_does_not_scan(self):
        token, _ = self.session()
        for csrf in ('', 'wrong', 'é'):
            handler = self.serve(Handler('POST', '/scan', form={'session': token, 'csrf': csrf}))
            self.assertEqual(handler.code, 403)
        self.scan.assert_not_called()

    def test_session_is_peer_bound_and_expires(self):
        token, _ = self.session()
        other = self.serve(Handler('POST', '/scan', peer='192.168.0.50', authenticated=True,
                                  form={'session': token, 'csrf': self.csrf(token)}))
        self.assertEqual(other.code, 403)
        with patch.object(wifi_web.time, 'monotonic', return_value=wifi_web._sessions[token]['expires'] + 1):
            expired = self.serve(Handler(path='/status?session=' + token))
            self.assertEqual(expired.code, 410)
        self.scan.assert_not_called()

    def test_refresh_get_and_unknown_routes_do_not_start_actions(self):
        token, _ = self.session()
        self.assertEqual(self.serve(Handler(path='/status?session=' + token)).code, 200)
        for path in ('/scan', '/connect', '/missing'):
            self.assertEqual(self.serve(Handler(path=path)).code, 404)
        self.scan.assert_not_called()
        self.connect.assert_not_called()

    def test_scan_errors_empty_and_duplicate_results(self):
        token, _ = self.session()
        self.scan.side_effect = RuntimeError('internal diagnostic')
        error = self.serve(Handler('POST', '/scan', form={'session': token, 'csrf': self.csrf(token)}))
        self.assertIn('Scannen is niet gelukt', error.text)
        self.assertNotIn('internal diagnostic', error.text)
        self.assertIn('WIFI-SCAN-FAILED', error.text)
        self.scan.side_effect = None
        self.scan.return_value = []
        empty = self.serve(Handler('POST', '/scan', form={'session': token, 'csrf': self.csrf(token)}))
        self.assertIn('Geen netwerken gevonden', empty.text)
        self.scan.return_value = [('same', 50, 'WPA2'), ('same', 40, 'WPA2'), ('', 20, 'open')]
        scanned = self.serve(Handler('POST', '/scan', form={'session': token, 'csrf': self.csrf(token)}))
        self.assertEqual(scanned.text.count('<option'), 1)

    def test_connect_consumes_network_choices_and_no_password_is_stored(self):
        token, choice, _ = self.scanned()
        form = {'session': token, 'csrf': self.csrf(token, '/connect'), 'network': choice, 'password': 'TOP-SECRET'}
        self.assertEqual(self.serve(Handler('POST', '/connect', form=form)).code, 200)
        self.assertEqual(self.serve(Handler('POST', '/connect', form=form)).code, 400)
        self.connect.assert_called_once()
        self.assertNotIn('TOP-SECRET', repr(wifi_web._sessions))

    def test_enterprise_and_wep_cannot_be_connected(self):
        for security in ('WPA2 802.1X', 'WEP', 'WPA3', 'OWE', 'WPA2-EAP'):
            self.scan.return_value = [('unsupported', 80, security)]
            token, choice, _ = self.scanned()
            handler = self.serve(Handler('POST', '/connect', form={'session': token, 'csrf': self.csrf(token, '/connect'),
                                                                 'network': choice, 'password': 'not-used'}))
            self.assertEqual(handler.code, 400)
        self.connect.assert_not_called()

    def test_body_bounds_content_type_and_duplicate_fields(self):
        token, _ = self.session()
        for headers in ({'Content-Length': '4097'}, {'Content-Length': '-1'},
                        {'Content-Length': 'no'}, {'Content-Type': 'text/plain'}):
            handler = self.serve(Handler('POST', '/scan', form={'session': token, 'csrf': self.csrf(token)}, headers=headers))
            self.assertEqual(handler.code, 400)
        handler = Handler('POST', '/scan')
        raw = ('session=' + token + '&csrf=' + token + '&csrf=' + token).encode()
        handler.rfile = io.BytesIO(raw)
        handler.headers['Content-Length'] = str(len(raw))
        self.assertEqual(self.serve(handler).code, 400)
        self.scan.assert_not_called()

    def test_sessions_and_scan_choices_are_bounded(self):
        for _ in range(70):
            self.session()
        self.assertEqual(len(wifi_web._sessions), wifi_web.MAX_SESSIONS)
        self.scan.return_value = [('network' + str(i), 80, 'WPA2') for i in range(100)]
        _, _, handler = self.scanned()
        self.assertEqual(handler.text.count('<option'), 64)

    def test_action_tokens_cannot_be_reused_for_other_post_path(self):
        token, choice, _ = self.scanned()
        handler = self.serve(Handler('POST', '/connect', form={'session': token, 'csrf': self.csrf(token),
                                                             'network': choice, 'password': 'not-used'}))
        self.assertEqual(handler.code, 403)
        self.connect.assert_not_called()

    def test_origin_is_optional_but_mismatches_are_rejected(self):
        token, _ = self.session()
        form = {'session': token, 'csrf': self.csrf(token)}
        for origin in ('http://evil.example', 'null', 'http://wifi.retromodem.evil/',
                       'http://wifi.retromodem:9999', 'http://wifi.retromodem/other',
                       'http://user@wifi.retromodem'):
            handler = self.serve(Handler('POST', '/scan', form=form, headers={'Origin': origin}))
            self.assertEqual(handler.code, 403, origin)
        self.scan.assert_not_called()
        for origin in ('http://wifi.retromodem', 'http://wifi.retromodem:80'):
            handler = self.serve(Handler('POST', '/scan', form=form, headers={'Origin': origin}))
            self.assertEqual(handler.code, 200)
