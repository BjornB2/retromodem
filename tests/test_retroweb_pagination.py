"""Exercise the real PHP paginator, without fetching sites or loading Composer."""
import base64
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PHP = shutil.which('php')
LIBRARY = ROOT / 'proxy/retroweb/lib/PagePaginator.php'
HARNESS = r'''
require $argv[1];
$in = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
$p = new RetroWebPagePaginator($in['cache'], $in['limit'] ?? 18000, 5, $in['ttl'] ?? 3600, $in['maxDocuments'] ?? 128);
if (isset($in['read'])) {
    $r = $p->read($in['read'], $in['part']);
    echo json_encode(['status'=>$r['status'], 'html'=>base64_encode($r['html'])]);
    exit;
}
$first = $p->first(base64_decode($in['content']), 'Test article', '<p>RetroWEB navigation</p>', '', 'http://127.0.0.1:8090');
preg_match('/document=([a-f0-9]{64})/', $first, $match);
$token = $match[1] ?? null;
$pages = [];
if ($token) {
    for ($i=1; $i<=1000; $i++) {
        $r = $p->read($token, (string)$i);
        if ($r['status'] !== 200) break;
        $pages[] = base64_encode($r['html']);
    }
    $all = $p->read($token, 'all');
} else {
    $pages[] = base64_encode($first);
    $all = ['status'=>200, 'html'=>$first];
}
echo json_encode(['first'=>base64_encode($first), 'token'=>$token, 'pages'=>$pages, 'all'=>base64_encode($all['html'])]);
'''


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in {'img', 'hr', 'br', 'meta', 'input', 'link'}:
            self.stack.append((tag, attrs.get('id')))
        if tag == 'a' and any(identifier == 'article' for _, identifier in self.stack):
            self.links.append(attrs.get('href'))

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_data(self, data):
        if any(identifier == 'article' for _, identifier in self.stack):
            self.text.append(data)


@unittest.skipUnless(PHP, 'PHP runtime unavailable')
class RetroWebPaginationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name) / 'pages'

    def invoke(self, **values):
        result = subprocess.run([PHP, '-d', 'display_errors=stderr', '-r', HARNESS, str(LIBRARY)],
                                input=json.dumps(dict(cache=str(self.cache), **values)),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def paginate(self, content, **values):
        response = self.invoke(content=base64.b64encode(content.encode('iso-8859-1')).decode(), **values)
        response['pages'] = [base64.b64decode(page) for page in response['pages']]
        response['first'] = base64.b64decode(response['first'])
        response['all'] = base64.b64decode(response['all'])
        return response

    def article(self, pages):
        text, links = [], []
        for page in pages:
            parser = ArticleParser()
            parser.feed(page.decode('iso-8859-1'))
            text.extend(parser.text)
            links.extend(parser.links)
        return ''.join(text), links

    def test_short_page_remains_single_without_cache(self):
        response = self.paginate('<div id="article"><p>Short article.</p></div>')
        self.assertIsNone(response['token'])
        self.assertEqual(len(response['pages']), 1)
        self.assertEqual(self.article(response['pages'])[0], 'Short article.')
        self.assertFalse(self.cache.exists())

    def test_large_nested_paragraph_and_links_preserve_text_and_byte_budget(self):
        text = ('café &amp; &#937; ' * 5000) + ('z' * 20000)
        content = '<div id="article"><p><b>Intro </b><a href="https://example.com/?part=2&amp;q=a">' + text + '</a></p></div>'
        response = self.paginate(content)
        self.assertGreater(len(response['pages']), 3)
        for page in response['pages']:
            self.assertLessEqual(len(page), 18000 - 512)
            self.assertIn(b'<title>Test article</title>', page)
            self.assertEqual(page.count(b'class="retroweb-paging"'), 2)
        recovered, links = self.article(response['pages'])
        original, _ = self.article([content.encode('iso-8859-1')])
        self.assertEqual(recovered, original)
        self.assertTrue(links)
        self.assertEqual(set(links), {'https://example.com/?part=2&q=a'})

    def test_long_lists_and_tables_split_without_missing_items(self):
        items = ''.join(f'<li>Item {index}: ' + 'word ' * 300 + '</li>' for index in range(30))
        rows = ''.join(f'<tr><td>Cell {index}: ' + 'data ' * 300 + '</td></tr>' for index in range(20))
        content = '<div id="article"><ol>' + items + '</ol><table>' + rows + '</table></div>'
        response = self.paginate(content)
        recovered, _ = self.article(response['pages'])
        original, _ = self.article([content.encode('iso-8859-1')])
        self.assertEqual(recovered, original)
        for page in response['pages']:
            self.assertLessEqual(len(page), 18000 - 512)

    def test_image_limit_applies_even_to_small_html(self):
        content = '<div id="article">' + ''.join(f'<p><img src="https://example.com/{i}.gif" alt="Image {i}"></p>' for i in range(13)) + '</div>'
        response = self.paginate(content)
        self.assertEqual(len(response['pages']), 3)
        self.assertEqual(sum(page.count(b'<img') for page in response['pages']), 13)
        self.assertTrue(all(page.count(b'<img') <= 5 for page in response['pages']))

    def test_snapshot_reload_is_stable_and_entire_page_preserves_original(self):
        content = '<div id="article">' + '<p>Keep this paragraph.</p>' * 2000 + '</div>'
        first = self.paginate(content)
        second = self.paginate(content)
        self.assertEqual(first['token'], second['token'])
        self.assertEqual(first['pages'], second['pages'])
        self.assertIn(content.encode('iso-8859-1'), first['all'])
        read = self.invoke(read=first['token'], part='2')
        self.assertEqual(read['status'], 200)
        self.assertEqual(base64.b64decode(read['html']), first['pages'][1])

    def test_invalid_expired_and_out_of_range_selections(self):
        response = self.paginate('<p>' + 'word ' * 10000 + '</p>')
        for token, part, status in (('../escape', '1', 400), ('a' * 64, '1', 404),
                                    (response['token'], '0', 400), (response['token'], '../2', 400),
                                    (response['token'], '999999', 404)):
            self.assertEqual(self.invoke(read=token, part=part)['status'], status)
        path = self.cache / ('pagination-' + response['token'] + '.json')
        snapshot = json.loads(path.read_text())
        snapshot['created'] = 0
        path.write_text(json.dumps(snapshot))
        self.assertEqual(self.invoke(read=response['token'], part='1')['status'], 404)

    def test_snapshot_count_bound(self):
        for index in range(4):
            self.paginate('<p>' + str(index) + 'word ' * 5000 + '</p>', maxDocuments=2)
        self.assertLessEqual(len(list(self.cache.glob('pagination-*.json'))), 2)

    def test_internal_anchors_point_to_the_part_containing_the_target(self):
        content = '<div id="article"><p><a href="#end">Jump to end</a></p>' + '<p>Paragraph text.</p>' * 2000 + '<h2 id="end">Last heading</h2></div>'
        response = self.paginate(content)
        target_part = next(index + 1 for index, page in enumerate(response['pages']) if b'id="end"' in page)
        self.assertGreater(target_part, 1)
        expected = ('document=' + response['token'] + '&amp;part=' + str(target_part) + '#end').encode()
        self.assertIn(expected, response['pages'][0])
        self.assertTrue(all(len(page) <= 18000 - 512 for page in response['pages']))
