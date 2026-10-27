import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from combat_meter import CombatMeter
from EclipticaMusic import App


class CombatLogTests(unittest.TestCase):
    def test_real_damage_format_is_limited_to_the_current_world(self):
        meter = CombatMeter(seconds=10)
        self.assertEqual(meter.ingest('2026.09.22 20:00:04 Debug - Dealing 100 STRIKE damage', now=1), [])
        meter.ingest('2026.09.22 20:00:00 Debug - [Behaviour] Entering Room: Ecliptica - Demo Playtest', now=2)
        meter.ingest('2026.09.22 20:00:01 Debug - ECLIPTICA - now in stage: Stage_ProtoColony on phase: 0.1', now=3)
        meter.ingest('2026.09.22 20:00:04 Debug - Dealing 100 STRIKE damage', now=4)
        meter.ingest('2026.09.22 20:00:05 Debug - Dealing 50 NON-STRIKE damage', now=5)
        meter.ingest('2026.09.22 20:00:05 Debug - Unrelated STRIKE damage: 999', now=6)
        result = meter.snapshot(now=6)
        self.assertEqual((result['total_damage'], result['dps'], result['attack_speed']), (150, 15, 0.1))
        meter.ingest('2026.09.22 20:00:40 Debug - [Behaviour] OnLeftRoom', now=7)
        meter.ingest('2026.09.22 20:00:41 Debug - Dealing 100 STRIKE damage', now=8)
        self.assertEqual(meter.snapshot(now=8)['total_damage'], 0)

    def test_tokens_and_boss_ownership_are_conservative(self):
        meter = CombatMeter('MyPlayer')
        meter.ingest('ECLIPTICA - now in stage: Stage_ProtoColony on phase: 0.1', now=1)
        meter.ingest('2026.09.22 Debug - spawn token, False, 0', now=2)
        meter.ingest('2026.09.22 Debug - spawn token, True, 55', now=3)
        for t in (4, 5, 6):
            meter.ingest('2026.09.22 Debug - ECLIPTICA saving SESSION ID 11508', now=t)
        result = meter.snapshot(now=6)
        self.assertEqual((result['tokens_collected'], result['tokens_spawned']), (2, 2))
        meter.ingest('ECLIPTICA - now fighting boss: FlyLord(Clone) on phase: 0.06', now=7)
        self.assertEqual(meter.ingest('2026.09.22 Debug - ownership of OtherEnemy transferred to MyPlayer', now=8), [])
        self.assertEqual(meter.ingest('2026.09.22 Debug - unrelated target: MyPlayer', now=8), [])
        self.assertEqual(meter.ingest('2026.09.22 Debug - ownership of FlyLord transferred to MyPlayer', now=9), [('target_on', 'MyPlayer')])
        self.assertTrue(meter.snapshot(now=9)['is_targeted'])
        meter.ingest('ECLIPTICA - now in intermission', now=10)
        meter.ingest('ECLIPTICA - now in stage: Stage_Next on phase: 0.2', now=11)
        self.assertEqual(meter.snapshot(now=11)['tokens_collected'], 0)

    def test_break_dummy_does_not_inflate_boss_damage(self):
        meter = CombatMeter()
        meter.ingest('ECLIPTICA - now fighting boss: FlyLord on phase: 0.1', now=1)
        meter.ingest('2026.09.22 Debug - Dealing 200 STRIKE damage', now=2)
        meter.ingest('ECLIPTICA - now in intermission', now=3)
        meter.ingest('2026.09.22 Debug - Dealing 30 STRIKE damage', now=4)
        meter.ingest('2026.09.22 Debug - Dealing 50 NON-STRIKE damage', now=5)
        current = meter.snapshot(now=8)
        self.assertEqual((current['dummy_damage'], current['dummy_dps'], current['boss_damage']), (80, 20, 0))
        self.assertTrue(current['dummy_active'])
        meter.ingest('ECLIPTICA - now in stage: Stage_Next on phase: 0.2', now=8)
        final = meter.snapshot(now=20)
        self.assertFalse(final['dummy_active'])
        self.assertEqual((final['dummy_damage'], final['dummy_dps']), (80, 20))

    def test_startup_replay_does_not_replay_damage_or_partial_lines(self):
        class Status:
            def set(self, value):
                self.value = value
        meter = CombatMeter()
        app = SimpleNamespace(meter=meter, discovered_bosses=set(), status=Status(),
                              handle_boss=lambda name: None,
                              handle_event=lambda description, phase: None)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'log.txt'
            path.write_bytes(b'ECLIPTICA - now in stage: Stage_A on phase: 0.1\n'
                             b'2026 Debug - Dealing 100 STRIKE damage\n'
                             b'2026 Debug - Dealing 2')
            offset = App.resume_from_log(app, path)
            self.assertEqual(meter.snapshot()['total_damage'], 0)
            with path.open('ab') as stream:
                stream.write(b'0 STRIKE damage\n')
            with path.open('r', encoding='utf-8') as stream:
                stream.seek(offset)
                meter.ingest(stream.readline())
            self.assertEqual(meter.snapshot()['total_damage'], 20)

    def test_resume_does_not_restore_a_scene_after_leaving_the_world(self):
        class Status:
            def set(self, value):
                self.value = value
        played = []
        app = SimpleNamespace(meter=CombatMeter(), discovered_bosses=set(), status=Status(),
                              handle_boss=lambda name: played.append(name),
                              handle_event=lambda description, phase: played.append(phase))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'log.txt'
            path.write_text('ECLIPTICA - now fighting boss: FlyLord on phase: 0.1\n'
                            '2026 Debug - [Behaviour] OnLeftRoom\n', encoding='utf-8')
            App.resume_from_log(app, path)
        self.assertEqual(played, [])
        self.assertEqual(app.meter.snapshot()['boss'], '待機中')


if __name__ == '__main__':
    unittest.main()
