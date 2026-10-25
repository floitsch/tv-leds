#!/usr/bin/env python
# Copyright (C) 2026 Toit contributors.
"""Temporary loopback-only USB serial bridge and ESP32-S3 reset helper.

Compatible with the TV's minimal Python 2.7. Use an SSH local forward; the
bridge exposes no LAN listener. Reset sequences follow esptool's USB Serial/
JTAG strategy, not a USB-UART adapter's reset circuit.
"""
from __future__ import print_function

import array
import fcntl
import glob
import json
import os
import select
import socket
import sys
import termios
import time


def text_file(path):
    with open(path) as source:
        return source.read().strip().strip('\0')


def identify(serial_number):
    devices = []
    for path in glob.glob('/sys/bus/usb/devices/*'):
        try:
            if (text_file(path + '/serial') == serial_number
                    and text_file(path + '/idVendor') == '303a'
                    and text_file(path + '/idProduct') == '1001'):
                devices.append(os.path.realpath(path))
        except IOError:
            pass
    if len(devices) != 1:
        raise RuntimeError('Expected one matching ESP32-S3, found %d' % len(devices))
    nodes = [p for p in glob.glob('/sys/class/tty/ttyACM*')
             if os.path.realpath(p + '/device').startswith(devices[0] + os.sep)]
    if len(nodes) != 1:
        raise RuntimeError('Expected one matching CDC interface, found %d' % len(nodes))
    node = '/dev/' + os.path.basename(nodes[0])
    links = sorted(p for p in glob.glob('/dev/serial/by-id/*') if os.path.realpath(p) == node)
    return links[0] if links else node


def open_port(serial_number):
    port = identify(serial_number)
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        settings = termios.tcgetattr(fd)
        settings[0] = settings[1] = settings[3] = 0
        settings[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB
                         | termios.HUPCL | getattr(termios, 'CRTSCTS', 0))
        settings[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
        settings[4] = settings[5] = termios.B115200
        settings[6][termios.VMIN] = settings[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, settings)
    except BaseException:
        os.close(fd)
        raise
    return fd, port


def reset(serial_number, bootloader):
    fd, port = open_port(serial_number)
    try:
        state = array.array('I', [0])
        fcntl.ioctl(fd, termios.TIOCMGET, state, True)

        def set_line(bit, level):
            state[0] = (state[0] | bit) if level else (state[0] & ~bit)
            fcntl.ioctl(fd, termios.TIOCMSET, state)

        if bootloader:
            set_line(termios.TIOCM_RTS, False)
            set_line(termios.TIOCM_DTR, False)
            time.sleep(0.1)
            set_line(termios.TIOCM_DTR, True)
            set_line(termios.TIOCM_RTS, False)
            time.sleep(0.1)
            set_line(termios.TIOCM_RTS, True)
            set_line(termios.TIOCM_DTR, False)
            set_line(termios.TIOCM_RTS, True)
            time.sleep(0.1)
            set_line(termios.TIOCM_DTR, False)
            set_line(termios.TIOCM_RTS, False)
        else:
            set_line(termios.TIOCM_DTR, False)
            set_line(termios.TIOCM_RTS, True)
            time.sleep(0.2)
            set_line(termios.TIOCM_RTS, False)
            time.sleep(0.2)
        print(json.dumps({'reset': 'bootloader' if bootloader else 'run', 'port': port}))
    finally:
        os.close(fd)


def bridge(serial_number):
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 19021))
    listener.listen(1)
    listener.settimeout(10)
    deadline = time.time() + 300
    print('Listening on TV loopback 127.0.0.1:19021')
    sys.stdout.flush()
    try:
        while time.time() < deadline:
            try:
                client, address = listener.accept()
            except socket.timeout:
                continue
            fd = None
            try:
                client.settimeout(5)
                fd, port = open_port(serial_number)
                print('Connected: ' + port)
                sys.stdout.flush()
                while time.time() < deadline:
                    ready = select.select([fd, client], [], [], 1)[0]
                    if fd in ready:
                        data = os.read(fd, 4096)
                        if not data:
                            raise RuntimeError('Serial device disconnected')
                        client.sendall(data)
                    if client in ready:
                        data = client.recv(4096)
                        if not data:
                            break
                        sent = 0
                        write_deadline = time.time() + 5
                        while sent < len(data):
                            remaining = write_deadline - time.time()
                            if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                                raise RuntimeError('Serial write timeout')
                            sent += os.write(fd, data[sent:])
            except (IOError, OSError, RuntimeError, socket.error) as error:
                print('Connection ended: ' + str(error))
                sys.stdout.flush()
            finally:
                if fd is not None:
                    os.close(fd)
                client.close()
    finally:
        listener.close()


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[2] not in ('bridge', 'bootloader', 'run'):
        sys.exit('Usage: tv-serial-bridge.py VERIFIED_USB_SERIAL bridge|bootloader|run')
    if sys.argv[2] == 'bridge':
        bridge(sys.argv[1])
    else:
        reset(sys.argv[1], sys.argv[2] == 'bootloader')
