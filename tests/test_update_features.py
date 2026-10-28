import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/update-features.py'
SPEC = importlib.util.spec_from_file_location('feature_update', SCRIPT)
update = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(update)


class FeatureUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'installed'
        self.source = Path(self.temp.name) / 'source'
        self.old = {}
        hashes = {}
        manifest = []
        for name, (relative, mode, service, allow_new) in update.FILES.items():
            incoming = self.source / name
            incoming.parent.mkdir(parents=True, exist_ok=True)
            incoming.write_bytes(b'VALUE = "new"\n' if name.endswith('.py') else b'new source\n')
            target = self.root / relative
            if not allow_new:
                target.parent.mkdir(parents=True, exist_ok=True)
                previous = ('old ' + name).encode()
                target.write_bytes(previous)
                target.chmod(0o640)
                self.old[relative] = previous
                hashes[name] = [update.sha(previous)]
                manifest.append(update.sha(previous) + '  ' + relative)
        baseline = self.source / 'config/feature-update-baseline.json'
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps({'schema_version': 1, 'files': hashes}))
        self.manifest = self.root / update.MANIFEST
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text('\n'.join(manifest) + '\n' + '0' * 64 + '  etc/untouched\n')
        self.original_manifest = self.manifest.read_bytes()
        self.sentinel = self.root / 'etc/retromodem/retromodem.env'
        self.sentinel.parent.mkdir(parents=True, exist_ok=True)
        self.sentinel.write_bytes(b'KEEP_PRIVATE=secret\n')
        self.restarts = []

    def run_update(self, **kwargs):
        options = dict(validator=lambda *_: None, is_active=lambda _: True,
                       restart_service=self.restarts.append)
        options.update(kwargs)
        with contextlib.redirect_stdout(io.StringIO()):
            return update.run_update(self.root, self.source, **options)

    def assert_original(self):
        for relative, old in self.old.items():
            self.assertEqual((self.root / relative).read_bytes(), old)
        new_relative = update.FILES['proxy/retroweb/lib/PagePaginator.php'][0]
        self.assertFalse((self.root / new_relative).exists())
        self.assertEqual(self.manifest.read_bytes(), self.original_manifest)
        self.assertEqual(self.sentinel.read_bytes(), b'KEEP_PRIVATE=secret\n')

    def test_check_has_no_side_effects(self):
        result = self.run_update()
        self.assertEqual(result['changed'], len(update.FILES))
        self.assertIsNone(result['backup'])
        self.assertFalse((self.root / 'var').exists())
        self.assertEqual(self.restarts, [])
        self.assert_original()

    def test_apply_backs_up_everything_before_writing_and_preserves_config(self):
        def writer(*args):
            backups = list((self.root / 'var/lib/retromodem/update-backups').iterdir())
            metadata = json.loads((backups[0] / 'metadata.json').read_text())
            self.assertEqual(len(metadata['files']), len(update.FILES) + 1)
            for relative, old in self.old.items():
                self.assertEqual((backups[0] / 'files' / relative).read_bytes(), old)
            update.write_atomic(*args)
        result = self.run_update(apply=True, writer=writer)
        for name, (relative, mode, _, new) in update.FILES.items():
            self.assertEqual((self.root / relative).read_bytes(), (self.source / name).read_bytes())
            self.assertEqual((self.root / relative).stat().st_mode & 0o777, mode if new else 0o640)
            self.assertIn(update.sha((self.source / name).read_bytes()) + '  ' + relative,
                          self.manifest.read_text())
        self.assertIn('0' * 64 + '  etc/untouched', self.manifest.read_text())
        self.assertEqual(len(self.restarts), 3)
        self.assertEqual(self.sentinel.read_bytes(), b'KEEP_PRIVATE=secret\n')
        self.assertEqual(json.loads((Path(result['backup']) / 'metadata.json').read_text())['status'], 'applied')
        self.restarts.clear()
        self.assertEqual(self.run_update(apply=True)['changed'], 0)
        self.assertEqual(self.restarts, [])

    def test_unknown_local_edit_rejected_without_backup(self):
        target = self.root / next(iter(update.FILES.values()))[0]
        target.write_bytes(b'local customization')
        for apply in (False, True):
            with self.assertRaisesRegex(ValueError, 'unrecognized local version'):
                self.run_update(apply=apply)
        self.assertFalse((self.root / 'var').exists())

    def test_validation_failure_prevents_writes(self):
        def invalid(*_):
            raise ValueError('invalid source')
        with self.assertRaisesRegex(ValueError, 'invalid source'):
            self.run_update(apply=True, validator=invalid)
        self.assert_original()
        self.assertFalse((self.root / 'var').exists())

    def test_write_failure_restores_existing_and_removes_new_file(self):
        def writer(path, *args):
            if path.name == 'retromodem-diagnose':
                raise OSError('disk failure')
            update.write_atomic(path, *args)
        with self.assertRaisesRegex(RuntimeError, 'rolled-back'):
            self.run_update(apply=True, writer=writer)
        self.assert_original()

    def test_restart_failure_rolls_back_manifest_and_all_features(self):
        attempts = []
        def restart(service):
            attempts.append(service)
            if len(attempts) == 1:
                raise RuntimeError('failed restart')
        with self.assertRaisesRegex(RuntimeError, 'rolled-back'):
            self.run_update(apply=True, restart_service=restart)
        self.assert_original()
        self.assertEqual(len(attempts), 4)

    def test_inactive_services_are_not_started(self):
        self.run_update(apply=True, is_active=lambda _: False)
        self.assertEqual(self.restarts, [])

    def test_symlink_target_is_rejected(self):
        target = self.root / next(iter(update.FILES.values()))[0]
        target.unlink()
        target.symlink_to(self.sentinel)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.run_update(apply=True)
        self.assertEqual(self.sentinel.read_bytes(), b'KEEP_PRIVATE=secret\n')

    def test_invalid_python_rejected_by_real_validator(self):
        path = self.source / 'web/chatgpt_web.py'
        path.write_text('def broken(\n')
        with self.assertRaises(SyntaxError):
            self.run_update(apply=True, validator=update.validate)
        self.assert_original()

    def test_missing_manifest_does_not_create_partial_manifest(self):
        self.manifest.unlink()
        self.run_update(apply=True)
        self.assertFalse(self.manifest.exists())


if __name__ == '__main__':
    unittest.main()
