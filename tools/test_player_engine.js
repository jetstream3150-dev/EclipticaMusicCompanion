'use strict';
// Deterministic engine tests. YouTube is simulated; these do not certify real playback.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const events = [], players = [], frames = [];
class AudioStub {
  constructor() { this.volume = 0; this.paused = true; this.src = ''; }
  pause() { this.paused = true; }
  removeAttribute(name) { if (name === 'src') this.src = ''; }
  load() {}
  play() { this.paused = false; return Promise.resolve(); }
}
const document = {hidden: false, getElementById: () => ({textContent: ''}), addEventListener() {}};
const context = vm.createContext({
  Audio: AudioStub, document, URL, location: {origin: 'http://localhost'},
  window: {dispatchEvent(e) { events.push('result:' + e.detail.result); }},
  CustomEvent: class { constructor(name, data) { this.detail = data.detail; } },
  fetch: url => url === '/state' ? new Promise(() => {}) : Promise.resolve({}),
  setInterval() {}, setTimeout() { return 1; }, clearTimeout() {},
  requestAnimationFrame: fn => { frames.push(fn); return frames.length; },
  cancelAnimationFrame() {}, performance: {now: () => 0},
  YT: {PlayerState: {ENDED: 0}, Player: function(id, options) {
    this.options = options; this.volume = 0; this.stopped = true;
    this.loadVideoById = video => { events.push('load:' + video); this.video = video; this.stopped = false; };
    this.stopVideo = () => { events.push('stop'); this.stopped = true; };
    this.setVolume = n => { this.volume = n; };
    this.seekTo = () => {}; this.playVideo = () => {};
    players.push({id, player: this});
  }}
});
vm.runInContext(fs.readFileSync('engine.js', 'utf8'), context);
const run = code => vm.runInContext(code, context);
const tick = async () => { await new Promise(resolve => setImmediate(resolve)); while (frames.length) frames.shift()(5000); await new Promise(resolve => setImmediate(resolve)); };
(async () => {
  run('onYouTubeIframeAPIReady()');
  assert.equal(players.length, 1); assert.equal(players[0].id, 'yt0');
  players[0].player.options.events.onReady({});
  run('unlock()');
  run("requestPlay('https://www.youtube.com/watch?v=Allowed1234', 0.1, 0.8)"); await tick();
  players[0].player.options.events.onStateChange({data: 1});
  assert.equal(players[0].player.volume, 80);
  assert.equal(players[0].player.stopped, false);
  run("requestPlay('https://www.youtube.com/watch?v=Allowed5678', 0.1, 0.8)"); await tick();
  const next = events.lastIndexOf('load:Allowed5678');
  assert.equal(events[next-1], 'stop');
  assert.equal(players[0].player.stopped, false);
  assert.equal(players[0].player.volume, 80);
  assert.equal(players.length, 1);
  run("requestPlay('C:/music/example.wav', 0.1, 0.8)"); await tick();
  assert.equal(players[0].player.stopped, true);
  assert.equal(run('aud[active].paused'), false);
  assert.equal(run('aud[active].volume'), 0.8);
  run("requestPlay('https://www.youtube.com/watch?v=Allowed1234', 0.1, 0.8)"); await tick();
  assert.equal(run('aud.every(a => a.paused)'), true);
  assert.equal(players[0].player.stopped, false);
  assert.equal(players[0].player.volume, 80);
  players[0].player.options.events.onError({data:150});
  assert.equal(run('aud.every(a => a.paused)'), true);
  assert.equal(players[0].player.stopped, true);
  assert.equal(run('statusEl.textContent.includes("エラー150")'), true);
  run("requestPlay('https://www.youtube.com/watch?v=Allowed1234', 0.1, 0.8, 'C:/music/fallback.wav')"); await tick();
  players[0].player.options.events.onError({data:150}); await tick();
  assert.equal(run('aud[active].src.includes("fallback.wav")'), true);
  assert.equal(run('aud[active].paused'), false);
  run('stopAll()');
  assert.equal(run('aud.every(a => a.paused)'), true);
  assert.equal(players[0].player.stopped, true);
  console.log('PASS: one YouTube player, transitions, errors, local fallback, and stop');
})().catch(e => { console.error(e); process.exitCode = 1; });
