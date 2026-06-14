import unittest

from wc2026.markets.derive import _poisson_score_matrix
from wc2026.analysis.goal_strategy import band_probs, recommend, total_goals_dist


class GoalStrategyTest(unittest.TestCase):
    def test_total_goals_dist_sums_to_one(self):
        mat = _poisson_score_matrix(1.3, 1.1)
        dist = total_goals_dist(mat)
        self.assertAlmostEqual(sum(dist.values()), 1.0, places=6)
        self.assertAlmostEqual(dist[0], mat[0, 0], places=6)

    def test_band_overlap_at_three(self):
        dist = {0: 0.1, 1: 0.2, 2: 0.3, 3: 0.25, 4: 0.1, 5: 0.05}
        bp = band_probs(dist)
        self.assertAlmostEqual(bp["2-3"], 0.55, places=6)
        self.assertAlmostEqual(bp["3-4"], 0.35, places=6)
        self.assertAlmostEqual(bp["0-1"], 0.30, places=6)

    def test_low_scoring_match_is_avoided(self):
        lam, mu = 0.8, 0.7
        rec = recommend(_poisson_score_matrix(lam, mu), lam, mu)
        self.assertEqual(rec["recommend"], "回避")

    def test_balanced_moderate_match_recommends_2_3(self):
        lam, mu = 1.2, 1.1                      # xg=2.3, 均衡
        rec = recommend(_poisson_score_matrix(lam, mu), lam, mu)
        self.assertEqual(rec["recommend"], "2-3球")
        self.assertTrue(any("均衡" in c[0] for c in rec["checklist"]))

    def test_high_scoring_strong_side_recommends_3_4(self):
        lam, mu = 2.3, 1.0                      # xg=3.3, 强侧>1.5
        rec = recommend(_poisson_score_matrix(lam, mu), lam, mu)
        self.assertEqual(rec["recommend"], "3-4球")
        self.assertTrue(any("期望进球>1.5" in c[0] for c in rec["checklist"]))

    def test_checklist_has_odds_confirmation_item(self):
        lam, mu = 1.2, 1.1
        rec = recommend(_poisson_score_matrix(lam, mu), lam, mu)
        self.assertTrue(any(s == "需盘口确认" for _c, s in rec["checklist"]))


if __name__ == "__main__":
    unittest.main()
