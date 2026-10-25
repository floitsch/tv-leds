#!/usr/bin/env python3
# Copyright (C) 2026 Toit contributors.
"""Verify black-bar handling through Chromecast HDMI and the live TV pipeline.

Requires the patterns APK, ADB access, websocket-client, and configured
TV SSH access. Displays test patterns briefly, restores the detector's runtime
state, and exits to the Chromecast home screen. Saves measured LED colours.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time

import ambient

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "build/lg-root/black-bars"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial", help="Connected Chromecast ADB address")
    args = parser.parse_args()
    adb = os.environ.get("ADB", str(Path.home() / "Android/Sdk/platform-tools/adb"))

    def android(*command):
        subprocess.run([adb, "-s", args.serial, "shell", *command],
                       check=True, capture_output=True, text=True, timeout=15)

    layout = json.loads((ROOT / "config/led-layout.json").read_text())
    groups = {}
    start = 0
    for side in ("left", "top", "right", "bottom"):
        end = start + layout["sideCounts"][side]
        groups[side] = range(start, end)
        start = end
    count = start

    def dark(rgb):
        return max(rgb) <= 8

    def color(name, rgb):
        r, g, b = rgb
        if name == "green":
            return g > 100 and g > max(r, b) * 1.5
        if name == "magenta":
            return min(r, b) > 50 and g < min(r, b) * .8
        if name == "cyan":
            return min(g, b) > 50 and r < min(g, b) * .8
        if name == "red":
            return r > 80 and r > max(g, b) * 1.5
        raise ValueError(name)

    def all_color(name):
        return lambda leds: all(color(name, rgb) for rgb in leds)

    def dark_sides(*sides):
        return lambda leds: all(dark(leds[i]) for side in sides for i in groups[side])

    OUTPUT.mkdir(parents=True, exist_ok=True)
    tunnel = ambient.ensure_tunnel()
    client = None
    original_enabled = None
    results = []
    try:
        client = ambient.Client()
        info = client.request(command="serverinfo")["info"]
        original_enabled = next(c["enabled"] for c in info["components"]
                                if c["name"] == "BLACKBORDER")
        client.request(command="ledcolors", subcommand="ledstream-start")

        def check(label, mode, enabled, predicate, minimum_seconds=.8):
            if enabled is not None:
                client.request(command="componentstate", componentstate={
                    "component": "BLACKBORDER", "state": enabled})
            android("am", "start", "-n", "org.toit.tvleds/.PatternActivity",
                    "--es", "mode", mode)
            started = time.monotonic()
            stable = 0
            leds = []
            passed = False
            while time.monotonic() - started < 12:
                message = client.connection.recv()
                if isinstance(message, bytes):
                    continue
                message = json.loads(message)
                if message.get("command") != "ledcolors-ledstream-update":
                    continue
                values = message["result"]["leds"]
                leds = [values[i:i + 3] for i in range(0, len(values), 3)]
                matched = len(leds) == count and predicate(leds)
                stable = stable + 1 if matched else 0
                if stable >= 5 and time.monotonic() - started >= minimum_seconds:
                    passed = True
                    break
            elapsed = time.monotonic() - started
            result = dict(label=label, mode=mode, detectorEnabled=enabled,
                          passed=passed, observedSeconds=elapsed, leds=leds)
            results.append(result)
            (OUTPUT / "results.json").write_text(json.dumps(results, indent=2) + "\n")
            print(f"{'PASS' if passed else 'FAIL'}: {label} ({elapsed:.2f}s)", flush=True)
            if not passed:
                raise RuntimeError(label)

        check("letterbox baseline: top and bottom sample black bars", "letterbox", False,
              lambda leds: dark_sides("top", "bottom")(leds)
              and any(color("green", leds[i]) for i in groups["left"]))
        check("letterbox: every edge samples the green active picture", "letterbox", True,
              all_color("green"))
        check("subtitle-like overlay inside bottom bar does not change the crop", "letterbox-osd", None,
              all_color("green"), minimum_seconds=4)
        check("automatic change to 4:3 pillarbox", "pillarbox", None, all_color("magenta"))
        check("pillarbox baseline: left and right sample black bars", "pillarbox", False,
              lambda leds: dark_sides("left", "right")(leds)
              and any(color("magenta", leds[i]) for i in groups["top"]))
        check("pillarbox: every edge samples the magenta active picture", "pillarbox", True,
              all_color("magenta"))
        check("bars on both axes: every edge samples cyan", "windowbox", None, all_color("cyan"))
        check("windowbox baseline: all edges sample black bars", "windowbox", False,
              lambda leds: all(dark(rgb) for rgb in leds))
        check("windowbox: active picture restored", "windowbox", True, all_color("cyan"))
        check("a black frame stays black", "black", None,
              lambda leds: all(dark(rgb) for rgb in leds))
        check("return to full frame: red outer edges, no stale crop", "fullframe-edges", None,
              all_color("red"))
    finally:
        try:
            if client and original_enabled is not None:
                client.request(command="componentstate", componentstate={
                    "component": "BLACKBORDER", "state": original_enabled})
        finally:
            if client:
                client.close()
            if tunnel:
                tunnel.terminate()
                tunnel.wait(timeout=5)
            android("input", "keyevent", "KEYCODE_HOME")


if __name__ == "__main__":
    main()
