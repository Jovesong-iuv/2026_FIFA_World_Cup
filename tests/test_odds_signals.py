import sqlite3
import unittest

from wc2026.data import odds_history as oh
from wc2026.markets import odds_signals as OS


def _mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE odds_snapshots (captured_at TEXT, home_team TEXT, away_team TEXT, "
              "market TEXT, selection TEXT, line TEXT, odds REAL)")
    return c


def _two(c, home, away, ev1, ev2):
    oh.record_event_snapshot(home, away, ev1, captured_at="2026-06-01T00:00:00", conn=c)
    oh.record_event_snapshot(home, away, ev2, captured_at="2026-06-02T00:00:00", conn=c)


class TrendTest(unittest.TestCase):
    def test_needs_two_valid_points(self):
        self.assertIsNone(OS._trend([("t", 2.0)]))
        self.assertIsNone(OS._trend([]))
        self.assertIsNone(OS._trend([("t", 1.0), ("t2", 0)]))   # 无效赔率被过滤
        r = OS._trend([("t1", 2.0), ("t2", 1.8)])
        self.assertAlmostEqual(r[2], -0.1, places=3)


class SignalTest(unittest.TestCase):
    def test_no_snapshot_degrades(self):
        r = OS.detect_odds_signals("A", "B", conn=_mem())
        self.assertFalse(r["enabled"])

    def test_draw_drop_signal(self):
        c = _mem()
        _two(c, "A", "B", {"h2h": {"home": 2.0, "draw": 3.6, "away": 3.8}},
             {"h2h": {"home": 2.0, "draw": 3.2, "away": 3.8}})       # 平局 -11%
        r = OS.detect_odds_signals("A", "B", conn=c)
        self.assertTrue(r["enabled"])
        self.assertTrue(any(s["tag"] == "平局降赔" for s in r["signals"]))

    def test_over_overheat_signal(self):
        c = _mem()
        _two(c, "A", "B", {"totals": {"2.5": {"over": 2.00, "under": 1.80}}},
             {"totals": {"2.5": {"over": 1.75, "under": 1.80}}})     # 大球 -12.5%
        r = OS.detect_odds_signals("A", "B", conn=c)
        self.assertTrue(any("大球过热" in s["tag"] for s in r["signals"]))

    def test_spread_water_rise_signal(self):
        c = _mem()
        _two(c, "A", "B", {"spreads": {"-1.5": {"home": 1.90, "away": 1.90}}},
             {"spreads": {"-1.5": {"home": 2.05, "away": 1.75}}})    # 让球方水位 +7.9%
        r = OS.detect_odds_signals("A", "B", conn=c)
        self.assertTrue(any("深盘水位升高" in s["tag"] for s in r["signals"]))

    def test_stable_no_signal(self):
        c = _mem()
        _two(c, "A", "B", {"h2h": {"home": 2.0, "draw": 3.4, "away": 3.6}},
             {"h2h": {"home": 2.0, "draw": 3.4, "away": 3.6}})
        r = OS.detect_odds_signals("A", "B", conn=c)
        self.assertTrue(r["enabled"])
        self.assertEqual(r["signals"], [])


if __name__ == "__main__":
    unittest.main()
