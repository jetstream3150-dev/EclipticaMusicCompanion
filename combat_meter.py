"""Independent, log-only experimental combat HUD for ECLIPTICA.

No code or binary from EclipticaOverlay is used or redistributed.
Log event formats vary by world/version; only recognized explicit events are counted.
"""
from __future__ import annotations
from collections import deque
import re
import threading
import time

BOSS_RX = re.compile(r'ECLIPTICA\s*-\s*now fighting boss:\s*(.+?)\s+on phase:\s*([^\s\],;)]+)', re.I)
STAGE_RX = re.compile(r'ECLIPTICA\s*-\s*now in stage:\s*(.+?)\s+on phase:', re.I)
# Deliberately conservative: a damage amount requires an explicit ECLIPTICA event
# and a damage verb, rather than guessing from arbitrary VRChat log numbers.
DAMAGE_RXS = [
    re.compile(r'\b(?:damage\s+dealt|dealt\s+damage|damage\s+amount|strike\s+damage)\s*[:=]\s*([\d,]+(?:\.\d+)?)', re.I),
    re.compile(r'\bdealt\s+([\d,]+(?:\.\d+)?)\s+(?:points?\s+of\s+)?(?:STRIKE\s+)?damage\b', re.I),
    re.compile(r'\b(?:STRIKE|NON-STRIKE)\s+(?:damage\s*)?[:=]\s*([\d,]+(?:\.\d+)?)', re.I),
]
TARGET_RXS = [
    re.compile(r'\b(?:boss\s+)?(?:target|aggro|hate)\s*(?:changed\s+to|is|name)?\s*[:=>-]+\s*(.+?)(?:\s+on phase:|\s*\||$)', re.I),
    re.compile(r'\b(?:boss\s+)?(?:target|aggro|hate)\s+(?:changed\s+to|is|now)\s+(.+?)(?:\s+on phase:|\s*\||$)', re.I),
    re.compile(r'\b(?:ownership|owner)\s+(?:transferred|changed|moved)?\s*(?:to|->|:)\s*(.+?)(?:\s*\||$)', re.I),
]


def _clean_name(value):
    value=re.sub(r'\(Clone\)$','',str(value).strip(),flags=re.I).strip()
    value=re.sub(r'\s*\[(?:Info|Debug|Warning)\].*$', '',value,flags=re.I)
    return value[:90]


class CombatMeter:
    def __init__(self, own_name='', seconds=10):
        self.lock=threading.RLock()
        self.own_name=own_name.strip()
        self.seconds=max(1,min(15,int(seconds)))
        self.reset()

    def reset(self):
        with self.lock:
            self.boss=''
            self.phase=''
            self.stage=''
            self.target=''
            self.total=0.0
            self.boss_total=0.0
            self.phase_total=0.0
            self.peak=0.0
            self.last_strike=0.0
            self.hits=deque()
            self.damage_events=deque()
            self.strike_events=deque()
            self.events_found=0
            self.last_damage_at=0
            self.last_target_at=0

    def configure(self,name=None,seconds=None):
        with self.lock:
            if name is not None:self.own_name=str(name).strip()[:90]
            if seconds is not None:self.seconds=max(1,min(15,int(seconds)))

    def ingest(self,line, now=None):
        """Process one line, returning observable transitions. Thread-safe."""
        if 'ECLIPTICA' not in line.upper():return []
        t=time.monotonic() if now is None else float(now)
        transitions=[]
        with self.lock:
            if 'now in lobby' in line.lower() or 'now in intermission' in line.lower():
                self.target=''
                if 'now in lobby' in line.lower():
                    self.boss='';self.boss_total=0;self.phase_total=0;self.phase=''
                return []
            boss=BOSS_RX.search(line)
            if boss:
                name=_clean_name(boss.group(1));phase=_clean_name(boss.group(2))
                if name and name.casefold()!=self.boss.casefold():
                    self.boss=name;self.phase=phase;self.boss_total=0;self.phase_total=0;self.target=''
                    transitions.append(('boss',name))
                elif self.phase!=phase:
                    self.phase=phase;self.phase_total=0
                    transitions.append(('phase',phase))
            stage=STAGE_RX.search(line)
            if stage:self.stage=_clean_name(stage.group(1))
            for rx in DAMAGE_RXS:
                m=rx.search(line)
                if m:
                    try:amount=float(m.group(1).replace(',',''))
                    except ValueError:break
                    if not (0 < amount < 10_000_000):break
                    direct=('NON-STRIKE' not in line.upper() and 'NON STRIKE' not in line.upper())
                    self.total+=amount
                    if self.boss:
                        self.boss_total+=amount;self.phase_total+=amount
                    self.peak=max(self.peak,amount)
                    self.damage_events.append((t,amount))
                    if direct:
                        self.last_strike=amount
                        self.strike_events.append(t)
                    self.last_damage_at=t
                    self.events_found+=1
                    transitions.append(('damage',amount))
                    break
            # This is an estimate, not a guarantee of targeting. No alert if the
            # player name is unknown, or for empty/ambiguous usernames.
            for rx in TARGET_RXS:
                m=rx.search(line)
                if m:
                    target=_clean_name(m.group(1)).strip('"\'')
                    if not target or target.lower() in ('none','null','unknown','n/a'):
                        target=''
                    if re.search(r'[=:<>\[\]]',target) or len(target)>70:
                        break
                    if target.casefold()!=self.target.casefold():
                        before=self.target
                        self.target=target
                        self.last_target_at=t
                        own=self.own_name.casefold()
                        if own and target.casefold()==own and before.casefold()!=own:
                            transitions.append(('target_on',target))
                        elif own and before.casefold()==own:
                            transitions.append(('target_off',target))
                        elif target:transitions.append(('target_switch',target))
                    break
            self._trim(t)
        return transitions

    def _trim(self,now):
        cutoff=now-self.seconds
        while self.damage_events and self.damage_events[0][0]<cutoff:self.damage_events.popleft()
        while self.strike_events and self.strike_events[0]<cutoff:self.strike_events.popleft()

    def snapshot(self,now=None):
        t=time.monotonic() if now is None else float(now)
        with self.lock:
            self._trim(t)
            return {'boss':self.boss or '待機中','stage':self.stage or '—',
                'phase':self.phase or '—','target':self.target or '未検出',
                'is_targeted':bool(self.own_name and self.target and self.own_name.casefold()==self.target.casefold()),
                'own_name':self.own_name,'dps':round(sum(a for _,a in self.damage_events)/self.seconds,1),
                'attack_speed':round(len(self.strike_events)/self.seconds,1),
                'boss_damage':round(self.boss_total,1),'phase_damage':round(self.phase_total,1),
                'total_damage':round(self.total,1),'max_damage':round(self.peak,1),
                'last_strike':round(self.last_strike,1),'hits':len(self.damage_events),
                'events_found':self.events_found,'dps_window':self.seconds}
