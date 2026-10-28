import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from web import local_ui


class LocalLanguageTests(unittest.TestCase):
    def test_configuration_is_read_again_without_service_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'settings.env'
            with patch.object(local_ui, 'CONFIG', config), patch.dict(local_ui.os.environ, {'RETROMODEM_LANGUAGE': 'nl'}):
                self.assertEqual(local_ui.language(), 'nl')
                config.write_text("RETROMODEM_LANGUAGE='en'\n")
                self.assertEqual(local_ui.language(), 'en')
                config.write_text('RETROMODEM_LANGUAGE=nl\n')
                self.assertEqual(local_ui.language(), 'nl')

    def test_search_footer_and_both_languages_and_error(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/retroweb-proxy.py'
        spec = importlib.util.spec_from_file_location('language_proxy_test', path)
        proxy = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'bs4': SimpleNamespace(BeautifulSoup=None)}):
            spec.loader.exec_module(proxy)
        for lang, title, button, error in [('nl', b'RetroWEB zoeken', b'Zoeken / Openen', b'Zoeken is tijdelijk'), ('en', b'RetroWEB search', b'Search / Open', b'Search is temporarily')]:
            with patch.object(proxy.local_ui, 'language', return_value=lang):
                page = proxy.search_page()
                self.assertIn(title, page)
                self.assertIn(button, page)
                self.assertNotIn(b'chatgpt.retromodem', page.split(b'<hr>')[0])
                self.assertIn(b'RetroWEB</a> | <a href="http://chatgpt.retromodem/">ChatGPT</a>', page)
                with patch.object(proxy.urllib.request, 'urlopen', side_effect=OSError('offline')):
                    self.assertIn(error, proxy.search_page('Psion 5mx'))
