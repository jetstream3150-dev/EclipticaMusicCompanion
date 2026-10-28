import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import EclipticaMusic as music


class SampleMusicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp.name) / 'settings.json'
        self.config_patch = patch.object(music, 'CFG', self.config_path)
        self.config_patch.start()
        self.app = music.App.__new__(music.App)

    def tearDown(self):
        self.config_patch.stop()
        self.temp.cleanup()

    def load_saved(self, obj):
        self.config_path.write_text(json.dumps(obj), encoding='utf-8')
        return self.app.load_config()

    def test_new_config_has_tracks_for_all_difficulties_and_phases(self):
        cfg = self.app.load_config()
        self.assertEqual(len(cfg['music']), len(self.app.DIFFICULTIES) * len(self.app.PHASES))
        for difficulty in self.app.DIFFICULTIES:
            for phase in self.app.PHASES:
                self.assertEqual(cfg['music'][difficulty + '|' + phase], music.SAMPLE_PHASE_TRACKS[phase])
        self.assertEqual(cfg['lobby'], music.SAMPLE_PHASE_TRACKS['休憩'])
        self.assertTrue(cfg['sample_music_initialized'])

    def test_existing_tracks_and_boss_overrides_are_preserved(self):
        old = {'music': {'Primal|戦闘': 'my-track.mp3', 'Primal|準備': ''},
               'lobby': 'my-lobby.mp3', 'boss': {'Yuki': 'my-boss.mp3'},
               'fallback': {'boss|Yuki': 'my-fallback.mp3'}, 'volume': 32}
        cfg = self.load_saved(old)
        self.assertEqual(cfg['music']['Primal|戦闘'], 'my-track.mp3')
        self.assertEqual(cfg['music']['Primal|準備'], '')
        self.assertEqual(cfg['music']['Primal|ボス'], music.SAMPLE_PHASE_TRACKS['ボス'])
        for field in ('lobby', 'boss', 'fallback', 'volume'):
            self.assertEqual(cfg[field], old[field])

    def test_cleared_tracks_stay_cleared_after_initialization(self):
        cfg = self.load_saved({'music': {}, 'lobby': '', 'sample_music_initialized': True})
        self.assertEqual(cfg['music'], {})
        self.assertEqual(cfg['lobby'], '')


if __name__ == '__main__':
    unittest.main()
