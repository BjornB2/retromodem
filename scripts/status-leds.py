#!/usr/bin/python3
"""Drive the P/D front LEDs as modem, Wi-Fi and power status indicators."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path


CONFIG = Path("/etc/retromodem/retromodem.env")
PINCTRL = "/usr/bin/pinctrl"
MINIMUM_START_INDICATION = 3.0


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = CONFIG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for raw in lines:
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value.strip("'\"")
    return values


def command_output(args: list[str]) -> str:
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, check=False)
    return result.stdout.strip()


def current_undervoltage() -> bool:
    output = command_output(["/usr/bin/vcgencmd", "get_throttled"])
    match = re.search(r"0x([0-9a-fA-F]+)", output)
    return bool(match and int(match.group(1), 16) & 0x1)


def wifi_status(interface: str) -> str:
    connection = command_output([
        "/usr/bin/nmcli", "-g", "GENERAL.CONNECTION", "device", "show", interface,
    ])
    if connection == "retromodem-ap":
        return "hotspot"
    state = command_output([
        "/usr/bin/nmcli", "-g", "GENERAL.STATE", "device", "show", interface,
    ])
    return "connected" if state.startswith("100 ") else "connecting"


def service_main_pid(service: str) -> int:
    output = command_output([
        "/usr/bin/systemctl", "show", "--property=MainPID", "--value", service,
    ])
    return int(output) if output.isdigit() else 0


def process_has_modem_tty(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        targets = [entry.resolve() for entry in Path(f"/proc/{pid}/fd").iterdir()]
    except OSError:
        return False
    return any(str(target) == "/dev/ircomm0" or target.name.startswith("ttyUSB")
               for target in targets)


def modem_status(values: dict[str, str]) -> str:
    mode = values.get("RETROMODEM_LINE_MODE", "ppp")
    service = "retromodem-ppp.service" if mode == "ppp" else "retromodem-tcpser.service"
    return "ready" if process_has_modem_tty(service_main_pid(service)) else "starting"


def led_pattern(mode: str, network: str, modem: str, undervoltage: bool,
                elapsed: float) -> tuple[bool, bool]:
    """Return (PPP LED, dial-up LED); earlier cases have higher priority."""
    if undervoltage:
        # Two brisk flashes, then a pause: a warning distinct from every
        # networking state and still readable when the battery is marginal.
        phase = elapsed % 2.0
        enabled = phase < 0.14 or 0.30 <= phase < 0.44
        return enabled, enabled
    if network == "hotspot":
        # Alternating P/D means: connect a phone/laptop to the setup hotspot.
        return (elapsed % 0.8) < 0.4, (elapsed % 0.8) >= 0.4
    if network == "connecting":
        # Both LEDs breathe together while NetworkManager is looking for Wi-Fi.
        enabled = (elapsed % 1.2) < 0.6
        return enabled, enabled
    selected_ppp = mode == "ppp"
    if modem == "starting":
        enabled = (elapsed % 1.2) < 0.6
    else:
        enabled = True
    return enabled and selected_ppp, enabled and not selected_ppp


def set_led(pin: int, enabled: bool) -> None:
    subprocess.run([PINCTRL, "set", str(pin), "op", "dh" if enabled else "dl"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def main() -> None:
    started = time.monotonic()
    last_probe = 0.0
    observed_mode: str | None = None
    mode_changed = started
    state = ("ppp", "connecting", "starting", False, 24, 23)
    shown: tuple[bool, bool] | None = None
    while True:
        now = time.monotonic()
        if now - last_probe >= 1.0:
            values = load_config()
            mode = values.get("RETROMODEM_LINE_MODE", "ppp")
            if mode != observed_mode:
                observed_mode = mode
                mode_changed = now
            modem = modem_status(values)
            if now - mode_changed < MINIMUM_START_INDICATION:
                modem = "starting"
            state = (
                mode,
                wifi_status(values.get("RETROMODEM_WIFI_INTERFACE", "wlan0")),
                modem,
                current_undervoltage(),
                int(values.get("RETROMODEM_GPIO_LED_PPP", "24")),
                int(values.get("RETROMODEM_GPIO_LED_DIALUP", "23")),
            )
            last_probe = now
        mode, network, modem, undervoltage, ppp_pin, dialup_pin = state
        wanted = led_pattern(mode, network, modem, undervoltage, now - started)
        if wanted != shown:
            set_led(ppp_pin, wanted[0])
            set_led(dialup_pin, wanted[1])
            shown = wanted
        time.sleep(0.08)


if __name__ == "__main__":
    main()
