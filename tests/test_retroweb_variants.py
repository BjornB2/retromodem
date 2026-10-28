"""Real PHP snapshot variants: no origin access or image downloads are needed."""
import base64
import html
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / 'proxy/retroweb/lib/PagePaginator.php'
HARNESS = r'''
require $argv[1];
$in = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
$p = new RetroWebPagePaginator($in['cache'], $in['limit'] ?? 12000, $in['images'] ?? 5);
if (isset($in['token'])) {
    $result = $p->read($in['token'], $in['part'], $in['mode'] ?? null, $in['block'] ?? null);
    echo json_encode(['status'=>$result['status'],'html'=>base64_encode($result['html'])]);
} else {
    $first = $p->first(base64_decode($in['content']), 'Article', '<p>Original page</p>', '',
                       'http://127.0.0.1:8090', $in['mode'] ?? 'inline');
    preg_match('/document=([a-f0-9]{64})/', $first, $match);
    echo json_encode(['status'=>200,'token'=>$match[1],'html'=>base64_encode($first)]);
}
'''


@unittest.skipUnless(shutil.which('php'), 'PHP unavailable')
class DocumentVariantTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.cache = Path(self.temporary.name) / 'pages'

    def invoke(self, **values):
        result = subprocess.run(['php', '-r', HARNESS, str(LIBRARY)],
                                input=json.dumps(dict(cache=str(self.cache), **values)),
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        decoded = json.loads(result.stdout)
        decoded['html'] = base64.b64decode(decoded['html'])
        return decoded

    def first(self, content, **options):
        return self.invoke(content=base64.b64encode(content.encode('iso-8859-1')).decode(), **options)

    def snapshot(self, token):
        return json.loads((self.cache / ('pagination-' + token + '.json')).read_text())

    def test_short_page_has_both_views_without_fetching_images(self):
        content = '<p>Hello <img src="http://unreachable.invalid/photo.gif" alt="A photo" data-rm-link-label="Image 1: A photo"></p>'
        first = self.first(content)
        self.assertIn(b'Images: <b>Inline</b>', first['html'])
        self.assertIn(b'As links', first['html'])
        links = self.invoke(token=first['token'], part='1', mode='links')
        self.assertNotIn(b'<img', links['html'])
        self.assertIn(b'[Image 1: A photo]', links['html'])
        self.assertIn(b'href="http://unreachable.invalid/photo.gif"', links['html'])
        self.assertIn(b'<b>As links</b>', links['html'])
        inline = self.invoke(token=first['token'], part='1', mode='inline')
        self.assertEqual(inline['html'], first['html'])
        self.assertNotIn(b'data-rm-', inline['html'])

    def test_functional_image_link_keeps_original_destination(self):
        first = self.first('<a href="https://example.org/next"><img src="https://example.org/button.gif" alt="Next page"></a>')
        links = self.invoke(token=first['token'], part='1', mode='links')['html']
        self.assertIn(b'<a href="https://example.org/next">[Image 1: Next page]</a>', links)
        self.assertNotIn(b'<a href="https://example.org/button.gif">', links)

    def test_mode_is_not_part_of_document_identity(self):
        content = '<p>Article<img src="x.gif" alt="photo"></p>'
        links = self.first(content, mode='links')
        inline = self.first(content, mode='inline')
        self.assertEqual(links['token'], inline['token'])
        self.assertNotIn(b'<img', links['html'])
        self.assertIn(b'<img', inline['html'])
        self.assertEqual(len(list(self.cache.glob('pagination-*.json'))), 1)

    def test_toggle_from_part_seven_preserves_fine_source_position(self):
        # One huge paragraph: a top-level-only source anchor would return to part 1.
        content = '<div><p>' + ''.join(f'BLOCK{n:04}: ' + 'word ' * 100 +
            '<img src="x.gif" alt="' + 'Long photo description ' * 12 + '">' for n in range(250)) + '</p></div>'
        first = self.first(content)
        snapshot = self.snapshot(first['token'])
        self.assertGreater(len(snapshot['variants']['inline']['pages']), 7)
        seventh = self.invoke(token=first['token'], part='7', mode='inline')['html']
        candidates = re.findall(rb'href="([^"]+)"', seventh)
        query = next(urllib.parse.parse_qs(urllib.parse.urlsplit(html.unescape(url.decode())).query)
                     for url in candidates if b'img=links' in url and b'block=' in url)
        block = query['block'][0]
        target = snapshot['variants']['links']['blocks'][block]
        self.assertGreater(target, 1)
        result = self.invoke(token=first['token'], part='7', mode='links', block=block)
        self.assertEqual(result['html'], base64.b64decode(snapshot['variants']['links']['pages'][target - 1]))
        self.assertIn(f'Part {target} of '.encode(), result['html'])
        self.assertTrue(set(re.findall(rb'BLOCK[0-9]+', seventh)) & set(re.findall(rb'BLOCK[0-9]+', result['html'])))

    def test_byte_limits_apply_in_both_views_but_image_count_does_not(self):
        first = self.first('<p>' + '<img src="i.gif" alt="icon">' * 80 + '</p>', images=1)
        snapshot = self.snapshot(first['token'])
        self.assertEqual(len(snapshot['variants']['inline']['pages']), 1)
        self.assertEqual(first['html'].count(b'<img'), 80)
        for variant in snapshot['variants'].values():
            for page in variant['pages']:
                self.assertLessEqual(len(base64.b64decode(page)), 12000 - 512)
        self.assertEqual(self.invoke(token=first['token'], part='all', mode='inline')['html'].count(b'<img'), 80)

    def test_invalid_mode_and_block_are_rejected(self):
        first = self.first('<p>Article</p>')
        for options in ({'mode':'invalid'}, {'mode':'links','block':'../x'},
                        {'mode':'inline','block':'b0'}):
            self.assertEqual(self.invoke(token=first['token'], part='1', **options)['status'], 400)
        self.assertEqual(self.invoke(token=first['token'], part='1', mode='links', block='b999999')['status'], 404)

    def test_legacy_deployed_snapshot_still_reads(self):
        self.cache.mkdir()
        token = 'a' * 64
        original = b'<html>Legacy page</html>'
        (self.cache / ('pagination-' + token + '.json')).write_text(json.dumps({
            'created':int(time.time()), 'pages':[base64.b64encode(original).decode()],
            'all':base64.b64encode(original).decode()}))
        self.assertEqual(self.invoke(token=token, part='1')['html'], original)
        self.assertEqual(self.invoke(token=token, part='1', mode='links')['status'], 404)
