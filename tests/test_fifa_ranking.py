import unittest

from wc2026.analysis.ranking import world_rank
from wc2026.data.fifa_ranking import fifa_rank, ranking_date

# 与库名写法不同、需别名映射的 9 支参赛队（最易错）
_ALIASED = ["Cape Verde", "Czech Republic", "DR Congo", "Iran", "Ivory Coast",
            "New Zealand", "South Korea", "Turkey", "United States"]
_DIRECT = ["Argentina", "Brazil", "Spain", "Mexico", "Japan", "Morocco"]


class _Elo:
    def __init__(self, ratings):
        self.ratings = ratings


class _Model:
    def __init__(self, ratings):
        self.elo = _Elo(ratings)


class FifaRankingTest(unittest.TestCase):
    def test_aliased_teams_resolve_to_int(self):
        for t in _ALIASED:
            r = fifa_rank(t)
            self.assertIsInstance(r, int, f"{t} 未解析到 FIFA 排名")
            self.assertGreaterEqual(r, 1)

    def test_direct_teams_resolve(self):
        for t in _DIRECT:
            self.assertIsInstance(fifa_rank(t), int, f"{t} 未解析")

    def test_unknown_team_none(self):
        self.assertIsNone(fifa_rank("Narnia United"))

    def test_ranking_date_format(self):
        d = ranking_date()
        self.assertRegex(d, r"^\d{4}-\d{2}-\d{2}$")


class WorldRankTest(unittest.TestCase):
    def test_fifa_preferred(self):
        rank, src = world_rank(_Model({"Argentina": 2000}), "Argentina")
        self.assertEqual(src, "FIFA")
        self.assertIsInstance(rank, int)

    def test_elo_fallback_for_non_fifa_team(self):
        # 一支不在 FIFA 榜里的队，但在模型 Elo 中 → 回退 Elo
        m = _Model({"ClubXYZ": 1700, "ClubABC": 1500})
        rank, src = world_rank(m, "ClubXYZ")
        self.assertEqual(src, "Elo")
        self.assertEqual(rank, 1)

    def test_unknown_everywhere(self):
        rank, src = world_rank(_Model({}), "Narnia United")
        self.assertIsNone(rank)
        self.assertEqual(src, "")


if __name__ == "__main__":
    unittest.main()
