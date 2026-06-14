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

    def test_load_missing_file(self):
        self.assertEqual(R.load_results_overlay(path=Path("/nonexistent/x.json")), {})


if __name__ == "__main__":
    unittest.main()
