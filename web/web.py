#!/usr/bin/python3
"""Small dependency-free configuration UI for the RetroModem appliance."""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
from email import policy
from email.parser import BytesParser
import os
import re
import secrets
import shlex
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import openai_auth
except ModuleNotFoundError:
    from web import openai_auth

CONFIG = Path("/etc/retromodem/retromodem.env")
PHONEBOOK = Path("/etc/retromodem/phonebook.json")
TRANSFERS = Path("/var/lib/retromodem/transfers")
RECEIVED = TRANSFERS / "received"
STATIC_ROOT = Path("/usr/local/share/retromodem/static")
LIBRARY_ROOT = Path("/var/lib/retromodem/software-library")
LIBRARY_META = LIBRARY_ROOT / "library.json"
SOFTWARE = {
    "eudoraweb-2.1": {
        "name": "EudoraWeb 2.1",
        "file": "software/EudoraWeb_2.1.prc",
        "protocol": "palm",
    },
    "mocha-telnet-3.0": {
        "name": "Mocha Telnet 3.0",
        "file": "software/MochaTelnet_3.0.prc",
        "protocol": "palm",
    },
}
ALLOWED_BITRATES = {"9600", "19200", "38400", "57600", "115200"}
CSRF_TOKENS: set[str] = set()
GUIDE_TARGETS = {"generic", "psion", "palm-old", "palm-new", "hp200lx", "win95", "win98", "winxp"}
LIBRARY_PROTOCOLS = {"download", "palm", "epoc", "xmodem", "ymodem", "zmodem"}
IR_ADAPTERS = {
    "ming-yuan-my018": {"name": "Ming Yuan MY018 · GPIO", "prefix": "MY018", "tty": "/dev/serial0", "dongle": ""},
    "mobile-action-ma620": {"name": "Mobile Action MA-620 · USB fallback", "prefix": "MA620", "tty": "auto", "dongle": "ma600"},
}


def pending_send() -> dict[str, str] | None:
    """Resolve only a web-created work copy, never an arbitrary posted path."""
    try:
        item = json.loads((TRANSFERS / "pending-send.json").read_text())
        token, name = item["token"], item["filename"]
        if not re.fullmatch(r"work-[a-f0-9]{12}", token) or Path(name).name != name:
            return None
        candidate = TRANSFERS / token / name
        if candidate.parent.resolve().parent != TRANSFERS.resolve() or candidate.is_symlink() or not candidate.is_file():
            return None
        return {"token": token, "filename": name, "protocol": item["protocol"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remember_send(path: Path, protocol: str) -> None:
    save = {"token": path.parent.name, "filename": path.name, "protocol": protocol}
    target = TRANSFERS / "pending-send.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(save), encoding="utf-8")
    os.replace(temporary, target)


def ir_adapter_id(config: dict[str, str]) -> str:
    value = config.get("RETROMODEM_ADAPTER", "ming-yuan-my018")
    return value if value in IR_ADAPTERS else "ming-yuan-my018"


def my018_power_enabled(config: dict[str, str]) -> bool:
    return config.get("RETROMODEM_MY018_POWER_CYCLE", "0") == "1"


def ir_adapter_settings(config: dict[str, str], language: str) -> str:
    active = ir_adapter_id(config)
    options = ''.join(f'<option value="{key}" {"selected" if key == active else ""}>{item["name"]}</option>' for key, item in IR_ADAPTERS.items())
    result = f'<label>{tr(language,"Infraroodadapter","Infrared adapter")}</label><select name="irda_adapter" id="irda-adapter">{options}</select>'
    for key, item in IR_ADAPTERS.items():
        prefix = item["prefix"]
        current = key == active
        physical = config.get(f"RETROMODEM_{prefix}_BITRATE", config.get("RETROMODEM_IRDA_BITRATE", "9600") if current else "9600")
        virtual = config.get(f"RETROMODEM_{prefix}_DIALUP_BITRATE", config.get("RETROMODEM_IRDA_DIALUP_BITRATE", "115200") if current else "115200")
        my018 = key == "ming-yuan-my018"
        controlled = my018_power_enabled(config)
        if my018:
            message = (tr(language, "Automatische snelheidskeuze via A/B/C en de transistorschakeling. Getest op 57k6: PPP met Palm IIIc en Psion 5mx, en Palm Beam naar de Palm. 38k4 is nog niet getest; 19k2 is alleen gedeeltelijk getest.", "Automatic speed selection through A/B/C and the transistor power switch. Tested at 57.6k: PPP with Palm IIIc and Psion 5mx, and Beam to Palm. 38.4k is untested; 19.2k was only partially tested.") if controlled else tr(language, "Vaste 9600-configuratie: bruggen A0/B0/C0. Hogere snelheden vereisen aangepaste bedrading, een voedingsschakelaar en de bijbehorende driver; sluit GPIO-draden niet aan op gesloten bruggen.", "Fixed 9600 configuration: A0/B0/C0 bridges. Higher rates require modified wiring, a power switch and the matching driver; never connect GPIO outputs to closed bridges."))
        else:
            message = tr(language,"Met deze MA-620 is alleen 9600 bit/s betrouwbaar gebleken. Hogere waarden zijn experimenteel.","Only 9600 bps has proven reliable with this MA-620. Higher settings are experimental.")
        rates = ("9600",) if my018 and not controlled else ("9600", "19200", "38400", "57600", "115200")
        labels = {"9600": "9600", "19200": tr(language, "19200 — gedeeltelijk getest", "19200 — partially tested"), "38400": tr(language, "38400 — nog niet getest", "38400 — untested"), "57600": tr(language, "57600 — getest, aanbevolen", "57600 — tested, recommended"), "115200": tr(language, "115200 — experimenteel, waarschuwing", "115200 — experimental, warning")}
        choices = ''.join(f'<option value="{rate}" {"selected" if rate == physical else ""}>{labels[rate] if my018 else rate}</option>' for rate in rates)
        virtual_choices = ''.join(f'<option value="{rate}" {"selected" if rate == virtual else ""}>{rate}</option>' for rate in ("9600", "19200", "38400", "57600", "115200"))
        warning = (f'<p class="notice warning" data-speed-warning="115200" role="status" {"" if physical == "115200" else "hidden"}>{tr(language,"115k2 is niet stabiel aangetoond: onze Palm Beam-tests leverden geen werkende verbinding op. Ook Psion PPP op 115k2 is niet bevestigd. Dit is geen algemene IrDA-limiet. Kies bij problemen 57k6 of 9600 en verbind opnieuw.","115.2k is not proven stable: our Palm Beam tests failed to connect. Psion PPP at 115.2k is also unconfirmed. This is not a general IrDA limit. If it fails, select 57.6k or 9600 and reconnect.")}</p>' if my018 else '')
        result += f'<div data-ir-profile="{key}"><h3>{item["name"]}</h3><p class="notice {"" if my018 else "warning"}">{message}</p><label>{tr(language,"Maximale fysieke IrDA-linksnelheid","Maximum physical IrDA link speed")}</label><select name="{prefix.lower()}_bitrate">{choices}</select>{warning}<p class="helper">{tr(language,"Ontdekking begint op 9600 bit/s. Daarna onderhandelen de apparaten een snelheid tot dit maximum. Een gewijzigde limiet geldt voor een nieuwe verbinding; toepassen verbreekt de huidige sessie.","Discovery starts at 9600 bps, then devices negotiate up to this maximum. A changed limit applies to a new connection; applying disconnects the current session.")}</p><label>{tr(language,"Virtuele poortsnelheid voor inbelmodem/Comms","Virtual port speed for dial-up modem/Comms")}</label><select name="{prefix.lower()}_dialup_bitrate">{virtual_choices}</select><p class="helper">{tr(language,"De virtuele poortsnelheid verandert de fysieke infraroodsnelheid niet. Instellingen worden per adapter bewaard.","The virtual port speed does not change the physical infrared speed. Settings are saved separately for each adapter.")}</p></div>'
    return result


def load_config() -> dict[str, str]:
    values = {k: v for k, v in os.environ.items() if k.startswith("RETROMODEM_")}
    try:
        lines = CONFIG.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = []
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"RETROMODEM_[A-Z0-9_]+", key):
            try:
                parsed = shlex.split(value, posix=True)
                values[key] = parsed[0] if parsed else ""
            except ValueError:
                continue
    return values


def save_config(changes: dict[str, str]) -> None:
    current = load_config()
    current.update(changes)
    lines = [f"{key}={shlex.quote(current[key])}" for key in sorted(current)]
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="retromodem.env.", dir=CONFIG.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        os.chmod(name, 0o600)
        os.replace(name, CONFIG)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def load_phonebook() -> list[dict[str, object]]:
    try:
        document = json.loads(PHONEBOOK.read_text(encoding="utf-8"))
        entries = document.get("entries", [])
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return []
    return entries if isinstance(entries, list) else []


def save_phonebook(entries: list[dict[str, object]]) -> None:
    PHONEBOOK.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="phonebook.json.", dir=PHONEBOOK.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"schema_version": 1, "entries": entries}, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.chmod(name, 0o600)
        os.replace(name, PHONEBOOK)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def load_library() -> dict[str, dict[str, str]]:
    try:
        document = json.loads(LIBRARY_META.read_text(encoding="utf-8"))
        items = document.get("items", {})
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return {}
    if not isinstance(items, dict):
        return {}
    return {str(key): value for key, value in items.items() if isinstance(value, dict)}


def save_library(items: dict[str, dict[str, str]]) -> None:
    LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="library.", suffix=".json", dir=LIBRARY_ROOT, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"schema_version": 1, "items": items}, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.chmod(name, 0o600)
        os.replace(name, LIBRARY_META)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def software_catalog() -> dict[str, dict[str, object]]:
    catalog = {key: dict(value, uploaded=False) for key, value in SOFTWARE.items()}
    catalog.update({key: dict(value, uploaded=True) for key, value in load_library().items()})
    return catalog


def library_filename(item: dict[str, object], source: Path) -> str:
    """Keep storage IDs private; retain the original name on the wire."""
    name = Path(str(item.get('original_name') or source.name)).name
    name = re.sub(r'[^A-Za-z0-9._ -]', '_', name)[:120]
    return name if name not in {'', '.', '..'} else 'bestand.bin'


def save_transfer_status(document: dict[str, object]) -> None:
    TRANSFERS.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix="status.", suffix=".json", dir=TRANSFERS, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False)
        os.chmod(name, 0o644)
        os.replace(name, TRANSFERS / "status.json")
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def transfer_process_alive(status: dict[str, object]) -> bool:
    try:
        pid = int(status.get("pid", 0))
        command = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ")
    except (FileNotFoundError, ValueError, PermissionError):
        return False
    return b"retromodem/transfer.py" in command


def phonebook_entry(form: dict[str, str]) -> dict[str, object]:
    number = form.get("number", "").strip()
    label = form.get("label", "").strip()
    kind = form.get("kind", "bbs")
    host = form.get("host", "").strip()
    try:
        port = int(form.get("port", "0"))
    except ValueError as error:
        raise ValueError("Ongeldige poort") from error
    if not re.fullmatch(r"[0-9*#]{1,32}", number):
        raise ValueError("Een telefoonnummer mag alleen cijfers, * en # bevatten")
    if not label or len(label) > 80:
        raise ValueError("Ongeldige naam")
    if kind not in {"ppp", "bbs"}:
        raise ValueError("Ongeldig type")
    if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host) or ".." in host:
        raise ValueError("Ongeldige hostnaam")
    if not 1 <= port <= 65535:
        raise ValueError("Ongeldige poort")
    return {"number": number, "label": label, "kind": kind, "host": host, "port": port}


def run(*args: str, timeout: int = 8, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, text=True, capture_output=True, timeout=timeout, check=False, env=env)
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        return subprocess.CompletedProcess(args, 127, "", str(error))


def service_active(name: str) -> bool:
    return run("/usr/bin/systemctl", "is-active", "--quiet", name).returncode == 0


def process_running(name: str) -> bool:
    return run("/usr/bin/pgrep", "-x", name).returncode == 0


def wifi_state(config: dict[str, str]) -> tuple[str, str]:
    interface = config.get("RETROMODEM_WIFI_INTERFACE", "wlan0")
    result = run("/usr/bin/nmcli", "-g", "GENERAL.STATE,GENERAL.CONNECTION", "device", "show", interface)
    fields = result.stdout.strip().splitlines()
    state = fields[0] if fields else "onbekend"
    profile = fields[1] if len(fields) > 1 else ""
    ssid = ""
    if profile and profile not in {"--", "—"}:
        ssid_result = run("/usr/bin/nmcli", "-g", "802-11-wireless.ssid", "connection", "show", profile)
        if ssid_result.returncode == 0:
            ssid = ssid_result.stdout.strip().splitlines()[0] if ssid_result.stdout.strip() else ""
    return state, ssid


def scan_wifi(config: dict[str, str]) -> list[tuple[str, int, str]]:
    interface = config.get("RETROMODEM_WIFI_INTERFACE", "wlan0")
    result = run(
        "/usr/bin/nmcli", "-t", "--escape", "yes",
        "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list",
        "ifname", interface, "--rescan", "yes", timeout=20,
    )
    networks: dict[str, tuple[int, str]] = {}
    for line in result.stdout.splitlines():
        # nmcli escapes literal colons as \:; split only unescaped separators.
        parts = re.split(r"(?<!\\):", line, maxsplit=2)
        if len(parts) != 3:
            continue
        ssid = parts[0].replace(r"\:", ":").replace(r"\\", "\\")
        if not ssid or ssid == config.get("RETROMODEM_AP_SSID", "retromodem"):
            continue
        try:
            signal = int(parts[1])
        except ValueError:
            signal = 0
        if ssid not in networks or signal > networks[ssid][0]:
            networks[ssid] = (signal, parts[2] or "open")
    return sorted(((ssid, *data) for ssid, data in networks.items()), key=lambda item: -item[1])


def usb_inventory() -> list[dict[str, str]]:
    """Return known and unknown USB adapters, including their tty node."""
    known = {
        "0df7:0620": ("Mobile Action MA-620", "irda"),
        "067b:2303": ("Prolific PL2303", "serial"),
    }
    ttys: dict[str, str] = {}
    for candidate in sorted(Path("/dev").glob("ttyUSB*")):
        info = run("/usr/bin/udevadm", "info", "--query=property", f"--name={candidate}").stdout
        properties = dict(line.split("=", 1) for line in info.splitlines() if "=" in line)
        usb_id = f"{properties.get('ID_VENDOR_ID', '')}:{properties.get('ID_MODEL_ID', '')}".lower()
        if usb_id != ":":
            ttys[usb_id] = str(candidate)
    found: list[dict[str, str]] = []
    for line in run("/usr/bin/lsusb").stdout.splitlines():
        match = re.search(r"ID ([0-9a-fA-F]{4}:[0-9a-fA-F]{4}) (.+)$", line)
        if not match:
            continue
        usb_id, description = match.group(1).lower(), match.group(2).strip()
        if usb_id not in known and usb_id not in ttys:
            continue
        name, transport = known.get(usb_id, (description, "other"))
        found.append({"usb_id": usb_id, "name": name, "description": description,
                      "transport": transport, "tty": ttys.get(usb_id, "—")})
    return found


def ipv4_addresses() -> list[str]:
    result = run("/usr/bin/hostname", "-I")
    return [address for address in result.stdout.split() if ":" not in address]


def transfer_status() -> dict[str, object]:
    try:
        status = json.loads((TRANSFERS / "status.json").read_text(encoding="utf-8"))
        return status if isinstance(status, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def tr(language: str, nl: str, en: str) -> str:
    return en if language == "en" else nl


def human_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} kB"
    return f"{size} bytes"


def transfer_estimate(size: int, protocol: str, config: dict[str, str]) -> str:
    """Return a deliberately conservative estimate for the active transport."""
    ir_only = protocol in {"palm", "epoc", "windows"}
    transport = "irda" if ir_only else config.get("RETROMODEM_TRANSPORT", "irda")
    if transport == "irda":
        configured = int(config.get("RETROMODEM_IRDA_BITRATE", "9600"))
        # This MA-620 specimen is only physically verified at 9600 bit/s;
        # the virtual 115200-baud IrCOMM setting does not raise air throughput.
        bitrate = min(configured, 9600) if ir_adapter_id(config) == "mobile-action-ma620" else configured
        medium = "IR"
    else:
        bitrate = int(config.get("RETROMODEM_SERIAL_BITRATE", "115200"))
        medium = tr(config.get("RETROMODEM_LANGUAGE", "nl"), "USB-serieel", "USB serial")
    efficiency = {"xmodem": 0.70, "ymodem": 0.78, "zmodem": 0.82,
                  "palm": 0.72, "epoc": 0.72, "windows": 0.72}.get(protocol, 0.75)
    seconds = max(1, int((size * 10 / max(1, bitrate) / efficiency) + (3 if transport == "irda" else 1) + 0.999))
    if seconds < 60:
        duration = f"±{seconds} sec"
    else:
        minutes, remainder = divmod(seconds, 60)
        duration = f"±{minutes}:{remainder:02d} min"
    return f"{duration} via {medium} ({bitrate} bit/s)"


def software_card(language: str, *, title: str, description: str, compatibility: str,
                  software_id: str = "", source: str = "") -> str:
    """Render one guide download with only actions the appliance can honour."""
    actions = []
    metadata = [compatibility]
    if software_id:
        item = software_catalog()[software_id]
        uploaded = bool(item.get("uploaded"))
        asset = ((LIBRARY_ROOT / Path(str(item.get("stored_name", ""))).name)
                 if uploaded else STATIC_ROOT / str(item["file"]))
        if asset.is_file():
            size = asset.stat().st_size
            metadata.append(human_size(size))
            if item.get("protocol") != "download":
                metadata.append(transfer_estimate(
                    size, str(item.get("protocol", "download")), load_config()
                ))
        href = (f'/library/download?id={urllib.parse.quote(software_id)}' if uploaded
                else f'/static/{item["file"]}')
        actions.append(
            f'<a class="button secondary" download href="{href}">'
            f'{tr(language,"Downloaden","Download")}</a>'
        )
        if item.get("protocol") != "download":
            send_label = (tr(language, "Via IR versturen", "Send over IR")
                          if item.get("protocol") in {"palm", "epoc"}
                          else tr(language, "Naar apparaat sturen", "Send to device"))
            actions.append(
                f'<form method="post" action="/transfer/library-send">'
                f'<input type="hidden" name="csrf" value="{{{{csrf}}}}">'
                f'<input type="hidden" name="software" value="{html.escape(software_id, quote=True)}">'
                f'<button class="primary" type="submit">{send_label}</button>'
                f'</form>'
            )
        if uploaded:
            actions.append(
                f'<form method="post" action="/guides/library-delete" '
                f'onsubmit="return confirm(\'{tr(language,"Dit bestand verwijderen?","Delete this file?")}\')">'
                f'<input type="hidden" name="csrf" value="{{{{csrf}}}}">'
                f'<input type="hidden" name="software" value="{html.escape(software_id, quote=True)}">'
                f'<button class="ghost" type="submit">{tr(language,"Verwijderen","Delete")}</button>'
                f'</form>'
            )
    if source:
        actions.append(
            f'<a class="button ghost" rel="noopener" href="{html.escape(source, quote=True)}">'
            f'{tr(language,"Projectpagina","Project page")}</a>'
        )
    return (
        f'<article class="software-card"><div><h3>{html.escape(title)}</h3>'
        f'<p>{description}</p><small class="helper">{" · ".join(metadata)}</small></div>'
        f'<div class="software-actions">{"".join(actions)}</div></article>'
    )


def uploaded_guide_sections(language: str) -> str:
    """Return escaped, per-guide HTML fragments for user-uploaded files."""
    grouped: dict[str, list[str]] = {target: [] for target in GUIDE_TARGETS}
    for software_id, item in load_library().items():
        target = str(item.get("target", "generic"))
        if target not in grouped:
            continue
        grouped[target].append(software_card(
            language,
            title=str(item.get("title", item.get("original_name", "Bestand"))),
            description=html.escape(str(item.get("description", ""))),
            compatibility=html.escape(str(item.get("compatibility", ""))),
            software_id=software_id,
        ))
    sections = {
        target: (f'<h3>{tr(language,"Zelf toegevoegde bestanden","Uploaded files")}</h3>'
                 f'<div class="software-list">{"".join(cards)}</div>')
        for target, cards in grouped.items() if cards
    }
    return json.dumps(sections, ensure_ascii=False).replace("<", "\\u003c")


def library_upload_form(language: str) -> str:
    return f"""<details class="card library-upload"><summary>{tr(language,'Softwarebibliotheek beheren','Manage software library')}</summary><p>{tr(language,'Voeg software of documentatie toe aan de handleiding van een apparaat.','Add software or documentation to a device guide.')}</p><form method="post" action="/guides/upload" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><label>{tr(language,'Bestand','File')}</label><input type="file" name="file" required><div class="grid"><div class="span-6"><label>{tr(language,'Titel','Title')}</label><input name="title" maxlength="80" required></div><div class="span-6"><label>{tr(language,'Hoort bij','Belongs to')}</label><select name="target"><option value="generic">{tr(language,'Algemeen','Generic')}</option><option value="psion">Psion 5mx</option><option value="palm-old">Palm OS 3.0/3.1</option><option value="palm-new">Palm OS 3.3–5.x</option><option value="hp200lx">HP 200LX</option><option value="win95">Windows 95</option><option value="win98">Windows 98</option><option value="winxp">Windows XP</option></select></div></div><label>{tr(language,'Korte uitleg','Short description')}</label><input name="description" maxlength="240" required><label>{tr(language,'Compatibiliteit of versie','Compatibility or version')}</label><input name="compatibility" maxlength="120" placeholder="Palm OS 4.1 · freeware"><label>{tr(language,'Actie naast downloaden','Action besides downloading')}</label><select name="protocol"><option value="download">{tr(language,'Alleen downloaden','Download only')}</option><option value="palm">Palm Beam (IrOBEX)</option><option value="epoc">Psion/EPOC EikonIr</option><option value="ymodem">YMODEM</option><option value="xmodem">XMODEM</option><option value="zmodem">ZMODEM</option></select><button class="primary" type="submit">{tr(language,'Toevoegen aan bibliotheek','Add to library')}</button></form></details>"""


def proxy_pagination_settings(page_size: str = "250000", page_images: str = "5") -> dict[str, str]:
    if page_size not in {"12000", "18000", "25000", "50000", "75000", "100000", "125000", "150000", "175000", "200000", "250000", "500000", "750000", "1000000", "1250000", "1500000", "1750000", "2000000", "0"}:
        raise ValueError("Invalid pagination settings")
    return {"RETROMODEM_PROXY_PAGE_SIZE": page_size}


