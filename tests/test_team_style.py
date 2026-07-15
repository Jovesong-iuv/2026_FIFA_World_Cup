import unittest

from wc2026.analysis.team_style import style_goal_adjustment, style_profile
from wc2026.markets.derive import over_under
from wc2026.models.dixon_coles import DixonColesModel
from wc2026.models.predictor import EnsembleModel


class TeamStyleAdjustmentTest(unittest.TestCase):
    def test_ensemble_exposes_dixon_coles_rho(self):
        dc = DixonColesModel()
        dc.rho = -0.075

        model = EnsembleModel(dc, team_profiles={})

        self.assertEqual(model.rho, -0.075)

    def test_style_profile_exposes_quantified_proxy_dimensions(self):
        p = style_profile("A", profiles={
            "A": {"formation": "4-3-3",
                  "style_detail": "传控体系,高位逼抢+快速反击,定位球威胁"}
        })

        dims = p["dimensions"]
        self.assertGreater(dims["attack_volume"], 0)
        self.assertGreater(dims["pressing"], 0)
        self.assertGreater(dims["transition_attack"], 0)
        self.assertGreater(dims["set_piece_attack"], 0)

    def test_low_block_profile_has_defensive_resistance(self):
        p = style_profile("A", profiles={
            "A": {"formation": "5-4-1", "style_detail": "低位密集防守,阵地战,防守韧性"}
        })

        dims = p["dimensions"]
        self.assertEqual(p["lean"], "防守")
        self.assertGreater(dims["low_block"], 0)
        self.assertGreater(dims["defensive_resistance"], 0)
        self.assertLessEqual(dims["tempo"], 0)

    def test_attacking_pair_raises_expected_goals(self):
        adj = style_goal_adjustment(
            "A", "B", 1.2, 1.1,
            profiles={
                "A": {"formation": "4-3-3", "style_detail": "高位逼抢+快速反击"},
                "B": {"formation": "4-3-3", "style_detail": "边路突破,进攻型"},
            },
        )
        self.assertGreater(adj["home_goals"], 1.2)
        self.assertGreater(adj["away_goals"], 1.1)
        self.assertEqual(adj["home_profile"]["lean"], "进攻")
        self.assertEqual(adj["away_profile"]["lean"], "进攻")

    def test_defensive_pair_lowers_expected_goals(self):
        adj = style_goal_adjustment(
            "A", "B", 1.2, 1.1,
            profiles={
                "A": {"formation": "5-4-1", "style_detail": "低位防守+反击"},
                "B": {"formation": "4-5-1", "style_detail": "防守韧性,密集防守"},
            },
        )
        self.assertLess(adj["home_goals"], 1.2)
        self.assertLess(adj["away_goals"], 1.1)
        self.assertEqual(adj["home_profile"]["lean"], "防守")
        self.assertEqual(adj["away_profile"]["lean"], "防守")

    def test_ensemble_uses_style_shape_before_market_summary(self):
        dc = DixonColesModel()
        dc.attack = {"OpenA": 0.0, "OpenB": 0.0, "LowA": 0.0, "LowB": 0.0}
        dc.defense = {"OpenA": 0.0, "OpenB": 0.0, "LowA": 0.0, "LowB": 0.0}
        dc.teams = sorted(dc.attack)
        dc.fitted = True
        profiles = {
            "OpenA": {"formation": "4-3-3", "style_detail": "高位逼抢,快速反击"},
            "OpenB": {"formation": "4-3-3", "style_detail": "进攻型,边路突破"},
            "LowA": {"formation": "5-4-1", "style_detail": "低位防守,反击"},
            "LowB": {"formation": "4-5-1", "style_detail": "密集防守,阵地战"},
        }
        model = EnsembleModel(dc, team_profiles=profiles)

        open_over = over_under(model.score_matrix("OpenA", "OpenB"), 2.5)["over"]
        low_over = over_under(model.score_matrix("LowA", "LowB"), 2.5)["over"]

        self.assertGreater(open_over, low_over)

    def test_prediction_goals_exposes_style_adjusted_goals(self):
        dc = DixonColesModel()
        dc.attack = {"OpenA": 0.0, "OpenB": 0.0}
        dc.defense = {"OpenA": 0.0, "OpenB": 0.0}
        dc.teams = sorted(dc.attack)
        dc.fitted = True
        model = EnsembleModel(dc, team_profiles={
            "OpenA": {"formation": "4-3-3", "style_detail": "高位逼抢"},
            "OpenB": {"formation": "4-3-3", "style_detail": "进攻型"},
        })

        base = model.expected_goals("OpenA", "OpenB")
        adjusted = model.prediction_goals("OpenA", "OpenB")

        self.assertGreater(adjusted[0], base[0])
        self.assertGreater(adjusted[1], base[1])


if __name__ == "__main__":
    unittest.main()
