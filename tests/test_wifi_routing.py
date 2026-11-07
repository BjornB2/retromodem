from pathlib import Path
import unittest
from web import web

ROOT = Path(__file__).resolve().parents[1]


class WifiRoutingTests(unittest.TestCase):
    def test_dns_and_installer_have_local_route_and_modules(self):
        self.assertIn('address=/wifi.retromodem/192.168.77.1', (ROOT / 'config/dnsmasq-retromodem.conf').read_text())
        install = (ROOT / 'install.sh').read_text()
        for name in ('wifi_web.py', 'wifi_network.py'):
            self.assertIn('"$PROJECT_DIR/web/' + name + '"', install)

    def test_direct_web_routes_for_both_methods(self):
        for method in ('do_GET', 'do_POST'):
            handler = object.__new__(web.Handler)
            handler.config = lambda: {}
            handler.headers = {'Host': 'wifi.retromodem'}
            handler.serve_retro_wifi = lambda: setattr(handler, 'routed', True)
            getattr(handler, method)()
            self.assertTrue(handler.routed)
