"""Small cookie-free proxy content settings for retro browsers."""
import re
import secrets
import threading
import time
import urllib.parse

try:
    import wifi_web as ui
except ModuleNotFoundError:
    from web import wifi_web as ui

PAGE_SIZES = ('12000', '18000', *(str(n * 1000) for n in range(25, 201, 25)),
              *(str(n * 1000) for n in range(250, 2001, 250)), '0')
PRESETS = {'600x180': 'Psion 5mx', '144x120': 'Palm classic',
           '288x256': 'Palm HiRes', '288x400': 'Palm T3', '512x342': 'Macintosh Plus'}
FIELDS = {'session', 'csrf', 'page_size', 'image_start', 'image_preset', 'image_width', 'image_height'}
_sessions = {}
_lock = threading.RLock()


def _new(peer):
    now = time.monotonic()
    with _lock:
        for key in list(_sessions):
            if _sessions[key]['expires'] <= now:
                del _sessions[key]
        while len(_sessions) >= 64:
            del _sessions[next(iter(_sessions))]
        token = secrets.token_hex(32)
        _sessions[token] = {'peer': peer, 'csrf': secrets.token_hex(32), 'expires': now + 900}
        return token, _sessions[token]['csrf']


def content_settings(page_size, image_start, width, height):
    """Validation shared with the full administration UI."""
    if page_size not in PAGE_SIZES or image_start not in {'inline', 'links', 'remember'}:
        raise ValueError('Invalid proxy content settings')
    if any(not re.fullmatch(r'[0-9]{1,4}', value) or not 16 <= int(value) <= 4096
           for value in (width, height)):
        raise ValueError('Invalid image dimensions')
    return {'RETROMODEM_PROXY_PAGE_SIZE': page_size, 'RETROMODEM_PROXY_IMAGE_START': image_start,
            'RETROMODEM_PROXY_IMAGE_WIDTH': str(int(width)), 'RETROMODEM_PROXY_IMAGE_HEIGHT': str(int(height))}


def _changes(form):
    if set(form) != FIELDS:
        raise ValueError('Invalid fields')
    preset = form['image_preset']
    if preset == 'custom':
        width, height = form['image_width'], form['image_height']
    elif preset in PRESETS:
        width, height = preset.split('x')
    else:
        raise ValueError('Invalid preset')
    return content_settings(form['page_size'], form['image_start'], width, height)


