import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('transfer_cleanup', Path(__file__).resolve().parents[1] / 'scripts/transfer.py')
transfer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(transfer)


class CleanupTests(unittest.TestCase):
    def test_only_temporary_upload_work_copies_are_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / 'work-123'
            work.mkdir()
            temporary = work / 'example.prc'
            temporary.write_bytes(b'copy')
            library = root / 'library'
            library.mkdir()
            original = library / 'example.prc'
            original.write_bytes(b'original')
            with patch.object(transfer, 'ROOT', root):
                transfer.cleanup_sent_upload(original)
                transfer.cleanup_sent_upload(temporary)
            self.assertTrue(original.exists())
            self.assertFalse(work.exists())

    def test_work_directory_outside_transfer_root_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / 'work-important'
            work.mkdir()
            original = work / 'example.prc'
            original.write_bytes(b'original')
            with patch.object(transfer, 'ROOT', root / 'transfers'):
                transfer.cleanup_sent_upload(original)
            self.assertTrue(original.exists())
