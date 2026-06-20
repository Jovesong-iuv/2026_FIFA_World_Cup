import unittest

from wc2026.analysis.motivation import (derive_group_states, group_state_for,
                                        status_note)


def _group(teams, scored):
    """scored: {(hi,ai): (hs,as_)}，缺失为未赛。"""
    matches = []
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            hs, as_ = scored.get((i, j), (None, None))
            matches.append((i, j, hs, as_))
    return {"G": {"teams": list(teams), "matches": matches}}


class MotivationTest(unittest.TestCase):
    def test_pre_final_round_all_alive(self):
        teams = ["A", "B", "C", "D"]
        states = derive_group_states(_group(teams, {(0, 1): (1, 0)}))["G"]
        self.assertTrue(all(v == "alive" for v in states.values()))

    def test_qualified_and_eliminated(self):
        # 已踢 4 场，剩 (A vs D)、(B vs C)：A 锁定出线，D 已出局
        teams = ["A", "B", "C", "D"]
        scored = {(0, 1): (1, 0), (0, 2): (1, 0),   # A 全胜 → 6 分
                  (1, 3): (5, 0), (2, 3): (5, 0)}    # B、C 各胜 D；D 0 分且净胜球极差
        states = derive_group_states(_group(teams, scored))["G"]
        self.assertEqual(states["A"], "qualified")
        self.assertEqual(states["D"], "eliminated")

    def test_must_win(self):
        # A 赢则前二、平/负则可能被挤出 → 生死战
        teams = ["A", "B", "C", "D"]
        scored = {(0, 1): (2, 0), (0, 2): (0, 1),   # A 胜 B、负 C
                  (1, 3): (1, 0), (2, 3): (1, 0)}    # B 胜 D、C 胜 D
        states = derive_group_states(_group(teams, scored))["G"]
        self.assertEqual(states["A"], "must_win")

    def test_group_state_for_and_note(self):
        teams = ["A", "B", "C", "D"]
        scored = {(0, 1): (1, 0), (0, 2): (1, 0), (1, 3): (5, 0), (2, 3): (5, 0)}
        states = derive_group_states(_group(teams, scored))
        gs = group_state_for(states, "G", "A", "D")
        self.assertEqual(gs["home"]["status"], "qualified")
        self.assertEqual(gs["away"]["status"], "eliminated")
        note = status_note(states, "G", "A", "D")
        self.assertIn("已出线", note)
        self.assertIn("已出局", note)


if __name__ == "__main__":
    unittest.main()
