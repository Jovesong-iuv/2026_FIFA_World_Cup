import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from wc2026.analysis.schedule import (beijing, is_concluded, match_result,
                                      parse_utc, sort_fixtures)
from wc2026.data.sources.fixtures_2026 import (fetch_fixture_snapshot,
                                               merge_fixture_snapshots)


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

    def test_live_snapshot_resolves_knockout_placeholder_without_losing_local_score(self):
        cached = [
            {"match_number": 100, "home_team": "Argentina", "away_team": "Switzerland",
             "home_score": 3, "away_score": 1, "predictable": 1},
            {"match_number": 101, "home_team": "To be announced",
             "away_team": "To be announced", "home_score": None, "away_score": None,
             "predictable": 0},
        ]
        live = [
            {"match_number": 100, "home_team": "Argentina", "away_team": "Switzerland",
             "home_score": None, "away_score": None, "predictable": 1},
            {"match_number": 101, "home_team": "France", "away_team": "Spain",
             "home_score": None, "away_score": None, "predictable": 1,
             "data_source": "live_fixture_feed"},
        ]

        merged = merge_fixture_snapshots(cached, live)

        by_number = {f["match_number"]: f for f in merged}
        self.assertEqual(by_number[100]["home_score"], 3)
        self.assertEqual(by_number[100]["away_score"], 1)
        self.assertEqual(by_number[101]["home_team"], "France")
        self.assertEqual(by_number[101]["away_team"], "Spain")
        self.assertEqual(by_number[101]["predictable"], 1)

    @patch("wc2026.models.predictor.get_model",
           return_value=SimpleNamespace(teams=["France", "Spain"]))
    @patch("wc2026.data.sources.fixtures_2026.requests.get")
    def test_live_snapshot_retries_a_transient_connection_failure(self, get, _model):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = [{
            "MatchNumber": 101, "RoundNumber": 7,
            "DateUtc": "2026-07-14 19:00:00Z",
            "HomeTeam": "France", "AwayTeam": "Spain",
            "Group": None, "Location": "New York/New Jersey Stadium",
            "HomeTeamScore": None, "AwayTeamScore": None,
        }]
        get.side_effect = [requests.exceptions.SSLError("transient"), response]

        fixtures = fetch_fixture_snapshot(timeout=1)

        self.assertEqual(get.call_count, 2)
        self.assertEqual(fixtures[0]["home_team"], "France")


if __name__ == "__main__":
    unittest.main()
