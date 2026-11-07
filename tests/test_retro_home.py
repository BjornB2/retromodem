import io
import unittest
from pathlib import Path
from web import web


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
        self.assertLess(page.index('retroweb.bjrno.com'), page.index('chatgpt.retromodem'))
        self.assertLess(page.index('chatgpt.retromodem'), page.index('setup.retromodem'))
        setup = self.render('setup.retromodem')
        self.assertIn('http://wifi.retromodem/', setup)
        self.assertIn('http://start.retromodem/', setup)
        self.assertNotIn('<script', setup)
        self.assertIn('Settings', self.render('setup.retromodem', 'en'))

    def test_removed_local_proxy_pages_are_not_routed(self):
        routes = (Path(web.__file__).parents[1] / 'config/dnsmasq-retromodem.conf').read_text()
        self.assertNotIn('search.retromodem', routes)
        self.assertNotIn('proxy.retromodem', routes)
