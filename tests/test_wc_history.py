import unittest

from wc2026.analysis.wc_history import meeting_row, summarize_record


class WcHistoryTest(unittest.TestCase):
    def test_summarize_record_counts_and_editions(self):
        rows = [
            {"date": "2018-06-17", "home_team": "Brazil", "away_team": "X", "home_score": 1, "away_score": 1},
            {"date": "2018-06-22", "home_team": "Y", "away_team": "Brazil", "home_score": 0, "away_score": 2},
            {"date": "2022-11-24", "home_team": "Brazil", "away_team": "Z", "home_score": 2, "away_score": 0},
        ]
        s = summarize_record(rows, "Brazil")
        self.assertEqual(s["matches"], 3)
        self.assertEqual((s["w"], s["d"], s["l"]), (2, 1, 0))
        self.assertEqual((s["gf"], s["ga"]), (5, 1))
        self.assertEqual(s["editions"], 2)          # 2018, 2022
        self.assertEqual((s["first"], s["last"]), (2018, 2022))

    def test_summarize_skips_unplayed(self):
        rows = [{"date": "2026-06-11", "home_team": "Brazil", "away_team": "X",
                 "home_score": None, "away_score": None}]
        s = summarize_record(rows, "Brazil")
        self.assertEqual(s["matches"], 0)
        self.assertIsNone(s["first"])

    def test_meeting_row_formats_score_and_year(self):
        m = meeting_row({"date": "2010-06-11", "home_team": "South Africa", "away_team": "Mexico",
                         "home_score": 1, "away_score": 1, "country": "South Africa"})
        self.assertEqual(m["year"], 2010)
        self.assertEqual(m["score"], "1-1")
        self.assertEqual(m["country"], "South Africa")


if __name__ == "__main__":
    unittest.main()
