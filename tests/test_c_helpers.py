"""Check the actual installer compiler commands without installing binaries."""
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CHelperBuildTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cc"), "C compiler unavailable")
    def test_installer_compiler_commands_resolve_all_headers(self):
        text = (ROOT / "install.sh").read_text().replace("\\\n", " ")
        commands = [shlex.split(line.replace("$PROJECT_DIR", str(ROOT)))
                    for line in text.splitlines() if line.startswith("cc ")]
        self.assertEqual(len(commands), 2)
        for command in commands:
            with self.subTest(source=command[-1]):
                output_index = command.index("-o")
                del command[output_index:output_index + 2]
                # Linux supplies AF_IRDA; macOS does not. Preprocessing on
                # either platform still catches missing project/system headers.
                command.insert(1, "-fsyntax-only" if sys.platform.startswith("linux") else "-E")
                result = subprocess.run(command, capture_output=True, text=True, errors="replace")
                self.assertEqual(result.returncode, 0, result.stderr)
