import io
import unittest
from unittest.mock import patch
import urllib.error
from web import web


class SearchRelayTests(unittest.TestCase):
    def handler(self):
        handler = object.__new__(web.Handler)
        handler.path = '/__retroweb/page?document=' + 'a' * 64 + '&part=1&img=links'
        handler.headers = {'Host': 'search.retromodem', 'X-Retromodem-Client': '192.168.77.99'}
        handler.client_address = ('192.168.77.2', 10000)
        handler.config = lambda: {}
        handler.wfile = io.BytesIO()
        handler.send_response = lambda status: setattr(handler, 'status', status)
        handler.send_error = lambda status, *_: setattr(handler, 'status', status)
        handler.response_headers = {}
        handler.send_header = lambda key, value: handler.response_headers.update({key: value})
        handler.end_headers = lambda: None
        return handler

    def test_relay_forwards_actual_peer_not_untrusted_header(self):
        handler = self.handler()
        response = io.BytesIO(b'<html>links</html>')
        response.headers = {'Content-Type': 'text/html'}
        with patch.object(web.urllib.request, 'urlopen', return_value=response) as fetch:
            handler.do_GET()
        request = fetch.call_args.args[0]
        self.assertEqual(request.get_header('X-retromodem-client'), '192.168.77.2')
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.wfile.getvalue(), b'<html>links</html>')
        self.assertIn('no-cache', handler.response_headers['Cache-Control'])
        self.assertEqual(handler.response_headers['Pragma'], 'no-cache')
        self.assertEqual(handler.response_headers['Expires'], '0')

    def test_expired_snapshot_status_is_not_changed_to_502(self):
        handler = self.handler()
        error = urllib.error.HTTPError('http://localhost', 404, 'expired', {}, io.BytesIO())
        with patch.object(web.urllib.request, 'urlopen', side_effect=error):
            handler.do_GET()
        self.assertEqual(handler.status, 404)
