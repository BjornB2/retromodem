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
$p = new RetroWebPagePaginator($in['cache'], $in['limit'] ?? 12000, $in['images'] ?? 5,
                               3600, 128, 67108864, $in['language'] ?? 'en');
if (isset($in['token'])) {
    $result = $p->read($in['token'], $in['part'], $in['mode'] ?? null, $in['block'] ?? null);
    echo json_encode(['status'=>$result['status'],'html'=>base64_encode($result['html'])]);
} else {
    $first = $p->first(base64_decode($in['content']), isset($in['title']) ? base64_decode($in['title']) : 'Article', '<p>Reload page</p>', '',
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

    def old_metadata(self, snapshot):
        if snapshot.pop('metadata_encoding', None) == 'base64':
            for field in ('title', 'navigation', 'body_attrs', 'base_url'):
                snapshot[field] = base64.b64decode(snapshot[field]).decode('iso-8859-1')
        return snapshot

    def test_latin1_framing_is_byte_exact_after_save_reload_and_language_rebuild(self):
        title = b'Psion caf\xe9 \x81 review'
        first = self.first('<p>Body</p>', title=base64.b64encode(title).decode())
        self.assertIn(title, first['html'])
        self.assertEqual(self.snapshot(first['token'])['metadata_encoding'], 'base64')
        again = self.invoke(token=first['token'], part='1', mode='inline')
        self.assertEqual(first['html'], again['html'])
        rebuilt = self.invoke(token=first['token'], part='1', mode='links', language='nl')
        self.assertEqual(rebuilt['status'], 200)
        self.assertIn(title, rebuilt['html'])

    def test_short_page_has_both_views_without_fetching_images(self):
        content = '<p>Hello <img src="http://unreachable.invalid/photo.gif" width="40" height="30" alt="A photo" data-rm-link-label="Image 1: A photo"></p>'
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
        self.assertNotIn(b'data-rm-link-label', inline['html'])
        self.assertNotIn(b'data-rm-image-number', inline['html'])

    def test_functional_image_link_keeps_original_destination(self):
        first = self.first('<a href="https://example.org/next"><img src="https://example.org/button.gif" alt="Next page"></a>')
        links = self.invoke(token=first['token'], part='1', mode='links')['html']
        self.assertIn(b'<a href="https://example.org/next">[Image 1: Next page]</a>', links)
        self.assertNotIn(b'<a href="https://example.org/button.gif">', links)

    def test_mode_is_not_part_of_document_identity(self):
        content = '<p>Article<img src="x.gif" width="40" height="30" alt="photo"></p>'
        links = self.first(content, mode='links')
        inline = self.first(content, mode='inline')
        self.assertEqual(links['token'], inline['token'])
        self.assertNotIn(b'<img', links['html'])
        self.assertIn(b'<img', inline['html'])
        self.assertEqual(len(list(self.cache.glob('pagination-*.json'))), 1)

    def test_toggle_from_part_seven_preserves_fine_source_position(self):
        # One huge paragraph: a top-level-only source anchor would return to part 1.
        content = '<div><p>' + ''.join(f'BLOCK{n:04}: ' + 'word ' * 100 +
            '<img src="x.gif" width="20" height="10" alt="' + 'Long photo description ' * 12 + '">' for n in range(250)) + '</p></div>'
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
        self.assertEqual(result['status'], 200)
        self.assertIn(f'Part {target} of '.encode(), result['html'])
        self.assertTrue(set(re.findall(rb'BLOCK[0-9]+', seventh)) & set(re.findall(rb'BLOCK[0-9]+', result['html'])))
        reverse_url = next(url for url in re.findall(rb'href="([^"]+)"', result['html'])
                           if b'img=inline' in url and b'block=' in url)
        reverse_query = urllib.parse.parse_qs(urllib.parse.urlsplit(html.unescape(reverse_url.decode())).query)
        self.assertEqual(reverse_query['block'], [block])
        back = self.invoke(token=first['token'], part=str(target), mode='inline', block=block)
        self.assertEqual(back['html'], seventh)

    def weight(self, page):
        pixels = 0
        for tag in re.findall(rb'<img\b[^>]*>', page):
            declared = re.search(rb'data-rm-pixels="([0-9]+)"', tag)
            if declared:
                pixels += int(declared[1])
                continue
            width = re.search(rb'width="([0-9]+)"', tag)
            height = re.search(rb'height="([0-9]+)"', tag)
            pixels += int(width[1]) * int(height[1]) if width and height else 512 * 342
        return len(page) + pixels

    def test_combined_html_and_pixel_budget_splits_large_images_not_links(self):
        content = '<p>Photos</p>' + ''.join(f'<p>Photo {n}<img src="photo-{n}.gif" width="100" height="100"></p>' for n in range(6))
        first = self.first(content, limit=25000)
        snapshot = self.snapshot(first['token'])
        inline = [base64.b64decode(value) for value in snapshot['variants']['inline']['pages']]
        links = snapshot['variants']['links']['pages']
        self.assertGreater(len(inline), 1)
        self.assertEqual(len(links), 1)
        self.assertEqual(sum(page.count(b'<img') for page in inline), 6)
        self.assertTrue(all(self.weight(page) <= 25000 - 512 for page in inline))

    def test_individually_oversized_image_is_a_link_not_lost(self):
        content = '<p>Caption <a href="https://example.org/article"><img src="huge.gif" width="500" height="500" alt="Read article"></a> End</p>'
        first = self.first(content, limit=18000)
        self.assertNotIn(b'<img', first['html'])
        self.assertIn(b'<a href="https://example.org/article">[Image 1: Read article]</a>', first['html'])
        self.assertIn(b'oversized image(s)', first['html'])
        self.assertNotIn(b'<a href="huge.gif">', first['html'])
        self.assertIn(b'Caption ', first['html'])
        self.assertIn(b' End', first['html'])

    def test_unknown_dimensions_are_conservative_but_renderer_weight_is_preserved(self):
        unknown = self.first('<img src="unknown.gif" alt="Unknown">', limit=100000)
        self.assertNotIn(b'<img', unknown['html'])
        renderer = self.first('<img src="bounded.gif" data-rm-pixels="1000" alt="Bounded">', limit=12000)
        self.assertIn(b'<img', renderer['html'])
        self.assertIn(b'data-rm-pixels="1000"', renderer['html'])
        self.assertLessEqual(self.weight(renderer['html']), 12000 - 512)

    def test_unlimited_and_entire_page_views_keep_all_images_with_warning(self):
        content = '<img src="huge.gif" width="500" height="500" alt="Big">'
        unlimited = self.first(content, limit=0)
        self.assertIn(b'<img', unlimited['html'])
        self.assertIn(b'Unsplit: may use substantial memory.', unlimited['html'])
        limited = self.first(content, limit=18000)
        all_page = self.invoke(token=limited['token'], part='all', mode='inline')['html']
        self.assertIn(b'<img', all_page)
        self.assertIn(b'Unsplit: may use substantial memory.', all_page)

    def test_controls_and_messages_are_localized_and_before_first_heading(self):
        content = '<img src="huge.gif" width="500" height="500" data-rm-link-label="Image 1: Big">'
        dutch = self.first(content, language='nl')
        page = dutch['html']
        for control in (b'Afbeeldingen:', b'Laten zien', b'als links', b'Deel 1 van', b'Volledige pagina tonen'):
            self.assertIn(control, page)
            self.assertLess(page.index(control), page.index(b'<h1>'))
        self.assertIn(b'[Afbeelding 1: Big]', page)
        self.assertIn(b'te grote afbeelding(en)', page)
        self.assertNotIn(b'Images:', page)
        self.assertNotIn(b'Pagina opnieuw ophalen', page)
        self.assertNotIn(b'Reload page', page)
        english = self.first(content, language='en')
        self.assertNotEqual(dutch['token'], english['token'])
        missing = self.invoke(token='f' * 64, part='1', language='nl')
        self.assertIn(b'Pagina niet beschikbaar', missing['html'])

    def test_old_canonical_snapshot_rebuilds_for_new_language_and_policy(self):
        content = '<p>Photos</p>' + '<img src="x.gif" width="100" height="100" data-rm-link-label="Image 1: Photo">' * 6
        original = self.first(content, limit=25000)
        snapshot = self.snapshot(original['token'])
        snapshot = self.old_metadata(snapshot)
        snapshot['schema_version'] = 2
        snapshot.pop('language')
        snapshot.pop('weight_policy')
        snapshot['variants']['inline']['pages'] = [base64.b64encode(b'UNSAFE OLD PAGE').decode()]
        (self.cache / ('pagination-' + original['token'] + '.json')).write_text(json.dumps(snapshot))
        fresh = self.invoke(token=original['token'], part='1', mode='inline', language='nl', limit=200000)
        self.assertEqual(fresh['status'], 200)
        self.assertNotIn(b'UNSAFE OLD PAGE', fresh['html'])
        self.assertIn(b'Afbeeldingen:', fresh['html'])
        self.assertLessEqual(self.weight(fresh['html']), 25000 - 512)
        rebuilt = self.snapshot(original['token'])
        self.assertEqual(rebuilt['schema_version'], 3)
        self.assertEqual(rebuilt['limit'], 25000)
        self.assertEqual(rebuilt['language'], 'nl')
        self.assertGreater(len(rebuilt['variants']['inline']['pages']), 1)

    def test_existing_same_language_snapshot_loses_obsolete_reload_control(self):
        original = self.first('<p>Content</p>', language='nl')
        snapshot = self.snapshot(original['token'])
        snapshot = self.old_metadata(snapshot)
        snapshot['weight_policy'] = 'html-plus-pixels-v1'
        snapshot['navigation'] = '<p><a href="https://example.org/">Pagina opnieuw ophalen</a></p><hr>'
        snapshot['variants']['inline']['pages'] = [base64.b64encode(b'OLD RELOAD CONTROL').decode()]
        (self.cache / ('pagination-' + original['token'] + '.json')).write_text(json.dumps(snapshot))
        fresh = self.invoke(token=original['token'], part='1', language='nl')
        self.assertEqual(fresh['status'], 200)
        self.assertIn(b'Afbeeldingen:', fresh['html'])
        self.assertNotIn(b'OLD RELOAD', fresh['html'])
        self.assertNotIn(b'Pagina opnieuw ophalen', fresh['html'])

    def test_byte_limits_apply_in_both_views_but_image_count_does_not(self):
        first = self.first('<p>' + '<img src="i.gif" width="8" height="8" alt="icon">' * 80 + '</p>', images=1)
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

    def test_noncanonical_legacy_snapshot_is_retired_safely(self):
        self.cache.mkdir()
        token = 'a' * 64
        original = b'<html>Legacy page</html>'
        (self.cache / ('pagination-' + token + '.json')).write_text(json.dumps({
            'created':int(time.time()), 'pages':[base64.b64encode(original).decode()],
            'all':base64.b64encode(original).decode()}))
        self.assertEqual(self.invoke(token=token, part='1')['status'], 410)
        self.assertEqual(self.invoke(token=token, part='1', mode='links')['status'], 410)
