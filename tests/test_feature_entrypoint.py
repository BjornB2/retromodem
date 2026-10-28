"""Feature flags must exit before any full-install system changes."""
import shutil
import subprocess
import tempfile
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class FeatureEntrypointTests(unittest.TestCase):
    def test_check_uses_only_the_feature_helper(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            shutil.copyfile(ROOT / 'install.sh', source / 'install.sh')
            (source / 'scripts').mkdir()
            (source / 'scripts/update-features.py').write_text(
                'import sys\nprint("FEATURE-ONLY " + " ".join(sys.argv[1:]))\n')
            result = subprocess.run(['sh', str(source / 'install.sh'), '--features-check'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'FEATURE-ONLY --check')

    def test_conflicting_flags_and_adapter_changes_rejected(self):
        for flags in (['--features-check', '--features-only'], ['--features-check', '--adapter', 'serial']):
            result = subprocess.run(['sh', str(ROOT / 'install.sh'), *flags], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
