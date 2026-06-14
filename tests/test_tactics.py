import unittest

from wc2026.analysis.tactics import formation_lean, parse_formation, tactical_read


class TacticsTest(unittest.TestCase):
    def test_parse_valid_and_invalid(self):
        self.assertEqual(parse_formation("4-2-3-1"), [4, 2, 3, 1])
        self.assertEqual(parse_formation("5-4-1"), [5, 4, 1])
        self.assertEqual(parse_formation("4-4-3"), [])   # 和=11，非法
        self.assertEqual(parse_formation(""), [])
        self.assertEqual(parse_formation(None), [])

    def test_lean_classification(self):
        self.assertEqual(formation_lean("5-4-1")["lean"], "防守")   # 5 后卫
        self.assertEqual(formation_lean("4-5-1")["lean"], "防守")   # 单前锋
        self.assertEqual(formation_lean("4-3-3")["lean"], "进攻")   # 3 前锋
        self.assertEqual(formation_lean("4-4-2")["lean"], "均衡")
        self.assertEqual(formation_lean("x")["lean"], "未知")

    def test_both_defensive_goals_low(self):
        r = tactical_read("A", "B", "5-4-1", "5-3-2")
        self.assertEqual(r["goals_hint"], "偏少")

    def test_both_attacking_goals_high(self):
        r = tactical_read("A", "B", "4-3-3", "4-3-3")
        self.assertEqual(r["goals_hint"], "偏多")

    def test_mixed_mentions_counter(self):
        r = tactical_read("A", "B", "4-3-3", "5-4-1")
        self.assertTrue(any("反击" in n for n in r["notes"]))

    def test_gk_advantage_note(self):
        r = tactical_read("A", "B", "4-4-2", "4-4-2", gk_home=7.4, gk_away=6.8)
        self.assertTrue(any("门将" in n and "A" in n for n in r["notes"]))

    def test_missing_ratings_note(self):
        r = tactical_read("A", "B", "4-4-2", "4-4-2")
        self.assertTrue(any("评分暂缺" in n for n in r["notes"]))


if __name__ == "__main__":
    unittest.main()
