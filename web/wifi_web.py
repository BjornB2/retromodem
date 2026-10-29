"""Cookie-free, small HTML Wi-Fi setup for trusted retro PPP clients."""
import html
import ipaddress
import secrets
import threading
import time
import urllib.parse

try:
    import local_ui
except ModuleNotFoundError:
    from web import local_ui

_sessions = {}
_lock = threading.RLock()
SESSION_TTL = 15 * 60
MAX_SESSIONS = 64
MAX_BODY = 4096


def _escape(value, quote=False):
    return html.escape(str(value), quote=quote).replace('&#x27;', '&#39;')


def _peer(handler, config):
    peer = handler.client_address[0]
    try:
        loopback = ipaddress.ip_address(peer).is_loopback
    except ValueError:
        loopback = False
    if loopback and handler.headers.get('X-Retromodem-Client') == '192.168.77.2':
        return '192.168.77.2'
    if peer == '192.168.77.2':
        return peer
    if getattr(handler, 'authenticated', lambda _: False)(config):
        return peer
    return None


def _new_session(peer):
    now = time.monotonic()
    token = secrets.token_hex(32)
    with _lock:
        for key in [key for key, value in _sessions.items() if value['expires'] <= now]:
            del _sessions[key]
        while len(_sessions) >= MAX_SESSIONS:
            del _sessions[next(iter(_sessions))]
        _sessions[token] = {'peer': peer, 'expires': now + SESSION_TTL, 'networks': {},
                            'actions': {path: secrets.token_hex(32) for path in ('/scan', '/connect')}}
    return token


def _session(token, peer):
    with _lock:
        item = _sessions.get(token)
        if not item or item['expires'] <= time.monotonic() or item['peer'] != peer:
            return None
        return item


def _personal(security):
    security = security.strip().upper()
    if security in ('', '--', 'OPEN', 'NONE'):
        return True
    if any(value in security for value in ('802.1X', 'EAP', 'ENTERPRISE', 'WEP', 'OWE')):
        return False
    return any(value in security.split() for value in ('WPA', 'WPA1', 'WPA2', 'WPA-PSK', 'WPA2-PSK'))


def _reply(handler, title, body, code=200):
    document = ('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 2.0//EN">'
                '<html><head><title>' + _escape(title) + '</title></head><body>'
                '<h1>' + _escape(title) + '</h1>' + body + '</body></html>')
    data = document.encode('iso-8859-1', 'xmlcharrefreplace')
    handler.send_response(code)
    handler.send_header('Content-Type', 'text/html; charset=iso-8859-1')
    handler.send_header('Content-Length', str(len(data)))
    handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
    handler.send_header('Pragma', 'no-cache')
    handler.send_header('Expires', '0')
    handler.send_header('Referrer-Policy', 'no-referrer')
    handler.send_header('X-Frame-Options', 'DENY')
    handler.end_headers()
    handler.wfile.write(data)


def _form(path, token, contents, label, csrf):
    return ('<form method="POST" action="' + path + '">'
            '<input type="hidden" name="session" value="' + token + '">'
            '<input type="hidden" name="csrf" value="' + csrf + '">'
            + contents + '<p><input type="submit" value="' + _escape(label, True) + '"></p></form>')


def _status(config, callback, tr):
    try:
        value = callback(config)
    except (OSError, RuntimeError, ValueError):
        value = {'state': 'unavailable', 'network_state': 'unknown', 'ssid': ''}
    state, ssid = value.get('state', 'disconnected'), value.get('ssid', '')
    network_state = value.get('network_state', state)
    if network_state == 'connected':
        text = tr('Verbonden met ', 'Connected to ') + _escape(ssid)
    elif network_state == 'hotspot':
        text = tr('Hotspot actief; geen externe wifi-verbinding.', 'Hotspot active; no external Wi-Fi connection.')
    elif network_state == 'unknown':
        text = tr('Wifi-status niet beschikbaar.', 'Wi-Fi status unavailable.')
    else:
        text = tr('Niet verbonden met wifi.', 'Not connected to Wi-Fi.')
    result = '<p>' + tr('Huidige verbinding: ', 'Current connection: ') + text + '</p>'
    if state == 'connecting':
        result += '<p>' + tr('Bezig met verbinden. Controleer zo de status.',
                             'Connecting. Check the status shortly.') + '</p>'
    elif state == 'failed':
        result += '<p>' + tr('De laatste verbindingspoging is mislukt. Controleer netwerk en wachtwoord en probeer opnieuw.',
                             'The last connection attempt failed. Check the network and password and try again.') + '</p>'
    return result


