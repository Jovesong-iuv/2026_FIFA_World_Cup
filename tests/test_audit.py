import sqlite3
import unittest

from wc2026.analysis import audit as A
from wc2026.data import odds_history as oh


def _mem_odds():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE odds_snapshots (captured_at TEXT, home_team TEXT, away_team TEXT, "
        "market TEXT, selection TEXT, line TEXT, odds REAL)")
    return conn


# 已完赛 fixture + 对应赛前锁定快照（提供 outcomes → match_audit 走快照分支，不需真实模型）
FIX_HOME = {"match_number": 1, "home_team": "France", "away_team": "Senegal",
            "date_utc": "2026-06-20 19:00:00Z", "home_score": 2, "away_score": 1}
SNAP_HOME = {"outcomes": {"home": 0.60, "draw": 0.22, "away": 0.18},
             "locked_at": "2026-06-20T10:00:00Z"}
FIX_DRAW = {"match_number": 2, "home_team": "Canada", "away_team": "Bosnia and Herzegovina",
            "date_utc": "2026-06-20 19:00:00Z", "home_score": 1, "away_score": 1}
SNAP_DRAW = {"outcomes": {"home": 0.55, "draw": 0.25, "away": 0.20},
             "locked_at": "2026-06-20T10:00:00Z"}
FIX_FUTURE = {"match_number": 3, "home_team": "Spain", "away_team": "Japan",
              "date_utc": "2026-07-01 19:00:00Z", "home_score": None, "away_score": None}
FIX_KO = {"match_number": 80, "round_number": 5, "group_name": "", "home_team": "France",
          "away_team": "Argentina", "date_utc": "2026-07-04 19:00:00Z",
          "home_score": 1, "away_score": 1}
SNAP_KO = {"outcomes": {"home": 0.42, "draw": 0.30, "away": 0.28},
           "locked_at": "2026-07-04T10:00:00Z"}


class ParseOutcomeTest(unittest.TestCase):
    def test_actual_outcome(self):
        self.assertEqual(A.actual_outcome(2, 1), "home")
        self.assertEqual(A.actual_outcome(1, 1), "draw")
        self.assertEqual(A.actual_outcome(0, 3), "away")
        self.assertIsNone(A.actual_outcome(None, 1))

    def test_parse_utc_formats(self):
        d1 = A._parse_utc("2026-06-20 19:00:00Z")
        d2 = A._parse_utc("2026-06-20T19:00:00+00:00")
        self.assertEqual(d1, d2)
        self.assertIsNone(A._parse_utc(""))


class MatchAuditSnapshotTest(unittest.TestCase):
    def test_model_hit_no_market(self):
        a = A.match_audit(None, FIX_HOME, snapshot=SNAP_HOME)
        self.assertTrue(a["finished"])
        self.assertEqual(a["actual"], "home")
        self.assertEqual(a["model"]["source"], "赛前锁定快照")
        self.assertEqual(a["model"]["pick"], "home")
        self.assertTrue(a["model"]["hit"])
        self.assertFalse(a["market"]["enabled"])
        self.assertIn("模型命中", a["verdict"])
        # rows 标出实际结果
        actual_row = [r for r in a["rows"] if r["is_actual"]][0]
        self.assertEqual(actual_row["key"], "home")
        self.assertIsNone(actual_row["market_prob"])

    def test_model_miss(self):
        a = A.match_audit(None, FIX_DRAW, snapshot=SNAP_DRAW)
        self.assertEqual(a["actual"], "draw")
        self.assertEqual(a["model"]["pick"], "home")     # 最看好主胜，实际平局
        self.assertFalse(a["model"]["hit"])
        self.assertIn("模型未中", a["verdict"])

    def test_knockout_audit_includes_professional_postmatch_review(self):
        insights = {"matches": {
            "France__Argentina": {
                "prior_matches": [
                    {"team": "France", "xg_for": 1.7, "shots_for": 14, "source": "FBref"},
                    {"team": "Argentina", "xg_for": 1.1, "shots_for": 9, "source": "FotMob"},
                ],
                "tactical_notes": ["法国边路推进效率更高。"],
                "availability_notes": ["阿根廷主力后腰伤疑。"],
                "deep_analysis": {"text": "法国压迫质量占优，但淘汰赛节奏更保守。"},
                "data_as_of": "2026-07-05",
            }
        }}
        a = A.match_audit(None, FIX_KO, snapshot=SNAP_KO, insights=insights)
        review = a["postmatch_review"]
        self.assertEqual(a["stage"]["type"], "knockout")
        self.assertTrue(review["enabled"])
        self.assertIn("淘汰赛", review["summary"])
        self.assertIn("点球风险", "；".join(review["correction_factors"]))
        self.assertIn("渐进式权重", review["model_feedback"])
        self.assertTrue(any("xG" in item for item in review["evidence"]))

    def test_random_knockout_events_are_not_model_update_signal(self):
        insights = {"matches": {
            "France__Argentina": {
                "prior_matches": [
                    {"team": "France", "xg_for": 1.2, "shots_for": 10, "source": "FBref"},
                    {"team": "Argentina", "xg_for": 1.1, "shots_for": 9, "source": "FBref"},
                ],
                "deep_analysis": {"text": "比赛进入点球大战，且上半场出现红牌，常规实力判断噪声较大。"},
            }
        }}
        a = A.match_audit(None, FIX_KO, snapshot=SNAP_KO, insights=insights)
        fb = a["postmatch_review"]["model_update"]
        self.assertEqual(fb["primary_bias"], "random_event")
        self.assertFalse(fb["should_update_strength"])
        self.assertEqual(fb["weight"], "low")

    def test_process_data_can_mark_strength_update_signal(self):
        fixture = {**FIX_KO, "home_score": 0, "away_score": 2}
        insights = {"matches": {
            "France__Argentina": {
                "prior_matches": [
                    {"team": "France", "xg_for": 0.7, "shots_for": 6, "source": "FBref"},
                    {"team": "Argentina", "xg_for": 2.3, "shots_for": 17, "source": "FBref"},
                ],
                "tactical_notes": ["阿根廷高位逼抢持续压制法国出球。"],
            }
        }}
        a = A.match_audit(None, fixture, snapshot=SNAP_KO, insights=insights)
        fb = a["postmatch_review"]["model_update"]
        self.assertEqual(fb["primary_bias"], "strength_bias")
        self.assertTrue(fb["should_update_strength"])
        self.assertIn(fb["weight"], ("medium", "high"))


