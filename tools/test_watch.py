import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from combat_meter import CombatMeter
from EclipticaMusic import App


class WatcherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def make_app(self, name='Alice'):
        return SimpleNamespace(meter=CombatMeter(name), watch_events=queue.Queue(),
                               combat_events=queue.Queue(), _watch_generation=7)

    def start_watch(self, app, path, directory):
        signal = threading.Event()
        patcher = patch('EclipticaMusic.LOG', directory)
        patcher.start()
        self.addCleanup(patcher.stop)
        thread = threading.Thread(target=App.watch, args=(app, path, signal, 0, 7), daemon=True)
        thread.start()
        self.addCleanup(lambda: (signal.set(), thread.join(timeout=2)))
        return signal, thread

    def event(self, events, kind, timeout=4):
        while True:
            generation, actual, value = events.get(timeout=timeout)
            self.assertEqual(generation, 7)
            if actual == kind:
                return value

    def test_damage_does_not_fill_ui_queue_and_boss_alert_survives(self):
        path = self.directory / 'output_log_2026-10-27_10-00-00.txt'
        path.write_bytes(b'ECLIPTICA - now in stage: A on phase: 0.1\n' +
                         b'2026 Debug - Dealing 12 STRIKE damage\n' * 4000 +
                         b'ECLIPTICA - now fighting boss: FlyLord on phase: 0.1\n' +
                         b'2026 Debug - ownership of FlyLord transferred to Alice\n')
        app = self.make_app()
        signal, thread = self.start_watch(app, path, self.directory)
        self.assertEqual(self.event(app.watch_events, 'phase')[1], '戦闘')
        self.assertEqual(self.event(app.watch_events, 'boss'), 'FlyLord')
        self.assertEqual(app.combat_events.get(timeout=4), (7, 'boss', 'FlyLord'))
        self.assertEqual(app.combat_events.get(timeout=4), (7, 'target_on', 'Alice'))
        self.assertTrue(app.combat_events.empty())
        self.assertEqual(app.meter.snapshot()['total_damage'], 48000)
        signal.set();thread.join(timeout=2)
        self.assertFalse(thread.is_alive())

    def test_partial_utf8_and_oversized_line_are_safe(self):
        path = self.directory / 'output_log_2026-10-27_10-00-00.txt'
        name = '雷龍'.encode('utf-8')
        path.write_bytes(b'ECLIPTICA - now fighting boss: ' + name[:2])
        app = self.make_app()
        self.start_watch(app, path, self.directory)
        with self.assertRaises(queue.Empty):app.watch_events.get(timeout=.4)
        with path.open('ab') as f:
            f.write(name[2:] + b' on phase: 0.1\n')
        self.assertEqual(self.event(app.watch_events, 'boss'), '雷龍')
        with path.open('ab') as f:
            f.write(b'ECLIPTICA - now in lobby' + b'x' * 1_100_000 + b'\n')
            f.write(b'ECLIPTICA - now in stage: RealStage on phase: 0.1\n')
        self.assertEqual(self.event(app.watch_events, 'phase'), ('戦闘開始: RealStage', '戦闘'))
        self.assertEqual(app.meter.snapshot()['stage'], 'RealStage')

    def test_truncated_log_is_read_from_its_new_beginning(self):
        path = self.directory / 'output_log_2026-10-27_10-00-00.txt'
        path.write_bytes(b'x' * 4000 + b'\nECLIPTICA - now in stage: Old on phase: 0.1\n')
        app = self.make_app()
        self.start_watch(app, path, self.directory)
        self.assertEqual(self.event(app.watch_events, 'phase')[0], '戦闘開始: Old')
        path.write_bytes(b'ECLIPTICA - now fighting boss: FlyLord on phase: 0.1\n')
        self.assertIn('監視を再開', self.event(app.watch_events, 'status'))
        self.assertEqual(self.event(app.watch_events, 'boss'), 'FlyLord')
        self.assertEqual(app.meter.snapshot()['boss'], 'FlyLord')

    def test_rotates_to_new_session_without_replaying_old_lines(self):
        old = self.directory / 'output_log_2026-10-27_10-00-00.txt'
        old.write_bytes(b'ECLIPTICA - now in stage: Old on phase: 0.1\n')
        app = self.make_app()
        self.start_watch(app, old, self.directory)
        self.assertEqual(self.event(app.watch_events, 'phase')[0], '戦闘開始: Old')
        new = self.directory / 'output_log_2026-10-27_10-01-00.txt'
        new.write_bytes(b'ECLIPTICA - now in lobby\n')
        self.assertEqual(self.event(app.watch_events, 'log'), str(new))
        with new.open('ab') as f:
            f.write(b'ECLIPTICA - now in stage: New on phase: 0.1\n')
        self.assertEqual(self.event(app.watch_events, 'phase'), ('戦闘開始: New', '戦闘'))
        self.assertEqual(app.meter.snapshot()['stage'], 'New')

    def test_restart_discards_stale_gui_events(self):
        calls = []
        root = SimpleNamespace(winfo_exists=lambda: True, after=lambda *args: None)
        app = SimpleNamespace(root=root, stop=threading.Event(), _watch_generation=8,
                              watch_events=queue.Queue(),
                              drain_watch_events=lambda: None,
                              handle_boss=lambda name: calls.append(('boss', name)),
                              handle_event=lambda description, phase: calls.append(('phase', phase)))
        app.watch_events.put((7, 'phase', ('old', '休憩')))
        app.watch_events.put((8, 'boss', 'current'))
        App.drain_watch_events(app)
        self.assertEqual(calls, [('boss', 'current')])
        app.stop.set();app.watch_events.put((8, 'phase', ('old', 'ロビー')))
        App.drain_watch_events(app)
        self.assertEqual(calls, [('boss', 'current')])

    def test_restart_and_stop_discard_stale_target_alerts(self):
        root = SimpleNamespace(winfo_exists=lambda: True, after=lambda *args: None)
        app = SimpleNamespace(root=root, stop=threading.Event(), _watch_generation=8,
                              combat_events=queue.Queue(), overlay_cfg={'alert': True},
                              hud=None, meter=SimpleNamespace(snapshot=lambda: {}),
                              refresh_metric_widgets=lambda snapshot: None,
                              update_hud_loop=lambda: None)
        app.combat_events.put((7, 'target_on', 'old'))
        app.combat_events.put((8, 'target_on', 'current'))
        with patch('EclipticaMusic.play_target_tone') as tone:
            App.update_hud_loop(app)
            self.assertEqual(tone.call_count, 1)
            app.stop.set();app.combat_events.put((8, 'target_on', 'stopped'))
            App.update_hud_loop(app)
            self.assertEqual(tone.call_count, 1)


if __name__ == '__main__':
    unittest.main()
