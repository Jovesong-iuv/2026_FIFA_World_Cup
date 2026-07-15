import unittest
import sqlite3
from unittest.mock import patch

from wc2026.data.sources import espn
from wc2026.data.sources.fixtures_2026 import _REBUILD


def _competitor(side, team, score, periods):
    return {
        "homeAway": side,
        "team": {"displayName": team},
        "score": str(score),
        "linescores": [{"displayValue": str(v)} for v in periods],
    }


def _summary(status, home, away, *, shootout=None, details=None, stats=None):
    return {
        "header": {"competitions": [{
            "status": {"type": {"name": status}},
            "competitors": [home, away],
            "details": details or [],
        }]},
        "shootout": shootout or [],
        "boxscore": {"teams": stats or []},
    }


class EspnSummaryParserTest(unittest.TestCase):
    def test_aet_without_period_scores_does_not_leak_final_score_into_regulation(self):
        payload = _summary(
            "STATUS_FINAL_AET",
            _competitor("home", "Argentina", 3, []),
            _competitor("away", "Cape Verde", 2, []),
        )

        result = espn.parse_summary(payload)

        self.assertIsNone(result["regulation_home_score"])
        self.assertIsNone(result["regulation_away_score"])
        self.assertEqual((result["final_home_score"], result["final_away_score"]), (3, 2))

    def test_aet_keeps_regulation_and_final_scores_separate(self):
        payload = _summary(
            "STATUS_FINAL_AET",
            _competitor("home", "Argentina", 3, [1, 0, 1, 1]),
            _competitor("away", "Cape Verde", 2, [0, 1, 1, 0]),
            details=[{"ownGoal": True, "clock": {"displayValue": "111'"},
                      "team": {"displayName": "Argentina"}}],
        )

        result = espn.parse_summary(payload)

        self.assertEqual(result["regulation_home_score"], 1)
        self.assertEqual(result["regulation_away_score"], 1)
        self.assertEqual(result["final_home_score"], 3)
        self.assertEqual(result["final_away_score"], 2)
        self.assertEqual(result["result_status"], "AET")
        self.assertIn("extra_time", result["event_flags"])
        self.assertIn("own_goal", result["event_flags"])

    def test_penalty_shootout_goals_are_not_match_goals(self):
        payload = _summary(
            "STATUS_FINAL_PEN",
            _competitor("home", "Germany", 1, [0, 1, 0, 0, 3]),
            _competitor("away", "Paraguay", 1, [1, 0, 0, 0, 4]),
            shootout=[
                {"team": "Germany", "shots": [{"didScore": True}, {"didScore": True}, {"didScore": True}]},
                {"team": "Paraguay", "shots": [{"didScore": True}] * 4},
            ],
        )

        result = espn.parse_summary(payload)

        self.assertEqual((result["regulation_home_score"], result["regulation_away_score"]), (1, 1))
        self.assertEqual((result["final_home_score"], result["final_away_score"]), (1, 1))
        self.assertEqual((result["penalty_home_score"], result["penalty_away_score"]), (3, 4))
        self.assertEqual(result["result_status"], "PEN")
        self.assertIn("penalty_shootout", result["event_flags"])

    def test_ft_extracts_single_match_statistics(self):
        stats = [
            {"team": {"displayName": "France"}, "statistics": [
                {"name": "possessionPct", "displayValue": "61.2"},
                {"name": "totalShots", "displayValue": "14"},
                {"name": "shotsOnTarget", "displayValue": "6"},
            ]},
            {"team": {"displayName": "Morocco"}, "statistics": [
                {"name": "possessionPct", "displayValue": "38.8"},
                {"name": "totalShots", "displayValue": "8"},
                {"name": "shotsOnTarget", "displayValue": "2"},
            ]},
        ]
        payload = _summary(
            "STATUS_FULL_TIME",
            _competitor("home", "France", 2, [1, 1]),
            _competitor("away", "Morocco", 0, [0, 0]),
            stats=stats,
        )

        result = espn.parse_summary(payload)

        self.assertEqual(result["result_status"], "FT")
        self.assertEqual(result["match_stats"]["France"]["shots"], 14)
        self.assertEqual(result["match_stats"]["France"]["shots_on_target"], 6)
        self.assertEqual(result["match_stats"]["Morocco"]["possession"], 0.388)


