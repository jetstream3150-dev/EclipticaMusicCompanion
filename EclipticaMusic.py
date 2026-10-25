import json,os,re,threading,time,webbrowser,mimetypes,sys,subprocess,shutil
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from datetime import datetime
BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
USER_DIR=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else BASE
CFG=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'EclipticaMusicCompanion'/'settings.json'
CFG.parent.mkdir(parents=True,exist_ok=True)
LOG=Path(os.environ.get('USERPROFILE',str(Path.home())))/'AppData/LocalLow/VRChat/VRChat'
DEFAULT={'round':{},'waiting':{},'phase':{},'boss':{},'music':{},'fade':2.0,'volume':80,'log':'','auto':False,'fallback':{},'lobby':''}
state={'seq':0,'track':'','fade':2,'volume':.8,'stop':False,'player_status':'プレイヤー未接続','player_seen':0,'volume_seq':0,'fallback':''}
lock=threading.Lock()
allowed_media=set()
class Handler(BaseHTTPRequestHandler):
 def do_POST(self):
  if self.path!='/player-status' or self.client_address[0]!='127.0.0.1':
   self.send_error(403);return
  try:
   size=int(self.headers.get('Content-Length','0'))
   if size<1 or size>4096:raise ValueError('invalid size')
   data=json.loads(self.rfile.read(size).decode('utf-8'))
   with lock:state['player_status']=str(data.get('status',''))[:240];state['player_seen']=time.time()
   self.send_response(204);self.end_headers()
  except (ValueError,UnicodeError,json.JSONDecodeError):self.send_error(400)
 def log_message(self,*args):pass
 def do_GET(self):
  u=urlparse(self.path)
  if self.headers.get('Host','').split(':')[0] not in ('127.0.0.1','localhost'):
   self.send_error(403);return
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
class App:
 def __init__(self,root,port):
  self.root=root;self.port=port;self.cfg=self.load_config();self.stop=threading.Event();self.worker=None;self.round=0;self.boss='';self.laststage='';self.vars={};self.difficulty=tk.StringVar(value='Primal');self.phase_choice=tk.StringVar(value='休憩');self.current_round=tk.IntVar(value=1);root.title('Ecliptica Music Companion v1.3.3 β');root.geometry('1080x810');root.minsize(880,670);root.configure(bg='#0b1020');self.status=tk.StringVar(value='待機中');self.event_status=tk.StringVar(value='検知イベント: なし');self.fade=tk.DoubleVar(value=self.cfg.get('fade',2));self.volume=tk.IntVar(value=self.cfg.get('volume',80));self.log=tk.StringVar(value=self.cfg.get('log',''));self.player_process=None;self.player_launched=False;self.player_status=tk.StringVar(value='プレイヤー: 未接続');self.build();root.protocol('WM_DELETE_WINDOW',self.close);root.after(400,self.open_player);root.after(1200,self.auto_start);root.after(1500,self.refresh_player_status)
 def build(self):
  # Dark gaming theme: legible contrast, large controls and clear primary actions.
  BG='#0b1020'; PANEL='#141d32'; FIELD='#1c2942'; EDGE='#304363'; TEXT='#edf4ff'; MUTED='#9cb0cc'; ACCENT='#3ce6d0'; PURPLE='#9b86ff'
  style=ttk.Style(self.root)
  try:style.theme_use('clam')
  except tk.TclError:pass
  style.configure('.',font=('Segoe UI',10),background=BG,foreground=TEXT)
  style.configure('TFrame',background=BG)
  style.configure('TLabel',background=BG,foreground=TEXT)
  style.configure('Muted.TLabel',background=BG,foreground=MUTED)
  style.configure('Title.TLabel',font=('Segoe UI',20,'bold'),background=BG,foreground=ACCENT)
  style.configure('Section.TLabel',font=('Segoe UI',12,'bold'),background=BG,foreground=TEXT)
  style.configure('TLabelframe',background=PANEL,bordercolor=EDGE,relief='solid')
  style.configure('TLabelframe.Label',font=('Segoe UI',11,'bold'),background=BG,foreground=ACCENT)
  style.configure('TButton',background=FIELD,foreground=TEXT,padding=(12,8),borderwidth=1,bordercolor=EDGE,font=('Segoe UI',10,'bold'))
  style.map('TButton',background=[('active','#304365'),('pressed','#263c57')],foreground=[('disabled','#69788f')])
  style.configure('Action.TButton',background=ACCENT,foreground='#061521',padding=(17,10),font=('Segoe UI',11,'bold'),bordercolor=ACCENT)
  style.map('Action.TButton',background=[('active','#8af9e9'),('pressed','#20b9aa')],foreground=[('active','#061521')])
  style.configure('Danger.TButton',background='#41283e',foreground='#ffc6d3',bordercolor='#704158')
  style.map('Danger.TButton',background=[('active','#64374d')])
  style.configure('TEntry',fieldbackground=FIELD,foreground=TEXT,insertcolor=TEXT,bordercolor=EDGE,padding=7)
  style.configure('TCombobox',fieldbackground=FIELD,background=FIELD,foreground=TEXT,arrowcolor=ACCENT,bordercolor=EDGE,padding=6)
  style.map('TCombobox',fieldbackground=[('readonly',FIELD)],foreground=[('readonly',TEXT)],selectbackground=[('readonly',FIELD)],selectforeground=[('readonly',TEXT)])
  style.configure('TNotebook',background=BG,borderwidth=0)
  style.configure('TNotebook.Tab',background=FIELD,foreground=MUTED,padding=(17,11),font=('Segoe UI',10,'bold'))
  style.map('TNotebook.Tab',background=[('selected',PANEL),('active','#263650')],foreground=[('selected',ACCENT),('active',TEXT)])
  style.configure('TScrollbar',background=FIELD,troughcolor=BG,arrowcolor=MUTED)
  style.configure('Horizontal.TScale',background=PANEL,troughcolor=FIELD)
  style.configure('TSpinbox',fieldbackground=FIELD,foreground=TEXT,arrowcolor=ACCENT)
  try:self.root.option_add('*TCombobox*Listbox.background','#1c2942');self.root.option_add('*TCombobox*Listbox.foreground','#edf4ff');self.root.option_add('*TCombobox*Listbox.selectBackground','#355575')
  except tk.TclError:pass
  f=ttk.Frame(self.root,padding=18);f.pack(fill='both',expand=True)
  ttk.Label(f,text='◈  ECLIPTICA  /  MUSIC COMPANION',style='Title.TLabel').pack(anchor='w')
  ttk.Label(f,text='YOUR BATTLE. YOUR SOUNDTRACK.   •   v1.3.3 BETA',style='Muted.TLabel').pack(anchor='w',pady=(2,13))
  control=ttk.LabelFrame(f,text='1. 操作パネル',padding=9);control.pack(fill='x')
  r=ttk.Frame(control);r.pack(fill='x',pady=3)
  ttk.Button(r,text='▶ 監視開始',command=self.start,style='Action.TButton').pack(side='left')
  ttk.Button(r,text='■ 監視停止',command=self.stop_watch,style='Danger.TButton').pack(side='left',padx=4)
  ttk.Button(r,text='■ BGM停止',command=self.stop_music,style='Danger.TButton').pack(side='left',padx=4)
  ttk.Button(r,text='♫ プレイヤー表示',command=self.open_player).pack(side='right')
  r=ttk.Frame(control);r.pack(fill='x',pady=5)
  ttk.Label(r,text='現在の難易度').pack(side='left')
  ttk.Combobox(r,textvariable=self.difficulty,values=self.DIFFICULTIES,state='readonly',width=20).pack(side='left',padx=6)
  ttk.Label(r,text='現在のフェーズ').pack(side='left',padx=(10,0))
  ttk.Combobox(r,textvariable=self.phase_choice,values=self.PHASES,state='readonly',width=14).pack(side='left',padx=6)
  ttk.Button(r,text='▶ 選択した曲を再生',command=self.play_selected).pack(side='left',padx=6)
  r=ttk.Frame(control);r.pack(fill='x',pady=3)
  ttk.Label(r,text='VRChatログ').pack(side='left');ttk.Entry(r,textvariable=self.log).pack(side='left',fill='x',expand=True,padx=5)
  ttk.Button(r,text='最新ログ',command=self.detect).pack(side='left')
  r=ttk.Frame(control);r.pack(fill='x',pady=3)
  ttk.Label(r,text='フェード(秒)').pack(side='left');ttk.Spinbox(r,from_=0,to=15,increment=.5,textvariable=self.fade,width=6).pack(side='left',padx=5)
  ttk.Label(r,text='音量(%)').pack(side='left',padx=(12,0));ttk.Scale(r,from_=0,to=100,variable=self.volume,orient='horizontal',command=self.on_volume_change,length=180).pack(side='left',padx=5);ttk.Label(r,textvariable=self.volume,width=4).pack(side='left')
  ttk.Button(r,text='💾 設定を保存',command=self.save,style='Action.TButton').pack(side='right')
  r=ttk.Frame(control);r.pack(fill='x',pady=3)
  ttk.Button(r,text='設定をバックアップ',command=self.export_config).pack(side='left')
  ttk.Button(r,text='設定を復元',command=self.import_config).pack(side='left',padx=5)
  ttk.Button(r,text='保存先を開く',command=self.open_config_dir).pack(side='left',padx=5)
  lobby_row=ttk.Frame(control);lobby_row.pack(fill='x',pady=4);ttk.Label(lobby_row,text='ロビー・入室BGM').pack(side='left');self.lobby=tk.StringVar(value=self.cfg.get('lobby',''));ttk.Entry(lobby_row,textvariable=self.lobby).pack(side='left',fill='x',expand=True,padx=5);ttk.Button(lobby_row,text='📁',command=lambda:self.pick(self.lobby)).pack(side='left');ttk.Button(lobby_row,text='▶',command=lambda:self.play(self.lobby.get())).pack(side='left');nb=ttk.Notebook(f);nb.pack(fill='both',expand=True,pady=(14,8))
  guide=ttk.Frame(nb,padding=14);nb.add(guide,text='はじめに')
  for t in ['① 「難易度別BGM」で戦闘・準備・ボス・終了・休憩の曲を登録','② 「ボス別BGM」で特定ボスの曲を上書き設定（任意）','③ 保存 → 黒いプレイヤーで「再生を有効化」 → 監視開始（自動監視は初期状態でOFF）','④ 途中参加時は現在ログの直近イベントを解析し、可能なら該当BGMを再生します（ログ情報が不足する場合は手動選択）','※ ステージ開始・ボス開始・休憩開始・ロビーをログから試験検知します。難易度は手動選択してください。', '※ YouTubeエラー150/101では予備MP3に自動切替します（設定済みの場合）。', '※ 音楽ファイルはこのPCの絶対パスで保存されます。別PCへの設定移行時は再指定が必要です。']:
   ttk.Label(guide,text=t,wraplength=890).pack(anchor='w',pady=9)
  tracks=ttk.Frame(nb,padding=10);nb.add(tracks,text='難易度別BGM')
  ttk.Label(tracks,text='難易度ごとに5つのフェーズの曲を登録します。休憩はラウンド終了後の「世界の狭間」です。',style='Muted.TLabel').pack(anchor='w',pady=(0,8))
  canvas=tk.Canvas(tracks,highlightthickness=0,bg='#0b1020',bd=0);bar=ttk.Scrollbar(tracks,orient='vertical',command=canvas.yview)
  inner=ttk.Frame(canvas);inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
  canvas.create_window((0,0),window=inner,anchor='nw');canvas.configure(yscrollcommand=bar.set)
  bar.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True)
  for difficulty in self.DIFFICULTIES:
   frame=ttk.LabelFrame(inner,text=difficulty,padding=7);frame.pack(fill='x',pady=5)
   for phase in self.PHASES:
    key=difficulty+'|'+phase;v=tk.StringVar(value=self.cfg.get('music',{}).get(key,''));self.vars[('music',key)]=v
    r=ttk.Frame(frame);r.pack(fill='x',pady=2)
    ttk.Label(r,text=phase,width=11).pack(side='left')
    ttk.Entry(r,textvariable=v,width=65).pack(side='left',fill='x',expand=True,padx=4)
    ttk.Button(r,text='📁',width=3,command=lambda x=v:self.pick(x)).pack(side='left',padx=2)
    ttk.Button(r,text='▶',width=3,command=lambda x=v,k=key:self.play(x.get(),self.get_fallback(k))).pack(side='left');fb=tk.StringVar(value=self.cfg.get('fallback',{}).get(key,''));self.vars[('fallback',key)]=fb;ttk.Label(inner,text='予備MP3 ('+difficulty+' / '+phase+')').pack(anchor='w');fr=ttk.Frame(inner);fr.pack(fill='x');ttk.Entry(fr,textvariable=fb).pack(side='left',fill='x',expand=True);ttk.Button(fr,text='📁',command=lambda x=fb:self.pick(x)).pack(side='left')
  bosses=ttk.Frame(nb,padding=10);nb.add(bosses,text='ボス別BGM')
  ttk.Label(bosses,text='▼ ボスを選択 → 曲を登録 → 設定を保存。候補にない名前は直接入力できます。',style='Muted.TLabel').pack(anchor='w',pady=(0,8))
  self.boss_rows=ttk.Frame(bosses);self.boss_rows.pack(fill='both',expand=True)
  for name,track in self.cfg.get('boss',{}).items():self.add_boss_row(name,track)
  if not self.cfg.get('boss'):self.add_boss_row('','')
  ttk.Button(bosses,text='＋ ボスを追加',command=lambda:self.add_boss_row('','')).pack(anchor='w',pady=8)
  ttk.Label(f,text='自動監視: 戦闘・ボス・休憩に試験対応。難易度は手動選択。準備・終了は未対応。',foreground='#f7c879').pack(anchor='w')
  ttk.Label(f,textvariable=self.event_status,padding=6,style='Muted.TLabel').pack(fill='x',pady=(7,0))
  ttk.Label(f,textvariable=self.player_status,padding=6,style='Muted.TLabel').pack(fill='x',pady=(4,0))
  ttk.Label(f,textvariable=self.status,padding=8,style='Section.TLabel').pack(fill='x',pady=(4,0))
 BOSS_CHOICES=('Kakarot', 'Nan', 'BuffNoob', 'Pride', 'Steven', 'Amaziah', 'JackedPumpkin', 'QueenVolt', 'M41D', 'Corus', 'CorusPhase2', 'Yuki', 'YukiPhase2', 'Pandora', 'Mephiel', 'MephielPhase2', 'OnyxPilot', 'NeoPilot', 'Gilgamesh', 'GilgameshPhase2', 'GilgameshPhase3', 'GoldenGrouch', 'DarkMouth')
 DIFFICULTIES=('Primal','Penumbra','Antumbra','Umbra','Eclipse','Eye of the Eclipse')
 PHASES=('戦闘','準備','ボス','終了','休憩')
 def load_config(self):
  if not CFG.exists():return json.loads(json.dumps(DEFAULT))
  try:
   obj=json.loads(CFG.read_text('utf-8'))
   if not isinstance(obj,dict):raise ValueError('設定の形式が正しくありません')
   cfg=json.loads(json.dumps(DEFAULT));cfg.update(obj)
   if not isinstance(cfg.get('music'),dict) or not isinstance(cfg.get('boss'),dict):raise ValueError('曲設定が正しくありません')
   return cfg
  except Exception:
   try:CFG.rename(CFG.with_name('settings_broken_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json'))
   except OSError:pass
   return json.loads(json.dumps(DEFAULT))
 def export_config(self):
  self.save()
  target=filedialog.asksaveasfilename(title='設定をバックアップ',defaultextension='.json',initialfile='EclipticaMusicCompanion_backup.json',filetypes=[('JSON','*.json')])
  if target:
   try:shutil.copy2(CFG,target);messagebox.showinfo('完了','設定を書き出しました。')
   except Exception as e:messagebox.showerror('失敗',str(e))
 def import_config(self):
  source=filedialog.askopenfilename(title='設定を復元',filetypes=[('JSON','*.json')])
  if not source:return
  try:
   obj=json.loads(Path(source).read_text('utf-8'))
   if not isinstance(obj,dict) or not isinstance(obj.get('music',{}),dict) or not isinstance(obj.get('boss',{}),dict):raise ValueError('対応していない設定ファイルです')
   if not messagebox.askyesno('確認','現在の設定を置き換えてアプリを再起動しますか？'):return
   CFG.write_text(json.dumps(obj,ensure_ascii=False,indent=2),'utf-8')
   messagebox.showinfo('復元完了','設定を復元しました。アプリを終了して起動し直してください。')
  except Exception as e:messagebox.showerror('復元失敗',str(e))
 def open_config_dir(self):
  try:os.startfile(str(CFG.parent))
  except Exception as e:messagebox.showerror('開けませんでした',str(e))
 def add_boss_row(self,name,track):
  r=ttk.Frame(self.boss_rows);r.pack(fill='x',pady=3)
  n=tk.StringVar(value=name);v=tk.StringVar(value=track)
  self.vars[('bossrow',str(id(r)))]=(n,v)
  ttk.Combobox(r,textvariable=n,values=self.BOSS_CHOICES,width=22,state='normal').pack(side='left',padx=4)
  ttk.Entry(r,textvariable=v).pack(side='left',fill='x',expand=True,padx=4)
  ttk.Button(r,text='📁',command=lambda:self.pick(v)).pack(side='left')
  ttk.Button(r,text='▶',command=lambda:self.play(v.get())).pack(side='left',padx=3)
  def remove():
   self.vars.pop(('bossrow',str(id(r))),None);r.destroy()
  ttk.Button(r,text='×',command=remove).pack(side='left')
 def play_selected(self):
  key=self.difficulty.get()+'|'+self.phase_choice.get()
  v=self.vars.get(('music',key));track=v.get().strip() if v else ''
  if not track:self.status.set('選択した難易度・フェーズの曲が未設定です');return
  self.play(track,self.get_fallback(key))
 def get_fallback(self,key):
  v=self.vars.get(('fallback',key));return v.get().strip() if v else ''
 def play_auto(self,phase):
  difficulty=self.difficulty.get();key=difficulty+'|'+phase
  v=self.vars.get(('music',key));track=v.get().strip() if v else ''
  if track:self.play(track,self.get_fallback(key))
  else:self.status.set(f'{difficulty} / {phase} の曲は未設定です')
 def pick(self,v):
  p=filedialog.askopenfilename(filetypes=[('音楽','*.mp3 *.wav *.ogg *.m4a')]);
  if p:v.set(p)
 def save(self):
  music={};boss={};fallback={}
  for (group,k),v in self.vars.items():
   if group=='music' and v.get().strip():music[k]=v.get().strip()
   elif group=='fallback' and v.get().strip():fallback[k]=v.get().strip()
   elif group=='bossrow':
    n,t=v;name=n.get().strip()
    if name and t.get().strip():boss[name]=t.get().strip()
  self.cfg['music']=music;self.cfg['boss']=boss;self.cfg['fallback']=fallback;self.cfg['lobby']=self.lobby.get().strip()
  self.cfg.update(log=self.log.get(),fade=float(self.fade.get()),volume=int(self.volume.get()))
  try:
   tmp=CFG.with_suffix('.tmp');tmp.write_text(json.dumps(self.cfg,ensure_ascii=False,indent=2),'utf-8');tmp.replace(CFG);self.status.set('設定を保存しました')
  except Exception as e:messagebox.showerror('保存失敗',str(e))
 def detect(self):
  files=sorted(LOG.glob('output_log_*.txt'),key=lambda p:p.stat().st_mtime,reverse=True)
  if files:self.log.set(str(files[0]));self.status.set('最新ログを選択しました')
  else:messagebox.showwarning('ログ未検出','VRChatを起動してから再度お試しください。')
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
  self.root.after(1200,self.refresh_player_status)
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
 def play(self,track,fallback=''):
  track=track.strip()
  if not track:return
  if not track.startswith(('https://youtube.com/','https://www.youtube.com/','https://music.youtube.com/','https://youtu.be/')) and not Path(track).is_file():self.status.set('URLか存在する音楽ファイルを設定してください');return
  if Path(track).is_file():
   with lock:allowed_media.add(str(Path(track).resolve()))
  with lock:state.update(seq=state['seq']+1,track=track,fade=max(0,float(self.fade.get())),volume=max(0,min(100,int(self.volume.get())))/100,stop=False,fallback=fallback)
  self.status.set('切替指示: '+track[:65])
 def stop_music(self):
  with lock:state.update(seq=state['seq']+1,stop=True)
 def auto_start(self):
  if self.cfg.get('auto',True):self.start()
 def start(self):
  self.save()
  # Prefer the current VRChat session's newest log over a persisted stale path.
  files=sorted(LOG.glob('output_log_*.txt'),key=lambda x:x.stat().st_mtime,reverse=True)
  configured=Path(self.log.get()) if self.log.get().strip() else None
  p=files[0] if files else configured
  if p is None or not p.is_file():
   self.status.set('VRChatログが見つかりません。VRChatを起動してください');return
  self.log.set(str(p))
  self.stop.set()
  self.stop=threading.Event();self.round=0;self.boss='';self.laststage=''
  self.worker=threading.Thread(target=self.watch,args=(p,self.stop),daemon=True)
  self.worker.start();self.status.set('監視中: '+p.name)
  self.event_status.set('検知イベント: 待機中（次のゲームイベントから再生）')
 def resume_from_log(self,p):
  # The most recent ECLIPTICA state in this VRChat session is a best-effort hint.
  try:
   if time.time()-p.stat().st_mtime>7200:return
   with p.open('rb') as f:
    f.seek(max(0,p.stat().st_size-2_000_000));raw=f.read().decode('utf-8','replace')
   events=[]
   for line in raw.splitlines():
    if 'ECLIPTICA - now in intermission' in line:events.append(('休憩',None))
    elif 'ECLIPTICA - now in lobby' in line:events.append(('ロビー',None))
    else:
     b=re.search(r'ECLIPTICA - now fighting boss:\s*(.+?)\s+on phase:',line)
     st=re.search(r'ECLIPTICA - now in stage:\s*(.+?)\s+on phase:',line)
     if b:events.append(('ボス',re.sub(r'\(Clone\)$','',b.group(1).strip(),flags=re.I)))
     elif st:events.append(('戦闘',st.group(1).strip()))
   if events:
    kind,name=events[-1]
    if kind=='ボス':self.handle_boss(name)
    elif kind=='ロビー':self.handle_event('途中参加・ロビー','ロビー')
    else:self.handle_event('途中参加・推定'+kind,kind)
   else:self.handle_event('入室・状態不明（ロビーBGMを仮再生）','ロビー')
  except (OSError,UnicodeError) as e:self.status.set('途中参加の状態確認に失敗: '+str(e))
 def stop_watch(self):
  self.stop.set();self.status.set('監視停止')
 def watch(self,p,signal):
  # Start at EOF: old events must not play when the app starts mid-game.
  # Reopen new VRChat logs automatically when VRChat restarts.
  try:
   f=p.open('r',encoding='utf-8',errors='replace')
   f.seek(0,2)
   while not signal.is_set():
    line=f.readline()
    if not line:
     time.sleep(.25)
     try:
      newest=max(LOG.glob('output_log_*.txt'),key=lambda x:x.stat().st_mtime,default=None)
      if newest and newest!=p and newest.stat().st_mtime>p.stat().st_mtime:
       nf=newest.open('r',encoding='utf-8',errors='replace')
       nf.seek(0,2)
       f.close();f=nf;p=newest
       self.root.after(0,lambda path=str(p):self.log.set(path))
       self.root.after(0,lambda name=p.name:self.status.set('新しいログへ自動切替: '+name))
     except OSError:pass
     continue
    if 'ECLIPTICA - now in intermission' in line:
     self.root.after(0,lambda:self.handle_event('休憩開始','休憩'))
    elif 'ECLIPTICA - now in lobby' in line:
     self.root.after(0,lambda:self.handle_event('ロビーに戻りました','ロビー'))
    else:
     stage=re.search(r'ECLIPTICA - now in stage:\s*(.+?)\s+on phase:',line)
     boss=re.search(r'ECLIPTICA - now fighting boss:\s*(.+?)\s+on phase:',line)
     if stage:
      # Never deduplicate by stage name: the same stage may appear in later rounds.
      name=stage.group(1).strip()
      self.root.after(0,lambda n=name:self.handle_event('戦闘開始: '+n,'戦闘'))
     elif boss:
      name=re.sub(r'\(Clone\)$','',boss.group(1).strip(),flags=re.I).strip()
      self.root.after(0,lambda n=name:self.handle_boss(n))
   f.close()
  except Exception as e:
   self.root.after(0,lambda msg=str(e):self.status.set('ログ読み込み失敗: '+msg))
 def handle_event(self,description,phase):
  self.event_status.set('検知イベント: '+description)
  if phase=='ロビー':
   track=self.lobby.get().strip()
   if track:self.play(track)
   else:self.status.set('ロビーBGMは未設定です')
  elif phase is None:self.stop_music()
  else:
   self.phase_choice.set(phase)
   self.play_auto(phase)
 def handle_boss(self,name):
  self.event_status.set('検知イベント: ボス開始 '+name)
  self.phase_choice.set('ボス')
  base=re.sub(r'\s*Phase\d+$','',name,flags=re.I).strip()
  bosses={k.casefold():v for k,v in self.cfg.get('boss',{}).items()}
  # Prefer phase-specific override, then generic boss, then difficulty boss music.
  track=bosses.get(name.casefold()) or bosses.get(base.casefold())
  if track:self.play(track)
  else:self.play_auto('ボス')
 def close(self):
  self.stop.set();self.stop_music()
  if self.player_process is not None and self.player_process.poll() is None:
   try:
    # Dedicated Edge profile only; do not terminate unrelated Edge sessions.
    subprocess.run(['taskkill','/PID',str(self.player_process.pid),'/T','/F'],capture_output=True,timeout=3,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   except Exception:pass
  self.root.destroy()
if __name__=='__main__':
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 root=tk.Tk();App(root,server.server_port);root.mainloop();server.shutdown()
