import unittest

import numpy as np

from wc2026.analysis import knockout_analysis as K


class KnockoutAnalysisTest(unittest.TestCase):
    def test_advancement_formula_combines_90_et_and_penalties(self):
        mat = np.array([[0.12, 0.08, 0.04],
                        [0.18, 0.16, 0.06],
                        [0.14, 0.12, 0.10]])

        res = K.knockout_probabilities(mat, 1.3, 0.9, "Brazil", "Japan")

        self.assertAlmostEqual(
            res["advance"]["home"],
            res["outcomes_90"]["home"]
            + res["outcomes_90"]["draw"] * res["extra_time"]["home"]
            + res["outcomes_90"]["draw"] * res["extra_time"]["draw"] * res["penalties"]["home"],
            places=6,
        )
        self.assertAlmostEqual(res["advance"]["home"] + res["advance"]["away"], 1.0, places=6)
        self.assertIn("P(巴西晋级)", res["advance"]["formula_home"])
        self.assertGreater(res["extra_time"]["draw"], 0)

    def test_totals_include_quarter_line_and_goal_distribution(self):
        mat = np.array([[0.20, 0.10, 0.04, 0.01],
                        [0.12, 0.16, 0.09, 0.02],
                        [0.08, 0.07, 0.06, 0.02],
                        [0.01, 0.01, 0.01, 0.00]])

        totals = K.totals_90(mat)

        self.assertIn("2.5", totals["lines"])
        self.assertIn("2.75", totals["lines"])
        self.assertIn("over_full", totals["lines"]["2.75"])
        self.assertIn("under_half_win", totals["lines"]["2.75"])
        self.assertAlmostEqual(sum(totals["goal_distribution"].values()), 1.0, places=6)

    def test_ev_board_sorts_recommendations(self):
        board = K.ev_board(
            {"home": 0.52, "draw": 0.24, "away": 0.24},
            {"home": 0.72, "away": 0.28},
            {"2.5": {"over": 0.48, "under": 0.52},
             "2.75": {"over_full": 0.30, "over_half_win": 0.20, "under_full": 0.30, "under_half_win": 0.20}},
            {"home": 2.1, "draw": 3.2, "away": 3.4},
            "Brazil",
            "Japan",
            limit=7,
        )

        self.assertLessEqual(len(board), 7)
        self.assertEqual(board[0]["rank"], 1)
        self.assertGreaterEqual(board[0]["ev"], board[-1]["ev"])
        self.assertTrue(any(r["recommendation"] == "推荐" for r in board))


if __name__ == "__main__":
    unittest.main()
