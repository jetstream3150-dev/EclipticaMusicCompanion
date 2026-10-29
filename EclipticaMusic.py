import json,os,re,threading,time,webbrowser,mimetypes,sys,subprocess,shutil,queue,math,unicodedata
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import tkinter as tk
import zipfile
from tkinter import ttk,filedialog,messagebox
from datetime import datetime
from combat_meter import CombatMeter
from boss_weakness import lookup as lookup_weakness
from alert_sound import play_custom_sound
from vrchat_identity import detect_identity, session_sort_key
from battle_results import BattleResults
from steamvr_hud import SteamVRHUD
BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
USER_DIR=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else BASE
CFG=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'EclipticaMusicCompanion'/'settings.json'
CFG.parent.mkdir(parents=True,exist_ok=True)
LOG=Path(os.environ.get('USERPROFILE',str(Path.home())))/'AppData/LocalLow/VRChat/VRChat'
DEFAULT={'round':{},'waiting':{},'phase':{},'boss':{},'music':{},'fade':2.0,'volume':80,'log':'','auto':False,'fallback':{},'lobby':'','overlay':{'show':False,'name':'','auto_name':True,'alert':True,'other_alerts':False,'volume':65,'seconds':10,'opacity':92},'discovered_bosses':[]}
# NCS official YouTube videos, used only as replaceable starter tracks.
SAMPLE_PHASE_TRACKS={
 '戦闘':'https://www.youtube.com/watch?v=yJg-Y5byMMw',
 '準備':'https://www.youtube.com/watch?v=TW9d8vYrVFQ',
 'ボス':'https://www.youtube.com/watch?v=J2X5mJ3HDYE',
 '終了':'https://www.youtube.com/watch?v=3nQNiWdeH2Q',
 '休憩':'https://www.youtube.com/watch?v=TW9d8vYrVFQ',
}
# These are original, bundled demo loops, not downloads of YouTube videos.
SAMPLE_FALLBACK_FILES={
 SAMPLE_PHASE_TRACKS['戦闘']:'battle.wav',
 SAMPLE_PHASE_TRACKS['ボス']:'boss.wav',
 SAMPLE_PHASE_TRACKS['準備']:'calm.wav',
 SAMPLE_PHASE_TRACKS['終了']:'calm.wav',
}
DEMO_TRACKS={'demo://battle':'battle.wav','demo://boss':'boss.wav','demo://calm':'calm.wav'}
def resolve_demo_track(track):
 name=DEMO_TRACKS.get(track)
 return str(BASE/'demo_audio'/name) if name else track

def sample_fallback(track):
 name=SAMPLE_FALLBACK_FILES.get(track)
 if not name:return ''
 path=BASE/'demo_audio'/name
 return str(path) if path.is_file() else ''

def youtube_id(track):
 """Accept supported YouTube video URLs only; do not accept malformed IDs."""
 try:
  u=urlparse(track)
  if u.scheme.lower()!='https' or u.username or u.password:return ''
  host=(u.hostname or '').lower()
  if host=='youtu.be':video=u.path.strip('/')
  elif host in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'):
   if u.path=='/watch':video=parse_qs(u.query).get('v',[''])[0]
   elif u.path.startswith(('/shorts/','/embed/')):video=u.path.split('/')[2]
   else:return ''
  else:return ''
  return video if re.fullmatch(r'[A-Za-z0-9_-]{11}',video) else ''
 except (ValueError,IndexError):return ''

def read_resume_snapshot(path,meter):
 """Replay only complete recent lines, without replaying damage or alerts."""
 stat=path.stat();end=stat.st_size
 if time.time()-stat.st_mtime>7200:return end,None
 with path.open('rb') as stream:
  begin=max(0,end-2_000_000);stream.seek(begin);data=stream.read(end-begin)
 last=data.rfind(b'\n')
 offset=begin+last+1 if last>=0 else begin
 data=data[:last+1] if last>=0 else b''
 if begin and data:
  first=data.find(b'\n');data=data[first+1:] if first>=0 else b''
 event=None
 for line in data.decode('utf-8','replace').splitlines():
  meter.ingest(line,replay=True)
  if re.search(r'\[Behaviour\]\s*(?:Entering Room:|OnLeftRoom\b)',line,re.I):event=None
  if 'ECLIPTICA - now in intermission' in line:event=('休憩',None)
  elif 'ECLIPTICA - now in lobby' in line:event=('ロビー',None)
  else:
   boss=re.search(r'ECLIPTICA - now fighting boss:\s*(.+?)\s+on phase:',line)
   stage=re.search(r'ECLIPTICA - now in stage:\s*(.+?)\s+on phase:',line)
   if boss:event=('ボス',re.sub(r'\(Clone\)$','',boss.group(1).strip(),flags=re.I).strip())
   elif stage:event=('戦闘',stage.group(1).strip())
 return offset,event

def add_sample_music_once(cfg,difficulties):
 # Fill missing slots on first upgrade without changing any existing selection.
 # The marker lets a user clear a sample permanently after it has been added.
 if cfg.get('sample_music_initialized') is True:return cfg
 for difficulty in difficulties:
  for phase,track in SAMPLE_PHASE_TRACKS.items():
   cfg['music'].setdefault(difficulty+'|'+phase,track)
 if not cfg.get('lobby'):cfg['lobby']=SAMPLE_PHASE_TRACKS['休憩']
 cfg['sample_music_initialized']=True
 return cfg
state={'seq':0,'track':'','fade':2,'volume':.8,'stop':False,'player_status':'プレイヤー未接続','player_seen':0,'volume_seq':0,'fallback':''}
lock=threading.Lock()
allowed_media=set()
UI_APP=None
API_QUEUE=queue.Queue(maxsize=256)
class UIRequest:
 """A GUI-thread request that can be cancelled before it starts."""
 def __init__(self,fun):
  self.fun=fun;self.done=threading.Event();self.guard=threading.Lock()
  self.state='queued';self.value=None;self.error=None
 def cancel_if_queued(self):
  with self.guard:
   if self.state!='queued':return False
   self.state='cancelled';self.done.set();return True
 def execute(self):
  with self.guard:
   if self.state!='queued':return
   self.state='running'
  try:self.value=self.fun()
  except Exception as exc:self.error=exc
  finally:
   with self.guard:self.state='done';self.done.set()
class Handler(BaseHTTPRequestHandler):
 def do_POST(self):
  host=self.headers.get('Host','').split(':')[0]
  if self.client_address[0]!='127.0.0.1' or host not in ('127.0.0.1','localhost'):
   self.send_error(403);return
  if self.path in ('/api/action','/api/goodbye'):
   origin=self.headers.get('Origin','')
   expected=f'http://127.0.0.1:{self.server.server_port}'
   if origin!=expected or UI_APP is None:
    self.send_error(403);return
   if self.path=='/api/goodbye':
    UI_APP.ui_goodbye_at=time.time()
    self.send_response(204);self.end_headers();return
   if self.headers.get('X-Ecliptica-UI')!='1' or self.headers.get('Content-Type','').split(';')[0].strip()!='application/json':
    self.send_error(403);return
   try:
    size=int(self.headers.get('Content-Length','0'))
    if size<2 or size>20000:raise ValueError('操作データが不正です')
    data=json.loads(self.rfile.read(size).decode('utf-8'))
    if not isinstance(data,dict):raise ValueError('操作データが不正です')
    value=self._dispatch(lambda:UI_APP.api_action(data),timeout=180 if data.get('action') in ('pick','pick_alert','backup','restore') else 20)
    self._json_response({'ok':True,'result':value});return
   except Exception as exc:
    self._json_response({'ok':False,'error':str(exc)[:220]},400);return
  if self.path!='/player-status':
   self.send_error(403);return
  try:
   size=int(self.headers.get('Content-Length','0'))
   if size<1 or size>4096:raise ValueError('invalid size')
   data=json.loads(self.rfile.read(size).decode('utf-8'))
   with lock:state['player_status']=str(data.get('status',''))[:240];state['player_seen']=time.time()
   self.send_response(204);self.end_headers()
  except (ValueError,UnicodeError,json.JSONDecodeError):self.send_error(400)
 def _json_response(self,obj,status=200):
  raw=json.dumps(obj,ensure_ascii=False).encode('utf-8')
  self.send_response(status)
  self.send_header('Content-Type','application/json; charset=utf-8')
  self.send_header('Cache-Control','no-store')
  self.send_header('X-Content-Type-Options','nosniff')
  self.send_header('Content-Length',str(len(raw)))
  self.end_headers();self.wfile.write(raw)
 def _dispatch(self,fun,timeout=20):
  request=UIRequest(fun)
  try:API_QUEUE.put_nowait(request)
  except queue.Full:raise RuntimeError('アプリへの操作が混み合っています。少し待ってから再試行してください')
  if not request.done.wait(timeout):
   if request.cancel_if_queued():
    raise TimeoutError('アプリが応答しません。今回の操作は実行されていません。アプリを終了して起動し直してください')
   if not request.done.is_set():
    raise TimeoutError('操作の処理が続いています。完了するまで待ち、設定を確認してください')
  if request.error:raise RuntimeError(str(request.error))
  return request.value
 def log_message(self,*args):pass
 def do_GET(self):
  u=urlparse(self.path)
  if self.headers.get('Host','').split(':')[0] not in ('127.0.0.1','localhost'):
   self.send_error(403);return
  if u.path in ('/api/config','/api/view'):
   if UI_APP is None:self.send_error(503);return
   UI_APP.ui_last_seen=time.time();UI_APP.ui_goodbye_at=0
   try:
    if u.path=='/api/view':
     data=self._dispatch(lambda:UI_APP.api_view())
    else:data=self._dispatch(lambda:UI_APP.api_config())
    self._json_response({'ok':True,'result':data})
   except Exception as exc:self._json_response({'ok':False,'error':str(exc)[:220]},503)
   return
  if u.path in ('/ui','/engine.js','/party.js'):
   target=BASE/('unified.html' if u.path=='/ui' else u.path.lstrip('/'))
   if not target.is_file():self.send_error(404);return
   b=target.read_bytes();self.send_response(200)
   self.send_header('Content-Type','text/html; charset=utf-8' if u.path=='/ui' else 'application/javascript; charset=utf-8')
   self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
   self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b);return
  if u.path=='/state':
   with lock: b=json.dumps(state).encode()
   self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b);return
  if u.path=='/media':
   p=Path(unquote(parse_qs(u.query).get('path',[''])[0]))
   if str(p.resolve()) not in allowed_media or not p.is_file() or p.suffix.lower() not in ('.mp3','.wav','.ogg','.m4a'):
    self.send_error(404);return
   size=p.stat().st_size;rg=self.headers.get('Range','');start=0;end=size-1
   m=re.match(r'bytes=(\d*)-(\d*)',rg)
   if m:
    if m.group(1):start=int(m.group(1))
    if m.group(2):end=min(end,int(m.group(2)))
   if start>end or start>=size:self.send_error(416);return
   self.send_response(206 if m else 200)
   self.send_header('Content-Type',mimetypes.guess_type(p.name)[0] or 'application/octet-stream')
   self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1))
   if m:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
   self.end_headers()
   with p.open('rb') as f:
    f.seek(start);remaining=end-start+1
    while remaining:
     b=f.read(min(65536,remaining))
     if not b:break
     self.wfile.write(b);remaining-=len(b)
   return
  if u.path=='/':
   b=(BASE/'player.html').read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(b);return
  self.send_error(404)

