"""Exercise the real UI, backend, and HTML audio in a Windows Edge session.

Only the YouTube API is replaced with a deterministic local test double. It
returns error 150, allowing the rejection and fallback paths to be checked
without claiming that an actual YouTube video played on the runner.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import EclipticaMusic as music


ROOT = Path(__file__).resolve().parent.parent
FAKE_YOUTUBE = b'''window.__testYoutubeLoads=[];window.__testYoutubePlayers=[];window.__testYoutubeEvents=[];
window.YT={PlayerState:{ENDED:0},Player:function(id,opts){
  window.__testYoutubePlayers.push(id);
  this.stopVideo=function(){window.__testYoutubeEvents.push('stop');};this.setVolume=function(){};this.seekTo=function(){};
  this.playVideo=function(){};this.getPlayerState=function(){return -1;};
  this.loadVideoById=function(video){window.__testYoutubeLoads.push(video);window.__testYoutubeEvents.push('load:'+video);
    setTimeout(function(){if(video==='Allowed1234'||video==='Allowed5678')opts.events.onStateChange({data:1});
      else if(video==='Autoplay123')opts.events.onAutoplayBlocked({});
      else opts.events.onError({data:150});},100);};
  var self=this;setTimeout(function(){opts.events.onReady({target:self});},0);
}};
onYouTubeIframeAPIReady();'''


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class FakeApp:
    def __init__(self):
        self.ui_last_seen = 0
        self.ui_goodbye_at = 0
        self.player = music.App.__new__(music.App)
        self.player.fade = Value(.1)
        self.player.volume = Value(80)
        self.player.status = Value('')

    def api_config(self):
        return {'music': {'Primal|戦闘': 'https://www.youtube.com/watch?v=AAAAAAAAAAA'},
                'fallback': {}, 'boss': {}, 'overlay': {}, 'identity_status': '',
                'lobby': '', 'log': '', 'fade': .1, 'volume': 80,
                'difficulties': ['Primal'], 'phases': ['戦闘', 'ボス'],
                'difficulty': 'Primal', 'phase': '戦闘', 'boss_choices': [], 'revision': 0}

    def api_view(self):
        with music.lock:
            player = music.state['player_status']
        return {'status':'待機中', 'event':'待機中', 'player':player,
                'monitoring':False, 'revision':0, 'combat':{}, 'weakness':{},
                'overlay_visible':False, 'party_overlay_enabled':False, 'identity_status':'',
                'diagnostics':{'player_connected':True,'log_exists':False}, 'volume':80,
                'vr_status':'OFF','results':[]}

    def api_action(self, data):
        if data.get('action') == 'play_selected':
            self.player.play('https://www.youtube.com/watch?v=AAAAAAAAAAA', str(ROOT / 'demo_audio' / 'battle.wav'))
            return self.player.status.get()
        if data.get('action') == 'play':
            if self.player.play(data.get('track',''),data.get('fallback','')) is False:
                raise ValueError(self.player.status.get())
            return self.player.status.get()
        return 'OK'


class Handler(music.Handler):
    def _dispatch(self, fun, timeout=20):
        return fun()

    def do_GET(self):
        if self.path == '/ui':
            raw = (ROOT / 'unified.html').read_bytes()
            expected = b'https://www.youtube.com/iframe_api'
            if expected not in raw:
                self.send_error(500); return
            raw = raw.replace(expected, b'/fake-youtube.js')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers(); self.wfile.write(raw); return
        if self.path == '/fake-youtube.js':
            self.send_response(200)
            self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            self.send_header('Content-Length', str(len(FAKE_YOUTUBE)))
            self.end_headers(); self.wfile.write(FAKE_YOUTUBE); return
        super().do_GET()


def main():
    driver = Path(os.environ.get('EDGEWEBDRIVER', '')) / 'msedgedriver.exe'
    if not driver.is_file():
        raise RuntimeError('Windows Edge WebDriver is required for the playback integration test')
    for name in ('battle.wav', 'boss.wav', 'calm.wav'):
        if not (ROOT / 'demo_audio' / name).is_file():
            raise RuntimeError('Generated test audio is missing: ' + name)
    music.UI_APP = FakeApp()
    with music.lock:
        music.state.update(seq=0, track='', fade=.1, volume=.8, stop=False,
                           player_status='', player_seen=0, volume_seq=0, fallback='')
        music.allowed_media.clear()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='ecliptica-playback-') as tmp:
        proc = subprocess.Popen([str(driver), '--port=' + str(port)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = 'http://127.0.0.1:' + str(port)
        session = None

        def call(method, path, payload=None):
            data = None if payload is None else json.dumps(payload).encode()
            req = Request(base + path, data=data, method=method,
                          headers={'Content-Type':'application/json'})
            with urlopen(req, timeout=20) as response:
                return json.load(response).get('value')

        def js(script):
            return call('POST', '/session/' + session + '/execute/sync', {'script':script, 'args':[]})

        def wait_for(condition, description, seconds=20):
            deadline = time.monotonic() + seconds
            last = None
            while time.monotonic() < deadline:
                last = condition()
                if last: return last
                time.sleep(.25)
            raise AssertionError(description + ' timed out; last result: ' + str(last))

        def sound_state():
            return js("return {time:aud[active].currentTime, paused:aud[active].paused, "
                      "volume:aud[active].volume, src:aud[active].src, "
                      "status:document.getElementById('status').textContent, "
                      "loads:window.__testYoutubeLoads.length};")

        def playing(filename):
            value = sound_state()
            return value if value and not value['paused'] and value['time'] > .4 and value['volume'] > .05 and filename in value['src'] else None

        try:
            for _ in range(50):
                try: call('GET', '/status'); break
                except (URLError, OSError): time.sleep(.1)
            result = call('POST', '/session', {'capabilities': {'alwaysMatch': {
                'browserName':'MicrosoftEdge', 'ms:edgeOptions': {
                    'args':['--no-first-run', '--user-data-dir=' + tmp, '--window-size=1130,850']}}}})
            session = result['sessionId']
            call('POST', '/session/' + session + '/url',
                 {'url':'http://127.0.0.1:' + str(server.server_port) + '/ui'})
            wait_for(lambda: js("return typeof model!=='undefined' && !!model && ytReady;"),
                     'UI and test player initialization')
            assert js("return JSON.stringify(window.__testYoutubePlayers)==='[\"yt0\"]' && document.querySelectorAll('#players > *').length===1;"), 'The UI must create one YouTube player'
            print('PASS: the UI creates exactly one YouTube player', flush=True)
            # Let the initial player and UI polls finish. The old duplicate
            # global poll name caused all later player updates to disappear.
            time.sleep(2)
            element = call('POST', '/session/' + session + '/element',
                           {'using':'css selector', 'value':'#home-preview'})
            eid = element['element-6066-11e4-a52e-4f735466cecf']
            call('POST', '/session/' + session + '/element/' + eid + '/click', {})
            first = wait_for(lambda: playing('battle.wav'), 'preview and rejected-YouTube fallback')
            assert first['loads'] == 1 and 'エラー150' in first['status'] and '予備BGM' in first['status'], first
            print('PASS: UI preview reaches real backend; simulated YouTube rejection starts audible battle WAV', flush=True)

            # Simulate an automatic scene event without another user click.
            # Wait past the normal transient click-activation window first.
            time.sleep(6)
            call('POST', '/session/' + session + '/window/minimize', {})
            wait_for(lambda: js('return document.hidden;'), 'minimized browser state')
            music.UI_APP.player.play('https://www.youtube.com/watch?v=BBBBBBBBBBB', str(ROOT / 'demo_audio' / 'boss.wav'))
            boss = wait_for(lambda: playing('boss.wav'), 'automatic boss music switch')
            assert boss['loads'] == 2 and 'エラー150' in boss['status'], boss
            print('PASS: automatic scene change starts the boss fallback while minimized', flush=True)

            music.UI_APP.player.play('https://www.youtube.com/watch?v=AAAAAAAAAAA')
            def rejected():
                value = sound_state()
                return value if value and value['loads'] == 3 and 'エラー150' in value['status'] and '未設定' in value['status'] else None
            reject = wait_for(rejected, 'unsupported video rejection')
            assert js('return aud.every(a=>a.paused);'), reject
            print('PASS: rejected custom YouTube track stops with a clear error', flush=True)

            custom_fallback = str(ROOT / 'demo_audio' / 'battle.wav')
            music.UI_APP.player.play('https://www.youtube.com/watch?v=Autoplay123', custom_fallback)
            autoplay = wait_for(lambda: playing('battle.wav'), 'autoplay-blocked fallback')
            assert '自動再生' in autoplay['status'] and '予備BGM' in autoplay['status'], autoplay
            print('PASS: a simulated browser autoplay block starts the configured fallback', flush=True)

            # Minimize precisely while a new local track's play() is pending.
            # The visibility handler must not remove that track's source.
            call('POST', '/session/' + session + '/window/maximize', {})
            wait_for(lambda: js('return !document.hidden;'), 'restored browser state')
            js("window.__raceAudio=aud[1-active]; window.__raceOriginal=window.__raceAudio.play.bind(window.__raceAudio); "
               "window.__raceAudio.play=function(){return new Promise((resolve,reject)=>"
               "{window.__releaseRace=()=>window.__raceOriginal().then(resolve,reject);});}; return true;")
            music.UI_APP.player.play(str(ROOT / 'demo_audio' / 'boss.wav'))
            wait_for(lambda: js('return typeof window.__releaseRace === "function";'), 'pending local play')
            call('POST', '/session/' + session + '/window/minimize', {})
            wait_for(lambda: js('return document.hidden;'), 'browser minimized during playback start')
            assert js('return window.__raceAudio.src.includes("boss.wav");'), 'Pending audio source was cleared on minimize'
            js('window.__releaseRace(); return true;')
            wait_for(lambda: playing('boss.wav'), 'pending local playback after minimize')
            print('PASS: minimizing during a pending local play does not interrupt music', flush=True)

            call('POST', '/session/' + session + '/window/maximize', {})
            wait_for(lambda: js('return !document.hidden;'), 'restore browser for registration checks')
            js("selectPanel('music'); let e=document.getElementById('music-track'); "
               "e.value='https://www.youtube.com/watch?v=AAAAAAAAAAA';e.dispatchEvent(new Event('input',{bubbles:true})); "
               "document.getElementById('music-fallback').value=''; document.getElementById('music-save').click();return true;")
            rejected = wait_for(lambda: js("let t=document.getElementById('music-check').textContent; return t.includes('再生できません') ? t : null;"), 'registration error 150')
            assert '埋め込みが許可されていません' in rejected, rejected
            print('PASS: saved restricted URL displays the real player rejection, without claiming success', flush=True)

            js("let e=document.getElementById('music-track');e.value='https://www.youtube.com/watch?v=Allowed1234';"
               "e.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('music-preview').click();return true;")
            allowed=wait_for(lambda: js("let t=document.getElementById('music-check').textContent;return t.includes('再生を確認:')?t:null;"), 'registered URL playback event')
            assert '再生を確認' in allowed, allowed
            print('PASS: successful mocked YouTube player event produces a confirmed result', flush=True)

            js("let e=document.getElementById('music-track');e.value=" + json.dumps(str(ROOT / 'demo_audio' / 'battle.wav')) + ";e.dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('music-preview').click();return true;")
            wait_for(lambda: playing('battle.wav'), 'local file playback')
            wait_for(lambda: js("return document.getElementById('music-check').textContent.includes('再生を確認:');"), 'local file result')
            print('PASS: user-selected local audio plays through the actual HTML audio element', flush=True)
            music.UI_APP.player.play('https://www.youtube.com/watch?v=Allowed1234')
            wait_for(lambda: js("return window.__testYoutubeLoads.at(-1)==='Allowed1234' && currentTask?.confirmed;"), 'first YouTube video')
            music.UI_APP.player.play('https://www.youtube.com/watch?v=Allowed5678')
            wait_for(lambda: js("return window.__testYoutubeLoads.at(-1)==='Allowed5678' && currentTask?.confirmed;"), 'second YouTube video')
            assert js("let a=window.__testYoutubeEvents;let n=a.lastIndexOf('load:Allowed5678');return n>0 && a[n-1]==='stop' && window.__testYoutubePlayers.length===1;"), 'YouTube switch did not stop the old video first'
            print('PASS: two successive YouTube tracks use one player and stop the old track first', flush=True)
            js("selectPanel('home');document.getElementById('diagnose').click();return true;")
            diagnosis=wait_for(lambda: js("let t=document.getElementById('diagnosis').textContent;return t.includes('VRChatログ')?t:null;"), 'one-click diagnostic')
            assert '出力' in diagnosis and '未確認' in diagnosis, diagnosis
            print('PASS: diagnostics distinguish missing log and unverified speaker output', flush=True)
        finally:
            if session:
                try: call('DELETE', '/session/' + session)
                except (OSError, URLError, HTTPError): pass
            proc.terminate()
            try: proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()
            server.shutdown()


if __name__ == '__main__':
    main()
