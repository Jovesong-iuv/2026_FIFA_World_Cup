import unittest

from wc2026.analysis import dashboard_bridge


class DashboardBridgePayloadTest(unittest.TestCase):
    def test_prediction_payload_exposes_style_and_win_margins(self):
        pred = {
            "matrix": __import__("numpy").array([[0.4, 0.1], [0.2, 0.3]]),
            "dimensions": {
                "dims": [],
                "score_home": 70,
                "score_away": 64,
                "explanation": "测试",
                "data_quality": 1.0,
            },
            "exp_goals": (1.2, 0.8),
            "base_exp_goals": (1.1, 0.9),
            "adj_factors": {},
            "notes": [],
            "confidence": "中",
            "tank_risk": False,
        }

        payload = dashboard_bridge.build_dashboard_payload(
            _Model(), "Spain", "Saudi Arabia", pred=pred
        )

        self.assertIn("style_profiles", payload["prediction"])
        self.assertIn("win_margins", payload["prediction"])
        self.assertIn("home_by_2_plus", payload["prediction"]["win_margins"])
        self.assertIn("attack_volume", payload["prediction"]["style_profiles"]["home"]["dimensions"])


class _Model:
    teams = ["Spain", "Saudi Arabia"]
    attack = {"Spain": 1.0, "Saudi Arabia": 0.0}
    defense = {"Spain": 0.0, "Saudi Arabia": 1.0}

    def has_team(self, _t):
        return True

    def expected_goals(self, *_args):
        return 1.2, 0.8

    def score_matrix(self, *_args):
        return __import__("numpy").array([[0.4, 0.1], [0.2, 0.3]])


if __name__ == "__main__":
    unittest.main()
