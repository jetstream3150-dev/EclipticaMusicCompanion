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
  self.root=root;self.port=port;self.cfg=self.load_config();self.stop=threading.Event();self.worker=None;self.round=0;self.boss='';self.laststage='';self.vars={};self.difficulty=tk.StringVar(value='Primal');self.phase_choice=tk.StringVar(value='休憩');self.current_round=tk.IntVar(value=1);root.title('Ecliptica Music Companion v1.4 β');root.geometry('920x760');root.minsize(650,540);root.configure(bg='#0b1020');self.status=tk.StringVar(value='待機中');self.event_status=tk.StringVar(value='検知イベント: なし');self.fade=tk.DoubleVar(value=self.cfg.get('fade',2));self.volume=tk.IntVar(value=self.cfg.get('volume',80));self.log=tk.StringVar(value=self.cfg.get('log',''));self.player_process=None;self.player_launched=False;self.player_status=tk.StringVar(value='プレイヤー: 未接続');self.build();root.protocol('WM_DELETE_WINDOW',self.close);root.after(1200,self.auto_start);root.after(1500,self.refresh_player_status)
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
  self.boss_name=tk.StringVar(value=self.BOSS_CHOICES[0]);self.boss_track=tk.StringVar()
  self.boss_name.trace_add('write',self.boss_name_changed)
  self._save_after=None;self._loading_editor=False
  outer=ttk.Frame(self.root,padding=16);outer.pack(fill='both',expand=True)
  ttk.Label(outer,text='◈  ECLIPTICA',style='Title.TLabel').pack(anchor='w')
  ttk.Label(outer,text='MUSIC COMPANION   •   v1.4',style='Muted.TLabel').pack(anchor='w',pady=(0,12))
  self.tabs=ttk.Notebook(outer);self.tabs.pack(fill='both',expand=True)
  home=ttk.Frame(self.tabs,padding=16);self.tabs.add(home,text='🏠 ホーム')
  ttk.Label(home,text='ゲームに合わせて音楽を流そう！',style='Heading.TLabel').pack(anchor='center',pady=(6,15))
  ttk.Button(home,text='▶  音楽をスタート！',style='Action.TButton',command=self.quick_start).pack(fill='x',ipady=8)
  ttk.Label(home,text='最初だけ、開いたプレイヤーで「再生を有効化」を押してね',style='Muted.TLabel').pack(anchor='center',pady=(9,15))
  actions=ttk.Frame(home);actions.pack(fill='x',pady=4)
  ttk.Button(actions,text='■  音楽を止める',command=self.stop_music).pack(side='left',fill='x',expand=True,padx=(0,5))
  ttk.Button(actions,text='■  自動切替を止める',command=self.stop_watch).pack(side='left',fill='x',expand=True,padx=(5,0))
  ttk.Label(home,text='いまのゲーム',style='Heading.TLabel').pack(anchor='w',pady=(20,7))
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
  ttk.Button(music,text='▶ この曲を試す',command=lambda:self.play(self.music_editor.get(),self.fallback_editor.get())).pack(anchor='w',pady=(2,17))
  ttk.Label(music,text='予備のMP3（YouTubeが再生できないとき用）',style='Heading.TLabel').pack(anchor='w')
  rr=ttk.Frame(music);rr.pack(fill='x',pady=(8,10))
  self.fallback_editor=tk.StringVar()
  ttk.Entry(rr,textvariable=self.fallback_editor).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(rr,text='📁 ファイル',command=lambda:self.pick(self.fallback_editor)).pack(side='left')
  ttk.Label(music,text='変更した曲は自動で保存されます。',style='Muted.TLabel').pack(anchor='w',pady=(8,0))
  self.edit_diff.trace_add('write',lambda *_:self.load_music_editor())
  self.edit_phase.trace_add('write',lambda *_:self.load_music_editor())
  self.music_editor.trace_add('write',lambda *_:self.update_music_editor())
  self.fallback_editor.trace_add('write',lambda *_:self.update_music_editor())
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
  ttk.Button(boss,text='▶ この曲を試す',command=lambda:self.play(self.boss_track.get())).pack(anchor='w',pady=(4,12))
  ttk.Label(boss,text='ボスごとの曲は自動保存。空欄なら難易度別のボスBGMが流れます。',style='Muted.TLabel',wraplength=680).pack(anchor='w')
  self.boss_track.trace_add('write',lambda *_:self.update_boss_editor())
  self.boss_name_changed()
  advanced=ttk.Frame(self.tabs,padding=16);self.tabs.add(advanced,text='⚙ その他')
  ttk.Label(advanced,text='ロビーの曲',style='Heading.TLabel').pack(anchor='w')
  rr=ttk.Frame(advanced);rr.pack(fill='x',pady=(8,15))
  ttk.Entry(rr,textvariable=self.lobby).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(rr,text='📁 ファイル',command=lambda:self.pick(self.lobby)).pack(side='left')
  ttk.Label(advanced,text='VRChatのログ',style='Heading.TLabel').pack(anchor='w')
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
  self.lobby.trace_add('write',lambda *_:self.schedule_save())
  self.log.trace_add('write',lambda *_:self.schedule_save())
  self.fade.trace_add('write',lambda *_:self.schedule_save())
  self.volume.trace_add('write',lambda *_:self.schedule_save())
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
  self._loading_editor=False
 def update_boss_editor(self):
  if self._loading_editor:return
  name=self.boss_name.get().strip()
  if not name:return
  if self.boss_track.get().strip():self.boss_map[name]=self.boss_track.get().strip()
  else:self.boss_map.pop(name,None)
  self.schedule_save()
 def schedule_save(self):
  if not hasattr(self,'_save_after'):return
  if self._save_after is not None:self.root.after_cancel(self._save_after)
  self._save_after=self.root.after(750,self.autosave)
 def autosave(self):
  self._save_after=None
  self.save(quiet=True)
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
  # Grid keeps all controls aligned; widths adapt to the available panel.
  r=ttk.Frame(self.boss_rows)
  r.pack(fill='x',pady=3)
  r.columnconfigure(0,weight=0,minsize=190)
  r.columnconfigure(1,weight=1,minsize=120)
  n=tk.StringVar(value=name);v=tk.StringVar(value=track)
  self.vars[('bossrow',str(id(r)))]=(n,v)
  ttk.Combobox(r,textvariable=n,values=self.BOSS_CHOICES,width=21,state='normal').grid(row=0,column=0,sticky='ew',padx=(0,5))
  ttk.Entry(r,textvariable=v).grid(row=0,column=1,sticky='ew',padx=(0,5))
  ttk.Button(r,text='📁',width=3,command=lambda:self.pick(v)).grid(row=0,column=2,padx=2)
  ttk.Button(r,text='▶',width=3,command=lambda:self.play(v.get())).grid(row=0,column=3,padx=2)
  def remove():
   self.vars.pop(('bossrow',str(id(r))),None)
   r.destroy()
  ttk.Button(r,text='×',width=3,command=remove).grid(row=0,column=4,padx=(2,0))
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
 def save(self,quiet=False):
  music={};boss=dict(self.boss_map);fallback={}
  for (group,k),v in self.vars.items():
   if group=='music' and v.get().strip():music[k]=v.get().strip()
   elif group=='fallback' and v.get().strip():fallback[k]=v.get().strip()
   elif group=='bossrow':
    n,t=v;name=n.get().strip()
    if name and t.get().strip():boss[name]=t.get().strip()
  self.cfg['music']=music;self.cfg['boss']=boss;self.cfg['fallback']=fallback;self.cfg['lobby']=self.lobby.get().strip()
  self.cfg.update(log=self.log.get(),fade=float(self.fade.get()),volume=int(self.volume.get()))
  try:
   tmp=CFG.with_suffix('.tmp');tmp.write_text(json.dumps(self.cfg,ensure_ascii=False,indent=2),'utf-8');tmp.replace(CFG);self.status.set('設定を保存しました') if not quiet else None
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
 def quick_start(self):
  # One-click setup: launch the player and begin log monitoring.
  # Browser autoplay policy still requires the first unlock click in Edge.
  self.open_player()
  self.start()
  self.status.set('開始しました。最初だけプレイヤーの「再生を有効化」を押してください')
 def play(self,track,fallback=''):
  track=track.strip()
  if not track:return
  if not track.startswith(('https://youtube.com/','https://www.youtube.com/','https://music.youtube.com/','https://youtu.be/')) and not Path(track).is_file():self.status.set('URLか存在する音楽ファイルを設定してください');return
  if Path(track).is_file():
   with lock:allowed_media.add(str(Path(track).resolve()))
  if fallback and Path(fallback).is_file():
   with lock:allowed_media.add(str(Path(fallback).resolve()))
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
  # Recover the latest game state from this session's recent log.
  self.root.after(250,lambda path=p:self.resume_from_log(path))
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
   else:self.status.set('現在の場面をログから特定できません。手動で曲を選択してください')
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
  bosses={n.casefold():t for n,t in self.boss_map.items() if n.strip() and t.strip()}
  # Prefer phase-specific override, then generic boss, then difficulty boss music.
  track=bosses.get(name.casefold()) or bosses.get(base.casefold())
  if track:self.play(track)
  else:self.play_auto('ボス')
 def close(self):
  self.stop.set();self.save(quiet=True);self.stop_music()
  if self.player_process is not None and self.player_process.poll() is None:
   try:
    # Dedicated Edge profile only; do not terminate unrelated Edge sessions.
    subprocess.run(['taskkill','/PID',str(self.player_process.pid),'/T','/F'],capture_output=True,timeout=3,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   except Exception:pass
  self.root.destroy()
if __name__=='__main__':
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 root=tk.Tk();App(root,server.server_port);root.mainloop();server.shutdown()
