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

    def test_youtube_url_validation(self):
        for url in (music.SAMPLE_PHASE_TRACKS['戦闘'], 'https://youtu.be/yJg-Y5byMMw',
                    'https://www.youtube.com/shorts/yJg-Y5byMMw'):
            self.assertEqual(music.youtube_id(url), 'yJg-Y5byMMw')
        for url in ('https://youtube.com/watch?v=bad',
                    'https://youtube.com.evil.example/watch?v=yJg-Y5byMMw',
                    'https://someone@youtube.com/watch?v=yJg-Y5byMMw'):
            self.assertEqual(music.youtube_id(url), '')

    def test_preset_uses_bundled_fallback_without_changing_user_choice(self):
        class Value:
            def __init__(self, value): self.value = value
            def get(self): return self.value
            def set(self, value): self.value = value

        bundled = Path(self.temp.name) / 'demo_audio'
        bundled.mkdir()
        (bundled / 'battle.wav').write_bytes(b'demo')
        custom = Path(self.temp.name) / 'custom.wav'
        custom.write_bytes(b'custom')
        self.app.fade = Value(2)
        self.app.volume = Value(80)
        self.app.status = Value('')
        old_state = dict(music.state)
        self.addCleanup(lambda: music.state.update(old_state))
        self.addCleanup(music.allowed_media.clear)
        with patch.object(music, 'BASE', Path(self.temp.name)):
            track = music.SAMPLE_PHASE_TRACKS['戦闘']
            self.app.play(track)
            self.assertEqual(music.state['track'], track)
            self.assertEqual(music.state['fallback'], str(bundled / 'battle.wav'))
            self.assertIn(str((bundled / 'battle.wav').resolve()), music.allowed_media)
            self.app.play(track, str(custom))
            self.assertEqual(music.state['fallback'], str(custom))
            self.app.play('https://www.youtube.com/watch?v=AAAAAAAAAAA')
            self.assertEqual(music.state['fallback'], '')
            self.app.play('https://youtube.com/watch?v=bad')
            self.assertTrue(music.state['stop'])
            self.assertIn('有効なYouTube動画のURL', self.app.status.get())


if __name__ == '__main__':
    unittest.main()
