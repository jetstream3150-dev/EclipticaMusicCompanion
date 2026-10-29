import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import EclipticaMusic as music
from combat_meter import CombatMeter
from difficulty_detection import infer_difficulty


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class DifficultyTests(unittest.TestCase):
    def setUp(self):
        app = self.app = music.App.__new__(music.App)
        app.difficulty = Value('Eclipse')
        app.phase_choice = Value('休憩')
        app.status = Value('')
        app.event_status = Value('')
        app.revision = 0
        app.stop = threading.Event()
        app.worker = None
        app.meter = CombatMeter()
        app.discovered_bosses = set()
        app.boss_map = {'Yuki': 'special-boss'}
        app.boss_fallback_map = {}
        app.vars = {(group, difficulty + '|' + phase): Value('')
                    for difficulty in app.DIFFICULTIES for phase in app.PHASES
                    for group in ('music', 'fallback')}
        app.vars['music', 'Primal|戦闘'].set('primal-stage')
        app.vars['music', 'Eclipse|戦闘'].set('eclipse-stage')
        app.vars['music', 'Primal|ボス'].set('primal-boss')
        app.vars['music', 'Eclipse|ボス'].set('eclipse-boss')
        app.save = lambda quiet=True: True
        self.played = []
        app.play = lambda track, fallback='': self.played.append((track, fallback))
        app.stop_music = lambda: self.played.append(('STOP', ''))

    def test_preview_does_not_change_active_difficulty_or_scene(self):
        self.app.api_action({'action': 'play_selected', 'difficulty': 'Primal', 'phase': '戦闘'})
        self.assertEqual(self.played[-1][0], 'primal-stage')
        self.assertEqual(self.app.difficulty.get(), 'Eclipse')
        self.assertEqual(self.app.phase_choice.get(), '休憩')
        self.app.handle_event('stage', '戦闘')
        self.assertEqual(self.played[-1][0], 'eclipse-stage')

    def test_auto_mode_selects_detected_track_and_never_uses_old_manual_value(self):
        self.app.difficulty.set('自動判定')
        self.app.detected_event=infer_difficulty('ECLIPTICA - now in stage: Test on phase: 0.81')
        self.app.handle_event('stage', '戦闘')
        self.assertEqual(self.played[-1][0], 'eclipse-stage')
        self.app.detected_event=None
        self.app.handle_event('stage', '戦闘')
        self.assertEqual(self.played[-1][0], 'STOP')
        self.assertIn('判定できません',self.app.status.get())

    def test_auto_mode_preserves_boss_specific_override(self):
        self.app.difficulty.set('自動判定');self.app.detected_event=None
        self.app.handle_boss('Yuki')
        self.assertEqual(self.played[-1][0], 'special-boss')

    def test_unknown_difficulty_never_selects_a_track(self):
        self.app.difficulty.set('')
        self.assertFalse(self.app.start())
        self.app.play_auto('戦闘')
        self.assertEqual(self.played, [('STOP', '')])
        self.assertIn('難易度', self.app.status.get())

    def test_live_change_replays_current_stage_and_preserves_boss_override(self):
        self.app.worker = SimpleNamespace(is_alive=lambda: True)
        self.app.meter.ingest('ECLIPTICA - now in stage: Stage_ProtoColony on phase: 0.1 as class: Nekomancer')
        self.app.api_action({'action': 'set_active_difficulty', 'difficulty': 'Primal'})
        self.assertEqual(self.played[-1][0], 'primal-stage')
        self.app.meter.ingest('ECLIPTICA - now fighting boss: Yuki(Clone) on phase: 0.1')
        self.app.api_action({'action': 'set_active_difficulty', 'difficulty': 'Eclipse'})
        self.assertEqual(self.played[-1][0], 'special-boss')
        self.app.handle_boss('UnregisteredBoss')
        self.assertEqual(self.played[-1][0], 'eclipse-boss')

    def test_failed_save_restores_selection(self):
        self.app.save = lambda quiet=True: False
        self.app.status.set('保存できません')
        with self.assertRaises(RuntimeError):
            self.app.api_action({'action': 'set_active_difficulty', 'difficulty': 'Primal'})
        self.assertEqual(self.app.difficulty.get(), 'Eclipse')

    def test_missing_track_message_is_not_hidden_on_live_change(self):
        self.app.worker = SimpleNamespace(is_alive=lambda: True)
        self.app.meter.ingest('ECLIPTICA - now in stage: Stage_ProtoColony on phase: 0.1')
        result = self.app.api_action({'action': 'set_active_difficulty', 'difficulty': 'Umbra'})
        self.assertIn('未設定', result)
        self.assertEqual(self.played[-1][0], 'STOP')

    def test_selection_is_saved_and_old_config_has_no_guessed_difficulty(self):
        app = self.app
        app.save = music.App.save.__get__(app)
        app._saving = False; app._save_after = None; app.unified = True
        app.cfg = {}; app.lobby = Value(''); app.log = Value('')
        app.fade = Value(2); app.volume = Value(80); app.overlay_cfg = {}
        with tempfile.TemporaryDirectory() as tmp, patch.object(music, 'CFG', Path(tmp) / 'settings.json'):
            self.assertTrue(app.save(quiet=True))
            self.assertEqual(json.loads(music.CFG.read_text(encoding='utf-8'))['active_difficulty'], 'Eclipse')
            self.assertEqual(app.load_config()['active_difficulty'], 'Eclipse')
            music.CFG.write_text('{}', encoding='utf-8')
            self.assertNotIn('active_difficulty', app.load_config())


if __name__ == '__main__':
    unittest.main()
