"""Bounded NetworkManager Wi-Fi operations shared by both configuration UIs.

Passwords are stored only in NetworkManager's intended root-only profile;
never in argv, status or error messages. No PPP/modem/IrDA service is touched.
"""
import configparser
import fcntl
import io
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import tempfile
import time
import uuid

NMCLI = '/usr/bin/nmcli'
RUNTIME = Path('/run/retromodem')
PROFILES = Path('/etc/NetworkManager/system-connections')
_operation = threading.Lock()
_state_lock = threading.Lock()
_job = {'state': '', 'message': ''}
DIAGNOSTICS = Path('/var/lib/retromodem/wifi-diagnostics.json')
_diagnostic_lock = threading.Lock()


class WifiError(RuntimeError):
    def __init__(self, code):
        super().__init__('Wi-Fi operation failed')
        self.code = code


def record_event(config, event, *, code='', count=None, mode=None, duration=None):
    """Bounded, persistent, root-only diagnostics: never SSIDs or raw errors."""
    if event not in {'scan', 'form_expired'}:
        return
    if code not in {'', 'ok', 'empty', 'failed', 'timeout', 'not_allowed', 'unavailable', 'busy'}:
        code = 'failed'
    if mode is None:
        try:
            mode = _actual(_interface(config))['state']
        except (ValueError, RuntimeError, OSError):
            mode = 'unknown'
    if mode not in {'hotspot', 'connected', 'connecting', 'disconnected'}:
        mode = 'unknown'
    item = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'uptime_s': int(time.monotonic()), 'event': event, 'mode': mode, 'code': code}
    if isinstance(count, int):
        item['count'] = max(0, min(count, 64))
    if isinstance(duration, (int, float)):
        item['duration_s'] = round(max(0, min(duration, 120)), 2)
    temporary = None
    try:
        with _diagnostic_lock:
            DIAGNOSTICS.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(DIAGNOSTICS) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                entries = []
                if DIAGNOSTICS.exists() and not DIAGNOSTICS.is_symlink() and DIAGNOSTICS.stat().st_size < 65536:
                    try:
                        entries = json.loads(DIAGNOSTICS.read_text())
                    except (ValueError, OSError):
                        pass
                if not isinstance(entries, list):
                    entries = []
                with tempfile.NamedTemporaryFile(mode='w', dir=DIAGNOSTICS.parent,
                                                 prefix='.wifi-diagnostics-', delete=False) as output:
                    temporary = Path(output.name)
                    os.fchmod(output.fileno(), 0o600)
                    json.dump((entries + [item])[-64:], output)
                os.replace(temporary, DIAGNOSTICS)
    except OSError:
        pass  # Diagnostics must never prevent scanning or recovery.
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _interface(config):
    interface = config.get('RETROMODEM_WIFI_INTERFACE', 'wlan0')
    if not isinstance(interface, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,32}', interface):
        raise ValueError('Invalid Wi-Fi interface')
    return interface


def _run(*args, timeout=10, input=None):
    """Never surface process output or exceptions: they can contain secrets."""
    try:
        result = subprocess.run([NMCLI, *args], input=input, capture_output=True,
                                text=True, timeout=timeout, check=False,
                                env={**os.environ, 'LC_ALL': 'C'})
    except subprocess.TimeoutExpired:
        raise WifiError('timeout') from None
    except (OSError, subprocess.SubprocessError):
        raise WifiError('unavailable') from None
    if result.returncode:
        reason = (result.stderr or '').lower()
        code = 'not_allowed' if 'not allowed' in reason else 'failed'
        raise WifiError(code)
    return result.stdout


def _actual(interface):
    lines = _run('--escape', 'no', '-g', 'GENERAL.STATE,GENERAL.CON-UUID',
                 'device', 'show', interface).splitlines()
    state = lines[0] if lines else ''
    active_uuid = lines[1] if len(lines) > 1 else ''
    if not active_uuid or active_uuid == '--':
        return {'state': 'connecting' if state.startswith(('40 ', '50 ', '60 ', '70 ', '80 ', '90 ')) else 'disconnected',
                'ssid': '', 'uuid': ''}
    fields = _run('--escape', 'no', '-g', '802-11-wireless.ssid,802-11-wireless.mode',
                  'connection', 'show', 'uuid', active_uuid).splitlines()
    ssid = fields[0] if fields else ''
    mode = fields[1] if len(fields) > 1 else ''
    kind = 'hotspot' if mode == 'ap' else ('connected' if state.startswith('100 ') else 'connecting')
    return {'state': kind, 'ssid': ssid, 'uuid': active_uuid}


