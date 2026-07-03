import unittest
from unittest.mock import patch

import numpy as np

from wc2026.analysis import groups as G
from wc2026.analysis.groups import simulate_groups


class MockModel:
    """确定性桩：字母序靠前的队恒以 2-0 取胜（无平局），便于断言名次。"""

    def __init__(self, teams):
        self._teams = set(teams)

    def has_team(self, t):
        return t in self._teams

    def score_matrix(self, home, away, neutral=True):
        m = np.zeros((4, 4))
        if home < away:
            m[2, 0] = 1.0  # 主队 2-0
        else:
            m[0, 2] = 1.0  # 客队 2-0
        return m


def _round_robin(teams, scored=None):
    """生成 4 队单循环 6 场。scored: {(hi,ai): (hs,as)} 指定真实比分。"""
    scored = scored or {}
    matches = []
    for i in range(4):
        for j in range(i + 1, 4):
            hs, as_ = scored.get((i, j), (None, None))
            matches.append((i, j, hs, as_))
    return {"teams": list(teams), "matches": matches}


class SimulateGroupsTest(unittest.TestCase):
    def test_dominant_team_always_first(self):
        teams = ["AAA", "BBB", "CCC", "DDD"]
        model = MockModel(teams)
        data = {"Group A": _round_robin(teams)}
        res = simulate_groups(model, data, n_sims=1000, seed=1)
        rows = {r["team"]: r for r in res["Group A"]}
        self.assertAlmostEqual(rows["AAA"]["first"], 1.0, places=6)   # 全胜
        self.assertAlmostEqual(rows["AAA"]["top2"], 1.0, places=6)
        self.assertAlmostEqual(rows["BBB"]["top2"], 1.0, places=6)    # 稳居前二
        self.assertAlmostEqual(rows["CCC"]["third"], 1.0, places=6)   # 恒第三

    def test_first_and_top2_mass_per_group(self):
        teams = ["T1", "T2", "T3", "T4"]
        model = MockModel(teams)
        data = {"Group A": _round_robin(teams)}
        res = simulate_groups(model, data, n_sims=500, seed=2)
        self.assertAlmostEqual(sum(r["first"] for r in res["Group A"]), 1.0, places=6)
        self.assertAlmostEqual(sum(r["top2"] for r in res["Group A"]), 2.0, places=6)
        self.assertAlmostEqual(sum(r["third"] for r in res["Group A"]), 1.0, places=6)

    def test_qualify_equals_top2_plus_third_advance(self):
        teams = ["T1", "T2", "T3", "T4"]
        model = MockModel(teams)
        res = simulate_groups(model, {"Group A": _round_robin(teams)}, n_sims=400, seed=3)
        for r in res["Group A"]:
            self.assertAlmostEqual(r["qualify"], r["top2"] + r["third_advance"], places=9)

    def test_exactly_eight_thirds_advance_with_twelve_groups(self):
        # 12 个结构相同的小组：每 sim 恰好 8 个小组第三递补、24 个前二 → 共 32 出线
        model_teams = []
        data = {}
        for k in range(12):
            teams = [f"G{k}T{i}" for i in range(4)]
            model_teams += teams
            data[f"Group {chr(ord('A') + k)}"] = _round_robin(teams)
        model = MockModel(model_teams)
        res = simulate_groups(model, data, n_sims=600, seed=4)
        total_third_adv = sum(r["third_advance"] for rows in res.values() for r in rows)
        total_qualify = sum(r["qualify"] for rows in res.values() for r in rows)
        self.assertAlmostEqual(total_third_adv, 8.0, places=6)
        self.assertAlmostEqual(total_qualify, 32.0, places=6)

    def test_real_score_override(self):
        # 钦定 T4 打爆 T1（弱队真实赢球），其首名概率应明显上升
        teams = ["T1", "T2", "T3", "T4"]
        model = MockModel(teams)
        baseline = {r["team"]: r for r in
                    simulate_groups(model, {"G": _round_robin(teams)}, n_sims=800, seed=5)["G"]}
        # (0,3) 即 T1 vs T4，真实比分 0-5
        scored = _round_robin(teams, scored={(0, 3): (0, 5)})
        bumped = {r["team"]: r for r in
                  simulate_groups(model, {"G": scored}, n_sims=800, seed=5)["G"]}
        self.assertGreater(bumped["T4"]["qualify"], baseline["T4"]["qualify"])

    def test_load_group_data_applies_results_overlay(self):
        rows = [
            {"match_number": 1, "group_name": "Group A", "home_team": "AAA", "away_team": "BBB",
             "home_score": None, "away_score": None},
            {"match_number": 2, "group_name": "Group A", "home_team": "AAA", "away_team": "CCC",
             "home_score": None, "away_score": None},
            {"match_number": 3, "group_name": "Group A", "home_team": "AAA", "away_team": "DDD",
             "home_score": None, "away_score": None},
            {"match_number": 4, "group_name": "Group A", "home_team": "BBB", "away_team": "CCC",
             "home_score": None, "away_score": None},
            {"match_number": 5, "group_name": "Group A", "home_team": "BBB", "away_team": "DDD",
             "home_score": None, "away_score": None},
            {"match_number": 6, "group_name": "Group A", "home_team": "CCC", "away_team": "DDD",
             "home_score": None, "away_score": None},
        ]

        class Conn:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def execute(self, *_args, **_kwargs):
                return self

            def fetchall(self):
                return rows

        def overlay(fixtures):
            out = [dict(f) for f in fixtures]
            out[0]["home_score"], out[0]["away_score"] = 2, 0
            return out

        with patch("wc2026.analysis.groups.get_conn", return_value=Conn()), \
                patch("wc2026.analysis.groups.apply_results_overlay", side_effect=overlay):
            data = G.load_group_data(MockModel(["AAA", "BBB", "CCC", "DDD"]))

        self.assertEqual(data["Group A"]["matches"][0], (0, 1, 2, 0))


if __name__ == "__main__":
    unittest.main()
