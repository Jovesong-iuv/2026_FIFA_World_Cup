import unittest

from wc2026.analysis.groups import compute_standings


def _gd(teams, scored):
    """构造单组 group_data。scored: {(hi,ai): (hs,as_)}，缺失为未赛。"""
    matches = []
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            hs, as_ = scored.get((i, j), (None, None))
            matches.append((i, j, hs, as_))
    return {"G": {"teams": list(teams), "matches": matches}}


class StandingsTest(unittest.TestCase):
    def test_all_wins_top(self):
        teams = ["A", "B", "C", "D"]
        res = compute_standings(_gd(teams, {(0, 1): (2, 0), (0, 2): (2, 0), (0, 3): (2, 0)}))["G"]
        self.assertEqual(res[0]["team"], "A")
        self.assertEqual(res[0]["pts"], 9)
        self.assertEqual(res[0]["played"], 3)
        self.assertEqual(res[0]["rank"], 1)

    def test_goal_difference_breaks_ties(self):
        teams = ["A", "B", "C", "D"]
        scored = {(0, 2): (5, 0), (0, 3): (5, 0), (1, 2): (1, 0), (1, 3): (1, 0)}
        res = {r["team"]: r for r in compute_standings(_gd(teams, scored))["G"]}
        self.assertEqual(res["A"]["pts"], res["B"]["pts"])
        self.assertLess(res["A"]["rank"], res["B"]["rank"])     # A 净胜球高 → 排前

    def test_head_to_head_breaks_equal_gd_gf(self):
        # A/B/C 全部 pts3 gd0；A、B 进球同为 2，用相互战绩(A 2-1 胜 B)分先后
        teams = ["A", "B", "C"]
        scored = {(0, 1): (2, 1), (0, 2): (0, 1), (1, 2): (1, 0)}
        res = {r["team"]: r for r in compute_standings(_gd(teams, scored))["G"]}
        self.assertEqual(res["A"]["pts"], res["B"]["pts"])
        self.assertEqual(res["A"]["gd"], res["B"]["gd"])
        self.assertEqual(res["A"]["gf"], res["B"]["gf"])
        self.assertLess(res["A"]["rank"], res["B"]["rank"])     # 相互战绩 A 胜 B

    def test_ranks_contiguous_and_unplayed_not_counted(self):
        res = compute_standings(_gd(["A", "B", "C", "D"], {(0, 1): (1, 0)}))["G"]
        self.assertEqual([r["rank"] for r in res], [1, 2, 3, 4])
        played = {r["team"]: r["played"] for r in res}
        self.assertEqual(played["A"], 1)
        self.assertEqual(played["C"], 0)

    def test_win_draw_loss_points(self):
        res = {r["team"]: r for r in
               compute_standings(_gd(["A", "B", "C"], {(0, 1): (1, 1), (0, 2): (3, 0)}))["G"]}
        self.assertEqual((res["A"]["w"], res["A"]["d"], res["A"]["l"]), (1, 1, 0))
        self.assertEqual(res["A"]["pts"], 4)
        self.assertEqual(res["B"]["pts"], 1)


if __name__ == "__main__":
    unittest.main()
