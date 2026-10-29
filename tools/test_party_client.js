'use strict';
const assert = require('node:assert/strict');
const party = require('../party.js');

assert.throws(() => party.endpoint('ws://example.com'), /wss/);
assert.throws(() => party.endpoint('wss://user:password@example.com'), /URL/);
assert.throws(() => party.endpoint('wss://example.com/?secret=abc'), /URL/);
assert.equal(party.endpoint('ws://127.0.0.1:8765'), 'ws://127.0.0.1:8765/');
const invite = party.createInvite('wss://relay.example.com');
const parsed = party.parseInvite(invite);
assert.equal(parsed.room.length, 43);
assert.notEqual(party.parseInvite(party.createInvite('wss://relay.example.com')).room, parsed.room);
assert.throws(() => party.parseInvite(JSON.stringify({version: 1, server: 'wss://relay.example.com', room: 'short'})), /招待/);
assert.equal(party.safeRoster([{id: 'x', name: 'bad', job: '', dps: 1, boss_damage: 1, total_damage: 1, monitoring: true}]), null);
assert.equal(party.safeRoster([{id: 'a'.repeat(24), name: 'bad', job: '', dps: Infinity, boss_damage: 1, total_damage: 1, monitoring: true}]), null);

class FakeSocket {
  constructor(url) { this.url = url; this.readyState = 1; this.bufferedAmount = 0; this.sent = []; FakeSocket.last = this; }
  send(value) { this.sent.push(JSON.parse(value)); }
  close() { this.readyState = 3; }
}
let view;
const client = new party.Client(value => { view = value; }, FakeSocket);
client.connect(invite, 'Alice');
const socket = FakeSocket.last;
assert.equal(socket.url, 'wss://relay.example.com/');
assert(!socket.url.includes(parsed.room));
socket.onopen();
assert.deepEqual(socket.sent[0], {type: 'join', room: parsed.room, name: 'Alice'});
socket.onmessage({data: JSON.stringify({type: 'welcome', id: 'a'.repeat(24)})});
assert.equal(view.status, '接続中（共有中）');
socket.onmessage({data: JSON.stringify({type: 'roster', members: [{id: 'a'.repeat(24), name: 'Alice', job: 'Nekomancer', dps: 12, boss_damage: 50, total_damage: 100, monitoring: true}]})});
assert.equal(view.members.length, 1);
client.update({dps: 12, boss_damage: 50, total_damage: 100, job: 'Nekomancer', own_name: 'must not be sent', raw_log: 'must not be sent'}, true);
assert.deepEqual(socket.sent[1], {type: 'metrics', monitoring: true, job: 'Nekomancer', dps: 12, boss_damage: 50, total_damage: 100});
client.lastSend -= 2000;
client.update({dps: 12, boss_damage: 50, total_damage: 100, job: 'Nekomancer'}, true);
assert.equal(socket.sent.length, 2, 'unchanged values should not be repeatedly broadcast');
client.lastSend -= 60000;
client.update({dps: 12, boss_damage: 50, total_damage: 100, job: 'Nekomancer'}, true);
assert.equal(socket.sent.length, 3, 'heartbeat should still be sent');
client.lastSend = 0;
client.update({dps: 12, boss_damage: 50, total_damage: 100, job: 'Nekomancer'}, false);
assert.deepEqual(socket.sent[3], {type: 'metrics', monitoring: false, job: '', dps: 0, boss_damage: 0, total_damage: 0});
socket.onclose({code: 1006});
assert.equal(view.status, '再接続待ち');
client.disconnect();
assert.equal(view.status, '未接続');
assert.equal(view.members.length, 0);
socket.onmessage({data: JSON.stringify({type: 'welcome', id: 'b'.repeat(24)})});
assert.equal(view.status, '未接続');
client.connect(invite, 'Alice');
FakeSocket.last.onclose({code: 1008});
assert.match(view.status, /接続拒否/);
assert.equal(client.retryTimer, null);
client.disconnect();
console.log('Party browser client checks PASS');
