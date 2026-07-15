import unittest
from unittest.mock import patch

import numpy as np

from wc2026.analysis.environment import match_environment_report


class EnvironmentAnalysisTest(unittest.TestCase):
    @patch("wc2026.analysis.environment.load_cached_weather", return_value={
        "temperature_c": 24.0, "humidity_pct": 55,
        "precipitation_probability_pct": 10, "wind_kmh": 12.0,
        "forecast_time_utc": "2026-06-13T01:00", "source": "Open-Meteo",
        "fetched_at": "2026-06-12T20:00:00Z",
    })
    def test_usa_paraguay_report_contains_sourced_environment_without_political_background(self, _weather):
        mat = np.zeros((4, 4), dtype=float)
        mat[1, 0] = 0.18
        mat[2, 1] = 0.20
        mat[1, 1] = 0.16
        mat[0, 1] = 0.08
        mat = mat / mat.sum()

        fixture = {
            "date_utc": "2026-06-13 01:00:00Z",
            "location": "Los Angeles Stadium",
            "group_name": "Group D",
        }

        report = match_environment_report("United States", "Paraguay", mat, fixture=fixture)

        factors = {row["factor"] for row in report["environment"]}
        self.assertIn("跨时区", factors)
        self.assertIn("球场信息", factors)
        self.assertIn("海拔影响", factors)
        self.assertIn("气温与天气", factors)
        self.assertIn("远征与场地适应", factors)
        weather_row = next(row for row in report["environment"] if row["factor"] == "气温与天气")
        self.assertIn("24.0°C", weather_row["detail"])
        self.assertEqual(weather_row["source"], "Open-Meteo")

        self.assertEqual(report["score_pick"]["score"], "2-1")
        self.assertIn("环境", report["score_pick"]["basis"])

        teams = {row["team"] for row in report["adaptation"]}
        self.assertEqual(teams, {"美国", "巴拉圭"})

        self.assertEqual(report["background"], [])

    def test_unknown_fixture_degrades_gracefully(self):
        mat = np.ones((2, 2), dtype=float) / 4
        report = match_environment_report("Spain", "Germany", mat, fixture=None)

        self.assertGreaterEqual(len(report["environment"]), 5)
        self.assertTrue(report["score_pick"]["score"])
        self.assertTrue(any("暂无" in row["detail"] for row in report["environment"]))


if __name__ == "__main__":
    unittest.main()
