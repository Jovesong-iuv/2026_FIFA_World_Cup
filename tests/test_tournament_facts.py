import tempfile
import unittest
from pathlib import Path

from wc2026.analysis import tournament_facts as TF


class TournamentFactsTest(unittest.TestCase):
    def test_player_leaderboard_sums_goals_and_special_tags(self):
        data = {
            "player_events": [
                {"player": "Tielemans", "team": "Belgium", "event": "goal", "minute": 89},
                {"player": "Tielemans", "team": "Belgium", "event": "goal", "minute": 118, "detail": "pen"},
                {"player": "Pulisic", "team": "United States", "event": "goal", "minute": 67, "detail": "FK"},
            ]
        }

        board = TF.player_leaderboard(data)

        self.assertEqual(board[0]["player"], "Tielemans")
        self.assertEqual(board[0]["goals"], 2)
        self.assertEqual(board[0]["penalty_goals"], 1)
        self.assertEqual(board[1]["free_kick_goals"], 1)

    def test_team_summary_combines_record_process_stats_and_players(self):
        data = {
            "team_records": {"Belgium": {"played": 4, "w": 2, "d": 2, "l": 0, "gf": 9, "ga": 4}},
            "team_process": {"Belgium": {"matches": 1, "shots_for": 16, "shots_against": 12,
                                          "possession_for": 57}},
            "player_events": [
                {"player": "Tielemans", "team": "Belgium", "event": "goal", "minute": 89},
                {"player": "Tielemans", "team": "Belgium", "event": "mom", "minute": None},
            ],
        }

        summary = TF.team_summary("Belgium", data)

        self.assertEqual(summary["record"]["played"], 4)
        self.assertEqual(summary["process"]["avg_shots_for"], 16)
        self.assertEqual(summary["top_scorers"][0]["player"], "Tielemans")
        self.assertEqual(summary["mom"][0]["player"], "Tielemans")

    def test_match_facts_and_compare_teams(self):
        data = {
            "matches": [
                {"match_number": 82, "home_team": "Belgium", "away_team": "Senegal",
                 "score": "3-2", "stage": "round_of_32"}
            ],
            "team_records": {
                "Belgium": {"played": 4, "gf": 9, "ga": 4},
                "Senegal": {"played": 4, "gf": 10, "ga": 9},
            },
            "team_process": {
                "Belgium": {"matches": 1, "shots_for": 16, "shots_against": 12},
                "Senegal": {"matches": 1, "shots_for": 12, "shots_against": 16},
            },
            "player_events": [],
        }

        self.assertEqual(TF.match_facts(82, data)["score"], "3-2")
        comp = TF.compare_teams("Belgium", "Senegal", data)
        self.assertEqual(comp["home"]["team"], "Belgium")
        self.assertEqual(comp["away"]["record"]["gf"], 10)

    def test_load_facts_missing_file_degrades_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(TF.load_facts(Path(tmp) / "missing.json"), TF.empty_facts())


if __name__ == "__main__":
    unittest.main()
