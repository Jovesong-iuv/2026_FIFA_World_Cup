import sqlite3
import unittest

from wc2026.data import bets as B


def _mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE bets (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, match TEXT, "
              "market TEXT, selection TEXT, odds REAL, stake REAL, status TEXT DEFAULT 'pending', "
              "note TEXT, close_odds REAL)")
    return c


class PnlSummaryTest(unittest.TestCase):
    def test_pnl_of(self):
        self.assertAlmostEqual(B.pnl_of({"status": "won", "odds": 2.5, "stake": 100}), 150.0)
        self.assertAlmostEqual(B.pnl_of({"status": "lost", "odds": 2.5, "stake": 100}), -100.0)
        self.assertAlmostEqual(B.pnl_of({"status": "push", "odds": 2.5, "stake": 100}), 0.0)
        self.assertAlmostEqual(B.pnl_of({"status": "pending", "odds": 2.5, "stake": 100}), 0.0)

    def test_summary_roi_winrate(self):
        bets = [
            {"status": "won", "odds": 2.0, "stake": 100},   # +100
            {"status": "lost", "odds": 3.0, "stake": 100},  # -100
            {"status": "won", "odds": 1.5, "stake": 100},   # +50
            {"status": "push", "odds": 2.0, "stake": 100},  # 0（不计胜率）
            {"status": "pending", "odds": 2.0, "stake": 100},
        ]
        s = B.summary(bets)
        self.assertEqual(s["settled"], 4)
        self.assertEqual(s["pending"], 1)
        self.assertAlmostEqual(s["profit"], 50.0)
        self.assertAlmostEqual(s["staked"], 400.0)
        self.assertAlmostEqual(s["roi"], 50.0 / 400.0)
        self.assertEqual(s["wins"], 2)
        self.assertAlmostEqual(s["win_rate"], 2 / 3)   # 3 decided (won/lost), push 排除

    def test_max_drawdown(self):
        bets = [
            {"status": "won", "odds": 2.0, "stake": 100},   # run +100 peak100
            {"status": "lost", "odds": 2.0, "stake": 100},  # run 0  (dd 100)
            {"status": "lost", "odds": 2.0, "stake": 100},  # run -100 (dd 200)
            {"status": "won", "odds": 3.0, "stake": 100},   # run +100
        ]
        s = B.summary(bets)
        self.assertAlmostEqual(s["max_drawdown"], 200.0)
        self.assertEqual(s["curve"], [100.0, 0.0, -100.0, 100.0])

    def test_empty(self):
        s = B.summary([])
        self.assertEqual(s["roi"], 0.0)
        self.assertEqual(s["curve"], [])

    def test_clv_metrics(self):
        bets = [
            {"status": "won", "odds": 2.10, "stake": 100, "close_odds": 2.00},   # 击败收盘 (+5%)
            {"status": "lost", "odds": 1.90, "stake": 100, "close_odds": 2.00},  # 未击败 (-5%)
            {"status": "pending", "odds": 3.0, "stake": 100, "close_odds": None},  # 无收盘 → 不计
        ]
        s = B.summary(bets)
        self.assertEqual(s["clv_count"], 2)
        self.assertAlmostEqual(s["beat_close_rate"], 0.5)
        self.assertAlmostEqual(s["avg_clv"], ((2.10/2.00 - 1) + (1.90/2.00 - 1)) / 2, places=6)

    def test_db_set_close(self):
        c = _mem()
        B.add_bet("A vs B", "胜平负", "主胜", 2.1, 100, conn=c)
        bid = B.list_bets(conn=c)[0]["id"]
        B.set_close(bid, 1.95, conn=c)
        self.assertAlmostEqual(B.list_bets(conn=c)[0]["close_odds"], 1.95)
        B.set_close(bid, 0.5, conn=c)  # <=1 → 清空
        self.assertIsNone(B.list_bets(conn=c)[0]["close_odds"])

    def test_db_roundtrip(self):
        c = _mem()
        B.add_bet("墨西哥 vs 南非", "胜平负", "主胜", 2.1, 100, "测试", conn=c)
        rows = B.list_bets(conn=c)
        self.assertEqual(len(rows), 1)
        bid = rows[0]["id"]
        B.set_status(bid, "won", conn=c)
        self.assertEqual(B.list_bets(conn=c)[0]["status"], "won")
        B.delete_bet(bid, conn=c)
        self.assertEqual(B.list_bets(conn=c), [])


if __name__ == "__main__":
    unittest.main()