class MatchAuditMarketTest(unittest.TestCase):
    def test_market_from_prematch_snapshot(self):
        conn = _mem_odds()
        # 赛前（08:00 < 开赛 19:00）h2h：主胜强赔
        oh.record_event_snapshot("France", "Senegal",
                                 {"h2h": {"home": 1.50, "draw": 4.00, "away": 6.00}},
                                 captured_at="2026-06-20T08:00:00", conn=conn)
        a = A.match_audit(None, FIX_HOME, snapshot=SNAP_HOME, conn=conn)
        self.assertTrue(a["market"]["enabled"])
        self.assertEqual(a["market"]["pick"], "home")    # 1.50 最低赔 → 隐含最高
        self.assertTrue(a["market"]["hit"])
        self.assertAlmostEqual(sum(a["market"]["probs"].values()), 1.0, places=3)

    def test_ignores_post_kickoff_odds(self):
        conn = _mem_odds()
        # 仅有开赛后的赔率 → 视为无赛前快照
        oh.record_event_snapshot("France", "Senegal",
                                 {"h2h": {"home": 1.50, "draw": 4.0, "away": 6.0}},
                                 captured_at="2026-06-20T20:00:00", conn=conn)
        a = A.match_audit(None, FIX_HOME, snapshot=SNAP_HOME, conn=conn)
        self.assertFalse(a["market"]["enabled"])


class AuditSummaryTest(unittest.TestCase):
    def test_summary_counts_and_metrics(self):
        fixtures = [FIX_HOME, FIX_DRAW, FIX_FUTURE]
        snaps = {1: SNAP_HOME, 2: SNAP_DRAW}
        s = A.audit_summary(None, fixtures, snapshots=snaps)
        self.assertEqual(s["n_finished"], 2)             # 未完赛被排除
        self.assertEqual(s["n_with_snapshot"], 2)
        self.assertEqual(s["model_metrics"]["n"], 2)
        self.assertEqual(s["model_metrics"]["accuracy"], 0.5)  # 1 中 1 错
        self.assertFalse(s["comparison"]["enabled"])     # 无市场样本

    def test_summary_with_market_comparison(self):
        conn = _mem_odds()
        for h, a in (("France", "Senegal"), ("Canada", "Bosnia and Herzegovina")):
            oh.record_event_snapshot(h, a, {"h2h": {"home": 1.8, "draw": 3.4, "away": 4.2}},
                                     captured_at="2026-06-20T08:00:00", conn=conn)
        s = A.audit_summary(None, [FIX_HOME, FIX_DRAW], snapshots={1: SNAP_HOME, 2: SNAP_DRAW}, conn=conn)
        self.assertEqual(s["n_with_market"], 2)
        self.assertTrue(s["comparison"]["enabled"])
        self.assertIn(s["comparison"]["log_loss"]["better"], ("模型", "市场", "持平"))

    def test_summary_counts_knockout_reviews(self):
        s = A.audit_summary(None, [FIX_HOME, FIX_KO], snapshots={1: SNAP_HOME, 80: SNAP_KO})
        self.assertEqual(s["scope"]["group_stage_finished"], 1)
        self.assertEqual(s["scope"]["knockout_finished"], 1)
        self.assertEqual(s["scope"]["knockout_reviewed"], 1)


class CompareTest(unittest.TestCase):
    def test_compare_directions(self):
        mm = {"n": 2, "log_loss": 0.70, "brier": 0.40, "accuracy": 0.50}
        km = {"n": 2, "log_loss": 0.80, "brier": 0.45, "accuracy": 0.50}
        c = A._compare(mm, km)
        self.assertTrue(c["enabled"])
        self.assertEqual(c["log_loss"]["better"], "模型")   # 越低越好
        self.assertEqual(c["brier"]["better"], "模型")
        self.assertEqual(c["accuracy"]["better"], "持平")

    def test_compare_disabled_without_market(self):
        c = A._compare({"n": 2, "log_loss": 0.7}, {"n": 0})
        self.assertFalse(c["enabled"])


if __name__ == "__main__":
    unittest.main()
