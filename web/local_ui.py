"""Read the appliance language on each request, including after settings changes."""
import os
import shlex
from pathlib import Path

CONFIG = Path('/etc/retromodem/retromodem.env')


def language():
    value = os.environ.get('RETROMODEM_LANGUAGE', 'en')
    try:
        for line in CONFIG.read_text(encoding='utf-8').splitlines():
            key, separator, raw = line.partition('=')
            if separator and key.strip() == 'RETROMODEM_LANGUAGE':
                parsed = shlex.split(raw, comments=True)
                value = parsed[0] if parsed else 'en'
    except (OSError, ValueError):
        pass
    return 'en' if value == 'en' else 'nl'


def tr(lang, nl, en):
    return en if lang == 'en' else nl
