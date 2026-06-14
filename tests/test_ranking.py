import unittest

from wc2026.analysis.ranking import elo_rank


class _Elo:
    def __init__(self, ratings):
        self.ratings = ratings


class _Model:
    def __init__(self, ratings):
        self.elo = _Elo(ratings)


class EloRankTest(unittest.TestCase):
    def test_ranks_by_rating_desc(self):
        m = _Model({"A": 1900, "B": 1700, "C": 1500, "D": 1300})
        self.assertEqual(elo_rank(m, "A"), (1, 4))
        self.assertEqual(elo_rank(m, "C"), (3, 4))

    def test_ties_share_rank(self):
        m = _Model({"A": 1800, "B": 1800, "C": 1500})
        self.assertEqual(elo_rank(m, "A")[0], 1)
        self.assertEqual(elo_rank(m, "B")[0], 1)
        self.assertEqual(elo_rank(m, "C")[0], 3)  # 竞争名次：两个并列第1后是第3

    def test_unknown_team_returns_none(self):
        m = _Model({"A": 1800})
        self.assertEqual(elo_rank(m, "Z"), (None, 1))

    def test_no_elo_data(self):
        class Bare:
            elo = None
        rank, total = elo_rank(Bare(), "A")
        self.assertIsNone(rank)
        self.assertEqual(total, 0)


if __name__ == "__main__":
    unittest.main()