def proxy_settings_card(language: str, config: dict[str, str]) -> str:
    mode = config.get("RETROMODEM_PROXY_MODE", config.get("RETROMODEM_68KPROXY_MODE", ""))
    if mode not in {"transparent", "manual"}:
        mode = "manual"
    default_exceptions = "retroweb.bjrno.com,frogfind.com,theoldnet.com,68k.news"
    configured_exceptions = config.get("RETROMODEM_PROXY_EXCEPTIONS", config.get("RETROMODEM_68KPROXY_EXCEPTIONS", "")) or default_exceptions
    extra_exceptions = html.escape("\n".join(value for value in re.split(r"[\s,]+", configured_exceptions) if value))
    image_start = config.get("RETROMODEM_PROXY_IMAGE_START", config.get("RETROMODEM_PROXY_IMAGE_MODE", "inline"))
    if image_start not in {"inline", "links", "remember"}:
        image_start = "inline"
    try:
        image_width = max(16, min(4096, int(config.get("RETROMODEM_PROXY_IMAGE_WIDTH", config.get("RETROMODEM_68KPROXY_IMAGE_WIDTH", "200")))))
        image_height = max(16, min(4096, int(config.get("RETROMODEM_PROXY_IMAGE_HEIGHT", config.get("RETROMODEM_68KPROXY_IMAGE_HEIGHT", "150")))))
    except ValueError:
        image_width, image_height = 200, 150
    page_size = config.get("RETROMODEM_PROXY_PAGE_SIZE", "250000")
    try:
        proxy_pagination_settings(page_size)
    except ValueError:
        page_size = "250000"
    page_options = ''.join(f'<option value="{value}" {"selected" if page_size == value else ""}>{label}</option>' for value, label in (
        ("12000", tr(language, "Klein — circa 12 kB", "Small — approximately 12 kB")),
        ("18000", tr(language, "Normaal — circa 18 kB", "Normal — approximately 18 kB")),
        *((str(n * 1000), f"{n} kB") for n in range(25, 201, 25)),
        *((str(n * 1000), f"{n} kB" + (tr(language, " (standaard)", " (default)") if n == 250 else "")) for n in range(250, 2001, 250)),
        ("0", tr(language, "Volledige pagina — kans op vol geheugen", "Entire page — may exhaust memory"))))
    pagination_controls = f'''<h3>{tr(language,'Pagina’s opdelen','Page splitting')}</h3><label>{tr(language,'Geschatte paginagrootte per deel','Estimated page size per part')}</label><select name="page_size">{page_options}</select><p class="helper">{tr(language,'Dit gaat niet over dataverkeer of de downloadgrootte, maar over de geschatte paginagrootte inclusief uitgepakte afbeeldingen. Bij Afbeeldingen laten zien tellen HTML en afbeeldingen samen mee: één byte per weergegeven pixel. Bij Als links telt alleen HTML. Een te grote losse afbeelding blijft als link beschikbaar. De browser gebruikt daarnaast werkgeheugen; dit is geen gegarandeerde geheugenlimiet. Open de oorspronkelijke website opnieuw na een wijziging.','This is not data transfer or download size: it estimates the page size including decoded images. With images shown, HTML and images count together: one byte per displayed pixel. In links view only HTML counts. A single oversized image remains available as a link. The browser also needs working memory; this is not a guaranteed memory limit. Reopen the original website after a change.')}</p>'''
    option = lambda value, label: f'<option value="{value}" {"selected" if mode == value else ""}>{label}</option>'
    presets = [("600x180", "Psion 5mx (640×240)"), ("144x120", "Palm classic (160×160)"),
               ("288x256", "Palm HiRes (320×320)"), ("288x400", "Palm T3 (320×480)"),
               ("512x342", tr(language, "Macintosh Plus / standaard", "Macintosh Plus / default"))]
    current_size = f"{image_width}x{image_height}"
    preset_options = "".join(f'<option value="{value}" {"selected" if value == current_size else ""}>{label}</option>' for value, label in presets)
    if current_size not in {value for value, _ in presets}:
        preset_options += f'<option value="" selected>{tr(language,"Aangepast","Custom")}</option>'
    image_options = ''.join(f'<option value="{value}" {"selected" if image_start == value else ""}>{label}</option>' for value, label in (("inline", tr(language,'Afbeeldingen laten zien','Show images')), ("links", tr(language,'Als links tonen','Show as links')), ("remember", tr(language,'Vorige keuze onthouden','Remember previous choice'))))
    advanced_controls = f'''<label>{tr(language,'Afbeeldingen bij starten','Images at session start')}</label><select name="image_start">{image_options}</select><p class="helper">{tr(language,'Start iedere nieuwe verbinding met afbeeldingen, met klikbare afbeeldingslinks of met je laatst gekozen weergave. Tijdens het browsen kun je bovenaan wisselen met Images: Inline | As links. Deze keuze blijft gelden tijdens die verbinding.','Start each new connection with images, clickable image links, or your last chosen view. While browsing, switch at the top using Images: Inline | As links. The choice remains active for that connection.')}</p><label>{tr(language,'Uitzonderingen','Exceptions')}</label><textarea name="exceptions" rows="8" placeholder="example.com\nretro.example.org">{extra_exceptions}</textarea><p class="helper">{tr(language,'Deze domeinen worden rechtstreeks en ongewijzigd doorgegeven. RetroWEB, FrogFind, The Old Net en 68k.news zijn standaard opgenomen.','These domains are passed through directly and unchanged. RetroWEB, FrogFind, The Old Net and 68k.news are included by default.')}</p><label>{tr(language,'Preset voor afbeeldingsformaat','Image size preset')}</label><select onchange="if(this.value){{const p=this.value.split('x');document.getElementById('proxy-image-width').value=p[0];document.getElementById('proxy-image-height').value=p[1];}}"><option value="">{tr(language,'Kies een apparaat…','Choose a device…')}</option>{preset_options}</select><p class="helper">{tr(language,'De apparaatpresets laten ruimte vrij voor de browserbalken, zodat de volledige afbeelding op het scherm past.','Device presets leave room for browser controls so the complete image fits on screen.')}</p><div class="grid" style="margin-bottom:18px"><div class="span-6"><label>{tr(language,'Maximale afbeeldingsbreedte','Maximum image width')}</label><input id="proxy-image-width" type="number" name="image_width" min="16" max="4096" step="1" value="{image_width}"></div><div class="span-6"><label>{tr(language,'Maximale afbeeldingshoogte','Maximum image height')}</label><input id="proxy-image-height" type="number" name="image_height" min="16" max="4096" step="1" value="{image_height}"></div></div>'''
    advanced_controls = advanced_controls.replace('Images: Inline | As links', tr(language,'Afbeeldingen: Afbeeldingen laten zien | Als links','Images: Inline | As links'))
    advanced_controls = (f'<div class="notice"><strong>{tr(language,"Zoeken:","Search:")}</strong> {tr(language,"open <code>http://search.retromodem</code>. Deze lokale pagina is alleen voor zoeken; resultaten openen als gewone websites via de proxy.","open <code>http://search.retromodem</code>. This local page is for search only; results open as ordinary websites through the proxy.")}</div>' + advanced_controls)
    return f"""<section class="card" id="webproxy"><h2>{tr(language,'Ingebouwde webproxy','Built-in web proxy')}</h2><p>{tr(language,'Gebaseerd op','Based on')} <a href="http://retroweb.bjrno.com">RetroWEB</a>, {tr(language,'het open webproxyproject voor oude browsers. De proxy haalt moderne HTTPS-pagina’s op, vereenvoudigt ze en levert ze als gewone HTTP-pagina.','the web proxy project for old browsers. The proxy fetches modern HTTPS pages, simplifies them and serves them as ordinary HTTP pages.')}</p><form method="post" action="/settings/proxy"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><label>{tr(language,'Proxystand','Proxy mode')}</label><select name="mode">{option('manual',tr(language,'Handmatig (standaard)','Manual (default)'))}{option('transparent',tr(language,'Automatisch','Automatic'))}</select><p class="helper"><strong>{tr(language,'Handmatig:','Manual:')}</strong> {tr(language,'stel in de browser HTTP-proxy <code>192.168.77.1</code>, poort <code>8080</code> in. Zonder browserinstelling gaat verkeer rechtstreeks.','configure HTTP proxy <code>192.168.77.1</code>, port <code>8080</code> in the browser. Without a browser setting, traffic remains direct.')}<br><strong>{tr(language,'Automatisch:','Automatic:')}</strong> {tr(language,'al het HTTP-webverkeer gaat vanzelf via de ingebouwde proxy.','all HTTP web traffic automatically uses the built-in proxy.')}</p>{pagination_controls}{advanced_controls}<div class="notice warning"><strong>{tr(language,'Niet voor gevoelige gegevens.','Not for sensitive data.')}</strong> {tr(language,'De proxy herschrijft inhoud en ondersteunt alleen GET-verzoeken; gebruik hem niet voor wachtwoorden, accounts of betalingen.','The proxy rewrites content and supports GET requests only; do not use it for passwords, accounts or payments.')}</div><button class="primary" type="submit">{tr(language,'Proxy-instellingen opslaan','Save proxy settings')}</button></form></section>"""


def chatgpt_settings_card(language: str, config: dict[str, str]) -> str:
    status = openai_auth.connection_status()
    continues = config.get("RETROMODEM_CHATGPT_CONTINUE", "0") == "1"
    allows_agent = config.get("RETROMODEM_CHATGPT_AGENT", "0") == "1"
    if status["connected"]:
        account = html.escape(str(status["email"] or tr(language, "Verbonden account", "Connected account")))
        action = f"""<div class="notice status-row" style="flex-wrap:wrap;margin-bottom:18px"><div><strong>{tr(language,'Verbonden','Connected')}</strong>{account}</div>
<form method="post" action="/openai/disconnect" style="margin:0"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><button class="danger" style="margin:0" type="submit">{tr(language,'ChatGPT loskoppelen','Disconnect ChatGPT')}</button></form></div>
<p>{tr(language,'Bel <code>5559999</code> voor ChatGPT met webzoeken, of gebruik de webversie hieronder.','Dial <code>5559999</code> for ChatGPT with web search, or use the web version below.')}</p>"""
    else:
        action = f"""<p>{tr(language,'Verbind een ChatGPT Plus- of Pro-account zonder API-key. De toestemming geldt alleen voor antwoorden via de Responses API en geeft geen toegang tot je bestaande ChatGPT-gesprekken.','Connect a ChatGPT Plus or Pro account without an API key. Permission applies only to Responses API answers and does not expose your existing ChatGPT conversations.')}</p>
<form method="post" action="/openai/start"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><button class="primary" type="submit">Continue with ChatGPT</button></form>"""
    conversation = f"""<form class="form-section" method="post" action="/settings/chatgpt"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><input type="hidden" name="continue_conversation" value="0"><input type="hidden" name="allow_agent" value="0"><label><input name="continue_conversation" type="checkbox" value="1" style="width:auto;min-height:auto" {'checked' if continues else ''}> {tr(language,'Gesprek voortzetten tussen oproepen','Continue conversation between calls')}</label><small class="helper">{tr(language,'Uit: iedere oproep begint een nieuw gesprek. Aan: de geschiedenis blijft in het geheugen tot /new, een herstart of het uitschakelen van deze optie.','Off: every call starts a new conversation. On: history remains in memory until /new, a restart, or disabling this option.')}</small><label><input name="allow_agent" type="checkbox" value="1" style="width:auto;min-height:auto" {'checked' if allows_agent else ''}> {tr(language,'Netwerkagent toestaan','Allow network agent')}</label><small class="helper">{tr(language,'Geeft ChatGPT netwerktools voor DNS, ping, poorttests, HTTP/API en SSH. Voor wijzigende acties vraagt de terminal eerst ja/nee.','Gives ChatGPT network tools for DNS, ping, port checks, HTTP/API and SSH. The terminal asks yes/no before mutating actions.')}</small><button type="submit">{tr(language,'ChatGPT-opties opslaan','Save ChatGPT options')}</button></form>"""
    web_help = tr(language, 'Open <a href="http://chatgpt.retromodem">http://chatgpt.retromodem</a> voor de webversie, ook zonder proxyinstelling. Werkt met eenvoudige HTML-formulieren, zonder JavaScript of cookies. Gesprekken blijven maximaal een uur in het geheugen; een herstart wist ze. Kies Nieuw gesprek om opnieuw te beginnen. Verbind PPP opnieuw als de naam nog niet wordt gevonden.', 'Open <a href="http://chatgpt.retromodem">http://chatgpt.retromodem</a> for the web version, also without a configured proxy. Uses basic HTML forms without JavaScript or cookies. Conversations remain in memory for up to one hour; restarting clears them. Select New conversation to start again. Reconnect PPP if the name cannot be resolved.')
    conversation = conversation.replace('Gesprek voortzetten tussen oproepen', 'Gesprek voortzetten in web en BBS').replace('Continue conversation between calls', 'Continue conversation in web and BBS')
    conversation = conversation.replace('Uit: iedere oproep begint een nieuw gesprek. Aan: de geschiedenis blijft in het geheugen tot /new, een herstart of het uitschakelen van deze optie.', 'Uit: iedere oproep of nieuw geopende webpagina begint een nieuw gesprek. Aan: web en BBS hervatten hetzelfde gesprek tot Nieuw gesprek, /new, een reboot of het uitschakelen van deze optie. Bij lange gesprekken vervallen de oudste berichten.')
    conversation = conversation.replace('Off: every call starts a new conversation. On: history remains in memory until /new, a restart, or disabling this option.', 'Off: each call or newly opened web page starts a new conversation. On: web and BBS resume the same conversation until New conversation, /new, a reboot, or disabling this option. Long conversations drop the oldest messages.')
    conversation = conversation.replace('Voor wijzigende acties vraagt de terminal eerst ja/nee.', 'Voor wijzigende acties vraagt de terminal of webpagina eerst ja/nee.').replace('The terminal asks yes/no before mutating actions.', 'The terminal or web page asks yes/no before mutating actions.')
    conversation = conversation.replace('netwerktools voor DNS, ping, poorttests, HTTP/API en SSH.', 'netwerktools voor het vinden van apparaten, lokale poortscans, DNS, ping, traceroute, HTTP/API en SSH.').replace('network tools for DNS, ping, port checks, HTTP/API and SSH.', 'network tools for device discovery, local port scans, DNS, ping, traceroute, HTTP/API and SSH.')
    web_help = web_help.replace('Gesprekken blijven maximaal een uur in het geheugen; een herstart wist ze.', 'Of een gesprek bij opnieuw openen wordt hervat, stel je hieronder in.').replace('Conversations remain in memory for up to one hour; restarting clears them.', 'The option below controls whether reopening resumes the conversation.')
    return f"""<section class="card" id="chatgpt"><h2>ChatGPT · web en BBS 5559999</h2>{action}<p>{web_help}</p>{conversation}</section>"""


def phonebook_page(language: str) -> str:
    """Render fixed dial-up services and the editable public BBS directory."""
    entries = load_phonebook()
    bbs_cards = ""
    for entry in entries:
        if str(entry.get("kind", "bbs")) != "bbs":
            continue
        number = html.escape(str(entry.get("number", "")), quote=True)
        label = html.escape(str(entry.get("label", "")), quote=True)
        host = html.escape(str(entry.get("host", "")), quote=True)
        port = html.escape(str(entry.get("port", "23")), quote=True)
        bbs_cards += f"""<form class="card phone-entry bbs-entry" method="post" action="/phonebook/update">
<input type="hidden" name="csrf" value="{{{{csrf}}}}"><input type="hidden" name="original_number" value="{number}">
<input type="hidden" name="kind" value="bbs">
<div><label>{tr(language,'Nummer','Number')}</label><input name="number" inputmode="tel" value="{number}" required></div>
<div><label>{tr(language,'Naam','Name')}</label><input name="label" value="{label}" required></div>
<div><label>Host</label><input name="host" value="{host}" required></div><div><label>Port</label><input name="port" type="number" min="1" max="65535" value="{port}" required></div>
<div class="entry-actions"><button name="action" value="save" type="submit">{tr(language,'Opslaan','Save')}</button><button class="danger" name="action" value="delete" type="submit">{tr(language,'Verwijderen','Delete')}</button></div></form>"""
    connected = bool(openai_auth.connection_status()["connected"])
    chat_status = (f'<span class="chip ok">{tr(language,"Verbonden","Connected")}</span>' if connected
                   else f'<span class="chip warn">{tr(language,"Niet verbonden","Not connected")}</span>')
    return f"""<div class="page-heading"><h1>{tr(language,'Telefoonboek','Phone book')}</h1><p>{tr(language,'Alle nummers voor inbelinternet, publieke BBS’en en ChatGPT.','All numbers for dial-up internet, public BBSes and ChatGPT.')}</p></div>
<h2 class="section-heading">{tr(language,'Systeemnummers','System numbers')}</h2>
<div class="grid"><section class="card"><h2>{tr(language,'Inbelinternet','Dial-up internet')} · 5559000</h2><dl><dt>{tr(language,'Gebruikersnaam','Username')}</dt><dd><code>user</code></dd><dt>{tr(language,'Wachtwoord','Password')}</dt><dd>{tr(language,'Leeg laten','Leave blank')}</dd><dt>IP / DNS</dt><dd>{tr(language,'Automatisch','Automatic')}</dd></dl></section>
<section class="card"><div class="status-row"><div><h2>ChatGPT · 5559999</h2><small>{tr(language,'Chat met webzoeken; nieuw gesprek of voortzetten is instelbaar.','Chat with web search; starting new or continuing is configurable.')}</small></div>{chat_status}</div><div class="actions"><a class="button primary" href="/settings#chatgpt">{tr(language,'ChatGPT-autorisatie en gespreksmodus','ChatGPT authorization and conversation mode')}</a></div></section></div>
<h2 class="section-heading">{tr(language,'BBS-nummers','BBS numbers')} · 5551000–…</h2>{bbs_cards}
<section class="card"><h2>{tr(language,'BBS toevoegen','Add BBS')}</h2><form method="post" action="/phonebook/add"><input type="hidden" name="csrf" value="{{{{csrf}}}}">
<label>{tr(language,'Telefoonnummer','Phone number')}</label><input name="number" inputmode="tel" placeholder="5551010" required>
<label>{tr(language,'Naam','Name')}</label><input name="label" placeholder="Nieuwe BBS" required>
<input type="hidden" name="kind" value="bbs"><label>Host</label><input name="host" placeholder="bbs.example.net" required><label>Port</label><input name="port" type="number" min="1" max="65535" value="23" required>
<button type="submit">{tr(language,'Toevoegen','Add')}</button></form></section>"""


