import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import EclipticaMusic as music
from battle_results import BattleResults
from combat_meter import CombatMeter


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class FeatureTests(unittest.TestCase):
    def test_boss_segment_result_uses_only_observed_damage(self):
        meter = CombatMeter()
        meter.ingest('ECLIPTICA - now fighting boss: Yuki on phase: 1', now=10)
        meter.ingest('2026 Debug - Dealing 100 STRIKE damage', now=12)
        meter.ingest('2026 Debug - Dealing 50 NON-STRIKE damage', now=16)
        transition = meter.ingest('ECLIPTICA - now in intermission', now=20)
        self.assertEqual(len(transition), 1)
        kind, result = transition[0]
        self.assertEqual(kind, 'result')
        self.assertEqual((result['boss'], result['seconds'], result['damage'], result['average_dps'], result['events']),
                         ('Yuki', 10, 150, 15, 2))
        self.assertFalse(result['partial'])
        self.assertNotIn('win', result)
        self.assertEqual(meter.ingest('ECLIPTICA - now in intermission', now=21), [])

    def test_replay_and_interruption_are_labeled_partial(self):
        meter = CombatMeter()
        meter.ingest('ECLIPTICA - now fighting boss: Yuki on phase: 1', now=10, replay=True)
        meter.ingest('2026 Debug - Dealing 999 STRIKE damage', now=11, replay=True)
        meter.ingest('2026 Debug - Dealing 50 STRIKE damage', now=12)
        kind, result = meter.interrupt('監視停止', now=20)
        self.assertEqual(kind, 'result')
        self.assertTrue(result['partial'])
        self.assertEqual(result['damage'], 50)
        self.assertIsNone(meter.interrupt(now=21))

    def test_history_is_bounded_and_stays_on_local_disk(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'battle_results.json'
            store = BattleResults(path, limit=2)
            for name in ('A', 'B', 'C'):store.append({'boss': name})
            self.assertEqual([r['boss'] for r in BattleResults(path, 2).latest()], ['C', 'B'])
            with patch('battle_results.os.replace', side_effect=PermissionError('denied')):
                with self.assertRaises(PermissionError):store.append({'boss': 'D'})
            self.assertEqual([r['boss'] for r in BattleResults(path, 2).latest()], ['C', 'B'])

    def test_internal_preset_survives_install_directory_change(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(music, 'BASE', Path(temp)):
                self.assertEqual(music.resolve_demo_track('demo://battle'), str(Path(temp)/'demo_audio'/'battle.wav'))
                self.assertEqual(music.resolve_demo_track('demo://other'), 'demo://other')

    def test_bulk_settings_rollback_if_save_fails(self):
        values={(group,d+'|戦闘'):Value('old-'+d+'-'+group)
                for d in ('A','B') for group in ('music','fallback')}
        app=SimpleNamespace(DIFFICULTIES=['A','B'],PHASES=['戦闘'],vars=values,
                            save=lambda quiet=True:False,status=Value('write failed'),revision=0)
        before={k:v.get() for k,v in values.items()}
        with self.assertRaises(RuntimeError):
            music.App.api_action(app,{'action':'set_music_all','phase':'戦闘','track':'demo://battle','fallback':''})
        self.assertEqual({k:v.get() for k,v in values.items()},before)
        app.save=lambda quiet=True:True
        music.App.api_action(app,{'action':'set_music_all','phase':'戦闘','track':'demo://battle','fallback':''})
        self.assertEqual([values[('music',d+'|戦闘')].get() for d in ('A','B')], ['demo://battle']*2)


if __name__ == '__main__':
    unittest.main()
