import unittest

from wc2026.markets.value import market_temperature


class MarketTemperatureTest(unittest.TestCase):
    def test_overhyped_favorite_is_hot(self):
        # 市场给主胜剔水概率 0.65，模型只给 0.55 → 偏热(市场高估热门)
        res = market_temperature({"home": 0.55, "draw": 0.25, "away": 0.20},
                                 {"home": 0.65, "draw": 0.22, "away": 0.13})
        self.assertEqual(res["favorite"], "home")
        self.assertEqual(res["verdict"], "偏热")
        self.assertEqual(res["results"]["home"]["label"], "偏热")
        self.assertEqual(res["results"]["away"]["label"], "偏冷")

    def test_neutral_within_threshold(self):
        res = market_temperature({"home": 0.50, "draw": 0.28, "away": 0.22},
                                 {"home": 0.51, "draw": 0.27, "away": 0.22})
        self.assertEqual(res["verdict"], "中性")
        for k in ("home", "draw", "away"):
            self.assertEqual(res["results"][k]["label"], "中性")

    def test_undervalued_favorite_is_cold(self):
        res = market_temperature({"home": 0.60, "draw": 0.25, "away": 0.15},
                                 {"home": 0.50, "draw": 0.30, "away": 0.20})
        self.assertEqual(res["verdict"], "偏冷")  # 市场低估热门 → 有价值
        self.assertAlmostEqual(res["results"]["home"]["diff"], -0.10, places=6)

    def test_missing_market_prob_skipped(self):
        res = market_temperature({"home": 0.6, "draw": 0.25, "away": 0.15},
                                 {"home": 0.6})
        self.assertIn("home", res["results"])
        self.assertNotIn("draw", res["results"])


if __name__ == "__main__":
    unittest.main()