def page(title: str, body: str, language: str, csrf: str, refresh: int | None = None) -> bytes:
    refresh_tag = f'<meta http-equiv="refresh" content="{refresh}">' if refresh else ""
    nav_items = [
        ("/", "Status", "Status"),
        ("/modem", tr(language, "Verbinding", "Connection"), "Modem"),
        ("/transfer", tr(language, "Bestanden", "Files"), tr(language, "Bestandsoverdracht", "File transfer")),
        ("/phonebook", tr(language, "Telefoonboek", "Phone book"), tr(language, "Telefoonboek", "Phone book")),
        ("/wifi", "Wi-Fi", "Wi-Fi"),
        ("/settings", tr(language, "Instellingen", "Settings"), tr(language, "Instellingen", "Settings")),
        ("/guides", tr(language, "Handleidingen", "Guides"), tr(language, "Handleidingen", "Guides")),
    ]
    navigation = "".join(
        f'<a href="{href}" class="{"current" if match == title else ""}" {"aria-current=page" if match == title else ""}>{label}</a>'
        for href, label, match in nav_items
    )
    document = f"""<!doctype html>
<html lang="{language}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{refresh_tag}<title>{html.escape(title)} · RetroModem</title>
<style>
:root{{--ink:#18303e;--muted:#61727b;--paper:#fff;--card:#fff;--canvas:#eef2f2;--sky:#dcebf0;--accent:#eb7146;--accent-dark:#d95d35;--green:#3f9f75;--amber:#b7791f;--red:#b63e3e;--line:#cbd6d9;--graphite:#123d55;--navy-2:#1d5874;--shadow:0 18px 50px rgba(21,49,62,.10)}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:var(--canvas);color:var(--ink);font:16px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{height:78px;background:var(--paper);color:var(--graphite);padding:0 max(24px,calc((100% - 1160px)/2));border-bottom:1px solid #d7e0e2;display:flex;flex-direction:column;justify-content:center}}header h1{{margin:0;font-size:1.2rem;letter-spacing:-.02em;color:var(--graphite)}}header h1:before{{content:"";display:inline-block;width:7px;height:20px;margin-right:10px;border-radius:2px;background:var(--accent);vertical-align:-3px;transform:skewY(-20deg)}}header small{{color:var(--muted);font-size:.72rem;margin-left:21px}}main{{max-width:1160px;margin:0 auto;padding:0 24px 80px}}
nav{{display:flex;gap:0;overflow-x:auto;margin:0 0 38px;padding:0;background:var(--paper);position:sticky;top:0;z-index:5;border-bottom:1px solid var(--line);box-shadow:0 5px 18px rgba(21,49,62,.04)}}nav a,.button,button{{border:0;border-radius:8px;background:var(--graphite);color:#fff;min-height:42px;padding:.78rem 1rem;text-decoration:none;cursor:pointer;font-size:.86rem;font-weight:700;line-height:1;white-space:nowrap;display:inline-flex;align-items:center;justify-content:center;transition:.18s ease}}nav a{{position:relative;border-radius:0;background:transparent;color:var(--muted);font-size:.78rem;font-weight:800}}nav a:hover{{background:var(--sky);color:var(--graphite)}}nav a.current{{background:transparent;color:var(--graphite)}}nav a.current:after{{content:"";position:absolute;left:14px;right:14px;bottom:0;height:3px;border-radius:3px 3px 0 0;background:var(--accent)}}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{{outline:3px solid rgba(29,88,116,.25);outline-offset:2px}}button:disabled,.button.disabled{{opacity:.55;cursor:not-allowed}}
.page-heading{{margin:0 0 28px;padding:0 2px}}.page-heading:before{{content:"RETROMODEM";display:block;margin-bottom:7px;color:var(--accent);font-size:.7rem;font-weight:900;letter-spacing:.14em}}.page-heading h1{{font-size:clamp(2rem,4vw,3.4rem);line-height:1;letter-spacing:-.045em;margin:0 0 10px;color:var(--graphite)}}.page-heading p{{color:var(--muted);margin:0;max-width:70ch;line-height:1.65}}.section-heading{{margin:34px 0 12px;color:var(--graphite);font-size:1.25rem}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px;box-shadow:var(--shadow)}}main>.card+*,main>.grid+*,main>.notice+*,main>.page-heading+*{{margin-top:16px}}main>.section-heading+*{{margin-top:0}}.card>:first-child{{margin-top:0}}.card>:last-child{{margin-bottom:0}}h2{{color:var(--graphite);font-size:1.16rem;margin:0 0 14px;letter-spacing:-.01em}}h3{{color:var(--graphite);font-size:1rem;line-height:1.3;margin:22px 0 8px}}p{{margin:0 0 14px}}dl{{display:grid;grid-template-columns:auto 1fr;gap:8px 14px;margin:0}}dt{{color:var(--muted)}}dd{{margin:0;font-weight:650;overflow-wrap:anywhere}}.ok{{color:var(--green)}}.bad{{color:var(--red)}}
.hero{{display:grid;grid-template-columns:1fr auto;gap:18px;align-items:center;background:var(--graphite);color:#fff;border:0;margin-bottom:16px;box-shadow:0 18px 50px rgba(21,49,62,.18)}}.hero h2{{color:#fff;font-size:1.45rem;margin-bottom:5px}}.hero p{{margin:0;color:#c5d5dc}}.route{{font:700 .96rem ui-monospace,SFMono-Regular,Consolas,monospace;color:#fff!important;margin-top:12px!important}}.dashboard{{display:grid;grid-template-columns:repeat(12,1fr);gap:16px}}.span-12{{grid-column:span 12}}.span-8{{grid-column:span 8}}.span-6{{grid-column:span 6}}.span-4{{grid-column:span 4}}
.chip{{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:4px 9px;background:#e9edef;color:#405159;font-size:.78rem;font-weight:800}}.chip:before{{content:"";width:7px;height:7px;border-radius:50%;background:#829198}}.chip.ok{{background:#e4f4eb;color:#176641}}.chip.ok:before{{background:var(--green)}}.chip.active{{background:#dceff1;color:#145d66}}.chip.active:before{{background:#247f89}}.chip.bad{{background:#f8e7e7;color:#8d2f2f}}.chip.bad:before{{background:var(--red)}}.chip.warn{{background:#fbf0d8;color:#875c17}}.chip.warn:before{{background:var(--amber)}}
.status-list{{display:grid;gap:0}}.status-row{{display:flex;align-items:center;justify-content:space-between;gap:12px;min-height:52px;padding:11px 0;border-bottom:1px solid #e3e9ea}}.status-row:last-child{{border-bottom:0}}.status-row>div:first-child{{min-width:0}}.status-row strong{{display:block}}.status-row small{{display:block;color:var(--muted)}}.status-row code{{font-size:.86rem}}.actions{{display:flex;gap:9px;flex-wrap:wrap}}.card>.actions{{margin-top:18px;padding-top:16px;border-top:1px solid var(--line)}}.card>.status-row+.actions{{margin-top:0}}.card>.status-row{{border-bottom:0}}.actions .button,.button.secondary{{background:transparent;color:var(--graphite);border:1px solid #b8c8cd;box-shadow:none}}.actions .button.primary,.button.primary,button.primary{{background:var(--accent);color:#fff;border:0}}.button.danger,button.danger{{background:#a33;color:#fff}}.button.ghost,button.ghost{{background:transparent;color:var(--graphite);border:1px solid var(--line);box-shadow:none}}
label{{display:block;color:var(--graphite);font-size:.8rem;font-weight:800;margin:16px 0 7px}}input,select{{width:100%;min-height:44px;padding:.78rem .85rem;border:1px solid #bfcdd1;border-radius:7px;background:#fbfcfc;color:var(--ink);font:inherit;outline:none}}input:focus,select:focus{{border-color:var(--navy-2);box-shadow:0 0 0 3px rgba(29,88,116,.1);background:#fff}}button{{margin-top:18px;background:var(--accent);box-shadow:0 7px 18px rgba(235,113,70,.18)}}button:hover,.button:hover{{transform:translateY(-1px)}}.helper{{display:block;color:var(--muted);font-size:.84rem;margin-top:6px}}.form-section{{background:color-mix(in srgb,var(--sky) 55%,#fff);border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:20px}}.form-section h3{{margin-top:0}}details.hardware,details.guide-help{{margin-top:18px;padding-top:14px;border-top:1px solid var(--line)}}summary{{cursor:pointer;font-weight:800;color:var(--graphite)}}.guide-tabs{{display:flex;gap:7px;flex-wrap:wrap}}.guide-tabs button{{margin:0;background:transparent;color:var(--graphite);border:1px solid #b8c8cd;border-radius:8px;box-shadow:none}}.guide-tabs button.active{{background:var(--sky);color:var(--graphite);border-color:#9fb6bf;box-shadow:inset 0 -3px 0 var(--accent)}}.guide-panel[hidden]{{display:none}}.guide-panel{{width:100%;max-width:none}}.verification{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 18px}}.verification span{{display:inline-flex;align-items:center;padding:5px 10px;border-radius:999px;font-size:.78rem;font-weight:800;background:var(--canvas);color:var(--muted);border:1px solid var(--line)}}.verification .verified{{background:#e4f2eb;color:#246343;border-color:#b7dbc8}}.verification .experimental{{background:#fff2d9;color:#79520d;border-color:#edd19a}}.verification .unsupported{{background:#f9e5e1;color:#8b3428;border-color:#e8bab1}}
.phone-entry{{display:grid;grid-template-columns:1fr 2fr 2fr 110px;gap:0 12px;margin-bottom:12px}}.entry-actions{{display:flex;gap:8px;grid-column:1/-1}}.bbs-entry{{grid-template-columns:110px minmax(140px,1.2fr) minmax(170px,1.5fr) 85px auto;padding:7px 9px;gap:7px;align-items:center;box-shadow:none;margin-bottom:5px}}.bbs-entry label{{display:none}}.bbs-entry input,.bbs-entry select{{padding:6px 7px}}.bbs-entry .entry-actions{{grid-column:auto;gap:5px}}.bbs-entry button{{margin:0;padding:7px 9px;font-size:.82rem;min-height:38px}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px 6px;border-bottom:1px solid var(--line);text-align:left}}.notice{{padding:13px 15px;border-left:4px solid var(--green);border-radius:0 10px 10px 0;background:#e9f5ed}}.warning{{border-color:var(--amber);background:#fbf0dd}}.transfer-status{{display:grid;grid-template-columns:auto 1fr auto;gap:12px;align-items:center}}.transfer-status button{{margin:0}}.status-icon{{font-size:1.5rem}}.status-title{{font-weight:750}}.status-meta{{color:var(--muted);font-size:.9rem}}.progress{{height:9px;background:#d7d0c4;border-radius:9px;overflow:hidden;margin-top:10px}}.progress>span{{display:block;height:100%;width:35%;background:var(--green);border-radius:9px}}.progress.running>span{{animation:scan 1.25s ease-in-out infinite}}@keyframes scan{{0%{{transform:translateX(-110%)}}100%{{transform:translateX(310%)}}}}.technical{{margin-top:10px}}.technical pre{{white-space:pre-wrap;max-height:120px;overflow:auto;font-size:.78rem}}.file-list{{display:grid;gap:8px;margin:0;padding:0;list-style:none}}.file-list li{{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;border-bottom:1px solid var(--line)}}.file-list li:last-child{{border:0}}code{{background:#e8e3da;padding:2px 5px;border-radius:5px}}ol.steps{{padding-left:1.4rem}}ol.steps>li{{margin:0 0 18px;padding-left:5px}}ul.compact{{margin:6px 0}}
.received-files{{padding-block:18px}}.received-files>p{{margin-bottom:6px}}.file-list li{{padding:7px 0}}.file-actions{{display:flex;align-items:center;gap:6px}}.file-actions form{{margin:0}}.file-actions .button,.file-actions button{{margin:0;padding:7px 10px;min-height:36px;font-size:.82rem}}
.software-list{{display:grid;gap:10px}}.software-card{{display:grid;grid-template-columns:minmax(0,1fr) 210px;gap:20px;align-items:center;padding:16px;border:1px solid var(--line);border-radius:12px;background:#f9f7f2}}.software-card h3{{margin:0 0 5px}}.software-card p{{margin:0}}.software-actions{{display:grid;gap:7px;width:210px}}.software-actions form{{margin:0;width:100%}}.software-actions .button,.software-actions button{{margin:0;width:100%}}.guide-images{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;margin:14px 0 20px}}.guide-images figure{{margin:0;border:1px solid var(--line);border-radius:10px;overflow:hidden;background:#f7f8f8}}.guide-images img{{display:block;width:100%;height:auto;image-rendering:auto}}.guide-images figcaption{{padding:9px 11px;color:var(--muted);font-size:.8rem}}
@media(max-width:850px){{.span-8,.span-6,.span-4{{grid-column:span 12}}.bbs-entry{{grid-template-columns:100px 1fr 1fr 80px}}.bbs-entry .entry-actions{{grid-column:1/-1}}}}@media(max-width:720px){{.phone-entry,.bbs-entry{{grid-template-columns:1fr 1fr;padding:16px}}.bbs-entry label{{display:block}}.bbs-entry>div:nth-of-type(2),.bbs-entry>div:nth-of-type(3){{grid-column:1/-1}}.guide-tabs{{flex-wrap:nowrap;overflow-x:auto;padding-bottom:6px}}}}@media(max-width:520px){{main{{padding-inline:12px;padding-bottom:52px}}header{{height:64px;padding-inline:16px}}header small,.page-heading:before{{display:none}}nav{{margin-inline:-12px;margin-bottom:26px;padding-inline:4px}}nav a{{min-height:46px;padding-inline:12px}}.page-heading h1{{font-size:2.25rem}}.card{{padding:19px}}.hero{{grid-template-columns:1fr}}.hero .button{{width:100%}}.phone-entry,.bbs-entry,.transfer-status,.software-card{{grid-template-columns:1fr}}.software-actions{{width:100%}}.bbs-entry>div{{grid-column:1!important}}dl{{grid-template-columns:minmax(90px,auto) 1fr}}dd{{margin-bottom:7px}}.transfer-status form,.transfer-status button{{width:100%}}.actions .button{{flex:1 1 100%}}}}
@media(prefers-reduced-motion:reduce){{.progress.running>span{{animation:none;width:100%;opacity:.65}}}}
</style></head><body>
<header><h1>RetroModem</h1><small>{tr(language,'Wi-Fi-bridge voor klassieke computers en handhelds','Wi-Fi bridge for classic computers and handhelds')}</small></header>
<main><nav>{navigation}</nav>{body}</main>
</body></html>"""
    return document.encode("utf-8")


def irda_speed_guide(language: str, device: str) -> str:
    tested = {
        "generic": tr(language, "MY018: PPP op 57k6 getest met Palm IIIc/OS 4.1 en Psion 5mx; Palm Beam naar de Palm ook getest. Andere apparaten zijn daarmee niet automatisch getest.", "MY018: 57.6k PPP tested with Palm IIIc/OS 4.1 and Psion 5mx; Beam to Palm also tested. Other devices are not automatically verified."),
        "psion": tr(language, "MY018: PPP op de Psion 5mx werkt op 57k6. EPOC- en terminalbestandsoverdracht zijn met deze nieuwe module nog niet opnieuw geverifieerd; de eerdere beperkingen blijven dus gelden.", "MY018: PPP on Psion 5mx works at 57.6k. EPOC and terminal transfers have not been reverified with this new module; the previous limitations still apply."),
        "palm-new": tr(language, "MY018 + Palm IIIc/OS 4.1: PPP en een volledige Beam-overdracht naar de Palm werken op 57k6. Gemeten: 79.026 bytes in 23,91 s, gemiddeld 3,305 kB/s inclusief verbinden. Beam vanaf de Palm was eerder op 9600 getest; op 57k6 nog niet.", "MY018 + Palm IIIc/OS 4.1: PPP and a complete Beam transfer to Palm work at 57.6k. Measured: 79,026 bytes in 23.91 s, averaging 3.305 kB/s including connection. Beam from Palm was previously tested at 9600, not yet at 57.6k."),
    }
    return f'<div class="form-section"><h3>{tr(language,"IrDA-snelheid per adapter","IrDA speed by adapter")}</h3><p>{tested[device]}</p><ul><li><strong>MY018:</strong> {tr(language,"57k6 is de aanbevolen geteste instelling, uitsluitend met de aangepaste A/B/C-bedrading en transistorschakeling. 19k2 is gedeeltelijk getest; 38k4 nog niet.","57.6k is the recommended tested setting, only with the modified A/B/C wiring and transistor switch. 19.2k is partially tested; 38.4k is untested.")}</li><li><strong>MA-620:</strong> {tr(language,"gebruik de bewezen 9600-instelling van deze USB-adapter; de MY018-resultaten gelden hier niet voor.","use this USB adapter’s verified 9600 setting; MY018 results do not apply.")}</li></ul><p class="notice warning"><strong>115k2:</strong> {tr(language,"experimenteel, niet stabiel aangetoond. Palm Beam kon in onze tests niet verbinden; Psion PPP is niet bevestigd. Dit is geen algemene IrDA-beperking. Ga bij problemen terug naar 57k6 of 9600.","experimental, not proven stable. Palm Beam failed to connect in our tests; Psion PPP is unconfirmed. This is not a general IrDA limitation. Fall back to 57.6k or 9600 if needed.")}</p><p>{tr(language,"Kies het maximum op","Select the maximum on")} <a href="/modem">{tr(language,"de Modem-pagina","the Modem page")}</a>. {tr(language,"Ontdekking begint altijd op 9600, daarna volgt de onderhandelde snelheid. Een connection-instelling op het apparaat bewijst de fysieke linksnelheid niet; Beam en PPP kunnen hun eigen instellingen gebruiken. Verbreek en verbind opnieuw na een wijziging.","Discovery always starts at 9600, then the negotiated speed follows. A device connection preference does not prove the physical speed; Beam and PPP can use their own settings. Disconnect and reconnect after a change.")}</p></div>'


