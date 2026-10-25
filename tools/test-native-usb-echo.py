#!/usr/bin/env python
# Copyright (C) 2026 Toit contributors.
"""Verify the USB echo fixture on Linux, including webOS's Python 2.7.

Uses only the standard library. Identify the board by USB serial, then use
its discovered persistent link if available. Does not flash or reset it.
"""
from __future__ import print_function

import array
import fcntl
import glob
import hashlib
import json
import os
import select
import sys
import termios
import time


def read_text(path):
    with open(path) as source:
        return source.read().strip().strip('\0')


def identify(serial_number):
    devices = []
    for path in glob.glob('/sys/bus/usb/devices/*'):
        try:
            if (read_text(path + '/serial') == serial_number
                    and read_text(path + '/idVendor') == '303a'
                    and read_text(path + '/idProduct') == '1001'):
                devices.append(os.path.realpath(path))
        except IOError:
            continue
    if len(devices) != 1:
        raise RuntimeError('Expected one matching ESP32-S3, found %d' % len(devices))
    ports = []
    for path in glob.glob('/sys/class/tty/ttyACM*'):
        interface = os.path.realpath(path + '/device')
        if interface.startswith(devices[0] + os.sep):
            ports.append('/dev/' + os.path.basename(path))
    if len(ports) != 1:
        raise RuntimeError('Expected one CDC serial port, found %d' % len(ports))
    node = ports[0]
    links = [link for link in glob.glob('/dev/serial/by-id/*')
             if os.path.realpath(link) == node]
    return (sorted(links)[0] if links else node), devices[0]


def main():
    if (len(sys.argv) not in (3, 4) or sys.argv[1] != '--serial'
            or (len(sys.argv) == 4 and sys.argv[3] != '--framed')):
        raise RuntimeError('Usage: test-native-usb-echo.py --serial VERIFIED_USB_SERIAL [--framed]')
    serial_number = sys.argv[2]
    framed = len(sys.argv) == 4
    port, usb_path = identify(serial_number)
    clock = getattr(time, 'monotonic', time.time)
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    original = None
    modem = None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = termios.tcgetattr(fd)
        raw = termios.tcgetattr(fd)
        raw[0] = 0
        raw[1] = 0
        raw[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB
                    | getattr(termios, 'CRTSCTS', 0))
        raw[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
        raw[3] = 0
        raw[4] = raw[5] = termios.B115200
        raw[6][termios.VMIN] = 0
        raw[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, raw)
        modem = array.array('I', [0])
        fcntl.ioctl(fd, termios.TIOCMGET, modem, True)
        active = array.array('I', [(modem[0] | termios.TIOCM_DTR) & ~termios.TIOCM_RTS])
        fcntl.ioctl(fd, termios.TIOCMSET, active)
        time.sleep(0.2)
        termios.tcflush(fd, termios.TCIOFLUSH)
        transmitted = hashlib.sha256()
        received = hashlib.sha256()
        start = clock()
        overall_deadline = start + 30
        for block in range(128):
            payload = os.urandom(1024)
            wire = b'Ech\x03\xff\xa9' + payload if framed else payload
            deadline = min(clock() + 2, overall_deadline)
            sent = 0
            while sent < len(wire):
                remaining = deadline - clock()
                if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                    raise RuntimeError('Write timeout at block %d' % block)
                count = os.write(fd, wire[sent:])
                if count <= 0:
                    raise RuntimeError('Write failed at block %d' % block)
                sent += count
            reply = b''
            while len(reply) < len(payload):
                remaining = deadline - clock()
                if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
                    raise RuntimeError('Read timeout at block %d: %d bytes' % (block, len(reply)))
                part = os.read(fd, len(payload) - len(reply))
                if not part:
                    raise RuntimeError('Device disconnected at block %d' % block)
                reply += part
            if reply != payload:
                raise RuntimeError('Echo mismatch at block %d' % block)
            transmitted.update(payload)
            received.update(reply)
        elapsed = clock() - start
        print(json.dumps({
            'result': 'PASS', 'serial': serial_number, 'port': port,
            'protocol': 'Ech' if framed else 'raw',
            'usbSysfsPath': usb_path, 'bytesEchoedExactly': 131072,
            'elapsedSeconds': elapsed, 'payloadKiBPerSecond': 128 / elapsed,
            'sentSha256': transmitted.hexdigest(), 'receivedSha256': received.hexdigest(),
            'note': 'Request/reply payload rate, not maximum one-way streaming throughput',
        }, indent=2))
    finally:
        try:
            if modem is not None:
                fcntl.ioctl(fd, termios.TIOCMSET, modem)
        finally:
            try:
                if original is not None:
                    termios.tcsetattr(fd, termios.TCSANOW, original)
            finally:
                os.close(fd)


if __name__ == '__main__':
    try:
        main()
    except (IOError, OSError, RuntimeError, termios.error) as error:
        print('FAIL: %s' % error, file=sys.stderr)
        sys.exit(1)
