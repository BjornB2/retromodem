#!/usr/bin/python3
"""Small line-oriented ChatGPT BBS for RetroModem's Hayes phone book."""

from __future__ import annotations

import json
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import textwrap
import threading
import urllib.error
import urllib.request
from pathlib import Path

try:
    import openai_auth
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web"))
    import openai_auth

try:
    import chat_history
except ModuleNotFoundError:
    from web import chat_history
try:
    import network_tools
except ModuleNotFoundError:
    from web import network_tools
try:
    import local_ui
except ModuleNotFoundError:
    from web import local_ui

ADDRESS = os.environ.get("RETROMODEM_CHATGPT_ADDRESS", "127.0.0.1")
PORT = int(os.environ.get("RETROMODEM_CHATGPT_PORT", "2324"))
CONTINUE_BETWEEN_CALLS = os.environ.get("RETROMODEM_CHATGPT_CONTINUE", "0") == "1"
ALLOW_NETWORK_AGENT = os.environ.get("RETROMODEM_CHATGPT_AGENT", "0") == "1"
MAX_HISTORY_CHARS = 24000
INSTRUCTIONS = (
    "Je bent ChatGPT via RetroModem, een tekstterminal voor retrocomputers. "
    "Antwoord standaard in het Nederlands, beknopt en in platte tekst. Gebruik geen Markdown-tabellen. "
    "Regels mogen maximaal ongeveer 76 tekens lang zijn. Je mag webzoeken voor actuele informatie. "
    "Je hebt geen toegang tot lokale bestanden of beheer van de RetroModem. "
    "Gebruik netwerktools alleen wanneer de gebruiker daarom vraagt. Leesacties mogen direct; "
    "gebruik network_scan voor het vinden van apparaten of open poorten op het lokale netwerk; target leeg kiest automatisch het LAN. "
    "Gebruik geen losse pingrondes als vervanging. Noem ontbrekende apparaten niet met zekerheid afwezig. "
    "wijzigende HTTP- of SSH-acties vereisen altijd de lokaal afgedwongen bevestiging."
)


def instructions():
    if local_ui.language() == 'en':
        return INSTRUCTIONS.replace('Antwoord standaard in het Nederlands', 'Antwoord standaard in het Engels')
    return INSTRUCTIONS

NETWORK_TOOL = {
    "type": "function", "name": "network_action", "strict": True,
    "description": "Voer vanaf RetroModem een netwerkactie uit. Gebruik local_network voor de eigen hostnaam, IP-adressen, interfaces en routes. Gebruik SSH alleen voor andere netwerkhosts, nooit voor RetroModem zelf.",
    "parameters": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "operation": {"type": "string", "enum": ["local_network", "neighbors", "dns", "ping", "tcp", "traceroute", "http", "ssh"]},
            "target": {"type": "string", "description": "Hostnaam of IP-adres."},
            "port": {"type": "integer", "minimum": 1, "maximum": 65535},
            "url": {"type": "string", "description": "Volledige http(s)-URL."},
            "method": {"type": "string", "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"]},
            "body": {"type": "string"},
            "username": {"type": "string"},
            "command": {"type": "string", "description": "Opdracht op de externe SSH-host."},
        },
        "required": ["operation", "target", "port", "url", "method", "body", "username", "command"],
    },
}


def _run(argv: list[str], timeout: int = 25) -> str:
    completed = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=timeout, check=False)
    output = (completed.stdout + completed.stderr).strip()
    return f"exit={completed.returncode}\n{output[:12000]}"


def ssh_is_read_only(command: str) -> bool:
    normalized = " ".join(command.strip().lower().split())
    prefixes = ("cat ", "df", "free", "get ", "ip addr", "ip route", "journalctl",
                "list ", "ls", "pwd", "show ", "status", "systemctl status", "uname", "uptime", "who")
    return bool(normalized) and normalized.startswith(prefixes)


