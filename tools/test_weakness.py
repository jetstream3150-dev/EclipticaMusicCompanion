import tempfile
import unittest
from pathlib import Path

from boss_weakness import lookup, parse_table
from combat_meter import CombatMeter

ROOT = Path(__file__).resolve().parents[1]
DATA = str(ROOT / 'boss_weakness_data.txt')


class WeaknessTests(unittest.TestCase):
    def test_real_boss_and_weakness(self):
        result = lookup('FlyLord(Clone)', DATA)
        self.assertTrue(result['available'])
        self.assertEqual(result['name'], 'Beelzebub')
        shadow = next(item for item in result['elements'] if item['name'] == '闇')
        self.assertEqual((shadow['value'], shadow['kind']), ('1.5x', 'weak'))

    def test_phase_and_notes(self):
        result = lookup('JimBringerPhase2(Clone)', DATA)
        self.assertEqual(result['name'], 'Jim C. Bringer(P2)')
        self.assertIn('すべてのダメージを無効化します。', result['notes'])
        self.assertEqual(lookup('YukiPhase2(Clone)', DATA)['name'], 'Yuki(P2)')
        self.assertFalse(lookup('YukiPhase3(Clone)', DATA)['available'])

    def test_live_log_boss_can_be_looked_up(self):
        meter = CombatMeter()
        meter.ingest('ECLIPTICA - now fighting boss: YukiPhase2(Clone) on phase: 0', now=1)
        self.assertEqual(lookup(meter.snapshot(now=2)['boss'], DATA)['name'], 'Yuki(P2)')

    def test_generic_boss_and_unknown(self):
        self.assertEqual(lookup('GilgameshPhase2(Clone)', DATA)['name'], 'Gilgamesh')
        self.assertFalse(lookup('a-nonexistent-boss', DATA)['available'])
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(lookup('Gilgamesh', str(Path(directory) / 'missing'))['available'])

    def test_symbolic_values_are_not_invented(self):
        row = parse_table('Dummy\nFire: 1+x (weak)\nFrost: 1-x (resist)\n')
        result = row[('dummy', None)]['elements']
        self.assertEqual([(e['value'], e['kind']) for e in result],
                         [('1+x (weak)', 'weak'), ('1-x (resist)', 'resist')])


if __name__ == '__main__':
    unittest.main()
