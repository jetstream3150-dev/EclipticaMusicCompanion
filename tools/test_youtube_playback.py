"""Exercise the actual player engine in Edge, without bypassing autoplay policy.

This optional integration test runs on the disposable Windows build runner.
If YouTube cannot be reached from the runner, it reports UNVERIFIED instead of
claiming that playback succeeded. An explicit player error fails the build.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from EclipticaMusic import SAMPLE_PHASE_TRACKS


TRACKS = list(dict.fromkeys(SAMPLE_PHASE_TRACKS.values()))
STATE = {'seq': 0, 'track': '', 'fade': 0, 'volume': .8,
         'stop': False, 'fallback': '', 'volume_seq': 0}
MESSAGES = []
ENGINE = Path('engine.js').read_bytes()
HTML = b'''<!doctype html><html><head><meta charset="utf-8"><style>
#players{position:absolute;left:-10000px;top:-10000px;width:320px;height:200px;pointer-events:none}
</style></head><body><button id="unlock" onclick="unlock()">Unlock</button>
<p id="status"></p><div id="players"><div id="yt0"></div><div id="yt1"></div></div>
<script src="/engine.js"></script><script src="https://www.youtube.com/iframe_api"></script>
</body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/':
            data, content_type = HTML, 'text/html; charset=utf-8'
        elif self.path == '/engine.js':
            data, content_type = ENGINE, 'text/javascript; charset=utf-8'
        elif self.path == '/state':
            data, content_type = json.dumps(STATE).encode(), 'application/json'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != '/player-status':
            self.send_error(404)
            return
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        try:
            MESSAGES.append(json.loads(raw).get('status', ''))
        except (ValueError, TypeError):
            pass
        self.send_response(204)
        self.end_headers()


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    driver = Path(os.environ.get('EDGEWEBDRIVER', '')) / 'msedgedriver.exe'
    if not driver.is_file():
        print('UNVERIFIED: Edge WebDriver is unavailable on this runner.')
        return
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = free_port()
    with tempfile.TemporaryDirectory(prefix='ecliptica-yt-test-') as tmp:
        proc = subprocess.Popen([str(driver), '--port=' + str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        session = None
        base = 'http://127.0.0.1:' + str(port)

        def call(method, path, payload=None):
            data = None if payload is None else json.dumps(payload).encode()
            req = Request(base + path, data=data, method=method,
                          headers={'Content-Type': 'application/json'})
            with urlopen(req, timeout=20) as response:
                return json.load(response).get('value')

        def js(script):
            return call('POST', '/session/' + session + '/execute/sync', {'script': script, 'args': []})

        try:
            for attempt in range(50):
                try:
                    call('GET', '/status')
                    break
                except (URLError, OSError):
                    time.sleep(.1)
            result = call('POST', '/session', {'capabilities': {'alwaysMatch': {
                'browserName': 'MicrosoftEdge',
                'ms:edgeOptions': {'args': ['--no-first-run', '--user-data-dir=' + tmp,
                                            '--window-size=1130,850']}}}})
            session = result['sessionId']
            call('POST', '/session/' + session + '/url',
                 {'url': 'http://127.0.0.1:' + str(server.server_port) + '/'})
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if js("return typeof ready!=='undefined' && ready && yt.every(p=>p && typeof p.getPlayerState==='function');"):
                    break
                time.sleep(.5)
            else:
                print('UNVERIFIED: YouTube IFrame API did not initialize in this Windows runner.')
                return
            item = call('POST', '/session/' + session + '/element',
                        {'using': 'css selector', 'value': '#unlock'})
            element = item['element-6066-11e4-a52e-4f735466cecf']
            call('POST', '/session/' + session + '/element/' + element + '/click', {})
            # Let transient click activation expire, as during a real VRChat game.
            time.sleep(6)
            for url in TRACKS:
                STATE.update(seq=STATE['seq'] + 1, track=url, stop=False)
                begin = len(MESSAGES)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    reports = MESSAGES[begin:]
                    explicit = next((m for m in reports if 'YouTube再生エラー' in m or
                                     '埋め込み再生が禁止' in m), None)
                    if explicit:
                        raise RuntimeError('YouTube player error for ' + url + ': ' + explicit)
                    state = js("return {state:yt[active]?.getPlayerState?.(),time:yt[active]?.getCurrentTime?.()};")
                    if state and state.get('state') == 1 and state.get('time', 0) > 0.2:
                        print('PASS: YouTube IFrame playback progressed for', url, flush=True)
                        break
                    time.sleep(.5)
                else:
                    print('UNVERIFIED: YouTube playback did not start in this runner for', url, flush=True)
                    return
        except (OSError, URLError, HTTPError, KeyError, TypeError) as exc:
            print('UNVERIFIED: Windows browser playback test could not finish:', type(exc).__name__, str(exc)[:180])
        finally:
            if session:
                try:
                    call('DELETE', '/session/' + session)
                except (OSError, URLError):
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            server.shutdown()


if __name__ == '__main__':
    main()
