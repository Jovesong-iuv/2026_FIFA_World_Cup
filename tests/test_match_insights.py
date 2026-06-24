import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wc2026.analysis.match_insights import build_match_analysis, refresh_match_insight


class MatchInsightsTest(unittest.TestCase):
    def test_builds_field_analysis_from_prior_match_data_and_markets(self):
        report = {
            "prediction": {
                "win_margins": {"home_by_3_plus": 0.33, "home_by_4_plus": 0.16},
                "top_scores": [{"score": "2-0", "probability": 0.168},
                               {"score": "1-0", "probability": 0.143},
                               {"score": "3-0", "probability": 0.132}],
            }
        }

        res = build_match_analysis(
            "Spain", "Saudi Arabia", report,
            insights={
                "matches": {
                    "Spain::Saudi Arabia": {
                        "prior_matches": [
                            {"team": "Spain", "opponent": "Cape Verde", "score": "0-0",
                             "possession": 0.74, "shots_for": 27, "xg_for": 2.7,
                             "takeaway": "主要问题是把握机会。"},
                            {"team": "Saudi Arabia", "opponent": "Uruguay",
                             "shots_against": 27, "takeaway": "门将多次救险。"},
                        ],
                        "availability_notes": ["亚马尔比赛时间仍可能受到控制。"],
                        "tactical_notes": ["西班牙继续围攻，沙特五后卫低位防守。"],
                        "market_view": {
                            "primary": "上半场小1.5",
                            "avoid": "西班牙-2.5/3",
                            "scoreline_primary": "2-0",
                            "scoreline_secondary": "3-0",
                        },
                    }
                }
            },
        )

        self.assertTrue(res["available"])
        self.assertIn("74%控球", res["text"])
        self.assertIn("27次射门", res["text"])
        self.assertIn("2.7预期进球", res["text"])
        self.assertIn("上半场小1.5", res["recommendations"]["primary"])
        self.assertAlmostEqual(res["markets"]["home_by_3_plus"], 0.33)

    def test_missing_insight_degrades_cleanly(self):
        res = build_match_analysis("A", "B", {"prediction": {}}, insights={"matches": {}})

        self.assertFalse(res["available"])
        self.assertIn("暂无", res["text"])

    def test_refresh_match_insight_merges_online_sources(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "match_insights.json"
            with patch("wc2026.analysis.match_insights.fbref.fetch_team_shooting",
                       side_effect=[{"shots": 18, "xg": 1.9}, {"shots": 8, "xg": 0.7}]), \
                    patch("wc2026.analysis.match_insights.squads.refresh_fm_squad",
                          side_effect=[{"formation": "4-3-3", "injured": 1},
                                       {"formation": "5-4-1", "injured": 0}]), \
                    patch("wc2026.analysis.match_insights.news.fetch_for_teams",
                          return_value=[{"title": "Spain star returns", "source": "News", "link": "#"}]):
                res = refresh_match_insight("Spain", "Saudi Arabia", path=path)

            self.assertTrue(res["ok"])
            self.assertTrue(path.exists())
            built = build_match_analysis(
                "Spain", "Saudi Arabia", {"prediction": {}},
                insights=__import__("json").loads(path.read_text(encoding="utf-8")),
            )
            self.assertTrue(built["available"])
            self.assertIn("FBref聚合", built["text"])
            self.assertIn("4-3-3", built["text"])

    def test_refresh_match_insight_keeps_partial_data_when_source_fails(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "match_insights.json"
            with patch("wc2026.analysis.match_insights.fbref.fetch_team_shooting",
                       side_effect=RuntimeError("fbref down")), \
                    patch("wc2026.analysis.match_insights.squads.refresh_fm_squad",
                          side_effect=RuntimeError("fotmob down")), \
                    patch("wc2026.analysis.match_insights.news.fetch_for_teams", return_value=[]):
                res = refresh_match_insight("Spain", "Saudi Arabia", path=path)

            self.assertFalse(res["ok"])
            self.assertIn("FBref", " ".join(res["errors"]))
            self.assertTrue(path.exists())
            built = build_match_analysis(
                "Spain", "Saudi Arabia", {"prediction": {}},
                insights=__import__("json").loads(path.read_text(encoding="utf-8")),
            )
            self.assertTrue(built["available"])
            self.assertIn("本地球队画像", built["text"])
            self.assertIn("数据源提示", built["text"])

    def test_refresh_match_insight_uses_fotmob_stats_when_fbref_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "match_insights.json"
            with patch("wc2026.analysis.match_insights.fbref.fetch_team_shooting",
                       side_effect=RuntimeError("HTTP 403")), \
                    patch("wc2026.analysis.match_insights.fotmob.fetch_team_stats",
                          side_effect=[
                              {"possession": 0.651, "xg": 5.3, "xga": 0.8,
                               "goals_per_match": 2.5, "shots_on_target_per_match": 7},
                              {"possession": 0.70, "xg": 5.8, "xga": 1.2,
                               "goals_per_match": 3.5, "shots_on_target_per_match": 7},
                          ]), \
                    patch("wc2026.analysis.match_insights.squads.refresh_fm_squad",
                          return_value={"formation": "4-4-2", "injured": 0}), \
                    patch("wc2026.analysis.match_insights.news.fetch_for_teams", return_value=[]):
                res = refresh_match_insight("Switzerland", "Canada", path=path)

            self.assertFalse(res["ok"])
            built = build_match_analysis(
                "Switzerland", "Canada", {"prediction": {}},
                insights=__import__("json").loads(path.read_text(encoding="utf-8")),
            )
            self.assertTrue(built["available"])
            self.assertIn("FotMob本届聚合", built["text"])
            self.assertIn("65%控球", built["text"])
            self.assertIn("约5.8预期进球", built["text"])
            self.assertNotIn("瑞士首轮，65%控球", built["text"])


if __name__ == "__main__":
    unittest.main()
