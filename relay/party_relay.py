"""Experimental, opt-in in-memory relay for independently implemented party HUDs.

This process never reads VRChat logs. TLS must terminate at a trusted proxy or
in this server before traffic crosses a network. Rooms are bearer capabilities;
anyone with a room code can join and view its participants' chosen names/stats.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
import ipaddress
import json
import logging
import math
import re
import secrets
import ssl
import time
import unicodedata

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

ROOM = re.compile(r'[A-Za-z0-9_-]{43}\Z')
MAX_CLIENTS = 128
MAX_ROOMS = 64
MAX_PARTY = 12
MAX_MESSAGE = 4096
MAX_EVENTS_PER_SECOND = 5
MAX_VALUE = 1_000_000_000_000
ALLOWED_ORIGIN = re.compile(r'http://(?:127\.0\.0\.1|localhost):\d{1,5}\Z')


def clean_text(value, maximum=40):
    if not isinstance(value, str) or len(value) > maximum:
        raise ValueError('invalid text')
    if any(unicodedata.category(c).startswith('C') for c in value):
        raise ValueError('invalid characters')
    return value.strip()


def clean_metrics(data):
    if not isinstance(data.get('monitoring'), bool):
        raise ValueError('invalid monitoring state')
    result = {}
    for name in ('dps', 'boss_damage', 'total_damage'):
        value = data.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError('invalid metric')
        if not math.isfinite(value) or not 0 <= value <= MAX_VALUE:
            raise ValueError('invalid metric')
        result[name] = round(value, 1)
    result['job'] = clean_text(data.get('job', ''), 40)
    result['monitoring'] = data['monitoring']
    return result


class PartyRelay:
    def __init__(self):
        self.connections = set()
        self.rooms = {}

    async def broadcast(self, code):
        room = self.rooms.get(code)
        if not room:
            return
        peers = list(room.items())
        payload = json.dumps({'type': 'roster', 'members': [record for _, record in peers]},
                             ensure_ascii=False, separators=(',', ':'))
        async def send_one(peer):
            try:
                await asyncio.wait_for(peer.send(payload), timeout=2)
            except (ConnectionClosed, TimeoutError):
                pass
        await asyncio.gather(*(send_one(peer) for peer, _ in peers))

    async def handle(self, ws):
        code = None
        if len(self.connections) >= MAX_CLIENTS:
            await ws.close(1013, 'server busy')
            return
        self.connections.add(ws)
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=5)
            if not isinstance(first, str):
                raise ValueError('expected text')
            join = json.loads(first)
            if not isinstance(join, dict) or join.get('type') != 'join':
                raise ValueError('expected join')
            room_code = join.get('room')
            if not isinstance(room_code, str) or not ROOM.fullmatch(room_code):
                raise ValueError('invalid room')
            name = clean_text(join.get('name', ''), 40) or 'プレイヤー'
            if room_code not in self.rooms and len(self.rooms) >= MAX_ROOMS:
                await ws.close(1013, 'server busy')
                return
            room = self.rooms.setdefault(room_code, {})
            if len(room) >= MAX_PARTY:
                await ws.close(1008, 'room full')
                return
            code = room_code
            member = {'id': secrets.token_hex(12), 'name': name, 'job': '',
                      'dps': 0, 'boss_damage': 0, 'total_damage': 0, 'monitoring': False}
            room[ws] = member
            await ws.send(json.dumps({'type': 'welcome', 'id': member['id']}))
            await self.broadcast(code)
            times = deque()
            async for message in ws:
                now = time.monotonic()
                while times and times[0] <= now - 1:
                    times.popleft()
                if len(times) >= MAX_EVENTS_PER_SECOND or not isinstance(message, str):
                    raise ValueError('rate or message limit')
                times.append(now)
                data = json.loads(message)
                if not isinstance(data, dict) or data.get('type') != 'metrics':
                    raise ValueError('unsupported message')
                member.update(clean_metrics(data))
                await self.broadcast(code)
        except (ConnectionClosed, TimeoutError):
            pass
        except (ValueError, TypeError, json.JSONDecodeError):
            await ws.close(1008, 'invalid message')
        finally:
            self.connections.discard(ws)
            if code is not None:
                room = self.rooms.get(code)
                if room is not None:
                    room.pop(ws, None)
                    if room:
                        await self.broadcast(code)
                    else:
                        self.rooms.pop(code, None)


def is_loopback(host):
    if host.casefold() == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def run(host, port, cert, key, behind_tls_proxy=False):
    if bool(cert) != bool(key):
        raise ValueError('Both --cert and --key are required together')
    if not is_loopback(host) and not cert and not behind_tls_proxy:
        raise ValueError('TLS is required for non-loopback listeners')
    tls = None
    if cert:
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.minimum_version = ssl.TLSVersion.TLSv1_2
        tls.load_cert_chain(cert, key)
    logger = logging.getLogger('ecliptica-party-relay')
    logger.setLevel(logging.CRITICAL)
    relay = PartyRelay()
    async with serve(relay.handle, host, port, ssl=tls, compression=None,
                     max_size=MAX_MESSAGE, max_queue=4, open_timeout=5,
                     close_timeout=2, ping_interval=20, ping_timeout=20,
                     origins=[ALLOWED_ORIGIN], server_header=None, logger=logger):
        print('Party relay started; room codes and participant details are not logged.', flush=True)
        await asyncio.Future()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Experimental Ecliptica party relay')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--cert')
    parser.add_argument('--key')
    parser.add_argument('--behind-tls-proxy', action='store_true',
                        help='Allow a plain internal listener only when a trusted proxy enforces TLS')
    args = parser.parse_args()
    asyncio.run(run(args.host, args.port, args.cert, args.key, args.behind_tls_proxy))
