#!/usr/bin/env python3
"""Check/apply a guarded feature-only update, without OS, driver or config changes."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

PROJECT = Path(__file__).resolve().parents[1]
# source path: (installed path, default mode, affected service, new file allowed)
FILES = {
    'web/web.py': ('usr/local/lib/retromodem/web.py', 0o644, 'retromodem-web.service', False),
    'web/chatgpt_web.py': ('usr/local/lib/retromodem/chatgpt_web.py', 0o644, 'retromodem-web.service', False),
    'scripts/retroweb-proxy.py': ('usr/local/lib/retromodem/retroweb-proxy.py', 0o755, 'retromodem-proxy.service', False),
    'proxy/retroweb/proxy.php': ('opt/retromodem/retroweb/proxy.php', 0o644, 'retromodem-retroweb-core.service', False),
    'proxy/retroweb/config.php': ('opt/retromodem/retroweb/config.php', 0o644, 'retromodem-retroweb-core.service', False),
    'proxy/retroweb/lib/PagePaginator.php': ('opt/retromodem/retroweb/lib/PagePaginator.php', 0o644, 'retromodem-retroweb-core.service', True),
    'scripts/diagnose': ('usr/local/sbin/retromodem-diagnose', 0o755, None, False),
}
MANIFEST = 'usr/local/share/retromodem/install-manifest.sha256'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def guarded_path(root, name):
    root = root.resolve()
    parts = Path(name).parts
    if not parts or Path(name).is_absolute() or any(part in ('.', '..') for part in parts):
        raise ValueError('Invalid update path')
    target = root.joinpath(*parts)
    for count in range(1, len(parts) + 1):
        if root.joinpath(*parts[:count]).is_symlink():
            raise ValueError(f'Refusing symlink: {name}')
    return target


def baseline(source):
    document = json.loads((source / 'config/feature-update-baseline.json').read_text())
    if document.get('schema_version') != 1 or not isinstance(document.get('files'), dict):
        raise ValueError('Invalid feature-update baseline')
    for name, hashes in document['files'].items():
        if name not in FILES or not isinstance(hashes, list) or any(not isinstance(h, str) or not re.fullmatch('[0-9a-f]{64}', h) for h in hashes):
            raise ValueError('Invalid feature-update baseline entry')
    return document['files']


def plan(root, source=PROJECT):
    root, source = Path(root).resolve(), Path(source).resolve()
    known = baseline(source)
    changes, conflicts = [], []
    for name, (relative, mode, service, allow_new) in FILES.items():
        incoming = guarded_path(source, name)
        target = guarded_path(root, relative)
        if not incoming.is_file():
            raise ValueError(f'Update source missing: {name}')
        if target.exists() and not target.is_file():
            raise ValueError(f'Installed target is not a file: {relative}')
        desired = incoming.read_bytes()
        old = target.read_bytes() if target.exists() else None
        if old == desired:
            continue
        if old is None and not allow_new:
            conflicts.append(relative + ' (missing existing installation file)')
        elif old is not None and sha(old) not in known.get(name, []):
            conflicts.append(relative + ' (unrecognized local version)')
        stat = target.stat() if target.exists() else None
        changes.append({'source': name, 'relative': relative, 'data': desired, 'old': old,
                        'mode': stat.st_mode & 0o777 if stat else mode,
                        'uid': stat.st_uid if stat else os.getuid(),
                        'gid': stat.st_gid if stat else os.getgid(), 'service': service})
    if conflicts:
        raise ValueError('Feature-update conflicts; nothing changed: ' + ', '.join(conflicts))
    return changes


def validate(source, changes):
    for change in changes:
        path = source / change['source']
        if path.suffix == '.py':
            ast.parse(change['data'].decode('utf-8'), filename=change['source'])
        elif path.suffix == '.php':
            if not shutil.which('php'):
                raise ValueError('PHP CLI is required to validate the feature update')
            result = subprocess.run(['php', '-l', str(path)], capture_output=True)
            if result.returncode:
                raise ValueError(f'PHP syntax validation failed: {change["source"]}')
        elif change['source'] == 'scripts/diagnose':
            result = subprocess.run(['sh', '-n', str(path)], capture_output=True)
            if result.returncode:
                raise ValueError('Shell syntax validation failed: scripts/diagnose')


def active(service):
    return subprocess.run(['systemctl', 'is-active', '--quiet', service], capture_output=True).returncode == 0


def restart(service):
    result = subprocess.run(['systemctl', 'restart', service], capture_output=True)
    if result.returncode or not active(service):
        raise RuntimeError(f'Service restart failed: {service}')


def write_atomic(path, data, mode, uid, gid):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.retromodem-update-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        if os.getuid() == 0:
            os.chown(temporary, uid, gid)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def manifest_change(root, changes):
    path = guarded_path(root, MANIFEST)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError('Installed checksum manifest is not a file')
    old = path.read_bytes()
    updates = {change['relative']: sha(change['data']) for change in changes}
    lines = []
    for line in old.decode('utf-8').splitlines():
        match = re.fullmatch(r'([0-9a-f]{64}) [ *](.+)', line)
        if not match:
            raise ValueError('Installed checksum manifest is malformed')
        relative = match[2]
        if relative in updates:
            line = updates.pop(relative) + '  ' + relative
        lines.append(line)
    lines.extend(digest + '  ' + relative for relative, digest in sorted(updates.items()))
    desired = ('\n'.join(lines) + '\n').encode()
    stat = path.stat()
    return {'source': None, 'relative': MANIFEST, 'data': desired, 'old': old,
            'mode': stat.st_mode & 0o777, 'uid': stat.st_uid, 'gid': stat.st_gid, 'service': None}


def run_update(root, source=PROJECT, apply=False, validator=validate, is_active=active, restart_service=restart,
               writer=write_atomic):
    root, source = Path(root).resolve(), Path(source).resolve()
    changes = plan(root, source)
    validator(source, changes)
    for change in changes:
        print('UPDATE ' + change['relative'])
    services = sorted({change['service'] for change in changes if change['service']})
    print(f'{len(changes)} changed feature file(s). Configuration, credentials, drivers and modem mode are preserved.')
    if not apply or not changes:
        print('Check only; no files or services changed.' if not apply else 'Already current; no changes needed.')
        return {'changed': len(changes), 'backup': None, 'services': []}
    running = [service for service in services if is_active(service)]
    manifest = manifest_change(root, changes)
    if manifest is not None:
        changes.append(manifest)
    backup_base = guarded_path(root, 'var/lib/retromodem/update-backups')
    backup_base.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix=time.strftime('%Y%m%d-%H%M%S-'), dir=backup_base))
    metadata = {'schema_version': 1, 'status': 'prepared', 'services': running, 'files': []}
    # Back up every original before the first installed-file mutation.
    for change in changes:
        row = {key: change[key] for key in ('source', 'relative', 'mode', 'uid', 'gid')}
        row.update(existed=change['old'] is not None, before_sha256=sha(change['old']) if change['old'] is not None else None,
                   after_sha256=sha(change['data']))
        metadata['files'].append(row)
        if change['old'] is not None:
            target = backup / 'files' / change['relative']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(change['old'])
            target.chmod(0o600)
    metadata_path = backup / 'metadata.json'
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
    modified = []
    try:
        # Reject a concurrent settings-independent source change before replace.
        for change in changes:
            target = guarded_path(root, change['relative'])
            current = target.read_bytes() if target.exists() else None
            if current != change['old']:
                raise RuntimeError(f'Installed file changed during update: {change["relative"]}')
        for change in changes:
            writer(guarded_path(root, change['relative']), change['data'], change['mode'], change['uid'], change['gid'])
            modified.append(change)
        for service in running:
            restart_service(service)
        metadata['status'] = 'applied'
        metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
    except Exception as error:
        rollback_errors = []
        for change in reversed(modified):
            try:
                target = guarded_path(root, change['relative'])
                if change['old'] is None:
                    target.unlink()
                else:
                    write_atomic(target, change['old'], change['mode'], change['uid'], change['gid'])
            except Exception:
                rollback_errors.append(change['relative'])
        for service in running if modified else []:
            try:
                restart_service(service)
            except Exception:
                rollback_errors.append(service)
        metadata.update(status='rollback-incomplete' if rollback_errors else 'rolled-back', rollback_errors=rollback_errors)
        metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
        raise RuntimeError(f'Feature update failed ({type(error).__name__}); '
                           f'{metadata["status"]}; backup: {backup}') from None
    print('Feature update applied. Backup: ' + str(backup))
    return {'changed': len(changes) - int(manifest is not None), 'backup': str(backup), 'services': running}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true', help='Check compatibility and show changes (default)')
    mode.add_argument('--apply', action='store_true', help='Apply the checked update and restart only affected active feature services')
    args = parser.parse_args()
    if args.apply and os.getuid() != 0:
        parser.exit(1, 'Apply the feature update as root through the installer.\n')
    try:
        run_update(Path('/'), apply=args.apply)
    except Exception as error:
        parser.exit(1, f'{error}\n')
