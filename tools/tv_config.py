#!/usr/bin/env python3
# Copyright (C) 2026 Toit contributors.
"""Load machine-specific TV/USB identity settings from ignored local config."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_connection():
    path = ROOT / 'config/local.json'
    if not path.is_file():
        raise RuntimeError('Copy config/local.example.json to config/local.json and edit it first')
    config = json.loads(path.read_text())
    for field in ('host', 'user', 'identityFile', 'knownHostsFile', 'espUsbSerial'):
        if not isinstance(config.get(field), str) or not config[field].strip():
            raise ValueError('Missing or empty local setting: ' + field)
    if config['espUsbSerial'] == 'REPLACE_WITH_VERIFIED_USB_SERIAL':
        raise ValueError('Set espUsbSerial to the board identity discovered on the TV')
    for field in ('identityFile', 'knownHostsFile'):
        value = Path(config[field]).expanduser()
        config[field] = str(value if value.is_absolute() else ROOT / value)
    return config
