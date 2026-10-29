import queue
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from combat_meter import CombatMeter
from difficulty_detection import infer_difficulty
from EclipticaMusic import App, read_resume_snapshot


def stage(value, name='Stage_ProtoColony'):
    return f'ECLIPTICA - now in stage: {name} on phase: {value} as class: Nekomancer'


class AutoDifficultyTests(unittest.TestCase):
    def test_band_boundaries_and_final_eye_marker(self):
        for value, expected in [('0','Primal'),('0.199999','Primal'),('0.2','Penumbra'),
                                ('0.399999','Penumbra'),('0.4','Antumbra'),('0.599999','Antumbra'),
                                ('0.6','Umbra'),('0.799999','Umbra'),('0.8','Eclipse'),
                                ('0.999999','Eclipse'),('1','Eclipse')]:
            with self.subTest(value=value):
                self.assertEqual(infer_difficulty(stage(value))['difficulty'],expected)
        final=infer_difficulty(stage('1','Stage_Bringer'))
        self.assertEqual(final['difficulty'],'Eye of the Eclipse')
        self.assertEqual(infer_difficulty('ECLIPTICA - now fighting boss: JimBringerPhase2(Clone) on phase: 0',final)['difficulty'], 'Eye of the Eclipse')
        self.assertIsNone(infer_difficulty('ECLIPTICA - now fighting boss: JimBringerPhase2(Clone) on phase: 0'))
        self.assertEqual(infer_difficulty('ECLIPTICA - now fighting boss: JimBringer(Clone) on phase: 1')['difficulty'],'Eye of the Eclipse')

    def test_bad_or_unrelated_records_never_guess(self):
        for value in ('nan','-0.1','1.1','0.2oops','1e999',''):
            with self.subTest(value=value):self.assertIsNone(infer_difficulty(stage(value)))
        self.assertIsNone(infer_difficulty('unrelated: phase: 0.4'))

    def test_resume_keeps_latest_stage_in_break_but_clears_on_leave(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'output_log.txt'
            path.write_text(stage('0.41')+'\nECLIPTICA - now in intermission\n',encoding='utf-8')
            _,event,detected=read_resume_snapshot(path,CombatMeter())
            self.assertEqual(event,('休憩',None))
            self.assertEqual(detected['difficulty'],'Antumbra')
            with path.open('a',encoding='utf-8') as f:f.write('[Behaviour] OnLeftRoom\n')
            _,event,detected=read_resume_snapshot(path,CombatMeter())
            self.assertIsNone(event);self.assertIsNone(detected)

    def test_resume_clears_stale_difficulty_for_invalid_new_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'output_log.txt'
            path.write_text(stage('0.1')+'\n'+stage('invalid')+'\n',encoding='utf-8')
            _,event,detected=read_resume_snapshot(path,CombatMeter())
            self.assertEqual(event[0],'戦闘');self.assertIsNone(detected)
            with path.open('a',encoding='utf-8') as f:f.write('ECLIPTICA - now in stage: unknown format\n')
            _,event,detected=read_resume_snapshot(path,CombatMeter())
            self.assertIsNone(event);self.assertIsNone(detected)

    def test_watcher_emits_difficulty_before_playback_event_and_clears_on_leave(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);path=directory/'output_log_2026-10-29_00-00-00.txt'
            path.write_text(stage('0.21')+'\n',encoding='utf-8')
            app=SimpleNamespace(meter=CombatMeter(),watch_events=queue.Queue(),combat_events=queue.Queue(),_watch_generation=7)
            signal=threading.Event()
            with patch('EclipticaMusic.LOG',directory):
                thread=threading.Thread(target=App.watch,args=(app,path,signal,0,7),daemon=True);thread.start()
                try:
                    a=app.watch_events.get(timeout=4);b=app.watch_events.get(timeout=4)
                    self.assertEqual((a[1],a[2]['difficulty'],b[1]),('difficulty','Penumbra','phase'))
                    with path.open('a',encoding='utf-8') as f:f.write(stage('0.81')+'\n[Behaviour] OnLeftRoom\n')
                    found=[];deadline=time.monotonic()+4
                    while time.monotonic()<deadline and len(found)<4:
                        try:found.append(app.watch_events.get(timeout=.25))
                        except queue.Empty:pass
                    self.assertEqual([(x[1],x[2]['difficulty'] if x[1]=='difficulty' and x[2] else x[2]) for x in found],
                                     [('difficulty','Eclipse'),('phase',('戦闘開始: Stage_ProtoColony','戦闘')),
                                      ('difficulty',None),('phase',('VRChatワールドを移動',None))])
                finally:signal.set();thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
