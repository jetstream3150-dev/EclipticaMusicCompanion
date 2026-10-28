"""Check YouTube's documented IFrame example on a Windows test runner.

This compares the app's player with a conventional visible player; it neither
downloads media nor alters browser security or autoplay settings.
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
from urllib.error import URLError
from urllib.request import Request, urlopen


HTML = b'''<!doctype html><html><head><meta charset="utf-8"></head>
<body><button id="play" onclick="player.playVideo()">Play</button>
<div id="player"></div><script>
var player, ready=false, errors=[];
function onYouTubeIframeAPIReady() {
  player = new YT.Player('player', {height:'200', width:'320',
    videoId:'M7lc1UVf-VE', playerVars:{playsinline:1},
    events:{onReady:function(){ready=true;},
      onError:function(e){errors.push(e.data);}}});
}
</script><script src="https://www.youtube.com/iframe_api"></script></body></html>'''


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path != '/':
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)


def main():
    driver = Path(os.environ.get('EDGEWEBDRIVER', '')) / 'msedgedriver.exe'
    if not driver.is_file():
        print('UNVERIFIED: Edge WebDriver is unavailable.')
        return
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='ecliptica-yt-standard-') as tmp:
        proc = subprocess.Popen([str(driver), '--port=' + str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = 'http://127.0.0.1:' + str(port)
        session = None

        def call(method, path, payload=None):
            data = None if payload is None else json.dumps(payload).encode()
            req = Request(base + path, data=data, method=method,
                          headers={'Content-Type': 'application/json'})
            with urlopen(req, timeout=20) as response:
                return json.load(response).get('value')

        def js(script):
            return call('POST', '/session/' + session + '/execute/sync', {'script': script, 'args': []})

        try:
            for _ in range(50):
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
                if js('return ready;'):
                    break
                time.sleep(.5)
            else:
                print('UNVERIFIED: official example player did not initialize.', flush=True)
                return
            button = call('POST', '/session/' + session + '/element',
                          {'using':'css selector','value':'#play'})
            eid = button['element-6066-11e4-a52e-4f735466cecf']
            call('POST', '/session/' + session + '/element/' + eid + '/click', {})
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                state = js('return {errors:errors,state:player.getPlayerState(),time:player.getCurrentTime()};')
                if state['errors']:
                    print('UNVERIFIED: standard official YouTube example failed:', json.dumps(state), flush=True)
                    return
                if state['state'] == 1 and state['time'] > .2:
                    print('PASS: standard official YouTube example played:', json.dumps(state), flush=True)
                    return
                time.sleep(.5)
            print('UNVERIFIED: standard official example did not progress:', json.dumps(state), flush=True)
        except (OSError, URLError, KeyError, TypeError) as exc:
            print('UNVERIFIED: standard YouTube check could not finish:', type(exc).__name__, str(exc)[:180], flush=True)
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
