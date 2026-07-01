import unittest
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from wc2026.refresh import _live_score_candidates, refresh_knockout_postmatch_insights, resilient_refresh


class ResilientRefreshTest(unittest.TestCase):
    def test_live_score_candidates_skip_recent_future_and_stale_matches(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE fixtures (match_number INTEGER PRIMARY KEY, predictable INTEGER, "
            "date_utc TEXT, home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER)"
        )
        conn.executemany(
            "INSERT INTO fixtures VALUES (?, 1, ?, ?, ?, NULL, NULL)",
            [
                (1, "2026-07-01 08:00:00Z", "A", "B"),
                (2, "2026-07-01 10:30:00Z", "C", "D"),
                (3, "2026-07-01 13:00:00Z", "E", "F"),
                (4, "2026-06-20 08:00:00Z", "G", "H"),
            ],
        )

        rows = _live_score_candidates(conn, limit=10, now_utc="2026-07-01 12:00:00Z",
                                      settle_hours=2, lookback_days=7)

        self.assertEqual([r["match_number"] for r in rows], [1])

    def test_live_score_candidates_respect_limit(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE fixtures (match_number INTEGER PRIMARY KEY, predictable INTEGER, "
            "date_utc TEXT, home_team TEXT, away_team TEXT, home_score INTEGER, away_score INTEGER)"
        )
        conn.executemany(
            "INSERT INTO fixtures VALUES (?, 1, '2026-07-01 01:00:00Z', ?, ?, NULL, NULL)",
            [(i, f"H{i}", f"A{i}") for i in range(1, 6)],
        )

        rows = _live_score_candidates(conn, limit=3, now_utc="2026-07-01 12:00:00Z", settle_hours=2)

        self.assertEqual([r["match_number"] for r in rows], [1, 2, 3])

    def test_refresh_continues_after_network_steps_fail(self):
        calls = []

        def ok(name, value=None):
            def inner(*_args, **_kwargs):
                calls.append(name)
                return value or {"ok": name}
            return inner

        def fail(name):
            def inner(*_args, **_kwargs):
                calls.append(name)
                raise RuntimeError(f"{name} down")
            return inner

        with patch("wc2026.refresh.ingest_international_results", fail("history")), \
                patch("wc2026.refresh.fetch_and_store_fixtures", fail("fixtures")), \
                patch("wc2026.refresh.backfill_fixture_scores", ok("backfill", 2)), \
                patch("wc2026.refresh.refresh_live_fixture_scores", ok("live_scores", {"updated": 0})), \
                patch("wc2026.refresh.export_results_json", ok("export", 2)), \
                patch("wc2026.refresh.train_and_save", ok("train", SimpleNamespace(teams=["A"]))), \
                patch("wc2026.refresh.refresh_knockout_postmatch_insights", ok("knockout_review", {"matches": 0})), \
                patch("wc2026.refresh.recompute", ok("adjustments", {"A": {}})):
            result = resilient_refresh()

        self.assertEqual(result["status"], "partial")
        self.assertEqual(calls, ["history", "fixtures", "backfill", "live_scores", "export", "train",
                                 "knockout_review", "adjustments"])
        self.assertFalse(result["steps"][0]["ok"])
        self.assertFalse(result["steps"][1]["ok"])
        self.assertTrue(result["steps"][2]["ok"])

    def test_refresh_skips_adjustments_when_training_failed_and_no_cached_model(self):
        with patch("wc2026.refresh.ingest_international_results", return_value={"new": 0}), \
                patch("wc2026.refresh.fetch_and_store_fixtures", return_value={"fixtures": 104}), \
                patch("wc2026.refresh.backfill_fixture_scores", return_value=0), \
                patch("wc2026.refresh.refresh_live_fixture_scores", return_value={"updated": 0}), \
                patch("wc2026.refresh.export_results_json", return_value=0), \
                patch("wc2026.refresh.train_and_save", side_effect=RuntimeError("train failed")), \
                patch("wc2026.refresh.refresh_knockout_postmatch_insights", return_value={"matches": 0}), \
                patch("wc2026.refresh.get_model", side_effect=RuntimeError("no cached model")):
            result = resilient_refresh()

        skipped = [s for s in result["steps"] if s["name"] == "adjustments"][0]
        self.assertFalse(skipped["ok"])
        self.assertIn("跳过", skipped["error"])

    def test_refresh_runs_knockout_postmatch_insights_before_adjustments(self):
        calls = []

        def mark(name, value):
            def inner(*_args, **_kwargs):
                calls.append(name)
                return value
            return inner

        with patch("wc2026.refresh.ingest_international_results", mark("history", {"new": 0})), \
                patch("wc2026.refresh.fetch_and_store_fixtures", mark("fixtures", {"fixtures": 104})), \
                patch("wc2026.refresh.backfill_fixture_scores", mark("backfill", 1)), \
                patch("wc2026.refresh.refresh_live_fixture_scores", mark("live_scores", {"updated": 0})), \
                patch("wc2026.refresh.export_results_json", mark("export", 1)), \
                patch("wc2026.refresh.train_and_save", mark("train", SimpleNamespace(teams=["A"]))), \
                patch("wc2026.refresh.refresh_knockout_postmatch_insights",
                      mark("knockout_review", {"matches": 2, "ok": 2, "failed": 0})), \
                patch("wc2026.refresh.recompute", mark("adjustments", {"A": {}})):
            result = resilient_refresh()

        self.assertEqual(calls[-2:], ["knockout_review", "adjustments"])
        step = [s for s in result["steps"] if s["name"] == "knockout_review"][0]
        self.assertTrue(step["ok"])
        self.assertEqual(step["result"]["matches"], 2)

    def test_knockout_review_skips_cached_matches(self):
        with TemporaryDirectory() as d:
            path = Path(d) / "match_insights.json"
            path.write_text(
                '{"matches":{"A::B":{"data_as_of":"2026-07-01"},"C::D":{}}}',
                encoding="utf-8",
            )

            with patch("wc2026.refresh._finished_knockout_fixtures", return_value=[
                    {"match_number": 1, "home_team": "A", "away_team": "B"},
                    {"match_number": 2, "home_team": "C", "away_team": "D"},
            ]), patch("wc2026.refresh.refresh_match_insight",
                      return_value={"ok": True}) as refresh:
                result = refresh_knockout_postmatch_insights(path=path)

        self.assertEqual(result["matches"], 2)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["processed"], 1)
        refresh.assert_called_once_with("C", "D", path=path)


if __name__ == "__main__":
    unittest.main()
