import unittest

from wc2026.llm.match_chat import build_context


class BuildContextTest(unittest.TestCase):
    def _full(self):
        return {
            "home": "墨西哥", "away": "南非",
            "home_rank": 10, "away_rank": 64, "rank_total": 300,
            "result": None,
            "xg": (1.8, 0.9),
            "probs": {"home": 0.62, "draw": 0.24, "away": 0.14},
            "over_under25": {"over": 0.45, "under": 0.55},
            "goal_bands": {"0-1球": 0.30, "2-3球": 0.50, "4+球": 0.20},
            "btts": 0.41,
            "correct_score_top": [{"score": "2-0", "prob": 0.12}, {"score": "1-0", "prob": 0.10}],
            "upset": {"index": 21, "level": "中低风险", "factors": [{"detail": "热门方胜率高"}]},
            "strength": {"score_home": 76, "score_away": 59,
                         "dims_home": {"基础实力": 80, "进攻": 75},
                         "dims_away": {"基础实力": 60, "进攻": 55}},
            "goal_rec": {"recommend": "2-3球", "reasons": ["期望进球适中"]},
            "h2h": {"total": 4, "a_win": 2, "draw": 1, "a_loss": 1, "avg_gf": 1.5, "avg_ga": 1.0},
            "home_form": {"n": 6, "w": 4, "d": 1, "l": 1, "gf": 10, "ga": 5},
        }

    def test_includes_core_fields(self):
        ctx = build_context(self._full())
        for kw in ["比赛：墨西哥 vs 南非", "世界排名", "期望进球", "胜平负", "大小球2.5",
                   "进球区间", "爆冷指数：21", "综合实力", "进球区间推荐：2-3球", "历史交锋"]:
            self.assertIn(kw, ctx)

    def test_unfinished_default_text(self):
        self.assertIn("未开赛", build_context({"home": "A", "away": "B"}))

    def test_finished_result_text(self):
        ctx = build_context({"home": "A", "away": "B", "result": "A胜 2-0"})
        self.assertIn("赛果：A胜 2-0", ctx)

    def test_missing_keys_skipped(self):
        ctx = build_context({"home": "A", "away": "B"})
        self.assertNotIn("爆冷指数", ctx)
        self.assertNotIn("综合实力", ctx)

    def test_extra_text_included(self):
        ctx = build_context({"home": "A", "away": "B", "extra_text": "球队大巴晚点"})
        self.assertIn("用户补充材料：球队大巴晚点", ctx)


if __name__ == "__main__":
    unittest.main()