def verify_frozen_tk_assets(interpreter,frozen_dir):
 """Check either Tcl/Tk 8 filesystem scripts or Tcl/Tk 9 DLL-embedded scripts."""
 frozen_dir=Path(frozen_dir)
 if interpreter.eval('info library').startswith('//zipfs:/'):
  for pattern,required in (('tcl9*.dll','tcl_library/init.tcl'),('tcl9tk*.dll','tk_library/tk.tcl')):
   found=False
   for dll in frozen_dir.glob(pattern):
    try:
     with zipfile.ZipFile(dll) as archive:
      found=any(name.endswith(required) for name in archive.namelist())
    except (OSError,zipfile.BadZipFile):continue
    if found:break
   if not found:raise FileNotFoundError('Missing embedded Tcl/Tk data: '+required)
 else:
  for needed in ('_tcl_data/init.tcl','_tk_data/tk.tcl'):
   if not (frozen_dir/needed).is_file():
    raise FileNotFoundError('Missing bundled Tcl/Tk data: '+needed)

def play_target_tone(kind,volume=65,filename=''):
 """Windows-only, standalone PCM chime. Never blocks the GUI thread."""
 if sys.platform!='win32' or volume<=0:return
 def worker():
  if filename:
   try:
    if play_custom_sound(filename,volume):return
   except Exception:pass  # Continue with the built-in alert on playback failure.
  try:
   import winsound,math,struct,wave,io
   tones={'target_on':[(850,.105),(940,.105),(1030,.105),(1180,.23)],
    'target_off':[(750,.14),(510,.21)],'target_switch':[(660,.12),(880,.18)]}[kind]
   rate=22050;frames=[];amp=max(0,min(100,volume))/100*.38
   for frequency,duration in tones:
    count=int(rate*duration)
    for i in range(count):
     env=min(1,i/180,(count-i)/240)
     value=int(32767*amp*max(0,env)*math.sin(math.tau*frequency*i/rate))
     frames.append(struct.pack('<h',value))
    frames.extend([b'\0\0']*int(rate*.025))
   mem=io.BytesIO()
   with wave.open(mem,'wb') as f:
    f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(b''.join(frames))
   winsound.PlaySound(mem.getvalue(),winsound.SND_MEMORY)
  except Exception:pass
 threading.Thread(target=worker,daemon=True).start()

