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

    def test_half_full_time_probabilities_sum_to_one(self):
        hf = derive.half_full_time(1.4, 0.8)

        self.assertEqual(len(hf), 9)
        self.assertAlmostEqual(sum(hf.values()), 1.0, places=6)
        self.assertIn("胜胜", hf)
        self.assertIn("平负", hf)


if __name__ == "__main__":
    unittest.main()
