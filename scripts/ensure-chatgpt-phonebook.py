#!/usr/bin/python3
"""Install or migrate the reserved ChatGPT number without replacing user entries."""

import json
import os
import tempfile
from pathlib import Path

path = Path("/etc/retromodem/phonebook.json")
document = json.loads(path.read_text(encoding="utf-8"))
entries = document.setdefault("entries", [])
reserved = next((item for item in entries
                 if str(item.get("host")) == "127.0.0.1"
                 and int(item.get("port", 0)) == 2324), None)
target = next((item for item in entries if str(item.get("number")) == "5559999"), None)
changed = False
if reserved is not None and (target is None or target is reserved):
    reserved.update({
        "number": "5559999", "label": "ChatGPT BBS", "kind": "chatgpt",
        "host": "127.0.0.1", "port": 2324,
    })
    changed = True
elif reserved is None and target is None:
    entries.append({
        "number": "5559999", "label": "ChatGPT BBS", "kind": "chatgpt",
        "host": "127.0.0.1", "port": 2324,
    })
    changed = True

if changed:
    entries.sort(key=lambda item: str(item.get("number", "")))
    fd, temporary = tempfile.mkstemp(prefix="phonebook.json.", dir=path.parent, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(document, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
