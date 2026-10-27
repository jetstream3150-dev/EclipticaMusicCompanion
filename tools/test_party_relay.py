import asyncio
import json
import logging
import os
import secrets
import shutil
import ssl
import subprocess
import tempfile
import unittest
from contextlib import AsyncExitStack

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import InvalidStatus

from relay.party_relay import ALLOWED_ORIGIN, PartyRelay, clean_metrics, run

ORIGIN = 'http://127.0.0.1:12345'


async def receive_type(ws, kind, predicate=lambda value: True):
    for _ in range(10):
        payload = json.loads(await asyncio.wait_for(ws.recv(), timeout=2))
        if payload.get('type') == kind and predicate(payload):
            return payload
    raise AssertionError('expected event not received')


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.relay = PartyRelay()
        logger = logging.getLogger('party-test')
        logger.setLevel(logging.CRITICAL)
        self.server = await serve(self.relay.handle, '127.0.0.1', 0,
                                  origins=[ALLOWED_ORIGIN], compression=None,
                                  max_size=4096, close_timeout=1, logger=logger)
        self.url = 'ws://127.0.0.1:' + str(self.server.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def test_party_sharing_and_room_isolation(self):
        room, other = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        async with connect(self.url, origin=ORIGIN) as alice, \
                   connect(self.url, origin=ORIGIN) as bob, \
                   connect(self.url, origin=ORIGIN) as carol:
            for ws, code, name in ((alice, room, 'Alice'), (bob, room, 'Bob'), (carol, other, 'Carol')):
                await ws.send(json.dumps({'type': 'join', 'room': code, 'name': name}))
                await receive_type(ws, 'welcome')
            await receive_type(alice, 'roster', lambda x: len(x['members']) == 2)
            isolated = await receive_type(carol, 'roster')
            self.assertEqual([m['name'] for m in isolated['members']], ['Carol'])
            await alice.send(json.dumps({'type': 'metrics', 'dps': 12.5, 'boss_damage': 125,
                                         'total_damage': 300, 'job': 'Spellhammer', 'monitoring': True}))
            result = await receive_type(bob, 'roster', lambda x: any(m['dps'] == 12.5 for m in x['members']))
            member = next(m for m in result['members'] if m['name'] == 'Alice')
            self.assertEqual((member['boss_damage'], member['job']), (125, 'Spellhammer'))
            self.assertNotIn('Carol', [m['name'] for m in result['members']])
        await asyncio.sleep(0.05)
        self.assertEqual(self.relay.rooms, {})
        self.assertEqual(self.relay.connections, set())

    async def test_rejects_untrusted_browser_origins(self):
        with self.assertRaises(InvalidStatus):
            async with connect(self.url, origin='https://untrusted.example'):
                pass
        with self.assertRaises(InvalidStatus):
            async with connect(self.url):
                pass

    async def test_room_capacity_and_cleanup(self):
        room = secrets.token_urlsafe(32)
        async with AsyncExitStack() as stack:
            for index in range(12):
                ws = await stack.enter_async_context(connect(self.url, origin=ORIGIN, max_queue=128, close_timeout=1))
                await ws.send(json.dumps({'type': 'join', 'room': room, 'name': str(index)}))
                await receive_type(ws, 'welcome')
            extra = await stack.enter_async_context(connect(self.url, origin=ORIGIN, max_queue=128, close_timeout=1))
            await extra.send(json.dumps({'type': 'join', 'room': room, 'name': 'extra'}))
            await asyncio.wait_for(extra.wait_closed(), timeout=2)
            self.assertEqual(extra.close_code, 1008)
            self.assertEqual(len(self.relay.rooms[room]), 12)
        await asyncio.sleep(0.05)
        self.assertEqual(self.relay.rooms, {})

    async def test_invalid_message_and_flood_are_rejected(self):
        for messages in ([{'type': 'metrics', 'dps': -1}],
                         [{'type': 'metrics', 'dps': 1, 'boss_damage': 1,
                           'total_damage': 1, 'job': '', 'monitoring': True}] * 6):
            async with connect(self.url, origin=ORIGIN) as ws:
                await ws.send(json.dumps({'type': 'join', 'room': secrets.token_urlsafe(32), 'name': 'x'}))
                await receive_type(ws, 'welcome')
                for message in messages:
                    await ws.send(json.dumps(message))
                await asyncio.wait_for(ws.wait_closed(), timeout=3)
                self.assertEqual(ws.close_code, 1008)

    @unittest.skipUnless(shutil.which('node'), 'Node is not installed')
    async def test_real_javascript_clients_exchange_metrics(self):
        # Node's browser-compatible WebSocket doesn't send Origin; allow it only
        # on this test listener. The production listener requires the app origin.
        async with serve(self.relay.handle, '127.0.0.1', 0,
                         origins=[ALLOWED_ORIGIN, None], compression=None,
                         max_size=4096, close_timeout=1) as server:
            url = 'ws://127.0.0.1:' + str(server.sockets[0].getsockname()[1])
            process = await asyncio.create_subprocess_exec(
                'node', 'tools/test_party_end_to_end.js', url,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            out, err = await asyncio.wait_for(process.communicate(), timeout=12)
            self.assertEqual(process.returncode, 0, (out + err).decode('utf-8', 'replace'))
            self.assertIn(b'integration PASS', out)

    @unittest.skipUnless(shutil.which('node') and shutil.which('openssl'), 'Node or OpenSSL is not installed')
    async def test_javascript_clients_over_verified_tls(self):
        with tempfile.TemporaryDirectory() as directory:
            cert = os.path.join(directory, 'local-test-cert.pem')
            key = os.path.join(directory, 'local-test-key.pem')
            await asyncio.to_thread(subprocess.run, [
                'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                '-keyout', key, '-out', cert, '-days', '1', '-subj', '/CN=localhost',
                '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(cert, key)
            async with serve(self.relay.handle, '127.0.0.1', 0, ssl=tls,
                             origins=[ALLOWED_ORIGIN, None], compression=None,
                             max_size=4096, close_timeout=1) as server:
                url = 'wss://127.0.0.1:' + str(server.sockets[0].getsockname()[1])
                env = dict(os.environ, NODE_EXTRA_CA_CERTS=cert)
                process = await asyncio.create_subprocess_exec(
                    'node', 'tools/test_party_end_to_end.js', url, env=env,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                out, err = await asyncio.wait_for(process.communicate(), timeout=12)
                self.assertEqual(process.returncode, 0, (out + err).decode('utf-8', 'replace'))
                self.assertIn(b'integration PASS', out)

    async def test_non_loopback_listener_requires_tls(self):
        with self.assertRaises(ValueError):
            await run('0.0.0.0', 0, None, None)

    def test_rejects_nonfinite_and_negative_values(self):
        for bad in (float('nan'), float('inf'), -1, True, '99'):
            with self.assertRaises(ValueError):
                clean_metrics({'dps': bad, 'boss_damage': 1, 'total_damage': 1, 'job': '', 'monitoring': True})


if __name__ == '__main__':
    unittest.main()
