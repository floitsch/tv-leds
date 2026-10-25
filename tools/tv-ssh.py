#!/usr/bin/env python3
# Copyright (C) 2026 Toit contributors.
"""Connect to the configured LG TV; read a shell script from stdin by default."""
import subprocess
import sys

from tv_config import load_connection

config = load_connection()
arguments = sys.argv[1:]
terminal = arguments[:1] == ["--tty"]
if terminal:
    arguments = arguments[1:]
command = [
    "ssh", "-i", config["identityFile"],
    "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
    "-o", "StrictHostKeyChecking=yes",
    "-o", "UserKnownHostsFile=" + config["knownHostsFile"],
    "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR",
    config["user"] + "@" + config["host"],
]
if terminal:
    command.insert(1, "-tt")
command += arguments or ["sh", "-s"]
sys.exit(subprocess.call(command))
