"""Reload-page navigation follows the validated RetroModem UI language."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('php'), 'PHP unavailable')
class NavigationLanguageTests(unittest.TestCase):
    def test_browser_reload_does_not_need_an_on_page_link(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.php'
            shutil.copyfile(ROOT / 'proxy/retroweb/config.php', config)
            for language, expected in [('nl', 'Pagina opnieuw ophalen'), ('en', 'Reload page'), ('invalid', 'Reload page')]:
                code = "require $argv[1]; $_GET=['url'=>'https://example.org/article?lang=source','lang'=>$argv[2]]; echo renderNavigation();"
                result = subprocess.run(['php', '-r', code, str(config), language], capture_output=True, text=True,
                                        env=dict(os.environ, RETROMODEM_CONFIG_FILE=str(Path(directory) / 'none')))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual('', result.stdout)
