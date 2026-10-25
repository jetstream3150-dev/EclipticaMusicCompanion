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
DEFAULT={'round':{},'waiting':{},'phase':{},'boss':{},'music':{},'fade':2.0,'volume':80,'log':'','auto':False}
state={'seq':0,'track':'','fade':2,'volume':.8,'stop':False}
lock=threading.Lock()
allowed_media=set()
class Handler(BaseHTTPRequestHandler):
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
  self.root=root;self.port=port;self.cfg=self.load_config();self.stop=threading.Event();self.worker=None;self.round=0;self.boss='';self.laststage='';self.vars={};self.difficulty=tk.StringVar(value='Primal');self.phase_choice=tk.StringVar(value='休憩');self.current_round=tk.IntVar(value=1);root.title('Ecliptica Music Companion v1.0 配布準備版');root.geometry('980x760');root.minsize(800,620);self.status=tk.StringVar(value='待機中');self.fade=tk.DoubleVar(value=self.cfg.get('fade',2));self.volume=tk.IntVar(value=self.cfg.get('volume',80));self.log=tk.StringVar(value=self.cfg.get('log',''));self.build();root.protocol('WM_DELETE_WINDOW',self.close);root.after(400,self.open_player);root.after(1200,self.auto_start)
 def build(self):
  style=ttk.Style(self.root)
  try:style.theme_use('clam')
  except tk.TclError:pass
  style.configure('Title.TLabel',font=('',18,'bold'))
  style.configure('Action.TButton',padding=(10,7))
  f=ttk.Frame(self.root,padding=14);f.pack(fill='both',expand=True)
  ttk.Label(f,text='ECLIPTICA  MUSIC COMPANION  v1.0',style='Title.TLabel').pack(anchor='w')
  ttk.Label(f,text='個人用BGMプレイヤー ｜ 設定はPCごとに保存 ｜ VRChat本体は変更しません',foreground='#496a9b').pack(anchor='w',pady=(3,10))
  control=ttk.LabelFrame(f,text='1. 操作パネル',padding=9);control.pack(fill='x')
  r=ttk.Frame(control);r.pack(fill='x',pady=3)
  ttk.Button(r,text='▶ 監視開始',command=self.start,style='Action.TButton').pack(side='left')
  ttk.Button(r,text='■ 監視停止',command=self.stop_watch).pack(side='left',padx=4)
  ttk.Button(r,text='■ BGM停止',command=self.stop_music).pack(side='left',padx=4)
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
  ttk.Label(r,text='音量(%)').pack(side='left',padx=(12,0));ttk.Spinbox(r,from_=0,to=100,textvariable=self.volume,width=6).pack(side='left',padx=5)
  ttk.Button(r,text='💾 保存',command=self.save,style='Action.TButton').pack(side='right')
  r=ttk.Frame(control);r.pack(fill='x',pady=3)
  ttk.Button(r,text='設定をバックアップ',command=self.export_config).pack(side='left')
  ttk.Button(r,text='設定を復元',command=self.import_config).pack(side='left',padx=5)
  ttk.Button(r,text='保存先を開く',command=self.open_config_dir).pack(side='left',padx=5)
  nb=ttk.Notebook(f);nb.pack(fill='both',expand=True,pady=(12,7))
  guide=ttk.Frame(nb,padding=14);nb.add(guide,text='はじめに')
  for t in ['① 「難易度別BGM」で戦闘・準備・ボス・終了・休憩の曲を登録','② 「ボス別BGM」で特定ボスの曲を上書き設定（任意）','③ 保存 → 黒いプレイヤーで「再生を有効化」 → 監視開始（自動監視は初期状態でOFF）','④ 途中参加時は、難易度とフェーズを選択して手動再生できます','※ 自動判定はステージ開始・ボス開始のみ試験対応。休憩などは手動切替してください。', '※ YouTube動画は埋め込み制限により再生できない場合があります。', '※ 音楽ファイルはこのPCの絶対パスで保存されます。別PCへの設定移行時は再指定が必要です。']:
   ttk.Label(guide,text=t,wraplength=820).pack(anchor='w',pady=9)
  tracks=ttk.Frame(nb,padding=10);nb.add(tracks,text='難易度別BGM')
  ttk.Label(tracks,text='難易度ごとに5つのフェーズの曲を登録します。休憩はラウンド終了後の「世界の狭間」です。',foreground='#496a9b').pack(anchor='w',pady=(0,8))
  canvas=tk.Canvas(tracks,highlightthickness=0);bar=ttk.Scrollbar(tracks,orient='vertical',command=canvas.yview)
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
    ttk.Button(r,text='▶',width=3,command=lambda x=v:self.play(x.get())).pack(side='left')
  bosses=ttk.Frame(nb,padding=10);nb.add(bosses,text='ボス別BGM')
  ttk.Label(bosses,text='ボス名は自由に追加できます。ログ内のボス名と一致した場合に優先します。',foreground='#496a9b').pack(anchor='w',pady=(0,8))
  self.boss_rows=ttk.Frame(bosses);self.boss_rows.pack(fill='both',expand=True)
  for name,track in self.cfg.get('boss',{}).items():self.add_boss_row(name,track)
  if not self.cfg.get('boss'):self.add_boss_row('','')
  ttk.Button(bosses,text='＋ ボスを追加',command=lambda:self.add_boss_row('','')).pack(anchor='w',pady=8)
  ttk.Label(f,text='自動監視はログのステージ/ボス通知を利用します。難易度・準備・終了・休憩の自動判定は未検証です。',foreground='#98621b').pack(anchor='w')
  ttk.Label(f,textvariable=self.status,relief='sunken',padding=8).pack(fill='x',pady=(7,0))
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
  ttk.Entry(r,textvariable=n,width=22).pack(side='left',padx=4)
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
  self.play(track)
 def play_auto(self,phase):
  difficulty=self.difficulty.get();key=difficulty+'|'+phase
  v=self.vars.get(('music',key));track=v.get().strip() if v else ''
  if track:self.play(track)
  else:self.status.set(f'{difficulty} / {phase} の曲は未設定です')
 def pick(self,v):
  p=filedialog.askopenfilename(filetypes=[('音楽','*.mp3 *.wav *.ogg *.m4a')]);
  if p:v.set(p)
 def save(self):
  music={};boss={}
  for (group,k),v in self.vars.items():
   if group=='music' and v.get().strip():music[k]=v.get().strip()
   elif group=='bossrow':
    n,t=v;name=n.get().strip()
    if name and t.get().strip():boss[name]=t.get().strip()
  self.cfg['music']=music;self.cfg['boss']=boss
  self.cfg.update(log=self.log.get(),fade=float(self.fade.get()),volume=int(self.volume.get()))
  try:
   tmp=CFG.with_suffix('.tmp');tmp.write_text(json.dumps(self.cfg,ensure_ascii=False,indent=2),'utf-8');tmp.replace(CFG);self.status.set('設定を保存しました')
  except Exception as e:messagebox.showerror('保存失敗',str(e))
 def detect(self):
  files=sorted(LOG.glob('output_log_*.txt'),key=lambda p:p.stat().st_mtime,reverse=True)
  if files:self.log.set(str(files[0]));self.status.set('最新ログを選択しました')
  else:messagebox.showwarning('ログ未検出','VRChatを起動してから再度お試しください。')
 def open_player(self):
  # Launch Edge in app mode, avoiding pywebview/pythonnet runtime errors.
  if getattr(self,'player_process',None) is not None and self.player_process.poll() is None:
   return
  url=f'http://127.0.0.1:{self.port}/'
  candidates=[
   Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe',
   Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Microsoft/Edge/Application/msedge.exe',
   Path(os.environ.get('LOCALAPPDATA',''))/'Microsoft/Edge/Application/msedge.exe'
  ]
  edge=next((str(x) for x in candidates if x.is_file()),None)
  if not edge:
   messagebox.showerror('プレイヤー起動失敗','Microsoft Edgeが見つかりません。Edgeがインストールされているか確認してください。')
   return
  try:
   self.player_process=subprocess.Popen([edge,'--app='+url,'--window-size=570,400'],close_fds=True)
   self.status.set('音楽プレイヤーを起動しました')
  except Exception as e:
   messagebox.showerror('プレイヤー起動失敗',str(e))
 def play(self,track):
  track=track.strip()
  if not track:return
  if not track.startswith(('https://youtube.com/','https://www.youtube.com/','https://music.youtube.com/','https://youtu.be/')) and not Path(track).is_file():self.status.set('URLか存在する音楽ファイルを設定してください');return
  if Path(track).is_file():
   with lock:allowed_media.add(str(Path(track).resolve()))
  with lock:state.update(seq=state['seq']+1,track=track,fade=max(0,float(self.fade.get())),volume=max(0,min(100,int(self.volume.get())))/100,stop=False)
  self.status.set('切替指示: '+track[:65])
 def stop_music(self):
  with lock:state.update(seq=state['seq']+1,stop=True)
 def auto_start(self):
  if self.cfg.get('auto',True):self.start()
 def start(self):
  self.save();p=Path(self.log.get())
  if not p.is_file():self.detect();p=Path(self.log.get())
  if not p.is_file():self.status.set('VRChatのログが見つかりません。VRChat起動後に監視開始してください');return
  self.stop.set()
  self.stop=threading.Event();self.round=0;self.boss='';self.laststage='';self.worker=threading.Thread(target=self.watch,args=(p,self.stop),daemon=True);self.worker.start();self.open_player();self.status.set('監視中: '+p.name)
 def stop_watch(self):self.stop.set();self.status.set('監視停止')
 def watch(self,p,signal):
  try:
   with p.open('r',encoding='utf-8',errors='replace') as f:
    f.seek(0,2)
    while not signal.is_set():
     line=f.readline()
     if not line:
      time.sleep(.25)
      try:
       newest=max(LOG.glob('output_log_*.txt'),key=lambda x:x.stat().st_mtime,default=None)
       if newest and newest!=p and newest.stat().st_mtime>p.stat().st_mtime:
        self.root.after(0,lambda:self.status.set('新しいVRChatログを検出しました。監視開始を押して切り替えてください。'))
      except OSError:pass
      continue
     stage=re.search(r'ECLIPTICA - now in stage: (.+?) on phase:',line)
     boss=re.search(r'ECLIPTICA - now fighting boss: (.+?)\(Clone\) on phase:',line)
     if stage:
      name=stage.group(1)
      if name!=self.laststage:
       self.laststage=name;self.boss=''
       self.root.after(0,lambda:self.phase_choice.set('戦闘'))
       self.root.after(0,lambda:self.play_auto('戦闘'))
     elif boss:
      name=boss.group(1).strip()
      if name!=self.boss:
       self.boss=name
       base=re.sub(r'\s*Phase\d+$','',name,flags=re.I).strip()
       def update(n=name,b=base):
        self.phase_choice.set('ボス')
        matches=[(k,v) for k,v in self.cfg.get('boss',{}).items() if k.casefold() in (n.casefold(),b.casefold())]
        if matches:self.play(matches[0][1])
        else:self.play_auto('ボス')
       self.root.after(0,update)
  except Exception as e:self.root.after(0,lambda msg=str(e):self.status.set('ログ読み込み失敗: '+msg))
 def close(self):
  self.stop.set();self.stop_music()
  self.root.destroy()
if __name__=='__main__':
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 root=tk.Tk();App(root,server.server_port);root.mainloop();server.shutdown()