def perform_network_action(arguments: dict, confirm) -> str:
    operation = str(arguments.get("operation", ""))
    target = str(arguments.get("target", "")).strip()
    if operation == "local_network":
        addresses = _run(["/usr/sbin/ip", "-brief", "address", "show"], 10)
        routes = _run(["/usr/sbin/ip", "route", "show"], 10)
        return f"hostname={socket.gethostname()}\n\nInterfaces en adressen:\n{addresses}\n\nRoutes:\n{routes}"
    if operation == "neighbors":
        return _run(["/usr/sbin/ip", "neigh", "show"], 10)
    if operation in {"dns", "ping", "tcp", "traceroute", "ssh"} and (not target or target.startswith('-') or target in {"localhost", "127.0.0.1", "::1", "retromodem", "retromodem.local"}):
        return "Geweigerd: netwerktools mogen de RetroModem zelf niet beheren."
    try:
        if operation == "dns":
            return _run(["/usr/bin/getent", "ahosts", target], 15)
        if operation == "ping":
            return _run(["/usr/bin/ping", "-c", "3", "-W", "3", "--", target], 15)
        if operation == "traceroute":
            return _run([shutil.which('traceroute') or '/usr/sbin/traceroute', '-n', '-m', '12', '-w', '1', '-q', '1', target], 20)
        if operation == "tcp":
            port = int(arguments["port"])
            with socket.create_connection((target, port), timeout=8):
                return f"{target}:{port} is bereikbaar"
        if operation == "http":
            url = str(arguments.get("url", ""))
            method = str(arguments.get("method", "GET"))
            if not url.startswith(("http://", "https://")):
                return "Geweigerd: alleen http(s)-URL's zijn toegestaan."
            description = local_ui.tr(local_ui.language(), f"{method} uitvoeren op {url}?", f"Perform {method} on {url}?")
            if method not in {"GET", "HEAD"} and not confirm(description):
                return "Geweigerd door gebruiker."
            data = str(arguments.get("body", "")).encode() if method not in {"GET", "HEAD"} else None
            request = urllib.request.Request(url, data=data, method=method)
            request.add_header("Content-Type", "application/json")
            with urllib.request.urlopen(request, timeout=25) as response:
                content = response.read(12000).decode("utf-8", "replace")
                return f"HTTP {response.status}\n{content}"
        if operation == "ssh":
            username = str(arguments.get("username", "")).strip()
            command = str(arguments.get("command", "")).strip()
            port = int(arguments.get("port", 22))
            if not username or not command:
                return "SSH vereist gebruikersnaam en opdracht."
            description = local_ui.tr(local_ui.language(), f"SSH-opdracht op {username}@{target} uitvoeren: {command}?", f"Run SSH command on {username}@{target}: {command}?")
            if not ssh_is_read_only(command) and not confirm(description):
                return "Geweigerd door gebruiker."
            return _run(["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                         "-p", str(port), f"{username}@{target}", command], 40)
    except (OSError, ValueError, subprocess.TimeoutExpired, urllib.error.URLError) as error:
        return f"Netwerkactie mislukt: {error}"
    return "Onbekende netwerkactie."


def terminal_text(value: str) -> bytes:
    lines: list[str] = []
    for paragraph in value.replace("\r", "").split("\n"):
        if not paragraph:
            lines.append("")
        else:
            lines.extend(textwrap.wrap(paragraph, width=76, replace_whitespace=False,
                                       drop_whitespace=True) or [""])
    return ("\r\n".join(lines) + "\r\n").encode("cp437", "replace")


def choose_model() -> str:
    models = openai_auth.available_models()
    if not models:
        raise openai_auth.AuthError("Dit ChatGPT-account biedt geen geschikt model aan")
    preferred = os.environ.get("RETROMODEM_CHATGPT_MODEL", "")
    if preferred and any(item["slug"] == preferred for item in models):
        return preferred
    return models[0]["slug"]


def stream_answer(history: list[dict[str, str]], model: str, emit) -> str:
    token = openai_auth.access_token()
    payload = json.dumps({
        "model": model,
        "instructions": instructions(),
        "input": history,
        "tools": [{"type": "web_search"}],
        "store": False,
        "stream": True,
    }).encode("utf-8")
    request = urllib.request.Request("https://api.openai.com/v1/responses", data=payload)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    answer: list[str] = []
    completed = False
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                try:
                    event = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "response.output_text.delta":
                    delta = str(event.get("delta", ""))
                    answer.append(delta)
                    emit(delta)
                elif event_type == "response.failed":
                    error = event.get("response", {}).get("error", {})
                    raise openai_auth.AuthError(str(error.get("message") or error.get("code") or "antwoord mislukt"))
                elif event_type == "response.completed":
                    completed = True
    except urllib.error.HTTPError as error:
        detail = error.read(4096).decode("utf-8", "replace")
        raise openai_auth.AuthError(f"OpenAI gaf HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise openai_auth.AuthError(f"OpenAI is niet bereikbaar: {error}") from error
    if not completed:
        raise openai_auth.AuthError("De verbinding eindigde voordat het antwoord klaar was")
    return "".join(answer)


def agent_answer(history: list[dict[str, str]], model: str, emit, confirm) -> str:
    """Run a stateless Responses function-call loop for the optional network agent."""
    token = openai_auth.access_token()
    input_items: list[dict] = [dict(item) for item in history]
    tools = [{"type": "web_search"}, NETWORK_TOOL, network_tools.TOOL]
    for _ in range(8):
        payload = json.dumps({"model": model, "instructions": instructions(),
                              "input": input_items, "tools": tools,
                              "store": False, "stream": True}).encode("utf-8")
        request = urllib.request.Request("https://api.openai.com/v1/responses", data=payload)
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Content-Type", "application/json")
        try:
            output_by_index: dict[int, dict] = {}
            text_parts: list[str] = []
            with urllib.request.urlopen(request, timeout=180) as response:
                for raw in response:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    event = json.loads(line[6:])
                    event_type = event.get("type")
                    if event_type == "response.output_text.delta":
                        text_parts.append(str(event.get("delta", "")))
                    elif event_type == "response.output_item.done":
                        output_by_index[int(event.get("output_index", len(output_by_index)))] = event["item"]
                    elif event_type == "response.failed":
                        error = event.get("response", {}).get("error", {})
                        raise openai_auth.AuthError(str(error.get("message") or error.get("code") or "antwoord mislukt"))
        except urllib.error.HTTPError as error:
            detail = error.read(4096).decode("utf-8", "replace")
            raise openai_auth.AuthError(f"OpenAI gaf HTTP {error.code}: {detail}") from error
        except (urllib.error.URLError, json.JSONDecodeError) as error:
            raise openai_auth.AuthError(f"OpenAI is niet bereikbaar: {error}") from error
        output = [output_by_index[index] for index in sorted(output_by_index)]
        calls = [item for item in output if item.get("type") == "function_call"]
        if not calls:
            answer = "".join(text_parts)
            emit(answer)
            return answer
        input_items.extend(output)
        for call in calls:
            try:
                arguments = json.loads(call.get("arguments", "{}"))
            except json.JSONDecodeError:
                result = "Ongeldige toolargumenten."
            else:
                if call.get('name') == 'network_scan':
                    emit('\n' + local_ui.tr(local_ui.language(), 'Netwerk scannen...', 'Scanning network...') + '\n')
                    result = network_tools.scan(str(arguments.get('target', '')), str(arguments.get('ports', '')))
                elif call.get('name') == 'network_action':
                    result = perform_network_action(arguments, confirm)
                else:
                    result = 'Onbekende netwerktool.'
            input_items.append({"type": "function_call_output", "call_id": call["call_id"],
                                "output": result})
    raise openai_auth.AuthError("De agent gebruikte te veel opeenvolgende netwerkacties")


class ChatHandler(socketserver.StreamRequestHandler):
    def send(self, value: str) -> None:
        self.wfile.write(terminal_text(value))
        self.wfile.flush()

    def read_line(self) -> bytes | None:
        """Read and remotely echo one terminal line with DOS-style editing."""
        value = bytearray()
        while len(value) < 4096:
            byte = self.rfile.read(1)
            if not byte:
                return bytes(value) if value else None
            # A CR-terminated line may be followed by LF. Avoid probing for it
            # with a timeout: timing out a buffered socket reader can leave it
            # unusable for all later prompts on this connection.
            if getattr(self, "_swallow_lf", False):
                self._swallow_lf = False
                if byte == b"\n":
                    continue
            if byte in {b"\r", b"\n"}:
                if byte == b"\r":
                    self._swallow_lf = True
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                return bytes(value)
            if byte in {b"\x08", b"\x7f"}:
                if value:
                    value.pop()
                    self.wfile.write(b"\x08 \x08")
                    self.wfile.flush()
                continue
            if byte >= b" " and byte != b"\xff":
                value.extend(byte)
                self.wfile.write(byte)
                self.wfile.flush()
        return bytes(value)

    def handle(self) -> None:
        # Start every call on a clean ANSI screen. Unknown escape sequences are
        # harmless on simpler terminals; the following banner remains plain text.
        self.wfile.write(b"\x1b[2J\x1b[H")
        self.wfile.flush()
        mode = ("Vervolg gesprek - webzoeken beschikbaar" if CONTINUE_BETWEEN_CALLS
                else "Nieuw gesprek - webzoeken beschikbaar")
        if ALLOW_NETWORK_AGENT:
            mode += " - netwerkagent aan"
        self.send(f"RETROMODEM CHATGPT BBS\n{mode}\nTyp /help voor hulp of /quit om op te hangen.")
        if not openai_auth.connection_status()["connected"]:
            self.send("\nChatGPT is nog niet verbonden. Open de RetroModem-webinterface, ga naar Instellingen en kies Continue with ChatGPT.\n")
            return
        try:
            model = choose_model()
        except openai_auth.AuthError as error:
            self.send(f"\nChatGPT-verbinding niet bruikbaar: {error}\nOpen Instellingen om opnieuw te verbinden.")
            return
        if CONTINUE_BETWEEN_CALLS:
            history, history_revision = chat_history.update()
        else:
            history = []
        while True:
            self.wfile.write(b"\r\nJij> ")
            self.wfile.flush()
            raw = self.read_line()
            if raw is None:
                return
            if not raw:
                # Some serial terminals send one empty CR immediately after
                # CONNECT. Replace the old prompt in-place instead of leaving
                # two visible "Jij>" prompts at the start of the session.
                self.wfile.write(b"\x1b[1A\x1b[2K\r")
                self.wfile.flush()
                continue
            if len(raw) > 4096:
                self.send("Bericht te lang; maximaal 4096 tekens.")
                continue
            message = raw.decode("cp437", "replace").strip()
            if not message:
                continue
            command = message.lower()
            if command in {"/quit", "/exit", "quit", "exit"}:
                self.send("Tot ziens!")
                return
            if command == "/help":
                self.send("Schrijf een vraag en druk Enter. /new wist dit gesprek; /quit verbreekt de verbinding.")
                continue
            if command == "/new":
                history.clear()
                if CONTINUE_BETWEEN_CALLS:
                    history, history_revision = chat_history.update(reset=True)
                self.send("Nieuw gesprek gestart.")
                continue
            if CONTINUE_BETWEEN_CALLS:
                history, history_revision = chat_history.update()
            history.append({"role": "user", "content": message})
            while sum(len(item["content"]) for item in history) > MAX_HISTORY_CHARS and len(history) > 2:
                history.pop(0)
            self.wfile.write(b"\r\nChatGPT> ")
            self.wfile.flush()
            chunks: list[str] = []

            def emit(delta: str) -> None:
                chunks.append(delta)
                # Streaming small fragments directly is readable on slow links and
                # lets the terminal show that OpenAI is still answering.
                self.wfile.write(delta.replace("\n", "\r\n").encode("cp437", "replace"))
                self.wfile.flush()

            def confirm(description: str) -> bool:
                self.send(f"\nBEVESTIGING: {description}\nUitvoeren? typ ja of nee:")
                response = self.read_line()
                if response is None:
                    return False
                return response.decode("cp437", "replace").strip().lower() in {"ja", "j", "yes", "y"}

            try:
                answer = (agent_answer(history, model, emit, confirm) if ALLOW_NETWORK_AGENT
                          else stream_answer(history, model, emit))
            except (openai_auth.AuthError, OSError, BrokenPipeError) as error:
                self.send(f"\n\nFout: {error}")
                history.pop()
                continue
            self.wfile.write(b"\r\n")
            self.wfile.flush()
            history.append({"role": "assistant", "content": answer})
            if CONTINUE_BETWEEN_CALLS:
                chat_history.update(history, revision=history_revision)


class ChatServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True
    shared_history: list[dict[str, str]] = []
    history_lock = threading.Lock()


if __name__ == "__main__":
    with ChatServer((ADDRESS, PORT), ChatHandler) as server:
        server.serve_forever()