def guides_page(language: str) -> str:
    """Device-oriented guides with transport and use-case kept separate."""
    body = f"""<div class="page-heading"><h1>{tr(language,'Handleidingen','Guides')}</h1><p>{tr(language,'Kies je apparaat voor instellingen voor internet, BBS en bestandsoverdracht.','Choose your device for internet, BBS and file-transfer settings.')}</p></div><section class="card"><h2>{tr(language,'Kies een apparaat','Choose a device')}</h2><div class="guide-tabs">
<button type="button" data-guide="generic">{tr(language,'Algemeen','Generic')}</button><button type="button" data-guide="proxy">{tr(language,'Webproxy','Web proxy')}</button><button type="button" data-guide="psion">Psion 5mx</button><button type="button" data-guide="palm-old">Palm OS 3.0/3.1</button><button type="button" data-guide="palm-new">Palm OS 3.3–5.x</button><button type="button" data-guide="hp200lx">HP 200LX</button><button type="button" data-guide="win95">Windows 95</button><button type="button" data-guide="win98">Windows 98</button><button type="button" data-guide="winxp">Windows XP</button>
</div></section>
<section class="card guide-panel" id="generic" hidden><h2>{tr(language,'Algemene werkwijze','General workflow')}</h2>
<p class="helper">{tr(language,'Kies hierboven een apparaat voor geteste, modelspecifieke stappen.','Choose a device above for tested, model-specific steps.')}</p>
<h3>{tr(language,'1. Kies de verbinding','1. Choose the connection')}</h3><dl><dt>IrDA</dt><dd>{tr(language,'Mobile Action MA-620; fysieke linksnelheid 9600 bit/s. Richt de poorten op 10–30 cm afstand op elkaar.','Mobile Action MA-620; physical link speed 9600 bps. Align the ports at a distance of 10–30 cm.')}</dd><dt>USB-serieel</dt><dd>{tr(language,'Prolific PL2303; sluit de juiste seriële kabel of null-modemadapter op het apparaat aan. De snelheid is instelbaar op de Modem-pagina.','Prolific PL2303; connect the appropriate serial cable or null-modem adapter to the device. Configure speed on the Modem page.')}</dd></dl>
<h3>{tr(language,'2. Kies de modemmodus','2. Choose the modem mode')}</h3><dl><dt>Direct PPP</dt><dd>{tr(language,'Het apparaat start PPP rechtstreeks, zonder AT-commando of telefoonnummer.','The device starts PPP directly, without an AT command or phone number.')}</dd><dt>Hayes-dial-up</dt><dd>{tr(language,'Gebruik AT-commando’s. Bel <code>5559000</code> voor internet of een nummer uit het BBS-telefoonboek.','Use AT commands. Dial <code>5559000</code> for internet or a number from the BBS phone book.')}</dd></dl>
<h3>{tr(language,'3. Basisinstellingen','3. Basic settings')}</h3><ul><li>PPP: {tr(language,'gebruikersnaam <code>user</code>, leeg wachtwoord, IP en DNS automatisch.','username <code>user</code>, blank password, automatic IP and DNS.')}</li><li>{tr(language,'Begin webtests met een gewone HTTP-site; veel oude browsers ondersteunen moderne HTTPS-sites niet.','Start web tests with a plain HTTP site; many old browsers cannot open modern HTTPS sites.')}</li><li>{tr(language,'Voor X/Y/ZMODEM en ASCII gebruik je de pagina','For X/Y/ZMODEM and ASCII use the')} <a href="/transfer">{tr(language,'Bestandsoverdracht','File transfer')}</a>.</li></ul>
<h3>RetroWEB</h3><p>{tr(language,'Open na het verbinden','After connecting, open')} <a href="http://retroweb.bjrno.com"><strong>http://retroweb.bjrno.com</strong></a>. {tr(language,'RetroWEB zet moderne pagina’s en afbeeldingen om voor oude browsers. Gebruik http:// en niet https://.','RetroWEB converts modern pages and images for old browsers. Use http:// rather than https://.')}</p>
<h3>{tr(language,'Terminaltip','Terminal tip')}</h3><p>{tr(language,'Verschijnen tekens dubbel? Zet Local echo/Lokale echo in het terminalprogramma uit.','Do characters appear twice? Disable Local echo in the terminal application.')}</p></section>

<section class="card guide-panel" id="proxy" hidden><h2>{tr(language,'Ingebouwde webproxy','Built-in web proxy')}</h2><p>{tr(language,'De ingebouwde proxy is gebaseerd op','The built-in proxy is based on')} <a href="http://retroweb.bjrno.com">RetroWEB</a>. {tr(language,'Hij haalt moderne HTTPS-pagina’s op, vereenvoudigt de inhoud en levert die via HTTP aan oude browsers. De oorspronkelijke website-URL blijft in de adresbalk staan.','It fetches modern HTTPS pages, simplifies the content and serves it over HTTP to old browsers. The original website URL remains in the address bar.')}</p><h3>{tr(language,'Zoeken','Search')}</h3><p>{tr(language,'Open','Open')} <a href="http://search.retromodem"><strong>http://search.retromodem</strong></a>. {tr(language,'Deze lokale pagina is alleen bedoeld voor zoeken; zoekresultaten openen daarna als gewone websites via de proxy. Verbind PPP opnieuw als de naam nog niet wordt gevonden.','This local page is only for searching; results then open as ordinary websites through the proxy. Reconnect PPP if the name is not yet found.')}</p><h3>{tr(language,'Handmatige stand','Manual mode')}</h3><p>{tr(language,'Stel in de oude browser een HTTP-proxy in met server <code>192.168.77.1</code>, poort <code>8080</code> en zonder gebruikersnaam of wachtwoord. Zonder proxyinstelling blijft direct HTTP-verkeer mogelijk.','Configure HTTP proxy server <code>192.168.77.1</code>, port <code>8080</code>, with no username or password in the legacy browser. Without a proxy setting, direct HTTP traffic remains possible.')}</p><h3>{tr(language,'Automatische stand','Automatic mode')}</h3><p>{tr(language,'Alle HTTP-aanvragen worden door RetroModem onderschept en verwerkt; in de browser hoeft geen proxy te worden ingesteld.','All HTTP requests are intercepted and processed by RetroModem; no browser proxy setting is required.')}</p><h3>{tr(language,'Afbeeldingen','Images')}</h3><p>{tr(language,'Kies bij Instellingen tussen afbeeldingen inline of als genummerde links. Kies daarnaast een apparaatpreset of een maximale breedte en hoogte. Afbeeldingen worden afzonderlijk geladen en naar compacte GIF-bestanden omgezet.','In Settings choose inline images or numbered image links. Also choose a device preset or maximum width and height. Images load separately and are converted to compact GIF files.')}</p><h3>{tr(language,'Uitzonderingen','Exceptions')}</h3><p>{tr(language,'Uitgezonderde domeinen worden rechtstreeks en ongewijzigd doorgegeven. RetroWEB, FrogFind, The Old Net en 68k.news zijn standaard opgenomen.','Excluded domains are passed through directly and unchanged. RetroWEB, FrogFind, The Old Net and 68k.news are included by default.')}</p><div class="notice warning"><strong>{tr(language,'Niet voor gevoelige gegevens.','Not for sensitive data.')}</strong> {tr(language,'De proxy ondersteunt alleen GET en herschrijft pagina’s. Gebruik hem niet voor accounts, wachtwoorden of betalingen. Niet iedere moderne website kan zinvol worden vereenvoudigd.','The proxy supports GET only and rewrites pages. Do not use it for accounts, passwords or payments. Not every modern website can be simplified usefully.')}</div></section>

<section class="card guide-panel" id="psion" hidden><h2>Psion Series 5mx</h2><div class="verification"><span class="verified">{tr(language,'Getest','Tested')} · IrDA PPP</span><span class="verified">{tr(language,'Getest','Tested')} · IrDA dial-up/BBS</span><span class="verified">{tr(language,'Getest','Tested')} · YMODEM</span><span class="experimental">{tr(language,'Experimenteel','Experimental')} · EPOC IR</span><span>{tr(language,'Niet getest','Not tested')} · USB-serieel</span></div><p><strong>IrDA:</strong> {tr(language,'getest met de 5mx.','tested with the 5mx.')} <strong>USB-serieel:</strong> {tr(language,'technisch geschikt met Psion-seriële kabel en de juiste adapter, maar nog niet fysiek getest.','technically suitable with a Psion serial cable and the appropriate adapter, but not yet physically tested.')}</p>
<h3>{tr(language,'Eerst voorbereiden','Prepare first')}</h3><ol><li><strong>{tr(language,'Zet Remote Link uit.','Disable Remote Link.')}</strong> {tr(language,'Open Instellingen, druk op de menuknop linksboven op de schermrand en kies Extra → Remote Link → Uit. Anders houdt synchronisatie de communicatiepoort bezet.','Open System, press the upper-left bezel menu button and select Tools → Remote Link → Off. Otherwise synchronization keeps the communications port occupied.')}</li></ol><div class="guide-images"><figure><img src="/static/guides/psion/setup-remote-link.gif" alt="{tr(language,'Psion-menu Extra met Remote Link geselecteerd','Psion Tools menu with Remote Link selected')}" loading="lazy"><figcaption>{tr(language,'Extra → Remote Link','Tools → Remote Link')}</figcaption></figure><figure><img src="/static/guides/psion/setup-internet-service.gif" alt="{tr(language,'Psion Remote Link-venster met Link op Uit','Psion Remote Link dialog with Link set to Off')}" loading="lazy"><figcaption>{tr(language,'Zet Link op Uit en bevestig met OK.','Set Link to Off and confirm with OK.')}</figcaption></figure></div><ol start="2"><li><strong>{tr(language,'Bevestig Bellen.','Confirm Dialling.')}</strong> {tr(language,'Open Configuratiescherm → Bellen (Engels: Dialling), open of selecteer de huidige instelling en sluit met OK. Doe dit ook als de standaardwaarden al goed lijken; anders verschijnt later de fout dat verbindings- of locatiegegevens ontbreken.','Open Control panel → Dialling, open or select the current setting and close with OK. Do this even if the defaults already look correct; otherwise applications may later report missing connection or location information.')}</li><li>{tr(language,'Mobile Connectivity Update 3.10 is optioneel. Probeer de ingebouwde netwerksoftware eerst; installeer de update alleen wanneer jouw EPOC-installatie verbindingsopties mist.','Mobile Connectivity Update 3.10 is optional. Try the built-in networking first; install the update only if your EPOC installation lacks connection options.')}</li></ol>
<h3>Direct PPP</h3><ol><li>{tr(language,'Kies op RetroModem de gewenste infraroodadapter en <strong>Direct PPP</strong>.','On RetroModem select the desired infrared adapter and <strong>Direct PPP</strong>.')}</li><li>{tr(language,'Open Configuratiescherm → Modems, maak een modem genaamd <em>RetroModem</em> en kies <strong>Infrarode mobiele telefoon</strong>. Gebruik voor MY018 de aanbevolen 57600 bit/s en voor MA-620 9600 bit/s. Bij USB-serieel kies je Serial en exact dezelfde snelheid als op de Modem-pagina.','Open Control panel → Modems, create a modem named <em>RetroModem</em> and select <strong>Infrared mobile phone</strong>. Use the recommended 57600 bps for MY018 and 9600 bps for MA-620. For USB serial, select Serial and exactly the same speed as on the Modem page.')}</li><li>{tr(language,'Tab Opties: laat de standaardwaarden staan. Tab Initialisatie: <code>AT</code>. Tab Geavanceerd: Hardware (RTS/CTS), Terminal detect en Carrier detect uit, Modemtype Vaste lijn.','Options tab: retain the defaults. Initialization tab: <code>AT</code>. Advanced tab: Hardware (RTS/CTS), Terminal detect and Carrier detect off, Modem type Fixed line.')}</li><li>{tr(language,'Open Configuratiescherm → Internet/Netwerk en maak een nieuwe dienst. Tab Dienst: een herkenbare naam, verbinding <strong>Direct</strong> en modem RetroModem. Tab Account: Handmatig aanmelden uit, gebruiker <code>user</code>, wachtwoord leeg.','Open Control panel → Internet/Network and create a new service. Service tab: a recognizable name, <strong>Direct</strong> connection and the RetroModem modem. Account tab: Manual login off, user <code>user</code>, blank password.')}</li><li>{tr(language,'Tab Adressen: IP-adres en DNS van server ophalen. Tab Login: standaard laten. Tab Geavanceerd: alleen <strong>platte tekst accepteren</strong> ingeschakeld. Er is geen telefoonnummer of loginscript nodig.','Addresses tab: obtain IP address and DNS from server. Login tab: retain defaults. Advanced tab: enable only <strong>accept plain text</strong>. No phone number or login script is required.')}</li><li>{tr(language,'Richt de IR-poorten recht op elkaar op ongeveer 10–30 cm. Open Web of Opera, bezoek eerst <code>http://retroweb.bjrno.com</code> en kies de nieuwe dienst wanneer EPOC daarom vraagt. De eerste IrDA-koppeling kan enkele seconden kosten.','Align the IR ports directly at a distance of roughly 10–30 cm. Open Web or Opera, first visit <code>http://retroweb.bjrno.com</code> and select the new service when EPOC asks. The first IrDA association can take several seconds.')}</li></ol>
<h3>{tr(language,'Inbelinternet via 5559000','Dial-up internet through 5559000')}</h3><p>{tr(language,'Kies op RetroModem <strong>Hayes-dial-up / BBS</strong>. Maak op de Psion een tweede internetdienst met hetzelfde modem, maar als inbelverbinding met telefoonnummer <code>5559000</code>, gebruiker <code>user</code> en leeg wachtwoord. Laat IP en DNS door de server toewijzen.','Select <strong>Hayes dial-up / BBS</strong> on RetroModem. Create a second Psion internet service using the same modem, but as a dial-up connection with phone number <code>5559000</code>, user <code>user</code> and a blank password. Let the server assign IP and DNS.')}</p>
<h3>{tr(language,'BBS’en met Comms of Hermes','Using BBSes with Comms or Hermes')}</h3><ol><li>{tr(language,'Kies op RetroModem Hayes-dial-up. Open Comms of Hermes, gebruik Infrared en dezelfde virtuele snelheid als op de Modem-pagina. Gebruik 8 databits, geen pariteit en 1 stopbit.','Select Hayes dial-up on RetroModem. Open Comms or Hermes, use Infrared and the same virtual speed shown on the Modem page. Use 8 data bits, no parity and 1 stop bit.')}</li><li>{tr(language,'Kies bij voorkeur ANSI/ANSI-BBS met IBM CP437; gebruik VT100 wanneer ANSI-BBS niet beschikbaar is. Zet Lokale echo uit (in Comms onder Extra → Vertaalcodes), anders verschijnen tekens dubbel.','Prefer ANSI/ANSI-BBS with IBM CP437; use VT100 when ANSI-BBS is unavailable. Disable Local echo (in Comms under Tools → Translation codes), otherwise characters appear twice.')}</li><li>{tr(language,'Richt de poorten uit en wacht tot de D-led continu brandt. Stuur <code>AT</code> plus Enter; het antwoord hoort <code>OK</code> te zijn. Bel daarna bijvoorbeeld <code>ATDT5551008</code> of een ander nummer uit het telefoonboek.','Align the ports and wait until the D LED is solid. Send <code>AT</code> plus Enter; the response should be <code>OK</code>. Then dial, for example, <code>ATDT5551008</code> or another number from the phone book.')}</li></ol>
<h3>{tr(language,'Browsen en wifi','Browsing and Wi-Fi')}</h3><p>{tr(language,'Web en Opera zijn bruikbaar voor eenvoudige HTTP-sites. De ingebouwde proxy is gebaseerd op <a href="http://retroweb.bjrno.com">RetroWEB</a>. Handmatig is de standaard: stel in de browser HTTP-proxyserver <code>192.168.77.1</code>, poort <code>8080</code> en geen gebruikersnaam of wachtwoord in. Automatisch stuurt al het HTTP-verkeer zonder browserinstelling via de proxy. Kies bij Instellingen of afbeeldingen inline of als links verschijnen en welk formaat wordt gebruikt. De publieke RetroWEB-site blijft rechtstreeks beschikbaar. Gebruik de proxy niet voor gevoelige gegevens. Voor een nieuw wifi-netwerk verbind je telefoon of laptop met hotspot <code>retromodem</code> en open je <code>http://10.42.0.1</code>.','Web and Opera work for simple HTTP sites. The built-in proxy is based on <a href="http://retroweb.bjrno.com">RetroWEB</a>. Manual is the default: configure HTTP proxy server <code>192.168.77.1</code>, port <code>8080</code>, with no username or password. Automatic sends all HTTP traffic through the proxy without browser configuration. In Settings, choose inline images or image links and the desired size. The public RetroWEB site remains directly available. Do not use the proxy for sensitive data. For a new Wi-Fi network, connect a phone or laptop to hotspot <code>retromodem</code> and open <code>http://10.42.0.1</code>.')}</p>
<details class="guide-help"><summary>{tr(language,'Problemen oplossen','Troubleshooting')}</summary><ul><li>{tr(language,'Melding over ontbrekende locatie- of modemgegevens: bevestig Bellen opnieuw en controleer of de dienst modem RetroModem gebruikt.','Missing location or modem information: confirm Dialling again and verify that the service uses the RetroModem modem.')}</li><li>{tr(language,'Geen reactie op AT: Remote Link uit, lokale echo uit, IR-poorten opnieuw uitlijnen en enkele seconden wachten op de eerste IrCOMM-koppeling.','No response to AT: disable Remote Link and local echo, realign the IR ports and allow several seconds for the first IrCOMM association.')}</li><li>{tr(language,'Blijft “Looking up host name” staan: probeer de HTTP-testsite en controleer in de RetroModem-webinterface of wifi verbonden is.','If “Looking up host name” remains: try the HTTP test site and verify Wi-Fi connectivity in the RetroModem web interface.')}</li></ul></details>
<h3>{tr(language,'Bestanden','Files')}</h3><div class="notice warning"><strong>{tr(language,'Nog niet betrouwbaar.','Not yet reliable.')}</strong> {tr(language,'De ingebouwde EPOC-infraroodoverdracht kan halverwege of bij 95% afbreken. Alleen zeer kleine bestanden rond 1 KB zijn in de huidige configuratie praktisch gebleken, ook daarvoor bestaat geen garantie. Een bestand van 8 KB werkte eenmaal maar mislukte bij een identieke herhaling; 12 KB en groter is niet betrouwbaar. YMODEM via infrarood is eveneens apparaatafhankelijk en nog niet reproduceerbaar betrouwbaar. Gebruik voor grotere of belangrijke bestanden voorlopig een CF-kaart; YMODEM via USB-serieel moet nog fysiek worden geverifieerd. Ook de directe softwareknoppen hieronder kunnen via EPOC mislukken.','Native EPOC infrared transfer may stop midway or at 95%. Only very small files around 1 KB have proved practical in the current configuration, and even those are not guaranteed. An 8 KB file succeeded once but failed on an identical repeat; 12 KB and larger is not reliable. YMODEM over infrared is also device-dependent and not yet reproducibly reliable. For larger or important files, use a CF card for now; YMODEM over USB serial still requires physical verification. The direct software buttons below may therefore also fail over EPOC.')}</div><p>{tr(language,'Open in Comms Verzenden/Ontvangen en kies hetzelfde ASCII-, XMODEM-, YMODEM- of ZMODEM-protocol als op de Bestandsoverdrachtpagina. YMODEM werkte met een tweede 5mx in beide richtingen, maar niet betrouwbaar met het huidige testapparaat.','In Comms open Send/Receive and select the same ASCII-, XMODEM-, YMODEM- or ZMODEM protocol as on the File transfer page. YMODEM worked in both directions with a second 5mx, but not reliably with the current test device.')}</p><h3>{tr(language,'Nuttige software','Useful software')}</h3><div class="software-list">{software_card(language,title='Opera voor EPOC Release 5',description=tr(language,'Volwaardiger webbrowser voor de 5mx; veel moderne HTTPS-sites blijven onbruikbaar.','A more capable browser for the 5mx; many modern HTTPS sites remain unusable.'),compatibility='Psion 5mx · EPOC Release 5',source='https://software.psion.community/programs/uid/0x10004217/')}{software_card(language,title='Hermes',description=tr(language,'Sneller freeware-terminalprogramma als alternatief voor de ingebouwde Comms-app.','Faster freeware terminal application as an alternative to the built-in Comms app.'),compatibility='Psion Series 5/5mx',source='https://retrostuff.org/2019/12/09/serial-terminal-on-psion-serie-5mx-pro/')}</div><p>{tr(language,'Voor browsen kun je Opera of Web gebruiken; test eerst met <code>http://retroweb.bjrno.com</code>.','For browsing use Opera or Web; test first with <code>http://retroweb.bjrno.com</code>.')}</p></section>

<section class="card guide-panel" id="palm-old" hidden><h2>Palm OS 3.0/3.1</h2><p><strong>IrDA:</strong> {tr(language,'alleen modellen met ingebouwde IR-poort; deze generatie is nog niet fysiek getest.','only models with a built-in IR port; this generation has not yet been physically tested.')} <strong>{tr(language,'Serieel','Serial')}:</strong> {tr(language,'via cradle/kabel.','through a cradle/cable.')}</p><h3>Direct PPP</h3><ol><li>{tr(language,'Kies in Prefs → Serial/IR Infrared of Serial.','In Prefs → Serial/IR select Infrared or Serial.')}</li><li>{tr(language,'Prefs → Modem: 9600 voor IR; voor serieel dezelfde snelheid als RetroModem. Kies automatisch flow control.','Prefs → Modem: 9600 for IR; for serial use the same speed as RetroModem. Select automatic flow control.')}</li><li>{tr(language,'Prefs → Network: gebruiker <code>user</code>, leeg wachtwoord; Details: PPP. Werkt automatisch IP/DNS niet, gebruik dan IP <code>192.168.77.2</code> en DNS <code>1.1.1.1</code>/<code>8.8.8.8</code>. Script bevat alleen End.','Prefs → Network: user <code>user</code>, blank password; Details: PPP. If automatic IP/DNS fails, use IP <code>192.168.77.2</code> and DNS <code>1.1.1.1</code>/<code>8.8.8.8</code>. Script contains End only.')}</li></ol><h3>{tr(language,'Hayes-dial-up/BBS','Hayes dial-up/BBS')}</h3><p>{tr(language,'Alleen wanneer de Palm-verbinding modemcommando’s ondersteunt: bel 5559000 voor internet of een BBS-nummer. Gebruik een terminalprogramma voor interactieve BBS-sessies en zet local echo uit.','Only when the Palm connection supports modem commands: dial 5559000 for internet or a BBS number. Use a terminal application for interactive BBS sessions and disable local echo.')}</p><h3>{tr(language,'Bestanden','Files')}</h3><p>{tr(language,'Palm Beam gebruikt IrOBEX en is op de bestandspagina beschikbaar voor PRC/PDB-bestanden; deze oude OS-versies moeten nog worden getest. HotSync is iets anders en wordt niet nagebootst.','Palm Beam uses IrOBEX and is available on the file page for PRC/PDB files; these older OS releases still need testing. HotSync is separate and is not emulated.')}</p><h3>{tr(language,'Software','Software')}</h3><div class="software-list">{software_card(language,title='EudoraWeb 2.1',description=tr(language,'Snelle tekstbrowser zonder afbeeldingsondersteuning; PalmDB meldt compatibiliteit vanaf Palm OS 3.0.','Fast text browser without image support; PalmDB reports compatibility from Palm OS 3.0.'),compatibility='Palm OS 3.0–5.4 · freeware',software_id='eudoraweb-2.1',source='https://palmdb.net/app/eudora-eis')}{software_card(language,title='Mocha Telnet 3.0',description=tr(language,'Freeware Telnet/VT220- en SSH2-client voor klassieke Palms.','Freeware Telnet/VT220 and SSH2 client for classic Palms.'),compatibility='Palm OS 3.0+ · freeware · sleutel 119377',software_id='mocha-telnet-3.0',source='https://www.mochasoft.dk/palm2.htm')}</div></section>

<section class="card guide-panel" id="palm-new" hidden><h2>Palm OS 3.3–5.x</h2><p><strong>IrDA:</strong> {tr(language,'via Connection → Infrared waar aanwezig; getest op Palm IIIc met Palm OS 4.1.','through Connection → Infrared when available; tested on a Palm IIIc with Palm OS 4.1.')} <strong>{tr(language,'Serieel','Serial')}:</strong> {tr(language,'via cradle/kabel.','through a cradle/cable.')}</p><h3>Direct PPP</h3><ol><li>{tr(language,'Prefs → Connection → New: Connect to PC; Via Infrared of Serial.','Prefs → Connection → New: Connect to PC; Via Infrared or Serial.')}</li><li>{tr(language,'Details: 9600 voor IR; serieel gelijk aan RetroModem; Flow Ctl Automatic.','Details: 9600 for IR; serial equal to RetroModem; Flow Ctl Automatic.')}</li><li>{tr(language,'Prefs → Network: gebruiker <code>user</code>, leeg wachtwoord en de nieuwe verbinding. Details: PPP en Never. Zet Query DNS en Automatic IP uit; gebruik IP <code>192.168.77.2</code>, primaire DNS <code>1.1.1.1</code> en secundaire DNS <code>8.8.8.8</code>. Script: alleen End.','Prefs → Network: user <code>user</code>, blank password and the new connection. Details: PPP and Never. Disable Query DNS and Automatic IP; use IP <code>192.168.77.2</code>, primary DNS <code>1.1.1.1</code> and secondary DNS <code>8.8.8.8</code>. Script: End only.')}</li><li>{tr(language,'Richt de poorten uit en tik Connect. Signing on mag enkele seconden duren; RetroModem gebruikt bewust de normale PPP-onderhandelingstijd zodat Palm OS kan antwoorden.','Align the ports and tap Connect. Signing on may take several seconds; RetroModem deliberately uses the normal PPP negotiation interval so Palm OS has time to reply.')}</li></ol><h3>{tr(language,'Hayes-dial-up/BBS','Hayes dial-up/BBS')}</h3><p>{tr(language,'Maak indien beschikbaar een modemverbinding in plaats van PC Direct. Bel 5559000 voor internet of gebruik een terminalprogramma voor BBS-nummers; zet local echo daar uit.','When available, create a modem connection instead of PC Direct. Dial 5559000 for internet or use a terminal program for BBS numbers; disable local echo there.')}</p><h3>{tr(language,'Bestanden via Beam','Files through Beam')}</h3><p>{tr(language,'Open op de Palm de ontvangstfunctie voor Beam, kies op de Bestandsoverdrachtpagina <strong>Palm Beam</strong> en start daarna het verzenden. Dit gebruikt IrOBEX en staat los van HotSync. PRC- en PDB-bestanden worden ondersteund; RetroModem leest automatisch het Palm creator-ID.','Open Beam Receive on the Palm, select <strong>Palm Beam</strong> on the File transfer page and then start sending. This uses IrOBEX and is independent of HotSync. PRC and PDB files are supported; RetroModem reads the Palm creator ID automatically.')}</p><h3>{tr(language,'Nuttige software','Useful software')}</h3><div class="software-list">{software_card(language,title='EudoraWeb 2.1',description=tr(language,'Snelle tekstbrowser zonder afbeeldingen; deze freewareversie is met Palm OS 4.1 via Beam geïnstalleerd.','Fast text browser without images; this freeware release was installed over Beam on Palm OS 4.1.'),compatibility='Palm OS 3.0–5.4 · freeware',software_id='eudoraweb-2.1',source='https://palmdb.net/app/eudora-eis')}{software_card(language,title='Mocha Telnet 3.0',description=tr(language,'VT100/VT220- en SSH2-client, rechtstreeks van de freewarepagina van de maker.','VT100/VT220 and SSH2 client, obtained directly from the publisher’s freeware page.'),compatibility='Palm OS 3.0+ · freeware · sleutel 119377',software_id='mocha-telnet-3.0',source='https://www.mochasoft.dk/palm2.htm')}{software_card(language,title='ptelnet 0.7',description=tr(language,'GPLv3 Telnet/VT100-client; het project publiceert momenteel broncode maar geen gecontroleerde PRC-download.','GPLv3 Telnet/VT100 client; the project currently publishes source code but no verified PRC download.'),compatibility='Palm OS 3.5+ · GPLv3',source='https://github.com/migueletto/ptelnet')}{software_card(language,title='upIRC 3.8.3',description=tr(language,'IRC-client voor internetverbonden Palms; vanwege de onduidelijke distributiestatus alleen als externe verwijzing.','IRC client for networked Palms; external reference only because its distribution status is unclear.'),compatibility='Palm OS 3.0–5.4 · externe download',source='https://palmdb.net/app/upirc')}</div></section>

<section class="card guide-panel" id="hp200lx" hidden><h2>HP 200LX</h2><p><strong>IrDA:</strong> {tr(language,'niet compatibel met de huidige IrCOMM-driver; de 200LX gebruikt raw HPSIR.','not compatible with the current IrCOMM driver; the 200LX uses raw HPSIR.')} <strong>{tr(language,'Serieel','Serial')}:</strong> {tr(language,'de bruikbare route, met HP-seriële kabel en passende null-modemadapter.','the usable route, with an HP serial cable and suitable null-modem adapter.')}</p><h3>PPP</h3><p>{tr(language,'Gebruik DOS-PPP-software op COM1 en kies op RetroModem USB-serieel. Direct PPP is de eenvoudigste route; voor inbel-PPP kies je Hayes-dial-up en nummer 5559000. Snelheid en flow control moeten aan beide kanten gelijk zijn.','Use DOS PPP software on COM1 and select USB serial on RetroModem. Direct PPP is the simplest route; for dial-up PPP select Hayes dial-up and number 5559000. Speed and flow control must match at both ends.')}</p><h3>BBS</h3><p>{tr(language,'Gebruik een DOS-terminalprogramma op COM1, stuur <code>AT</code> en bel een nummer uit het telefoonboek. Zet local echo uit wanneer tekens dubbel verschijnen.','Use a DOS terminal program on COM1, send <code>AT</code> and dial a number from the phone book. Disable local echo if characters appear twice.')}</p><h3>{tr(language,'Bestanden','Files')}</h3><p>{tr(language,'Gebruik via de seriële kabel LapLink of een terminalprogramma met X/Y/ZMODEM. Raw-HPSIR/LapLink via infrarood is een afzonderlijke toekomstige backend.','Over the serial cable use LapLink or a terminal application offering X/Y/ZMODEM. Raw HPSIR/LapLink over infrared requires a separate future backend.')}</p></section>

<section class="card guide-panel" id="win95" hidden><h2>Windows 95</h2><p><strong>{tr(language,'Serieel','Serial')}:</strong> {tr(language,'aanbevolen en het meest voorspelbaar.','recommended and most predictable.')} <strong>IrDA:</strong> {tr(language,'alleen met Microsoft IR-monitorsupport en een passende MA-620-driver; ondersteuning verschilt per Windows 95-uitgave.','only with Microsoft IR Monitor support and a suitable MA-620 driver; support varies by Windows 95 release.')}</p><h3>{tr(language,'Internet','Internet')}</h3><p>{tr(language,'Installeer een standaardmodem op de gekozen COM-poort. Kies Hayes-dial-up op RetroModem en maak in Dial-Up Networking een verbinding naar <code>5559000</code>, gebruiker <code>user</code>, leeg wachtwoord. Voor Direct PPP is een directe-kabelverbinding/DCC-configuratie nodig.','Install a standard modem on the selected COM port. Select Hayes dial-up on RetroModem and create a Dial-Up Networking connection to <code>5559000</code>, user <code>user</code>, blank password. Direct PPP requires a direct-cable/DCC configuration.')}</p><h3>BBS</h3><p>{tr(language,'Gebruik HyperTerminal, dezelfde COM-snelheid en 8-N-1. Stuur <code>AT</code>, daarna bijvoorbeeld <code>ATDT5551000</code>; Local echo uit.','Use HyperTerminal, matching COM speed and 8-N-1. Send <code>AT</code>, then for example <code>ATDT5551000</code>; disable Local echo.')}</p><h3>{tr(language,'Bestanden','Files')}</h3><p>{tr(language,'HyperTerminal ondersteunt XMODEM, YMODEM en ZMODEM. Start aan één kant eerst ontvangen en kies op de RetroModem-pagina exact hetzelfde protocol.','HyperTerminal supports XMODEM, YMODEM and ZMODEM. Start receive on one side first and select exactly the same protocol on the RetroModem page.')}</p></section>

<section class="card guide-panel" id="win98" hidden><h2>Windows 98</h2><p><strong>IrDA:</strong> {tr(language,'bruikbaar wanneer de MA-620 correct als infraroodadapter is geïnstalleerd.','usable when the MA-620 is installed correctly as an infrared adapter.')} <strong>{tr(language,'Serieel','Serial')}:</strong> {tr(language,'via COM-poort en standaardmodem.','through a COM port and standard modem.')}</p><h3>{tr(language,'Internet','Internet')}</h3><p>{tr(language,'Voor serieel: standaardmodem plus Dial-Up Networking naar 5559000. Voor IR: kies de infrarood- of virtuele COM-poort die Windows aanmaakt. Gebruiker <code>user</code>, leeg wachtwoord, server assigned IP en DNS. Direct PPP kan via Direct Cable Connection.','For serial: standard modem plus Dial-Up Networking to 5559000. For IR: select the infrared or virtual COM port created by Windows. User <code>user</code>, blank password, server-assigned IP and DNS. Direct PPP can use Direct Cable Connection.')}</p><h3>BBS</h3><p>{tr(language,'Gebruik HyperTerminal op de seriële of infrarode virtuele COM-poort, 8-N-1, local echo uit, en bel met ATDT.','Use HyperTerminal on the serial or infrared virtual COM port, 8-N-1, local echo off, and dial using ATDT.')}</p><h3>{tr(language,'Bestanden','Files')}</h3><p>{tr(language,'Voor Wireless Link: lijn de IR-poorten uit, zet de ontvangende kant klaar en kies op de bestandspagina <strong>Windows Wireless Link (IrOBEX)</strong>. Voor HyperTerminal blijven X/Y/ZMODEM beschikbaar. Deze Wireless Link-route is geïmplementeerd maar nog niet fysiek getest.','For Wireless Link: align the IR ports, prepare the receiving side and select <strong>Windows Wireless Link (IrOBEX)</strong> on the file page. X/Y/ZMODEM remain available for HyperTerminal. This Wireless Link route is implemented but not yet physically tested.')}</p></section>

<section class="card guide-panel" id="winxp" hidden><h2>Windows XP</h2><p><strong>IrDA:</strong> {tr(language,'via de Windows-infraroodstack als de dongle/driver herkend wordt.','through the Windows infrared stack when the dongle/driver is recognized.')} <strong>{tr(language,'Serieel','Serial')}:</strong> {tr(language,'via een COM-poort en standaard 56k-modemprofiel.','through a COM port and standard 56k modem profile.')}</p><h3>{tr(language,'Internet','Internet')}</h3><p>{tr(language,'Maak voor Hayes-dial-up een nieuwe inbelverbinding met telefoonnummer <code>5559000</code>, gebruiker <code>user</code> en leeg wachtwoord. Selecteer als modem de seriële COM-poort of het door Windows gemaakte infraroodmodem. IP en DNS automatisch.','For Hayes-dial-up create a new dial-up connection using phone number <code>5559000</code>, user <code>user</code> and blank password. Select either the serial COM port modem or the infrared modem created by Windows. Automatic IP and DNS.')}</p><h3>BBS</h3><p>{tr(language,'Gebruik HyperTerminal vóór het verbinden via PPP. Kies de betreffende COM-poort, 8-N-1, hardware flow control waar beschikbaar en local echo uit.','Use HyperTerminal before connecting through PPP. Select the relevant COM port, 8-N-1, hardware flow control where available and local echo off.')}</p><h3>{tr(language,'Bestanden','Files')}</h3><p>{tr(language,'Open Wireless Link en zet de ontvangende kant klaar. Kies daarna op de RetroModem-bestandspagina <strong>Windows Wireless Link (IrOBEX)</strong>. Voor HyperTerminal blijven X/Y/ZMODEM beschikbaar. Deze IrOBEX-route is nog niet fysiek getest.','Open Wireless Link and prepare the receiving side. Then select <strong>Windows Wireless Link (IrOBEX)</strong> on the RetroModem file page. X/Y/ZMODEM remain available for HyperTerminal. This IrOBEX route has not yet been physically tested.')}</p></section>
<script>
const uploadedGuideSections={uploaded_guide_sections(language)};Object.entries(uploadedGuideSections).forEach(([id,content])=>{{const panel=document.getElementById(id);if(panel)panel.insertAdjacentHTML('beforeend',content)}});
const xpInternet=document.querySelector('#winxp h3');if(xpInternet?.nextElementSibling){{const result=document.createElement('p');result.className='notice';result.innerHTML='{tr(language,"Fysiek getest met Windows XP via het door Windows aangemaakte infraroodmodem: bel <code>5559000</code> met gebruiker <code>user</code>, leeg wachtwoord en automatische IP/DNS.","Physically tested with Windows XP through the infrared modem created by Windows: dial <code>5559000</code> with user <code>user</code>, a blank password, and automatic IP/DNS.")}';xpInternet.nextElementSibling.after(result)}}
const palmFileHeading=[...document.querySelectorAll('#palm-new h3')].find(heading=>heading.textContent.includes('{tr(language,"Bestanden","Files")}'));if(palmFileHeading?.nextElementSibling){{const result=document.createElement('p');result.className='notice';result.textContent='{tr(language,"Getest op een Palm IIIc met Palm OS 4.1: PRC-bestanden en memo’s als TXT kunnen vanaf de Palm naar RetroModem worden gebeamd.","Tested on a Palm IIIc with Palm OS 4.1: PRC files and memos exported as TXT can be beamed from the Palm to RetroModem.")}';palmFileHeading.nextElementSibling.after(result)}}
const verification={{
  'palm-old':[['','{tr(language,"Niet getest","Not tested")} · IrDA PPP'],['','{tr(language,"Niet getest","Not tested")} · USB-serieel'],['','{tr(language,"Niet getest","Not tested")} · Beam']],
  'palm-new':[['verified','{tr(language,"Getest","Tested")} · Palm IIIc/OS 4.1 · IrDA PPP'],['verified','{tr(language,"Getest","Tested")} · Beam naar Palm'],['verified','{tr(language,"Getest","Tested")} · Beam vanaf Palm · memo→TXT en PRC'],['','{tr(language,"Niet getest","Not tested")} · USB-serieel'],['','{tr(language,"Niet getest","Not tested")} · overige Palm-modellen']],
  'hp200lx':[['unsupported','{tr(language,"Niet ondersteund","Not supported")} · Infrarood (raw HPSIR)'],['','{tr(language,"Niet getest","Not tested")} · USB-serieel']],
  'win95':[['','{tr(language,"Niet getest","Not tested")} · Infrarood'],['','{tr(language,"Niet getest","Not tested")} · USB-serieel'],['','{tr(language,"Niet getest","Not tested")} · bestandsoverdracht']],
  'win98':[['','{tr(language,"Niet getest","Not tested")} · Infrarood'],['','{tr(language,"Niet getest","Not tested")} · USB-serieel'],['','{tr(language,"Niet getest","Not tested")} · bestandsoverdracht']],
  'winxp':[['verified','{tr(language,"Getest","Tested")} · IrDA inbelinternet'],['','{tr(language,"Niet getest","Not tested")} · USB-serieel'],['','{tr(language,"Niet getest","Not tested")} · bestandsoverdracht']]
}};
Object.entries(verification).forEach(([id,items])=>{{const panel=document.getElementById(id),heading=panel?.querySelector('h2');if(!heading)return;const row=document.createElement('div');row.className='verification';items.forEach(([kind,label])=>{{const badge=document.createElement('span');badge.className=kind;badge.textContent=label;row.appendChild(badge)}});heading.after(row)}});
const guideTabs=document.querySelector('.guide-tabs'),guideButtons=document.querySelectorAll('[data-guide]'),guidePanels=document.querySelectorAll('.guide-panel');guideTabs?.setAttribute('role','tablist');guideButtons.forEach(button=>button.setAttribute('role','tab'));function showGuide(id,updateHash=true){{if(!document.getElementById(id))id='generic';guidePanels.forEach(panel=>panel.hidden=panel.id!==id);guideButtons.forEach(button=>{{const active=button.dataset.guide===id;button.classList.toggle('active',active);button.setAttribute('aria-selected',active);button.tabIndex=active?0:-1}});if(updateHash)history.replaceState(null,'','#'+id)}}guideButtons.forEach((button,index)=>{{button.addEventListener('click',()=>showGuide(button.dataset.guide));button.addEventListener('keydown',event=>{{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();const next=(index+(event.key==='ArrowRight'?1:-1)+guideButtons.length)%guideButtons.length;guideButtons[next].focus();showGuide(guideButtons[next].dataset.guide)}})}});showGuide(location.hash.slice(1)||'generic',false);
</script>"""

    for device, title in (("generic", tr(language, "Algemene werkwijze", "General workflow")),
                          ("psion", "Psion Series 5mx"), ("palm-new", "Palm OS 3.3–5.x")):
        heading = f"<h2>{title}</h2>"
        body = body.replace(heading, heading + irda_speed_guide(language, device), 1)
    palm_dns_help = ('<div class="notice"><strong>' + tr(language, 'IP en DNS op de Palm', 'Palm IP and DNS') + '</strong><p>' + tr(language,
        'Werkt automatische toewijzing niet, zet dan Query DNS en IP Address Automatic uit en vul onderstaande adressen handmatig in. Het eigen IP-adres is het adres van de Palm; de DNS-server is RetroModem.',
        'If automatic assignment fails, disable Query DNS and IP Address Automatic and enter the addresses below manually. The IP address belongs to the Palm; the DNS server is RetroModem.') + '</p><dl><dt>' + tr(language, 'Eigen IP-adres', 'Palm IP address') + '</dt><dd><code>192.168.77.2</code></dd><dt>' + tr(language, 'Primaire DNS', 'Primary DNS') + '</dt><dd><code>192.168.77.1</code></dd><dt>' + tr(language, 'Secundaire DNS', 'Secondary DNS') + '</dt><dd><code>192.168.77.1</code></dd></dl><p>' + tr(language,
        'Gebruik voor DNS geen 1.1.1.1 of 8.8.8.8: die kennen de lokale namen search.retromodem en chatgpt.retromodem niet. RetroModem zoekt ook gewone internetadressen voor je op. Verbreek na aanpassen de Palm-netwerkverbinding en verbind opnieuw. Open daarna http://search.retromodem of http://chatgpt.retromodem; een browserproxy is hiervoor niet nodig.',
        'Do not use 1.1.1.1 or 8.8.8.8 for DNS: they do not know the local names search.retromodem and chatgpt.retromodem. RetroModem also resolves ordinary internet addresses. Disconnect and reconnect the Palm network connection after changing these settings. Then open http://search.retromodem or http://chatgpt.retromodem; no browser proxy is needed for these pages.') + '</p></div>')
    body = re.sub(r'(<section class="card guide-panel" id="palm-(?:old|new)".*?<h3>Direct PPP</h3>)', lambda match: match.group(1) + palm_dns_help, body, flags=re.S)
    corrections = {
        "Mobile Action MA-620; fysieke linksnelheid 9600 bit/s.": "Kies MY018 of MA-620 op de Modem-pagina; zie de adapterinstellingen hierboven.",
        "Mobile Action MA-620; physical link speed 9600 bps.": "Select MY018 or MA-620 on the Modem page; see the adapter settings above.",
        "Voor IR: infrarode mobiele telefoon, 9600 bit/s.": "Voor IR: infrarode mobiele telefoon; 9600 bit/s voor MA-620 of 57600 voor de aangepaste MY018-opstelling.",
        "For IR: infrared mobile phone, 9600 bps.": "For IR: infrared mobile phone; 9600 bps for MA-620 or 57600 for the modified MY018 setup.",
        "Details: 9600 voor IR; serieel gelijk aan RetroModem; Flow Ctl Automatic.": "Details: voor IR 9600 met MA-620 of 57600 met aangepaste MY018; serieel gelijk aan RetroModem; Flow Ctl Automatic. Dit profiel geldt voor PPP, niet voor Beam.",
        "Details: 9600 for IR; serial equal to RetroModem; Flow Ctl Automatic.": "Details: for IR use 9600 with MA-620 or 57600 with modified MY018; serial equal to RetroModem; Flow Ctl Automatic. This profile is for PPP, not Beam.",
        "DNS <code>1.1.1.1</code>/<code>8.8.8.8</code>": "primaire en secundaire DNS <code>192.168.77.1</code>" if language == 'nl' else "primary and secondary DNS <code>192.168.77.1</code>",
        "primaire DNS <code>1.1.1.1</code> en secundaire DNS <code>8.8.8.8</code>": "primaire en secundaire DNS <code>192.168.77.1</code>",
        "primary DNS <code>1.1.1.1</code> and secondary DNS <code>8.8.8.8</code>": "primary and secondary DNS <code>192.168.77.1</code>",
    }
    for old, new in corrections.items():
        body = body.replace(old, new)
    return body


