"""Image cleanup preserves content order and metadata, not site-wide tails."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
PHP = shutil.which('php')
HARNESS = r'''
require $argv[1];
$input = json_decode(stream_get_contents(STDIN), true);
if (($input['operation'] ?? '') === 'navigation') {
    $_GET = ['url' => 'https://example.org/article'];
    echo base64_encode(renderNavigation($input['mode'] ?? 'inline'));
} elseif (($input['operation'] ?? '') === 'merge') {
    $merged = mergeImageHints($input['previous'], $input['incoming']);
    echo base64_encode(json_encode(mergeImageHints($merged, $input['incoming'])));
} else {
    $html = renderCanonicalImages($input['content'], 'http://127.0.0.1:8090', 'https://example.org/article',
        $input['original'] ?? '', $input['map'] ?? [], $input['dimensions'] ?? []);
    echo base64_encode($html);
}
'''


class ImageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            self.images.append(dict(attrs))
        if tag == 'a':
            self.anchors.append(dict(attrs))


@unittest.skipUnless(PHP, 'PHP runtime unavailable')
class ImageCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name) / 'config.php'
        shutil.copyfile(ROOT / 'proxy/retroweb/config.php', self.config)
        self.environment = dict(os.environ, RETROMODEM_CONFIG_FILE=str(Path(self.temp.name) / 'missing'),
                                RETROMODEM_PROXY_IMAGE_WIDTH='200', RETROMODEM_PROXY_IMAGE_HEIGHT='150')

    def render(self, content='', **values):
        result = subprocess.run([PHP, '-d', 'display_errors=stderr', '-r', HARNESS, str(self.config)],
                                input=json.dumps(dict(content=content, **values)), capture_output=True,
                                text=True, env=self.environment, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = base64.b64decode(result.stdout).decode('iso-8859-1')
        parser = ImageParser()
        parser.feed(text)
        return text, parser

    def test_no_append_all_site_images_and_content_stays_in_place(self):
        content = '<p>Before <img src="photo.jpg" alt="Article photo"> After</p>'
        original = '<img src="sidebar.jpg"><img src="button.gif">' + content
        text, parser = self.render(content, original=original)
        self.assertEqual(len(parser.images), 1)
        self.assertNotIn('sidebar', text)
        self.assertNotIn('button.gif', text)
        self.assertRegex(text, r'<p>Before <img[^>]+> After</p>')
        source = (ROOT / 'proxy/retroweb/proxy.php').read_text()
        self.assertNotIn('$addedImages', source)
        self.assertNotIn('$contentImageCount < $originalImageCount', source)

    def test_icon_and_thin_diagram_are_not_removed(self):
        _, parser = self.render('<img src="/icon/button.gif" width="16" height="16" alt="Next">'
                                '<img src="diagram.gif" width="1000" height="20" alt="Timeline">')
        self.assertEqual(len(parser.images), 2)
        self.assertEqual((parser.images[0]['width'], parser.images[0]['height']), ('16', '16'))
        self.assertEqual((parser.images[1]['width'], parser.images[1]['height']), ('200', '4'))

    def test_functional_pixel_retained_but_unlabelled_tracker_removed(self):
        text, parser = self.render('<a href="/next"><img src="button.gif" width="1" height="1"></a>'
                                   '<img src="tracker.gif" width="1" height="1">')
        self.assertEqual(len(parser.images), 1)
        self.assertEqual(parser.anchors, [{'href': '/next'}])
        self.assertNotIn('tracker.gif', text)

    def test_dimensions_and_asset_hints_scale_without_upscaling(self):
        _, parser = self.render('<img src="photo.jpg" width="1600" height="800" alt="Photo">'
                                '<img src="small.gif" width="40" height="20">')
        self.assertEqual((parser.images[0]['width'], parser.images[0]['height']), ('200', '100'))
        self.assertEqual((parser.images[1]['width'], parser.images[1]['height']), ('40', '20'))
        for image in parser.images:
            query = parse_qs(urlsplit(image['src']).query)
            self.assertEqual(query['w'], [image['width']])
            self.assertEqual(query['h'], [image['height']])

    def test_original_metadata_and_alt_survive_extractor_tag_changes(self):
        _, parser = self.render('<a href="/next"><img src="photo.jpg" alt="A &amp; B"></a>',
                                map={'photo.jpg': 'https://example.org/photo.jpg'},
                                dimensions={'https://example.org/photo.jpg': {'width': 40, 'height': 20}})
        image = parser.images[0]
        self.assertEqual((image['width'], image['height']), ('40', '20'))
        self.assertEqual(image['alt'], 'A & B')
        self.assertEqual(image['data-rm-link-label'], 'Image 1: A & B')
        self.assertEqual(parser.anchors, [{'href': '/next'}])

    def test_unknown_dimensions_not_assumed_small(self):
        _, parser = self.render('<img src="/avatar/photo.png" alt="Author">')
        self.assertEqual(len(parser.images), 1)
        self.assertNotIn('width', parser.images[0])
        self.assertNotIn('height', parser.images[0])

    def test_conflicting_per_url_hints_are_not_guessed(self):
        text, _ = self.render(operation='merge', previous={'width': 16, 'height': 16, 'alt': 'Next'},
                              incoming={'width': 800, 'height': 600, 'alt': 'Photo'})
        merged = json.loads(text)
        self.assertIsNone(merged['width'])
        self.assertIsNone(merged['height'])
        self.assertIsNone(merged['alt'])
        self.assertTrue(merged['ambiguous_width'])

    def test_original_alt_used_when_extractor_removed_it(self):
        _, parser = self.render('<img src="photo.jpg">',
                                dimensions={'https://example.org/photo.jpg': {'width': 40, 'height': 20, 'alt': 'Original &amp; label'}})
        self.assertEqual(parser.images[0]['alt'], 'Original & label')

    def test_navigation_is_minimal_and_canonical_pipeline_independent_of_mode(self):
        text, _ = self.render(operation='navigation')
        self.assertIn('Open original again', text)
        self.assertNotIn('Visits:', text)
        self.assertNotIn('index.php', text)
        source = (ROOT / 'proxy/retroweb/proxy.php').read_text()
        self.assertIn('renderCanonicalImages($content', source)
        self.assertNotIn("if ($imageMode === 'inline')", source)
        self.assertIn('$baseUrl, $imageMode)', source)
        links, _ = self.render(operation='navigation', mode='links')
        self.assertEqual(links, text)

    def test_alt_entities_survive_latin1_document_output(self):
        text, parser = self.render('<img src="photo.jpg" alt="caf&#233; &#937;">')
        self.assertEqual(parser.images[0]['alt'], 'caf\u00e9 \u03a9')
        self.assertTrue(text.isascii())
