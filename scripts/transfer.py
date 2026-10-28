#!/usr/bin/python3
"""Run one exclusive serial file-transfer job and restore modem mode afterwards."""

import json
import fcntl
import os
import re
import queue
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path("/var/lib/retromodem/transfers")
STATUS = ROOT / "status.json"
LOCK = ROOT / "transfer.lock"
ACTIVE_PROCESS: subprocess.Popen[bytes] | None = None


class TransferProgress:
    """Payload counters only: never derive percentage from baud rate or a timer."""
    def __init__(self, total_bytes=None):
        self.details = {}
        self.first_sample = None
        self.total_bytes = total_bytes

    def update(self, line, now):
        match = re.search(r"RETROMODEM_PROGRESS\s+(\d+)\s+(\d+)", line)
        elapsed = None
        if not match:
            match = re.search(r"sent\s+(\d+)/(\d+)\s+bytes=", line)
            timing = re.search(r"in\s+([0-9.]+)\s+sec", line)
            elapsed = float(timing[1]) if timing else None
        if not match:
            match = re.search(r"\bBytes\s+(?:Sent|received):\s*(\d+)\s*/\s*(\d+)", line, re.I)
        if not match and self.total_bytes:
            sectors = re.search(r"([XY])modem sectors/kbytes sent:\s*(\d+)", line, re.I)
            count_only = re.search(r"Bytes Sent:\s*(\d+)\s+BPS:", line, re.I)
            if sectors:
                # lrzsz counts accepted 128-byte sectors. YMODEM includes
                # one pathname sector, which is not part of the file.
                count = max(0, int(sectors[2]) - (sectors[1].upper() == 'Y')) * 128
            elif count_only:
                count = int(count_only[1])
            else:
                return dict(self.details)
            # sb emits a fresh zero counter for its empty batch terminator.
            # This job sends one file, so that is not a new payload.
            if count < self.details.get('bytes_transferred', 0):
                return dict(self.details)
            line = f'RETROMODEM_PROGRESS {min(count, self.total_bytes)} {self.total_bytes}'
            match = re.search(r"RETROMODEM_PROGRESS\s+(\d+)\s+(\d+)", line)
        if match:
            count, total = map(int, match.groups())
            if total <= 0 or count > total:
                return dict(self.details)
            if self.first_sample is None:
                self.first_sample = (now, count)
            first_time, first_count = self.first_sample
            duration = elapsed if elapsed is not None else now - first_time
            amount = count if elapsed is not None else count - first_count
            self.details.update(bytes_transferred=count, bytes_total=total,
                                progress=min(99.9, count / total * 100))
            if duration > 0 and amount >= 0:
                self.details['speed_kbytes_sec'] = amount / duration / 1000
        return dict(self.details)


def palm_creator_id(path: Path) -> str:
    """Return the four-byte Palm database creator used by IrOBEX Beam."""
    header = path.read_bytes()[:68]
    if len(header) < 68 or path.suffix.lower() not in {".prc", ".pdb"}:
        raise TransferFailed("Palm Beam ondersteunt alleen geldige PRC- en PDB-bestanden")
    creator = header[64:68]
    if any(byte < 0x20 or byte > 0x7e for byte in creator):
        raise TransferFailed("Het Palm creator-ID in dit bestand is ongeldig")
    return creator.decode("ascii")


def write_status(state: str, message: str, output: str = "", **extra: object) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    temporary = STATUS.with_suffix(".tmp")
    document = {"state": state, "message": message, "output": output, "time": int(time.time()), **extra}
    temporary.write_text(json.dumps(document), encoding="utf-8")
    temporary.replace(STATUS)


def config() -> dict[str, str]:
    values = {}
    for line in Path("/etc/retromodem/retromodem.env").read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value.strip("'\"")
    return values


def device(values: dict[str, str]) -> tuple[str, str]:
    if values.get("RETROMODEM_TRANSPORT", "irda") == "irda":
        return "/dev/ircomm0", values.get("RETROMODEM_IRDA_DIALUP_BITRATE", "57600")
    usb_id = values.get("RETROMODEM_SERIAL_USB_ID", "067b:2303").lower()
    vendor, product = usb_id.split(":", 1)
    for candidate in sorted(Path("/dev").glob("ttyUSB*")):
        info = subprocess.run(["udevadm", "info", "--query=property", f"--name={candidate}"], text=True, capture_output=True).stdout
        if f"ID_VENDOR_ID={vendor}" in info and f"ID_MODEL_ID={product}" in info:
            return str(candidate), values.get("RETROMODEM_SERIAL_BITRATE", "115200")
    raise RuntimeError(f"Adapter {usb_id} niet gevonden")


