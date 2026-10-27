import io
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch
import wave

import EclipticaMusic as music
from alert_sound import play_custom_sound


class AlertSoundTests(unittest.TestCase):
    def test_wav_playback_scales_volume_and_missing_file_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sound.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
                wav.writeframes((10000).to_bytes(2, 'little', signed=True) * 10)
            played = []
            self.assertTrue(play_custom_sound(str(path), 50, wav_player=played.append))
            with wave.open(io.BytesIO(played[0]), 'rb') as wav:
                self.assertEqual(int.from_bytes(wav.readframes(1), 'little', signed=True), 5000)
            path.unlink()
            self.assertFalse(play_custom_sound(str(path), 50, wav_player=played.append))
            self.assertEqual(len(played), 1)

    def test_mp3_uses_volume_and_closes_the_device(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sound.mp3'
            path.write_bytes(b'test')
            commands = []
            def send(command):
                commands.append(command)
                return (0, '1000') if command.startswith('status ') else (0, '')
            self.assertTrue(play_custom_sound(str(path), 42, mci_send=send))
            self.assertTrue(any('volume to 420' in command for command in commands))
            self.assertTrue(commands[-1].startswith('close '))
            commands.clear()
            def failing_send(command):
                commands.append(command)
                return (1, '') if command.startswith('play ') else (0, '1000') if command.startswith('status ') else (0, '')
            self.assertFalse(play_custom_sound(str(path), 42, mci_send=failing_send))
            self.assertTrue(commands[-1].startswith('close '))

    def test_unusable_custom_sound_uses_built_in_alert(self):
        called = threading.Event()
        fake_winsound = types.SimpleNamespace(SND_MEMORY=1, PlaySound=lambda *args: called.set())
        with patch.object(music.sys, 'platform', 'win32'), \
             patch.object(music, 'play_custom_sound', return_value=False), \
             patch.dict(sys.modules, {'winsound': fake_winsound}):
            music.play_target_tone('target_on', 50, 'missing.mp3')
            self.assertTrue(called.wait(3), 'fallback alert did not play')


if __name__ == '__main__':
    unittest.main()
