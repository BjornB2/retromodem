import shutil
import subprocess
from pathlib import Path
import unittest


class ContentLandmarkTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('php'), 'PHP unavailable')
    def test_main_landmarks_preserve_overviews_without_duplicate_articles(self):
        result = subprocess.run(['php', str(Path(__file__).with_name('content_extractor_landmarks.php'))],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

