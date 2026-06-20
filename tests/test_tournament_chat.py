import unittest
from unittest.mock import patch

from wc2026.llm import tournament_chat as TC

FIXTURES = [
    {"match_number": 1, "home_team": "Brazil", "away_team": "Haiti",
     "group_name": "Group C", "home_score": 2, "away_score": 0},
    {"match_number": 2, "home_team": "Brazil", "away_team": "Scotland",
     "group_name": "Group C", "home_score": None, "away_score": None},
]
STANDINGS = {"Group C": [
    {"team": "Brazil", "rank": 1, "played": 1, "w": 1, "d": 0, "l": 0, "gf": 2, "ga": 0, "gd": 2, "pts": 3},
    {"team": "Haiti", "rank": 2, "played": 1, "w": 0, "d": 0, "l": 1, "gf": 0, "ga": 2, "gd": -2, "pts": 0},
]}
CHAMP = [{"team": "Brazil", "champion": 0.12, "final": 0.25, "r16": 0.70}]
AUDIT = {"n_finished": 1, "comparison": {"enabled": False}, "matches": [],
         "model_metrics": {"accuracy": 1.0, "log_loss": 0.5, "baseline_log_loss": 1.0986, "brier": 0.2}}


class FocusBlockTest(unittest.TestCase):
    def test_focus_team(self):
        s = TC._focus_team_block("Brazil", FIXTURES, STANDINGS, CHAMP)
        self.assertIn("巴西", s)
        self.assertIn("夺冠 12%", s)
        self.assertIn("第 1 名", s)
        self.assertIn("海地", s)            # 近期对手出现

    def test_focus_team_missing(self):
        self.assertIn("数据未提供", TC._focus_team_block("Narnia", [], {}, []))

    def test_focus_group_short_and_full_name(self):
        self.assertIn("巴西", TC._focus_group_block("C", STANDINGS))
        self.assertIn("巴西", TC._focus_group_block("Group C", STANDINGS))
        self.assertIn("净胜", TC._focus_group_block("C", STANDINGS))

    def test_focus_group_missing(self):
        self.assertIn("数据未提供", TC._focus_group_block("Z", STANDINGS))

    def test_pct(self):
        self.assertEqual(TC._pct(0.5), "50%")
        self.assertEqual(TC._pct(None), "—")


def _patches():
    return (
        patch("wc2026.llm.tournament_chat.dashboard_bridge._championship_payload", return_value=CHAMP),
        patch("wc2026.llm.tournament_chat.groups.load_group_data", return_value={"x": 1}),
        patch("wc2026.llm.tournament_chat.groups.compute_standings", return_value=STANDINGS),
        patch("wc2026.llm.tournament_chat.audit.audit_summary", return_value=AUDIT),
    )


class BuildContextTest(unittest.TestCase):
    def test_overview_assembles(self):
        ps = _patches()
        for p in ps:
            p.start()
        try:
            ctx = TC.build_global_context(object(), fixtures=FIXTURES, n_sims=10)
        finally:
            for p in ps:
                p.stop()
        self.assertIn("已完赛 1 场", ctx)
        self.assertIn("夺冠概率 Top", ctx)
        self.assertIn("各小组当前形势", ctx)
        self.assertIn("模型校准", ctx)
        self.assertNotIn("聚焦", ctx)        # 无 focus 时不深挖

    def test_focus_appended(self):
        ps = _patches()
        for p in ps:
            p.start()
        try:
            ctx = TC.build_global_context(object(), fixtures=FIXTURES, n_sims=10,
                                          focus_team="Brazil", focus_group="C")
        finally:
            for p in ps:
                p.stop()
        self.assertIn("聚焦球队 巴西", ctx)
        self.assertIn("聚焦小组 C", ctx)


if __name__ == "__main__":
    unittest.main()
