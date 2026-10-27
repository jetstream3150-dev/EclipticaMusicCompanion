'use strict';
const assert = require('node:assert/strict');
const {Client, createInvite} = require('../party.js');

function until(test, timeout = 4000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();
    const check = () => {
      if (test()) return resolve();
      if (Date.now() - start > timeout) return reject(new Error('timed out waiting for party event'));
      setTimeout(check, 20);
    };
    check();
  });
}

async function main() {
  const invite = createInvite(process.argv[2]);
  const a = new Client(() => {}), b = new Client(() => {});
  try {
    a.connect(invite, 'Alice'); b.connect(invite, 'Bob');
    await until(() => a.ownId && b.ownId && a.members.length === 2 && b.members.length === 2);
    a.update({dps: 42.5, boss_damage: 425, total_damage: 500, job: 'Spellhammer'}, true);
    await until(() => b.members.some(m => m.name === 'Alice' && m.dps === 42.5));
    assert.equal(b.members.find(m => m.name === 'Alice').job, 'Spellhammer');
    console.log('Party client-to-relay integration PASS');
  } finally { a.disconnect(); b.disconnect(); }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
