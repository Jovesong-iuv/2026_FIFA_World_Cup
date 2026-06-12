import unittest

from wc2026.analysis.strength import DIMENSIONS, strength_profile


class _Elo:
    def __init__(self, ratings):
        self.ratings = ratings

    def rating(self, t):
        return self.ratings.get(t, 1500.0)


class MockModel:
    def __init__(self):
        self.teams = ["Strong", "Weak", "Mid"]
        self.attack = {"Strong": 1.0, "Weak": -1.0, "Mid": 0.0}
        self.defense = {"Strong": -1.0, "Weak": 1.0, "Mid": 0.0}  # 越低防守越好
        self.elo = _Elo({"Strong": 1900.0, "Weak": 1300.0, "Mid": 1600.0})


class StrengthProfileTest(unittest.TestCase):
    def setUp(self):
        self.model = MockModel()

    def test_strong_team_scores_higher(self):
        res = strength_profile(self.model, "Strong", "Weak")
        self.assertGreater(res["score_home"], res["score_away"])
        # 强队各分项均应触顶（min-max 下取最大值 → 100）
        self.assertAlmostEqual(res["dims_home"]["基础实力"], 100.0, places=6)
        self.assertAlmostEqual(res["dims_home"]["进攻"], 100.0, places=6)
        self.assertAlmostEqual(res["dims_home"]["防守"], 100.0, places=6)  # 反转后最佳=100

    def test_defense_inversion(self):
        # Weak 的 defense 系数最高（最差）→ 防守分应最低（0）
        res = strength_profile(self.model, "Weak", "Strong")
        self.assertAlmostEqual(res["dims_home"]["防守"], 0.0, places=6)

    def test_all_dimensions_in_range(self):
        res = strength_profile(self.model, "Mid", "Weak")
        for side in ("dims_home", "dims_away"):
            for k in DIMENSIONS:
                self.assertGreaterEqual(res[side][k], 0.0)
                self.assertLessEqual(res[side][k], 100.0)

    def test_recent_form_and_h2h_from_evidence(self):
        evidence = {
            "h2h": {"total": 4, "a_win": 3, "draw": 0, "a_loss": 1},
            "home_form": {"n": 5, "w": 5, "d": 0},   # 全胜 → 100
            "away_form": {"n": 5, "w": 0, "d": 0},    # 全负 → 0
        }
        res = strength_profile(self.model, "Mid", "Weak", evidence=evidence)
        self.assertAlmostEqual(res["dims_home"]["近期状态"], 100.0, places=6)
        self.assertAlmostEqual(res["dims_away"]["近期状态"], 0.0, places=6)
        self.assertAlmostEqual(res["dims_home"]["历史交锋"], 75.0, places=6)   # 3/4
        self.assertAlmostEqual(res["dims_away"]["历史交锋"], 25.0, places=6)   # a_loss/total

    def test_no_evidence_neutral_form_and_h2h(self):
        res = strength_profile(self.model, "Mid", "Weak")
        self.assertEqual(res["dims_home"]["近期状态"], 50.0)
        self.assertEqual(res["dims_home"]["历史交锋"], 50.0)


if __name__ == "__main__":
    unittest.main()