def status(config):
    _recover_stale()
    try:
        actual = _actual(_interface(config))
    except (ValueError, RuntimeError):
        return {'state': 'disconnected', 'ssid': '', 'message': 'Wi-Fi status unavailable'}
    with _state_lock:
        job = dict(_job)
    result = {'state': actual['state'], 'ssid': actual['ssid'], 'message': '',
              'network_state': actual['state']}
    if job['state'] in {'connecting', 'failed'}:
        result.update(state=job['state'], message=job['message'])
    return result


def _split_nmcli(line):
    fields, value, escaped = [], [], False
    for character in line:
        if escaped:
            value.append(character)
            escaped = False
        elif character == '\\':
            escaped = True
        elif character == ':':
            fields.append(''.join(value))
            value = []
        else:
            value.append(character)
    if escaped:
        value.append('\\')
    fields.append(''.join(value))
    return fields


def scan(config):
    interface = _interface(config)
    started = time.monotonic()
    if not _operation.acquire(blocking=False):
        record_event(config, 'scan', code='busy', duration=0)
        raise WifiError('busy')
    try:
        output = _run('-t', '--escape', 'yes', '-f', 'SSID,SIGNAL,SECURITY',
                      'device', 'wifi', 'list', 'ifname', interface, '--rescan', 'yes', timeout=20)
        networks = {}
        for line in output.splitlines():
            fields = _split_nmcli(line)
            if len(fields) != 3:
                continue
            ssid, signal, security = fields
            if not ssid or len(ssid.encode('utf-8')) > 32 or any(c in ssid for c in '\x00\r\n'):
                continue
            if ssid == config.get('RETROMODEM_AP_SSID', 'retromodem'):
                continue
            try:
                signal = max(0, min(100, int(signal)))
            except ValueError:
                continue
            if ssid not in networks or signal > networks[ssid][0]:
                networks[ssid] = (signal, security or 'open')
        rows = sorted(((ssid, *values) for ssid, values in networks.items()),
                      key=lambda row: (-row[1], row[0]))[:64]
        record_event(config, 'scan', code='ok' if rows else 'empty', count=len(rows),
                     duration=time.monotonic() - started)
        return rows
    except (RuntimeError, OSError, ValueError) as error:
        record_event(config, 'scan', code=getattr(error, 'code', 'failed'),
                     duration=time.monotonic() - started)
        raise
    finally:
        _operation.release()


def _set_job(state, message=''):
    with _state_lock:
        _job.update(state=state, message=message)


def _process_identity(pid):
    try:
        # stat's parenthesized command can contain spaces; fields after its
        # final ')' start with state (field 3), and starttime is field 22.
        started = Path('/proc/' + str(pid) + '/stat').read_text().rsplit(')', 1)[1].split()[19]
        boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        return boot + ':' + started
    except (OSError, IndexError):
        return ''


def _clear_stale_marker(marker):
    try:
        info = json.loads(marker.read_text())
        if info.get('owner') != 'wifi-network-v1' or not isinstance(info.get('pid'), int):
            return
        if not info.get('identity') or _process_identity(info['pid']) != info['identity']:
            marker.unlink()
            _set_job('failed', 'The previous Wi-Fi attempt was interrupted. Please try again.')
    except (OSError, ValueError, AttributeError):
        # Empty/unrecognized markers can belong to the legacy connect helper.
        pass


def _recover_stale():
    if not _operation.acquire(blocking=False):
        return
    try:
        if not RUNTIME.exists():
            return
        with (RUNTIME / 'wifi-config.lock').open('a') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return
            _clear_stale_marker(RUNTIME / 'wifi-transition')
    except OSError:
        pass
    finally:
        _operation.release()


def recover():
    """Startup hook: release only abandoned markers owned by this module.

    Once the marker is gone the existing AP fallback service can recover the
    radio normally, without requiring an HTTP request from a disconnected user.
    """
    _recover_stale()


