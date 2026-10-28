import html
import importlib.util
import io
from pathlib import Path
import re
import unittest
from unittest.mock import patch
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('search_results_proxy', ROOT / 'scripts/retroweb-proxy.py')
proxy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)


def response(content):
    return io.BytesIO(content.encode())


def result(number=1, snippet='Short &amp; useful description'):
    return (f'<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2F{number}">'
            f'Psion {number}</a><a class="result__snippet">{snippet}</a></div>')


NEXT = '<form action="/html/" method="post"><input name="q" value="wrong"><input name="s" value="10"><input name="vqd" value="provider-token"><input name="o" value="json"></form>'


class SearchResultTests(unittest.TestCase):
    def setUp(self):
        proxy._search_pages.clear()

    def test_snippets_are_safe_plain_text_and_missing_snippet_is_allowed(self):
        source = result(snippet='About &lt;script&gt; &amp; <b>Psion</b>') + '<div class="result"><a class="result__a" href="https://example.org/2">Second</a></div>'
        with patch.object(proxy.urllib.request, 'urlopen', return_value=response(source)):
            page = proxy.search_page('Psion 5mx', 'nl')
        self.assertIn(b'<p>About &lt;script&gt; &amp; Psion</p>', page)
        self.assertNotIn(b'<script>', page)
        self.assertIn(b'Second</a></li>', page)
        self.assertNotIn(b'Meer resultaten', page)
        self.assertIn(b'Powered by', page)
        self.assertIn(b'Zoeken via <a href="http://duckduckgo.com/">DuckDuckGo</a>', page)

    def test_source_continuation_and_cached_back_navigation(self):
        with patch.object(proxy.urllib.request, 'urlopen', side_effect=[response(result() + NEXT), response(result(2))]) as fetch:
            first = proxy.search_page('Psion 5mx', 'nl').decode('latin1')
            url = html.unescape(re.search(r'href="([^"]+)">Meer resultaten', first)[1])
            token = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['page'][0]
            second = proxy.search_page('Psion 5mx', 'nl', token).decode('latin1')
            request = fetch.call_args.args[0]
            self.assertEqual(request.full_url, 'https://html.duckduckgo.com/html/')
            params = urllib.parse.parse_qs(request.data.decode())
            self.assertEqual(params['q'], ['Psion 5mx'])
            self.assertEqual(params['s'], ['10'])
            self.assertEqual(params['vqd'], ['provider-token'])
            back = html.unescape(re.search(r'href="([^"]+)">Vorige resultaten', second)[1])
            previous = urllib.parse.parse_qs(urllib.parse.urlsplit(back).query)['page'][0]
            self.assertEqual(proxy.search_page('Psion 5mx', 'nl', previous).decode('latin1'), first)
            self.assertEqual(fetch.call_count, 2)
        self.assertIn('Psion 2', second)
        self.assertNotIn('Meer resultaten', second)

    def test_no_artificial_eleven_result_limit(self):
        with patch.object(proxy.urllib.request, 'urlopen', return_value=response(''.join(result(n) for n in range(25)))):
            page = proxy.search_page('Psion 5mx', 'en')
        self.assertEqual(page.count(b'<li>'), 25)

    def test_forged_expired_and_wrong_query_tokens_never_fetch(self):
        token = proxy.new_search_page('different query')
        with patch.object(proxy.urllib.request, 'urlopen') as fetch:
            for selected in ('https://127.0.0.1/', 'a' * 32, token):
                page = proxy.search_page('Psion 5mx', 'nl', selected)
                self.assertIn(b'Zoeken is tijdelijk', page)
            fetch.assert_not_called()

    def test_foreign_continuation_forms_are_not_followed(self):
        with patch.object(proxy.urllib.request, 'urlopen', return_value=response(result() + NEXT.replace('/html/', 'https://evil.example/html/'))):
            page = proxy.search_page('Psion 5mx', 'nl')
        self.assertNotIn(b'Meer resultaten', page)

    def test_startpage_fallback_snippet(self):
        fallback = '<article><a class="w-gl__result-title" href="https://example.org/">Fallback</a><p class="w-gl__description">Fallback summary.</p></article>'
        with patch.object(proxy.urllib.request, 'urlopen', side_effect=[response(''), response(fallback)]):
            page = proxy.search_page('Psion 5mx', 'en')
        self.assertIn(b'Fallback summary.', page)
        self.assertIn(b'Search powered by <a href="http://www.startpage.com/">Startpage</a>', page)

    def test_search_cache_is_bounded(self):
        for number in range(100):
            proxy.new_search_page(str(number))
        self.assertLessEqual(len(proxy._search_pages), 64)
