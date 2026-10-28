#!/usr/bin/python3
"""RetroModem front-panel button controller.

GPIO numbering uses BCM numbers. The momentary button connects the configured
GPIO to ground, so the input is active-low with its internal pull-up enabled.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import time


CONFIG = Path("/etc/retromodem/retromodem.env")
APPLY_MODE = "/usr/local/lib/retromodem/apply-mode"
PINCTRL = "/usr/bin/pinctrl"


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in CONFIG.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def save_value(key: str, value: str) -> None:
    lines = CONFIG.read_text(encoding="utf-8").splitlines()
    replacement = f"{key}={value}"
    changed = False
    for index, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[index] = replacement
            changed = True
            break
    if not changed:
        lines.append(replacement)
    fd, name = tempfile.mkstemp(prefix="retromodem.env.", dir=CONFIG.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
        os.chmod(name, 0o600)
        os.replace(name, CONFIG)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def parse_level(output: str) -> bool:
    """Return True for high/released and False for low/pressed."""
    match = re.search(r"\b(hi|lo)\b", output.lower())
    if match:
        return match.group(1) == "hi"
    match = re.search(r"\blevel\s*=\s*([01])\b", output.lower())
    if match:
        return match.group(1) == "1"
    raise RuntimeError(f"Onbekende pinctrl-uitvoer: {output.strip()}")


def pin_high(pin: int) -> bool:
    result = subprocess.run(
        [PINCTRL, "get", str(pin)], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return parse_level(result.stdout)


def set_led(pin: int, enabled: bool) -> None:
    subprocess.run(
        [PINCTRL, "set", str(pin), "op", "dh" if enabled else "dl"],
        check=False,
    )


def shutdown_feedback(ppp_led: int, dialup_led: int) -> None:
    # Prevent the status daemon from overwriting the shutdown pattern.
    subprocess.run(
        ["/usr/bin/systemctl", "stop", "retromodem-leds.service"], check=False,
    )
    for _ in range(3):
        set_led(ppp_led, True)
        set_led(dialup_led, True)
        time.sleep(0.16)
        set_led(ppp_led, False)
        set_led(dialup_led, False)
        time.sleep(0.16)


def toggle_mode() -> None:
    values = load_config()
    current = values.get("RETROMODEM_LINE_MODE", "ppp")
    new_mode = "dialup" if current == "ppp" else "ppp"
    save_value("RETROMODEM_LINE_MODE", new_mode)
    try:
        subprocess.run([APPLY_MODE], check=True)
    except subprocess.CalledProcessError:
        # Do not leave the saved setting claiming a mode that failed to start.
        save_value("RETROMODEM_LINE_MODE", current)
        subprocess.run([APPLY_MODE], check=False)
        raise


def main() -> None:
    values = load_config()
    button = int(values.get("RETROMODEM_GPIO_BUTTON", "16"))
    ppp_led = int(values.get("RETROMODEM_GPIO_LED_PPP", "24"))
    dialup_led = int(values.get("RETROMODEM_GPIO_LED_DIALUP", "23"))
    hold_seconds = float(values.get("RETROMODEM_BUTTON_HOLD_SECONDS", "3.0"))

    subprocess.run([PINCTRL, "set", str(button), "ip", "pu"], check=True)

    stable_high = pin_high(button)
    candidate_high = stable_high
    candidate_since = time.monotonic()
    pressed_since: float | None = None
    shutdown_started = False

    while True:
        now = time.monotonic()
        level_high = pin_high(button)
        if level_high != candidate_high:
            candidate_high = level_high
            candidate_since = now
        elif level_high != stable_high and now - candidate_since >= 0.06:
            stable_high = level_high
            if not stable_high:
                pressed_since = now
                shutdown_started = False
            elif pressed_since is not None:
                if not shutdown_started and now - pressed_since >= 0.08:
                    toggle_mode()
                pressed_since = None

        if (not stable_high and pressed_since is not None and
                not shutdown_started and now - pressed_since >= hold_seconds):
            shutdown_started = True
            shutdown_feedback(ppp_led, dialup_led)
            subprocess.run(["/usr/bin/systemctl", "poweroff"], check=False)

        time.sleep(0.04)


if __name__ == "__main__":
    main()
