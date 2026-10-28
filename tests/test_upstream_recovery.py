import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
$in=json_decode(stream_get_contents(STDIN),true);
function retromodemNavigationLanguage() { global $in; return $in['language']??'nl'; }
require $argv[1];
$calls=[]; $now=1000;
$transport=function($url) use (&$calls,$in) {
  $calls[]=$url;
  $r=$in['responses'][$url]??[];
  if(isset($r['throw'])) throw new RuntimeException('simulated source failure',$r['throw']);
  return array_merge(['url'=>$url,'status'=>200,'body'=>'<title>Article</title>','type'=>'text/html','headers'=>[]],$r);
};
$clock=function()use(&$now){return $now;};
$r=fetchModemUpstream($in['url'],$in['allow_http']??false,$transport,$in['directory'],$clock);
$out=['result'=>$r,'message'=>modemUpstreamProblem($r)];
if(isset($in['after'])) {
  $now+=$in['after'];
  $out['second']=fetchModemUpstream($in['url'],$in['allow_http']??false,$transport,$in['directory'],$clock);
}
$out['calls']=$calls;
echo json_encode($out);
'''


@unittest.skipUnless(shutil.which('php'), 'PHP unavailable')
class UpstreamRecoveryTests(unittest.TestCase):
    def invoke(self, **options):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(['php', '-r', HARNESS, str(ROOT / 'proxy/retroweb/upstream.php')],
                                    input=json.dumps(dict({'url': 'https://example.org/page', 'directory': directory}, **options)),
                                    text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_legacy_http_recovery_is_explicit_and_limited_to_tls_handshake_failure(self):
        data = self.invoke(allow_http=True, responses={'https://example.org/page': {'throw': 35}})
        self.assertEqual(data['calls'], ['https://example.org/page', 'http://example.org/page'])
        self.assertEqual(data['result']['transport_note'], 'http-fallback')
        self.assertIsNone(data['message'])
        for allow, code in ((False, 35), (True, 60), (True, 77), (True, 28)):
            data = self.invoke(allow_http=allow, responses={'https://example.org/page': {'throw': code}})
            self.assertEqual(data['calls'], ['https://example.org/page'])
            self.assertIn('failure', data['result'])

    def test_timeout_is_a_source_failure_not_an_uncaught_500(self):
        data = self.invoke(responses={'https://example.org/page': {'throw': 28}})
        self.assertEqual(data['result']['failure'], 'timeout')
        self.assertIn('geen interne proxyfout', data['message'])
        english = self.invoke(language='en', responses={'https://example.org/page': {'throw': 28}})
        self.assertIn('connection timeout', english['message'])

    def test_429_backoff_respects_retry_after_and_suppresses_second_request(self):
        data = self.invoke(after=5, responses={'https://example.org/page': {'status': 429, 'headers': {'retry-after': '90'}}})
        self.assertEqual(len(data['calls']), 1)
        self.assertEqual(data['second']['retry_seconds'], 85)
        self.assertTrue(data['second']['backoff'])
        self.assertIn('niet dat jij te vaak hebt geklikt', data['message'])

    def test_backoff_expires_and_untrusted_retry_after_is_bounded(self):
        data = self.invoke(after=61, responses={'https://example.org/page': {'status': 429}})
        self.assertEqual(len(data['calls']), 2)
        data = self.invoke(after=1, responses={'https://example.org/page': {'status': 429, 'headers': {'retry-after': '999999999'}}})
        self.assertEqual(data['result']['retry_seconds'], 300)

    def test_cloudflare_challenge_is_distinguished_from_local_address_block(self):
        data = self.invoke(responses={'https://example.org/page': {'status': 403, 'body': '<title>Just a moment...</title>'}})
        self.assertIn('browsercontrole', data['message'])
        self.assertIn('geen lokale adresblokkade', data['message'])
        blocked = self.invoke(responses={'https://example.org/page': {'throw': 403}})
        self.assertEqual(blocked['result']['failure'], 'blocked')

    def test_wikiwand_block_uses_exact_original_wikipedia_article(self):
        data = self.invoke(url='https://www.wikiwand.com/en/articles/Psion_Series_5',
                           responses={'https://www.wikiwand.com/en/articles/Psion_Series_5': {'status': 403}})
        self.assertEqual(data['calls'], ['https://www.wikiwand.com/en/articles/Psion_Series_5',
                                         'https://en.wikipedia.org/wiki/Psion_Series_5'])
        self.assertEqual(data['result']['transport_note'], 'original-wikipedia')
