import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import EclipticaMusic as music


class Value:
    def __init__(self, value): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class APIQueueTests(unittest.TestCase):
    def setUp(self):
        self.q = queue.Queue(maxsize=16)
        self.patch = patch.object(music, 'API_QUEUE', self.q)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.handler = music.Handler.__new__(music.Handler)

    def dispatch_in_thread(self, function, timeout=.15):
        result = {}
        def run():
            try: result['value'] = self.handler._dispatch(function, timeout)
            except Exception as exc: result['error'] = exc
        thread = threading.Thread(target=run)
        thread.start()
        return thread, result

    def test_timed_out_queued_action_does_not_run_later(self):
        calls = []
        thread, result = self.dispatch_in_thread(lambda: calls.append('saved'), timeout=.05)
        request = self.q.get(timeout=1)
        thread.join(timeout=1)
        self.assertIsInstance(result.get('error'), TimeoutError)
        self.assertIn('実行されていません', str(result['error']))
        request.execute()
        self.assertEqual(calls, [])

    def test_running_timeout_does_not_claim_action_was_cancelled(self):
        started, finish = threading.Event(), threading.Event()
        def action():
            started.set(); finish.wait(1); return 'done'
        thread, result = self.dispatch_in_thread(action, timeout=.05)
        request = self.q.get(timeout=1)
        worker = threading.Thread(target=request.execute)
        worker.start(); self.assertTrue(started.wait(1))
        thread.join(timeout=1)
        self.assertIsInstance(result.get('error'), TimeoutError)
        self.assertIn('処理が続いています', str(result['error']))
        finish.set(); worker.join(timeout=1)
        self.assertEqual(request.value, 'done')

    def test_completed_request_returns_value(self):
        thread, result = self.dispatch_in_thread(lambda: 'saved')
        self.q.get(timeout=1).execute()
        thread.join(timeout=1)
        self.assertEqual(result.get('value'), 'saved')

    def test_unified_save_failure_is_reported_without_a_hidden_modal(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = music.App.__new__(music.App)
            app._saving = False; app._save_after = None; app.unified = True
            app.vars = {}; app.boss_map = {}; app.boss_fallback_map = {}
            app.cfg = {}; app.lobby = Value(''); app.log = Value('')
            app.fade = Value(2); app.volume = Value(80); app.overlay_cfg = {}; app.difficulty = Value('')
            app.discovered_bosses = set(); app.status = Value(''); app.revision = 0
            with patch.object(music, 'CFG', Path(tmp) / 'settings.json'), \
                 patch.object(Path, 'write_text', side_effect=PermissionError('test denied')), \
                 patch.object(music.messagebox, 'showerror') as dialog:
                with self.assertRaisesRegex(RuntimeError, '設定を保存できませんでした'):
                    app.api_action({'action':'set_boss', 'boss':'Yuki',
                                    'track':'https://www.youtube.com/watch?v=PnvVPv_EODw', 'fallback':''})
                dialog.assert_not_called()
                self.assertFalse(app._saving)
                self.assertIn('test denied', app.status.get())
                self.assertNotIn('Yuki', app.boss_map)


if __name__ == '__main__':
    unittest.main()
