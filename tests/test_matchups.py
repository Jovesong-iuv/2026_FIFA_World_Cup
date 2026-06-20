import unittest

from wc2026.analysis import matchups as M


def _sq(star_val, others_val, star_pos="Attacker"):
    return {"groups": {
        "Attacker": [{"name": "Star", "name_zh": "球星", "position": star_pos,
                      "value": star_val, "rating": 7.8}],
        "Midfielder": [{"name": "M1", "position": "Midfielder", "value": others_val, "rating": 7.0}],
        "Defender": [{"name": "D1", "position": "Defender", "value": others_val, "rating": 7.0}],
    }}


class BreakerTest(unittest.TestCase):
    def test_none_without_squad(self):
        self.assertIsNone(M._breaker(None))

    def test_picks_attacking_top(self):
        b = M._breaker(_sq(1.5e8, 2e7))
        self.assertEqual(b["name"], "球星")
        self.assertEqual(b["position"], "Attacker")


class ClassifyTest(unittest.TestCase):
    def test_superstar_type(self):
        r = M.classify_team("France", _sq(2.0e8, 1e7), 2.0)   # 突出个人 + 强攻
        self.assertEqual(r["type"], "超级巨星型")
        self.assertGreaterEqual(r["dominance"], 2.2)

    def test_low_efficiency_type(self):
        r = M.classify_team("England", _sq(1.2e8, 1.1e8), 1.0)  # 高身价、无碾压点、低攻
        self.assertEqual(r["type"], "低效热门")

    def test_data_limited(self):
        self.assertEqual(M.classify_team("Haiti", None, 0.8)["type"], "数据有限")


class AnalyzeTest(unittest.TestCase):
    def test_structure_and_notes(self):
        r = M.analyze_matchups("France", "Haiti", exp_goals=(2.4, 0.6),
                               sq_home=_sq(2.0e8, 1e7), sq_away=None,
                               score_home=85, score_away=55)
        self.assertEqual(set(r), {"home_type", "away_type", "home_breaker", "away_breaker", "notes"})
        self.assertTrue(any("综合实力占优" in n for n in r["notes"]))
        self.assertTrue(any("破局点" in n for n in r["notes"]))
        self.assertIsNone(r["away_breaker"])            # 客队无阵容数据降级

    def test_close_teams_note(self):
        r = M.analyze_matchups("A", "B", exp_goals=(1.4, 1.3), score_home=70, score_away=68)
        self.assertTrue(any("实力接近" in n for n in r["notes"]))


if __name__ == "__main__":
    unittest.main()
