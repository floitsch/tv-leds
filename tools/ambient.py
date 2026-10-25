#!/usr/bin/env python3
# Copyright (C) 2026 Toit contributors.
"""Start, stop, or inspect the TV-to-USB ambient-light setup.

Requires websocket-client and the configured root SSH connection. The start
command resolves the board by USB serial each time and applies the saved
two-axis black-bar detector. RGB input keeps the white channel off.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time

import websocket

from tv_config import load_connection

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / 'build/lg-root/ambient'


def ssh(command, *, tty=False, source=None):
    result = subprocess.run(
        ['python3', str(ROOT / 'tools/tv-ssh.py')]
        + (['--tty'] if tty else []) + [command],
        input=source, capture_output=True, text=True, check=True, timeout=20)
    return result.stdout


def luna(service, method, params=None):
    command = shlex.join(['luna-send', '-w', '8000', '-n', '1', '-f',
                         'luna://' + service + '/' + method, json.dumps(params or {})])
    return json.loads(ssh(command, tty=True))


def prepare_port():
    source = (ROOT / 'tools/test-native-usb-echo.py').read_text().split("if __name__ == '__main__':")[0]
    source += '\nserial_number = ' + repr(load_connection()['espUsbSerial']) + '\n'
    source += '''
import signal
port, path = identify(serial_number)
port = os.path.realpath(port)
stopped = []
for directory in glob.glob('/proc/[0-9]*'):
    try:
        with open(directory + '/cmdline', 'rb') as f:
            command = f.read().split('\\0')
        if command[:2] != ['python', '-']: continue
        if not any(os.readlink(fd) == port for fd in glob.glob(directory + '/fd/*')): continue
        pid = int(directory.rsplit('/', 1)[1])
        os.kill(pid, signal.SIGINT)
        stopped.append(pid)
    except (IOError, OSError): pass
deadline = time.time() + 4
while any(os.path.exists('/proc/' + str(pid)) for pid in stopped):
    if time.time() >= deadline: raise RuntimeError('Previous marker did not stop')
    time.sleep(0.05)
print(json.dumps({'port': port, 'stoppedMarkers': stopped}))
'''
    return json.loads(ssh('timeout -t 10 python -', source=source))['port']


def ensure_tunnel():
    try:
        with socket.create_connection(('127.0.0.1', 18090), timeout=1):
            return None
    except OSError:
        pass
    connection = load_connection()
    with (OUTPUT / 'tunnel.log').open('ab') as log:
        process = subprocess.Popen([
            'ssh', '-i', connection['identityFile'], '-o', 'IdentitiesOnly=yes',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
            '-o', 'UserKnownHostsFile=' + connection['knownHostsFile'],
            '-o', 'LogLevel=ERROR', '-o', 'ExitOnForwardFailure=yes', '-N',
            '-L', '127.0.0.1:18090:127.0.0.1:8090',
            connection['user'] + '@' + connection['host']],
            stdin=subprocess.DEVNULL, stdout=log, stderr=log)
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError('SSH tunnel failed; see build/lg-root/ambient/tunnel.log')
        try:
            with socket.create_connection(('127.0.0.1', 18090), timeout=.2):
                return process
        except OSError:
            time.sleep(.1)
    process.terminate()
    process.wait(timeout=5)
    raise RuntimeError('SSH tunnel did not become available')


class Client:
    def __init__(self):
        self.connection = websocket.create_connection('ws://127.0.0.1:18090/', timeout=8)
        self.transaction = 0
        self.request(command='authorize', subcommand='login',
                     password=os.environ.get('HYPERHDR_PASSWORD', 'hyperhdr'))

    def request(self, **body):
        self.transaction += 1
        self.connection.send(json.dumps(dict(body, tan=self.transaction)))
        while True:
            message = self.connection.recv()
            if isinstance(message, bytes):
                continue
            response = json.loads(message)
            if response.get('tan') == self.transaction:
                if response.get('success') is False:
                    raise RuntimeError(response.get('error', 'HyperHDR request failed'))
                return response

    def close(self):
        self.connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['start', 'stop', 'status'], nargs='?', default='start')
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    port = prepare_port() if args.command == 'start' else None
    loader = 'org.webosbrew.hyperhdr.loader.service'
    capture = 'org.webosbrew.piccap.service'
    if not luna(loader, 'status').get('running'):
        if args.command != 'start':
            print(json.dumps({'hyperhdrRunning': False}))
            return
        luna(loader, 'start')
    tunnel = ensure_tunnel()
    client = None
    try:
        client = Client()
        if args.command == 'start':
            response = client.request(command='config', subcommand='getconfig')
            stamp = time.strftime('%Y%m%d-%H%M%S')
            (OUTPUT / ('backup-' + stamp + '.json')).write_text(json.dumps(response, indent=2) + '\n')
            config = response['info']
            config = config.get('config', config)
            layout = json.loads((ROOT / 'config/led-layout.json').read_text())
            config['leds'] = layout['leds']
            config['device'] = json.loads((ROOT / 'config/ambient-device.json').read_text())
            config['device'].update(output=port, hardwareLedCount=len(layout['leds']))
            config['smoothing'].update(json.loads((ROOT / 'config/ambient-smoothing.json').read_text()))
            config['blackborderdetector'].update(json.loads((ROOT / 'config/ambient-blackbars.json').read_text()))
            client.request(command='config', subcommand='setconfig', config=config)
            client.request(command='componentstate', componentstate={'component': 'LEDDEVICE', 'state': True})
            client.request(command='componentstate', componentstate={
                'component': 'SMOOTHING', 'state': config['smoothing']['enable']})
            client.request(command='componentstate', componentstate={
                'component': 'BLACKBORDER', 'state': config['blackborderdetector']['enable']})
            settings = luna(capture, 'getSettings')
            settings.pop('returnValue', None)
            wanted = dict(address='127.0.0.1', port=19400, width=640, height=360,
                          fps=30, vsync=True, quirks=1, nogui=True, novideo=False, nv12=False)
            if any(settings.get(key) != value for key, value in wanted.items()):
                settings.update(wanted)
                luna(capture, 'setSettings', settings)
            if not luna(capture, 'status').get('isRunning'):
                luna(capture, 'start')
        elif args.command == 'stop':
            if luna(capture, 'status').get('isRunning'):
                luna(capture, 'stop')
            client.request(command='componentstate', componentstate={'component': 'LEDDEVICE', 'state': False})
        for _ in range(20):
            info = client.request(command='serverinfo')['info']
            state = luna(capture, 'status')
            enabled = any(c['name'] == 'LEDDEVICE' and c['enabled'] for c in info['components'])
            ready = enabled and state.get('connected')
            stopped = not enabled and not state.get('isRunning')
            if args.command == 'status' or (args.command == 'start' and ready) or (args.command == 'stop' and stopped):
                break
            time.sleep(.25)
        summary = {'deviceEnabled': enabled, 'captureRunning': state.get('isRunning'),
                   'captureConnected': state.get('connected'), 'priorities': info.get('priorities'),
                   'colorSmoothingEnabled': any(c['name'] == 'SMOOTHING' and c['enabled']
                                                for c in info['components']),
                   'blackBarDetectionEnabled': any(c['name'] == 'BLACKBORDER' and c['enabled']
                                                   for c in info['components'])}
        if port:
            summary.update(serialPort=port, ledCount=len(layout['leds']))
        (OUTPUT / 'state.json').write_text(json.dumps(summary, indent=2) + '\n')
        print(json.dumps(summary, indent=2))
        if args.command == 'start' and not (enabled and state.get('connected')):
            raise RuntimeError('Ambient lighting did not become ready; inspect the TV services and HyperHDR logs')
    finally:
        if client:
            client.close()
        if tunnel:
            tunnel.terminate()
            tunnel.wait(timeout=5)


if __name__ == '__main__':
    main()
