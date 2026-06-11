import unittest

import numpy as np

from wc2026.markets.derive import market_candidates


class MarketCandidatesTest(unittest.TestCase):
    def test_includes_value_markets_for_single_match_selection(self):
        mat = np.zeros((5, 5))
        mat[1, 0] = 0.35
        mat[1, 1] = 0.25
        mat[0, 1] = 0.20
        mat[2, 1] = 0.10
        mat[0, 0] = 0.10

        rows = market_candidates(mat, 1.2, 0.8, "墨西哥", "南非")
        markets = {r["market"] for r in rows}

        self.assertIn("胜平负", markets)
        self.assertIn("半全场胜平负", markets)
        self.assertIn("让球", markets)
        self.assertIn("大小球", markets)
        self.assertIn("进球个数", markets)
        self.assertIn("比分", markets)
        self.assertTrue(all(r["odds"] > 1 for r in rows))


if __name__ == "__main__":
    unittest.main()
