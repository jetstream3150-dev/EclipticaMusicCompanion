"""Exercise actual HTTP requests through the real Tk dispatch queue on Windows."""
import json
from pathlib import Path
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch
import tkinter as tk

import EclipticaMusic as music


def main():
    with tempfile.TemporaryDirectory(prefix='ecliptica-api-gui-') as tmp:
        config = Path(tmp) / 'settings.json'
        log_dir = Path(tmp) / 'vrchat'
        log_dir.mkdir()
        music.CFG = config
        music.LOG = log_dir
        server = ThreadingHTTPServer(('127.0.0.1', 0), music.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        root = tk.Tk(); root.withdraw()
        app = music.App(root, server.server_port)
        app.unified = True
        music.UI_APP = app
        root.after(40, app.drain_api)
        base = 'http://127.0.0.1:' + str(server.server_port)
        done = threading.Event()
        result = {}

        def request(path, data=None):
            headers = {}
            payload = None
            if data is not None:
                payload = json.dumps(data).encode('utf-8')
                headers = {'Content-Type':'application/json', 'X-Ecliptica-UI':'1', 'Origin':base}
            req = Request(base + path, data=payload, headers=headers)
            try:
                with urlopen(req, timeout=8) as response:
                    return response.status, json.load(response)
            except HTTPError as exc:
                return exc.code, json.load(exc)

        def exercise():
            try:
                url = 'https://www.youtube.com/watch?v=PnvVPv_EODw'
                status, response = request('/api/action', {'action':'set_boss', 'boss':'Yuki', 'track':url, 'fallback':''})
                assert status == 200 and response['ok'], (status,response)
                status, response = request('/api/config')
                assert status == 200 and response['result']['boss']['Yuki'] == url, response
                assert json.loads(config.read_text(encoding='utf-8'))['boss']['Yuki'] == url
                status, response = request('/api/action', {'action':'play', 'track':url, 'fallback':''})
                assert status == 200 and response['ok'], (status,response)
                status, state = request('/state')
                assert status == 200 and state['track'] == url and not state['stop'], state
                print('PASS: real GUI queue saves the supplied boss URL and accepts preview', flush=True)

                with patch.object(Path, 'write_text', side_effect=PermissionError('simulated access denied')), \
                     patch.object(music.messagebox, 'showerror', side_effect=AssertionError('hidden dialog opened')):
                    status, response = request('/api/action', {'action':'set_boss', 'boss':'Yuki',
                                               'track':'https://youtu.be/AAAAAAAAAAA', 'fallback':''})
                    assert status == 400 and '設定を保存できませんでした' in response.get('error',''), response
                status, response = request('/api/view')
                assert status == 200 and response['ok'], response
                assert json.loads(config.read_text(encoding='utf-8'))['boss']['Yuki'] == url
                status, response = request('/api/config')
                assert status == 200 and response['result']['boss']['Yuki'] == url, response
                print('PASS: failed save returns a visible error and the real GUI queue remains responsive', flush=True)

                with patch.object(music.messagebox, 'showwarning', side_effect=AssertionError('hidden dialog opened')):
                    status, response = request('/api/action', {'action':'detect'})
                    assert status == 400 and 'VRChatログが見つかりません' in response.get('error',''), response
                status, response = request('/api/view')
                assert status == 200 and response['ok'], response
                print('PASS: missing VRChat logs return a visible error without blocking the GUI queue', flush=True)

                status, response = request('/api/action', {'action':'set_music_all','phase':'戦闘',
                                                           'track':'demo://battle','fallback':''})
                assert status == 200 and response['ok'], response
                saved=json.loads(config.read_text(encoding='utf-8'))
                for difficulty in app.DIFFICULTIES:
                    assert saved['music'][difficulty+'|戦闘']=='demo://battle', saved['music']
                status, response = request('/api/action', {'action':'play','track':'demo://battle','fallback':''})
                assert status == 200 and response['ok'], response
                status, state = request('/state')
                assert status == 200 and state['track'].replace('\\','/').endswith('/demo_audio/battle.wav'), state
                print('PASS: actual GUI saves the built-in preset for every difficulty and resolves its bundled path', flush=True)

                for difficulty, track in [('Primal','demo://calm'),('Eclipse','demo://battle')]:
                    status, response = request('/api/action', {'action':'set_music','difficulty':difficulty,'phase':'戦闘','track':track,'fallback':''})
                    assert status == 200 and response['ok'], response
                log = log_dir / 'output_log_2026-10-29_00-00-00.txt'
                log.write_text('ECLIPTICA - now in stage: Stage_ProtoColony on phase: 0.1 as class: Nekomancer\n', encoding='utf-8')
                status, response = request('/api/action', {'action':'start','difficulty':'Eclipse'})
                assert status == 200 and response['ok'], response
                status, state = request('/state')
                assert state['track'].replace('\\','/').endswith('/demo_audio/battle.wav'), state
                status, response = request('/api/action', {'action':'play_selected','difficulty':'Primal','phase':'戦闘'})
                assert status == 200 and response['ok'], response
                status, response = request('/api/config')
                assert response['result']['difficulty']=='Eclipse', response
                with log.open('a',encoding='utf-8') as stream:
                    stream.write('ECLIPTICA - now in stage: Stage_ProtoColony on phase: 0.2 as class: Nekomancer\n')
                end=time.monotonic()+5
                while time.monotonic()<end:
                    _, state = request('/state')
                    if state['track'].replace('\\','/').endswith('/demo_audio/battle.wav'):break
                    time.sleep(.1)
                else:raise AssertionError('automatic stage event did not restore Eclipse track')
                status, response = request('/api/action', {'action':'set_active_difficulty','difficulty':'Primal'})
                assert status == 200 and response['ok'], response
                _, state = request('/state')
                assert state['track'].replace('\\','/').endswith('/demo_audio/calm.wav'), state
                assert json.loads(config.read_text(encoding='utf-8'))['active_difficulty']=='Primal'
                print('PASS: real GUI resumes the selected difficulty, isolates preview, and changes the live stage track', flush=True)

                status, response = request('/api/action', {'action':'set_active_difficulty','difficulty':'自動判定'})
                assert status == 200 and response['ok'], response
                with log.open('a',encoding='utf-8') as stream:
                    stream.write('ECLIPTICA - now in stage: Stage_New on phase: 0.81 as class: Nekomancer\n')
                end=time.monotonic()+5
                while time.monotonic()<end:
                    _, view=request('/api/view');_, state=request('/state')
                    if view['result']['detected_difficulty']=='Eclipse' and state['track'].replace('\\','/').endswith('/demo_audio/battle.wav'):break
                    time.sleep(.1)
                else:raise AssertionError('automatic Eclipse detection did not select the Eclipse stage track')
                with log.open('a',encoding='utf-8') as stream:
                    stream.write('2026 Debug - [Behaviour] OnLeftRoom\n')
                end=time.monotonic()+5
                while time.monotonic()<end:
                    _, view=request('/api/view');_, state=request('/state')
                    if not view['result']['detected_difficulty'] and state['stop']:break
                    time.sleep(.1)
                else:raise AssertionError('difficulty was not cleared after leaving the world')
                with log.open('a',encoding='utf-8') as stream:
                    stream.write('ECLIPTICA - now in stage: Stage_Return on phase: 0.81 as class: Nekomancer\n')
                status, response=request('/api/action',{'action':'start','difficulty':'自動判定'})
                assert status==200 and response['ok'],response
                _, view=request('/api/view');_, state=request('/state')
                assert view['result']['detected_difficulty']=='Eclipse',view
                assert state['track'].replace('\\','/').endswith('/demo_audio/battle.wav'),state
                assert json.loads(config.read_text(encoding='utf-8'))['difficulty_mode']=='auto'
                print('PASS: real GUI auto-detects, resumes and clears the stage difficulty on exit',flush=True)
            except Exception as exc:
                result['error'] = exc
            finally:
                done.set()

        def poll():
            if done.is_set():root.quit()
            else:root.after(40,poll)
        root.after(40,poll)
        root.after(30000,root.quit)
        threading.Thread(target=exercise,daemon=True).start()
        try:
            root.mainloop()
            if not done.is_set():raise RuntimeError('Real GUI API integration test timed out')
            if 'error' in result:raise result['error']
        finally:
            app.close();server.shutdown();server.server_close()
            music.UI_APP=None


if __name__ == '__main__':
    main()
