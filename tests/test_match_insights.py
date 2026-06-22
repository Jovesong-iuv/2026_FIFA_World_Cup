import unittest

from wc2026.analysis.match_insights import build_match_analysis


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


if __name__ == "__main__":
    unittest.main()