class TransferCancelled(Exception):
    pass


class TransferFailed(Exception):
    pass


def cancelled(_signum: int, _frame: object) -> None:
    if ACTIVE_PROCESS is not None and ACTIVE_PROCESS.poll() is None:
        ACTIVE_PROCESS.terminate()
    raise TransferCancelled("Overdracht gestopt")


def execute(command: list[str], serial: object, output: object, cwd: Path) -> tuple[int, bytes]:
    global ACTIVE_PROCESS
    ACTIVE_PROCESS = subprocess.Popen(command, stdin=serial, stdout=output, stderr=subprocess.PIPE, cwd=cwd)
    try:
        _stdout, stderr = ACTIVE_PROCESS.communicate()
        return ACTIVE_PROCESS.returncode, stderr or b""
    finally:
        ACTIVE_PROCESS = None


def execute_device(command: list[str], cwd: Path, status_extra: dict[str, object], label: str,
                   inactivity_timeout: int = 180, serial=None, total_bytes=None) -> tuple[int, str]:
    """Run a native IrDA transfer tool and expose its output in the web UI."""
    global ACTIVE_PROCESS
    lines: list[str] = []
    events: queue.Queue[str | None] = queue.Queue()
    process = subprocess.Popen(
        command,
        stdin=serial, stdout=serial if serial is not None else subprocess.PIPE,
        stderr=subprocess.PIPE if serial is not None else subprocess.STDOUT, text=True,
        cwd=cwd, bufsize=1, env={**os.environ, 'LC_ALL': 'C'},
    )
    ACTIVE_PROCESS = process

    def collect_output() -> None:
        stream = process.stderr if serial is not None else process.stdout
        assert stream is not None
        # irpsion5 updates progress using carriage returns instead of newline
        # characters. Iterating over the stream by line therefore hid all
        # progress until the process exited. Treat CR and LF as status-record
        # boundaries so the browser receives the progress while it is useful.
        record: list[str] = []
        while True:
            character = stream.read(1)
            if character == "":
                break
            if character in {"\r", "\n"}:
                if record:
                    events.put("".join(record) + "\n")
                    record.clear()
            else:
                record.append(character)
        if record:
            events.put("".join(record) + "\n")
        events.put(None)

    reader = threading.Thread(target=collect_output, daemon=True)
    reader.start()
    last_output = time.monotonic()
    progress_meter = TransferProgress(total_bytes)
    try:
        while True:
            try:
                line = events.get(timeout=1)
            except queue.Empty:
                if process.poll() is not None:
                    break
                if time.monotonic() - last_output > inactivity_timeout:
                    process.terminate()
                    raise TransferFailed(
                        f"De {label}-overdracht gaf {inactivity_timeout} seconden geen voortgang; "
                        "de IrDA-sessie is gecontroleerd afgebroken."
                    )
                continue
            if line is None:
                break
            last_output = time.monotonic()
            lines.append(line)
            output = "".join(lines)[-4000:]
            measured = progress_meter.update(line, last_output)
            status_extra.update(measured)
            details = {**status_extra, "phase": "transferring" if measured else status_extra.get('phase', 'waiting'), **measured}
            if measured.get('bytes_total') == measured.get('bytes_transferred') and measured:
                details['phase'] = 'finalizing'
            message = f"{label}-overdracht actief" if measured else f"{label} — wachten op verbinding"
            write_status("running", message, output, **details)
        return process.wait(), "".join(lines)[-4000:]
    finally:
        ACTIVE_PROCESS = None


def available_name(directory: Path, name: str) -> Path:
    candidate = directory / name
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    for number in range(2, 1000):
        alternative = directory / f"{stem} ({number}){suffix}"
        if not alternative.exists():
            return alternative
    raise RuntimeError("Te veel bestanden met dezelfde naam")


def cleanup_sent_upload(path: Path) -> None:
    """Only discard web-created work copies; never a library/static original."""
    if path.parent.name.startswith("work-") and path.parent.parent.resolve() == ROOT.resolve():
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass


