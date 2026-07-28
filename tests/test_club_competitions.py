import ast
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from wc2026.data.sources import club_competitions as club


def _event(event_id="42"):
    return {
        "id": event_id,
        "date": "2026-07-28T19:00Z",
        "season": {"slug": "second-round"},
        "competitions": [{
            "status": {"type": {
                "state": "post", "completed": True, "shortDetail": "FT",
            }},
            "venue": {
                "fullName": "Arena",
                "address": {"city": "São Paulo"},
            },
            "competitors": [
                {
                    "homeAway": "away",
                    "score": "1",
                    "team": {"id": "2", "displayName": "Away FC", "logo": "away.png"},
                },
                {
                    "homeAway": "home",
                    "score": "2",
                    "winner": True,
                    "records": [{"type": "total", "summary": "8-2-1"}],
                    "team": {"id": "1", "displayName": "Home FC", "logo": "home.png"},
                },
            ],
        }],
    }


class ClubCompetitionsTest(unittest.TestCase):
    def test_top_level_competition_order_moves_world_cup_after_club_sections(self):
        app_path = Path(__file__).resolve().parents[1] / "web" / "app.py"
        tree = ast.parse(app_path.read_text(encoding="utf-8"))
        values = {
            node.targets[0].id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in {"COMPETITION_OPTIONS", "WORLD_CUP_PAGE_OPTIONS"}
        }

        self.assertEqual(values["COMPETITION_OPTIONS"], ["巴甲", "欧冠", "世界杯"])
        self.assertEqual(values["WORLD_CUP_PAGE_OPTIONS"][0], "首页")
        self.assertIn("单场分析", values["WORLD_CUP_PAGE_OPTIONS"])

    def test_parse_event_uses_home_away_markers(self):
        row = club.parse_scoreboard_event(_event(), "Brazilian Serie A")

        self.assertEqual(row["home"]["name"], "Home FC")
        self.assertEqual(row["away"]["name"], "Away FC")
        self.assertEqual(row["home"]["score"], "2")
        self.assertEqual(row["status"], "FT")
        self.assertEqual(row["stage"], "Second Round")
        self.assertEqual(row["city"], "São Paulo")

    def test_incomplete_post_state_is_classified_as_other(self):
        event = _event()
        event["competitions"][0]["status"]["type"].update({
            "completed": False,
            "shortDetail": "Postponed",
        })

        row = club.parse_scoreboard_event(event)

        self.assertEqual(row["state"], "other")
        self.assertFalse(row["completed"])

    @patch("wc2026.data.sources.club_competitions.requests.get")
    def test_champions_league_merges_main_and_qualifying_without_duplicates(self, get):
        main = Mock()
        main.raise_for_status.return_value = None
        main.json.return_value = {
            "leagues": [{"name": "UEFA Champions League",
                         "season": {"displayName": "2026-27 UEFA Champions League"}}],
            "events": [_event("42")],
        }
        qualifying = Mock()
        qualifying.raise_for_status.return_value = None
        qualifying.json.return_value = {
            "leagues": [{"name": "UEFA Champions League Qualifying",
                         "season": {"displayName": "2026-27 Qualifying"}}],
            "events": [_event("42"), _event("43")],
        }
        get.side_effect = [main, qualifying]

        result = club.fetch_competition_events(
            "champions_league", reference_date=date(2026, 7, 28)
        )

        self.assertEqual([row["id"] for row in result["events"]], ["42", "43"])
        self.assertEqual(result["date_range"], "20260718-20260811")
        self.assertEqual(len(result["seasons"]), 2)
        self.assertEqual(get.call_count, 2)

    @patch("wc2026.data.sources.club_competitions.requests.get")
    def test_endpoint_without_events_does_not_add_stale_season(self, get):
        empty = Mock()
        empty.raise_for_status.return_value = None
        empty.json.return_value = {
            "leagues": [{"season": {"displayName": "2025-26 UEFA Champions League"}}],
            "events": [],
        }
        qualifying = Mock()
        qualifying.raise_for_status.return_value = None
        qualifying.json.return_value = {
            "leagues": [{"season": {"displayName": "2026-27 Qualifying"}}],
            "events": [_event()],
        }
        get.side_effect = [empty, qualifying]

        result = club.fetch_competition_events("champions_league")

        self.assertEqual(result["seasons"], ["2026-27 Qualifying"])

    def test_unknown_competition_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported club competition"):
            club.fetch_competition_events("premier_league")


if __name__ == "__main__":
    unittest.main()
