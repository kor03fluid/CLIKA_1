"""USB NDJSON -> local HTTP ingest. Run from project root."""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class LineBuffer:
    def __init__(self, limit):
        self.limit = limit
        self.buffer = bytearray()
        self.discarding = False

    def feed(self, data):
        lines = []
        for byte in data:
            if byte == 10:
                if not self.discarding:
                    lines.append(bytes(self.buffer).rstrip(b'\r'))
                self.buffer.clear()
                self.discarding = False
            elif not self.discarding:
                self.buffer.append(byte)
                if len(self.buffer) > self.limit:
                    print('SKIP: line exceeds configured limit', file=sys.stderr)
                    self.buffer.clear()
                    self.discarding = True
        return lines

def forward(raw, url, timeout):
    if not raw.strip():
        return
    try:
        packet = json.loads(raw.decode('utf-8'))
        if not isinstance(packet, dict):
            raise ValueError('JSON object required')
    except (UnicodeDecodeError, ValueError) as error:
        print(f'SKIP: invalid NDJSON: {error}', file=sys.stderr)
        return
    request = urllib.request.Request(url, data=json.dumps(packet).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.load(response)
        print(json.dumps({'node': packet.get('node_id'), 'seq': packet.get('seq'), **result}), flush=True)
    except urllib.error.HTTPError as error:
        print(f'REJECT {error.code}: {error.read().decode("utf-8", errors="replace")}', file=sys.stderr, flush=True)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        # No delayed replay: fresh packets will arrive next heartbeat.
        print(f'HTTP FAILED (packet dropped): {error}', file=sys.stderr, flush=True)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--list', action='store_true', help='list available serial ports')
    parser.add_argument('--stdin', action='store_true', help='test without serial hardware')
    args = parser.parse_args()
    config = json.loads((ROOT / 'config/system.json').read_text(encoding='utf-8'))
    settings = config['serial']
    url = f"http://127.0.0.1:{config['server']['port']}/api/ingest"
    if args.stdin:
        framing = LineBuffer(settings['max_line_bytes'])
        while True:
            chunk = sys.stdin.buffer.read1(1024)
            if not chunk:
                break
            for raw in framing.feed(chunk):
                forward(raw, url, settings['http_timeout_seconds'])
        return
    try:
        import serial
        from serial.tools import list_ports
    except ImportError:
        raise SystemExit('Install first: python -m pip install pyserial')
    if args.list:
        for port in list_ports.comports():
            print(f'{port.device}: {port.description}')
        return
    if config['input']['driver'] != 'serial':
        raise SystemExit('Set input.driver to serial before reading USB (disables automatic mock nodes).')
    print(f"USB {settings['port']} @ {settings['baud_rate']} -> {url}", flush=True)
    try:
        while True:
            try:
                with serial.Serial(settings['port'], settings['baud_rate'], timeout=settings['read_timeout_seconds']) as connection:
                    # Opening USB may reboot some boards; wait for their next complete JSON line.
                    framing = LineBuffer(settings['max_line_bytes'])
                    print('USB OPEN', flush=True)
                    while True:
                        chunk = connection.read(min(max(connection.in_waiting, 1), 4096))
                        for raw in framing.feed(chunk):
                            forward(raw, url, settings['http_timeout_seconds'])
            except (serial.SerialException, OSError) as error:
                print(f'USB unavailable: {error}; retrying', file=sys.stderr, flush=True)
                time.sleep(settings['reconnect_seconds'])
    except KeyboardInterrupt:
        print('\nUSB bridge stopped')

if __name__ == '__main__':
    main()
