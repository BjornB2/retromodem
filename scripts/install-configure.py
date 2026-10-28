#!/usr/bin/env python3
"""Plan/apply adapter configuration without executing shell configuration values."""
import argparse
import os
from pathlib import Path
import re
import shlex
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
CHOICES = {"my018": "ming-yuan-my018", "ma620": "mobile-action-ma620", "serial": "serial"}


def read_config(path):
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if not re.match(r"^RETROMODEM_[A-Z0-9_]+=", line):
                continue
            key, raw = line.split("=", 1)
            parts = shlex.split(raw)
            if len(parts) > 1:
                raise ValueError(f"Invalid shell value for {key}")
            values[key] = parts[0] if parts else ""
    return values


def atomic_write(path, text, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError(f"Refusing symlink: {path}")
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def plan(root, adapter=None, confirmed=False):
    config = root / "etc/retromodem/retromodem.env"
    existing = read_config(config)
    values = {**read_config(PROJECT / "config/retromodem.env"), **existing}
    if adapter is None:
        if existing:
            adapter = ("serial" if existing.get("RETROMODEM_TRANSPORT") == "serial" else
                       next((k for k, v in CHOICES.items() if v == existing.get("RETROMODEM_ADAPTER")), None))
            if adapter is None:
                raise ValueError("Unknown saved adapter; choose --adapter my018|ma620|serial")
        else:
            adapter = "my018"
    if adapter == "my018":
        already_confirmed = (existing.get("RETROMODEM_MY018_POWER_CYCLE") == "1")
        if not (confirmed or already_confirmed):
            raise ValueError("MY018 requires the documented A/B/C + 2N3904 wiring. "
                             "Confirm with --my018-wiring-confirmed, or choose ma620/serial.")
        profile = {"RETROMODEM_ADAPTER": CHOICES[adapter], "RETROMODEM_TRANSPORT": "irda",
                   "RETROMODEM_TTY": "/dev/serial0", "RETROMODEM_DONGLE": "",
                   "RETROMODEM_MY018_POWER_CYCLE": "1",
                   "RETROMODEM_IRDA_BITRATE": existing.get("RETROMODEM_MY018_BITRATE", "57600"),
                   "RETROMODEM_IRDA_DIALUP_BITRATE": existing.get("RETROMODEM_MY018_DIALUP_BITRATE", "115200")}
        # Preserve speeds for an existing active MY018 profile.
        if existing.get("RETROMODEM_ADAPTER") == CHOICES[adapter]:
            for key in ("RETROMODEM_IRDA_BITRATE", "RETROMODEM_IRDA_DIALUP_BITRATE"):
                if key in existing:
                    profile[key] = existing[key]
        values.update(profile)
        values["RETROMODEM_MY018_BITRATE"] = values["RETROMODEM_IRDA_BITRATE"]
        values["RETROMODEM_MY018_DIALUP_BITRATE"] = values["RETROMODEM_IRDA_DIALUP_BITRATE"]
    elif adapter == "ma620":
        values.update(RETROMODEM_ADAPTER=CHOICES[adapter], RETROMODEM_TRANSPORT="irda",
                      RETROMODEM_TTY="auto", RETROMODEM_DONGLE="ma600", RETROMODEM_USB_ID="0df7:0620")
        values["RETROMODEM_IRDA_BITRATE"] = existing.get("RETROMODEM_MA620_BITRATE",
            existing.get("RETROMODEM_IRDA_BITRATE", "9600") if existing.get("RETROMODEM_ADAPTER") == CHOICES[adapter] else "9600")
        values["RETROMODEM_IRDA_DIALUP_BITRATE"] = existing.get("RETROMODEM_MA620_DIALUP_BITRATE",
            existing.get("RETROMODEM_IRDA_DIALUP_BITRATE", "115200") if existing.get("RETROMODEM_ADAPTER") == CHOICES[adapter] else "115200")
        values["RETROMODEM_MA620_BITRATE"] = values["RETROMODEM_IRDA_BITRATE"]
        values["RETROMODEM_MA620_DIALUP_BITRATE"] = values["RETROMODEM_IRDA_DIALUP_BITRATE"]
    elif adapter == "serial":
        # Keep the infrared profile for later switching in the UI.
        values["RETROMODEM_TRANSPORT"] = "serial"
    else:
        raise ValueError("Unknown adapter")
    if values["RETROMODEM_IRDA_BITRATE"] not in {"9600", "19200", "38400", "57600", "115200"}:
        raise ValueError("Invalid infrared bitrate")
    # Once wired for controlled MY018, retain its boot support when using USB.
    # No GPIO/boot changes for fresh USB-only installations.
    use_my018 = values.get("RETROMODEM_MY018_POWER_CYCLE") == "1"
    files = [(config, "".join(f"{key}={shlex.quote(value)}\n" for key, value in sorted(values.items())), 0o600)]
    reboot = False
    if use_my018:
        boot = root / "boot/firmware"
        boot_config = boot / "config.txt"
        cmdline = boot / "cmdline.txt"
        if not boot_config.is_file() or not cmdline.is_file():
            raise ValueError("Missing /boot/firmware/config.txt or cmdline.txt; expected Bookworm boot layout")
        text = boot_config.read_text()
        include = "include retromodem-my018.txt"
        # Add at the end under [all], so old conditional sections cannot hide it.
        block = "\n[all]\n" + include + "\n"
        if not text.endswith(block):
            text += block
        original_cmdline = cmdline.read_text()
        tokens = original_cmdline.split()
        if len(original_cmdline.strip().splitlines()) != 1:
            raise ValueError("cmdline.txt must contain one command line")
        tokens = [part for part in tokens if not re.match(r"^console=(serial0|ttyAMA0|ttyS0)(,|$)", part)]
        files.extend([
            (boot_config, text, 0o644),
            (cmdline, " ".join(tokens) + "\n", 0o644),
            (boot / "retromodem-my018.txt", (PROJECT / "config/my018-boot.txt").read_text(), 0o644),
            (root / "etc/modprobe.d/retromodem-my018.conf", (PROJECT / "config/my018-power.conf").read_text(), 0o644),
        ])
        reboot = any(not path.exists() or path.read_text() != text for path, text, _ in files[1:])
    return adapter, files, reboot, use_my018


def apply_plan(root, adapter=None, confirmed=False):
    selected, files, reboot, use_my018 = plan(root, adapter, confirmed)
    # Validate all targets before writing, including unchanged boot files.
    for path, _, _ in files:
        if path.is_symlink():
            raise ValueError(f"Refusing symlink: {path}")
    for path, text, mode in files:
        if not path.exists() or path.read_text() != text:
            if path.exists():
                backup = path.with_name(path.name + ".pre-retromodem")
                if not backup.exists():
                    atomic_write(backup, path.read_text(), mode)
            atomic_write(path, text, mode)
    return reboot


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", choices=CHOICES)
    parser.add_argument("--my018-wiring-confirmed", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.apply:
            print(int(apply_plan(Path("/"), args.adapter, args.my018_wiring_confirmed)))
        else:
            selected, _, _, _ = plan(Path("/"), args.adapter, args.my018_wiring_confirmed)
            print(f"Adapter: {selected}")
    except (ValueError, OSError) as error:
        parser.exit(1, f"Configuration error: {error}\n")
