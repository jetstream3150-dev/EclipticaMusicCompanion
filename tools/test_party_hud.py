from types import SimpleNamespace
import unittest

from EclipticaMusic import App


class PartyHudTests(unittest.TestCase):
    def test_local_roster_validation_is_atomic(self):
        calls = []
        app = SimpleNamespace(party_rows=[], refresh_party_hud=lambda: calls.append(True))
        rows = [{'name': 'Alice', 'job': 'Spellhammer', 'dps': 42.5, 'boss_damage': 425}]
        App.api_action(app, {'action': 'party_roster', 'rows': rows})
        self.assertEqual(app.party_rows, rows)
        self.assertEqual(calls, [True])
        for invalid in (
            rows * 13,
            [{'name': 'A\nB', 'job': '', 'dps': 0, 'boss_damage': 0}],
            [{'name': 'A', 'job': '', 'dps': float('nan'), 'boss_damage': 0}],
            [{'name': 'A', 'job': '', 'dps': -1, 'boss_damage': 0}],
            [{'name': 'A', 'job': '', 'dps': True, 'boss_damage': 0}],
        ):
            with self.assertRaises(ValueError):
                App.api_action(app, {'action': 'party_roster', 'rows': invalid})
            self.assertEqual(app.party_rows, rows)
        App.api_action(app, {'action': 'party_roster', 'rows': []})
        self.assertEqual(app.party_rows, [])


if __name__ == '__main__':
    unittest.main()
