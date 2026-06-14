import unittest
from datetime import datetime, timezone

from wc2026.analysis.schedule import (beijing, is_concluded, match_result,
                                      parse_utc, sort_fixtures)


class ScheduleTest(unittest.TestCase):
    def test_beijing_is_utc_plus_8(self):
        b = beijing("2026-06-11 19:00:00Z")          # UTC 19:00 → 北京 次日 03:00
        self.assertEqual(b["date"], "2026-06-12")
        self.assertEqual(b["time"], "03:00")
        self.assertIn(b["weekday"], ["周一", "周二", "周三", "周四", "周五", "周六", "周日"])

    def test_beijing_weekday_matches_python(self):
        b = beijing("2026-06-11 19:00:00Z")  # 北京时间 2026-06-12
        weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        self.assertEqual(b["weekday"], weekdays[datetime(2026, 6, 12).weekday()])

    def test_unparseable_date(self):
        b = beijing(None)
        self.assertEqual(b["full"], "—")

    def test_match_result_outcomes(self):
        self.assertEqual(match_result(None, None)["finished"], False)
        self.assertEqual(match_result(2, 0, "墨西哥", "南非")["winner"], "home")
        self.assertEqual(match_result(0, 2, "墨西哥", "南非")["winner"], "away")
        self.assertEqual(match_result(1, 1)["winner"], "draw")
        self.assertEqual(match_result(2, 0, "墨西哥", "南非")["score"], "2-0")
        self.assertIn("墨西哥胜", match_result(2, 0, "墨西哥", "南非")["text"])

    def test_is_concluded_by_score_or_time(self):
        now = datetime(2026, 6, 15, tzinfo=timezone.utc)
        self.assertTrue(is_concluded({"date_utc": "2026-06-11 19:00:00Z"}, now))   # 已过期
        self.assertFalse(is_concluded({"date_utc": "2026-06-20 19:00:00Z"}, now))  # 未来
        self.assertTrue(is_concluded(  # 有比分即已完赛
            {"date_utc": "2026-06-20 19:00:00Z", "home_score": 1, "away_score": 0}, now))

    def test_sort_upcoming_first_concluded_last(self):
        now = datetime(2026, 6, 15, tzinfo=timezone.utc)
        fx = [
            {"date_utc": "2026-06-11 19:00:00Z", "home_score": 2, "away_score": 1},  # 已完赛
            {"date_utc": "2026-06-20 19:00:00Z"},                                    # 未来
            {"date_utc": "2026-06-18 19:00:00Z"},                                    # 未来(更早)
            {"date_utc": "2026-06-12 19:00:00Z"},                                    # 已过期
        ]
        out = sort_fixtures(fx, now)
        # 未来两场在前(升序)，已结束两场在后(降序)
        self.assertEqual(out[0]["date_utc"], "2026-06-18 19:00:00Z")
        self.assertEqual(out[1]["date_utc"], "2026-06-20 19:00:00Z")
        self.assertEqual(out[2]["date_utc"], "2026-06-12 19:00:00Z")  # 较新的已结束在前
        self.assertEqual(out[3]["date_utc"], "2026-06-11 19:00:00Z")


if __name__ == "__main__":
    unittest.main()
