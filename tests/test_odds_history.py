import sqlite3
import unittest

from wc2026.data import odds_history as oh


def _mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE odds_snapshots (captured_at TEXT, home_team TEXT, away_team TEXT, "
        "market TEXT, selection TEXT, line TEXT, odds REAL)")
    return conn


_EVENT = {
    "h2h": {"home": 2.10, "draw": 3.40, "away": 3.60},
    "spreads": {"-0.5": {"home": 1.95, "away": 1.95}, "0": {"home": 1.50, "away": 2.60}},
    "totals": {"2.5": {"over": 1.90, "under": 1.90}},
}


class FlattenTest(unittest.TestCase):
    def test_flatten_covers_all_markets(self):
        rows = oh.flatten_event_odds(_EVENT)
        markets = {m for (m, _s, _l, _o) in rows}
        self.assertEqual(markets, {"h2h", "spreads", "totals"})
        self.assertEqual(len(rows), 3 + 4 + 2)  # h2h3 + spreads(2线*2) + totals(1线*2)
        self.assertIn(("h2h", "home", None, 2.10), rows)
        self.assertIn(("totals", "over", "2.5", 1.90), rows)

    def test_flatten_skips_invalid_odds(self):
        rows = oh.flatten_event_odds({"h2h": {"home": 0.0, "draw": 1.0, "away": 2.0}})
        self.assertEqual(rows, [("h2h", "away", None, 2.0)])  # 0 与 1.0 被过滤


class RecordLoadTest(unittest.TestCase):
    def test_record_then_load_h2h_series(self):
        conn = _mem_conn()
        oh.record_event_snapshot("Mexico", "Brazil", _EVENT, captured_at="2026-06-01T00:00:00", conn=conn)
        oh.record_event_snapshot("Mexico", "Brazil",
                                 {"h2h": {"home": 2.30, "draw": 3.30, "away": 3.20}},
                                 captured_at="2026-06-02T00:00:00", conn=conn)
        series = oh.load_history("Mexico", "Brazil", "h2h", conn=conn)
        self.assertEqual([o for _t, o in series["home"]], [2.10, 2.30])   # 升序
        self.assertEqual(len(series["draw"]), 2)

    def test_available_lines_and_line_filter(self):
        conn = _mem_conn()
        oh.record_event_snapshot("A", "B", _EVENT, captured_at="2026-06-01T00:00:00", conn=conn)
        self.assertEqual(oh.available_lines("A", "B", "spreads", conn=conn), ["-0.5", "0"])
        s = oh.load_history("A", "B", "totals", line="2.5", conn=conn)
        self.assertEqual(set(s), {"over", "under"})

    def test_record_empty_returns_zero(self):
        conn = _mem_conn()
        self.assertEqual(oh.record_event_snapshot("A", "B", {}, conn=conn), 0)


if __name__ == "__main__":
    unittest.main()
