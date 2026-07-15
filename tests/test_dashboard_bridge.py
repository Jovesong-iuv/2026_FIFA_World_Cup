import unittest
import ast
from pathlib import Path
from unittest.mock import patch

from wc2026.analysis import dashboard_bridge


class DashboardBridgePayloadTest(unittest.TestCase):
    def test_streamlit_single_match_page_mounts_visual_dashboard(self):
        app_path = Path(__file__).resolve().parents[1] / "web" / "app.py"
        tree = ast.parse(app_path.read_text(encoding="utf-8"))
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name)
                 and node.func.id == "render_bridge_dashboard"]

        self.assertEqual(len(calls), 1)

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

        with patch("wc2026.analysis.dashboard_bridge.tournament_facts.compare_teams",
                   return_value={"home": {"team": "Spain"}, "away": {"team": "Saudi Arabia"}}):
            payload = dashboard_bridge.build_dashboard_payload(
                _Model(), "Spain", "Saudi Arabia", pred=pred
            )

        self.assertIn("style_profiles", payload["prediction"])
        self.assertIn("win_margins", payload["prediction"])
        self.assertIn("match_analysis", payload)
        self.assertIn("knockout", payload)
        self.assertIn("home_by_2_plus", payload["prediction"]["win_margins"])
        self.assertIn("attack_volume", payload["prediction"]["style_profiles"]["home"]["dimensions"])
        self.assertIn("advance", payload["knockout"])
        self.assertIn("ev_board", payload["knockout"])
        self.assertEqual(payload["tournament_facts"]["home"]["team"], "Spain")
        self.assertIn("group_standings", payload)

    def test_group_standings_payload_highlights_match_group(self):
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
        gd = {
            "Group C": {
                "teams": ["Spain", "Saudi Arabia", "Japan", "Ghana"],
                "matches": [(0, 1, 2, 0), (2, 3, 1, 1), (0, 2, None, None)],
            }
        }

        with patch("wc2026.analysis.dashboard_bridge.groups.load_group_data", return_value=gd), \
                patch("wc2026.analysis.dashboard_bridge.tournament_facts.compare_teams",
                      return_value={"home": {"team": "Spain"}, "away": {"team": "Saudi Arabia"}}):
            payload = dashboard_bridge.build_dashboard_payload(
                _Model(), "Spain", "Saudi Arabia",
                fixture={"group_name": "Group C"}, fixtures=[], pred=pred
            )

        self.assertEqual(payload["group_standings"]["group"], "Group C")
        self.assertEqual(payload["group_standings"]["group_letter"], "C")
        self.assertEqual(payload["group_standings"]["teams"], ["Spain", "Saudi Arabia"])
        self.assertEqual(payload["group_standings"]["rows"][0]["team"], "Spain")
        self.assertTrue(payload["group_standings"]["rows"][0]["highlight"])
        self.assertEqual(payload["group_standings"]["rows"][0]["form"], "W")


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
