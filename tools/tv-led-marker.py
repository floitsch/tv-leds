#!/usr/bin/env python3
# Copyright (C) 2026 Toit contributors.
"""Show LED markers using the current-limited ESP32 receiver on the TV."""
import argparse
from pathlib import Path
import struct
import subprocess

from tv_config import load_connection


def packet(count, indices, color, markers=None):
    channels = {'red': (255, 0, 0, 0), 'green': (0, 255, 0, 0),
                'blue': (0, 0, 255, 0), 'white': (0, 0, 0, 255),
                'black': (0, 0, 0, 0)}
    data = bytearray(count * 4)
    assignments = dict.fromkeys(indices, color)
    assignments.update(markers or {})
    for index, selected_color in assignments.items():
        data[index * 4:index * 4 + 4] = bytes(channels[selected_color])
    first = second = extended = 0
    for i, value in enumerate(data):
        first = (first + value) % 255
        second = (second + first) % 255
        extended = (extended + (value ^ (i & 255))) % 255
    header = struct.pack('>H', count - 1)
    return (b'AWa' + header + bytes([header[0] ^ header[1] ^ 0x55]) + data
            + bytes([first, second, 0xaa if extended == 0x41 else extended]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count', type=int, default=512, help='Pixels transmitted, including unused trailing pixels')
    parser.add_argument('--index', type=int, nargs='+', help='Zero-based marker indices')
    parser.add_argument('--marker', action='append', default=[], help='Individual INDEX:COLOR marker; may be repeated')
    parser.add_argument('--color', choices=['red', 'green', 'blue', 'white', 'black'], default='red')
    parser.add_argument('--seconds', type=float, default=20, help='Duration, or 0 to run until stopped')
    args = parser.parse_args()
    markers = {}
    for value in args.marker:
        try:
            index, selected_color = value.split(':')
            index = int(index)
            if selected_color not in ('red', 'green', 'blue', 'white', 'black'):
                raise ValueError('Unknown colour')
            markers[index] = selected_color
        except ValueError:
            parser.error('Each marker must be INDEX:red|green|blue|white|black')
    indices = args.index if args.index is not None else ([] if markers else [0])
    if not 1 <= args.count <= 512 or any(i < 0 or i >= args.count for i in indices + list(markers)):
        parser.error('Count must be 1..512 and marker indices must be inside that count')
    if args.seconds != 0 and not 1 <= args.seconds <= 300:
        parser.error('Duration must be 1..300 seconds, or 0 to run until stopped')
    root = Path(__file__).resolve().parent.parent
    source = (root / 'tools/test-native-usb-echo.py').read_text().split("if __name__ == '__main__':")[0]
    source += '\nwire = ' + repr(packet(args.count, indices, args.color, markers))
    source += '\nblack = ' + repr(packet(args.count, [], args.color))
    source += '\nduration = ' + repr(args.seconds)
    source += '\nserial_number = ' + repr(load_connection()['espUsbSerial']) + '\n'
    source += '''
port, path = identify(serial_number)
fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
original = termios.tcgetattr(fd)
try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    raw = termios.tcgetattr(fd)
    raw[0] = raw[1] = raw[3] = 0
    raw[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | getattr(termios, 'CRTSCTS', 0))
    raw[2] |= termios.CS8 | termios.CREAD | termios.CLOCAL
    raw[4] = raw[5] = termios.B115200
    raw[6][termios.VMIN] = raw[6][termios.VTIME] = 0
    termios.tcsetattr(fd, termios.TCSANOW, raw)
    bits = array.array('I', [termios.TIOCM_DTR])
    fcntl.ioctl(fd, termios.TIOCMSET, bits)
    def send(data):
        sent = 0
        deadline = time.time() + 3
        while sent < len(data):
            remaining = deadline - time.time()
            if remaining <= 0 or not select.select([], [fd], [], remaining)[1]:
                raise RuntimeError('Marker write timeout')
            sent += os.write(fd, data[sent:sent + 64])
            time.sleep(0.002)
    try:
        end = time.time() + duration
        while duration == 0 or time.time() < end:
            send(wire)
            time.sleep(0.12)
    except KeyboardInterrupt:
        pass
    finally:
        send(black)
finally:
    termios.tcsetattr(fd, termios.TCSANOW, original)
    os.close(fd)
print('Marker finished; blackout sent.')
'''
    assignments = dict.fromkeys(indices, args.color)
    assignments.update(markers)
    duration_label = f'for {args.seconds:g}s' if args.seconds else 'until stopped'
    print(f"Showing {assignments} {duration_label}; firmware applies its estimated current limit.", flush=True)
    remote_command = f'timeout -t {int(args.seconds) + 10} python -' if args.seconds else 'python -'
    subprocess.run(['python3', str(root / 'tools/tv-ssh.py'),
                    remote_command], input=source.encode(),
                   timeout=args.seconds + 12 if args.seconds else None, check=True)


if __name__ == '__main__':
    main()
