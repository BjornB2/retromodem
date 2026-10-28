import io
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch
from web import chatgpt_web


class Handler:
    path = '/'
    client_address = ('127.0.0.1', 1)
    command = 'GET'
    headers = {}
    def __init__(self, fields=None):
        self.wfile = io.BytesIO()
        self.rfile = io.BytesIO()
        self.response_headers = {}
        if fields:
            self.command = 'POST'
            body = urllib.parse.urlencode(fields).encode('ascii')
            self.rfile = io.BytesIO(body)
            self.headers = {'Content-Length': str(len(body))}
    def send_response(self, status): self.status = status
    def send_header(self, name, value): self.response_headers[name] = value
    def end_headers(self): pass
    def send_error(self, status, *args): self.status = status


class ChatWebTests(unittest.TestCase):
    def setUp(self):
        chatgpt_web._sessions.clear()
        self.enabled_patch = patch.object(chatgpt_web.chat_history, 'enabled', return_value=False)
        self.enabled_patch.start()
        self.addCleanup(self.enabled_patch.stop)
        self.language_patch = patch.object(chatgpt_web.local_ui, 'language', return_value='nl')
        self.language_patch.start()
        self.addCleanup(self.language_patch.stop)
        self.connected_patch = patch.object(chatgpt_web, 'connected', return_value=True)
        self.connected_patch.start()
        self.addCleanup(self.connected_patch.stop)

    def test_disconnected_get_and_stale_post_show_setup_without_conversation(self):
        self.connected_patch.stop()
        with patch.object(chatgpt_web, 'backend') as backend, patch.object(chatgpt_web.chat_history, 'update') as history:
            backend.return_value.openai_auth.connection_status.return_value = {'connected': False}
            for fields in (None, {'session': 'old-session', 'turn': 'old-turn', 'message': 'must not send'}):
                handler = Handler(fields)
                chatgpt_web.serve(handler)
                body = handler.wfile.getvalue()
                self.assertEqual(handler.status, 200)
                self.assertIn(b'ChatGPT is nog niet verbonden', body)
                self.assertIn(b'http://retromodem.local/settings', body)
                self.assertIn(b'Continue with ChatGPT', body)
                self.assertNotIn(b'<form', body)
                self.assertNotIn(b'must not send', body)
                self.assertNotIn(b'old-session', body)
                self.assertEqual(chatgpt_web._sessions, {})
                self.assertIn('no-store', handler.response_headers['Cache-Control'])
                self.assertEqual(handler.response_headers['Pragma'], 'no-cache')
                self.assertEqual(handler.response_headers['Expires'], '0')
            history.assert_not_called()
            backend.return_value.choose_model.assert_not_called()
            backend.return_value.stream_answer.assert_not_called()
            backend.return_value.agent_answer.assert_not_called()

    def test_disconnected_message_follows_language(self):
        with patch.object(chatgpt_web, 'connected', return_value=False), patch.object(chatgpt_web.local_ui, 'language', return_value='en'):
            handler = Handler()
            chatgpt_web.serve(handler)
            self.assertIn(b'ChatGPT is not connected yet', handler.wfile.getvalue())
            self.assertIn(b'laptop or phone', handler.wfile.getvalue())
            self.assertNotIn(b'<form', handler.wfile.getvalue())

    def test_fresh_get_is_empty_and_cache_disabled_despite_an_old_session(self):
        chatgpt_web._sessions['old'] = {'history': [{'role': 'assistant', 'content': 'previous private conversation'}],
                                      'time': chatgpt_web.time.monotonic(), 'busy': False}
        handler = Handler()
        chatgpt_web.serve(handler)
        self.assertNotIn(b'previous private conversation', handler.wfile.getvalue())
        self.assertIn(b'<form', handler.wfile.getvalue())
        self.assertIn(b'<meta http-equiv="Pragma" content="no-cache">', handler.wfile.getvalue())
        self.assertIn('no-store', handler.response_headers['Cache-Control'])
        self.assertIn('no-cache', handler.response_headers['Cache-Control'])
        self.assertEqual(handler.response_headers['Expires'], '0')

    def test_form_stream_escaping_history_and_duplicate_post(self):
        first = Handler()
        chatgpt_web.serve(first)
        text = first.wfile.getvalue().decode('ascii')
        sid = re.search('name="session" value="(.*?)"', text)[1]
        turn = re.search('name="turn" value="(.*?)"', text)[1]
        class Backend:
            def choose_model(self): return 'existing-model'
            def stream_answer(self, history, model, emit):
                emit("it's ")
                emit('<script>')
                emit('antwoord')
                return '<script>antwoord'
        fields = {'session': sid, 'turn': turn, 'message': '<vraag>'}
        with patch.object(chatgpt_web, 'backend', return_value=Backend()):
            response = Handler(fields)
            chatgpt_web.serve(response)
            self.assertIn(b'&lt;script&gt;antwoord', response.wfile.getvalue())
            self.assertIn(b'&lt;vraag&gt;', response.wfile.getvalue())
            self.assertIn(b"it's ", response.wfile.getvalue())
            self.assertNotIn(b'&#x27;', response.wfile.getvalue())
            rendered = response.wfile.getvalue()
            self.assertLess(rendered.index(b'<form'), rendered.index(b'&lt;script&gt;antwoord'))
            self.assertLess(rendered.index(b'&lt;script&gt;antwoord'), rendered.index(b'&lt;vraag&gt;'))
            self.assertEqual(len(chatgpt_web._sessions[sid]['history']), 2)
            repeat = Handler(fields)
            chatgpt_web.serve(repeat)
            rendered = repeat.wfile.getvalue()
            self.assertLess(rendered.index(b'&lt;script&gt;antwoord'), rendered.index(b'&lt;vraag&gt;'))
            self.assertIn(b'Geen nieuw bericht', repeat.wfile.getvalue())
            self.assertEqual(len(chatgpt_web._sessions[sid]['history']), 2)

    def test_expired_form_recovers_draft_without_starting_request(self):
        handler = Handler({'session': 'invalid', 'message': 'hello "<test>"'})
        with patch.object(chatgpt_web, 'backend') as backend:
            chatgpt_web.serve(handler)
            backend.assert_not_called()
        self.assertEqual(handler.status, 200)
        self.assertIn(b'Pagina opnieuw verbonden', handler.wfile.getvalue())
        self.assertIn(b'value="hello &quot;&lt;test&gt;&quot;"', handler.wfile.getvalue())
        self.assertNotIn('invalid', chatgpt_web._sessions)

    def test_language_changes_on_next_page_and_in_recovery(self):
        first = Handler()
        chatgpt_web.serve(first)
        self.assertIn(b'Nieuw gesprek', first.wfile.getvalue())
        self.language_patch.stop()
        with patch.object(chatgpt_web.local_ui, 'language', return_value='en'):
            english = Handler()
            chatgpt_web.serve(english)
            self.assertIn(b'New conversation', english.wfile.getvalue())
            self.assertIn(b'value="Send"', english.wfile.getvalue())
            recovered = Handler({'session': 'expired', 'message': 'hello'})
            chatgpt_web.serve(recovered)
            self.assertIn(b'Page reconnected', recovered.wfile.getvalue())
            self.assertNotIn(b'Pagina opnieuw', recovered.wfile.getvalue())

    def test_agent_confirmation_requires_explicit_yes_and_resumes(self):
        for decision, expected in [('Nee', False), ('Ja', True), ('No', False), ('Yes', True)]:
            chatgpt_web._sessions.clear()
            first = Handler()
            chatgpt_web.serve(first)
            text = first.wfile.getvalue().decode('ascii')
            sid = re.search('name="session" value="(.*?)"', text)[1]
            turn = re.search('name="turn" value="(.*?)"', text)[1]
            calls = []
            class Backend:
                def choose_model(self): return 'existing-model'
                def agent_answer(self, history, model, emit, confirm):
                    calls.append(confirm('Een testactie uitvoeren?'))
                    emit('toegestaan' if calls[-1] else 'geweigerd')
                    return 'klaar'
            with patch.object(chatgpt_web.chat_history, 'enabled', side_effect=lambda key='RETROMODEM_CHATGPT_CONTINUE': key == 'RETROMODEM_CHATGPT_AGENT'), patch.object(chatgpt_web, 'backend', return_value=Backend()), patch.object(chatgpt_web.local_ui, 'language', return_value='en' if decision in {'No', 'Yes'} else 'nl'):
                response = Handler({'session': sid, 'turn': turn, 'message': 'test'})
                chatgpt_web.serve(response)
                self.assertEqual(calls, [])
                self.assertIn(b'Confirmation required:' if decision in {'No', 'Yes'} else b'Bevestiging nodig:', response.wfile.getvalue())
                token = re.search(b'name="confirmation" value="(.*?)"', response.wfile.getvalue())[1].decode()
                resume = Handler({'session': sid, 'confirmation': token, 'decision': decision})
                chatgpt_web.serve(resume)
                self.assertEqual(calls, [expected])
                self.assertIn(b'toegestaan' if expected else b'geweigerd', resume.wfile.getvalue())

    def test_reopening_loads_shared_history_and_new_clears_it(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(chatgpt_web.chat_history, 'ROOT', Path(directory)), patch.object(chatgpt_web.chat_history, 'enabled', return_value=True):
            chatgpt_web.chat_history.update([{'role': 'user', 'content': 'eerder via BBS'}, {'role': 'assistant', 'content': 'onthouden'}])
            handler = Handler()
            chatgpt_web.serve(handler)
            self.assertIn(b'eerder via BBS', handler.wfile.getvalue())
            reset = Handler()
            reset.path = '/?new=1'
            chatgpt_web.serve(reset)
            self.assertNotIn(b'eerder via BBS', reset.wfile.getvalue())
            self.assertEqual(chatgpt_web.chat_history.update()[0], [])

    def test_old_answer_cannot_restore_history_after_reset_or_reboot(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(chatgpt_web.chat_history, 'ROOT', Path(directory)):
            store = chatgpt_web.chat_history
            _, revision = store.update()
            store.update(reset=True)
            store.update([{'role': 'assistant', 'content': 'oud'}], revision=revision)
            self.assertEqual(store.update()[0], [])
            store.update([{'role': 'assistant', 'content': 'voor reboot'}])
            with patch.object(store, 'boot_id', return_value='new-boot'):
                self.assertEqual(store.update()[0], [])
