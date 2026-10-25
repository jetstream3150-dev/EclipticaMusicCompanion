import json,os,re,threading,time,webbrowser,mimetypes,sys
from pathlib import Path
from urllib.parse import urlparse,parse_qs,unquote
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import tkinter as tk
import webview
from tkinter import ttk,filedialog,messagebox
BASE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
USER_DIR=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else BASE
CFG=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'EclipticaMusicCompanion'/'settings.json'
CFG.parent.mkdir(parents=True,exist_ok=True)
LOG=Path(os.environ.get('USERPROFILE',str(Path.home())))/'AppData/LocalLow/VRChat/VRChat'
DEFAULT={'round':{},'phase':{},'boss':{},'fade':2.0,'volume':80,'log':'','auto':True}
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
  self.root=root;self.port=port;self.cfg=json.loads(CFG.read_text('utf-8')) if CFG.exists() else json.loads(json.dumps(DEFAULT));self.stop=threading.Event();self.worker=None;self.round=0;self.boss='';self.laststage='';self.vars={};root.title('Ecliptica Music Companion v0.4');root.geometry('800x670');self.status=tk.StringVar(value='待機中');self.fade=tk.DoubleVar(value=self.cfg.get('fade',2));self.volume=tk.IntVar(value=self.cfg.get('volume',80));self.log=tk.StringVar(value=self.cfg.get('log',''));self.build();root.protocol('WM_DELETE_WINDOW',self.close);root.after(400,self.open_player);root.after(1200,self.auto_start)
 def build(self):
  f=ttk.Frame(self.root,padding=12);f.pack(fill='both',expand=True)
  ttk.Label(f,text='🎵 Ecliptica Music Companion',font=('',16,'bold')).pack(anchor='w')
  ttk.Label(f,text='YouTube URLを貼るか、MP3・WAVを選択。フェード切替で自分だけに再生します。').pack(anchor='w',pady=6)
  r=ttk.Frame(f);r.pack(fill='x');ttk.Label(r,text='VRChatログ').pack(side='left');ttk.Entry(r,textvariable=self.log).pack(side='left',fill='x',expand=True,padx=5);ttk.Button(r,text='自動検出',command=self.detect).pack(side='left')
  r=ttk.Frame(f);r.pack(fill='x',pady=6);ttk.Label(r,text='フェード秒').pack(side='left');ttk.Spinbox(r,from_=0,to=15,increment=.5,textvariable=self.fade,width=6).pack(side='left',padx=5);ttk.Label(r,text='音量 %').pack(side='left',padx=12);ttk.Spinbox(r,from_=0,to=100,textvariable=self.volume,width=6).pack(side='left');ttk.Button(r,text='保存',command=self.save).pack(side='right')
  nb=ttk.Notebook(f);nb.pack(fill='both',expand=True)
  for key,title,items in [('round','ラウンド別',[str(i) for i in range(1,11)]),('phase','フェーズ別',[str(i) for i in range(1,6)]),('boss','ボス別',['Kakarot','Corus','Yuki','Gilgamesh'])]:
   frame=ttk.Frame(nb,padding=8);nb.add(frame,text=title)
   for k in items:
    var=tk.StringVar(value=self.cfg.get(key,{}).get(k,''));self.vars[(key,k)]=var
    row=ttk.Frame(frame);row.pack(fill='x',pady=3);ttk.Label(row,text=k,width=14).pack(side='left');ttk.Entry(row,textvariable=var).pack(side='left',fill='x',expand=True,padx=4);ttk.Button(row,text='ファイル',command=lambda v=var:self.pick(v)).pack(side='left');ttk.Button(row,text='▶',command=lambda v=var:self.play(v.get())).pack(side='left')
  r=ttk.Frame(f);r.pack(fill='x',pady=10);ttk.Button(r,text='▶ 自動監視開始',command=self.start).pack(side='left');ttk.Button(r,text='■ 監視停止',command=self.stop_watch).pack(side='left',padx=5);ttk.Button(r,text='■ BGM停止',command=self.stop_music).pack(side='left');ttk.Button(r,text='プレイヤー表示',command=self.open_player).pack(side='right')
  ttk.Label(f,textvariable=self.status,relief='sunken').pack(fill='x')
 def pick(self,v):
  p=filedialog.askopenfilename(filetypes=[('音楽','*.mp3 *.wav *.ogg *.m4a')]);
  if p:v.set(p)
 def save(self):
  for (group,k),v in self.vars.items():self.cfg.setdefault(group,{})[k]=v.get().strip()
  self.cfg.update(log=self.log.get(),fade=float(self.fade.get()),volume=int(self.volume.get()));CFG.write_text(json.dumps(self.cfg,ensure_ascii=False,indent=2),'utf-8');self.status.set('設定保存済み')
 def detect(self):
  files=sorted(LOG.glob('output_log_*.txt'),key=lambda p:p.stat().st_mtime,reverse=True)
  if files:self.log.set(str(files[0]));self.status.set('最新ログを選択しました')
  else:messagebox.showwarning('ログ未検出','VRChatを起動してから再度お試しください。')
 def open_player(self):
  if not getattr(self,'player_thread',None) or not self.player_thread.is_alive():
   self.player_thread=threading.Thread(target=self.run_player,daemon=True);self.player_thread.start()
 def run_player(self):
  try:
   webview.create_window('Ecliptica BGM Player',f'http://127.0.0.1:{self.port}/',width=570,height=400)
   webview.start(gui='edgechromium',private_mode=False)
  except Exception as e:
   self.root.after(0,lambda msg=str(e):messagebox.showerror('プレイヤー起動失敗',msg+'\nWebView2 Runtimeが必要な場合があります。'))
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
     if not line:time.sleep(.25);continue
     stage=re.search(r'ECLIPTICA - now in stage: (.+?) on phase:',line)
     boss=re.search(r'ECLIPTICA - now fighting boss: (.+?)\(Clone\) on phase:',line)
     if stage:
      name=stage.group(1)
      if name!=self.laststage:
       self.laststage=name;self.round+=1;self.boss='';track=self.cfg.get('round',{}).get(str(self.round),'')
       if track:self.root.after(0,lambda t=track:self.play(t))
     elif boss:
      name=boss.group(1)
      if name!=self.boss:
       self.boss=name;phase=re.search(r'Phase(\d+)$',name);base=re.sub(r'Phase\d+$','',name)
       track=(self.cfg.get('phase',{}).get(phase.group(1),'') if phase else '') or self.cfg.get('boss',{}).get(base,'')
       if track:self.root.after(0,lambda t=track:self.play(t))
  except Exception as e:self.root.after(0,lambda msg=str(e):self.status.set('ログ読み込み失敗: '+msg))
 def close(self):self.stop.set();self.stop_music();self.root.destroy()
if __name__=='__main__':
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 root=tk.Tk();App(root,server.server_port);root.mainloop();server.shutdown()
