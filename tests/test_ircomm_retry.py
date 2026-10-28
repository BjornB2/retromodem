"""Exercise the real search-retry patch, including synchronous completion."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = '''#include <assert.h>
#define HZ 100
#define DISCOVERY_DEFAULT_SLOTS 0
enum { IRCOMM_TTY_READY, IRCOMM_TTY_IDLE, IRCOMM_TTY_SEARCH,
       IRCOMM_TTY_CONNECT_INDICATION, IRCOMM_TTY_WD_TIMER_EXPIRED,
       IRCOMM_TTY_DETACH_CABLE };
struct cb { int state, timer; };
static struct cb *current;
static int requests, complete;
static void ircomm_tty_next_state(struct cb *s, int state) { s->state=state; }
static void ircomm_tty_start_watchdog_timer(struct cb *s, int timeout) { s->timer=timeout; }
static void irlmp_discovery_request(int slots) {
  requests++;
  if (complete) { current->state=IRCOMM_TTY_READY; current->timer=0; }
}
static void event(struct cb *self, int event) {
 switch(event) {
 case IRCOMM_TTY_CONNECT_INDICATION:
		ircomm_tty_next_state(self, IRCOMM_TTY_READY);
		break;
	case IRCOMM_TTY_WD_TIMER_EXPIRED:
#if 1
		/* Give up */
#else
		/* Try to discover any remote devices */
		ircomm_tty_start_watchdog_timer(self, 3*HZ);
		irlmp_discovery_request(DISCOVERY_DEFAULT_SLOTS);
#endif
		break;
	case IRCOMM_TTY_DETACH_CABLE:
		ircomm_tty_next_state(self, IRCOMM_TTY_IDLE);
  self->timer=0;
  break;
 }
}
int main(void) {
 struct cb self={IRCOMM_TTY_SEARCH,0}; current=&self;
 event(&self,IRCOMM_TTY_WD_TIMER_EXPIRED);
 assert(requests==1 && self.timer==3*HZ);
 event(&self,IRCOMM_TTY_WD_TIMER_EXPIRED);
 assert(requests==2 && self.state==IRCOMM_TTY_SEARCH);
 complete=1;
 event(&self,IRCOMM_TTY_WD_TIMER_EXPIRED);
 assert(requests==3 && self.state==IRCOMM_TTY_READY && self.timer==0);
 event(&self,IRCOMM_TTY_DETACH_CABLE);
 assert(self.state==IRCOMM_TTY_IDLE && self.timer==0);
 return 0;
}
'''


class IrcommRetryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc') and shutil.which('patch'), 'C compiler/patch unavailable')
    def test_retry_rearms_and_synchronous_connection_cancels_timer(self):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            source = tree / 'src/net/ircomm/ircomm_tty_attach.c'
            source.parent.mkdir(parents=True)
            source.write_text(SOURCE)
            result = subprocess.run(['patch', '--batch', '-p1', '-i',
                                     str(ROOT / 'patches/ircomm-retry-discovery.patch')],
                                    cwd=tree, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            binary = tree / 'retry-test'
            subprocess.run(['cc', str(source), '-o', str(binary)], check=True, capture_output=True)
            subprocess.run([str(binary)], check=True, capture_output=True)

    def test_build_applies_and_hashes_patch(self):
        build = (ROOT / 'scripts/build-irda').read_text()
        self.assertIn('patch -d "$source_dir" -p1', build)
        self.assertGreaterEqual(build.count('patches/ircomm-retry-discovery.patch'), 2)

    def test_shorter_interval_only_changes_six_search_waits(self):
        patch = (ROOT / 'patches/ircomm-search-interval.patch').read_text()
        removed = [line[1:] for line in patch.splitlines() if line.startswith('-') and not line.startswith('---')]
        added = [line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++')]
        self.assertEqual(removed, ['\t\tircomm_tty_start_watchdog_timer(self, 3*HZ);'] * 6)
        self.assertEqual(added, ['\t\tircomm_tty_start_watchdog_timer(self, HZ);'] * 6)
        self.assertEqual(patch.count('ircomm_tty_next_state(self, IRCOMM_TTY_SEARCH)'), 5)
        self.assertEqual(patch.count('Go back to search mode'), 3)
        self.assertIn('Connected states are never polled here', patch)
        build = (ROOT / 'scripts/build-irda').read_text()
        self.assertGreaterEqual(build.count('patches/ircomm-search-interval.patch'), 2)
        self.assertLess(build.index('patches/ircomm-retry-discovery.patch'),
                        build.index('patches/ircomm-search-interval.patch'))
