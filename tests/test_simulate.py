import unittest

from wc2026.markets.derive import _poisson_score_matrix, outcomes_1x2
from wc2026.markets.simulate import simulate_match


class SimulateMatchTest(unittest.TestCase):
    def test_sim_converges_to_analytic_1x2(self):
        mat = _poisson_score_matrix(1.6, 1.1)
        r = simulate_match(mat, n_sims=40000, seed=7)
        ana = outcomes_1x2(mat)
        for k in ("home", "draw", "away"):
            self.assertLess(abs(r["sim_1x2"][k] - ana[k]), 0.02, k)   # 大样本 2% 内收敛
        self.assertLess(r["max_abs_err"], 0.02)

    def test_top_scores_sim_close_to_model(self):
        mat = _poisson_score_matrix(1.4, 1.0)
        r = simulate_match(mat, n_sims=40000, seed=3, top_k=6)
        self.assertEqual(len(r["top_scores"]), 6)
        for row in r["top_scores"]:
            self.assertLess(abs(row["sim_prob"] - row["model_prob"]), 0.03)
        # 频率降序
        sp = [x["sim_prob"] for x in r["top_scores"]]
        self.assertEqual(sp, sorted(sp, reverse=True))

    def test_over_under_sim(self):
        mat = _poisson_score_matrix(1.5, 1.5)
        r = simulate_match(mat, n_sims=30000, seed=1)
        self.assertAlmostEqual(r["sim_ou25"]["over"] + r["sim_ou25"]["under"], 1.0, places=6)
        self.assertLess(abs(r["sim_ou25"]["over"] - r["model_ou25"]["over"]), 0.03)


if __name__ == "__main__":
    unittest.main()
