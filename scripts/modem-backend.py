#!/usr/bin/python3
"""Launch the selected RetroModem data service."""

import json
import os
import subprocess
import sys
from pathlib import Path

PHONEBOOK = Path("/etc/retromodem/phonebook.json")


def serial_device(usb_id: str) -> str:
    vendor, product = usb_id.lower().split(":", 1)
    for device in sorted(Path("/dev").glob("ttyUSB*")):
        result = subprocess.run(
            ["/usr/bin/udevadm", "info", "--query=property", f"--name={device}"],
            text=True, capture_output=True, check=False,
        )
        properties = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if properties.get("ID_VENDOR_ID", "").lower() == vendor and properties.get("ID_MODEL_ID", "").lower() == product:
            return str(device)
    raise SystemExit(f"Adapter {usb_id} is niet aangesloten")


def selected_device() -> tuple[str, str, bool]:
    transport = os.environ.get("RETROMODEM_TRANSPORT", "irda")
    if transport == "irda":
        speed = os.environ.get("RETROMODEM_IRDA_BITRATE", "9600")
        if os.environ.get("RETROMODEM_LINE_MODE") == "dialup":
            speed = os.environ.get("RETROMODEM_IRDA_DIALUP_BITRATE", "57600")
        return "/dev/ircomm0", speed, False
    if transport == "serial":
        speed = os.environ.get("RETROMODEM_SERIAL_BITRATE", "115200")
        if os.environ.get("RETROMODEM_LINE_MODE") == "dialup":
            speed = os.environ.get("RETROMODEM_SERIAL_DIALUP_BITRATE", "57600")
        return serial_device(os.environ.get("RETROMODEM_SERIAL_USB_ID", "067b:2303")), speed, True
    raise SystemExit(f"Onbekend transport: {transport}")


def direct_ppp() -> None:
    device, speed, hardware_flow = selected_device()
    args = [
        "/usr/sbin/pppd", device, speed, "nodetach", "local",
        "crtscts" if hardware_flow else "nocrtscts", "noauth", "passive", "silent",
        "persist", "holdoff", "2",
        # Keep pppd's normal three-second negotiation interval. Retrying every
        # second can make slower Palm OS PPP stacks restart LCP before their
        # IPCP response has been processed.
        "lcp-restart", "3", "ipcp-restart", "3",
        "lcp-echo-interval", "10", "lcp-echo-failure", "3",
        "192.168.77.1:192.168.77.2",
        "netmask", "255.255.255.0", "ms-dns", "192.168.77.1", "ms-dns", "192.168.77.1",
        # EPOC asks for primary and secondary WINS during IPCP. Supplying both
        # avoids a ConfRej followed by several complete LCP/IPCP restarts.
        "ms-wins", "192.168.77.1", "ms-wins", "192.168.77.1",
        # Keep Van Jacobson TCP header compression negotiable. Palm OS 4.1
        # requests it during IPCP and restarts the whole PPP negotiation when
        # the server rejects it. Clients such as EPOC that do not request VJ
        # are unaffected.
        "noipv6", "noccp", "debug", "logfile", "/var/log/retromodem-ppp.log",
    ]
    os.execv(args[0], args)


def tcpser() -> None:
    device, speed, _ = selected_device()
    document = json.loads(PHONEBOOK.read_text(encoding="utf-8"))
    # Dial-up clients must see carrier only after tcpser has connected to the
    # selected destination.  Forcing DCD high with &C0 makes clients such as
    # EPOC start PPP immediately, before sending ATD.  IrCOMM has no RTS/CTS,
    # so keep flow control disabled while retaining normal carrier tracking.
    init = "e1&c1&k0" if os.environ.get("RETROMODEM_TRANSPORT", "irda") == "irda" else "e1&c1&k3"
    args = ["/usr/local/bin/tcpser", "-d", device, "-s", speed, "-S", speed, "-l", "5", "-i", init]
    for entry in document.get("entries", []):
        number = str(entry["number"])
        target = f'{entry["host"]}:{int(entry["port"])}'
        args.extend(["-n", f"{number}={target}"])
    os.execv(args[0], args)


if len(sys.argv) != 2 or sys.argv[1] not in {"direct-ppp", "tcpser"}:
    raise SystemExit("Gebruik: modem-backend.py direct-ppp|tcpser")
direct_ppp() if sys.argv[1] == "direct-ppp" else tcpser()
