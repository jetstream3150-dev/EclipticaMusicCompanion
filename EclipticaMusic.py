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
  if self.path!='/player-status' or self.client_address[0]!='127.0.0.1' or self.headers.get('Host','').split(':')[0] not in ('127.0.0.1','localhost'):
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
  self.root=root;self.port=port;self.cfg=self.load_config();self.stop=threading.Event();self.worker=None;self.round=0;self.boss='';self.laststage='';self.vars={};self.difficulty=tk.StringVar(value='Primal');self.phase_choice=tk.StringVar(value='休憩');self.current_round=tk.IntVar(value=1);root.title('Ecliptica Music Companion v1.6.1 β');root.geometry('920x760');root.minsize(650,540);root.configure(bg='#0b1020');self.status=tk.StringVar(value='待機中');self.event_status=tk.StringVar(value='検知イベント: なし');self.fade=tk.DoubleVar(value=self.cfg.get('fade',2));self.volume=tk.IntVar(value=self.cfg.get('volume',80));self.log=tk.StringVar(value=self.cfg.get('log',''));self.player_process=None;self.player_launched=False;self.player_status=tk.StringVar(value='プレイヤー: 未接続');self.build();root.protocol('WM_DELETE_WINDOW',self.close);root.after(1200,self.auto_start);root.after(1500,self.refresh_player_status)
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
  ttk.Label(outer,text='MUSIC COMPANION   •   v1.6.1',style='Muted.TLabel').pack(anchor='w',pady=(0,12))
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
  ttk.Label(home,text='いまのゲーム（手動選択・試聴用）',style='Heading.TLabel').pack(anchor='w',pady=(20,7))
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
  section=ttk.LabelFrame(parent,text='🎵 許可されたYouTube音源をMP3として保存',padding=10)
  section.pack(fill='x',pady=(20,8))
  ttk.Label(section,text='自分が権利を持つ、またはダウンロードの許可を得た動画のみ使用してください。',style='Muted.TLabel',wraplength=700).pack(anchor='w')
  url=tk.StringVar()
  row=ttk.Frame(section);row.pack(fill='x',pady=(8,5))
  ttk.Entry(row,textvariable=url).pack(side='left',fill='x',expand=True,padx=(0,6))
  ttk.Button(row,text='URLを貼り付け',command=lambda:self.paste_url(url)).pack(side='left')
  authorized=tk.BooleanVar(value=False)
  ttk.Checkbutton(section,text='この動画のダウンロード・MP3変換が許可されていることを確認しました',variable=authorized).pack(anchor='w',pady=5)
  status=tk.StringVar(value='保存先：アプリの設定フォルダ内の DownloadedMusic')
  ttk.Label(section,textvariable=status,style='Muted.TLabel',wraplength=700).pack(fill='x',pady=(3,5))
  btn=ttk.Button(section,text='⬇ MP3に保存して、この曲に登録')
  btn.configure(command=lambda:self.download_authorized_mp3(url.get(),authorized.get(),target_var,status,btn))
  btn.pack(anchor='w')
 def paste_url(self,var):
  try:var.set(self.root.clipboard_get().strip())
  except tk.TclError:self.status.set('クリップボードにテキストがありません')
  else:self.status.set('URLを貼り付けました')
 def download_authorized_mp3(self,url,authorized,target_var,status,button):
  url=url.strip()
  if not authorized:
   messagebox.showwarning('利用許可を確認','ダウンロードが許可された音源であることを確認し、チェックしてください。');return
  parsed=urlparse(url)
  host=(parsed.hostname or '').lower()
  if parsed.scheme!='https' or host not in ('youtube.com','www.youtube.com','m.youtube.com','music.youtube.com','youtu.be'):
   messagebox.showwarning('URLが正しくありません','YouTubeのhttps://で始まるURLを貼り付けてください。');return
  try:
   import yt_dlp,imageio_ffmpeg
  except ImportError:
   messagebox.showerror('必要な機能がありません','MP3変換用ライブラリが見つかりません。v1.6のGitHub Actionsで再ビルドしてください。');return
  button.configure(state='disabled');status.set('動画を確認しています…')
  destination=CFG.parent/'DownloadedMusic'
  destination.mkdir(parents=True,exist_ok=True)
  def worker():
   try:
    ffmpeg=imageio_ffmpeg.get_ffmpeg_exe()
    if not Path(ffmpeg).is_file():raise RuntimeError('FFmpegが見つかりません')
    opts={'format':'bestaudio/best','noplaylist':True,'quiet':True,'no_warnings':True,'socket_timeout':20,'retries':2,
          'outtmpl':str(destination/'%(id)s.%(ext)s'),
          'ffmpeg_location':ffmpeg,
          'postprocessors':[{'key':'FFmpegExtractAudio','preferredcodec':'mp3','preferredquality':'192'}]}
    with yt_dlp.YoutubeDL(opts) as ydl:
     info=ydl.extract_info(url,download=False)
     if not info or info.get('_type')=='playlist':raise ValueError('単一の動画URLを指定してください')
     if (info.get('duration') or 0)>7200:raise ValueError('2時間を超える動画は対象外です')
     video_id=str(info.get('id',''))
     if not re.fullmatch(r'[a-zA-Z0-9_-]{6,32}',video_id):raise ValueError('動画IDを取得できません')
     mp3=destination/(video_id+'.mp3')
     if not mp3.is_file():
      self.root.after(0,lambda:status.set('MP3に変換しています…'))
      ydl.download([url])
     if not mp3.is_file() or mp3.stat().st_size<1000:raise RuntimeError('MP3ファイルの作成に失敗しました')
    def done():
     target_var().set(str(mp3));self.save(quiet=True)
     status.set('保存・曲の登録が完了しました: '+mp3.name)
     self.status.set('MP3を登録しました。試聴ボタンで確認できます')
     button.configure(state='normal')
    self.root.after(0,done)
   except Exception as exc:
    msg=str(exc).splitlines()[0][:220]
    def failed():
     status.set('変換できませんでした: '+msg)
     button.configure(state='normal')
    self.root.after(0,failed)
  threading.Thread(target=worker,daemon=True).start()
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
 BOSS_CHOICES=('Kakarot', 'Nan', 'BuffNoob', 'Pride', 'Steven', 'Amaziah', 'JackedPumpkin', 'QueenVolt', 'M41D', 'Corus', 'CorusPhase2', 'Yuki', 'YukiPhase2', 'Pandora', 'Mephiel', 'MephielPhase2', 'OnyxPilot', 'NeoPilot', 'Gilgamesh', 'GilgameshPhase2', 'GilgameshPhase3', 'GoldenGrouch', 'DarkMouth')
 DIFFICULTIES=('Primal','Penumbra','Antumbra','Umbra','Eclipse','Eye of the Eclipse')
 PHASES=('戦闘','準備','ボス','終了','休憩')
 def load_config(self):
  if not CFG.exists():return json.loads(json.dumps(DEFAULT))
  try:
   obj=json.loads(CFG.read_text('utf-8'))
   if not isinstance(obj,dict):raise ValueError('設定の形式が正しくありません')
   cfg=json.loads(json.dumps(DEFAULT));cfg.update(obj)
   if not isinstance(cfg.get('music'),dict) or not isinstance(cfg.get('boss'),dict) or not isinstance(cfg.get('fallback'),dict):raise ValueError('曲設定が正しくありません')
   return cfg
  except Exception:
   try:CFG.rename(CFG.with_name('settings_broken_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.json'))
   except OSError:pass
   return json.loads(json.dumps(DEFAULT))
 def export_config(self):
  self.save()
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
   if not messagebox.askyesno('確認','現在の設定を置き換えてアプリを再起動しますか？'):return
   CFG.write_text(json.dumps(obj,ensure_ascii=False,indent=2),'utf-8')
   messagebox.showinfo('復元完了','設定を復元しました。アプリを終了して起動し直してください。')
  except Exception as e:messagebox.showerror('復元失敗',str(e))
 def open_config_dir(self):
  try:os.startfile(str(CFG.parent));self.status.set('設定の保存先を開きました')
  except Exception as e:messagebox.showerror('開けませんでした',str(e))
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
  else:self.stop_music();self.status.set(f'{difficulty} / {phase} の曲は未設定のため停止しました')
 def pick(self,v):
  p=filedialog.askopenfilename(filetypes=[('音楽','*.mp3 *.wav *.ogg *.m4a')]);
  if p:
   v.set(p)
   self.status.set('音楽ファイルを選びました。自動保存されます')
 def save(self,quiet=False):
  if self._saving:return
  self._saving=True
  if self._save_after is not None:
   self.root.after_cancel(self._save_after);self._save_after=None
  if hasattr(self,'music_editor') and not getattr(self,'_loading_editor',False):self.update_music_editor()
  if hasattr(self,'boss_track') and not getattr(self,'_loading_editor',False):self.update_boss_editor()
  music={};boss=dict(self.boss_map);fallback={}
  for (group,k),v in self.vars.items():
   if group=='music' and v.get().strip():music[k]=v.get().strip()
   elif group=='fallback' and v.get().strip():fallback[k]=v.get().strip()
  fallback.update({'boss|'+name:path for name,path in self.boss_fallback_map.items() if path.strip()})
  self.cfg['music']=music;self.cfg['boss']=boss;self.cfg['fallback']=fallback;self.cfg['lobby']=self.lobby.get().strip()
  try:fade=max(0,min(15,float(self.fade.get())))
  except (ValueError,tk.TclError):fade=2.0
  self.cfg.update(log=self.log.get(),fade=fade,volume=int(self.volume.get()))
  try:
   tmp=CFG.with_suffix('.tmp');tmp.write_text(json.dumps(self.cfg,ensure_ascii=False,indent=2),'utf-8');tmp.replace(CFG);self.status.set('設定を保存しました') if not quiet else None
  except Exception as e:messagebox.showerror('保存失敗',str(e))
  finally:self._saving=False
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
  if not track:return
  is_youtube=bool(re.match(r'^https://(www\.|m\.|music\.)?youtube\.com/(watch\?|shorts/|embed/)|^https://youtu\.be/',track,re.I))
  if not is_youtube and not Path(track).is_file():self.status.set('YouTubeのURLか存在する音楽ファイルを設定してください');return
  if Path(track).is_file():
   with lock:allowed_media.add(str(Path(track).resolve()))
  if fallback and Path(fallback).is_file() and Path(fallback).suffix.lower() in ('.mp3','.wav','.ogg','.m4a'):
   with lock:allowed_media.add(str(Path(fallback).resolve()))
  try:fade=max(0,min(15,float(self.fade.get())))
  except (ValueError,tk.TclError):fade=2.0
  with lock:state.update(seq=state['seq']+1,track=track,fade=fade,volume=max(0,min(100,int(self.volume.get())))/100,stop=False,fallback=fallback)
  self.status.set('▶ 再生を指示しました: '+track[:65])
 def stop_music(self):
  with lock:state.update(seq=state['seq']+1,stop=True)
  self.status.set('■ 停止を指示しました（プレイヤーに反映されます）')
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
  self._watch_generation+=1
  self.stop=threading.Event();self.round=0;self.boss='';self.laststage=''
  self.worker=threading.Thread(target=self.watch,args=(p,self.stop),daemon=True)
  self.worker.start();self.status.set('監視中: '+p.name)
  # Recover the latest game state from this session's recent log.
  generation=self._watch_generation
  self.root.after(250,lambda path=p,g=generation:self.resume_from_log(path) if g==self._watch_generation and not self.stop.is_set() else None)
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
  self._watch_generation+=1
  self.stop.set();self.status.set('■ 自動切り替えを停止しました')
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
   else:self.stop_music();self.status.set('ロビーBGMは未設定のため、前の曲を停止しました')
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
  if track:
   fallbacks={n.casefold():v for n,v in self.boss_fallback_map.items() if v.strip()}
   fallback=fallbacks.get(name.casefold()) or fallbacks.get(base.casefold(),'')
   self.play(track,fallback)
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
