import unittest

from wc2026.markets.risk import bankroll_sim, kelly_fraction


class RiskTest(unittest.TestCase):
    def test_kelly_fraction(self):
        self.assertAlmostEqual(kelly_fraction(0.55, 2.0), 0.10, places=6)  # edge=0.1,b=1
        self.assertEqual(kelly_fraction(0.4, 2.0), 0.0)                    # 负边际→0
        self.assertEqual(kelly_fraction(0.5, 1.0), 0.0)                    # b<=0

    def test_zero_fraction_no_risk(self):
        r = bankroll_sim(0.55, 2.0, 0.0)
        self.assertEqual(r["risk_of_ruin"], 0.0)
        self.assertEqual(r["median_final"], 1.0)

    def test_positive_edge_mostly_profits(self):
        # 明显正期望 + 1/4 凯利 → 多数情形盈利、破产概率低
        f = kelly_fraction(0.60, 2.0) * 0.25
        r = bankroll_sim(0.60, 2.0, f, n_bets=80, n_sims=4000)
        self.assertGreater(r["p_profit"], 0.6)
        self.assertLess(r["risk_of_ruin"], 0.1)

    def test_overbetting_raises_ruin(self):
        # 同样边际,全凯利 vs 1/4 凯利:全凯利回撤/破产风险更高
        full = bankroll_sim(0.55, 2.0, kelly_fraction(0.55, 2.0), n_bets=100, n_sims=4000)
        quarter = bankroll_sim(0.55, 2.0, kelly_fraction(0.55, 2.0) * 0.25, n_bets=100, n_sims=4000)
        self.assertGreaterEqual(full["median_max_drawdown"], quarter["median_max_drawdown"])
        self.assertGreaterEqual(full["risk_of_ruin"], quarter["risk_of_ruin"])

    def test_outputs_in_range(self):
        r = bankroll_sim(0.52, 2.1, 0.05, n_bets=30, n_sims=2000)
        for k in ("p_profit", "p_drawdown_20", "risk_of_ruin"):
            self.assertTrue(0.0 <= r[k] <= 1.0)


if __name__ == "__main__":
    unittest.main()