def wifi_modules():
    try:
        import wifi_web
        import wifi_network
    except ModuleNotFoundError:
        from web import wifi_web, wifi_network
    return wifi_web, wifi_network


class Handler(BaseHTTPRequestHandler):
    server_version = "RetroModem/0.1"

    def serve_retro_home(self, host: str) -> None:
        language = self.config().get('RETROMODEM_LANGUAGE', 'nl')
        t = lambda nl, en: tr(language, nl, en)
        if host == 'setup.retromodem':
            title = t('Instellingen', 'Settings')
            body = ('<p><a href="http://wifi.retromodem/">Wi-Fi</a><br>' +
                    t('Bekijk de verbinding, zoek netwerken en verbind met Wi-Fi.',
                      'View the connection, scan networks and connect to Wi-Fi.') + '</p>' +
                    '<p>' + t('Meer instellingen voor dit apparaat volgen later.',
                               'More settings for this device will follow.') + '</p>')
        else:
            title = 'RetroModem'
            body = ('<p><a href="http://search.retromodem/">' + t('Zoeken', 'Search') + '</a><br>' +
                    t('Zoek op internet en open resultaten via de webproxy.',
                      'Search the internet and open results through the web proxy.') + '</p>' +
                    '<p><a href="http://chatgpt.retromodem/">ChatGPT</a><br>' +
                    t('Chat met ChatGPT. Koppel eerst je account via de beheerinterface.',
                      'Chat with ChatGPT. Connect your account through the administration interface first.') + '</p>' +
                    '<p><a href="http://setup.retromodem/">' + t('Instellingen', 'Settings') + '</a><br>' +
                    t('Stel RetroModem in vanaf dit apparaat.', 'Configure RetroModem from this device.') + '</p>')
        body += '<p><a href="http://start.retromodem/">' + t('Startpagina', 'Home') + '</a></p>' if host == 'setup.retromodem' else ''
        content = ('<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML 2.0//EN"><html><head><title>' +
                   title + '</title></head><body><h1>' + title + '</h1>' + body + '</body></html>').encode('iso-8859-1', 'xmlcharrefreplace')
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=iso-8859-1')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def config(self) -> dict[str, str]:
        return load_config()

    def serve_retro_wifi(self) -> None:
        frontend, network = wifi_modules()
        frontend.serve(self, status=network.status, scan=network.scan, connect=network.connect)

    def authenticated(self, config: dict[str, str]) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(username, "retromodem") and hmac.compare_digest(
            password, config.get("RETROMODEM_WEB_PASSWORD", "retromodem")
        )

    def require_auth(self, config: dict[str, str]) -> bool:
        if self.authenticated(config):
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="RetroModem", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def csrf(self) -> str:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        token = cookie.get("retromodem_csrf")
        if token and token.value in CSRF_TOKENS:
            return token.value
        value = secrets.token_urlsafe(24)
        CSRF_TOKENS.add(value)
        return value

    def send_page(self, title: str, body: str, config: dict[str, str], *, refresh: int | None = None) -> None:
        token = self.csrf()
        language = config.get("RETROMODEM_LANGUAGE", "nl")
        content = page(title, body.replace("{{csrf}}", html.escape(token)), language, token, refresh)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Set-Cookie", f"retromodem_csrf={token}; Path=/; SameSite=Strict; HttpOnly")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def form(self) -> dict[str, str]:
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 8192)
        except ValueError:
            length = 0
        data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        return {key: values[-1] for key, values in data.items()}

    def multipart(self) -> tuple[dict[str, str], str, bytes]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 32 * 1024 * 1024:
            raise ValueError("Bestand is groter dan 32 MB")
        content_type = self.headers.get("Content-Type", "")
        raw = self.rfile.read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw
        )
        fields, filename, payload = {}, "", b""
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            if part.get_filename() is not None:
                filename = Path(part.get_filename()).name
                payload = part.get_payload(decode=True) or b""
            else:
                fields[name] = (part.get_content() or "").strip()
        return fields, filename, payload

    def valid_csrf(self, form: dict[str, str]) -> bool:
        return form.get("csrf", "") in CSRF_TOKENS and hmac.compare_digest(form.get("csrf", ""), self.csrf())

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_json(self, document: object) -> None:
        content = json.dumps(document, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:  # noqa: N802
        config = self.config()
        host = getattr(self, "headers", {}).get("Host", "").split(":", 1)[0].lower().rstrip(".")
        if host in {'start.retromodem', 'setup.retromodem'}:
            self.serve_retro_home(host)
            return
        if host == 'wifi.retromodem':
            self.serve_retro_wifi()
            return
        if host == "chatgpt.retromodem":
            try:
                import chatgpt_web
            except ModuleNotFoundError:
                from web import chatgpt_web
            chatgpt_web.serve(self)
            return
        if host == "search.retromodem":
            try:
                request = urllib.request.Request("http://127.0.0.1:8080" + self.path, headers={
                    "Host": "search.retromodem",
                    "X-Retromodem-Client": getattr(self, 'client_address', ('127.0.0.1', 0))[0],
                })
                with urllib.request.urlopen(request, timeout=45) as response:
                    content = response.read(8 * 1024 * 1024 + 1)
                    content_type = response.headers.get("Content-Type", "text/html; charset=iso-8859-1")
                if len(content) > 8 * 1024 * 1024:
                    raise ValueError('Local proxy response too large')
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.end_headers()
                self.wfile.write(content)
            except urllib.error.HTTPError as error:
                self.send_error(error.code if error.code in {400, 403, 404, 410, 413} else HTTPStatus.BAD_GATEWAY)
            except (OSError, urllib.error.URLError, ValueError):
                self.send_error(HTTPStatus.BAD_GATEWAY, tr(config.get('RETROMODEM_LANGUAGE', 'nl'), 'Zoekpagina niet beschikbaar', 'Search page unavailable'))
            return
        if not self.require_auth(config):
            return
        language = config.get("RETROMODEM_LANGUAGE", "nl")
        path = urllib.parse.urlsplit(self.path).path
        if path == "/transfer/status":
            try:
                status = json.loads((TRANSFERS / "status.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                status = {"state": "idle", "message": "Geen overdracht actief"}
            if status.get("state") == "running" and not transfer_process_alive(status):
                status.update({"state": "error", "message": "Overdracht onverwacht beëindigd",
                               "finished": int(time.time()), "phase": "finished"})
                save_transfer_status(status)
                subprocess.Popen(["/usr/local/lib/retromodem/apply-mode"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            RECEIVED.mkdir(parents=True, exist_ok=True)
            status["received"] = [
                {"name": item.name, "size": human_size(item.stat().st_size),
                 "date": time.strftime("%d-%m-%Y %H:%M", time.localtime(item.stat().st_mtime)),
                 "url": f"/transfer/download?name={urllib.parse.quote(item.name)}"}
                for item in sorted(RECEIVED.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
                if item.is_file()
            ]
            status["pending_send"] = pending_send()
            self.send_json(status)
            return
        if path.startswith("/static/"):
            relative = path.removeprefix("/static/")
            if not re.fullmatch(r"[A-Za-z0-9_./-]+", relative) or ".." in relative.split("/"):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            asset = STATIC_ROOT / relative
            try:
                content = asset.read_bytes()
            except (FileNotFoundError, IsADirectoryError):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content_type = {
                ".gif": "image/gif",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".webp": "image/webp",
            }.get(asset.suffix.lower(), "application/octet-stream")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/library/download":
            software_id = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id", [""])[0]
            item = load_library().get(software_id)
            if item is None:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            asset = LIBRARY_ROOT / Path(str(item.get("stored_name", ""))).name
            if not asset.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content = asset.read_bytes()
            download_name = library_filename(item, asset)
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/transfer/download":
            name = Path(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("name", [""])[0]).name
            asset = RECEIVED / name
            if not name or not asset.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content = asset.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return
        if path == "/":
            state, ssid = wifi_state(config)
            inventory = usb_inventory()
            by_transport = {item["transport"]: item for item in inventory}
            transport = config.get("RETROMODEM_TRANSPORT", "irda")
            line_mode = config.get("RETROMODEM_LINE_MODE", "ppp")
            selected = by_transport.get(transport)
            irda_ready = service_active("retromodem-irda.service") or Path("/sys/class/net/irda0").exists()
            ppp_service = service_active("retromodem-ppp.service")
            tcpser_service = service_active("retromodem-tcpser.service")
            ppp_operstate = Path("/sys/class/net/ppp0/operstate")
            try:
                ppp_connected = ppp_operstate.read_text(encoding="utf-8").strip() == "up"
            except OSError:
                ppp_connected = False
            wifi_connected = state.startswith("100") or "connected" in state.lower() or "verbonden" in state.lower()
            addresses = ipv4_addresses()
            mode_label = tr(language, "Direct internet (PPP)", "Direct internet (PPP)") if line_mode == "ppp" else tr(language, "Inbelmodem (Dial-Up) en BBS", "Dial-up modem and BBS")
            adapter_label = IR_ADAPTERS[ir_adapter_id(config)]["name"] if transport == "irda" else "Prolific PL2303"
            medium_label = tr(language, "infrarood", "infrared") if transport == "irda" else tr(language, "USB-serieel", "USB serial")
            route = f"{mode_label} {tr(language, 'via', 'over')} {medium_label}"
            backend_ok = ppp_service if line_mode == "ppp" else tcpser_service
            operational = bool(selected and wifi_connected and backend_ok and (irda_ready if transport == "irda" else True))
            overall = tr(language, "Operationeel", "Operational") if operational else tr(language, "Aandacht nodig", "Needs attention")
            overall_class = "ok" if operational else "warn"

            adapter_rows = []
            adapter_specs = [
                ("irda", "Mobile Action MA-620", "0df7:0620", config.get("RETROMODEM_IRDA_BITRATE", "9600")),
                ("serial", "Prolific PL2303", "067b:2303", config.get("RETROMODEM_SERIAL_BITRATE", "115200")),
            ]
            if ir_adapter_id(config) == "ming-yuan-my018":
                gpio = {"name": IR_ADAPTERS["ming-yuan-my018"]["name"], "tty": "/dev/serial0", "transport": "irda", "usb_id": "GPIO"}
                selected = gpio if transport == "irda" and irda_ready else selected
                by_transport["irda"] = gpio if irda_ready else None
                adapter_specs[0] = ("irda", gpio["name"], "GPIO UART", config.get("RETROMODEM_IRDA_BITRATE", "9600"))
                operational = bool(selected and wifi_connected and backend_ok and irda_ready) if transport == "irda" else operational
                overall = tr(language, "Operationeel", "Operational") if operational else tr(language, "Aandacht nodig", "Needs attention")
                overall_class = "ok" if operational else "warn"
                for usb_item in inventory:
                    if usb_item["usb_id"] == "0df7:0620":
                        adapter_specs.append(("fallback", usb_item["name"], "0df7:0620", config.get("RETROMODEM_MA620_BITRATE", "9600")))
                        by_transport["fallback"] = usb_item
            for kind, name, usb_id, bitrate in adapter_specs:
                item = by_transport.get(kind)
                connected = item is not None
                if kind == transport:
                    chips = [f'<span class="chip {"active" if connected else "bad"}">{tr(language,"In gebruik","In use") if connected else tr(language,"Niet gevonden","Not found")}</span>']
                else:
                    chips = [f'<span class="chip">{tr(language,"Beschikbaar","Available") if connected else tr(language,"Niet aangesloten","Not connected")}</span>']
                detail = f'{html.escape(item["tty"])} · {bitrate} bit/s' if item else (tr(language, "GPIO-module gekozen; niet actief", "GPIO module selected; inactive") if usb_id == "GPIO UART" else f'USB {usb_id}')
                adapter_rows.append(f'<div class="status-row"><div><strong>{name}</strong><small>{detail}</small></div><div>{" ".join(chips)}</div></div>')
            for item in inventory:
                if item["transport"] in {"irda", "serial"}:
                    continue
                adapter_rows.append(f'<div class="status-row"><div><strong>{html.escape(item["name"])}</strong><small>{html.escape(item["tty"])} · USB {item["usb_id"]}</small></div><span class="chip ok">{tr(language,"Aangesloten","Connected")}</span></div>')

            transfer = transfer_status()
            transfer_running = transfer.get("state") == "running" and transfer_process_alive(transfer)
            if transfer_running:
                transfer_text = html.escape(str(transfer.get("message", tr(language, "Overdracht actief", "Transfer active"))))
                transfer_chip = f'<span class="chip active">{tr(language,"Actief","Active")}</span>'
            else:
                transfer_text = tr(language, "Geen overdracht actief", "No active transfer")
                transfer_chip = f'<span class="chip">{tr(language,"Gereed","Ready")}</span>'

            service_rows = [
                ("IrDA-stack", irda_ready, tr(language, "Draait", "Running") if irda_ready else tr(language, "Gestopt", "Stopped"), tr(language, "Gereed", "Ready") if irda_ready else tr(language, "Inactief", "Inactive")),
                ("Direct PPP", ppp_service, tr(language, "Verbonden", "Connected") if ppp_connected else (tr(language, "Wacht op verbinding", "Waiting for connection") if ppp_service else tr(language, "Gestopt", "Stopped")), tr(language, "Verbonden", "Connected") if ppp_connected else (tr(language, "Gereed", "Ready") if ppp_service else tr(language, "Inactief", "Inactive"))),
                ("Hayes / tcpser", tcpser_service, tr(language, "Wacht op oproep", "Waiting for call") if tcpser_service else tr(language, "Niet gekozen", "Not selected"), tr(language, "Gereed", "Ready") if tcpser_service else tr(language, "Inactief", "Inactive")),
                (tr(language, "Webinterface", "Web interface"), True, tr(language, "Draait", "Running"), tr(language, "Gereed", "Ready")),
            ]
            services_html = "".join(
                f'<div class="status-row"><div><strong>{label}</strong><small>{status}</small></div><span class="chip {"ok" if active else ""}">{chip_text}</span></div>'
                for label, active, status, chip_text in service_rows
            )
            ip_text = " · ".join(addresses) if addresses else "—"
            hero_detail = tr(language, "Klaar voor een verbinding van een retroapparaat", "Ready for a connection from a retro device")
            if ppp_connected:
                hero_detail = tr(language, "Retroapparaat verbonden", "Retro device connected")
            selected_bitrate = (config.get("RETROMODEM_IRDA_BITRATE", "9600") if transport == "irda"
                                else config.get("RETROMODEM_SERIAL_BITRATE", "115200"))
            body = f"""<section class="card hero"><div><span class="chip {overall_class}">{overall}</span><h2>{html.escape(route)}</h2><p>{hero_detail}</p></div><a class="button primary" href="/modem">{tr(language,'Verbinding wijzigen','Change connection')}</a></section>
<div class="dashboard">
<section class="card span-6"><h2>{tr(language,'Actieve verbinding','Active connection')}</h2><dl><dt>Adapter</dt><dd>{html.escape(adapter_label)}</dd><dt>{tr(language,'Aansluiting','Connection')}</dt><dd>{medium_label.capitalize()}</dd><dt>{tr(language,'Functie','Function')}</dt><dd>{mode_label}</dd><dt>{tr(language,'Snelheid','Speed')}</dt><dd>{selected_bitrate} bit/s</dd></dl></section>
<section class="card span-6"><h2>{tr(language,'Netwerk','Network')}</h2><div class="status-list"><div class="status-row"><div><strong>{html.escape((tr(language, 'Verbonden met ', 'Connected to ') + ssid) if ssid else tr(language, 'Wi-Fi verbonden', 'Wi-Fi connected'))}</strong><small>{html.escape(ip_text)} · retromodem.local</small></div><span class="chip {'ok' if wifi_connected else 'bad'}">{tr(language,'Verbonden','Connected') if wifi_connected else tr(language,'Offline','Offline')}</span></div><div class="status-row"><div><strong>{tr(language,'Draadloos netwerk','Wireless network')}</strong><small>{tr(language,'Netwerk kiezen of wijzigen','Select or change network')}</small></div><a class="button" href="/wifi">Wi-Fi</a></div></div></section>
<section class="card span-6"><h2>{tr(language,'Knop op het apparaat','Button on the device')}</h2><dl><dt>{tr(language,'Kort drukken','Short press')}</dt><dd>{tr(language,'Wissel tussen Direct internet (PPP) en Inbelmodem (Dial-Up) en BBS','Switch between Direct internet and Dial-up modem')}</dd><dt>{tr(language,'3 seconden','3 seconds')}</dt><dd>{tr(language,'Veilig uitschakelen; laat los wanneer beide leds knipperen','Shut down safely; release when both LEDs flash')}</dd><dt>PPP-led</dt><dd>{tr(language,'Direct internet (PPP) gekozen','Direct internet selected')}</dd><dt>{tr(language,'Inbel-led','Dial-up LED')}</dt><dd>{tr(language,'Inbelmodem (Dial-Up) en BBS gekozen','Dial-up modem and BBS selected')}</dd></dl></section>
<section class="card span-6"><h2>{tr(language,'Bestandsoverdracht','File transfer')}</h2><div class="status-row"><div><strong>{transfer_text}</strong><small>{html.escape(str(transfer.get('protocol','')).upper()) if transfer_running else tr(language,'Klaar voor een nieuwe overdracht','Ready for a new transfer')}</small></div>{transfer_chip}</div><div class="actions"><a class="button primary" href="/transfer">{tr(language,'Bestand overzetten','Transfer a file')}</a><a class="button" href="/guides">{tr(language,'Handleiding openen','Open guide')}</a></div></section>
<details class="card span-12 technical"><summary>{tr(language,'Technische status','Technical status')}</summary><h2>{tr(language,'Adapters en diensten','Adapters and services')}</h2><div class="grid"><div class="status-list">{''.join(adapter_rows)}</div><div class="status-list">{services_html}</div></div></details>
</div>"""
            self.send_page("Status", body, config)
        elif path == "/modem":
            transport = config.get("RETROMODEM_TRANSPORT", "irda")
            line_mode = config.get("RETROMODEM_LINE_MODE", "ppp")
            irda_bitrate = config.get("RETROMODEM_IRDA_BITRATE", config.get("RETROMODEM_BITRATE", "9600"))
            irda_dialup_bitrate = config.get("RETROMODEM_IRDA_DIALUP_BITRATE", "115200")
            serial_bitrate = config.get("RETROMODEM_SERIAL_BITRATE", "115200")
            serial_dialup_bitrate = config.get("RETROMODEM_SERIAL_DIALUP_BITRATE", config.get("RETROMODEM_DIALUP_BITRATE", "115200"))
            body = f"""<div class="page-heading"><h1>{tr(language,'Verbinding','Connection')}</h1><p>{tr(language,'Kies hoe je retroapparaat wordt aangesloten en wat RetroModem voor het apparaat moet doen.','Choose how your retro device connects and what RetroModem should provide.')}</p></div><section class="card"><h2>{tr(language,'Actieve verbinding kiezen','Choose active connection')}</h2>
<form method="post" action="/modem/settings"><input type="hidden" name="csrf" value="{{{{csrf}}}}">
<label>{tr(language,'Hoe wil je aansluiten?','How do you want to connect?')}</label><select id="adapter-select" name="transport"><option value="irda" {'selected' if transport == 'irda' else ''}>{tr(language,'Infrarood','Infrared')} </option><option value="serial" {'selected' if transport == 'serial' else ''}>USB-serieel · Prolific PL2303</option></select>
<label>{tr(language,'Wat wil je doen?','What do you want to do?')}</label><select name="line_mode"><option value="ppp" {'selected' if line_mode == 'ppp' else ''}>{tr(language,'Direct internet (PPP)','Direct internet (PPP)')}</option><option value="dialup" {'selected' if line_mode == 'dialup' else ''}>{tr(language,'Inbelmodem (Dial-Up) en BBS','Dial-up modem and BBS')}</option></select><small class="helper">{tr(language,'Je kunt deze keuze ook wisselen met een korte druk op de knop van het apparaat.','You can also change this selection with a short press of the button on the device.')}</small>
<div class="adapter-settings form-section" data-adapter="irda">{ir_adapter_settings(config, language)}</div>
<div class="adapter-settings form-section" data-adapter="serial"><h3>{tr(language,'Instellingen voor USB-serieel','USB serial settings')}</h3><label>{tr(language,'Snelheid voor direct internet','Direct internet speed')}</label><select name="serial_bitrate">{''.join(f'<option value="{rate}" {"selected" if serial_bitrate == rate else ""}>{rate}</option>' for rate in ('9600','19200','38400','57600','115200'))}</select><label>{tr(language,'Snelheid voor inbelmodem','Dial-up modem speed')}</label><select name="serial_dialup_bitrate">{''.join(f'<option value="{rate}" {"selected" if serial_dialup_bitrate == rate else ""}>{rate}</option>' for rate in ('300','1200','2400','4800','9600','19200','38400','57600','115200'))}</select></div>
<button class="primary" type="submit">{tr(language,'Verbinding toepassen','Apply connection')}</button></form></section>
<script>const adapter=document.getElementById('adapter-select');const irAdapter=document.getElementById('irda-adapter');function showAdapter(){{document.querySelectorAll('.adapter-settings').forEach(section=>section.hidden=section.dataset.adapter!==adapter.value);document.querySelectorAll('[data-ir-profile]').forEach(section=>section.hidden=section.dataset.irProfile!==irAdapter.value)}}adapter.addEventListener('change',showAdapter);irAdapter.addEventListener('change',showAdapter);showAdapter();document.querySelectorAll('[data-speed-warning]').forEach(warning=>{{const select=warning.closest('[data-ir-profile]').querySelector('select[name$="_bitrate"]');function showSpeedWarning(){{warning.hidden=select.value!==warning.dataset.speedWarning}}select.addEventListener('change',showSpeedWarning);showSpeedWarning()}});</script>"""
            self.send_page("Modem", body, config)
        elif path == "/phonebook":
            self.send_page(tr(language, "Telefoonboek", "Phone book"), phonebook_page(language), config)
        elif path == "/wifi":
            networks = scan_wifi(config)
            wifi_status, current_ssid = wifi_state(config)
            wifi_connected = wifi_status.startswith("100") or "connected" in wifi_status.lower() or "verbonden" in wifi_status.lower()
            rows = "".join(
                f'<option value="{html.escape(ssid, quote=True)}">{html.escape(ssid)} · {signal}% · {html.escape(security)}</option>'
                for ssid, signal, security in networks
            )
            body = f"""<div class="page-heading"><h1>Wi-Fi</h1><p>{tr(language,'Bekijk de huidige verbinding of laat RetroModem met een ander draadloos netwerk verbinden.','View the current connection or connect RetroModem to another wireless network.')}</p></div><section class="card"><h2>{tr(language,'Huidige verbinding','Current connection')}</h2><div class="status-row"><div><strong>{html.escape(current_ssid or tr(language,'Geen netwerknaam beschikbaar','Network name unavailable'))}</strong><small>retromodem.local</small></div><span class="chip {'ok' if wifi_connected else 'bad'}">{tr(language,'Verbonden','Connected') if wifi_connected else tr(language,'Offline','Offline')}</span></div></section>
<section class="card"><h2>{tr(language,'Netwerk wijzigen','Change network')}</h2>
<div class="notice warning">{tr(language,'Tijdens het overschakelen kan deze pagina kort onbereikbaar zijn. Open daarna opnieuw','This page may briefly become unavailable while switching. Afterwards, reopen')} <code>http://retromodem.local</code>.</div>
<form method="post" action="/wifi/connect"><input type="hidden" name="csrf" value="{{{{csrf}}}}">
<label for="ssid">{tr(language,'Netwerk','Network')}</label><select id="ssid" name="ssid" required>{rows}</select>
<small class="helper">{tr(language,'De lijst wordt opnieuw gescand wanneer je deze pagina opent.','The list is rescanned whenever you open this page.')}</small>
<label for="password">{tr(language,'Wachtwoord','Password')}</label><input id="password" name="password" type="password" autocomplete="current-password">
<button class="primary" type="submit">{tr(language,'Met dit netwerk verbinden','Connect to this network')}</button></form></section>"""
            body += '<section class="card"><p>' + tr(language, 'Wi-Fi instellen vanaf je aangesloten retroapparaat kan ook via', 'You can also configure Wi-Fi from your connected retro device at') + ' <a href="http://wifi.retromodem/">wifi.retromodem</a>. ' + tr(language, 'Alle lokale functies vind je op', 'Find all local features at') + ' <a href="http://start.retromodem/">start.retromodem</a>.</p></section>'
            self.send_page("Wi-Fi", body, config)
        elif path == "/transfer":
            try:
                status = json.loads((TRANSFERS / "status.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                status = {"state": "idle", "message": tr(language, "Geen overdracht actief", "No transfer active")}
            RECEIVED.mkdir(parents=True, exist_ok=True)
            downloads = "".join(
                f'<li><div><strong>{html.escape(item.name)}</strong><small class="helper">{human_size(item.stat().st_size)} · {time.strftime("%d-%m-%Y %H:%M", time.localtime(item.stat().st_mtime))}</small></div><div class="file-actions"><a class="button secondary" href="/transfer/download?name={urllib.parse.quote(item.name)}">{tr(language,"Downloaden","Download")}</a><form method="post" action="/transfer/delete"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><input type="hidden" name="name" value="{html.escape(item.name, quote=True)}"><button class="danger" type="submit">{tr(language,"Verwijderen","Delete")}</button></form></div></li>'
                for item in sorted(RECEIVED.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:10] if item.is_file()
            )
            status["received"] = [
                {"name": item.name, "size": human_size(item.stat().st_size),
                 "date": time.strftime("%d-%m-%Y %H:%M", time.localtime(item.stat().st_mtime)),
                 "url": f"/transfer/download?name={urllib.parse.quote(item.name)}"}
                for item in sorted(RECEIVED.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
                if item.is_file()
            ]
            status["pending_send"] = pending_send()
            status_json = json.dumps(status, ensure_ascii=False).replace("<", "\\u003c")
            body = f"""<div class="page-heading"><h1>{tr(language,'Bestandsoverdracht','File transfer')}</h1><p>{tr(language,'Stuur losse bestanden naar een retroapparaat of ontvang ze op RetroModem. Kies aan beide kanten hetzelfde protocol.','Send individual files to a retro device or receive them on RetroModem. Select the same protocol on both ends.')}</p></div><section class="card" id="transfer-status" role="status" aria-live="polite"><div class="transfer-status"><span class="status-icon" id="status-icon">●</span><div><div class="status-title" id="status-title">{html.escape(str(status.get('message','Geen overdracht actief')))}</div><div class="status-meta" id="status-meta"></div><div class="progress" id="progress" hidden><span></span></div></div><form method="post" action="/transfer/cancel" id="cancel-form" hidden><input type="hidden" name="csrf" value="{{{{csrf}}}}"><button class="danger" type="submit">{tr(language,'Overdracht stoppen','Stop transfer')}</button></form></div><details class="technical" id="technical" hidden><summary>{tr(language,'Technische details','Technical details')}</summary><pre id="technical-output"></pre></details></section>
<div class="grid"><section class="card"><h2>{tr(language,'Naar apparaat verzenden','Send to device')}</h2><p>{tr(language,'Zet het retroapparaat eerst klaar om te ontvangen. Kies daarna hier het bestand en start de overdracht.','First prepare the retro device to receive. Then select the file here and start the transfer.')}</p><form method="post" action="/transfer/start" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><input type="hidden" name="direction" value="send"><label>{tr(language,'Bestand','File')}</label><input type="file" name="file" required><label>Protocol</label><select name="protocol" data-protocol="send"><optgroup label="{tr(language,'Terminalprotocollen (IR of serieel)','Terminal protocols (IR or serial)')}"><option value="ymodem">YMODEM — bestandsnaam en batch</option><option value="xmodem">XMODEM — breed compatibel</option><option value="zmodem">ZMODEM — automatisch, hervatten</option><option value="ascii">ASCII — platte tekst, geen foutcontrole</option></optgroup><optgroup label="{tr(language,'Apparaatspecifiek via infrarood','Device-specific over infrared')}"><option value="palm">Palm Beam (IrOBEX) — PRC/PDB</option><option value="windows">Windows Wireless Link (IrOBEX) — nog niet getest</option><option value="epoc">Psion/EPOC EikonIr — experimenteel</option></optgroup></select><p class="helper" id="send-protocol-help" hidden></p><button class="primary" type="submit">{tr(language,'Verzenden starten','Start sending')}</button></form></section>
<section class="card"><h2>{tr(language,'Van apparaat ontvangen','Receive from device')}</h2><p>{tr(language,'Start hier eerst de ontvangst. Begin daarna pas met verzenden op het retroapparaat.','Start receiving here first. Only then start sending on the retro device.')}</p><form method="post" action="/transfer/start" enctype="multipart/form-data"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><input type="hidden" name="direction" value="receive"><label>Protocol</label><select name="protocol" data-protocol="receive"><optgroup label="{tr(language,'Terminalprotocollen (IR of serieel)','Terminal protocols (IR or serial)')}"><option value="zmodem">ZMODEM — automatisch, hervatten</option><option value="ymodem">YMODEM — bestandsnaam en batch</option><option value="xmodem">XMODEM — één bestand</option><option value="ascii">ASCII — stopt na 120 seconden</option></optgroup><optgroup label="{tr(language,'Apparaatspecifiek via infrarood','Device-specific over infrared')}"><option value="palm">Palm Beam (IrOBEX) — PRC/PDB/TXT</option><option value="windows">Windows Wireless Link (IrOBEX) — nog niet getest</option><option value="epoc">Psion/EPOC EikonIr — experimenteel</option></optgroup></select><div id="receive-filename"><label>{tr(language,'Bestandsnaam voor XMODEM/ASCII','Filename for XMODEM/ASCII')}</label><input name="filename" value="received-file.bin"></div><button class="primary" type="submit">{tr(language,'Ontvangst starten','Start receiving')}</button></form></section></div>
<section class="card received-files" id="received-files"><h2>{tr(language,'Ontvangen bestanden','Received files')}</h2><p class="helper">{tr(language,'Nieuwe ontvangsten verschijnen hier automatisch.','Newly received files appear here automatically.')}</p><ul class="file-list" id="received-list">{downloads or '<li>—</li>'}</ul></section>
<p class="helper">{tr(language,'Weet je niet welk protocol je nodig hebt? Open de handleiding van je apparaat. Psion/EPOC-overdracht blijft experimenteel en kan op sommige apparaten mislukken.','Unsure which protocol to use? Open your device guide. Psion/EPOC transfer remains experimental and may fail on some devices.')} <a href="/guides">{tr(language,'Naar handleidingen','Open guides')}</a>.</p>
<script>
const selects=document.querySelectorAll('[data-protocol]'),requestedProtocol=new URLSearchParams(location.search).get('protocol');selects.forEach(s=>{{const key='retromodem-'+s.dataset.protocol+'-protocol',saved=localStorage.getItem(key),requested=s.dataset.protocol==='send'?requestedProtocol:null;if(requested&&s.querySelector('option[value="'+CSS.escape(requested)+'"]')){{s.value=requested;localStorage.setItem(key,requested)}}else if(saved&&s.querySelector('option[value="'+CSS.escape(saved)+'"]'))s.value=saved;else localStorage.setItem(key,s.value);s.addEventListener('change',()=>localStorage.setItem(key,s.value))}});if(requestedProtocol)history.replaceState(null,'','/transfer');
const sendSelect=document.querySelector('[data-protocol="send"]'),sendHelp=document.getElementById('send-protocol-help');function sendProtocolHelp(){{const palm=sendSelect.value==='palm';sendHelp.hidden=!palm;sendHelp.textContent=palm?'{tr(language,"Palm gevonden maar ‘unable to connect’? Leg de poorten recht tegenover elkaar op ongeveer 10–30 cm afstand; te dichtbij kan eveneens mislukken. Controleer ook Beam Receive. Blijft het daarna mislukken, voer dan een soft reset van de Palm uit; daarbij blijven je gegevens behouden.","Palm discovered but ‘unable to connect’? Align the ports directly opposite each other at roughly 10–30 cm; placing them too close can also fail. Check Beam Receive as well. If it still fails, perform a soft reset of the Palm; your data is preserved.")}':''}}sendSelect.addEventListener('change',sendProtocolHelp);sendProtocolHelp();
const receiveSelect=document.querySelector('[data-protocol="receive"]'),filenameBox=document.getElementById('receive-filename');function filenameVisibility(){{filenameBox.hidden=!['xmodem','ascii'].includes(receiveSelect.value)}}receiveSelect.addEventListener('change',filenameVisibility);filenameVisibility();
function renderStatus(s){{
const running=s.state==='running',elapsed=s.started?Math.max(0,Math.floor(Date.now()/1000-s.started)):0,bar=document.querySelector('#progress span');
const hasProgress=typeof s.progress==='number'&&Number.isFinite(s.progress),hasSpeed=typeof s.speed_kbytes_sec==='number'&&Number.isFinite(s.speed_kbytes_sec);
const percent=hasProgress?Math.max(0,Math.min(running?99.9:100,s.progress)):null;
let meta=(s.protocol?s.protocol.toUpperCase()+' · ':'')+(running?elapsed+' seconden actief':s.state==='complete'?'Voltooid':s.state==='error'?'Mislukt':s.state==='cancelled'?'Gestopt':'Gereed');
if(hasProgress)meta+=' · '+percent.toFixed(percent>99&&percent<100?1:0)+'%';
if(typeof s.bytes_total==='number')meta+=' · '+(s.bytes_transferred/1000).toFixed(1)+' / '+(s.bytes_total/1000).toFixed(1)+' kB';
if(hasSpeed)meta+=' · '+s.speed_kbytes_sec.toFixed(2)+' kB/s';
if(running&&s.phase==='finalizing')meta+=' · {tr(language,"Bevestiging afwachten","Waiting for confirmation")}';
document.getElementById('status-title').textContent=s.message||'—';document.getElementById('status-meta').textContent=meta;
document.getElementById('status-icon').textContent=running?'↔':s.state==='complete'?'✓':s.state==='error'?'!':'●';
const progress=document.getElementById('progress');progress.hidden=!running&&!hasProgress;progress.classList.toggle('running',running&&!hasProgress);
progress.setAttribute('role','progressbar');progress.setAttribute('aria-label','{tr(language,"Bestandsoverdracht","File transfer")}');progress.setAttribute('aria-valuemin','0');progress.setAttribute('aria-valuemax','100');
if(hasProgress)progress.setAttribute('aria-valuenow',String(percent));else progress.removeAttribute('aria-valuenow');
bar.style.width=hasProgress?percent+'%':'';bar.style.transform=hasProgress?'none':'';
document.getElementById('cancel-form').hidden=!running;const details=document.getElementById('technical'),output=document.getElementById('technical-output');output.textContent=s.output||'';details.hidden=!s.output;
if(running&&s.direction&&s.protocol){{const select=document.querySelector('[data-protocol="'+s.direction+'"]');if(select&&select.querySelector('option[value="'+CSS.escape(s.protocol)+'"]'))select.value=s.protocol}}
}}
function renderReceived(files){{if(!Array.isArray(files))return;const list=document.getElementById('received-list');list.replaceChildren();if(!files.length){{const empty=document.createElement('li');empty.textContent='—';list.append(empty);return}}files.forEach(file=>{{const row=document.createElement('li'),info=document.createElement('div'),name=document.createElement('strong'),meta=document.createElement('small'),actions=document.createElement('div'),download=document.createElement('a'),form=document.createElement('form'),csrf=document.createElement('input'),filename=document.createElement('input'),remove=document.createElement('button');name.textContent=file.name;meta.className='helper';meta.textContent=file.size+' · '+file.date;info.append(name,meta);actions.className='file-actions';download.className='button secondary';download.href=file.url;download.textContent='{tr(language,"Downloaden","Download")}';form.method='post';form.action='/transfer/delete';csrf.type='hidden';csrf.name='csrf';csrf.value='{{{{csrf}}}}';filename.type='hidden';filename.name='name';filename.value=file.name;remove.className='danger';remove.type='submit';remove.textContent='{tr(language,"Verwijderen","Delete")}';form.append(csrf,filename,remove);actions.append(download,form);row.append(info,actions);list.append(row)}})}}
const sendForm=sendSelect.form,fileInput=sendForm.querySelector('input[type=file]'),sendButton=sendForm.querySelector('button[type=submit]'),retryInput=document.createElement('input'),picker=document.createElement('div'),chooseButton=document.createElement('button'),selectedName=document.createElement('span');retryInput.type='hidden';retryInput.name='retry_token';sendForm.append(retryInput);picker.className='file-picker';picker.style.cssText='display:flex;align-items:center;gap:12px;flex-wrap:wrap;border:1px solid var(--line);border-radius:8px;padding:12px';chooseButton.type='button';chooseButton.className='secondary';chooseButton.style.margin='0';selectedName.style.overflowWrap='anywhere';selectedName.setAttribute('aria-live','polite');picker.append(chooseButton,selectedName);fileInput.after(picker);fileInput.hidden=true;fileInput.required=false;let pendingInitialized=false,pendingFile=null;
function addReceivedSendActions(){{document.querySelectorAll('#received-list .file-actions').forEach(actions=>{{if(actions.querySelector('[data-send-received]'))return;const form=actions.querySelector('form').cloneNode(true);form.action='/transfer/select-received';form.dataset.sendReceived='true';const button=form.querySelector('button');button.className='secondary';button.textContent='{tr(language,"Verzenden","Send")}';actions.prepend(form)}})}}
function renderFilePicker(){{const name=fileInput.files.length?fileInput.files[0].name:pendingFile?pendingFile.filename:'';const text=name||'{tr(language,"Geen bestand geselecteerd","No file selected")}';if(selectedName.textContent!==text)selectedName.textContent=text;chooseButton.textContent=name?'{tr(language,"Verwijderen","Remove")}':'{tr(language,"Kies bestand","Choose file")}';addReceivedSendActions()}}
function renderPending(s){{const item=s.pending_send;pendingFile=item;retryInput.value=item?item.token:'';if(item&&!pendingInitialized&&!requestedProtocol&&!fileInput.files.length){{sendSelect.value=item.protocol;sendProtocolHelp()}}pendingInitialized=true;renderFilePicker();sendButton.textContent='{tr(language,"Verzenden","Send")}';sendButton.disabled=s.state==='running'}}
chooseButton.addEventListener('click',async()=>{{if(!fileInput.files.length&&!pendingFile){{fileInput.click();return}}chooseButton.disabled=true;try{{if(pendingFile){{const data=new URLSearchParams({{csrf:sendForm.querySelector('[name=csrf]').value,retry_token:retryInput.value}});const response=await fetch('/transfer/clear-selection',{{method:'POST',body:data}});if(!response.ok)throw new Error('{tr(language,"Selectie verwijderen mislukt. Mogelijk is er nog een overdracht actief.","Could not remove selection. A transfer may still be active.")}')}}fileInput.value='';pendingFile=null;retryInput.value='';renderFilePicker()}}catch(error){{alert(error.message)}}finally{{chooseButton.disabled=false}}}});fileInput.addEventListener('change',renderFilePicker);sendForm.addEventListener('submit',event=>{{if(!fileInput.files.length&&!retryInput.value){{event.preventDefault();fileInput.click()}}}});
async function pollStatus(){{try{{const response=await fetch('/transfer/status',{{cache:'no-store'}});if(response.ok){{const status=await response.json();renderStatus(status);renderReceived(status.received);renderPending(status)}}}}catch(error){{}}}}renderStatus({status_json});renderPending({status_json});setInterval(pollStatus,1000);
</script>"""
            self.send_page(tr(language, "Bestandsoverdracht", "File transfer"), body, config)
        elif path == "/settings":
            body = f"""<div class="page-heading"><h1>{tr(language,'Instellingen','Settings')}</h1><p>{tr(language,'Beheer taal, noodnetwerk, hardware en de softwarebibliotheek.','Manage language, fallback network, hardware and the software library.')}</p></div><section class="card"><h2>{tr(language,'Algemene instellingen','General settings')}</h2>
<form method="post" action="/settings"><input type="hidden" name="csrf" value="{{{{csrf}}}}">
<label>{tr(language,'Taal','Language')}</label><select name="language"><option value="nl" {'selected' if language == 'nl' else ''}>Nederlands</option><option value="en" {'selected' if language == 'en' else ''}>English</option></select>
<div class="form-section"><h3>{tr(language,'Nood-accesspoint','Fallback access point')}</h3><p>{tr(language,'Dit netwerk verschijnt alleen wanneer RetroModem geen bekend wifi-netwerk kan gebruiken.','This network appears only when RetroModem cannot use a known Wi-Fi network.')}</p>
<label>{tr(language,'Accesspointnaam (SSID)','Access point name (SSID)')}</label><input name="ap_ssid" maxlength="32" value="{html.escape(config.get('RETROMODEM_AP_SSID','retromodem'), quote=True)}" required>
<label>{tr(language,'Accesspoint-wachtwoord','Access point password')}</label><input id="ap-password" name="ap_password" type="password" minlength="8" maxlength="63" value="{html.escape(config.get('RETROMODEM_AP_PASSWORD','12345678'), quote=True)}" required>
<label><input id="show-ap-password" type="checkbox" style="width:auto;min-height:auto"> {tr(language,'Wachtwoord tonen','Show password')}</label></div>
<button class="primary" type="submit">{tr(language,'Wijzigingen opslaan','Save changes')}</button></form></section>
<details class="card hardware"><summary>{tr(language,'Hardware en leds','Hardware and LEDs')}</summary><p>{tr(language,'De knop zit tussen GPIO16 en massa. Kort drukken wisselt de modemmodus; drie seconden vasthouden schakelt de Pi veilig uit. Laat los wanneer beide leds knipperen en wacht tot ze uit zijn voordat je de voeding losneemt.','The button connects GPIO16 to ground. A short press switches modem mode; holding it for three seconds safely shuts down the Pi. Release when both LEDs flash and wait until they are off before removing power.')}</p><dl><dt>GPIO16</dt><dd>{tr(language,'Knop, interne pull-up','Button, internal pull-up')}</dd><dt>GPIO23</dt><dd>{tr(language,'Inbelmodem-led','Dial-up modem LED')}</dd><dt>GPIO24</dt><dd>PPP-led</dd></dl></details>
{chatgpt_settings_card(language, config)}
{proxy_settings_card(language, config)}
{library_upload_form(language)}
<script>const showPassword=document.getElementById('show-ap-password'),password=document.getElementById('ap-password');showPassword.addEventListener('change',()=>password.type=showPassword.checked?'text':'password');</script>"""
            self.send_page(tr(language, "Instellingen", "Settings"), body, config)
        elif path == "/guides":
            self.send_page(tr(language, "Handleidingen", "Guides"), guides_page(language), config)
        elif path == "/guides-legacy":
            self.redirect("/guides")
        elif False:  # Kept temporarily for source-history comparison; never served.
            body = f"""<section class="card"><h2>{tr(language,'Kies je apparaat','Choose your device')}</h2><div class="guide-tabs">
<button type="button" data-guide="generic">{tr(language,'Algemeen','Generic')}</button><button type="button" data-guide="psion">Psion 5mx</button><button type="button" data-guide="palm-old">Palm OS 3.0/3.1</button><button type="button" data-guide="palm-new">Palm OS 3.3–5.x</button><button type="button" data-guide="hp200lx">HP 200LX</button>
</div></section>
<div class="notice"><strong>{tr(language,'Dubbele tekens in een terminal?','Duplicate characters in a terminal?')}</strong> {tr(language,'Dan echoën waarschijnlijk zowel het apparaat als de BBS iedere toetsaanslag. Zet <em>Local echo/Lokale echo</em> in het terminalprogramma uit. Laat remote echo aan, zodat de BBS de tekst eenmaal terugstuurt.','Both the device and the BBS are probably echoing every keystroke. Disable <em>Local echo</em> in the terminal program. Keep remote echo enabled so the BBS returns the text once.')}</div>
<section class="card guide-panel" id="generic" hidden><h2>{tr(language,'Generieke IrDA/PPP-handleiding','Generic IrDA/PPP guide')}</h2>
<p>{tr(language,'Gebruik deze stappen voor apparaten met een echte IrDA-poort en ondersteuning voor een infraroodmodem of directe PPP-verbinding. Menu’s verschillen per apparaat.','Use these steps for devices with a true IrDA port and support for an infrared modem or direct PPP connection. Menu names vary by device.')}</p>
<ol class="steps">
<li>{tr(language,'Zet synchronisatie-, HotSync- of Remote Link-functies die de IR-poort gebruiken tijdelijk uit.','Temporarily disable synchronization, HotSync or Remote Link features that use the IR port.')}</li>
<li>{tr(language,'Maak een verbinding via <strong>Infrared/IrCOMM</strong>. Kies bij voorkeur <strong>Direct</strong> of <strong>PC</strong>; vraagt het apparaat expliciet om een modem, kies dan een generiek of mobiel infraroodmodem.','Create an <strong>Infrared/IrCOMM</strong> connection. Prefer <strong>Direct</strong> or <strong>PC</strong>; if the device explicitly requires a modem, choose a generic or mobile infrared modem.')}</li>
<li>{tr(language,'Stel de snelheid in op <strong>9600 bit/s</strong>. Gebruik hardware- of automatische flow control als dat verplicht is.','Set the speed to <strong>9600 bit/s</strong>. Use hardware or automatic flow control if the device requires a choice.')}</li>
<li>{tr(language,'Maak een PPP-netwerkdienst: gebruikersnaam <code>user</code>, leeg wachtwoord, IP-adres automatisch, DNS automatisch en geen inbelnummer of aanmeldscript.','Create a PPP network service: username <code>user</code>, blank password, automatic IP address, automatic DNS, and no dial number or login script.')}</li>
<li>{tr(language,'Richt beide IR-poorten recht op elkaar, begin op 10–30 cm afstand en open een gewone HTTP-site zoals <code>http://retroweb.bjrno.com</code>.','Point both IR ports directly at each other, start at 10–30 cm, and open a plain HTTP site such as <code>http://retroweb.bjrno.com</code>.')}</li>
</ol><p>{tr(language,'Niet ieder apparaat met een rood venstertje spreekt IrDA/IrCOMM. Oudere apparaten kunnen alleen raw HPSIR of een eigen protocol gebruiken.','Not every device with a red window supports IrDA/IrCOMM. Older devices may only support raw HPSIR or a proprietary protocol.')}</p></section>
<section class="card guide-panel" id="psion"><h2>Psion Series 5mx — {tr(language,'internet via infrarood','internet over infrared')}</h2>
<ol class="steps">
<li><strong>{tr(language,'Zet Remote Link uit','Disable Remote Link')}</strong><br>{tr(language,'Open <em>Instellingen</em>, druk op de menuknop linksboven op de rand, kies <em>Extra → Remote Link</em> en zet deze op <em>Uit</em>. Anders kan Remote Link de communicatiepoort bezet houden.','Open <em>System</em>, press the menu button at the upper-left edge, choose <em>Tools → Remote Link</em> and set it to <em>Off</em>. Otherwise Remote Link may keep the communications port occupied.')}</li>
<li><strong>{tr(language,'Open Bellen minstens één keer','Open Dialling at least once')}</strong><br>{tr(language,'Open rechts in Instellingen het <em>Configuratiescherm</em> en daarna <em>Bellen</em> (op een Engelstalige Psion: <em>Dialling</em>). Selecteer of bevestig de huidige instelling en sluit met <em>OK</em>. Ook wanneer de standaardwaarden al goed staan, moet dit venster één keer geopend en bevestigd zijn. Anders meldt Opera: “Controleer of gegevens over locatie en modems zijn ingesteld”.','Open the <em>Control panel</em> at the right side of System and then <em>Dialling</em>. Select or confirm the current setting and close with <em>OK</em>. Even when the defaults look correct, open and confirm this dialog once. Otherwise Opera reports that the location and modem information must be configured.')}</li>
<li><strong>{tr(language,'Maak een infraroodmodem','Create an infrared modem')}</strong><br>{tr(language,'Open <em>Modems</em>, maak een nieuw modem en geef het bijvoorbeeld de naam <em>retromodem</em>.','Open <em>Modems</em>, create a new modem and name it <em>retromodem</em>.')}
<ul class="compact"><li>{tr(language,'Modem: <strong>Infrarode mobiele telefoon</strong>','Modem: <strong>Infrared mobile phone</strong>')}</li><li>{tr(language,'Snelheid: <strong>9600</strong>','Speed: <strong>9600</strong>')}</li><li>{tr(language,'Initialisatie: <code>AT</code>','Initialization: <code>AT</code>')}</li><li>{tr(language,'Geavanceerd: hardware RTS/CTS; vaste lijn','Advanced: hardware RTS/CTS; fixed line')}</li></ul></li>
<li><strong>{tr(language,'Maak een internetdienst','Create an internet service')}</strong><br>{tr(language,'Open <em>Internet</em> of <em>Netwerk</em>, maak een nieuwe dienst en kies het modem <em>retromodem</em>.','Open <em>Internet</em> or <em>Network</em>, create a new service and select the <em>retromodem</em> modem.')}
<ul class="compact"><li>{tr(language,'Dienst: <strong>Direct</strong>','Service: <strong>Direct</strong>')}</li><li>{tr(language,'Handmatig aanmelden: uit','Manual login: off')}</li><li>{tr(language,'Gebruikersnaam: <code>user</code>; wachtwoord leeg','Username: <code>user</code>; password blank')}</li><li>{tr(language,'IP-adres: ophalen van server','IP address: obtain from server')}</li><li>{tr(language,'DNS-adressen: ophalen van server','DNS addresses: obtain from server')}</li><li>{tr(language,'Geavanceerd: alleen platte tekst accepteren','Advanced: only accept plain text')}</li></ul></li>
<li><strong>{tr(language,'Leg de apparaten tegenover elkaar','Align the devices')}</strong><br>{tr(language,'Richt de IR-poort aan de linkerzijkant van de Psion op de infraroodadapter. Begin op ongeveer 10–30 cm afstand en zorg dat er niets tussen zit.','Point the IR port on the left side of the Psion toward the infrared adapter. Start at roughly 10–30 cm with a clear line of sight.')}</li>
<li><strong>{tr(language,'Maak verbinding','Connect')}</strong><br>{tr(language,'Open Opera of Web en bezoek eerst een gewone HTTP-site, bijvoorbeeld <code>http://retroweb.bjrno.com</code>. Kies de zojuist gemaakte internetdienst wanneer daarom wordt gevraagd. Het lampje op de dongle hoort tijdens verkeer te knipperen.','Open Opera or Web and first visit a plain HTTP site such as <code>http://retroweb.bjrno.com</code>. Select the internet service you just created when prompted. The dongle LED should blink while traffic is flowing.')}</li>
</ol><h3>{tr(language,'Inbelinternet via 5559000','Dial-up internet through 5559000')}</h3><p>{tr(language,'Kies in RetroModem <strong>Hayes-dial-up / BBS</strong>. Maak op de Psion een inbelinternetdienst met het infraroodmodem en nummer <code>5559000</code>. De fysieke MA-620-link blijft 9600 bit/s; de nagebootste Comms/modempoort gebruikt standaard 115200.','Select <strong>Hayes dial-up / BBS</strong> in RetroModem. Create a Psion dial-up internet service using the infrared modem and number <code>5559000</code>. The physical MA-620 link remains 9600 bps; the emulated Comms/modem port defaults to 115200.')}</p>
<h3>{tr(language,'BBS bellen met Comms','Dial a BBS with Comms')}</h3><ol class="steps"><li>{tr(language,'Open Comms met infrarood en de ingestelde virtuele poortsnelheid (standaard 115200 baud). Remote Link moet uit staan.','Open Comms using infrared and the configured virtual port speed (default 115200 baud). Remote Link must be disabled.')}</li><li>{tr(language,'Ga naar <strong>Extra → Vertaalcodes</strong> en zet <strong>Lokale echo</strong> uit. Anders verschijnen tekens dubbel zodra de BBS ze terugstuurt.','Open <strong>Tools → Translation codes</strong> and disable <strong>Local echo</strong>. Otherwise characters appear twice when the BBS echoes them.')}</li><li>{tr(language,'Geef na openen zo nodig eerst <code>AT</code> plus Enter en bel daarna bijvoorbeeld <code>ATDT5551008</code>.','After opening, enter <code>AT</code> plus Enter if needed, then dial for example <code>ATDT5551008</code>.')}</li></ol></section>
<section class="card"><h2>{tr(language,'Problemen oplossen','Troubleshooting')}</h2><ul>
<li>{tr(language,'Opera vraagt om locatie- of modemgegevens: voer stap 2 uit en controleer of de internetdienst het juiste modem gebruikt.','Opera asks for location or modem data: perform step 2 and check that the internet service uses the correct modem.')}</li>
<li>{tr(language,'De dongle knippert kort en stopt: controleer Remote Link, 9600 bit/s en de IR-uitlijning.','The dongle flashes briefly and stops: check Remote Link, 9600 bit/s and IR alignment.')}</li>
<li>{tr(language,'“Looking up host name” blijft staan: de IR-link is waarschijnlijk wel actief; controleer of de Pi wifi en internet heeft en probeer de HTTP-testsite.','“Looking up host name” remains on screen: the IR link is probably active; check the Pi Wi-Fi/internet connection and try the HTTP test site.')}</li>
</ul></section>
<section class="card guide-panel" id="palm-old" hidden><h2>Palm OS 3.0/3.1</h2>
<p>{tr(language,'Deze oudere versies hebben nog geen apart scherm <em>Connection</em>. Alleen Palms met een ingebouwde IR-poort kunnen deze route gebruiken.','These older versions do not yet have a separate <em>Connection</em> panel. This route only works on Palms with a built-in IR port.')}</p>
<ol class="steps">
<li>{tr(language,'Open <em>Prefs → Serial/IR</em> en kies <strong>Infrared</strong>.','Open <em>Prefs → Serial/IR</em> and select <strong>Infrared</strong>.')}</li>
<li>{tr(language,'Open <em>Prefs → Modem</em>. Kies 9600 bit/s, automatische flow control en een directe/generieke modemconfiguratie zonder telefoonnummer.','Open <em>Prefs → Modem</em>. Select 9600 bit/s, automatic flow control and a direct/generic modem configuration without a phone number.')}</li>
<li>{tr(language,'Open <em>Prefs → Network</em>, maak een service met gebruikersnaam <code>user</code> en laat het wachtwoord leeg.','Open <em>Prefs → Network</em>, create a service with username <code>user</code> and leave the password blank.')}</li>
<li>{tr(language,'Tik <em>Details</em>: Connection type <strong>PPP</strong>, Query DNS aan en IP Address Automatic aan. Open <em>Script</em> en laat alleen <strong>End</strong> staan.','Tap <em>Details</em>: set Connection type to <strong>PPP</strong>, enable Query DNS and Automatic IP Address. Open <em>Script</em> and leave only <strong>End</strong>.')}</li>
<li>{tr(language,'Richt de IR-poorten op elkaar en tik in Network op <em>Connect</em>.','Align the IR ports and tap <em>Connect</em> in Network.')}</li>
</ol></section>
<section class="card guide-panel" id="palm-new" hidden><h2>Palm OS 3.3–5.x</h2>
<p>{tr(language,'De benamingen kunnen per Palm-, Handspring- of Sony-model iets afwijken. Op sommige Palm OS 5-apparaten ontbreekt de optie Infrared.','Names may differ slightly between Palm, Handspring and Sony models. Some Palm OS 5 devices do not offer an Infrared option.')}</p>
<ol class="steps">
<li>{tr(language,'Open <em>Prefs → Connection</em>, tik <em>New</em> en noem de verbinding <em>RetroModem</em>.','Open <em>Prefs → Connection</em>, tap <em>New</em> and name the connection <em>RetroModem</em>.')}</li>
<li>{tr(language,'Kies <strong>Connect to: PC</strong> en <strong>Via: Infrared</strong>. Dit is een directe PPP-verbinding; kies niet Modem als PC beschikbaar is.','Choose <strong>Connect to: PC</strong> and <strong>Via: Infrared</strong>. This is a direct PPP connection; do not choose Modem when PC is available.')}</li>
<li>{tr(language,'Tik <em>Details</em>: Speed <strong>9,600 bps</strong> en Flow Ctl <strong>Automatic</strong>.','Tap <em>Details</em>: set Speed to <strong>9,600 bps</strong> and Flow Ctl to <strong>Automatic</strong>.')}</li>
<li>{tr(language,'Open <em>Prefs → Network</em>. Maak of kopieer een service; Username <code>user</code>, Password leeg en Connection <strong>RetroModem</strong>.','Open <em>Prefs → Network</em>. Create or duplicate a service; Username <code>user</code>, blank Password, and Connection <strong>RetroModem</strong>.')}</li>
<li>{tr(language,'Onder <em>Details</em>: Connection type <strong>PPP</strong>, Idle timeout <strong>Never</strong>, Query DNS aan en IP Address Automatic aan. Onder <em>Script</em> verwijder je alle regels behalve <strong>End</strong>.','Under <em>Details</em>: Connection type <strong>PPP</strong>, Idle timeout <strong>Never</strong>, Query DNS enabled and Automatic IP Address enabled. Under <em>Script</em>, remove every line except <strong>End</strong>.')}</li>
<li>{tr(language,'Richt de poorten op elkaar en tik <em>Connect</em>. “Established” betekent dat PPP actief is.','Align the ports and tap <em>Connect</em>. “Established” means PPP is active.')}</li>
</ol><p><strong>{tr(language,'Palm OS 5-opmerking:','Palm OS 5 note:')}</strong> {tr(language,'internettoegang werkt via de ingebouwde Network Preferences; de beschikbare browser verschilt per fabrikant. Gebruik voor de eerste test een HTTP-adres.','internet access uses the built-in Network Preferences; the available browser differs by manufacturer. Use an HTTP address for the first test.')}</p></section>
<section class="card guide-panel" id="hp200lx" hidden><h2>HP 200LX</h2>
<div class="notice warning"><strong>{tr(language,'Nog niet ondersteund door de huidige RetroModem-driver.','Not yet supported by the current RetroModem driver.')}</strong></div>
<p>{tr(language,'De HP 200LX heeft wel een infraroodpoort, maar die spreekt alleen de fysieke <strong>HPSIR/raw SIR</strong>-laag. De HP implementeert niet de hogere IrLAP/IrLMP/IrCOMM-lagen waarmee de Psion, Palm en onze huidige Linux-driver verbinding maken. Daarom zal de 200LX de MA-620 momenteel niet als IR-modem ontdekken.','The HP 200LX does have an infrared port, but it only implements the physical <strong>HPSIR/raw SIR</strong> layer. It does not implement the higher IrLAP/IrLMP/IrCOMM layers used by the Psion, Palm and our current Linux driver. Consequently, the 200LX cannot currently discover the MA-620 as an IR modem.')}</p>
<p>{tr(language,'Voor ondersteuning moeten we later een aparte raw-SIR-modus bouwen die de MA-620 buiten de Linux IrDA-stack rechtstreeks als seriële optische verbinding gebruikt. Aan HP-zijde is dan DOS-PPP-software nodig die COM2/Infrared gebruikt. Dit wordt een afzonderlijk hardwareprofiel en kan niet tegelijk met de huidige IrCOMM-modus draaien.','Supporting it will require a separate raw-SIR mode that uses the MA-620 directly as an optical serial connection, outside the Linux IrDA stack. The HP will also need DOS PPP software configured for COM2/Infrared. This will be a separate hardware profile and cannot run at the same time as the current IrCOMM mode.')}</p>
<p>{tr(language,'Wat nu al wel kan: LapLink Remote Access via infrarood met een andere HP 100/200LX of een computer met compatibele raw-HPSIR-ondersteuning; dat is bestandsoverdracht, geen verbinding met deze internetbridge.','What already works: LapLink Remote Access over infrared with another HP 100/200LX or a computer offering compatible raw-HPSIR support; that provides file transfer, not a connection to this internet bridge.')}</p></section>
<section class="card"><h2>{tr(language,'Meer handleidingen volgen','More guides are coming')}</h2><p>Windows XP · OBEX file transfer</p></section>
<script>const guideButtons=document.querySelectorAll('[data-guide]');const guidePanels=document.querySelectorAll('.guide-panel');function showGuide(id){{guidePanels.forEach(panel=>panel.hidden=panel.id!==id);guideButtons.forEach(button=>button.classList.toggle('active',button.dataset.guide===id));location.hash=id}}guideButtons.forEach(button=>button.addEventListener('click',()=>showGuide(button.dataset.guide)));showGuide(location.hash.slice(1)||'psion');</script>"""
            self.send_page(tr(language, "Handleidingen", "Guides"), body, config)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        config = self.config()
        if getattr(self, 'headers', {}).get('Host', '').split(':', 1)[0].lower().rstrip('.') == 'wifi.retromodem':
            self.serve_retro_wifi()
            return
        if getattr(self, 'headers', {}).get('Host', '').split(':', 1)[0].lower().rstrip('.') == 'chatgpt.retromodem':
            try:
                import chatgpt_web
            except ModuleNotFoundError:
                from web import chatgpt_web
            chatgpt_web.serve(self)
            return
        if not self.require_auth(config):
            return
        language = config.get("RETROMODEM_LANGUAGE", "nl")
        path = urllib.parse.urlsplit(self.path).path
        if path in {"/transfer/start", "/guides/upload"}:
            try:
                form, upload_name, upload = self.multipart()
            except (ValueError, TypeError) as error:
                self.send_error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, str(error))
                return
        else:
            form = self.form()
            upload_name, upload = "", b""
        if not self.valid_csrf(form):
            self.send_error(HTTPStatus.FORBIDDEN, "Ongeldig formulier; laad de pagina opnieuw.")
            return
        if path == "/transfer/clear-selection":
            try:
                current = json.loads((TRANSFERS / "status.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                current = {}
            if current.get("state") == "running" and transfer_process_alive(current):
                self.send_error(HTTPStatus.CONFLICT, "Er is nog een bestandsoverdracht actief")
                return
            selected = pending_send()
            if selected:
                if form.get("retry_token") != selected["token"]:
                    self.send_error(HTTPStatus.CONFLICT, "De selectie is gewijzigd; laad de pagina opnieuw")
                    return
                asset = TRANSFERS / selected["token"] / selected["filename"]
                asset.unlink(missing_ok=True)
                try:
                    asset.parent.rmdir()
                except OSError:
                    pass
            (TRANSFERS / "pending-send.json").unlink(missing_ok=True)
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
        elif path == "/transfer/select-received":
            name = form.get("name", "")
            source = RECEIVED / name
            if not name or Path(name).name != name or source.is_symlink() or not source.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Bestand niet gevonden")
                return
            work_dir = TRANSFERS / f"work-{secrets.token_hex(6)}"
            work_dir.mkdir(mode=0o700)
            selected = work_dir / name
            selected.write_bytes(source.read_bytes())
            remember_send(selected, "ymodem")
            self.redirect("/transfer")
        elif path == "/transfer/delete":
            name = Path(form.get("name", "")).name
            asset = RECEIVED / name
            if not name or not asset.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Bestand niet gevonden")
                return
            asset.unlink()
            self.redirect("/transfer#received-files")
        elif path == "/transfer/cancel":
            try:
                status = json.loads((TRANSFERS / "status.json").read_text(encoding="utf-8"))
                pid = int(status.get("pid", 0))
                if status.get("state") == "running" and transfer_process_alive(status):
                    os.kill(pid, signal.SIGTERM)
            except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError, json.JSONDecodeError):
                status = {}
            status.update({"state": "cancelled", "message": "Overdracht gestopt",
                           "finished": int(time.time()), "phase": "finished"})
            save_transfer_status(status)
            subprocess.Popen(["/usr/local/lib/retromodem/apply-mode"], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
            self.redirect("/transfer")
        elif path == "/guides/upload":
            target = form.get("target", "")
            protocol = form.get("protocol", "")
            title = form.get("title", "").strip()[:80]
            description = form.get("description", "").strip()[:240]
            compatibility = form.get("compatibility", "").strip()[:120]
            if target not in GUIDE_TARGETS or protocol not in LIBRARY_PROTOCOLS:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige handleiding of overdrachtsmethode")
                return
            if not upload_name or not upload or not title or not description:
                self.send_error(HTTPStatus.BAD_REQUEST, "Bestand, titel en uitleg zijn verplicht")
                return
            original_name = re.sub(r"[^A-Za-z0-9._ -]", "_", Path(upload_name).name)[:120] or "bestand.bin"
            software_id = secrets.token_hex(8)
            stored_name = f"{software_id}-{re.sub(r'[^A-Za-z0-9._-]', '_', original_name)}"
            LIBRARY_ROOT.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix="upload.", dir=LIBRARY_ROOT)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(upload)
                os.chmod(temporary, 0o644)
                os.replace(temporary, LIBRARY_ROOT / stored_name)
            finally:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
            items = load_library()
            items[software_id] = {
                "title": title, "description": description, "compatibility": compatibility,
                "target": target, "protocol": protocol, "original_name": original_name,
                "stored_name": stored_name,
            }
            save_library(items)
            self.redirect(f"/guides#{target}")
        elif path == "/guides/library-delete":
            software_id = form.get("software", "")
            items = load_library()
            item = items.pop(software_id, None)
            if item is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Bestand niet gevonden")
                return
            target = str(item.get("target", "generic"))
            stored_name = Path(str(item.get("stored_name", ""))).name
            if stored_name:
                try:
                    (LIBRARY_ROOT / stored_name).unlink()
                except FileNotFoundError:
                    pass
            save_library(items)
            self.redirect(f"/guides#{target}")
        elif path == "/transfer/library-send":
            software_id = form.get("software", "")
            item = software_catalog().get(software_id)
            if item is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Software niet gevonden")
                return
            source = ((LIBRARY_ROOT / Path(str(item.get("stored_name", ""))).name)
                      if item.get("uploaded") else STATIC_ROOT / str(item["file"]))
            if not source.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Softwarebestand ontbreekt")
                return
            TRANSFERS.mkdir(parents=True, exist_ok=True)
            try:
                current = json.loads((TRANSFERS / "status.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                current = {}
            if current.get("state") == "running" and transfer_process_alive(current):
                self.send_error(HTTPStatus.CONFLICT, "Er is al een bestandsoverdracht actief")
                return
            work_dir = TRANSFERS / f"work-{secrets.token_hex(6)}"
            work_dir.mkdir(mode=0o700)
            transfer_path = work_dir / library_filename(item, source)
            transfer_path.write_bytes(source.read_bytes())
            remember_send(transfer_path, str(item["protocol"]))
            process = subprocess.Popen(
                ["/usr/local/lib/retromodem/transfer.py", "send", str(item["protocol"]), str(transfer_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True,
            )
            threading.Thread(target=process.wait, daemon=True).start()
            protocol = urllib.parse.quote(str(item["protocol"]), safe="")
            self.redirect(f"/transfer?protocol={protocol}")
        elif path == "/transfer/start":
            direction = form.get("direction", "")
            protocol = form.get("protocol", "")
            if direction not in {"send", "receive"} or protocol not in {"ascii", "xmodem", "ymodem", "zmodem", "epoc", "palm", "windows"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige overdracht")
                return
            TRANSFERS.mkdir(parents=True, exist_ok=True)
            try:
                current = json.loads((TRANSFERS / "status.json").read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                current = {}
            if current.get("state") == "running":
                self.send_error(HTTPStatus.CONFLICT, "Er is al een bestandsoverdracht actief")
                return
            if direction == "send":
                selected = pending_send()
                if upload_name and upload:
                    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", upload_name)[:120] or "upload.bin"
                    work_dir = TRANSFERS / f"work-{secrets.token_hex(6)}"
                    work_dir.mkdir(mode=0o700)
                    transfer_path = work_dir / safe_name
                    transfer_path.write_bytes(upload)
                elif selected and form.get("retry_token") == selected["token"]:
                    transfer_path = TRANSFERS / selected["token"] / selected["filename"]
                else:
                    self.send_error(HTTPStatus.BAD_REQUEST, "Geen bestand geselecteerd; kies het bestand opnieuw")
                    return
                remember_send(transfer_path, protocol)
            else:
                safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", form.get("filename", "received-file.bin"))[:120] or "received-file.bin"
                transfer_path = TRANSFERS / safe_name
            process = subprocess.Popen(
                ["/usr/local/lib/retromodem/transfer.py", direction, protocol, str(transfer_path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            threading.Thread(target=process.wait, daemon=True).start()
            self.redirect("/transfer")
        elif path == "/modem/settings":
            transport = form.get("transport", "")
            line_mode = form.get("line_mode", "")
            adapter_id = form.get("irda_adapter", ir_adapter_id(config))
            if adapter_id not in IR_ADAPTERS:
                self.send_error(HTTPStatus.BAD_REQUEST, "Onbekende infraroodadapter")
                return
            profile = IR_ADAPTERS[adapter_id]
            adapter_changes = {}
            for key, item in IR_ADAPTERS.items():
                prefix = item["prefix"]
                current = key == ir_adapter_id(config)
                for suffix, active_key, fallback in (("BITRATE", "RETROMODEM_IRDA_BITRATE", "9600"), ("DIALUP_BITRATE", "RETROMODEM_IRDA_DIALUP_BITRATE", "115200")):
                    field = f"{prefix.lower()}_{suffix.lower()}"
                    value = form.get(field, config.get(f"RETROMODEM_{prefix}_{suffix}", config.get(active_key, fallback) if current else fallback))
                    if value not in ALLOWED_BITRATES or (key == "ming-yuan-my018" and suffix == "BITRATE" and value != "9600" and not my018_power_enabled(config)):
                        self.send_error(HTTPStatus.BAD_REQUEST, "Deze linksnelheid is nog niet beschikbaar voor deze adapter")
                        return
                    adapter_changes[f"RETROMODEM_{prefix}_{suffix}"] = value
            irda_bitrate = adapter_changes[f'RETROMODEM_{profile["prefix"]}_BITRATE']
            irda_dialup_bitrate = adapter_changes[f'RETROMODEM_{profile["prefix"]}_DIALUP_BITRATE']
            serial_bitrate = form.get("serial_bitrate", "")
            serial_dialup_bitrate = form.get("serial_dialup_bitrate", "")
            dialup_rates = ALLOWED_BITRATES | {"300", "1200", "2400", "4800"}
            if transport not in {"irda", "serial"} or line_mode not in {"ppp", "dialup"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige modemmodus")
                return
            if irda_bitrate not in ALLOWED_BITRATES or irda_dialup_bitrate not in ALLOWED_BITRATES or serial_bitrate not in ALLOWED_BITRATES or serial_dialup_bitrate not in dialup_rates:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige modemsnelheid")
                return
            save_config({
                **adapter_changes,
                "RETROMODEM_ADAPTER": adapter_id,
                "RETROMODEM_TTY": profile["tty"],
                "RETROMODEM_DONGLE": profile["dongle"],
                "RETROMODEM_USB_ID": "0df7:0620",
                "RETROMODEM_TRANSPORT": transport,
                "RETROMODEM_LINE_MODE": line_mode,
                "RETROMODEM_IRDA_BITRATE": irda_bitrate,
                "RETROMODEM_IRDA_DIALUP_BITRATE": irda_dialup_bitrate,
                "RETROMODEM_SERIAL_BITRATE": serial_bitrate,
                "RETROMODEM_SERIAL_DIALUP_BITRATE": serial_dialup_bitrate,
            })
            run("/usr/local/lib/retromodem/apply-mode", timeout=20)
            self.redirect("/modem")
        elif path == "/phonebook/add":
            form["kind"] = "bbs"
            try:
                entry = phonebook_entry(form)
            except ValueError as error:
                self.send_error(HTTPStatus.BAD_REQUEST, str(error))
                return
            entries = load_phonebook()
            if any(item.get("number") == entry["number"] for item in entries):
                self.send_error(HTTPStatus.CONFLICT, "Dit telefoonnummer bestaat al")
                return
            entries.append(entry)
            entries.sort(key=lambda item: str(item.get("number", "")))
            save_phonebook(entries)
            if service_active("retromodem-tcpser.service"):
                run("/usr/bin/systemctl", "restart", "retromodem-tcpser.service")
            self.redirect("/phonebook")
        elif path == "/phonebook/update":
            original = form.get("original_number", "")
            entries = load_phonebook()
            index = next((i for i, item in enumerate(entries) if item.get("number") == original), None)
            if index is None:
                self.send_error(HTTPStatus.NOT_FOUND, "Telefoonnummer niet gevonden")
                return
            if entries[index].get("kind") in {"ppp", "chatgpt"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "Deze vaste systeementry kan niet worden gewijzigd")
                return
            if form.get("action") == "delete":
                entries.pop(index)
            else:
                form["kind"] = str(entries[index].get("kind", "bbs"))
                try:
                    entry = phonebook_entry(form)
                except ValueError as error:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(error))
                    return
                if any(i != index and item.get("number") == entry["number"] for i, item in enumerate(entries)):
                    self.send_error(HTTPStatus.CONFLICT, "Dit telefoonnummer bestaat al")
                    return
                entries[index] = entry
            entries.sort(key=lambda item: str(item.get("number", "")))
            save_phonebook(entries)
            if service_active("retromodem-tcpser.service"):
                run("/usr/bin/systemctl", "restart", "retromodem-tcpser.service")
            self.redirect("/phonebook")
        elif path == "/wifi/connect":
            ssid = form.get("ssid", "")
            if not ssid or len(ssid.encode("utf-8")) > 32:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige netwerknaam")
                return
            try:
                wifi_modules()[1].connect(config, ssid, form.get("password", ""))
            except (ValueError, RuntimeError):
                self.send_error(HTTPStatus.BAD_REQUEST, tr(language, 'Wifi-invoer ongeldig of er loopt al een verbindingspoging.', 'Invalid Wi-Fi input or a connection attempt is already running.'))
                return
            body = f"""<div class="notice"><strong>{tr(language,'Bezig met verbinden…','Connecting…')}</strong><br>{tr(language,'Verbind je telefoon zo nodig met het gekozen netwerk en open daarna','If necessary, connect your device to the selected network and then open')} <code>http://retromodem.local</code>. {tr(language,'Bij een fout keert accesspoint retromodem automatisch terug.','If it fails, the retromodem access point will return automatically.')}</div>"""
            self.send_page("Wi-Fi", body, config)
        elif path == "/openai/start":
            try:
                authorization_url = openai_auth.start_authorization()
            except (openai_auth.AuthError, OSError) as error:
                self.send_error(HTTPStatus.BAD_GATEWAY, str(error))
                return
            body = f"""<div class="page-heading"><h1>ChatGPT verbinden</h1><p>{tr(language,'Eenmalige aanmelding zonder API-key.','One-time sign-in without an API key.')}</p></div>
<section class="card"><h2>1. Continue with ChatGPT</h2><p>{tr(language,'Open de beveiligde OpenAI-aanmeldpagina, kies je account en geef toestemming voor gebruik van je ChatGPT-abonnement.','Open the secure OpenAI sign-in page, choose your account, and authorize use of your ChatGPT plan.')}</p><p><a class="button primary" target="_blank" rel="noreferrer" href="{html.escape(authorization_url, quote=True)}">Continue with ChatGPT</a></p></section>
<section class="card"><h2>{tr(language,'2. Plak de terugkoppel-URL','2. Paste the callback URL')}</h2><p>{tr(language,'Na toestemming probeert de browser 127.0.0.1 te openen. Die pagina mag een fout tonen. Kopieer de volledige URL uit de adresbalk, inclusief code en state, en plak hem hieronder. De code is kort geldig en werkt maar één keer.','After consent the browser tries to open 127.0.0.1. That page may show an error. Copy the complete address-bar URL, including code and state, and paste it below. The code expires quickly and works only once.')}</p>
<form method="post" action="/openai/complete"><input type="hidden" name="csrf" value="{{{{csrf}}}}"><label>{tr(language,'Volledige URL uit de adresbalk','Complete URL from the address bar')}</label><textarea name="callback_url" rows="5" maxlength="8192" autocomplete="off" required></textarea><button class="primary" type="submit">{tr(language,'Verbinding voltooien','Complete connection')}</button></form></section>"""
            self.send_page("ChatGPT", body, config)
        elif path == "/openai/complete":
            try:
                credentials = openai_auth.complete_authorization(form.get("callback_url", ""))
            except (openai_auth.AuthError, OSError) as error:
                body = f'<div class="notice warning"><strong>{tr(language,"Verbinden mislukt","Connection failed")}</strong><br>{html.escape(str(error))}</div><p><a class="button" href="/settings">{tr(language,"Terug naar Instellingen","Back to Settings")}</a></p>'
                self.send_page("ChatGPT", body, config)
                return
            account = html.escape(str(credentials.get("email", "")))
            body = f'<div class="notice"><strong>{tr(language,"ChatGPT is verbonden","ChatGPT is connected")}</strong><br>{account}</div><p>{tr(language,"Bel 5559999 om te chatten.","Dial 5559999 to chat.")}</p><p><a class="button primary" href="/phonebook">{tr(language,"Naar Telefoonboek","Go to Phone book")}</a></p>'
            self.send_page("ChatGPT", body, config)
        elif path == "/openai/disconnect":
            openai_auth.disconnect()
            try:
                import chatgpt_web
            except ModuleNotFoundError:
                from web import chatgpt_web
            chatgpt_web.reset_shared()
            self.redirect("/settings")
        elif path == "/settings/chatgpt":
            continue_conversation = "1" if form.get("continue_conversation") == "1" else "0"
            allow_agent = "1" if form.get("allow_agent") == "1" else "0"
            save_config({"RETROMODEM_CHATGPT_CONTINUE": continue_conversation,
                         "RETROMODEM_CHATGPT_AGENT": allow_agent})
            if continue_conversation == "0":
                try:
                    import chatgpt_web
                except ModuleNotFoundError:
                    from web import chatgpt_web
                chatgpt_web.reset_shared()
            run("/usr/bin/systemctl", "restart", "retromodem-chatgpt.service")
            self.redirect("/settings#chatgpt")
        elif path == "/settings/proxy":
            try:
                pagination = proxy_pagination_settings(form.get("page_size", "250000"), form.get("page_images", "5"))
            except ValueError:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige pagina-indeling")
                return
            mode = form.get("mode", "")
            if mode not in {"transparent", "manual"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige proxystand")
                return
            image_start = form.get("image_start", form.get("image_mode", ""))
            if image_start not in {"inline", "links", "remember"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige afbeeldingsweergave")
                return
            exceptions = [value.lower().strip(".") for value in re.split(r"[\s,]+", form.get("exceptions", "")) if value]
            domain_pattern = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,62}$")
            if len(exceptions) > 50 or any(not domain_pattern.fullmatch(value) for value in exceptions):
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige proxy-uitzondering")
                return
            try:
                image_width = int(form.get("image_width", "512"))
                image_height = int(form.get("image_height", "342"))
            except ValueError:
                image_width = image_height = 0
            if not 16 <= image_width <= 4096 or not 16 <= image_height <= 4096:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige afbeeldingsgrootte")
                return
            save_config({**pagination, "RETROMODEM_PROXY_MODE": mode,
                         "RETROMODEM_PROXY_EXCEPTIONS": ",".join(dict.fromkeys(exceptions)),
                         "RETROMODEM_PROXY_IMAGE_START": image_start,
                         "RETROMODEM_PROXY_IMAGE_WIDTH": str(image_width),
                         "RETROMODEM_PROXY_IMAGE_HEIGHT": str(image_height)})
            old_mode = config.get("RETROMODEM_PROXY_MODE", config.get("RETROMODEM_68KPROXY_MODE", "manual"))
            if old_mode not in {"manual", "transparent"}:
                old_mode = "manual"
            # Content settings are read on each request. Only a routing-mode
            # change needs firewall work; never kill in-flight HTTP requests.
            if old_mode != mode:
                applied = run("/usr/local/lib/retromodem/proxy-firewall", "apply")
                if applied.returncode:
                    save_config({"RETROMODEM_PROXY_MODE": old_mode})
                    run("/usr/local/lib/retromodem/proxy-firewall", "apply")
                    self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, "Proxyroutering kon niet worden toegepast; vorige instelling teruggezet. Controleer de netwerkstatus.")
                    return
            self.redirect("/settings#webproxy")
        elif path == "/settings":
            new_language = form.get("language", "")
            ap_ssid = form.get("ap_ssid", "").strip()
            ap_password = form.get("ap_password", "")
            if new_language not in {"nl", "en"}:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige instelling")
                return
            if not ap_ssid or len(ap_ssid.encode("utf-8")) > 32 or not 8 <= len(ap_password) <= 63:
                self.send_error(HTTPStatus.BAD_REQUEST, "Ongeldige accesspoint-instelling")
                return
            save_config({
                "RETROMODEM_LANGUAGE": new_language,
                "RETROMODEM_AP_SSID": ap_ssid,
                "RETROMODEM_AP_PASSWORD": ap_password,
            })
            updated = load_config()
            environment = os.environ.copy()
            environment.update(updated)
            run("/usr/local/lib/retromodem/configure-ap", env=environment)
            run("/usr/bin/systemctl", "restart", "retromodem-ap-fallback.service")
            self.send_page(tr(new_language, "Opgeslagen", "Saved"), f'<div class="notice">{tr(new_language,"Instellingen opgeslagen.","Settings saved.")}</div>', updated)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def log_message(self, fmt: str, *args: object) -> None:
        if getattr(self, 'headers', {}).get('Host', '').split(':', 1)[0].lower().rstrip('.') == 'wifi.retromodem':
            print(f"{self.address_string()} - Wi-Fi setup request", flush=True)
            return
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    wifi_modules()[1].recover()
    address = os.environ.get("RETROMODEM_WEB_ADDRESS", "0.0.0.0")
    port = int(os.environ.get("RETROMODEM_WEB_PORT", "80"))
    ThreadingHTTPServer((address, port), Handler).serve_forever()
