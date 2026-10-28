"""Apply the real tcpser patch and exercise Linux termios flag overlap."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Pinned upstream function, deliberately including the original bug.
FUNCTION = '''int ser_set_flow_control(int fd, int status) {
  struct termios tio;
  if(0 != tcgetattr(fd, &tio)) {
    ELOG(LOG_FATAL, "Could not get serial port attributes");
    return -1;
  }
  // turn all off.
  tio.c_cflag &= ~(IXON | IXOFF | CRTSCTS);
  tio.c_cflag |= status;
  if(0 != tcsetattr(fd, TCSANOW, &tio)) {
    ELOG(LOG_FATAL,"Could not set serial port attributes");
    return -1;
  }
  return 0;
}
'''

# Use actual Linux bit values even when tests run on macOS.
HARNESS = '''#include <assert.h>
#define IXON 0x400U
#define IXOFF 0x1000U
#define CRTSCTS 0x80000000U
#define CBAUD 0x100fU
#define TCSANOW 0
#define LOG_FATAL 0
#define ELOG(...) ((void)0)
struct termios { unsigned int c_cflag, c_iflag; };
static struct termios current;
static int tcgetattr(int fd, struct termios *t) { *t=current; return 0; }
static int tcsetattr(int fd, int action, const struct termios *t) { current=*t; return 0; }
'''
MAIN = '''
int main(void) {
  unsigned int speeds[] = {0x1002, 0x1001, 13}; /* 115200, 57600, 9600 */
  unsigned int modes[] = {0, CRTSCTS, IXON|IXOFF, CRTSCTS|IXON|IXOFF};
  for (unsigned int i=0; i<3; i++) {
    for (unsigned int j=0; j<4; j++) {
      current.c_cflag = speeds[i] | 0x8b0U | CRTSCTS;
      current.c_iflag = 1U | IXON | IXOFF;
      assert(ser_set_flow_control(1, modes[j]) == 0);
      assert((current.c_cflag & CBAUD) == speeds[i]);
      assert((current.c_cflag & CRTSCTS) == (modes[j] & CRTSCTS));
      assert((current.c_iflag & (IXON|IXOFF)) == (modes[j] & (IXON|IXOFF)));
      assert((current.c_iflag & 1U) == 1U);
      assert((current.c_cflag & 0x8b0U) == 0x8b0U);
    }
  }
  return 0;
}
'''


class TcpserFlowControlTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc') and shutil.which('patch'), 'C compiler/patch unavailable')
    def test_real_patch_preserves_speed_and_separates_flow_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / 'src').mkdir()
            source = tree / 'src/serial.c'
            source.write_text(HARNESS + FUNCTION + MAIN)
            patch = ROOT / 'patches/tcpser-flowcontrol-speed.patch'
            result = subprocess.run(['patch', '--batch', '-p1', '-i', str(patch)],
                                    cwd=tree, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            binary = tree / 'flow-test'
            subprocess.run(['cc', str(source), '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)

    def test_installer_applies_flow_patch_before_build(self):
        text = (ROOT / 'install.sh').read_text()
        self.assertLess(text.index('patches/tcpser-flowcontrol-speed.patch'),
                        text.index('make -C "$work_dir/tcpser"'))
