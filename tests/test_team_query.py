import unittest
from unittest.mock import patch

from wc2026.analysis import team_query


class TeamQueryTest(unittest.TestCase):
    def test_build_team_snapshot_includes_rank_profile_and_fixture_record(self):
        model = _Model()
        fixtures = [
            {"home_team": "Germany", "away_team": "Japan", "home_score": 2, "away_score": 1,
             "group_name": "Group E", "date_utc": "2026-06-12T19:00:00Z"},
            {"home_team": "Spain", "away_team": "Germany", "home_score": 1, "away_score": 1,
             "group_name": "Group E", "date_utc": "2026-06-17T19:00:00Z"},
        ]

        with patch("wc2026.analysis.team_query.ranking.world_rank", return_value=(3, "FIFA")), \
                patch("wc2026.analysis.team_query.evidence.recent_form",
                      return_value={"n": 2, "w": 1, "d": 1, "l": 0, "gf": 3, "ga": 2,
                                    "matches": [{"date": "2026-06-17", "opponent": "Spain",
                                                 "ha": "客", "score": "1-1", "outcome": "平"}]}):
            snap = team_query.build_team_snapshot(model, "Germany", fixtures)

        self.assertEqual(snap["team"], "Germany")
        self.assertEqual(snap["rank"], 3)
        self.assertEqual(snap["rank_source"], "FIFA")
        self.assertEqual(snap["current_record"]["played"], 2)
        self.assertEqual(snap["current_record"]["w"], 1)
        self.assertEqual(snap["recent_form"]["n"], 2)
        self.assertIn("style_detail", snap["profile"])

    def test_rotation_news_is_warning_only_not_strength_adjustment(self):
        items = [
            {"title": "Germany expected to rotate starters and use bench players today"},
            {"title": "美国队可能让部分主力休息，替补上场"},
        ]

        signals = team_query.rotation_signals(items)

        self.assertTrue(signals["detected"])
        self.assertGreaterEqual(len(signals["items"]), 2)
        self.assertIn("不修正球队基础强弱", signals["policy"])
        self.assertNotIn("adjustment", signals)


class _Model:
    teams = ["Germany", "Japan", "Spain"]


if __name__ == "__main__":
    unittest.main()