def _body_form(handler):
    raw_length = handler.headers.get('Content-Length', '')
    if not raw_length.isdigit() or not 0 < int(raw_length) <= MAX_BODY:
        raise ValueError('length')
    if handler.headers.get('Content-Type', '').split(';', 1)[0].strip().lower() != 'application/x-www-form-urlencoded':
        raise ValueError('type')
    raw = handler.rfile.read(int(raw_length))
    if len(raw) != int(raw_length):
        raise ValueError('length')
    values = urllib.parse.parse_qs(raw.decode('ascii'), keep_blank_values=True,
                                  encoding='iso-8859-1', errors='strict', max_num_fields=8)
    if any(len(items) != 1 for items in values.values()):
        raise ValueError('duplicates')
    return {key: items[0] for key, items in values.items()}


def serve(handler, *, status, scan, connect, diagnostic=None):
    """Callbacks receive config; connect starts asynchronously, never blocks for Wi-Fi."""
    config = handler.config()
    tr = lambda nl, en: local_ui.tr(config.get('RETROMODEM_LANGUAGE', 'en'), nl, en)
    title = tr('Wifi instellen', 'Wi-Fi setup')
    peer = _peer(handler, config)
    if peer is None:
        _reply(handler, title, '<p>' + tr('Alleen beschikbaar via de retroverbinding of met beheerderslogin.',
                                        'Available only over the retro connection or with administrator authentication.') + '</p>', 403)
        return
    parsed = urllib.parse.urlsplit(handler.path)
    method = handler.command
    if method == 'GET' and parsed.path == '/':
        token = _new_session(peer)
    elif method == 'GET' and parsed.path == '/status':
        args = urllib.parse.parse_qs(parsed.query)
        token = args.get('session', [''])[0]
        if not _session(token, peer):
            _reply(handler, title, '<p>' + tr('Deze pagina is verlopen. ', 'This page has expired. ') +
                   '<a href="/">' + tr('Opnieuw openen', 'Start again') + '</a></p>', 410)
            return
    elif method == 'POST' and parsed.path in ('/scan', '/connect'):
        origin = handler.headers.get('Origin')
        if origin:
            try:
                source = urllib.parse.urlsplit(origin)
                valid_origin = (source.scheme == 'http' and source.hostname == 'wifi.retromodem'
                                and source.port in (None, 80, 8080) and not source.username
                                and not source.password and source.path in ('', '/')
                                and not source.query and not source.fragment)
            except ValueError:
                valid_origin = False
            if not valid_origin:
                _reply(handler, title, '<p>' + tr('Ongeldige herkomst van het formulier.', 'Invalid form origin.') + '</p>', 403)
                return
        try:
            form = _body_form(handler)
        except (ValueError, UnicodeError):
            _reply(handler, title, '<p>' + tr('Ongeldig formulier.', 'Invalid form.') + '</p>', 400)
            return
        token = form.get('session', '')
        item = _session(token, peer)
        expected = item['actions'][parsed.path] if item else ''
        if not item or not secrets.compare_digest(form.get('csrf', '').encode('utf-8'), expected.encode('ascii')):
            if diagnostic is not None:
                diagnostic(config, 'form_expired')
            _reply(handler, title, '<p>' + tr('Formulier verlopen; open de pagina opnieuw.',
                                             'Form expired; reopen the page.') + ' [WIFI-FORM-EXPIRED]</p><p><a href="/">' + tr('Opnieuw openen', 'Start again') + '</a></p>', 403)
            return
    else:
        _reply(handler, title, '<p>' + tr('Pagina niet gevonden.', 'Page not found.') + '</p>', 404)
        return

    item = _session(token, peer)
    body = _status(config, status, tr)
    if method == 'POST' and parsed.path == '/scan':
        with _lock:
            item['networks'] = {}
        try:
            found = scan(config)
            choices = {}
            seen = set()
            for ssid, signal, security in found:
                if not isinstance(ssid, str) or not ssid or len(ssid.encode('utf-8')) > 32 or ssid in seen:
                    continue
                seen.add(ssid)
                choice = secrets.token_hex(8)
                choices[choice] = (ssid, str(security))
                if len(choices) >= 64:
                    break
            with _lock:
                if _session(token, peer) is not item:
                    raise ValueError('expired')
                item['networks'] = choices
        except (OSError, RuntimeError, ValueError) as error:
            choices = {}
            code = getattr(error, 'code', 'failed')
            reasons = {
                'timeout': tr('De wifi-scan duurde te lang.', 'The Wi-Fi scan timed out.'),
                'busy': tr('Er wordt al een wifi-bewerking uitgevoerd.', 'Another Wi-Fi operation is in progress.'),
                'not_allowed': tr('De wifi-radio staat scannen nu niet toe.', 'The Wi-Fi radio does not allow scanning right now.'),
                'unavailable': tr('De wifi-service is tijdelijk niet beschikbaar.', 'The Wi-Fi service is temporarily unavailable.'),
                'failed': tr('De wifi-service kon de scan niet voltooien.', 'The Wi-Fi service could not complete the scan.'),
            }
            if code not in reasons:
                code = 'failed'
            body += ('<p>' + tr('Scannen is niet gelukt. ', 'Scan failed. ') + reasons[code] +
                     ' [WIFI-SCAN-' + code.upper().replace('_', '-') + ']</p><p>' +
                     tr('Probeer Scan netwerken opnieuw. Noteer deze foutcode als het blijft gebeuren.',
                        'Try Scan networks again. Note this error code if the problem persists.') + '</p>')
        if choices:
            options = []
            for choice, (ssid, security) in choices.items():
                label = ssid + ' (' + security + ')'
                if not _personal(security):
                    label += tr(' - niet ondersteund', ' - unsupported')
                options.append('<option value="' + choice + '">' + _escape(label) + '</option>')
            contents = ('<p>' + tr('Netwerk:', 'Network:') + '<br><select name="network">' +
                        ''.join(options) + '</select></p><p>' + tr('Wachtwoord:', 'Password:') +
                        '<br><input type="password" name="password" size="24" maxlength="128"></p><p>' +
                        tr('Laat leeg voor een open netwerk. Alleen open wifi en WPA/WPA2 Personal worden ondersteund.',
                           'Leave empty for an open network. Only open Wi-Fi and WPA/WPA2 Personal are supported.') + '</p>')
            body += _form('/connect', token, contents, tr('Verbinden', 'Connect'), item['actions']['/connect'])
        elif 'Scannen is niet gelukt' not in body and 'Scan failed' not in body:
            body += '<p>' + tr('Geen netwerken gevonden.', 'No networks found.') + '</p>'
    elif method == 'POST' and parsed.path == '/connect':
        with _lock:
            selected = item['networks'].pop(form.get('network', ''), None)
            if selected:
                item['networks'] = {}
        if not selected:
            _reply(handler, title, '<p>' + tr('Ongeldige netwerkkeuze; scan opnieuw.', 'Invalid network choice; scan again.') + '</p>', 400)
            return
        ssid, security = selected
        if not _personal(security):
            _reply(handler, title, '<p>' + tr('Deze beveiliging wordt niet ondersteund. Gebruik open wifi of WPA/WPA2 Personal.',
                                             'This security is unsupported. Use open Wi-Fi or WPA/WPA2 Personal.') + '</p>', 400)
            return
        password = form.get('password', '')
        if len(password) > 128 or any(char in password for char in '\r\n\x00'):
            _reply(handler, title, '<p>' + tr('Ongeldig wachtwoord.', 'Invalid password.') + '</p>', 400)
            return
        try:
            connect(config, ssid, password)
            body = '<p>' + tr('Verbinding wordt gemaakt met ', 'Connecting to ') + _escape(ssid) + '.</p>'
            body += '<p>' + tr('De retroverbinding kan open blijven. Controleer zo de status.',
                               'The retro connection can stay open. Check the status shortly.') + '</p>'
        except (OSError, RuntimeError, ValueError):
            body = '<p>' + tr('Verbinden kon niet worden gestart. Scan opnieuw en probeer opnieuw.',
                               'Connection could not be started. Scan and try again.') + '</p>'
        finally:
            password = ''

    body += ('<p><a href="/status?session=' + token + '">' + tr('Status controleren', 'Check status') + '</a></p>')
    body += '<p>' + tr('Scannen kan even duren.', 'Scanning may take a moment.') + '</p>'
    body += _form('/scan', token, '', tr('Scan netwerken', 'Scan networks'), item['actions']['/scan'])
    body += '<p>' + tr('Dit is lokale HTTP; het wifi-wachtwoord wordt niet versleuteld verstuurd.',
                       'This is local HTTP; the Wi-Fi password is not sent encrypted.') + '</p>'
    body += '<p>' + tr('De wifi-inloggegevens worden lokaal op de Pi bewaard voor volgende verbindingen.',
                       'Wi-Fi credentials are saved locally on the Pi for future connections.') + '</p>'
    _reply(handler, title, body)
