import sqlite3
import unittest

from wc2026.data import access_log as al


def _mem():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE ip_access (ip TEXT PRIMARY KEY, note TEXT, first_seen TEXT, "
              "last_seen TEXT, visits INTEGER DEFAULT 0, user_agent TEXT)")
    return c


class AccessLogTest(unittest.TestCase):
    def test_first_visit_inserts(self):
        c = _mem()
        al.record_visit("1.2.3.4", "UA-x", conn=c)
        rows = al.list_access(conn=c)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ip"], "1.2.3.4")
        self.assertEqual(rows[0]["visits"], 1)
        self.assertIsNone(rows[0]["note"])

    def test_revisit_increments_and_keeps_note(self):
        c = _mem()
        al.record_visit("1.2.3.4", conn=c)
        al.set_note("1.2.3.4", "老王", conn=c)
        al.record_visit("1.2.3.4", conn=c)          # 再次访问
        al.record_visit("1.2.3.4", conn=c)
        row = al.list_access(conn=c)[0]
        self.assertEqual(row["visits"], 3)
        self.assertEqual(row["note"], "老王")       # 备注被保留(auto-match)

    def test_set_note_updates(self):
        c = _mem()
        al.record_visit("9.9.9.9", conn=c)
        al.set_note("9.9.9.9", "测试", conn=c)
        self.assertEqual(al.list_access(conn=c)[0]["note"], "测试")

    def test_empty_ip_ignored(self):
        c = _mem()
        al.record_visit("", conn=c)
        self.assertEqual(al.list_access(conn=c), [])

    def test_multiple_ips_ordered_by_last_seen(self):
        c = _mem()
        al.record_visit("1.1.1.1", conn=c)
        al.record_visit("2.2.2.2", conn=c)
        ips = [r["ip"] for r in al.list_access(conn=c)]
        self.assertEqual(set(ips), {"1.1.1.1", "2.2.2.2"})


if __name__ == "__main__":
    unittest.main()
