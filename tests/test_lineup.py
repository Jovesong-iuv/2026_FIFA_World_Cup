import unittest

from wc2026.data.squads import estimate_lineup


def _groups():
    def pl(name, val, rating=7.0, injured=False):
        return {"player_name": name, "value": val, "rating": rating, "injured": injured}
    return {
        "Goalkeeper": [pl("GK1", 5e6), pl("GK2", 3e6)],
        "Defender": [pl("DF1", 40e6), pl("DF2", 30e6), pl("DF3", 20e6),
                     pl("DF4", 15e6), pl("DF5", 10e6, injured=True), pl("DF6", 8e6)],
        "Midfielder": [pl("MF1", 50e6), pl("MF2", 25e6), pl("MF3", 12e6),
                       pl("MF4", 9e6), pl("MF5", 7e6), pl("MF6", 5e6)],
        "Attacker": [pl("FW1", 80e6), pl("FW2", 60e6), pl("FW3", 18e6)],
    }


class EstimateLineupTest(unittest.TestCase):
    def test_433_picks_top_by_value_per_position(self):
        res = estimate_lineup(_groups(), "4-3-3")
        names = [p["player_name"] for p in res["xi"]]
        self.assertEqual(res["size"], 11)
        self.assertIn("GK1", names)
        self.assertEqual(sorted(n for n in names if n.startswith("DF")), ["DF1", "DF2", "DF3", "DF4"])
        self.assertNotIn("DF5", names)   # 伤停被排除

    def test_excludes_injured(self):
        res = estimate_lineup(_groups(), "4-4-2")
        self.assertNotIn("DF5", [p["player_name"] for p in res["xi"]])

    def test_total_value_sums_xi(self):
        res = estimate_lineup(_groups(), "4-3-3")
        self.assertAlmostEqual(res["total_value"], sum(float(p["value"]) for p in res["xi"]))
        # 4-3-3: GK1 + DF1-4 + MF1-3 + FW1-3
        expected = 5e6 + (40+30+20+15)*1e6 + (50+25+12)*1e6 + (80+60+18)*1e6
        self.assertAlmostEqual(res["total_value"], expected)

    def test_formation_counts(self):
        for f, exp in [("4-3-3", 11), ("4-4-2", 11), ("3-5-2", 11)]:
            self.assertEqual(estimate_lineup(_groups(), f)["size"], exp)

    def test_short_position_takes_available(self):
        groups = {"Goalkeeper": [{"player_name": "GK1", "value": 1e6}]}  # 仅 1 人
        res = estimate_lineup(groups, "4-3-3")
        self.assertEqual([p["player_name"] for p in res["xi"]], ["GK1"])
        self.assertEqual(res["size"], 1)


if __name__ == "__main__":
    unittest.main()