class BattleHUD(tk.Toplevel):
 """Optional compact desktop HUD (not a native SteamVR overlay)."""
 def __init__(self,app):
  super().__init__(app.root)
  self.app=app;self.overrideredirect(True);self.attributes('-topmost',True)
  self.geometry('362x460+48+75');self.configure(bg='#060d16')
  self.start_drag=None
  self.border=tk.Frame(self,bg='#164e55',padx=1,pady=1);self.border.pack(fill='both',expand=True)
  content=tk.Frame(self.border,bg='#0d1721',padx=15,pady=12);content.pack(fill='both',expand=True)
  header=tk.Frame(content,bg='#0d1721');header.pack(fill='x')
  self.h=tk.Label(header,text='ECLIPTICA   /   BATTLE HUD',font=('Segoe UI',11,'bold'),bg='#0d1721',fg='#67eee1',anchor='w');self.h.pack(side='left',fill='x',expand=True)
  close=tk.Label(header,text='✕',font=('Segoe UI',12,'bold'),bg='#0d1721',fg='#9bb0ba',cursor='hand2');close.pack(side='right',padx=5)
  close.bind('<Button-1>',lambda e:self.app.hide_overlay_from_window())
  for w in (header,self.h):
   w.bind('<ButtonPress-1>',self.drag_start);w.bind('<B1-Motion>',self.drag)
  tk.Frame(content,bg='#253640',height=1).pack(fill='x',pady=10)
  self.boss_lbl=tk.Label(content,bg='#0d1721',fg='white',font=('Segoe UI',16,'bold'),anchor='w');self.boss_lbl.pack(fill='x')
  self.target_lbl=tk.Label(content,bg='#0d1721',fg='#c3e3e4',font=('Segoe UI',11,'bold'),anchor='w');self.target_lbl.pack(fill='x',pady=(8,8))
  cards=tk.Frame(content,bg='#0d1721');cards.pack(fill='x')
  self.metrics={}
  for i,(key,label) in enumerate([('dps','DPS'),('boss_damage','BOSS DMG'),('total_damage','TOTAL'),('attack_speed','HITS / s')]):
   cell=tk.Frame(cards,bg='#152734',padx=12,pady=8);cell.grid(row=i//2,column=i%2,padx=3,pady=3,sticky='nsew');cards.columnconfigure(i%2,weight=1)
   tk.Label(cell,text=label,font=('Segoe UI',9),bg='#152734',fg='#80a6b4',anchor='w').pack(fill='x')
   val=tk.Label(cell,text='0',font=('Segoe UI',18,'bold'),bg='#152734',fg='#f5ffff',anchor='w');val.pack(fill='x');self.metrics[key]=val
  self.weak_lbl=tk.Label(content,text='',font=('Segoe UI',9),bg='#0d1721',fg='#c3e3e4',anchor='w',justify='left',wraplength=320);self.weak_lbl.pack(fill='x',pady=(8,0))
  self.tracker_lbl=tk.Label(content,text='',font=('Segoe UI',9),bg='#0d1721',fg='#c3e3e4',anchor='w',justify='left',wraplength=320);self.tracker_lbl.pack(fill='x',pady=(6,0))
  self.note=tk.Label(content,text='ログから推定 / 画面上をドラッグして移動',font=('Segoe UI',9),bg='#0d1721',fg='#7896a3');self.note.pack(anchor='w',pady=(6,0))
  self.refresh(app.meter.snapshot(),app.overlay_cfg)
 def drag_start(self,event):self.start_drag=(event.x_root-self.winfo_x(),event.y_root-self.winfo_y())
 def drag(self,event):
  if self.start_drag:self.geometry('+%d+%d'%(event.x_root-self.start_drag[0],event.y_root-self.start_drag[1]))
 def refresh(self,v,cfg):
  if not bool(cfg.get('show')):return
  self.attributes('-alpha',max(.3,min(1,float(cfg.get('opacity',92))/100)))
  self.boss_lbl.config(text='BOSS  /  '+v['boss'][:28])
  targeted=v['is_targeted'];self.target_lbl.config(text='⚠ YOU ARE TARGETED!' if targeted else 'TARGET (推定)  /  '+v['target'][:30],fg='#ff727c' if targeted else '#b2d8de')
  for key,lbl in self.metrics.items():
   value=v.get(key,0);lbl.config(text=('%0.1f'%value if key in ('dps','attack_speed') else '%0.0f'%value))
  if cfg.get('show_weakness',True) and not cfg.get('separate_widgets',False):
   w=lookup_weakness(v['boss'],str(BASE/'boss_weakness_data.txt'))
   changes=[('弱' if e['kind']=='weak' else '耐')+e['name']+' '+e['value'] for e in w['elements'] if e['kind']!='neutral']
   summary='  '.join(changes) if changes else (' / '.join(w['notes'][:2]) if w['notes'] else ('弱点・耐性: すべて等倍' if w['available'] else '弱点・耐性: 未登録'))
   self.weak_lbl.config(text='参考  '+summary)
  else:self.weak_lbl.config(text='')
  if cfg.get('separate_widgets',False):tracker=''
  elif v.get('mode')=='stage':tracker='トークン（推定） %d / %d'%(v.get('tokens_collected',0),v.get('tokens_spawned',0))
  elif v.get('mode')=='break' and v.get('dummy_hits',0):tracker='練習ダミー（推定） DPS %.1f / 合計 %.0f'%(v.get('dummy_dps',0),v.get('dummy_damage',0))
  else:tracker=''
  self.tracker_lbl.config(text=tracker)
  self.border.config(bg='#aa3646' if targeted else '#164e55')
  self.note.config(text='集計イベント %d件  /  %d秒DPS  • ドラッグ移動'%(v['events_found'],v['dps_window']))

class MetricWidget(tk.Toplevel):
 """Independently movable desktop widget; the header acts as a drag handle."""
 TITLES={'weakness':'ボスの弱点・耐性','tokens':'トークン（推定）','dummy':'練習ダミー（推定）','damage':'ダメージ（推定）','target':'ターゲット（推定）'}
 def __init__(self,app,kind,position):
  super().__init__(app.root)
  self.app=app;self.kind=kind;self.start_drag=None
  self.overrideredirect(True);self.attributes('-topmost',True);self.configure(bg='#0d1721')
  self.geometry('300x86%+d%+d'%tuple(position))
  frame=tk.Frame(self,bg='#0d1721',padx=10,pady=8,highlightbackground='#164e55',highlightthickness=1);frame.pack(fill='both',expand=True)
  header=tk.Label(frame,text='☰  '+self.TITLES[kind]+'  • ドラッグ移動',font=('Segoe UI',9,'bold'),bg='#0d1721',fg='#67eee1',anchor='w',cursor='hand2');header.pack(fill='x')
  header.bind('<ButtonPress-1>',self.drag_start);header.bind('<B1-Motion>',self.drag);header.bind('<ButtonRelease-1>',self.drag_end)
  self.value=tk.Label(frame,text='',font=('Segoe UI',9),bg='#0d1721',fg='#edf7f8',anchor='w',justify='left',wraplength=278);self.value.pack(fill='both',expand=True)
 def drag_start(self,event):self.start_drag=(event.x_root-self.winfo_x(),event.y_root-self.winfo_y())
 def drag(self,event):
  if self.start_drag:
   x=max(0,event.x_root-self.start_drag[0]);y=max(0,event.y_root-self.start_drag[1]);self.geometry('+%d+%d'%(x,y))
 def drag_end(self,event):
  if self.start_drag:
   self.start_drag=None;self.app.overlay_cfg['widget_positions'][self.kind]=[self.winfo_x(),self.winfo_y()];self.app.save(quiet=True)
 def refresh(self,text,opacity):
  self.attributes('-alpha',max(.3,min(1,float(opacity)/100)));self.value.config(text=text)

class PartyHUD(tk.Toplevel):
 """A separate, draggable desktop window for the locally displayed roster."""
 def __init__(self,app):
  super().__init__(app.root)
  self.app=app;self.overrideredirect(True);self.attributes('-topmost',True)
  self.geometry('362x160+430+75');self.configure(bg='#0d1721');self.start_drag=None
  content=tk.Frame(self,bg='#0d1721',padx=12,pady=9,highlightbackground='#164e55',highlightthickness=1);content.pack(fill='both',expand=True)
  header=tk.Frame(content,bg='#0d1721');header.pack(fill='x')
  title=tk.Label(header,text='PARTY  /  DPS',font=('Segoe UI',10,'bold'),bg='#0d1721',fg='#67eee1',anchor='w');title.pack(side='left',fill='x',expand=True)
  close=tk.Label(header,text='✕',font=('Segoe UI',11,'bold'),bg='#0d1721',fg='#9bb0ba',cursor='hand2');close.pack(side='right')
  close.bind('<Button-1>',lambda e:self.app.hide_party_hud_from_window())
  for widget in (header,title):
   widget.bind('<ButtonPress-1>',self.drag_start);widget.bind('<B1-Motion>',self.drag)
  self.list_lbl=tk.Label(content,text='',font=('Segoe UI',9),bg='#0d1721',fg='#edf7f8',anchor='nw',justify='left',wraplength=320);self.list_lbl.pack(fill='both',expand=True,pady=(8,0))
 def drag_start(self,event):self.start_drag=(event.x_root-self.winfo_x(),event.y_root-self.winfo_y())
 def drag(self,event):
  if self.start_drag:self.geometry('+%d+%d'%(event.x_root-self.start_drag[0],event.y_root-self.start_drag[1]))
 def refresh(self,rows,opacity):
  self.attributes('-alpha',max(.3,min(1,float(opacity)/100)))
  self.list_lbl.config(text='\n'.join('%s  /  %s  |  DPS %.1f  /  DMG %.0f'%(r['name'][:12],r['job'][:9] or '—',r['dps'],r['boss_damage']) for r in rows))
  self.geometry('362x%d'%max(90,min(440,65+len(rows)*30)))

class App:
 def __init__(self,root,port):
  self.root=root;self.port=port;self.cfg=self.load_config();self.stop=threading.Event();self.worker=None;self.round=0;self.boss='';self.laststage='';self.vars={};self.difficulty=tk.StringVar(value=self.cfg.get('active_difficulty','') if self.cfg.get('active_difficulty') in self.DIFFICULTIES else '');self.phase_choice=tk.StringVar(value='休憩');self.current_round=tk.IntVar(value=1);root.title('Ecliptica Music Companion v1.8.2 β Lite');root.geometry('920x760');root.minsize(650,540);root.configure(bg='#0b1020');self.status=tk.StringVar(value='待機中');self.event_status=tk.StringVar(value='検知イベント: なし');self.fade=tk.DoubleVar(value=self.cfg.get('fade',2));self.volume=tk.IntVar(value=self.cfg.get('volume',80));self.log=tk.StringVar(value=self.cfg.get('log',''));self.player_process=None;self.player_launched=False;self.unified=False;self.ui_last_seen=0;self.ui_goodbye_at=0;self.ui_launched_at=0;self.revision=0;self.player_status=tk.StringVar(value='プレイヤー: 未接続');self.overlay_cfg=self._overlay_options();self.meter=CombatMeter(self.overlay_cfg['name'],self.overlay_cfg['seconds']);self.combat_events=queue.Queue();self.watch_events=queue.Queue();self.discovered_bosses=set(self.cfg.get('discovered_bosses',[])) if isinstance(self.cfg.get('discovered_bosses'),list) else set();self.hud=None;self.party_hud=None;self.party_rows=[];self.extra_widgets={};self.identity_status='自動取得の確認待ち';self.identity_log='';self.results=BattleResults(CFG.parent/'battle_results.json');self.vr_hud=SteamVRHUD();self.build();self.root.after(50,self.drain_watch_events);self.root.after(350,self.update_hud_loop);self.root.after(800,self.refresh_identity);self.root.after(15000,self.periodic_identity_refresh);root.protocol('WM_DELETE_WINDOW',self.close);root.after(650,lambda:self.toggle_hud(True) if self.overlay_cfg['show'] else None);root.after(1200,self.auto_start);root.after(1500,self.refresh_player_status)
  if self.overlay_cfg['vr_show']:self.vr_hud.enable(True,self.overlay_cfg['vr_split'])
 def _overlay_options(self):
  defaults={'show':False,'vr_show':False,'vr_split':False,'show_damage':False,'show_target':False,'name':'','auto_name':True,'alert':True,'other_alerts':False,'show_weakness':True,'show_party':True,'separate_widgets':False,'widget_positions':{},'sound_path':'','volume':65,'seconds':10,'opacity':92}
  saved=self.cfg.get('overlay',{})
  if isinstance(saved,dict):
   defaults.update({k:v for k,v in saved.items() if k in defaults})
   # An existing user's manually entered name must remain a manual override.
   if 'auto_name' not in saved and str(saved.get('name','')).strip():
    defaults['auto_name']=False
  defaults['auto_name']=bool(defaults['auto_name'])
  try:defaults['seconds']=max(1,min(15,int(defaults['seconds'])))
  except (ValueError,TypeError):defaults['seconds']=10
  try:defaults['volume']=max(0,min(100,int(defaults['volume'])))
  except (ValueError,TypeError):defaults['volume']=65
  try:defaults['opacity']=max(30,min(100,int(defaults['opacity'])))
  except (ValueError,TypeError):defaults['opacity']=92
  defaults['name']=str(defaults['name'])[:90]
  defaults['separate_widgets']=defaults['separate_widgets'] is True
  for key in ('vr_show','vr_split','show_damage','show_target'):defaults[key]=defaults[key] is True
  positions=defaults.get('widget_positions')
  defaults['widget_positions']={k:list(v) for k,v in positions.items() if k in MetricWidget.TITLES and isinstance(v,list) and len(v)==2 and all(type(n) is int and 0<=n<=16384 for n in v)} if isinstance(positions,dict) else {}
  if not isinstance(defaults['sound_path'],str) or len(defaults['sound_path'])>4096:defaults['sound_path']=''
  return defaults
 def refresh_identity(self,force=False):
  """Check a local VRChat login event; never assume someone else's joined name."""
  if not self.overlay_cfg.get('auto_name',True) and not force:
   self.identity_status='手入力モード';return self.identity_status
  result=detect_identity(LOG)
  self.identity_status=result.message
  self.identity_log=result.log_path
  if self.overlay_cfg.get('auto_name',True):
   previous=self.overlay_cfg.get('name','')
   if previous!=result.name:
    # A missing/stale authentication must disable targeting alerts.
    self.overlay_cfg['name']=result.name
    self.meter.configure(result.name,self.overlay_cfg['seconds'])
    self.save(quiet=True)
    self.revision+=1
  return result.message if not result.name else result.message+'：'+result.name
 def periodic_identity_refresh(self):
  if self.overlay_cfg.get('auto_name',True):self.refresh_identity()
  if self.root.winfo_exists():self.root.after(15000,self.periodic_identity_refresh)
 def hide_overlay_from_window(self):
  self.toggle_hud(False);self.save(quiet=True);self.revision+=1
 def hide_party_hud_from_window(self):
  self.overlay_cfg['show_party']=False;self.refresh_party_hud();self.save(quiet=True);self.revision+=1
 def refresh_party_hud(self):
  visible=bool(self.overlay_cfg.get('show') and self.overlay_cfg.get('show_party',True) and self.party_rows)
  if visible:
   if self.party_hud is None or not self.party_hud.winfo_exists():self.party_hud=PartyHUD(self)
   self.party_hud.refresh(self.party_rows,self.overlay_cfg.get('opacity',92));self.party_hud.deiconify()
  elif self.party_hud is not None and self.party_hud.winfo_exists():self.party_hud.withdraw()
 def refresh_metric_widgets(self,v):
  enabled=bool(self.overlay_cfg.get('show') and self.overlay_cfg.get('separate_widgets'))
  w=lookup_weakness(v['boss'],str(BASE/'boss_weakness_data.txt')) if enabled and v.get('mode')=='boss' else {}
  changes=[('弱' if e['kind']=='weak' else '耐')+e['name']+' '+e['value'] for e in w.get('elements',[]) if e['kind']!='neutral']
  weak='  '.join(changes) if changes else (' / '.join(w.get('notes',[])[:2]) or ('すべて等倍' if w.get('available') else '未登録'))
  values={
   'weakness':(enabled and self.overlay_cfg.get('show_weakness',True) and v.get('mode')=='boss',weak),
   'tokens':(enabled and v.get('mode')=='stage','取得 %d / 出現 %d'%(v.get('tokens_collected',0),v.get('tokens_spawned',0))),
   'dummy':(enabled and v.get('mode')=='break' and v.get('dummy_hits',0)>0,'DPS %.1f / 合計 %.0f'%(v.get('dummy_dps',0),v.get('dummy_damage',0))),
   'damage':(self.overlay_cfg.get('show_damage',False),'DPS %.1f  /  ボス %.0f  /  合計 %.0f'%(v.get('dps',0),v.get('boss_damage',0),v.get('total_damage',0))),
   'target':(self.overlay_cfg.get('show_target',False),'あなたが狙われています！' if v.get('is_targeted') else 'ターゲット: '+str(v.get('target','未検出'))[:36])}
  positions=self.overlay_cfg['widget_positions']
  for index,(kind,(visible,value)) in enumerate(values.items()):
   widget=self.extra_widgets.get(kind)
   if visible:
    if widget is None or not widget.winfo_exists():
     default={'damage':[48,75],'target':[380,75]}.get(kind,[430,250+index*95])
     widget=MetricWidget(self,kind,positions.get(kind,default));self.extra_widgets[kind]=widget
    widget.refresh(value,self.overlay_cfg.get('opacity',92));widget.deiconify()
   elif widget is not None and widget.winfo_exists():widget.withdraw()
 def toggle_hud(self,visible):
  self.overlay_cfg['show']=bool(visible)
  if visible:
   if self.hud is None or not self.hud.winfo_exists():
    self.hud=BattleHUD(self)
   self.hud.deiconify();self.hud.lift()
  elif self.hud is not None and self.hud.winfo_exists():self.hud.withdraw()
  self.refresh_party_hud()
  self.refresh_metric_widgets(self.meter.snapshot())
 def update_hud_loop(self):
  for _ in range(100):
   try:generation,kind,value=self.combat_events.get_nowait()
   except queue.Empty:break
   if generation!=self._watch_generation or self.stop.is_set():continue
   if kind=='boss':
    if value not in self.discovered_bosses:
     self.discovered_bosses.add(value);self.cfg['discovered_bosses']=sorted(self.discovered_bosses);self.revision+=1
   elif kind=='result':self.record_result(value)
   elif kind in ('target_on','target_off','target_switch'):
    if self.overlay_cfg.get('alert',True) and (kind!='target_switch' or self.overlay_cfg.get('other_alerts',False)):
     play_target_tone(kind,int(self.overlay_cfg.get('volume',65)),self.overlay_cfg.get('sound_path',''))
  snapshot=self.meter.snapshot()
  if getattr(self,'vr_hud',None):self.vr_hud.update(snapshot)
  if self.hud is not None and self.hud.winfo_exists():
   self.hud.refresh(snapshot,self.overlay_cfg)
  self.refresh_metric_widgets(snapshot)
  if self.root.winfo_exists():self.root.after(350,self.update_hud_loop)
 def record_result(self,result):
  try:self.results.append(result)
  except (OSError,ValueError) as exc:self.status.set('戦闘記録を保存できませんでした: '+str(exc)[:120])
 def finish_monitor(self,reason):
  self.stop.set()
  if self.worker and self.worker.is_alive():self.worker.join(timeout=.75)
  # Keep completed records that arrived just before monitoring stopped.
  while True:
   try:generation,kind,value=self.combat_events.get_nowait()
   except queue.Empty:break
   if generation==self._watch_generation and kind=='result':self.record_result(value)
  prior=self.meter.interrupt(reason)
  if prior:self.record_result(prior[1])
 def build(self):
  BG='#0b1020';PANEL='#17263d';FIELD='#263650';EDGE='#304363';TEXT='#edf4ff';MUTED='#9cb0cc';ACCENT='#49e7da'
  style=ttk.Style(self.root)
  try:style.theme_use('clam')
  except tk.TclError:pass
  style.configure('.',font=('Segoe UI',11),background=BG,foreground=TEXT)
  style.configure('TFrame',background=BG)
  style.configure('TLabel',background=BG,foreground=TEXT)
  style.configure('Muted.TLabel',background=BG,foreground=MUTED)
  style.configure('Title.TLabel',background=BG,foreground=ACCENT,font=('Segoe UI',20,'bold'))
  style.configure('Heading.TLabel',background=BG,foreground=TEXT,font=('Segoe UI',14,'bold'))
  style.configure('TButton',background=FIELD,foreground=TEXT,padding=(12,10),bordercolor=EDGE,font=('Segoe UI',11,'bold'))
  style.map('TButton',background=[('active','#34516d')])
  style.configure('Action.TButton',background=ACCENT,foreground='#061521',padding=(15,17),font=('Segoe UI',15,'bold'))
  style.map('Action.TButton',background=[('active','#86ffed')])
  style.configure('TEntry',fieldbackground=FIELD,foreground=TEXT,insertcolor=TEXT,padding=8)
  style.configure('TCombobox',fieldbackground=FIELD,background=FIELD,foreground=TEXT,arrowcolor=ACCENT,padding=7)
  style.map('TCombobox',fieldbackground=[('readonly',FIELD)],foreground=[('readonly',TEXT)],selectbackground=[('readonly',FIELD)],selectforeground=[('readonly',TEXT)])
  style.configure('TNotebook',background=BG,borderwidth=0)
  style.configure('TNotebook.Tab',background=FIELD,foreground=MUTED,padding=(18,12),font=('Segoe UI',11,'bold'))
  style.map('TNotebook.Tab',background=[('selected',PANEL)],foreground=[('selected',ACCENT)])
  style.configure('Horizontal.TScale',background=BG,troughcolor=FIELD)
  style.configure('TScrollbar',background=FIELD,troughcolor=BG)
  style.configure('TLabelframe',background=BG,foreground=TEXT)
  style.configure('TLabelframe.Label',background=BG,foreground=ACCENT)
  style.configure('TCheckbutton',background=BG,foreground=TEXT)
  self.root.option_add('*TCombobox*Listbox.background',FIELD)
  self.root.option_add('*TCombobox*Listbox.foreground',TEXT)
  self.root.option_add('*TCombobox*Listbox.selectBackground','#34516d')
  self.lobby=tk.StringVar(value=self.cfg.get('lobby',''))
  # Create all existing music variables, even when their editors are not visible.
  for difficulty in self.DIFFICULTIES:
   for phase in self.PHASES:
    key=difficulty+'|'+phase
    self.vars[('music',key)]=tk.StringVar(value=self.cfg.get('music',{}).get(key,''))
    self.vars[('fallback',key)]=tk.StringVar(value=self.cfg.get('fallback',{}).get(key,''))
  self.boss_map=dict(self.cfg.get('boss',{}))
  self.boss_fallback_map={k[5:]:v for k,v in self.cfg.get('fallback',{}).items() if k.startswith('boss|')}
  self.boss_name=tk.StringVar(value=self.BOSS_CHOICES[0]);self.boss_track=tk.StringVar()
  self.boss_name.trace_add('write',self.boss_name_changed)
  self._save_after=None;self._loading_editor=False;self._saving=False;self._watch_generation=0
  outer=ttk.Frame(self.root,padding=16);outer.pack(fill='both',expand=True)
  ttk.Label(outer,text='◈  ECLIPTICA',style='Title.TLabel').pack(anchor='w')
  ttk.Label(outer,text='MUSIC COMPANION   •   v1.8.2 Lite',style='Muted.TLabel').pack(anchor='w',pady=(0,12))
  self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
  # A shared feedback bar remains visible regardless of the selected tab.
  # The message is derived from the existing status variable so every existing
  # command benefits without replacing individual button callbacks.
  self.feedback_text=tk.StringVar(value='● 準備完了 — ボタン操作の結果がここに表示されます')
  self.feedback_color=tk.StringVar(value='#49e7da')
  self._feedback_timer=None
  self._feedback_last=''
  self.status.trace_add('write',self._on_status_change)

  home=ttk.Frame(self.tabs,padding=16);self.tabs.add(home,text='🏠 ホーム')
  ttk.Label(home,text='ゲームに合わせて音楽を流そう！',style='Heading.TLabel').pack(anchor='center',pady=(6,15))
  ttk.Button(home,text='▶  音楽をスタート！',style='Action.TButton',command=self.quick_start).pack(fill='x',ipady=8)
  ttk.Label(home,text='① 曲を設定 → ② 音楽をスタート → ③ プレイヤーで再生を有効化',style='Muted.TLabel').pack(anchor='center',pady=(9,15))
  actions=ttk.Frame(home);actions.pack(fill='x',pady=4)
  ttk.Button(actions,text='■  音楽を止める',command=self.stop_music).pack(side='left',fill='x',expand=True,padx=(0,5))
  ttk.Button(actions,text='■  自動切替を止める',command=self.stop_watch).pack(side='left',fill='x',expand=True,padx=(5,0))
  ttk.Label(home,text='ゲームと同じ難易度を選択（自動判定は未対応）',style='Heading.TLabel').pack(anchor='w',pady=(20,7))
  row=ttk.Frame(home);row.pack(fill='x')
  ttk.Label(row,text='難易度').pack(side='left')
  ttk.Combobox(row,textvariable=self.difficulty,values=self.DIFFICULTIES,state='readonly',width=20).pack(side='left',padx=(8,20))
  ttk.Label(row,text='場面').pack(side='left')
  ttk.Combobox(row,textvariable=self.phase_choice,values=self.PHASES,state='readonly',width=12).pack(side='left',padx=8)
  ttk.Button(home,text='▶ 選んだ場面の曲を試す',command=self.play_selected).pack(anchor='w',pady=(10,0))
  ttk.Label(home,text='音量',style='Heading.TLabel').pack(anchor='w',pady=(18,3))
  row=ttk.Frame(home);row.pack(fill='x')
  ttk.Scale(row,from_=0,to=100,variable=self.volume,orient='horizontal',command=self.on_volume_change).pack(side='left',fill='x',expand=True)
  ttk.Label(row,textvariable=self.volume,width=5).pack(side='left',padx=8)
  ttk.Label(home,textvariable=self.event_status,style='Muted.TLabel',wraplength=680).pack(fill='x',pady=(18,4))
  ttk.Label(home,textvariable=self.player_status,style='Muted.TLabel',wraplength=680).pack(fill='x',pady=4)
  ttk.Label(home,textvariable=self.status,wraplength=680).pack(fill='x',pady=4)
  ttk.Button(home,text='♫ プレイヤーを表示',command=self.open_player).pack(anchor='w',pady=(12,0))
  music=ttk.Frame(self.tabs,padding=16);self.tabs.add(music,text='🎵 曲を設定')
  ttk.Label(music,text='① 難易度と場面を選ぶ',style='Heading.TLabel').pack(anchor='w',pady=(2,8))
  rr=ttk.Frame(music);rr.pack(fill='x')
  self.edit_diff=tk.StringVar(value=self.DIFFICULTIES[0]);self.edit_phase=tk.StringVar(value='戦闘')
  ttk.Combobox(rr,textvariable=self.edit_diff,values=self.DIFFICULTIES,state='readonly',width=23).pack(side='left',padx=(0,8))
  ttk.Combobox(rr,textvariable=self.edit_phase,values=self.PHASES,state='readonly',width=16).pack(side='left')
  ttk.Label(music,text='「戦闘」は道中の音楽です。',style='Muted.TLabel').pack(anchor='w',pady=(6,18))
  ttk.Label(music,text='② YouTubeのURLを貼る（またはMP3を選ぶ）',style='Heading.TLabel').pack(anchor='w')
  rr=ttk.Frame(music);rr.pack(fill='x',pady=(9,7))
  self.music_editor=tk.StringVar()
  ttk.Entry(rr,textvariable=self.music_editor).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(rr,text='📁 ファイル',command=lambda:self.pick(self.music_editor)).pack(side='left')
  preview=ttk.Frame(music);preview.pack(fill='x',pady=(2,17))
  ttk.Button(preview,text='▶ この曲を試す',command=lambda:self.play(self.music_editor.get(),self.fallback_editor.get())).pack(side='left')
  ttk.Button(preview,text='■ 再生を停止',command=self.stop_music).pack(side='left',padx=8)
  ttk.Button(preview,text='💾 設定を保存',command=self.save).pack(side='left',padx=8)
  ttk.Label(music,text='予備のMP3（YouTubeが再生できないとき用）',style='Heading.TLabel').pack(anchor='w')
  rr=ttk.Frame(music);rr.pack(fill='x',pady=(8,10))
  self.fallback_editor=tk.StringVar()
  ttk.Entry(rr,textvariable=self.fallback_editor).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(rr,text='📁 ファイル',command=lambda:self.pick(self.fallback_editor)).pack(side='left')
  ttk.Label(music,text='自動保存にも対応。右上ではなく、上の「設定を保存」で確認できます。',style='Muted.TLabel').pack(anchor='w',pady=(8,0))
  self.edit_diff.trace_add('write',lambda *_:self.load_music_editor())
  self.edit_phase.trace_add('write',lambda *_:self.load_music_editor())
  self.music_editor.trace_add('write',lambda *_:self.update_music_editor())
  self.fallback_editor.trace_add('write',lambda *_:self.update_music_editor())
  self.add_mp3_import_panel(music,lambda:self.music_editor)
  self.load_music_editor()
  boss=ttk.Frame(self.tabs,padding=16);self.tabs.add(boss,text='👑 ボスの曲')
  ttk.Label(boss,text='① ボスを選ぶ',style='Heading.TLabel').pack(anchor='w',pady=(3,8))
  rr=ttk.Frame(boss);rr.pack(fill='x')
  ttk.Combobox(rr,textvariable=self.boss_name,values=sorted(set(self.BOSS_CHOICES)|set(self.boss_map),key=str.casefold),state='normal',width=28).pack(side='left',fill='x',expand=True)
  ttk.Label(boss,text='候補にいないボスは名前を直接入力できます。',style='Muted.TLabel').pack(anchor='w',pady=(6,18))
  ttk.Label(boss,text='② ボスの曲を登録する',style='Heading.TLabel').pack(anchor='w')
  rr=ttk.Frame(boss);rr.pack(fill='x',pady=(9,8))
  ttk.Entry(rr,textvariable=self.boss_track).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(rr,text='📁 ファイル',command=lambda:self.pick(self.boss_track)).pack(side='left')
  ttk.Label(boss,text='③ 予備のMP3（YouTubeが再生できないとき用）',style='Heading.TLabel').pack(anchor='w',pady=(12,8))
  rr=ttk.Frame(boss);rr.pack(fill='x',pady=(0,12))
  self.boss_fallback=tk.StringVar()
  ttk.Entry(rr,textvariable=self.boss_fallback).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(rr,text='📁 MP3を選ぶ',command=lambda:self.pick(self.boss_fallback)).pack(side='left')
  controls=ttk.Frame(boss);controls.pack(fill='x',pady=(3,12))
  ttk.Button(controls,text='▶ この曲を試す',command=lambda:self.play(self.boss_track.get(),self.boss_fallback.get())).pack(side='left')
  ttk.Button(controls,text='■ 再生を停止',command=self.stop_music).pack(side='left',padx=8)
  ttk.Button(controls,text='💾 設定を保存',command=self.save).pack(side='left',padx=8)
  ttk.Label(boss,text='自動保存対応。空欄なら難易度別のボスBGMが流れます。',style='Muted.TLabel',wraplength=680).pack(anchor='w')
  self.add_mp3_import_panel(boss,lambda:self.boss_track)
  self.boss_track.trace_add('write',lambda *_:self.update_boss_editor())
  self.boss_fallback.trace_add('write',lambda *_:self.update_boss_editor())
  self.boss_name_changed()
  advanced=ttk.Frame(self.tabs,padding=16);self.tabs.add(advanced,text='⚙ その他')
  ttk.Label(advanced,text='ロビーの曲',style='Heading.TLabel').pack(anchor='w')
  rr=ttk.Frame(advanced);rr.pack(fill='x',pady=(8,15))
  ttk.Entry(rr,textvariable=self.lobby).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(rr,text='📁 ファイル',command=lambda:self.pick(self.lobby)).pack(side='left')
  lobby_controls=ttk.Frame(advanced);lobby_controls.pack(fill='x',pady=(0,16))
  ttk.Button(lobby_controls,text='▶ ロビーの曲を試す',command=lambda:self.play(self.lobby.get())).pack(side='left')
  ttk.Button(lobby_controls,text='■ 再生を停止',command=self.stop_music).pack(side='left',padx=8)
  ttk.Label(advanced,text='VRChatのログ（通常は自動検出）',style='Heading.TLabel').pack(anchor='w')
  rr=ttk.Frame(advanced);rr.pack(fill='x',pady=(8,15))
  ttk.Entry(rr,textvariable=self.log).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(rr,text='最新を探す',command=self.detect).pack(side='left')
  ttk.Label(advanced,text='曲の切替時間（秒）',style='Heading.TLabel').pack(anchor='w')
  ttk.Spinbox(advanced,from_=0,to=15,increment=.5,textvariable=self.fade,width=9).pack(anchor='w',pady=(8,15))
  ttk.Button(advanced,text='設定を保存',command=self.save).pack(anchor='w',pady=(0,12))
  rr=ttk.Frame(advanced);rr.pack(fill='x')
  ttk.Button(rr,text='バックアップ',command=self.export_config).pack(side='left')
  ttk.Button(rr,text='復元',command=self.import_config).pack(side='left',padx=8)
  ttk.Button(rr,text='保存先を開く',command=self.open_config_dir).pack(side='left')
  self.add_mp3_import_panel(advanced,lambda:self.lobby)
  self.lobby.trace_add('write',lambda *_:self.schedule_save())
  self.log.trace_add('write',lambda *_:self.schedule_save())
  self.fade.trace_add('write',lambda *_:self.schedule_save())
  self.volume.trace_add('write',lambda *_:self.schedule_save())
  self.feedback_frame=tk.Frame(outer,bg='#17263d',highlightbackground='#304363',highlightthickness=1)
  self.feedback_frame.pack(fill='x',pady=(10,0))
  self.feedback_icon=tk.Label(self.feedback_frame,text='✓',bg='#17263d',fg='#49e7da',font=('Segoe UI',15,'bold'))
  self.feedback_icon.pack(side='left',padx=(12,6),pady=9)
  self.feedback_label=tk.Label(self.feedback_frame,textvariable=self.feedback_text,bg='#17263d',fg='#edf4ff',font=('Segoe UI',11,'bold'),anchor='w',justify='left',wraplength=700)
  self.feedback_label.pack(side='left',fill='x',expand=True,pady=9)
  self.feedback_frame.bind('<Configure>',lambda e:self.feedback_label.configure(wraplength=max(180,e.width-85)))
 def _on_status_change(self,*_):
  message=self.status.get().strip()
  if not message:return
  # Keep feedback concise and avoid claiming that the player confirmed an action.
  is_error=any(w in message for w in ('失敗','エラー','見つかりません','未設定','できません','開けません'))
  is_wait=any(w in message for w in ('監視中','起動しました','切替指示','指示しました','変換しています'))
  icon='!' if is_error else ('…' if is_wait else '✓')
  self.feedback_text.set(message)
  self.feedback_icon.configure(text=icon,fg='#ffb86b' if is_error else '#49e7da')
  if self._feedback_timer is not None:
   self.root.after_cancel(self._feedback_timer)
  self._feedback_timer=self.root.after(6500,self._reset_feedback)
 def _reset_feedback(self):
  self._feedback_timer=None
  self.feedback_text.set('● 準備完了 — 操作するとここに結果が表示されます')
  self.feedback_icon.configure(text='✓',fg='#49e7da')

 def add_mp3_import_panel(self,parent,target_var):
  # Lite distribution intentionally has no network downloader/FFmpeg executable.
  section=ttk.LabelFrame(parent,text='音楽ファイルの登録（セキュリティ点検版）',padding=10)
  section.pack(fill='x',pady=(20,8))
  ttk.Label(section,text='MP3へのダウンロード・変換はこの配布版では無効です。お手持ちの音声ファイルは上の「ファイル」ボタンから登録できます。YouTube URLの再生は引き続き可能です。',style='Muted.TLabel',wraplength=700).pack(anchor='w')
 def load_music_editor(self):
  self._loading_editor=True
  key=self.edit_diff.get()+'|'+self.edit_phase.get()
  self.music_editor.set(self.vars[('music',key)].get())
  self.fallback_editor.set(self.vars[('fallback',key)].get())
  self._loading_editor=False
 def update_music_editor(self):
  if self._loading_editor:return
  key=self.edit_diff.get()+'|'+self.edit_phase.get()
  self.vars[('music',key)].set(self.music_editor.get())
  self.vars[('fallback',key)].set(self.fallback_editor.get())
  self.schedule_save()
 def boss_name_changed(self,*_):
  if not hasattr(self,'boss_track'):return
  self._loading_editor=True
  self.boss_track.set(self.boss_map.get(self.boss_name.get().strip(),''))
  self.boss_fallback.set(self.boss_fallback_map.get(self.boss_name.get().strip(),''))
  self._loading_editor=False
 def update_boss_editor(self):
  if self._loading_editor:return
  name=self.boss_name.get().strip()
  if not name:return
  if self.boss_track.get().strip():self.boss_map[name]=self.boss_track.get().strip()
  else:self.boss_map.pop(name,None)
  if self.boss_fallback.get().strip():self.boss_fallback_map[name]=self.boss_fallback.get().strip()
  else:self.boss_fallback_map.pop(name,None)
  self.schedule_save()
 def schedule_save(self):
  if not hasattr(self,'_save_after') or self._saving:return
  if self._save_after is not None:self.root.after_cancel(self._save_after)
  self._save_after=self.root.after(750,self.autosave)
 def autosave(self):
  self._save_after=None
  self.save(quiet=True)
 OFFICIAL_BOSS_CHOICES=('Jim C. Bringer','Neo Pilot','Bravera','O-One','Pandora','Abaddon','Khepri','Mephiel','Irides','Golden Grouch','Corus','Yuki','Cone Head','Despair','M-41-D','Melgor Johnson','Amaziah',"Jacked O' Lantern",'The Black Lily','NX-Obsidian','Middleman','Steven','Kodama','The Gravetender','Vesra','Pride','Maxipuss','Darkmouth','Kakarot','NaN','Beelzebub','Buff Noob')
 BOSS_CHOICES=('Stage_Bringer', 'JimBringer', 'FlyLord', 'Kakarot', 'Nan', 'BuffNoob', 'Pride', 'Steven', 'Amaziah', 'JackedPumpkin', 'QueenVolt', 'M41D', 'Corus', 'CorusPhase2', 'Yuki', 'YukiPhase2', 'Pandora', 'Mephiel', 'MephielPhase2', 'OnyxPilot', 'NeoPilot', 'Gilgamesh', 'GilgameshPhase2', 'GilgameshPhase3', 'GoldenGrouch', 'DarkMouth')
 DIFFICULTIES=('Primal','Penumbra','Antumbra','Umbra','Eclipse','Eye of the Eclipse')
 PHASES=('戦闘','準備','ボス','終了','休憩')
 def load_config(self):
  if not CFG.exists():return add_sample_music_once(json.loads(json.dumps(DEFAULT)),self.DIFFICULTIES)
  try:
   obj=json.loads(CFG.read_text('utf-8'))
   if not isinstance(obj,dict):raise ValueError('設定の形式が正しくありません')
   cfg=json.loads(json.dumps(DEFAULT));cfg.update(obj)
   if not isinstance(cfg.get('music'),dict) or not isinstance(cfg.get('boss'),dict) or not isinstance(cfg.get('fallback'),dict):raise ValueError('曲設定が正しくありません')
   return add_sample_music_once(cfg,self.DIFFICULTIES)
  except Exception:
   try:CFG.rename(CFG.with_name('settings_broken_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json'))
   except OSError:pass
   return add_sample_music_once(json.loads(json.dumps(DEFAULT)),self.DIFFICULTIES)
 def export_config(self):
  if not self.save():return
  target=filedialog.asksaveasfilename(title='設定をバックアップ',defaultextension='.json',initialfile='EclipticaMusicCompanion_backup.json',filetypes=[('JSON','*.json')])
  if target:
   try:shutil.copy2(CFG,target);self.status.set('バックアップを保存しました');messagebox.showinfo('完了','設定を書き出しました。')
   except Exception as e:messagebox.showerror('失敗',str(e))
 def import_config(self):
  source=filedialog.askopenfilename(title='設定を復元',filetypes=[('JSON','*.json')])
  if not source:return
  try:
   obj=json.loads(Path(source).read_text('utf-8'))
   if not isinstance(obj,dict) or not isinstance(obj.get('music',{}),dict) or not isinstance(obj.get('boss',{}),dict):raise ValueError('対応していない設定ファイルです')
   if not messagebox.askyesno('確認','現在の設定をバックアップの内容で置き換えますか？'):return
   restored=json.loads(json.dumps(DEFAULT));restored.update(obj)
   if not isinstance(restored.get('fallback'),dict):raise ValueError('予備MP3の設定が正しくありません')
   # Restore means exactly the user's backup; don't add samples on next start.
   restored['sample_music_initialized']=True
   self.cfg=restored
   self.overlay_cfg=self._overlay_options()
   self.vr_hud.enable(self.overlay_cfg['vr_show'],self.overlay_cfg['vr_split'])
   self.meter.configure(self.overlay_cfg['name'],self.overlay_cfg['seconds'])
   if self.overlay_cfg.get('auto_name',True):self.refresh_identity()
   self.discovered_bosses=set(restored.get('discovered_bosses',[])) if isinstance(restored.get('discovered_bosses'),list) else set()
   self.toggle_hud(bool(self.overlay_cfg['show']))
   self._loading_editor=True
   try:
    for (group,key),var in self.vars.items():
     var.set(restored.get(group,{}).get(key,''))
    self.boss_map=dict(restored.get('boss',{}))
    self.boss_fallback_map={k[5:]:v for k,v in restored.get('fallback',{}).items() if k.startswith('boss|')}
    self.lobby.set(restored.get('lobby',''))
    self.log.set(restored.get('log',''))
    self.fade.set(restored.get('fade',2))
    self.volume.set(restored.get('volume',80))
    self.difficulty.set(restored.get('active_difficulty','') if restored.get('active_difficulty') in self.DIFFICULTIES else '')
   finally:self._loading_editor=False
   self.load_music_editor();self.boss_name_changed()
   self.on_volume_change();self.save(quiet=True);self.revision+=1
   self.status.set('バックアップから設定を復元しました')
   messagebox.showinfo('復元完了','設定を復元しました。')
  except Exception as e:messagebox.showerror('復元失敗',str(e))
 def open_config_dir(self):
  try:os.startfile(str(CFG.parent));self.status.set('設定の保存先を開きました')
  except Exception as e:messagebox.showerror('開けませんでした',str(e))
 def play_selected(self,difficulty=None,phase=None):
  key=(self.difficulty.get() if difficulty is None else difficulty)+'|'+(self.phase_choice.get() if phase is None else phase)
  v=self.vars.get(('music',key));track=v.get().strip() if v else ''
  if not track:self.status.set('選択した難易度・フェーズの曲が未設定です');return
  self.play(track,self.get_fallback(key))
 def get_fallback(self,key):
  v=self.vars.get(('fallback',key));return v.get().strip() if v else ''
 def play_auto(self,phase):
  difficulty=self.difficulty.get()
  if difficulty not in self.DIFFICULTIES:
   self.stop_music();self.status.set('ゲームと同じ難易度を選択してください');return
  key=difficulty+'|'+phase
  v=self.vars.get(('music',key));track=v.get().strip() if v else ''
  if track:self.play(track,self.get_fallback(key))
  else:self.stop_music();self.status.set(f'{difficulty} / {phase} の曲は未設定のため停止しました')
 def pick(self,v):
  p=filedialog.askopenfilename(filetypes=[('音楽','*.mp3 *.wav *.ogg *.m4a')]);
  if p:
   v.set(p)
   self.status.set('音楽ファイルを選びました。自動保存されます')
 def save(self,quiet=False):
  if self._saving:return False
  self._saving=True
  try:
   if self._save_after is not None:
    self.root.after_cancel(self._save_after);self._save_after=None
   if not self.unified and hasattr(self,'music_editor') and not getattr(self,'_loading_editor',False):self.update_music_editor()
   if not self.unified and hasattr(self,'boss_track') and not getattr(self,'_loading_editor',False):self.update_boss_editor()
   music={};boss=dict(self.boss_map);fallback={}
   for (group,k),v in self.vars.items():
    if group=='music' and v.get().strip():music[k]=v.get().strip()
    elif group=='fallback' and v.get().strip():fallback[k]=v.get().strip()
   fallback.update({'boss|'+name:path for name,path in self.boss_fallback_map.items() if path.strip()})
   updated=dict(self.cfg)
   updated.update(music=music,boss=boss,fallback=fallback,lobby=self.lobby.get().strip())
   try:fade=max(0,min(15,float(self.fade.get())))
   except (ValueError,tk.TclError):fade=2.0
   updated.update(log=self.log.get(),fade=fade,volume=int(self.volume.get()),overlay=dict(self.overlay_cfg),active_difficulty=self.difficulty.get(),discovered_bosses=sorted(self.discovered_bosses))
   tmp=CFG.with_suffix('.tmp');tmp.write_text(json.dumps(updated,ensure_ascii=False,indent=2),'utf-8');tmp.replace(CFG);self.cfg=updated
   self.status.set('設定を保存しました') if not quiet else None
   return True
  except Exception as e:
   message='設定を保存できませんでした: '+str(e)[:180]
   self.status.set(message)
   # The Tk window is hidden in unified mode; a modal error there can block
   # the UI request queue behind the browser until its timeout.
   if not self.unified:messagebox.showerror('保存失敗',str(e))
   return False
  finally:self._saving=False
 def detect(self):
  files=sorted(LOG.glob('output_log_*.txt'),key=session_sort_key,reverse=True)
  if files:self.log.set(str(files[0]));self.status.set('最新ログを選択しました');return True
  self.status.set('VRChatログが見つかりません。VRChatを起動してから再度お試しください')
  if not self.unified:messagebox.showwarning('ログ未検出','VRChatを起動してから再度お試しください。')
  return False
 def on_volume_change(self,_=None):
  try:
   with lock:state['volume']=max(0,min(100,int(float(self.volume.get()))))/100;state['volume_seq']+=1
  except (ValueError,tk.TclError):pass
 def refresh_player_status(self):
  with lock:
   msg=state.get('player_status','');seen=state.get('player_seen',0)
  if seen and time.time()-seen<5:self.player_status.set('プレイヤー: '+msg)
  elif self.player_launched:self.player_status.set('プレイヤー: 接続待ち／ウィンドウを確認してください')
  else:self.player_status.set('プレイヤー: 未起動')
  if self.root.winfo_exists():self.root.after(1200,self.refresh_player_status)
 def open_player(self):
  # Only a deliberate click may relaunch a player. Never launch on watch start.
  # A dedicated Edge profile prevents reuse of the user's normal Edge windows.
  if self.player_launched:
   if self.player_process is None or self.player_process.poll() is None:
    self.status.set('プレイヤーは起動済みです。タスクバーのEdgeを確認してください')
    return
   self.player_launched=False
  url=f'http://127.0.0.1:{self.port}/'
  candidates=[
   Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
   Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe',
   Path(os.environ.get('LOCALAPPDATA',''))/'Microsoft/Edge/Application/msedge.exe'
  ]
  edge=next((str(x) for x in candidates if x.is_file()),None)
  if not edge:
   messagebox.showerror('プレイヤー起動失敗','Microsoft Edgeが見つかりません。');return
  try:
   profile=CFG.parent/'edge_player_profile'
   profile.mkdir(parents=True,exist_ok=True)
   self.player_process=subprocess.Popen([edge,'--user-data-dir='+str(profile),'--no-first-run','--app='+url,'--window-size=570,400'],close_fds=True)
   self.player_launched=True
   self.status.set('専用BGMプレイヤーを起動しました（監視開始で増えません）')
  except Exception as e:
   messagebox.showerror('プレイヤー起動失敗',str(e))
 def quick_start(self):
  # One-click setup: launch the player and begin log monitoring.
  # Browser autoplay policy still requires the first unlock click in Edge.
  self.open_player()
  self.start()
  if self.worker and self.worker.is_alive():self.status.set('監視中です。最初だけプレイヤーの「再生を有効化」を押してください')
 def play(self,track,fallback=''):
  track=track.strip()
  if not track:self.status.set('曲を設定してください');return False
  track=resolve_demo_track(track)
  fallback=resolve_demo_track(fallback.strip())
  is_youtube=bool(youtube_id(track))
  if not is_youtube and not Path(track).is_file():
   self.stop_music();self.status.set('有効なYouTube動画のURLか存在する音楽ファイルを設定してください');return False
  # Preserve explicit user fallbacks; use a bundled original loop only for the
  # preset videos if the user hasn't specified one.
  if is_youtube and not fallback:fallback=sample_fallback(track)
  if Path(track).is_file():
   with lock:allowed_media.add(str(Path(track).resolve()))
  if fallback and Path(fallback).is_file() and Path(fallback).suffix.lower() in ('.mp3','.wav','.ogg','.m4a'):
   with lock:allowed_media.add(str(Path(fallback).resolve()))
  try:fade=max(0,min(15,float(self.fade.get())))
  except (ValueError,tk.TclError):fade=2.0
  with lock:state.update(seq=state['seq']+1,track=track,fade=fade,volume=max(0,min(100,int(self.volume.get())))/100,stop=False,fallback=fallback)
  self.status.set('▶ 再生を指示しました: '+track[:65])
  return True
 def stop_music(self):
  with lock:state.update(seq=state['seq']+1,stop=True)
  self.status.set('■ 停止を指示しました（プレイヤーに反映されます）')
 def auto_start(self):
  if self.cfg.get('auto',True):self.start()
 def start(self):
  if self.difficulty.get() not in self.DIFFICULTIES:
   self.status.set('音楽を始める前に、ゲームと同じ難易度を選択してください');return False
  if not self.save():return False
  # Prefer the current VRChat session's newest log over a persisted stale path.
  files=sorted(LOG.glob('output_log_*.txt'),key=session_sort_key,reverse=True)
  configured=Path(self.log.get()) if self.log.get().strip() else None
  p=files[0] if files else configured
  if p is None or not p.is_file():
   self.status.set('VRChatログが見つかりません。VRChatを起動してください');return False
  self.log.set(str(p))
  self.finish_monitor('監視再開')
  self._watch_generation+=1
  self.meter.reset();self.meter.configure(self.overlay_cfg['name'],self.overlay_cfg['seconds'])
  for pending in (self.combat_events,self.watch_events):
   while True:
    try:pending.get_nowait()
    except queue.Empty:break
  self.stop=threading.Event();self.round=0;self.boss='';self.laststage=''
  self.event_status.set('検知イベント: 待機中（次のゲームイベントから再生）')
  # Read a fixed historical snapshot before monitoring subsequent bytes. This
  # prevents live lines from being replayed twice or overwriting newer state.
  offset=self.resume_from_log(p)
  self.worker=threading.Thread(target=self.watch,args=(p,self.stop,offset,self._watch_generation),daemon=True)
  self.worker.start();self.status.set('監視中: '+p.name);return True
 def resume_from_log(self,p):
  # The most recent ECLIPTICA state in this VRChat session is a best-effort hint.
  try:
   offset,last_event=read_resume_snapshot(p,self.meter)
   if last_event:
    kind,name=last_event
    if kind=='ボス':self.handle_boss(name)
    elif kind=='ロビー':self.handle_event('途中参加・ロビー','ロビー')
    else:self.handle_event('途中参加・推定'+kind,kind)
   else:
    self.status.set('現在の場面をログから特定できません。次のゲームイベントを待っています')
    if hasattr(self,'event_status'):self.event_status.set('現在の場面は未確認。次のゲームイベントを待っています')
   return offset
  except (OSError,UnicodeError) as e:
   self.status.set('途中参加の状態確認に失敗: '+str(e));return None
 def stop_watch(self):
  self.finish_monitor('監視停止')
  self._watch_generation+=1
  self.status.set('■ 自動切り替えを停止しました')
 def drain_watch_events(self):
  # Only the GUI thread touches Tk; stale events from an old watcher are ignored.
  for _ in range(100):
   try:generation,kind,value=self.watch_events.get_nowait()
   except queue.Empty:break
   if generation!=self._watch_generation or self.stop.is_set():continue
   if kind=='phase':self.handle_event(value[0],value[1])
   elif kind=='boss':self.handle_boss(value)
   elif kind=='log':self.log.set(value)
   elif kind=='status':self.status.set(value)
  if self.root.winfo_exists():self.root.after(50,self.drain_watch_events)
 def watch(self,p,signal,offset=None,generation=None):
  # Read the log off-thread and deliver events through a generation-tagged queue.
  if generation is None:generation=self._watch_generation
  def emit(kind,value):
   if not signal.is_set():self.watch_events.put((generation,kind,value))
  f=None
  try:
   f=p.open('rb')
   if offset is None:f.seek(0,2)
   else:f.seek(offset)
   partial=b'';skipping=False;next_discovery=0.0
   while not signal.is_set():
    line=f.readline(65536)
    if not line:
     if signal.wait(.25):break
     now=time.monotonic()
     if now<next_discovery:continue
     next_discovery=now+1.0
     try:
      # VRChat or log cleanup may truncate a file in place.
      try:current_size=p.stat().st_size
      except OSError:current_size=None
      if current_size is not None and current_size<f.tell():
       f.close();f=p.open('rb');partial=b'';skipping=False
       with self.meter.lock:
        if signal.is_set():break
        previous=self.meter.interrupt('ログ更新')
        if previous:self.combat_events.put((generation,'result',previous[1]))
        self.meter.reset()
       emit('status','ログが更新されたため監視を再開しました: '+p.name)
       continue
      newest=max(LOG.glob('output_log_*.txt'),key=session_sort_key,default=None)
      try:current_key=session_sort_key(p)
      except OSError:current_key=None
      if newest and newest!=p and (current_key is None or session_sort_key(newest)>current_key):
       nf=newest.open('rb')
       try:
        with self.meter.lock:
         if signal.is_set():nf.close();break
         previous=self.meter.interrupt('ログ切替')
         if previous:self.combat_events.put((generation,'result',previous[1]))
         self.meter.reset()
         resume_offset,resume_event=read_resume_snapshot(newest,self.meter)
       except Exception:
        nf.close();raise
       nf.seek(resume_offset)
       f.close();f=nf;p=newest;partial=b'';skipping=False
       emit('log',str(p));emit('status','新しいログへ自動切替: '+p.name)
       if resume_event:
        kind,name=resume_event
        if kind=='ボス':emit('boss',name)
        else:emit('phase',('ログ切替後・推定'+kind,kind))
       else:emit('status','ログ切替後の場面は未確認です。次のゲームイベントを待っています')
     except OSError:pass
     continue
    # Bound memory if a corrupted log contains an exceptionally long line.
    if skipping:
     if line.endswith(b'\n'):skipping=False
     continue
    if len(partial)+len(line)>1_048_576:
     partial=b'';skipping=not line.endswith(b'\n');continue
    partial+=line
    if not partial.endswith(b'\n'):continue
    line=partial.decode('utf-8','replace');partial=b''
    # Keep the live HUD and target alerts updated as new log lines arrive.
    with self.meter.lock:
     if signal.is_set():break
     for transition in self.meter.ingest(line):
      # The HUD consumes boss/target events only; queuing every damage hit
      # would let an ignored backlog grow indefinitely during busy fights.
      if transition[0] in ('boss','target_on','target_off','target_switch','result'):
       self.combat_events.put((generation,transition[0],transition[1]))
    if re.search(r'\[Behaviour\]\s*OnLeftRoom\b',line,re.I):
     emit('phase',('VRChatワールドを退出',None));continue
    if 'ECLIPTICA - now in intermission' in line:
     emit('phase',('休憩開始','休憩'))
    elif 'ECLIPTICA - now in lobby' in line:
     emit('phase',('ロビーに戻りました','ロビー'))
    else:
     stage=re.search(r'ECLIPTICA - now in stage:\s*(.+?)\s+on phase:',line)
     boss=re.search(r'ECLIPTICA - now fighting boss:\s*(.+?)\s+on phase:',line)
     if stage:
      # Never deduplicate by stage name: the same stage may appear in later rounds.
      name=stage.group(1).strip()
      emit('phase',('戦闘開始: '+name,'戦闘'))
     elif boss:
      name=re.sub(r'\(Clone\)$','',boss.group(1).strip(),flags=re.I).strip()
      emit('boss',name)
  except Exception as e:
   emit('status','ログ読み込み失敗: '+str(e))
  finally:
   if f is not None:f.close()
 def handle_event(self,description,phase):
  self.event_status.set('検知イベント: '+description)
  if phase=='ロビー':
   track=self.lobby.get().strip()
   if track:self.play(track)
   else:self.stop_music();self.status.set('ロビーBGMは未設定のため、前の曲を停止しました')
  elif phase is None:self.stop_music()
  else:
   self.phase_choice.set(phase)
   self.play_auto(phase)
 def handle_boss(self,name):
  if name and name not in self.discovered_bosses:
   self.discovered_bosses.add(name);self.revision+=1
  self.event_status.set('検知イベント: ボス開始 '+name)
  self.phase_choice.set('ボス')
  base=re.sub(r'\s*Phase\d+$','',name,flags=re.I).strip()
  # Exact phase name has priority, then a canonical name / its known log alias.
  def canon(v):
   slug=re.sub(r'[^a-z0-9]','',v.casefold())
   aliases={'nan':'nan','buffnoob':'buffnoob','jackedpumpkin':'jackedolantern',
    'stagebringer':'jimcbringer','jimbringer':'jimcbringer',
    'm41d':'m41d','neopilot':'neopilot','goldengrouch':'goldengrouch',
    'darkmouth':'darkmouth'}
   return aliases.get(slug,slug)
  def matching_track(mapping):
   # Do not collapse an explicitly configured phase into the generic track.
   by_exact={k.casefold():v for k,v in mapping.items() if k.strip() and v.strip()}
   direct=by_exact.get(name.casefold())
   if direct:return direct
   for wanted in (canon(base),):
    for key,value in mapping.items():
     if value.strip() and canon(key)==wanted:return value
   return ''
  track=matching_track(self.boss_map)
  if track:self.play(track,matching_track(self.boss_fallback_map))
  else:self.play_auto('ボス')
 def drain_api(self):
  for _ in range(30):
   try:request=API_QUEUE.get_nowait()
   except queue.Empty:break
   request.execute()
  if self.root.winfo_exists():self.root.after(40,self.drain_api)
 def api_config(self):
  music={};fallback={}
  for (group,k),var in self.vars.items():
   if group=='music' and var.get():music[k]=var.get()
   if group=='fallback' and var.get():fallback[k]=var.get()
  fallback.update({'boss|'+k:v for k,v in self.boss_fallback_map.items() if v})
  return {'music':music,'fallback':fallback,'boss':dict(self.boss_map),
   'overlay':dict(self.overlay_cfg),'identity_status':self.identity_status,
   'lobby':self.lobby.get(),'log':self.log.get(),'fade':self.fade.get(),
   'volume':self.volume.get(),'difficulty':self.difficulty.get(),
   'phase':self.phase_choice.get(),'difficulties':list(self.DIFFICULTIES),
   'phases':list(self.PHASES),'boss_choices':sorted(set(self.BOSS_CHOICES)|set(self.OFFICIAL_BOSS_CHOICES)|self.discovered_bosses|set(self.boss_map),key=str.casefold),'revision':self.revision}
 def api_view(self):
  combat=self.meter.snapshot()
  with lock:player_connected=bool(state.get('player_seen') and time.time()-state['player_seen']<5)
  return {'status':self.status.get(),'event':self.event_status.get(),
    'player':self.player_status.get(),'monitoring':bool(self.worker and self.worker.is_alive() and not self.stop.is_set()),
    'revision':self.revision,'volume':self.volume.get(),'combat':combat,'weakness':lookup_weakness(combat['boss'],str(BASE/'boss_weakness_data.txt')),'overlay_visible':bool(self.overlay_cfg['show']),'party_overlay_enabled':bool(self.overlay_cfg.get('show_party',True)),'identity_status':self.identity_status,'vr_status':self.vr_hud.status(),'results':self.results.latest(),'diagnostics':{'player_connected':player_connected,'log_exists':bool(self.log.get().strip() and Path(self.log.get()).is_file())}}
 def api_action(self,d):
  action=d.get('action','')
  if not isinstance(action,str):raise ValueError('不正な操作です')
  def val(name,limit=4096):
   x=d.get(name,'')
   if not isinstance(x,str) or len(x)>limit:raise ValueError(name+'の文字数が不正です')
   return x.strip()
  def must_save(quiet=True):
   if not self.save(quiet=quiet):raise RuntimeError(self.status.get() or '設定を保存できませんでした')
  if action=='party_roster':
   rows=d.get('rows')
   if not isinstance(rows,list) or len(rows)>12:raise ValueError('パーティー表示の人数が不正です')
   clean=[]
   for row in rows:
    if not isinstance(row,dict):raise ValueError('パーティー表示が不正です')
    name=row.get('name','');job=row.get('job','')
    if any(not isinstance(v,str) or len(v)>40 or any(unicodedata.category(ch).startswith('C') for ch in v) for v in (name,job)):
     raise ValueError('パーティー表示名が不正です')
    dps=row.get('dps');damage=row.get('boss_damage')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1_000_000_000_000 for v in (dps,damage)):
     raise ValueError('パーティー集計値が不正です')
    clean.append({'name':name,'job':job,'dps':dps,'boss_damage':damage})
   self.party_rows=clean;self.refresh_party_hud();return 'パーティー表示を更新しました'
  if action=='overlay_detect_name':
   if not self.overlay_cfg.get('auto_name',True):
    return '自動取得をONにしてからお試しください'
   return self.refresh_identity(force=True)
  if action=='overlay_settings':
   own=val('name',90)
   auto_name=d.get('auto_name',True)
   if not isinstance(auto_name,bool):raise ValueError('自動取得の指定が不正です')
   if auto_name:
    # Browser-submitted names are never trusted as proof of local identity.
    own=self.overlay_cfg['name'] if self.overlay_cfg.get('auto_name',True) else ''
   try:seconds=int(d.get('seconds',10));volume=int(d.get('volume',65));opacity=int(d.get('opacity',92))
   except (TypeError,ValueError):raise ValueError('HUDの数値設定が不正です')
   if not 1<=seconds<=15 or not 0<=volume<=100 or not 30<=opacity<=100:raise ValueError('HUDの設定範囲外です')
   for key in ('show','alert','other_alerts'):
    if not isinstance(d.get(key),bool):raise ValueError('HUDのチェック項目が不正です')
   show_weakness=d.get('show_weakness',True)
   if not isinstance(show_weakness,bool):raise ValueError('弱点表示の指定が不正です')
   vr_show=d.get('vr_show',self.overlay_cfg.get('vr_show',False))
   if not isinstance(vr_show,bool):raise ValueError('VR HUDの指定が不正です')
   split_options={key:d.get(key,self.overlay_cfg.get(key,False)) for key in ('vr_split','show_damage','show_target')}
   if any(not isinstance(value,bool) for value in split_options.values()):raise ValueError('個別HUDの指定が不正です')
   show_party=d.get('show_party',self.overlay_cfg.get('show_party',True))
   if not isinstance(show_party,bool):raise ValueError('パーティーHUDの指定が不正です')
   separate_widgets=d.get('separate_widgets',self.overlay_cfg.get('separate_widgets',False))
   if not isinstance(separate_widgets,bool):raise ValueError('ウィジェット配置の指定が不正です')
   sound_path=d.get('sound_path',self.overlay_cfg.get('sound_path',''))
   if not isinstance(sound_path,str) or len(sound_path)>4096 or '\0' in sound_path:raise ValueError('通知音ファイルの指定が不正です')
   sound_path=sound_path.strip()
   if sound_path and Path(sound_path).suffix.lower() not in ('.wav','.mp3'):raise ValueError('通知音はWAVまたはMP3を選択してください')
   self.overlay_cfg.update(show=d['show'],alert=d['alert'],other_alerts=d['other_alerts'],name=own,auto_name=auto_name,seconds=seconds,volume=volume,opacity=opacity)
   self.overlay_cfg.update(split_options)
   self.overlay_cfg['show_weakness']=show_weakness;self.overlay_cfg['show_party']=show_party;self.overlay_cfg['separate_widgets']=separate_widgets;self.overlay_cfg['sound_path']=sound_path;self.overlay_cfg['vr_show']=vr_show
   if auto_name:self.refresh_identity(force=True)
   else:self.identity_status='手入力モード'
   self.meter.configure(self.overlay_cfg['name'],seconds)
   self.toggle_hud(d['show'])
   must_save();self.vr_hud.enable(vr_show,split_options['vr_split']);self.revision+=1
   self.status.set('バトルHUDの設定を保存しました')
   return self.status.get()
  if action=='overlay_test':
   sound_path=val('sound_path') if 'sound_path' in d else self.overlay_cfg.get('sound_path','')
   try:volume=int(d.get('volume',self.overlay_cfg['volume']))
   except (TypeError,ValueError):raise ValueError('警告音量が不正です')
   if not 0<=volume<=100:raise ValueError('警告音量が範囲外です')
   play_target_tone('target_on',volume,sound_path)
   return '警告音の再生を指示しました'
  if action=='set_active_difficulty':
   difficulty=val('difficulty',80)
   if difficulty not in self.DIFFICULTIES:raise ValueError('ゲームと同じ難易度を選択してください')
   previous=self.difficulty.get()
   self.difficulty.set(difficulty)
   try:must_save()
   except Exception:self.difficulty.set(previous);raise
   self.revision+=1;self.status.set('自動再生の難易度: '+difficulty)
   if difficulty!=previous and self.worker and self.worker.is_alive() and not self.stop.is_set():
    snapshot=self.meter.snapshot();mode=snapshot.get('mode')
    if mode=='boss':self.handle_boss(snapshot.get('boss',''))
    elif mode=='stage':self.play_auto('戦闘')
    elif mode=='break':self.play_auto('休憩')
   return self.status.get()
  if action=='start':
   if 'difficulty' in d:self.api_action({'action':'set_active_difficulty','difficulty':val('difficulty',80)})
   if self.start() is False:raise RuntimeError(self.status.get())
   return self.status.get()
  if action=='stop':self.stop_music();return self.status.get()
  if action=='stop_watch':self.stop_watch();return self.status.get()
  if action=='save':must_save(quiet=False);return self.status.get()
  if action=='play':
   if self.play(val('track'),val('fallback')) is False:raise ValueError(self.status.get())
   return self.status.get()
  if action=='play_selected':
   difficulty=val('difficulty',80);phase=val('phase',80)
   if difficulty not in self.DIFFICULTIES or phase not in self.PHASES:raise ValueError('難易度・場面が不正です')
   self.play_selected(difficulty,phase);return self.status.get()
  if action=='set_music':
   difficulty=val('difficulty',80);phase=val('phase',80)
   if difficulty not in self.DIFFICULTIES or phase not in self.PHASES:raise ValueError('難易度・場面が不正です')
   key=difficulty+'|'+phase
   self.vars[('music',key)].set(val('track'))
   self.vars[('fallback',key)].set(val('fallback'))
   must_save();self.revision+=1
   self.status.set('曲の設定を保存しました: '+difficulty+' / '+phase)
   return self.status.get()
  if action=='set_music_all':
   phase=val('phase',80);track=val('track');fallback=val('fallback')
   if phase not in self.PHASES:raise ValueError('場面が不正です')
   if not track:raise ValueError('曲を選択してください')
   changed=[]
   for difficulty in self.DIFFICULTIES:
    key=difficulty+'|'+phase
    for group,value in (('music',track),('fallback',fallback)):
     variable=self.vars[(group,key)];changed.append((variable,variable.get()));variable.set(value)
   try:must_save()
   except Exception:
    for variable,previous in changed:variable.set(previous)
    raise
   self.revision+=1;self.status.set('すべての難易度の「'+phase+'」に設定しました');return self.status.get()
  if action=='add_boss':
   name=val('boss',120)
   if not name:raise ValueError('ボス名を入力してください')
   if name not in self.discovered_bosses:
    self.discovered_bosses.add(name);must_save();self.revision+=1
   self.status.set('ボスを一覧に追加しました: '+name)
   return self.status.get()
  if action=='set_boss':
   name=val('boss',120)
   if not name:raise ValueError('ボス名を入力してください')
   track=val('track');fallback=val('fallback')
   previous_boss=dict(self.boss_map);previous_fallback=dict(self.boss_fallback_map)
   if track:self.boss_map[name]=track
   else:self.boss_map.pop(name,None)
   if fallback:self.boss_fallback_map[name]=fallback
   else:self.boss_fallback_map.pop(name,None)
   try:must_save()
   except Exception:
    self.boss_map=previous_boss;self.boss_fallback_map=previous_fallback;raise
   self.revision+=1
   self.status.set('ボスの曲を保存しました: '+name)
   return self.status.get()
  if action=='set_lobby':
   self.lobby.set(val('track'));must_save();self.revision+=1
   self.status.set('ロビーBGMを保存しました');return self.status.get()
  if action=='settings':
   try:fade=float(d.get('fade',2));volume=int(d.get('volume',80))
   except (ValueError,TypeError):raise ValueError('数値が不正です')
   if not 0<=fade<=15 or not 0<=volume<=100:raise ValueError('設定範囲外です')
   self.fade.set(fade);self.volume.set(volume)
   log=val('log');self.log.set(log)
   self.on_volume_change();must_save();self.revision+=1
   self.status.set('その他の設定を保存しました');return self.status.get()
  if action=='volume':
   try:volume=int(d.get('volume',80))
   except (ValueError,TypeError):raise ValueError('音量が不正です')
   self.volume.set(max(0,min(100,volume)));self.on_volume_change();self.schedule_save()
   return '音量 '+str(self.volume.get())
  if action=='detect':
   if not self.detect():raise RuntimeError(self.status.get())
   self.revision+=1;return self.log.get()
  if action=='pick':
   path=filedialog.askopenfilename(parent=self.root,title='音楽ファイルを選択',filetypes=[('音楽ファイル','*.mp3 *.wav *.ogg *.m4a')])
   if path:self.status.set('音楽ファイルを選択しました');return path
   return ''
  if action=='pick_alert':
   return filedialog.askopenfilename(parent=self.root,title='警告音ファイルを選択',filetypes=[('WAV / MP3','*.wav *.mp3')]) or ''
  if action=='backup':self.export_config();return self.status.get()
  if action=='restore':self.import_config();return self.status.get()
  if action=='open_folder':self.open_config_dir();return self.status.get()
  if action=='download':raise ValueError('この安全点検版ではMP3へのダウンロード・変換は無効です。音楽ファイルの登録またはYouTube URLでの再生をご利用ください')
  if action=='quit':
   self.root.after(200,self.close);return '終了します'
  raise ValueError('未対応の操作です: '+action)
 def open_unified(self):
  # The complete interface and playback engine share ONE dedicated Edge app window.
  self.unified=True
  url=f'http://127.0.0.1:{self.port}/ui'
  candidates=[Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
   Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe',
   Path(os.environ.get('LOCALAPPDATA',''))/'Microsoft/Edge/Application/msedge.exe']
  edge=next((str(x) for x in candidates if x.is_file()),None)
  try:
   if edge:
    profile=CFG.parent/'edge_unified_profile'
    profile.mkdir(parents=True,exist_ok=True)
    self.player_process=subprocess.Popen([edge,'--user-data-dir='+str(profile),'--no-first-run',
     '--app='+url,'--window-size=1130,850'],close_fds=True)
   else:
    # Default browser can still show a single tab instead of two app windows.
    if not webbrowser.open(url,new=1):raise RuntimeError('ブラウザを開けませんでした')
   self.player_launched=True;self.ui_launched_at=time.time()
  except Exception as exc:
   self.unified=False;self.root.deiconify()
   messagebox.showerror('統合画面を開けませんでした','従来の操作画面を表示します。\n'+str(exc))
 def check_ui_closed(self):
  # pagehide is delayed so that a simple browser refresh does not kill the app.
  if self.unified and self.ui_goodbye_at and time.time()-self.ui_goodbye_at>6:
   if self.ui_last_seen<self.ui_goodbye_at:self.close();return
   self.ui_goodbye_at=0
  if self.root.winfo_exists():self.root.after(1800,self.check_ui_closed)
 def close(self):
  self.finish_monitor('アプリ終了')
  self.save(quiet=True);self.stop_music();self.vr_hud.close()
  for widget in self.extra_widgets.values():
   if widget.winfo_exists():widget.destroy()
  if self.party_hud is not None and self.party_hud.winfo_exists():self.party_hud.destroy()
  if self.hud is not None and self.hud.winfo_exists():self.hud.destroy()
  if self.player_process is not None and self.player_process.poll() is None:
   try:
    # Dedicated Edge profile only; do not terminate unrelated Edge sessions.
    subprocess.run(['taskkill','/PID',str(self.player_process.pid),'/T','/F'],capture_output=True,timeout=3,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   except Exception:pass
  self.root.destroy()
if __name__=='__main__':
 if '--vr-self-test' in sys.argv:
  try:
   import openvr
   from steamvr_hud import make_frame
   if make_frame({'boss':'Yuki'}).size!=(720,224):raise RuntimeError('VR HUD image size is incorrect')
   if any(make_frame({'target':'Alice'},kind).size!=(640,136) for kind in ('damage','target')):raise RuntimeError('Split VR HUD image size is incorrect')
  except Exception as exc:
   report=os.environ.get('ECLIPTICA_VR_SELF_TEST_REPORT')
   if report:
    try:Path(report).write_text(type(exc).__name__+': '+str(exc),encoding='utf-8')
    except OSError:pass
   sys.exit(89)
  sys.exit(0)
 # PyInstaller post-build health check: run without opening the UI or Edge.
 # This catches missing Tcl/Tk assets *before* GitHub Actions publishes the EXE.
 if '--tk-self-test' in sys.argv:
  try:
   interpreter=tk.Tcl()  # Loads Tcl's init.tcl, without creating a desktop window.
   if not interpreter.eval('info patchlevel'):
    raise RuntimeError('Tcl runtime did not initialize')
   if getattr(sys,'frozen',False):
    verify_frozen_tk_assets(interpreter,Path(sys._MEIPASS))
  except Exception as exc:
   report=os.environ.get('ECLIPTICA_TK_SELF_TEST_REPORT')
   if report:
    try:Path(report).write_text(type(exc).__name__+': '+str(exc),encoding='utf-8')
    except OSError:pass
   sys.exit(87)
  sys.exit(0)
 if '--gui-self-test' in sys.argv:
  # Exercise the bundled application and its HUD without opening a browser or
  # reading VRChat logs. The build runs this with an isolated LOCALAPPDATA.
  try:
   root=tk.Tk();root.withdraw()
   app=App(root,0)
   for track in SAMPLE_FALLBACK_FILES:
    if not sample_fallback(track):raise FileNotFoundError('Bundled demo audio is missing')
   app.meter.ingest('ECLIPTICA - now fighting boss: YukiPhase2(Clone) on phase: 0')
   app.toggle_hud(True);app.update_hud_loop();root.update()
   if app.api_view()['weakness']['name']!='Yuki(P2)' or '弱火' not in app.hud.weak_lbl.cget('text'):
    raise RuntimeError('HUD boss reference information is unavailable')
   app.overlay_cfg['separate_widgets']=True;app.update_hud_loop();root.update()
   if '弱火' not in app.extra_widgets['weakness'].value.cget('text'):
    raise RuntimeError('Movable weakness widget is unavailable')
   app.overlay_cfg.update(show_damage=True,show_target=True);app.toggle_hud(False);app.update_hud_loop();root.update()
   if any(kind not in app.extra_widgets or not app.extra_widgets[kind].winfo_viewable() for kind in ('damage','target')):
    raise RuntimeError('Separate damage and target windows are unavailable')
   app.close()
  except Exception as exc:
   report=os.environ.get('ECLIPTICA_GUI_SELF_TEST_REPORT')
   if report:
    try:Path(report).write_text(type(exc).__name__+': '+str(exc),encoding='utf-8')
    except OSError:pass
   sys.exit(88)
  sys.exit(0)
 if sys.platform=='win32':
  import ctypes
  mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\EclipticaMusicCompanionSingleWindow')
  if ctypes.windll.kernel32.GetLastError()==183:
   ctypes.windll.user32.MessageBoxW(None,'Ecliptica Music Companionは既に起動しています。タスクバーを確認してください。','Ecliptica Music Companion',0x40)
   sys.exit(0)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 root=tk.Tk();root.withdraw()
 UI_APP=App(root,server.server_port)
 UI_APP.unified=True
 root.after(40,UI_APP.drain_api)
 root.after(350,UI_APP.open_unified)
 root.after(1800,UI_APP.check_ui_closed)
 root.mainloop();server.shutdown()
