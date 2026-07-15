import sqlite3
import tempfile
import unittest
from pathlib import Path

from wc2026.data import results as R


def _db():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE fixtures (match_number INTEGER PRIMARY KEY, predictable INTEGER, "
              "home_team TEXT, away_team TEXT, date_utc TEXT, home_score INTEGER, away_score INTEGER)")
    c.execute("CREATE TABLE matches (date TEXT, home_team TEXT, away_team TEXT, "
              "home_score INTEGER, away_score INTEGER, tournament TEXT)")
    return c


class ResultsTest(unittest.TestCase):
    def test_regulation_score_requires_verified_knockout_score(self):
        aet = {"round_number": 4, "home_score": 3, "away_score": 2,
               "result_status": "AET", "regulation_home_score": 1,
               "regulation_away_score": 1}
        unknown = {"round_number": 4, "home_score": 3, "away_score": 2}

        self.assertEqual(R.regulation_score(aet), (1, 1))
        self.assertIsNone(R.regulation_score(unknown))

    def test_backfill_matches_by_team_and_date(self):
        c = _db()
        c.execute("INSERT INTO fixtures VALUES (1,1,'Mexico','South Africa','2026-06-11 19:00:00Z',NULL,NULL)")
        c.execute("INSERT INTO fixtures VALUES (2,1,'Spain','Brazil','2026-07-01 19:00:00Z',NULL,NULL)")  # 无赛果
        c.execute("INSERT INTO matches VALUES ('2026-06-11','Mexico','South Africa',2,0,'FIFA World Cup')")
        n = R.backfill_fixture_scores(conn=c)
        self.assertEqual(n, 1)
        row = c.execute("SELECT home_score, away_score FROM fixtures WHERE match_number=1").fetchone()
        self.assertEqual((row["home_score"], row["away_score"]), (2, 0))
        self.assertIsNone(c.execute("SELECT home_score FROM fixtures WHERE match_number=2").fetchone()["home_score"])

    def test_backfill_respects_date_window(self):
        c = _db()
        c.execute("INSERT INTO fixtures VALUES (1,1,'A','B','2026-06-11 19:00:00Z',NULL,NULL)")
        c.execute("INSERT INTO matches VALUES ('2026-05-01','A','B',3,3,'Friendly')")  # 日期太远
        self.assertEqual(R.backfill_fixture_scores(conn=c), 0)

    def test_export_and_load_roundtrip(self):
        c = _db()
        c.execute("INSERT INTO fixtures VALUES (7,1,'A','B','2026-06-11 19:00:00Z',3,1)")
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "wc_results.json"
            self.assertEqual(R.export_results_json(path=p, conn=c), 1)
            self.assertEqual(R.load_results_overlay(path=p), {7: (3, 1)})

    def test_export_preserves_regulation_metadata(self):
        c = _db()
        for name, decl in (
            ("regulation_home_score", "INTEGER"), ("regulation_away_score", "INTEGER"),
            ("final_home_score", "INTEGER"), ("final_away_score", "INTEGER"),
            ("penalty_home_score", "INTEGER"), ("penalty_away_score", "INTEGER"),
            ("result_status", "TEXT"), ("winner_team", "TEXT"),
            ("result_source", "TEXT"), ("source_event_id", "TEXT"),
            ("result_fetched_at", "TEXT"), ("event_flags", "TEXT"),
        ):
            c.execute(f"ALTER TABLE fixtures ADD COLUMN {name} {decl}")
        c.execute(
            "INSERT INTO fixtures (match_number,predictable,home_team,away_team,date_utc,home_score,away_score,"
            "regulation_home_score,regulation_away_score,final_home_score,final_away_score,result_status,"
            "result_source,source_event_id,event_flags) VALUES (86,1,'Argentina','Cape Verde',"
            "'2026-07-03 22:00:00Z',3,2,1,1,3,2,'AET','ESPN','760500','[\"extra_time\"]')"
        )
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "wc_results.json"
            R.export_results_json(path=p, conn=c)
            row = R.load_results_overlay(path=p)[86]

        self.assertEqual(row["regulation_home_score"], 1)
        self.assertEqual(row["result_status"], "AET")
        self.assertEqual(row["source_event_id"], "760500")

    def test_load_missing_file(self):
        self.assertEqual(R.load_results_overlay(path=Path("/nonexistent/x.json")), {})

    def test_apply_results_overlay_fills_only_missing_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "wc_results.json"
            p.write_text('{"results":{"7":[3,1],"8":[2,0],"9":[5,4]}}', encoding="utf-8")

            rows = [
                {"match_number": 7, "home_score": None, "away_score": None},
                {"match_number": 8, "home_score": 1, "away_score": 1},
                {"match_number": 9, "predictable": 0, "home_score": None, "away_score": None},
            ]

            self.assertEqual(
                R.apply_results_overlay(rows, path=p),
                [
                    {"match_number": 7, "home_score": 3, "away_score": 1},
                    {"match_number": 8, "home_score": 1, "away_score": 1},
                    {"match_number": 9, "predictable": 0, "home_score": None, "away_score": None},
                ],
            )

    def test_load_and_apply_metadata_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "wc_results.json"
            p.write_text(
                '{"results":{"86":{"home_score":3,"away_score":2,'
                '"regulation_home_score":1,"regulation_away_score":1,'
                '"result_status":"AET","result_source":"ESPN"}}}',
                encoding="utf-8",
            )

            overlay = R.load_results_overlay(path=p)
            rows = R.apply_results_overlay([{
                "match_number": 86, "predictable": 1,
                "home_score": None, "away_score": None,
            }], path=p)

        self.assertEqual(overlay[86]["result_status"], "AET")
        self.assertEqual(rows[0]["home_score"], 3)
        self.assertEqual(rows[0]["regulation_home_score"], 1)
        self.assertEqual(rows[0]["result_source"], "ESPN")


if __name__ == "__main__":
    unittest.main()
