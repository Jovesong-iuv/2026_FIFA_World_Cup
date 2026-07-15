import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from wc2026.analysis import imminent as IM


def _fx(mn, date_utc, home_score=None):
    return {"match_number": mn, "home_team": f"H{mn}", "away_team": f"A{mn}",
            "date_utc": date_utc, "home_score": home_score, "away_score": None}


class ImminentFixturesTest(unittest.TestCase):
    NOW = "2026-06-20T17:00:00Z"

    def test_window_selection_and_order(self):
        fixtures = [
            _fx(1, "2026-06-20 19:00:00Z"),    # T-2h  → 入选
            _fx(2, "2026-06-20 18:30:00Z"),    # T-1.5h → 入选（更近，排前）
            _fx(3, "2026-06-21 19:00:00Z"),    # T-26h → 窗口外
            _fx(4, "2026-06-20 19:30:00Z", home_score=2),  # 已完赛 → 排除
            _fx(5, "2026-06-20 16:00:00Z"),    # 已开赛(T+1h) → 排除
        ]
        imm = IM.imminent_fixtures(fixtures, now=self.NOW, window_hours=2.0)
        self.assertEqual([f["match_number"] for f in imm], [2, 1])
        self.assertAlmostEqual(imm[0]["_hours_to_kickoff"], 1.5, places=2)

    def test_empty_when_all_far(self):
        imm = IM.imminent_fixtures([_fx(1, "2026-06-25 19:00:00Z")], now=self.NOW, window_hours=2.0)
        self.assertEqual(imm, [])


class DetectKeyChangesTest(unittest.TestCase):
    def _snap(self, home, draw, away, **extra):
        return {"outcomes": {"home": home, "draw": draw, "away": away},
                "data_quality": {"score": extra.get("dq", 0.8)},
                "lineup": {"confidence": extra.get("lineup", "estimated")},
                "risks": extra.get("risks", []), "locked_at": "2026-06-20T08:00:00Z"}

    def test_no_prev(self):
        out = IM.detect_key_changes(None, self._snap(0.5, 0.3, 0.2))
        self.assertFalse(out["changed"])
        self.assertFalse(out["escalate"])

    def test_major_swing_escalates(self):
        prev = self._snap(0.60, 0.25, 0.15)
        curr = self._snap(0.40, 0.30, 0.30)            # 主胜 -20%, 客胜 +15%
        out = IM.detect_key_changes(prev, curr)
        self.assertTrue(out["changed"])
        self.assertTrue(out["escalate"])
        self.assertEqual(out["risks"][0]["level"], "高")

    def test_small_change_below_threshold(self):
        prev = self._snap(0.60, 0.25, 0.15)
        curr = self._snap(0.62, 0.24, 0.14)            # 仅 +2% < 5% 阈值
        out = IM.detect_key_changes(prev, curr)
        self.assertFalse(out["changed"])

    def test_lineup_upgrade_is_change(self):
        prev = self._snap(0.5, 0.3, 0.2, lineup="estimated")
        curr = self._snap(0.5, 0.3, 0.2, lineup="confirmed")
        out = IM.detect_key_changes(prev, curr)
        self.assertTrue(out["changed"])
        self.assertEqual(out["risks"][0]["level"], "中")   # 非重大 → 中

    def test_new_high_risk_escalates(self):
        prev = self._snap(0.5, 0.3, 0.2, risks=[])
        curr = self._snap(0.5, 0.3, 0.2, risks=[{"level": "高"}])
        out = IM.detect_key_changes(prev, curr)
        self.assertTrue(out["escalate"])


class SnapshotJsonTest(unittest.TestCase):
    def test_snapshot_locks_exactly_three_scorelines(self):
        fixture = {
            "match_number": 5,
            "home_team": "France",
            "away_team": "Senegal",
            "date_utc": "2026-06-20 19:00:00Z",
        }
        report = {
            "match": {"home_cn": "法国", "away_cn": "塞内加尔"},
            "generated_at": "2026-06-20T10:00:00Z",
            "phase": "prematch",
            "prediction": {
                "outcomes": {"home": 0.6, "draw": 0.22, "away": 0.18},
                "expected_goals": {"home": 1.7, "away": 0.9},
                "top_scores": [
                    {"score": "1-0", "prob": 0.16},
                    {"score": "2-0", "prob": 0.14},
                    {"score": "2-1", "prob": 0.11},
                    {"score": "1-1", "prob": 0.10},
                ],
            },
            "data_quality": {"score": 0.8},
            "lineup": None,
            "confidence": "中",
            "risks": [],
        }

        snap = IM._snap_from_report(fixture, report, "2026-06-20T10:00:00Z")

        self.assertEqual([r["score"] for r in snap["top_scores"]], ["1-0", "2-0", "2-1"])

    def test_merge_load_roundtrip_and_strip_report(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "snap.json"
            IM._merge_json({"match_number": 5, "home": "A", "away": "B",
                            "outcomes": {"home": 0.6}, "report": {"big": "x"}}, path=p)
            alls = IM.load_all_prematch_snapshots(path=p)
            self.assertIn(5, alls)
            self.assertNotIn("report", alls[5])          # report 不入精简 JSON
            one = IM.load_prematch_snapshot(5, path=p)
            self.assertEqual(one["home"], "A")
            # 追加另一场，旧的保留（合并而非覆盖）
            IM._merge_json({"match_number": 6, "home": "C", "away": "D"}, path=p)
            self.assertEqual(set(IM.load_all_prematch_snapshots(path=p)), {5, 6})

    def test_load_missing_returns_empty(self):
        with TemporaryDirectory() as d:
            self.assertEqual(IM.load_all_prematch_snapshots(path=Path(d) / "none.json"), {})
            self.assertIsNone(IM.load_prematch_snapshot(1, path=Path(d) / "none.json"))


if __name__ == "__main__":
    unittest.main()
