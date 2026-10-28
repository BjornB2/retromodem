"""Offline PHP security checks; no DNS requests or network transfers."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / 'proxy/retroweb/lib/ImageFetcher.php'
HARNESS = r'''
require $argv[1];
$input = json_decode(stream_get_contents(STDIN), true);
$calls = []; $dns = []; $now = 0;
$resolver = function($host, $timeout) use ($input, &$dns, &$now) {
    $dns[] = $host;
    $now += $input['dns_elapsed'] ?? 0;
    if (filter_var($host, FILTER_VALIDATE_IP)) return [$host];
    return $input['dns'][$host] ?? ['8.8.8.8'];
};
$transport = function($request) use ($input, &$calls, &$now) {
    $calls[] = $request;
    $now += $input['transport_elapsed'] ?? 0;
    $response = $input['responses'][$request['url']] ?? ['status'=>200,'headers'=>['content-type'=>'image/gif'],'body'=>'GIF89a'];
    if (isset($response['throw'])) throw new RuntimeException('', $response['throw']);
    return $response;
};
$fetcher = new RetroWebImageFetcher($input['bytes'] ?? 100, $input['timeout_ms'] ?? 25000,
    $input['redirects'] ?? 5, 'Test', $resolver, $transport, function() use (&$now) { return $now; });
$result = $fetcher->fetch($input['url']);
echo json_encode(['result'=>$result,'calls'=>$calls,'dns'=>$dns]);
'''


@unittest.skipUnless(shutil.which('php'), 'PHP unavailable')
class ImageFetcherTests(unittest.TestCase):
    def fetch(self, url='https://example.org/image.gif', **options):
        completed = subprocess.run(['php', '-r', HARNESS, str(LIBRARY)],
                                   input=json.dumps(dict(url=url, **options)), capture_output=True,
                                   text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stderr, '')
        return json.loads(completed.stdout)

    def redirect(self, location, body=''):
        return {'status': 302, 'headers': {'location': location}, 'body': body}

    def test_public_result_is_pinned_and_never_auto_follows(self):
        response = self.fetch(dns={'example.org': ['8.8.8.8', '1.1.1.1']})
        self.assertEqual(response['result']['status'], 200)
        self.assertEqual(response['calls'][0]['ip'], '8.8.8.8')
        self.assertFalse(response['calls'][0]['follow_redirects'])
        source = LIBRARY.read_text()
        self.assertIn('CURLOPT_FOLLOWLOCATION => false', source)
        self.assertIn('CURLOPT_RESOLVE', source)
        self.assertIn("CURLOPT_PROXY => ''", source)
        self.assertIn('CURLOPT_WRITEFUNCTION', source)

    def test_private_local_credentials_and_non_http_rejected(self):
        for url in ('file:///etc/passwd', 'http://localhost/x', 'http://127.0.0.2/x',
                    'http://10.0.0.1/x', 'http://192.168.0.1/x', 'http://169.254.169.254/x',
                    'http://[::1]/x', 'http://[::ffff:8.8.8.8]/x', 'http://100.64.0.1/x',
                    'http://name:pass@example.org/x', 'http://example.org/\r\nx', 'http://example.org/\\x'):
            with self.subTest(url=url):
                response = self.fetch(url)
                self.assertEqual(response['result']['status'], 403)
                self.assertEqual(response['result']['body'], '')
                self.assertEqual(response['calls'], [])

    def test_public_to_private_redirect_never_contacts_second_host(self):
        response = self.fetch(responses={'https://example.org/image.gif': self.redirect('http://private.example.org/image')},
                              dns={'private.example.org': ['192.168.0.1']})
        self.assertEqual(response['result']['status'], 403)
        self.assertEqual(len(response['calls']), 1)

    def test_mixed_private_dns_and_unknown_dns_fail_closed(self):
        blocked = self.fetch(dns={'example.org': ['8.8.8.8', '127.0.0.1']})
        self.assertEqual(blocked['result']['status'], 403)
        self.assertEqual(blocked['calls'], [])
        unknown = self.fetch(dns={'example.org': []})
        self.assertEqual(unknown['result']['status'], 204)
        self.assertEqual(unknown['calls'], [])

    def test_relative_redirect_validated_and_total_bytes_bounded(self):
        response = self.fetch(responses={'https://example.org/image.gif': self.redirect('/folder/next.gif', '123')})
        self.assertEqual([call['url'] for call in response['calls']],
                         ['https://example.org/image.gif', 'https://example.org/folder/next.gif'])
        self.assertEqual(response['calls'][1]['max_bytes'], 97)
        too_big = self.fetch(bytes=4)
        self.assertEqual(too_big['result']['status'], 413)
        self.assertEqual(too_big['result']['body'], '')

    def test_redirect_loop_and_non_200_never_return_payload(self):
        loop = self.fetch(responses={'https://example.org/image.gif': self.redirect('/image.gif')}, redirects=2)
        self.assertEqual(loop['result']['status'], 204)
        self.assertEqual(len(loop['calls']), 3)
        for status in (401, 403, 404, 429, 500):
            response = self.fetch(responses={'https://example.org/image.gif': {'status': status, 'headers': {}, 'body': 'PRIVATE ERROR'}})
            self.assertEqual(response['result']['status'], 204)
            self.assertEqual(response['result']['body'], '')

    def test_deadline_includes_resolver_and_transfer(self):
        response = self.fetch(timeout_ms=1000, dns_elapsed=2)
        self.assertEqual(response['result']['status'], 204)
        self.assertEqual(response['calls'], [])
        response = self.fetch(timeout_ms=1000, transport_elapsed=2)
        self.assertEqual(response['result']['status'], 204)
        self.assertEqual(response['result']['body'], '')

    def test_uppercase_scheme_and_trailing_dot_get_normalized_before_pinning(self):
        response = self.fetch('HTTPS://EXAMPLE.ORG./image.gif')
        self.assertEqual(response['calls'][0]['url'], 'https://example.org/image.gif')
        self.assertEqual(response['calls'][0]['host'], 'example.org')
        self.assertEqual(response['calls'][0]['port'], 443)

    def test_endpoint_only_uses_validated_fetcher(self):
        endpoint = (ROOT / 'proxy/retroweb/image_cruncher.php').read_text()
        self.assertIn('new RetroWebImageFetcher', endpoint)
        self.assertNotIn('@file_get_contents($imageUrl', endpoint)
        self.assertNotIn("'follow_location' => 1", endpoint)