class EspnScoreboardMatchTest(unittest.TestCase):
    def test_scoreboard_dates_cover_utc_boundary(self):
        self.assertEqual(
            espn.scoreboard_dates("2026-07-07T00:00:00Z"),
            ["20260706", "20260707", "20260708"],
        )

    def test_matches_event_by_normalized_teams_and_kickoff(self):
        events = [{
            "id": "760505",
            "date": "2026-07-06T00:00Z",
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "USA"}},
                {"homeAway": "away", "team": {"displayName": "Belgium"}},
            ]}],
        }]
        fixture = {
            "home_team": "United States", "away_team": "Belgium",
            "date_utc": "2026-07-06 00:00:00Z",
        }

        event = espn.match_scoreboard_event(events, fixture)

        self.assertEqual(event["id"], "760505")

    def test_matches_espn_bosnia_hyphen_alias(self):
        events = [{
            "id": "760494", "date": "2026-07-02T00:00Z",
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "United States"}},
                {"homeAway": "away", "team": {"displayName": "Bosnia-Herzegovina"}},
            ]}],
        }]
        fixture = {"home_team": "United States", "away_team": "Bosnia and Herzegovina",
                   "date_utc": "2026-07-02 00:00:00Z"}

        self.assertEqual(espn.match_scoreboard_event(events, fixture)["id"], "760494")

    def test_rejects_ambiguous_or_time_mismatched_event(self):
        event = {
            "id": "x", "date": "2026-07-07T08:00Z",
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "France"}},
                {"homeAway": "away", "team": {"displayName": "Spain"}},
            ]}],
        }
        fixture = {"home_team": "France", "away_team": "Spain",
                   "date_utc": "2026-07-06 00:00:00Z"}

        self.assertIsNone(espn.match_scoreboard_event([event], fixture))


class EspnRefreshTest(unittest.TestCase):
    def test_retries_espn_aet_result_when_regulation_score_was_initially_missing(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript(_REBUILD)
        conn.execute(
            "INSERT INTO fixtures (match_number,round_number,date_utc,home_team,away_team,"
            "predictable,home_score,away_score,final_home_score,final_away_score,result_status,"
            "result_source,source_event_id) VALUES "
            "(80,4,'2020-07-04 00:00:00Z','Argentina','Cape Verde',1,3,2,3,2,'AET','ESPN','old')"
        )
        event = {
            "id": "760500", "date": "2020-07-04T00:00:00Z",
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": "Argentina"}},
                {"homeAway": "away", "team": {"displayName": "Cape Verde"}},
            ]}],
        }
        payload = _summary(
            "STATUS_FINAL_AET",
            _competitor("home", "Argentina", 3, [1, 0, 1, 1]),
            _competitor("away", "Cape Verde", 2, [0, 1, 1, 0]),
        )

        with patch("wc2026.data.sources.espn.fetch_scoreboard", return_value=[event]), \
                patch("wc2026.data.sources.espn.fetch_summary", return_value=payload):
            result = espn.refresh_fixture_results(conn=conn)

        row = conn.execute(
            "SELECT regulation_home_score,regulation_away_score,source_event_id "
            "FROM fixtures WHERE match_number=80"
        ).fetchone()
        self.assertEqual(result["updated"], 1)
        self.assertEqual((row["regulation_home_score"], row["regulation_away_score"]), (1, 1))
        self.assertEqual(row["source_event_id"], "760500")
        conn.close()


if __name__ == "__main__":
    unittest.main()
