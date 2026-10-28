"""Offline bootstrap checks. A fake curl serves archives; no real install runs."""
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
REVISION = 'a' * 40


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.archive = self.root / 'fixture.tar.gz'
        self.archive_members([('retromodem/install.sh', b'#!/bin/sh\nexit 98\n')])
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ['PATH'],
                        FIXTURE_ARCHIVE=str(self.archive), MOCK_CURL_RECORD=str(self.root / 'curl-record'))
        for key in ('RETROMODEM_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN'):
            self.env.pop(key, None)
        curl = self.bin / 'curl'
        curl.write_text('''#!/usr/bin/env python3
import json, os, shutil, sys
config = sys.stdin.read()
args = sys.argv[1:]
open(os.environ['MOCK_CURL_RECORD'], 'w').write(json.dumps({
    'args': args, 'config': config,
    'token_in_environment': 'RETROMODEM_GITHUB_TOKEN' in os.environ}))
shutil.copyfile(os.environ['FIXTURE_ARCHIVE'], args[args.index('--output') + 1])
''')
        curl.chmod(0o755)

    def archive_members(self, entries):
        with tarfile.open(self.archive, 'w:gz') as archive:
            for name, data in entries:
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

    def invoke(self, *args):
        return subprocess.run(['sh', str(ROOT / 'bootstrap.sh'), *args],
                              env=self.env, capture_output=True, text=True)

    def test_help_and_invalid_ref_do_not_download(self):
        self.assertEqual(self.invoke('--help').returncode, 0)
        self.assertNotEqual(self.invoke('--ref', 'main').returncode, 0)
        self.assertFalse((self.root / 'curl-record').exists())

    def test_pinned_download_only_never_executes_installer(self):
        destination = self.root / 'source'
        result = self.invoke('--ref', REVISION, '--download-only', str(destination))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((destination / 'install.sh').exists())
        self.assertEqual((destination / '.retromodem-source-commit').read_text(), REVISION + '\n')
        again = self.invoke('--ref', REVISION, '--download-only', str(destination))
        self.assertNotEqual(again.returncode, 0)

    def test_token_uses_stdin_not_arguments_or_environment(self):
        import json
        token = 'github_pat_' + 'x' * 60
        self.env['RETROMODEM_GITHUB_TOKEN'] = token
        result = self.invoke('--ref', REVISION, '--download-only', str(self.root / 'source'))
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads((self.root / 'curl-record').read_text())
        self.assertIn(token, record['config'])
        self.assertNotIn(token, ' '.join(record['args']))
        self.assertFalse(record['token_in_environment'])
        self.assertNotIn(token, result.stdout + result.stderr)

    def test_rejects_unsafe_tar_paths_and_links(self):
        for index, name in enumerate(('../escape', '/absolute', 'repo/../../escape')):
            self.archive_members([('repo/install.sh', b'exit 98'), (name, b'bad')])
            result = self.invoke('--ref', REVISION, '--download-only', str(self.root / f'source{index}'))
            self.assertNotEqual(result.returncode, 0)
        with tarfile.open(self.archive, 'w:gz') as archive:
            member = tarfile.TarInfo('repo/install.sh')
            member.type = tarfile.SYMTYPE
            member.linkname = '/etc/passwd'
            archive.addfile(member)
        self.assertNotEqual(self.invoke('--ref', REVISION, '--download-only',
                                        str(self.root / 'linked')).returncode, 0)

    def test_token_file_must_be_private(self):
        token_file = self.root / 'token'
        token_file.write_text('github_pat_' + 'x' * 60)
        token_file.chmod(0o644)
        result = self.invoke('--ref', REVISION, '--token-file', str(token_file),
                             '--download-only', str(self.root / 'source'))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'curl-record').exists())

    def test_installer_receives_choices_without_download_credentials(self):
        import json
        installer = b'''#!/bin/sh
python3 - "$@" <<'PY'
import json, os, sys
open(os.environ['MOCK_INSTALL_RECORD'], 'w').write(json.dumps({
    'args': sys.argv[1:],
    'tokens': [name for name in ('RETROMODEM_GITHUB_TOKEN', 'GH_TOKEN', 'GITHUB_TOKEN', 'token') if name in os.environ]
}))
PY
'''
        self.archive_members([('repo/install.sh', installer)])
        self.env.update(RETROMODEM_GITHUB_TOKEN='github_pat_' + 'x' * 60,
                        GH_TOKEN='unused', GITHUB_TOKEN='unused', token='old-exported-value',
                        MOCK_INSTALL_RECORD=str(self.root / 'install-record'))
        sudo = self.bin / 'sudo'
        sudo.write_text('#!/bin/sh\nexec "$@"\n')
        sudo.chmod(0o755)
        result = self.invoke('--ref', REVISION, '--adapter', 'my018',
                             '--my018-wiring-confirmed', '--non-interactive')
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads((self.root / 'install-record').read_text())
        self.assertEqual(record['args'], ['--adapter', 'my018', '--my018-wiring-confirmed', '--non-interactive'])
        self.assertEqual(record['tokens'], [])


if __name__ == '__main__':
    unittest.main()
