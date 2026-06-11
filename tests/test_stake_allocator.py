import unittest

from wc2026.markets.value import allocate_stakes


class StakeAllocatorTest(unittest.TestCase):
    def test_allocates_positive_edge_candidates_by_fractional_kelly(self):
        rows = allocate_stakes(
            [
                {"key": "home", "label": "主胜", "market": "胜平负", "model_prob": 0.55, "odds": 2.1},
                {"key": "draw", "label": "平局", "market": "胜平负", "model_prob": 0.24, "odds": 3.0},
                {"key": "score_1_0", "label": "1-0", "market": "比分", "model_prob": 0.14, "odds": 8.5},
            ],
            bankroll=1000,
            kelly_fraction=0.25,
        )

        self.assertEqual([r["key"] for r in rows], ["home", "score_1_0"])
        self.assertAlmostEqual(sum(r["stake"] for r in rows), 1000)
        self.assertGreater(rows[0]["stake"], rows[1]["stake"])
        self.assertGreater(rows[0]["edge"], 0)

    def test_accounts_for_push_probability_when_allocating_handicap(self):
        rows = allocate_stakes(
            [
                {
                    "key": "ah_0_home",
                    "label": "主队 0",
                    "market": "让球",
                    "model_prob": 0.45,
                    "push_prob": 0.30,
                    "odds": 1.9,
                }
            ],
            bankroll=500,
            kelly_fraction=0.25,
        )

        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["edge"], 0.155)
        self.assertAlmostEqual(rows[0]["stake"], 500)

    def test_returns_no_rows_when_there_is_no_positive_edge(self):
        rows = allocate_stakes(
            [{"key": "away", "label": "客胜", "market": "胜平负", "model_prob": 0.30, "odds": 2.5}],
            bankroll=1000,
        )

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
