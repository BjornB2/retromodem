import io
import unittest
from unittest.mock import patch
from web import web
from tests.test_wifi_routing import proxy


class RetroHomeTests(unittest.TestCase):
    def render(self, host, language='nl'):
        handler = object.__new__(web.Handler)
        handler.config = lambda: {'RETROMODEM_LANGUAGE': language}
        handler.headers = {'Host': host}
        handler.wfile = io.BytesIO()
        handler.send_response = lambda code: self.assertEqual(code, 200)
        handler.send_header = lambda *args: None
        handler.end_headers = lambda: None
        handler.do_GET()
        return handler.wfile.getvalue().decode('iso-8859-1')

    def test_start_and_setup_links(self):
        page = self.render('start.retromodem')
        self.assertLess(page.index('search.retromodem'), page.index('chatgpt.retromodem'))
        self.assertLess(page.index('chatgpt.retromodem'), page.index('setup.retromodem'))
        setup = self.render('setup.retromodem')
        self.assertIn('http://wifi.retromodem/', setup)
        self.assertIn('http://start.retromodem/', setup)
        self.assertNotIn('<script', setup)
        self.assertIn('Settings', self.render('setup.retromodem', 'en'))

    def test_proxy_routes_local_hubs(self):
        for host in ('start.retromodem', 'setup.retromodem'):
            handler = object.__new__(proxy.Handler)
            handler.path = 'http://' + host + '/'
            handler.headers = {'Host': host}
            handler.client_address = ('192.168.77.2', 1)
            handler.relay_local = lambda url, target: setattr(handler, 'target', target)
            with patch.object(proxy, 'settings', return_value={}), patch.object(proxy, 'session_image_mode', return_value='inline'):
                handler.do_GET()
            self.assertEqual(handler.target, host)