def restore_modem_mode(values: dict[str, str]) -> str:
    """Restore the selected modem service and verify that it really returned."""
    result = subprocess.run(
        ["/usr/local/lib/retromodem/apply-mode"],
        text=True, capture_output=True, check=False,
    )
    expected = ("retromodem-ppp.service"
                if values.get("RETROMODEM_LINE_MODE", "ppp") == "ppp"
                else "retromodem-tcpser.service")
    for _attempt in range(50):
        active = subprocess.run(
            ["systemctl", "is-active", "--quiet", expected],
            check=False,
        ).returncode == 0
        if result.returncode == 0 and active:
            return ""
        time.sleep(0.1)
    details = (result.stderr or result.stdout).strip()
    return f"{expected} kwam niet terug" + (f": {details}" if details else "")


def main() -> int:
    if len(sys.argv) != 4:
        raise SystemExit("Gebruik: transfer.py send|receive ascii|xmodem|ymodem|zmodem|epoc|palm|windows PAD")
    direction, protocol, pathname = sys.argv[1:4]
    if direction not in {"send", "receive"} or protocol not in {"ascii", "xmodem", "ymodem", "zmodem", "epoc", "palm", "windows"}:
        raise SystemExit("Ongeldige overdracht")
    path = Path(pathname)
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = LOCK.open("w")
    final_state = ("error", "Overdracht onverwacht afgebroken", "")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        write_status("error", "Er is al een bestandsoverdracht actief")
        return 1
    values = config()
    if protocol in {"epoc", "palm", "windows"} and values.get("RETROMODEM_TRANSPORT", "irda") != "irda":
        write_status("error", "Deze apparaatspecifieke overdracht werkt alleen via de IrDA-adapter")
        return 1
    tty, speed = ("", "") if protocol in {"epoc", "palm", "windows"} else device(values)
    received_dir = ROOT / "received"
    received_dir.mkdir(mode=0o755, exist_ok=True)
    if direction == "receive" and protocol in {"ascii", "xmodem"}:
        path = available_name(received_dir, path.name)
    commands = {
        ("send", "ascii"): ["/bin/cat", str(path)],
        ("send", "xmodem"): ["/usr/bin/sx", "-vv", str(path)],
        ("send", "ymodem"): ["/usr/bin/sb", "-vv", str(path)],
        ("send", "zmodem"): ["/usr/bin/sz", "-vv", str(path)],
        ("receive", "ascii"): ["/usr/bin/timeout", "120", "/bin/cat"],
        ("receive", "xmodem"): ["/usr/bin/rx", "-vv", str(path)],
        ("receive", "ymodem"): ["/usr/bin/rb", "-E", "-vv"],
        ("receive", "zmodem"): ["/usr/bin/rz", "-E", "-vv"],
    }
    command = commands.get((direction, protocol), [])
    signal.signal(signal.SIGTERM, cancelled)
    started = int(time.time())
    ready_message = (
        f"Wachten op verbinding met het apparaat om {path.name} te verzenden"
        if direction == "send" else
        f"Wachten op verbinding met het apparaat voor {protocol.upper()}-ontvangst"
    )
    status_extra = {"pid": os.getpid(), "direction": direction, "protocol": protocol,
                    "filename": path.name, "started": started, "phase": "waiting"}
    write_status("running", ready_message, **status_extra)
    subprocess.run(["systemctl", "stop", "retromodem-ppp.service", "retromodem-tcpser.service"], check=False)
    try:
        if protocol in {"epoc", "palm", "windows"}:
            transfer_cwd = received_dir if direction == "receive" else path.parent
            transfer_cwd.mkdir(parents=True, exist_ok=True)
            before = {item.name for item in transfer_cwd.iterdir()}
            if protocol == "palm":
                if direction == "send":
                    progress_tool = Path('/usr/local/lib/retromodem/irobex-palm-progress')
                    command = [str(progress_tool) if progress_tool.is_file() else "/usr/bin/irobex_palm3",
                               "-h", palm_creator_id(path), path.name]
                    status_extra["phase"] = "discovering"
                    message = "Palm zoeken — open Beam Receive op de Palm"
                else:
                    # Without file arguments irobex_palm3 becomes an IrOBEX
                    # receiver and preserves the object name supplied by Palm OS.
                    command = ["/usr/bin/irobex_palm3"]
                    status_extra["phase"] = "waiting"
                    message = "Klaar voor Palm Beam — kies Beam op de Palm"
                write_status("running", message, **status_extra)
            elif protocol == "windows":
                if direction == "send":
                    # ircp advertises the standard IrOBEX Object Push service
                    # used by Windows Wireless Link and preserves the filename.
                    command = ["/usr/bin/ircp", path.name]
                    status_extra["phase"] = "discovering"
                    message = "Windows Wireless Link zoeken — zet de pc klaar om te ontvangen"
                else:
                    command = ["/usr/bin/ircp", "-r", str(received_dir)]
                    status_extra["phase"] = "waiting"
                    message = "Klaar voor Windows Wireless Link — verzend nu vanaf de pc"
                write_status("running", message, **status_extra)
            else:
                irpsion = ("/usr/local/lib/retromodem/irpsion5-send"
                           if direction == "send" else "/usr/sbin/irpsion5")
                command = [irpsion, "-v", "-D", "1"]
                command += ["-s", path.name] if direction == "send" else ["-r"]
            label = {"palm": "Palm Beam", "windows": "Windows Wireless Link"}.get(
                protocol, "Psion/EPOC"
            )
            # irobex_palm3 provides no dependable byte-level progress output.
            # A sizeable PRC at 9600 bit/s can therefore be healthy yet silent
            # for several minutes; don't mistake that for a stalled transfer.
            timeout = 600 if protocol in {"palm", "windows"} else 180
            returncode, message = execute_device(
                command, transfer_cwd, status_extra, label, inactivity_timeout=timeout
            )
            if returncode != 0:
                family = {"palm": "Palm Beam", "windows": "Windows Wireless Link"}.get(
                    protocol, "EPOC-overdracht"
                )
                raise TransferFailed(message or f"{family} stopte met code {returncode}")
            received = ([item.name for item in transfer_cwd.iterdir()
                         if item.is_file() and item.name not in before]
                        if direction == "receive" else [])
            display_name = ", ".join(received) if received else path.name
            final_state = ("complete", f"Overdracht voltooid: {display_name}", message)
            return 0
        subprocess.run(["stty", "-F", tty, speed, "raw", "-echo"], check=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        transfer_cwd = received_dir if direction == "receive" and protocol in {"ymodem", "zmodem"} else path.parent
        before = {item.name for item in transfer_cwd.iterdir()}
        with open(tty, "r+b", buffering=0) as serial:
            connected_message = (
                f"{protocol.upper()} verbonden — bestandsnaam van {path.name} wordt verzonden"
                if direction == "send" else
                f"{protocol.upper()} verbonden — klaar om het bestand te ontvangen"
            )
            write_status("running", connected_message, **{**status_extra, "phase": "transferring"})
            if direction == "receive" and protocol == "ascii":
                with path.open("wb") as output:
                    returncode, stderr = execute(command, serial, output, transfer_cwd)
                message = stderr.decode("utf-8", "replace")[-2000:]
            elif protocol != 'ascii':
                returncode, message = execute_device(
                    command, transfer_cwd, status_extra, protocol.upper(), serial=serial,
                    total_bytes=path.stat().st_size if direction == 'send' else None,
                )
            else:
                returncode, stderr = execute(command, serial, serial, transfer_cwd)
                message = stderr.decode("utf-8", "replace")[-2000:]
        if returncode not in {0, 124}:
            raise TransferFailed(message or f"Transfer stopte met code {returncode}")
        received = []
        if direction == "receive" and protocol in {"ymodem", "zmodem"}:
            for item in transfer_cwd.iterdir():
                if item.is_file() and item.name not in before:
                    received.append(item.name)
        elif direction == "receive":
            received.append(path.name)
        display_name = ", ".join(received) if received else path.name
        final_state = ("complete", f"Overdracht voltooid: {display_name}", message)
        return 0
    except TransferCancelled:
        final_state = ("cancelled", "Overdracht gestopt", "")
        return 2
    except TransferFailed as error:
        final_state = ("error", "Overdracht mislukt", str(error))
        return 1
    except Exception as error:
        final_state = ("error", str(error), "")
        return 1
    finally:
        restore_error = restore_modem_mode(values)
        if restore_error:
            state, message, output = final_state
            final_state = (
                "error",
                ("Overdracht voltooid, maar de modemverbinding kon niet worden hersteld"
                 if state == "complete" else message),
                "\n".join(part for part in (output, restore_error) if part),
            )
        if direction == "send" and final_state[0] == "complete":
            cleanup_sent_upload(path)
        state = final_state[0]
        phase = "finished" if state == "complete" else state
        write_status(*final_state, direction=direction, protocol=protocol, filename=path.name,
                     started=started, finished=int(time.time()), phase=phase,
                     **{key: (100 if key == 'progress' and state == 'complete' else value)
                        for key, value in status_extra.items()
                        if key in {'progress', 'bytes_transferred', 'bytes_total', 'speed_kbytes_sec'}})


if __name__ == "__main__":
    raise SystemExit(main())
