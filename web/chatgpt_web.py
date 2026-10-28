"""Cookie-free HTML 2.0 frontend to the existing ChatGPT BBS integration."""
import html
import importlib.util
import queue
import secrets
import threading
import time
import urllib.parse
from pathlib import Path
try:
    import chat_history
    import local_ui
except ModuleNotFoundError:
    from web import chat_history
    from web import local_ui

_sessions = {}
_lock = threading.Lock()
_backend = None


def reset_shared():
    chat_history.update(reset=True)
    with _lock:
        for session in _sessions.values():
            pending = session.get('confirmation')
            if pending:
                pending['event'].set()
        _sessions.clear()


def backend():
    global _backend
    with _lock:
        if _backend is None:
            path = Path(__file__).with_name('chatgpt-bbs.py')
            if not path.exists():
                path = Path(__file__).resolve().parents[1] / 'scripts/chatgpt-bbs.py'
            spec = importlib.util.spec_from_file_location('retromodem_chat_backend', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _backend = module
    return _backend


def write(handler, text):
    handler.wfile.write(text.encode('iso-8859-1', 'xmlcharrefreplace'))
    handler.wfile.flush()


def escape(text, quote=False):
    # HTML 2.0 clients understand decimal references, not &#x27;.
    return html.escape(text, quote=quote).replace('&#x27;', '&#39;')


def form(sid, turn, draft='', language='nl'):
    return ('<form method="POST" action="/">'
            '<input type="hidden" name="session" value="%s">'
            '<input type="hidden" name="turn" value="%s">'
            '<input type="text" name="message" size="35" maxlength="4000" value="%s"> '
            '<input type="submit" value="%s"></form>') % (sid, turn, escape(draft, quote=True), local_ui.tr(language, 'Versturen', 'Send'))


def serve(handler):
    language = local_ui.language()
    t = lambda nl, en: local_ui.tr(language, nl, en)
    if handler.client_address[0] not in {'127.0.0.1', '192.168.77.2'}:
        handler.send_error(403, t('ChatGPT is alleen beschikbaar via de modemverbinding', 'ChatGPT is only available through the modem connection'))
        return
    post = handler.command == 'POST'
    fields = {}
    if post:
        try:
            length = int(handler.headers.get('Content-Length', '0'))
            if not 0 < length <= 16000:
                raise ValueError()
            fields = urllib.parse.parse_qs(handler.rfile.read(length).decode('ascii'), encoding='iso-8859-1')
        except (ValueError, UnicodeError):
            handler.send_error(400, t('Ongeldig bericht', 'Invalid message'))
            return
    sid = fields.get('session', [''])[0]
    continues = chat_history.enabled()
    if not post and urllib.parse.parse_qs(urllib.parse.urlsplit(handler.path).query).get('new') == ['1']:
        if continues:
            reset_shared()
    shared, revision = chat_history.update() if continues else ([], None)
    with _lock:
        now = time.monotonic()
        for key, item in list(_sessions.items()):
            if now - item['time'] > 3600 and not item['busy']:
                del _sessions[key]
        session = _sessions.get(sid) if post else None
        recovered = post and session is None
        if session is None:
            if len(_sessions) >= 32:
                handler.send_error(503, t('Te veel gesprekken; probeer later opnieuw', 'Too many conversations; try again later'))
                return
            sid = secrets.token_hex(16)
            session = {'history': shared, 'turn': secrets.token_hex(16), 'time': now, 'busy': False}
            _sessions[sid] = session
        pending = session.get('confirmation')
        resumed = bool(post and pending and secrets.compare_digest(fields.get('confirmation', [''])[0], pending['token']))
        if resumed:
            pending['approved'] = fields.get('decision', [''])[0] in {'Ja', 'Yes'}
            session['confirmation'] = None
            pending['event'].set()
        message = fields.get('message', [''])[0].strip()[:4000]
        valid = post and not recovered and message and secrets.compare_digest(fields.get('turn', [''])[0], session['turn']) and not session['busy'] and not resumed
        if valid:
            session['busy'] = True
            session['turn'] = secrets.token_hex(16)
        session['time'] = now
        history = list(shared if continues else session['history'])
        if resumed:
            history = session['job']['history']
            message = session['job']['message']
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=iso-8859-1')
    handler.send_header('Cache-Control', 'no-store')
    handler.send_header('Connection', 'close')
    handler.end_headers()
    handler.close_connection = True
    try:
        write(handler, '<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN"><html><head><title>ChatGPT - RetroModem</title></head><body><b>ChatGPT</b> | <a href="/?new=1">' + t('Nieuw gesprek', 'New conversation') + '</a>')
        write(handler, form(sid, session['turn'], message if recovered else '', language))
        if valid or resumed:
            write(handler, '<p><b>ChatGPT:</b><br>')
            events = session['job']['events'] if resumed else queue.Queue()
            request_history = history + [{'role': 'user', 'content': message}]

            def confirm(description):
                pending = {'token': secrets.token_hex(16), 'event': threading.Event(), 'approved': False}
                with _lock:
                    session['confirmation'] = pending
                events.put(('confirm', (description, pending['token'])))
                pending['event'].wait(180)
                with _lock:
                    if session.get('confirmation') is pending:
                        session['confirmation'] = None
                return pending['approved'] and chat_history.enabled('RETROMODEM_CHATGPT_AGENT')

            def generate():
                try:
                    bbs = backend()
                    emit = lambda delta: events.put(('text', delta))
                    if chat_history.enabled('RETROMODEM_CHATGPT_AGENT'):
                        answer = bbs.agent_answer(request_history, bbs.choose_model(), emit, confirm)
                    else:
                        answer = bbs.stream_answer(request_history, bbs.choose_model(), emit)
                    with _lock:
                        session['history'] = (request_history + [{'role': 'assistant', 'content': answer}])[-20:]
                        while sum(len(e['content']) for e in session['history']) > 24000 and len(session['history']) > 2:
                            del session['history'][:2]
                    if continues and chat_history.enabled():
                        chat_history.update(session['history'], revision=revision)
                    events.put(('done', ''))
                except Exception:
                    events.put(('error', t('Antwoord ophalen mislukt. Controleer de ChatGPT-verbinding bij Instellingen.', 'Could not retrieve the answer. Check the ChatGPT connection in Settings.')))
                finally:
                    with _lock:
                        session['busy'] = False
            if not resumed:
                session['job'] = {'events': events, 'history': history, 'message': message, 'text': ''}
                threading.Thread(target=generate, daemon=True).start()
            else:
                write(handler, escape(session['job']['text']).replace('\n', '<br>'))
            while True:
                try:
                    kind, value = events.get(timeout=1)
                except queue.Empty:
                    write(handler, '<!-- wachten -->')
                    continue
                if kind == 'done':
                    break
                if kind == 'confirm':
                    description, token = value
                    write(handler, '</p><p><b>' + t('Bevestiging nodig:', 'Confirmation required:') + '</b><br>' + escape(description) + '</p>'
                          '<form method="POST" action="/"><input type="hidden" name="session" value="' + sid + '">'
                          '<input type="hidden" name="confirmation" value="' + token + '">'
                          '<input type="submit" name="decision" value="' + t('Ja', 'Yes') + '"> '
                          '<input type="submit" name="decision" value="' + t('Nee', 'No') + '"></form>'
                          '<p>' + t('Deze keuze is drie minuten geldig. Zonder bevestiging wordt de actie niet uitgevoerd.', 'This choice is valid for three minutes. Without confirmation the action will not be performed.') + '</p></body></html>')
                    return
                session['job']['text'] += value
                write(handler, escape(value).replace('\n', '<br>'))
                if kind == 'error':
                    break
            write(handler, '</p>')
            write(handler, '<p><b>' + t('Jij:', 'You:') + '</b><br>' + escape(message).replace('\n', '<br>') + '</p>')
        elif recovered:
            if fields.get('confirmation'):
                write(handler, '<p>' + t('De bevestiging is verlopen. De gevraagde actie is niet alsnog uitgevoerd. Stel je vraag opnieuw als je verder wilt.', 'The confirmation has expired. No further action was performed. Ask again if you want to continue.') + '</p>')
            else:
                write(handler, '<p>' + t('Pagina opnieuw verbonden. Je bericht staat nog in het invoerveld; druk op Versturen om verder te gaan.', 'Page reconnected. Your message is still in the input field; press Send to continue.') + '</p>')
        elif post:
            write(handler, '<p>' + t('Geen nieuw bericht verzonden. Gebruik het formulier hierboven.', 'No new message was sent. Use the form above.') + '</p>')
        for entry in reversed(history):
            write(handler, '<p><b>' + (t('Jij', 'You') if entry['role'] == 'user' else 'ChatGPT') + ':</b><br>' + escape(entry['content']).replace('\n', '<br>') + '</p>')
        write(handler, '</body></html>')
    except (BrokenPipeError, ConnectionResetError):
        pass
