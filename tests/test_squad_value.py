import unittest

from wc2026.data.squads import squad_value_summary


def _groups():
    return {
        "Goalkeeper": [{"player_name": "GK1", "position": "Goalkeeper", "value": 5_000_000}],
        "Defender": [
            {"player_name": "DF1", "position": "Defender", "value": 20_000_000},
            {"player_name": "DF2", "position": "Defender", "value": None},  # 无身价
        ],
        "Attacker": [
            {"player_name": "FW1", "position": "Attacker", "value": 50_000_000},
            {"player_name": "FW2", "position": "Attacker", "value": 30_000_000},
        ],
    }


class SquadValueSummaryTest(unittest.TestCase):
    def test_total_and_counts(self):
        s = squad_value_summary(_groups())
        self.assertEqual(s["total"], 105_000_000)   # 5+20+50+30（DF2 无身价不计）
        self.assertEqual(s["count"], 5)
        self.assertEqual(s["valued_count"], 4)

    def test_by_position(self):
        s = squad_value_summary(_groups())
        self.assertEqual(s["by_position"]["Attacker"], 80_000_000)
        self.assertEqual(s["by_position"]["Defender"], 20_000_000)
        self.assertEqual(s["by_position"]["Goalkeeper"], 5_000_000)

    def test_top5_sorted_desc(self):
        s = squad_value_summary(_groups())
        names = [p["player_name"] for p in s["top5"]]
        self.assertEqual(names, ["FW1", "FW2", "DF1", "GK1"])  # 仅 4 个有身价

    def test_empty_or_none(self):
        for g in (None, {}, {"Defender": [{"player_name": "X", "value": None}]}):
            s = squad_value_summary(g)
            self.assertEqual(s["total"], 0)
            self.assertEqual(s["top5"], [])


if __name__ == "__main__":
    unittest.main()
