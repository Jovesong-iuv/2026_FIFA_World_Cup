import unittest

from wc2026.analysis.fatigue import haversine_km, match_fatigue, rest_and_travel


def _fixtures():
    # 一支队 Mexico 三场:墨西哥城→瓜达拉哈拉→蒙特雷
    return [
        {"match_number": 1, "home_team": "Mexico", "away_team": "South Africa",
         "date_utc": "2026-06-11 19:00:00Z", "location": "Mexico City Stadium"},
        {"match_number": 20, "home_team": "Mexico", "away_team": "X",
         "date_utc": "2026-06-17 19:00:00Z", "location": "Guadalajara Stadium"},
        {"match_number": 40, "home_team": "Y", "away_team": "Mexico",
         "date_utc": "2026-06-24 19:00:00Z", "location": "Monterrey Stadium"},
    ]


class FatigueTest(unittest.TestCase):
    def test_haversine_known_distance(self):
        # 墨西哥城↔瓜达拉哈拉 约 460-480 km
        d = haversine_km(19.303, -99.150, 20.682, -103.462)
        self.assertTrue(440 <= d <= 500, d)

    def test_first_match_no_prev(self):
        r = rest_and_travel("Mexico", _fixtures(), 1)
        self.assertIsNone(r["rest_days"])
        self.assertIsNone(r["travel_km"])
        self.assertEqual(r["alt"], 2240)   # 墨西哥城海拔

    def test_rest_days_and_travel(self):
        r = rest_and_travel("Mexico", _fixtures(), 20)
        self.assertEqual(r["rest_days"], 6)        # 06-11 → 06-17
        self.assertTrue(r["travel_km"] and r["travel_km"] > 400)
        self.assertEqual(r["alt"], 1560)           # 瓜达拉哈拉

    def test_match_fatigue_altitude_note(self):
        fx = _fixtures()
        mf = match_fatigue("Mexico", "South Africa", fx, fx[0])
        self.assertTrue(any("高原" in n for n in mf["notes"]))   # 墨西哥城 2240m

    def test_no_fixture(self):
        self.assertEqual(match_fatigue("A", "B", [], None)["notes"], [])


if __name__ == "__main__":
    unittest.main()