def serve(handler, *, save):
    config = handler.config()
    t = lambda nl, en: ui.local_ui.tr(config.get('RETROMODEM_LANGUAGE', 'nl'), nl, en)
    title = t('Webproxy instellen', 'Web proxy settings')
    peer = ui._peer(handler, config)
    reply = lambda body, code=200: ui._reply(handler, title, body, code)
    back = '<p><a href="/">' + t('Opnieuw openen', 'Start again') + '</a></p>'
    if peer is None:
        reply('<p>' + t('Alleen via de retroverbinding of met beheerderslogin.',
                       'Available only over the retro connection or with administrator authentication.') + '</p>', 403)
        return
    path = urllib.parse.urlsplit(handler.path).path
    message = ''
    if handler.command == 'POST' and path == '/save':
        origin = handler.headers.get('Origin')
        if origin:
            try:
                parsed = urllib.parse.urlsplit(origin)
                valid = (parsed.scheme == 'http' and parsed.hostname == 'proxy.retromodem'
                         and parsed.port in (None, 80, 8080) and not parsed.username and not parsed.password
                         and parsed.path in ('', '/') and not parsed.query and not parsed.fragment)
            except ValueError:
                valid = False
            if not valid:
                reply('<p>' + t('Ongeldige herkomst van het formulier.', 'Invalid form origin.') + '</p>', 403)
                return
        try:
            if handler.headers.get('Transfer-Encoding'):
                raise ValueError('Transfer encoding')
            form = ui._body_form(handler)
        except (ValueError, UnicodeError):
            reply('<p>' + t('Ongeldig formulier.', 'Invalid form.') + '</p>' + back, 400)
            return
        with _lock:
            item = _sessions.get(form.get('session', ''))
            valid = (item and item['peer'] == peer and item['expires'] > time.monotonic()
                     and secrets.compare_digest(form.get('csrf', '').encode('utf-8'), item['csrf'].encode('ascii')))
            if not valid:
                reply('<p>' + t('Formulier verlopen; open de pagina opnieuw.', 'Form expired; reopen the page.') + '</p>' + back, 403)
                return
            try:
                changes = _changes(form)
            except ValueError:
                reply('<p>' + t('Ongeldige instellingen. Breedte en hoogte moeten 16–4096 pixels zijn.',
                               'Invalid settings. Width and height must be 16–4096 pixels.') + '</p>' + back, 400)
                return
            del _sessions[form['session']]  # A repeated POST cannot save again.
        try:
            save(changes)
        except OSError:
            reply('<p>' + t('Opslaan is niet gelukt. Open de pagina opnieuw en probeer nogmaals.',
                           'Saving failed. Reopen the page and try again.') + '</p>' + back, 500)
            return
        config = handler.config()
        message = '<p><strong>' + t('Opgeslagen.', 'Saved.') + '</strong> ' + t(
            'Open de oorspronkelijke website opnieuw voor nieuwe paginadelen en afbeeldingsformaten.',
            'Reopen the original website for new page parts and image dimensions.') + '</p>'
    elif handler.command != 'GET' or path != '/':
        reply('<p>' + t('Pagina niet gevonden.', 'Page not found.') + '</p>', 404)
        return
    page = config.get('RETROMODEM_PROXY_PAGE_SIZE', '250000')
    if page not in PAGE_SIZES:
        page = '250000'
    start = config.get('RETROMODEM_PROXY_IMAGE_START', config.get('RETROMODEM_PROXY_IMAGE_MODE', 'inline'))
    if start not in {'inline', 'links', 'remember'}:
        start = 'inline'
    dimensions = []
    for key, fallback in (('WIDTH', '200'), ('HEIGHT', '150')):
        value = config.get('RETROMODEM_PROXY_IMAGE_' + key, config.get('RETROMODEM_68KPROXY_IMAGE_' + key, fallback))
        dimensions.append(value if re.fullmatch(r'[0-9]{1,4}', value) and 16 <= int(value) <= 4096 else fallback)
    width, height = dimensions
    def options(choices, selected):
        return ''.join('<option value="' + ui._escape(value, True) + '"' + (' selected' if value == selected else '') + '>' + ui._escape(label) + '</option>' for value, label in choices)
    page_options = [(value, t('Volledige pagina (kans op vol geheugen)', 'Entire page (may exhaust memory)') if value == '0' else str(int(value) // 1000) + ' kB') for value in PAGE_SIZES]
    contents = ('<p>' + t('Geschatte paginagrootte per deel:', 'Estimated page size per part:') +
                '<br><select name="page_size">' + options(page_options, page) + '</select></p><p>' +
                t('Dit is HTML plus uitgepakte afbeeldingen na conversie, geen downloadgrootte of gegarandeerde geheugenlimiet. Bij afbeeldingen als links telt alleen HTML. 250 kB is de standaard voor nieuwe installaties.',
                  'This is HTML plus decoded images after conversion, not download size or a guaranteed memory limit. With images as links only HTML counts. 250 kB is the default for new installations.') + '</p><p>' +
                t('Afbeeldingen bij nieuwe verbinding:', 'Images at new connection:') + '<br><select name="image_start">' +
                options((('inline', t('Afbeeldingen laten zien', 'Show images')), ('links', t('Als links', 'As links')), ('remember', t('Vorige keuze onthouden', 'Remember previous choice'))), start) + '</select></p><p>' +
                t('Deze startstand geldt vanaf de volgende PPP-verbinding. Op een geopende proxypagina kun je de huidige weergave bovenaan wisselen.',
                  'This starting mode applies from the next PPP connection. Change the current view at the top of an open proxy page.') + '</p><p>' +
                t('Afbeeldingsformaat:', 'Image size:') + '<br><select name="image_preset">' +
                options([('custom', t('Huidig / aangepast', 'Current / custom'))] + [(value, label + ' (' + value + ')') for value, label in PRESETS.items()], 'custom') + '</select></p><p>' +
                t('Een apparaatpreset vult bij opslaan de afmetingen in. Alleen bij Huidig / aangepast gelden onderstaande waarden (16–4096 pixels).',
                  'A device preset sets dimensions when saved. The values below apply only with Current / custom (16–4096 pixels).') + '</p><p>' +
                t('Maximale breedte:', 'Maximum width:') + '<br><input name="image_width" size="5" maxlength="4" value="' + width + '"><br>' +
                t('Maximale hoogte:', 'Maximum height:') + '<br><input name="image_height" size="5" maxlength="4" value="' + height + '"></p>')
    token, csrf = _new(peer)
    reply(message + '<p>' + t('Deze instellingen gelden ook in de beheerinterface. De verbinding blijft actief.',
                              'These settings are shared with administration. The connection stays active.') + '</p>' +
          ui._form('/save', token, contents, t('Opslaan', 'Save'), csrf) +
          '<p><a href="http://setup.retromodem/">' + t('Instellingen', 'Settings') +
          '</a> | <a href="http://start.retromodem/">' + t('Startpagina', 'Home') + '</a></p>')
