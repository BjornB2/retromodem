#!/usr/bin/env python3
"""Match the pinned upstream DKMS module inventory to the target kernel config."""
import argparse
from pathlib import Path
import re
import shlex

FIELDS = ("BUILT_MODULE_NAME", "BUILT_MODULE_LOCATION", "DEST_MODULE_LOCATION")
GUARDS = {
    **{name: "CONFIG_ISA_DMA_API" for name in
       ("nsc-ircc", "w83977af_ir", "smsc-ircc2", "ali-ircc", "via-ircc")},
    "vlsi_ir": "CONFIG_PCI",
    **{name: "CONFIG_USB" for name in
       ("irda-usb", "stir4200", "mcs7780", "kingsun-sir", "ksdazzle-sir", "ks959-sir")},
    **{name: "CONFIG_TTY" for name in
       ("irtty-sir", "sir-dev", "esi-sir", "tekram-sir", "actisys-sir", "litelink-sir",
        "girbil-sir", "old_belkin-sir", "mcp2120-sir", "act200l-sir", "ma600-sir", "toim3232-sir")},
}
REQUIRED = {"irda", "ircomm", "ircomm-tty", "irtty-sir", "sir-dev", "ma600-sir"}


def filter_modules(text, kernel_config):
    enabled = set(re.findall(r"^(CONFIG_[A-Z0-9_]+)=[ym]$", kernel_config, re.M))
    pattern = re.compile(r"^(BUILT_MODULE_NAME|BUILT_MODULE_LOCATION|DEST_MODULE_LOCATION)\[(\d+)\]=(.*)$")
    entries = {}
    for line in text.splitlines():
        match = pattern.fullmatch(line)
        if match:
            field, index, value = match.groups()
            parts = shlex.split(value)
            if len(parts) != 1 or field in entries.setdefault(int(index), {}):
                raise ValueError("Malformed/duplicate DKMS array entry")
            entries[int(index)][field] = parts[0]
    kept, skipped = [], []
    for _, entry in sorted(entries.items()):
        if set(entry) != set(FIELDS):
            raise ValueError("Incomplete DKMS module entry")
        name = entry["BUILT_MODULE_NAME"]
        if name in GUARDS and GUARDS[name] not in enabled:
            skipped.append(name)
        else:
            kept.append(entry)
    if not REQUIRED.issubset({entry["BUILT_MODULE_NAME"] for entry in kept}):
        raise ValueError("Kernel/DKMS inventory lacks required IrDA, MY018 or MA-620 modules")
    output = []
    inserted = False
    for line in text.splitlines():
        if pattern.fullmatch(line):
            if not inserted:
                for index, entry in enumerate(kept):
                    output.extend(f'{field}[{index}]="{entry[field]}"' for field in FIELDS)
                inserted = True
        else:
            output.append(line)
    return "\n".join(output) + "\n", skipped


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dkms_conf", type=Path)
    parser.add_argument("kernel_config", type=Path)
    args = parser.parse_args()
    try:
        output, skipped = filter_modules(args.dkms_conf.read_text(), args.kernel_config.read_text())
        args.dkms_conf.write_text(output)
        print("DKMS: skipped modules disabled by target kernel: " + (", ".join(skipped) or "none"))
    except (OSError, ValueError) as error:
        parser.exit(1, f"DKMS configuration error: {error}\n")
