import unittest

from wc2026.analysis.upset import risk_level, upset_index


class UpsetIndexTest(unittest.TestCase):
    def test_heavy_favorite_is_low_risk(self):
        res = upset_index({"home": 0.90, "draw": 0.07, "away": 0.03}, "Brazil", "Bolivia")
        self.assertEqual(res["index"], 10)
        self.assertEqual(res["level"], "低风险")
        self.assertEqual(res["favorite"], "Brazil")

    def test_even_match_is_higher_risk(self):
        res = upset_index({"home": 0.40, "draw": 0.30, "away": 0.30}, "Spain", "Germany")
        self.assertEqual(res["index"], 60)
        self.assertEqual(res["level"], "中风险")

    def test_tank_risk_increases_index(self):
        base = upset_index({"home": 0.40, "draw": 0.30, "away": 0.30}, "Spain", "Germany")
        bumped = upset_index({"home": 0.40, "draw": 0.30, "away": 0.30}, "Spain", "Germany",
                             tank_risk=True)
        self.assertEqual(bumped["index"], base["index"] + 10)
        self.assertTrue(any(f["name"] == "战意风险" for f in bumped["factors"]))

    def test_leaky_favorite_defense_adds_factor(self):
        evidence = {"home_form": {"n": 5, "ga": 10}, "away_form": {"n": 5, "ga": 2}}
        res = upset_index({"home": 0.90, "draw": 0.07, "away": 0.03}, "Brazil", "Bolivia",
                          evidence=evidence)
        self.assertEqual(res["index"], 18)  # 10 + 8
        self.assertTrue(any(f["name"] == "强队防守波动" for f in res["factors"]))

    def test_index_clamped_to_0_100(self):
        res = upset_index({"home": 0.0, "draw": 0.5, "away": 0.5}, "A", "B", tank_risk=True)
        self.assertLessEqual(res["index"], 100)
        self.assertGreaterEqual(res["index"], 0)

    def test_risk_level_bands(self):
        self.assertEqual(risk_level(0), "低风险")
        self.assertEqual(risk_level(20), "低风险")
        self.assertEqual(risk_level(21), "中低风险")
        self.assertEqual(risk_level(60), "中风险")
        self.assertEqual(risk_level(80), "高风险")
        self.assertEqual(risk_level(100), "极高风险")


if __name__ == "__main__":
    unittest.main()
