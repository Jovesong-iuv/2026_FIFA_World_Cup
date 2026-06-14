import unittest

import numpy as np

from wc2026.analysis.tournament import _match_thirds, simulate_tournament

GROUPS = list("ABCDEFGHIJKL")


class MockModel:
    def __init__(self, teams):
        self._t = set(teams)

    def has_team(self, t):
        return t in self._t

    def score_matrix(self, h, a, neutral=True):
        m = np.zeros((4, 4))
        m[0, 0], m[1, 0], m[0, 1], m[1, 1], m[2, 1] = 0.2, 0.3, 0.2, 0.2, 0.1
        return m


def _twelve_groups():
    data, all_teams = {}, []
    for g in GROUPS:
        teams = [f"{g}{i}" for i in range(4)]
        all_teams += teams
        matches = [(i, j, None, None) for i in range(4) for j in range(i + 1, 4)]
        data[f"Group {g}"] = {"teams": teams, "matches": matches}
    return data, all_teams


class TournamentTest(unittest.TestCase):
    def test_round_mass_invariants(self):
        data, all_teams = _twelve_groups()
        res = simulate_tournament(MockModel(all_teams), data, n_sims=300, seed=1)
        self.assertEqual(len(res), 48)
        self.assertAlmostEqual(sum(r["champion"] for r in res.values()), 1.0, places=6)
        self.assertAlmostEqual(sum(r["final"] for r in res.values()), 2.0, places=6)
        self.assertAlmostEqual(sum(r["sf"] for r in res.values()), 4.0, places=6)
        self.assertAlmostEqual(sum(r["qf"] for r in res.values()), 8.0, places=6)
        self.assertAlmostEqual(sum(r["r16"] for r in res.values()), 16.0, places=6)

    def test_monotonic_per_team(self):
        data, all_teams = _twelve_groups()
        res = simulate_tournament(MockModel(all_teams), data, n_sims=300, seed=2)
        for r in res.values():
            self.assertGreaterEqual(r["r16"], r["qf"])
            self.assertGreaterEqual(r["qf"], r["sf"])
            self.assertGreaterEqual(r["sf"], r["final"])
            self.assertGreaterEqual(r["final"], r["champion"])

    def test_match_thirds_assigns_valid(self):
        slot_sets = [{"A", "B", "C", "D", "F"}, {"C", "D", "F", "G", "H"}, {"C", "E", "F", "H", "I"},
                     {"E", "H", "I", "J", "K"}, {"B", "E", "F", "I", "J"}, {"A", "E", "H", "I", "J"},
                     {"E", "F", "G", "I", "J"}, {"D", "E", "I", "J", "L"}]
        adv = ["A", "B", "C", "D", "E", "F", "G", "H"]
        assign = _match_thirds(adv, slot_sets)
        self.assertIsNotNone(assign)
        self.assertEqual(len(set(assign.values())), 8)  # 8 个不同小组
        for i, g in assign.items():
            self.assertIn(g, slot_sets[i])

    def test_match_thirds_infeasible(self):
        self.assertIsNone(_match_thirds(["A"], [{"B"}]))


if __name__ == "__main__":
    unittest.main()
