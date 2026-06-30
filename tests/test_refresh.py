import unittest
from types import SimpleNamespace
from unittest.mock import patch

from wc2026.refresh import resilient_refresh


class ResilientRefreshTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