def _write_profile(document, password, profile_uuid):
    """Persist only our freshly generated profile, atomically and mode 0600."""
    parser = configparser.ConfigParser(interpolation=None, delimiters=('=',), strict=True)
    parser.optionxform = str
    parser.read_string(document)
    if parser.get('connection', 'uuid') != profile_uuid:
        raise RuntimeError('Wi-Fi profile could not be prepared')
    if password:
        if not parser.has_section('wifi-security'):
            parser.add_section('wifi-security')
        # GKeyFile string escaping; newline/NUL credentials are rejected earlier.
        escaped = password.replace('\\', '\\\\').replace(' ', '\\s').replace('\t', '\\t')
        parser.set('wifi-security', 'key-mgmt', 'wpa-psk')
        parser.set('wifi-security', 'psk', escaped)
        parser.set('wifi-security', 'psk-flags', '0')
    buffer = io.StringIO()
    parser.write(buffer, space_around_delimiters=False)
    PROFILES.mkdir(parents=True, exist_ok=True)
    target = PROFILES / ('retromodem-' + profile_uuid + '.nmconnection')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=PROFILES,
                                         prefix='.retromodem-', delete=False) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(buffer.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def _restore(interface, old_uuid):
    if old_uuid:
        try:
            _run('--wait', '25', 'connection', 'up', 'uuid', old_uuid,
                 'ifname', interface, timeout=35)
            return
        except RuntimeError:
            pass
    try:
        result = subprocess.run(['/usr/local/lib/retromodem/configure-ap'],
                                capture_output=True, timeout=20, check=False)
        if result.returncode:
            return
        _run('--wait', '25', 'connection', 'up', 'id', 'retromodem-ap',
             'ifname', interface, timeout=35)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        pass


def _worker(interface, ssid, password, handle, marker):
    profile_uuid, old_uuid, created = str(uuid.uuid4()), '', False
    profile_path = None
    try:
        old_uuid = _actual(interface)['uuid']
        # Render the response before a single-radio AP/client transition.
        time.sleep(2)
        document = _run('--offline', 'connection', 'add', 'type', 'wifi', 'ifname', interface,
                        'con-name', 'retromodem-wifi-' + profile_uuid[:8], 'ssid', ssid,
                        'connection.uuid', profile_uuid, 'connection.autoconnect', 'no')
        profile_path = _write_profile(document, password, profile_uuid)
        created = True
        _run('connection', 'load', str(profile_path))
        args = ['--wait', '25', 'connection', 'up', 'uuid', profile_uuid, 'ifname', interface]
        _run(*args, timeout=35)
        actual = _actual(interface)
        if actual['state'] != 'connected' or actual['uuid'] != profile_uuid:
            raise RuntimeError('Wi-Fi operation failed')
        _run('connection', 'modify', 'uuid', profile_uuid, 'connection.autoconnect', 'yes')
        _set_job('connected')
    except Exception:
        # No exception text, subprocess output, password or credential object
        # is logged, saved or passed through to the browser.
        if created:
            try:
                _run('connection', 'delete', 'uuid', profile_uuid)
            except RuntimeError:
                pass
        if profile_path is not None:
            profile_path.unlink(missing_ok=True)
        _restore(interface, old_uuid)
        _set_job('failed', 'Connection failed. The previous network or setup hotspot was restored where possible.')
    finally:
        try:
            marker.unlink(missing_ok=True)
        finally:
            handle.close()
            _operation.release()


def connect(config, ssid, password):
    interface = _interface(config)
    if not isinstance(ssid, str) or not ssid or len(ssid.encode('utf-8')) > 32 or any(c in ssid for c in '\x00\r\n'):
        raise ValueError('Invalid network name')
    if not isinstance(password, str) or len(password.encode('utf-8')) > 256 or any(c in password for c in '\x00\r\n'):
        raise ValueError('Invalid Wi-Fi password')
    if password and not (8 <= len(password.encode('utf-8')) <= 63 or re.fullmatch(r'[0-9a-fA-F]{64}', password)):
        raise ValueError('Invalid Wi-Fi password')
    if not _operation.acquire(blocking=False):
        raise RuntimeError('Wi-Fi connection is in progress')
    handle = None
    marker = RUNTIME / 'wifi-transition'
    marked = False
    try:
        RUNTIME.mkdir(parents=True, exist_ok=True)
        handle = (RUNTIME / 'wifi-config.lock').open('a')
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _clear_stale_marker(marker)
        # Do not race a legacy helper already transitioning the same radio.
        marker_temp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=RUNTIME,
                                             prefix='.wifi-transition-', delete=False) as marker_handle:
                marker_temp = Path(marker_handle.name)
                json.dump({'owner': 'wifi-network-v1', 'pid': os.getpid(),
                           'identity': _process_identity(os.getpid())}, marker_handle)
                marker_handle.flush()
                os.fsync(marker_handle.fileno())
            # Atomic and exclusive publication: a crash cannot leave an
            # empty marker indistinguishable from the legacy helper's marker.
            os.link(marker_temp, marker)
        finally:
            if marker_temp is not None:
                marker_temp.unlink(missing_ok=True)
        marked = True
        _set_job('connecting', 'Connecting to the selected network')
        threading.Thread(target=_worker, args=(interface, ssid, password, handle, marker),
                         name='retromodem-wifi', daemon=True).start()
    except Exception:
        if marked:
            marker.unlink(missing_ok=True)
        if handle is not None:
            handle.close()
        _operation.release()
        _set_job('failed', 'Wi-Fi connection could not be started')
        raise RuntimeError('Wi-Fi connection could not be started') from None
