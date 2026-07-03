import sqlite3
import unittest
from unittest.mock import patch

import numpy as np

from wc2026.analysis import recommendations as R


def _mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    R.ensure_schema(c)
    return c


class RecommendationStorageTest(unittest.TestCase):
    def test_save_and_list_recommendation_with_flexible_scores(self):
        conn = _mem()

        rid = R.save_recommendation(
            match_number=61,
            home_team="Australia",
            away_team="Egypt",
            source="iuv",
            scores="0-0 1-0 1-1 2:1",
            goal_picks="0-1球, 1-2球, 小2.5",
            half_full_picks="平平 平胜",
            confidence="高",
            note="自己判断",
            conn=conn,
        )
        rows = R.list_recommendations(match_number=61, conn=conn)

        self.assertEqual(rows[0]["id"], rid)
        self.assertEqual(rows[0]["source"], "iuv")
        self.assertEqual(rows[0]["scores"], ["0-0", "1-0", "1-1", "2-1"])
        self.assertEqual(rows[0]["goal_picks"], ["0-1球", "1-2球", "小2.5"])
        self.assertEqual(rows[0]["half_full_picks"], ["平平", "平胜"])


class RecommendationConsensusTest(unittest.TestCase):
    def test_consensus_combines_external_votes_with_model_probabilities(self):
        conn = _mem()
        R.save_recommendation(1, "Australia", "Egypt", "iuv", "0-0 1-0 1-1", "0-1球", conn=conn)
        R.save_recommendation(1, "Australia", "Egypt", "小红书", "1-1 0-1 1-2", "1-2球", conn=conn)
        recs = R.list_recommendations(match_number=1, conn=conn)
        mat = np.zeros((4, 4))
        mat[1, 1] = 0.20
        mat[1, 0] = 0.12
        mat[0, 0] = 0.10
        mat[0, 1] = 0.08
        mat[1, 2] = 0.06
        mat[2, 1] = 0.05
        mat[2, 2] = 0.04
        mat[0, 2] = 0.03
        mat[3, 0] = 0.02
        mat[0, 3] = 0.01
        mat = mat / mat.sum()

        res = R.consensus_report(
            "Australia", "Egypt", recs,
            model_matrix=mat,
            lambda_home=1.1,
            lambda_away=0.9,
            team_context={"home_score": 67, "away_score": 64},
        )

        self.assertEqual(res["score_recommendations"][0]["score"], "1-1")
        self.assertGreater(res["score_recommendations"][0]["probability"], 0)
        self.assertIn("1-2球", [r["label"] for r in res["goal_recommendations"]])
        self.assertIn("half_full_recommendations", res)
        self.assertEqual(res["team_context"]["home_score"], 67)

    def test_ai_analysis_prompt_includes_sources_model_and_half_full(self):
        recs = [{
            "source": "iuv",
            "scores": ["0-0", "1-0"],
            "goal_picks": ["0-1球"],
            "half_full_picks": ["平平"],
            "confidence": "高",
            "note": "",
        }]
        consensus = {
            "score_recommendations": [{"score": "0-0", "probability": 0.28}],
            "goal_recommendations": [{"label": "0-1球", "probability": 0.42}],
            "half_full_recommendations": [{"label": "平平", "probability": 0.31}],
            "team_context": {"home_style": "低位防守", "away_style": "反击", "home_score": 63, "away_score": 61},
        }

        prompt = R.build_ai_prompt("Australia", "Egypt", recs, consensus)

        self.assertIn("iuv", prompt)
        self.assertIn("0-0", prompt)
        self.assertIn("半全场", prompt)
        self.assertIn("低位防守", prompt)

    def test_ai_analysis_uses_provider_and_returns_text(self):
        with patch("wc2026.analysis.recommendations.provider.chat", return_value="综合首选 1-1。") as chat:
            res = R.ai_analyze("Australia", "Egypt", [], {"score_recommendations": []})

        self.assertTrue(res["ok"])
        self.assertEqual(res["text"], "综合首选 1-1。")
        self.assertTrue(chat.called)


if __name__ == "__main__":
    unittest.main()
