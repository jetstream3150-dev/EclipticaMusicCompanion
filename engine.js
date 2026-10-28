const aud = [new Audio(), new Audio()], yt = [null, null], ytReady = [false, false];
let active = 0, seq = 0, unlocked = false, ready = false, pending = null;
let last = -1, lastVolSeq = -1, master = 0.8, currentGain = [0, 0];
let currentTask = null, fadeFrame = 0, youtubeWait = null;
const statusEl = document.getElementById('status');

function status(msg) {
  statusEl.textContent = msg;
  fetch('/player-status', {method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({status:msg})}).catch(() => {});
}
function setGain(i, gain) {
  currentGain[i] = Math.max(0, Math.min(1, gain));
  const v = currentGain[i] * master;
  aud[i].volume = v;
  if (yt[i] && typeof yt[i].setVolume === 'function') {
    try { yt[i].setVolume(Math.round(v * 100)); } catch (_) {}
  }
}
function setMaster(v) {
  master = Math.max(0, Math.min(1, Number(v) || 0));
  for (let i = 0; i < 2; i++) setGain(i, currentGain[i]);
}
function stop(i) {
  aud[i].pause(); aud[i].removeAttribute('src'); aud[i].load();
  if (yt[i] && yt[i].stopVideo) try { yt[i].stopVideo(); } catch (_) {}
  setGain(i, 0);
}
function clearYoutubeWait() {
  if (youtubeWait !== null) clearTimeout(youtubeWait);
  youtubeWait = null;
}
function stopAll() {
  clearYoutubeWait(); pending = null; currentTask = null; seq++;
  cancelAnimationFrame(fadeFrame); stop(0); stop(1); status('停止中');
}
function vid(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:' || u.username || u.password) return null;
    let id = null;
    if (u.hostname === 'youtu.be') id = u.pathname.replace(/^\/+|\/+$/g, '');
    else if (['youtube.com','www.youtube.com','m.youtube.com','music.youtube.com'].includes(u.hostname)) {
      if (u.pathname === '/watch') id = u.searchParams.get('v');
      else if (u.pathname.startsWith('/shorts/') || u.pathname.startsWith('/embed/')) id = u.pathname.split('/')[2];
    }
    return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
  } catch (_) { return null; }
}
function onYouTubeIframeAPIReady() {
  ready = true;
  for (let i = 0; i < 2; i++) {
    yt[i] = new YT.Player('yt' + i, {height:'200', width:'220', videoId:'',
      playerVars:{playsinline:1, controls:1, origin:location.origin},
      events:{
        onReady:() => { ytReady[i] = true; if (pending && unlocked) runPending(); },
        onError:e => handleYoutubeError(i, e.data),
        onAutoplayBlocked:() => handleYoutubeError(i, 'autoplay'),
        onStateChange:e => {
          if (e.data === YT.PlayerState.ENDED && currentTask && currentTask.slot === i && active === i && !pending) {
            try { yt[i].seekTo(0, true); yt[i].playVideo(); status('ループ再生中: ' + currentTask.track); }
            catch (err) { status('ループ再生に失敗: ' + err.message); }
          }
        }
      }});
  }
  status('YouTubeプレイヤーを準備しています');
}
function youtubeMessage(code) {
  if (code === 'autoplay') return 'ブラウザがYouTubeの自動再生を止めました';
  if (code === 101 || code === 150) return 'YouTubeで再生できません（エラー' + code + '、埋め込み制限など）';
  if (code === 100) return 'YouTube動画が見つからないか公開されていません（エラー100）';
  if (code === 153) return 'YouTubeがプレイヤーの識別情報を確認できません（エラー153）';
  return 'YouTube再生エラー ' + code;
}
function handleYoutubeError(i, code) {
  if (!currentTask || currentTask.slot !== i || !vid(currentTask.track)) return;
  const task = currentTask, message = youtubeMessage(code);
  if (task.fallback) {
    stop(i);
    requestPlay(task.fallback, task.fade, task.vol, '', message + '\n予備BGMに切り替えました');
  } else {
    seq++; cancelAnimationFrame(fadeFrame); currentTask = null; stop(0); stop(1);
    status(message + '\n予備音源が未設定です');
  }
}
function requestPlay(track, fade, vol, fallback = '', notice = '') {
  clearYoutubeWait();
  pending = {track, fade:Number(fade) || 0, vol:Number(vol) || 0, fallback, notice};
  runPending();
}
async function runPending() {
  if (!pending) return;
  if (!unlocked) { status('再生待ち: 「▶ 再生を有効化」を押してください'); return; }
  const task = pending, id = vid(task.track), i = 1 - active, old = active;
  if (id && (!ready || !ytReady[i] || !yt[i] || typeof yt[i].loadVideoById !== 'function')) {
    status('YouTubeプレイヤーを準備中です');
    if (youtubeWait === null) youtubeWait = setTimeout(() => {
      youtubeWait = null;
      if (pending !== task) return;
      if (task.fallback) requestPlay(task.fallback, task.fade, task.vol, '', 'YouTubeの準備ができませんでした\n予備BGMに切り替えました');
      else { pending = null; status('YouTubeの準備ができませんでした。接続を確認してください'); }
    }, 10000);
    return;
  }
  clearYoutubeWait(); pending = null;
  const ticket = ++seq, previous = currentTask;
  cancelAnimationFrame(fadeFrame); stop(i);
  // Do not automatically play two embedded YouTube videos at the same time.
  if (id && previous && previous.slot === old && vid(previous.track)) stop(old);
  currentTask = {...task, slot:i};
  try {
    if (id) { yt[i].loadVideoById(id); setGain(i, 0); }
    else {
      aud[i].src = '/media?path=' + encodeURIComponent(task.track);
      aud[i].loop = true;
      aud[i].onerror = () => { if (ticket === seq) status('音楽ファイルを読み込めませんでした'); };
      await aud[i].play();
    }
  } catch (err) {
    if (ticket === seq) {
      if (err && err.name === 'NotAllowedError') {
        pending = task; unlocked = false; status('ブラウザが再生を止めました。「▶ 再生を有効化」を押してください');
      } else status('再生失敗: ' + (err && err.message || err));
    }
    return;
  }
  if (ticket !== seq) return;
  active = i; setMaster(task.vol); status(task.notice || '再生中: ' + task.track);
  const initialOld = currentGain[old], start = performance.now(), duration = Math.max(0, task.fade) * 1000;
  function step(now) {
    if (ticket !== seq) return;
    const t = duration ? Math.min(1, (now - start) / duration) : 1;
    setGain(i, t); setGain(old, (1 - t) * initialOld);
    if (t < 1) fadeFrame = requestAnimationFrame(step); else stop(old);
  }
  fadeFrame = requestAnimationFrame(step);
}
function unlock() {
  unlocked = true; status('再生を有効化しました');
  if (pending) runPending();
}
// Keep this name separate from the UI's own status polling function.
async function pollEngine() {
  try {
    const r = await fetch('/state', {cache:'no-store'}), x = await r.json();
    if (x.volume_seq !== lastVolSeq) { lastVolSeq = x.volume_seq; setMaster(x.volume); }
    if (x.seq !== last) {
      last = x.seq;
      if (x.stop) stopAll(); else if (x.track) requestPlay(x.track, x.fade, x.volume, x.fallback || '');
    }
  } catch (_) { status('アプリとの通信に失敗: ' + _.message); }
  if (pending && unlocked) runPending();
  setTimeout(pollEngine, 500);
}
status('アプリに接続しました'); pollEngine();
