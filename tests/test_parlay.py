import unittest

from wc2026.markets.value import parlay_summary


class ParlaySummaryTest(unittest.TestCase):
    def test_combines_probabilities_odds_and_expected_value(self):
        summary = parlay_summary(
            [
                {"label": "墨西哥胜", "model_prob": 0.7, "odds": 1.5},
                {"label": "韩国胜", "model_prob": 0.5, "odds": 2.2},
                {"label": "加拿大胜", "model_prob": 0.6, "odds": 1.9},
            ],
            stake=100,
        )

        self.assertAlmostEqual(summary["combined_prob"], 0.21)
        self.assertAlmostEqual(summary["combined_odds"], 6.27)
        self.assertAlmostEqual(summary["edge"], 0.3167)
        self.assertAlmostEqual(summary["potential_return"], 627)
        self.assertAlmostEqual(summary["expected_profit"], 31.67)

    def test_returns_empty_summary_without_valid_legs(self):
        summary = parlay_summary([{"label": "无效", "model_prob": 0.5, "odds": 1.0}], stake=100)

        self.assertEqual(summary["legs"], [])
        self.assertEqual(summary["combined_prob"], 0)
        self.assertEqual(summary["combined_odds"], 0)


if __name__ == "__main__":
    unittest.main()
