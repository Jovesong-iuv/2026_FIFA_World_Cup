import unittest

import numpy as np

from wc2026.markets import derive


class MarketDeriveTest(unittest.TestCase):
    def test_goal_band_groups_total_goals(self):
        mat = np.zeros((5, 5))
        mat[0, 0] = 0.10
        mat[1, 0] = 0.20
        mat[1, 1] = 0.30
        mat[3, 1] = 0.40

        bands = derive.goal_bands(mat)

        self.assertAlmostEqual(bands["0-1球"], 0.30)
        self.assertAlmostEqual(bands["2-3球"], 0.30)
        self.assertAlmostEqual(bands["4+球"], 0.40)

    def test_win_margin_ladders_from_score_matrix(self):
        mat = np.zeros((5, 5))
        mat[2, 0] = 0.20
        mat[3, 0] = 0.10
        mat[4, 0] = 0.05
        mat[0, 2] = 0.07
        mat[0, 3] = 0.03
        mat[1, 1] = 0.55

        margins = derive.win_margin_ladders(mat, thresholds=(2, 3, 4))

        self.assertAlmostEqual(margins["home_by_2_plus"], 0.35)
        self.assertAlmostEqual(margins["home_by_3_plus"], 0.15)
        self.assertAlmostEqual(margins["home_by_4_plus"], 0.05)
        self.assertAlmostEqual(margins["away_by_2_plus"], 0.10)
        self.assertAlmostEqual(margins["away_by_3_plus"], 0.03)
        self.assertAlmostEqual(margins["away_by_4_plus"], 0.00)

    def test_half_full_time_probabilities_sum_to_one(self):
        hf = derive.half_full_time(1.4, 0.8)

        self.assertEqual(len(hf), 9)
        self.assertAlmostEqual(sum(hf.values()), 1.0, places=6)
        self.assertIn("胜胜", hf)
        self.assertIn("平负", hf)

    def test_summarize_includes_win_margin_ladders(self):
        mat = np.zeros((5, 5))
        mat[3, 0] = 0.25
        mat[1, 1] = 0.75

        summary = derive.summarize(mat)

        self.assertIn("win_margins", summary)
        self.assertAlmostEqual(summary["win_margins"]["home_by_3_plus"], 0.25)


if __name__ == "__main__":
    unittest.main()
