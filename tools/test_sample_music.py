import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import EclipticaMusic as music


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class MusicConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp.name) / 'settings.json'
        self.config_patch = patch.object(music, 'CFG', self.config_path)
        self.config_patch.start()
        self.app = music.App.__new__(music.App)
        self.app.fade, self.app.volume, self.app.status = Value(2), Value(80), Value('')
        self.old_state = dict(music.state)
        self.old_allowed = set(music.allowed_media)

    def tearDown(self):
        music.state.clear(); music.state.update(self.old_state)
        music.allowed_media.clear(); music.allowed_media.update(self.old_allowed)
        self.config_patch.stop(); self.temp.cleanup()

    def test_new_config_has_no_trial_tracks(self):
        cfg = self.app.load_config()
        self.assertEqual(cfg['music'], {})
        self.assertEqual(cfg['lobby'], '')

    def test_existing_choices_including_legacy_are_preserved(self):
        old = {'music': {'Primal|戦闘': 'my-track.mp3', 'Primal|準備': 'demo://calm'},
               'lobby': 'https://youtu.be/yJg-Y5byMMw', 'boss': {'Yuki': 'my-boss.mp3'},
               'fallback': {'boss|Yuki': 'my-fallback.mp3'}, 'volume': 32}
        self.config_path.write_text(json.dumps(old), encoding='utf-8')
        cfg = self.app.load_config()
        for field in old:
            self.assertEqual(cfg[field], old[field])

    def test_youtube_url_validation(self):
        for url in ('https://www.youtube.com/watch?v=yJg-Y5byMMw',
                    'https://youtu.be/yJg-Y5byMMw', 'https://www.youtube.com/shorts/yJg-Y5byMMw'):
            self.assertEqual(music.youtube_id(url), 'yJg-Y5byMMw')
        for url in ('https://youtube.com/watch?v=bad',
                    'https://youtube.com.evil.example/watch?v=yJg-Y5byMMw',
                    'https://someone@youtube.com/watch?v=yJg-Y5byMMw'):
            self.assertEqual(music.youtube_id(url), '')

    def test_fallback_is_only_used_when_explicitly_configured(self):
        custom = Path(self.temp.name) / 'custom.wav'
        custom.write_bytes(b'fixture')
        url = 'https://www.youtube.com/watch?v=yJg-Y5byMMw'
        self.assertTrue(self.app.play(url))
        self.assertEqual(music.state['fallback'], '')
        self.assertTrue(self.app.play(url, str(custom)))
        self.assertEqual(music.state['fallback'], str(custom))
        self.assertIn(str(custom.resolve()), music.allowed_media)
        self.assertTrue(self.app.play(url, 'demo://battle'))
        self.assertEqual(music.state['fallback'], '')
        self.assertFalse(self.app.play('demo://battle'))
        self.assertTrue(music.state['stop'])
        self.assertIn('別の曲を設定', self.app.status.get())
        self.assertFalse(self.app.play('https://youtube.com/watch?v=bad'))
        self.assertIn('有効なYouTube動画のURL', self.app.status.get())


if __name__ == '__main__':
    unittest.main()
