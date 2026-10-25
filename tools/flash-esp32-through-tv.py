#!/usr/bin/env python3
# Copyright (C) 2026 Toit contributors.
"""Flash an application partition through the TV's verified USB interface.

Stop ambient.py before running this helper and restart it afterwards. The
input must be an app partition for the existing partition table, not a full
flash image. The original board backup is never overwritten.
"""

import argparse
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time
import sys

from tv_config import load_connection

ROOT = Path(__file__).resolve().parent.parent
REMOTE_HELPER = "/tmp/tv-leds-serial/tv-serial-bridge.py"
CLEANUP = """python - <<'PY'
import glob,os,signal
for directory in glob.glob('/proc/[0-9]*'):
    try:
        with open(directory+'/cmdline','rb') as source:
            command=source.read().split(chr(0))
        if '/tmp/tv-leds-serial/tv-serial-bridge.py' in command and 'bridge' in command:
            os.kill(int(directory.rsplit('/',1)[1]),signal.SIGTERM)
    except (IOError,OSError):
        pass
PY
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("application", type=Path)
    args = parser.parse_args()
    application = args.application.resolve(strict=True)
    config = load_connection()
    ssh = [
        "ssh", "-i", config["identityFile"],
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=" + config["knownHostsFile"],
        "-o", "ConnectTimeout=5", "-o", "LogLevel=ERROR",
    ]
    target = config["user"] + "@" + config["host"]

    def remote(script):
        # Feed scripts through stdin, including the final heredoc newline.
        subprocess.run(ssh + [target, "sh", "-s"], input=script + "\n",
                       text=True, check=True, timeout=25)

    remote("mkdir -p /tmp/tv-leds-serial")
    subprocess.run(["scp", "-O", *ssh[1:],
                    str(ROOT / "tools/tv-serial-bridge.py"),
                    target + ":" + REMOTE_HELPER], check=True, timeout=20)
    remote(CLEANUP)
    bridge = shlex.join(["python", REMOTE_HELPER, config["espUsbSerial"]])
    tunnel = None
    try:
        remote(bridge + " bootloader")
        remote("nohup " + bridge + " bridge >/tmp/tv-leds-serial/bridge.log"
               " 2>&1 </dev/null &")
        tunnel = subprocess.Popen(ssh + [
            "-N", "-o", "ExitOnForwardFailure=yes",
            "-L", "127.0.0.1:18091:127.0.0.1:19021", target,
        ])
        deadline = time.monotonic() + 6
        while True:
            if tunnel.poll() is not None:
                raise RuntimeError("SSH forwarding failed")
            try:
                with socket.create_connection(("127.0.0.1", 18091), timeout=.2):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("SSH forwarding did not become ready")
                time.sleep(.2)
        python = os.environ.get(
            "ESPTOOL_PYTHON",
            sys.executable,
        )
        subprocess.run([
            python, "-m", "esptool", "--chip", "esp32s3",
            "--port", "socket://127.0.0.1:18091", "--before", "no_reset",
            "--after", "no_reset", "write_flash", "--flash_mode", "keep",
            "--flash_freq", "keep", "--flash_size", "keep",
            "0x10000", str(application),
        ], check=True, timeout=100)
        remote(bridge + " run")
    finally:
        if tunnel:
            tunnel.terminate()
            tunnel.wait(timeout=5)
        remote(CLEANUP)


if __name__ == "__main__":
    main()
