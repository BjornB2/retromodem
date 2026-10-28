"""Small boot-scoped conversation store shared by the BBS and web processes."""
import fcntl
import json
import os
import secrets
import tempfile
from pathlib import Path

ROOT = Path('/var/lib/retromodem/chatgpt')
CONFIG = Path('/etc/retromodem/retromodem.env')
BOOT = Path('/proc/sys/kernel/random/boot_id')


def enabled(key='RETROMODEM_CHATGPT_CONTINUE'):
    value = os.environ.get(key, '0')
    try:
        for line in CONFIG.read_text().splitlines():
            if line.startswith(key + '='):
                value = line.split('=', 1)[1].strip().strip('\"\'')
    except OSError:
        pass
    return value == '1'


def boot_id():
    try:
        return BOOT.read_text().strip()
    except OSError:
        return 'local-tests'


def update(history=None, revision=None, reset=False):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (ROOT / 'history.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = ROOT / 'history.json'
        try:
            state = json.loads(path.read_text())
        except (OSError, ValueError):
            state = {}
        if state.get('boot') != boot_id() or reset:
            state = {'boot': boot_id(), 'revision': secrets.token_hex(16), 'history': []}
        if history is not None and (revision is None or revision == state['revision']):
            items = [dict(item) for item in history]
            while sum(len(i['content']) for i in items) > 24000 and len(items) > 2:
                del items[:2]
            state['history'] = items
            state['revision'] = secrets.token_hex(16)
        fd, temporary = tempfile.mkstemp(dir=ROOT, prefix='.history-')
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(state, output, ensure_ascii=False)
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return [dict(i) for i in state['history']], state['revision']
