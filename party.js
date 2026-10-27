/* Opt-in experimental party sharing. No connection or data is sent by default. */
(function (root) {
  'use strict';
  const ROOM = /^[A-Za-z0-9_-]{43}$/;
  const ID = /^[0-9a-f]{24}$/;
  const MAX_VALUE = 1_000_000_000_000;

  function endpoint(value) {
    if (typeof value !== 'string' || value.length > 512) throw new Error('中継先URLが不正です');
    const url = new URL(String(value).trim());
    const loopback = ['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname.toLowerCase());
    if (url.protocol !== 'wss:' && !(url.protocol === 'ws:' && loopback))
      throw new Error('中継先は wss:// を指定してください');
    if (url.username || url.password || url.search || url.hash)
      throw new Error('中継先URLに認証情報やパラメータは指定できません');
    return url.href;
  }

  function createInvite(server) {
    const url = endpoint(server);
    const bytes = new Uint8Array(32);
    root.crypto.getRandomValues(bytes);
    const token = root.btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    return JSON.stringify({version: 1, server: url, room: token});
  }

  function parseInvite(value) {
    let obj;
    if (typeof value !== 'string' || value.length > 2048) throw new Error('招待コードが不正です');
    try { obj = JSON.parse(value); } catch (_) { throw new Error('招待コードが不正です'); }
    if (!obj || obj.version !== 1 || typeof obj.room !== 'string' || !ROOM.test(obj.room))
      throw new Error('招待コードが不正です');
    return {server: endpoint(obj.server), room: obj.room};
  }

  function validText(value) {
    return typeof value === 'string' && value.length <= 40 && !/[\p{C}]/u.test(value);
  }

  function safeRoster(value) {
    if (!Array.isArray(value) || value.length > 12) return null;
    const output = [];
    for (const member of value) {
      if (!member || typeof member.id !== 'string' || !ID.test(member.id) ||
          !validText(member.name) || !validText(member.job) || typeof member.monitoring !== 'boolean') return null;
      if (['dps', 'boss_damage', 'total_damage'].some(k => typeof member[k] !== 'number' ||
          !Number.isFinite(member[k]) || member[k] < 0 || member[k] > MAX_VALUE)) return null;
      output.push({id: member.id, name: member.name, job: member.job, dps: member.dps,
                   boss_damage: member.boss_damage, total_damage: member.total_damage, monitoring: member.monitoring});
    }
    return output;
  }

  class Client {
    constructor(changed, WebSocketClass = root.WebSocket) {
      this.changed = changed;
      this.WebSocketClass = WebSocketClass;
      this.socket = null;
      this.status = '未接続';
      this.members = [];
      this.ownId = '';
      this.lastSend = 0;
      this.timer = null;
      this.retryTimer = null;
      this.attempt = 0;
      this.connection = null;
    }
    notify() { this.changed({status: this.status, members: this.members.slice(), ownId: this.ownId}); }
    connect(invite, name) {
      const parsed = parseInvite(invite);
      if (!validText(name)) throw new Error('名前は40文字以内で入力してください');
      this.disconnect();
      this.connection = {parsed, name: name.trim()};
      this.attempt = 0;
      this.open();
    }
    open() {
      if (!this.connection) return;
      const {parsed, name} = this.connection;
      const socket = new this.WebSocketClass(parsed.server);
      this.socket = socket;
      this.status = '接続中';
      this.notify();
      this.timer = root.setTimeout(() => {
        if (this.socket === socket && !this.ownId) socket.close();
      }, 10000);
      socket.onopen = () => {
        if (this.socket !== socket) return;
        socket.send(JSON.stringify({type: 'join', room: parsed.room, name}));
      };
      socket.onmessage = event => {
        if (this.socket !== socket || typeof event.data !== 'string' || event.data.length > 32768) return;
        let data;
        try { data = JSON.parse(event.data); } catch (_) { return; }
        if (data && data.type === 'welcome' && typeof data.id === 'string' && ID.test(data.id)) {
          root.clearTimeout(this.timer); this.timer = null;
          this.attempt = 0; this.ownId = data.id; this.status = '接続中（共有中）'; this.notify();
        } else if (data && data.type === 'roster' && this.ownId) {
          const members = safeRoster(data.members);
          if (members) { this.members = members; this.notify(); }
        }
      };
      socket.onerror = () => {};
      socket.onclose = event => {
        if (this.socket !== socket) return;
        root.clearTimeout(this.timer); this.timer = null;
        this.socket = null; this.ownId = ''; this.members = []; this.lastSend = 0;
        if (event && event.code === 1008) {
          this.connection = null; this.status = '接続拒否（コードや人数を確認）'; this.notify(); return;
        }
        if (!this.connection) { this.status = '接続終了'; this.notify(); return; }
        const delay = Math.min(30000, 1000 * (2 ** Math.min(this.attempt++, 5)));
        this.status = '再接続待ち'; this.notify();
        this.retryTimer = root.setTimeout(() => { this.retryTimer = null; this.open(); }, delay);
      };
    }
    update(combat, monitoring) {
      if (!this.socket || this.socket.readyState !== 1 || !this.ownId || this.socket.bufferedAmount > 32768) return;
      const now = Date.now();
      if (now - this.lastSend < 1000) return;
      monitoring = monitoring === true;
      const data = {type: 'metrics', monitoring, job: monitoring && typeof combat.job === 'string' && validText(combat.job) ? combat.job : ''};
      for (const name of ['dps', 'boss_damage', 'total_damage']) {
        const value = monitoring ? combat[name] : 0;
        if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > MAX_VALUE) return;
        data[name] = value;
      }
      this.lastSend = now;
      try { this.socket.send(JSON.stringify(data)); } catch (_) { this.disconnect(); }
    }
    disconnect() {
      root.clearTimeout(this.timer); this.timer = null;
      root.clearTimeout(this.retryTimer); this.retryTimer = null;
      this.connection = null; this.attempt = 0;
      const socket = this.socket;
      this.socket = null; this.ownId = ''; this.members = []; this.lastSend = 0; this.status = '未接続';
      if (socket) socket.close();
      this.notify();
    }
  }
  const api = {endpoint, createInvite, parseInvite, validText, safeRoster, Client};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.EMCParty = api;
})(globalThis);
