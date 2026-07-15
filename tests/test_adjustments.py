import unittest
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from wc2026.analysis import adjustments as adj
from wc2026.markets.derive import outcomes_1x2
from wc2026.models.dixon_coles import DixonColesModel
from wc2026.models.elo import EloModel
from wc2026.models.predictor import EnsembleModel


def _model() -> EnsembleModel:
    dc = DixonColesModel()
    dc.attack = {"Strong": 0.5, "Weak": -0.5, "Mid": 0.0}
    dc.defense = {"Strong": -0.5, "Weak": 0.5, "Mid": 0.0}  # 越低防守越好
    dc.teams = ["Strong", "Weak", "Mid"]
    dc.home_adv = 0.25
    dc.rho = -0.05
    dc.fitted = True
    elo = EloModel()
    elo.ratings = {"Strong": 1800.0, "Weak": 1400.0, "Mid": 1600.0}
    return EnsembleModel(dc, elo)


def _match(home, away, hs, as_, date="2026-06-20", **extra):
    return {"home_team": home, "away_team": away, "home_score": hs,
            "away_score": as_, "date_utc": date, **extra}


class ResultDeltaTest(unittest.TestCase):
    def test_scoreline_weight_is_bounded_by_nearest_top_three_distance(self):
        top = [{"score": "1-0", "prob": 0.2}, {"score": "2-1", "prob": 0.15},
               {"score": "1-1", "prob": 0.14}]

        self.assertEqual(adj._scoreline_weight(top, 2, 1)[0], 0.70)
        self.assertEqual(adj._scoreline_weight(top, 2, 2)[0], 0.90)
        self.assertEqual(adj._scoreline_weight(top, 3, 2)[0], 1.00)
        self.assertEqual(adj._scoreline_weight(top, 4, 2)[0], 1.10)
        self.assertEqual(adj._scoreline_weight([], 4, 2)[0], 1.00)

    def test_upset_moves_ratings(self):
        d = adj.compute_result_deltas(_model(), [_match("Weak", "Strong", 3, 0)])
        self.assertGreater(d["Weak"]["elo"], 0)      # 弱队爆冷 → 加分
        self.assertLess(d["Strong"]["elo"], 0)       # 强队爆冷输 → 减分
        self.assertGreater(d["Weak"]["attack"], 0)   # 大胜 → 进攻上修
        self.assertLess(d["Weak"]["defense"], 0)     # 零封 → 防守下修(更好)

    def test_upset_bigger_than_expected_result(self):
        m = _model()
        upset = adj.compute_result_deltas(m, [_match("Weak", "Strong", 2, 0)])
        expected = adj.compute_result_deltas(m, [_match("Strong", "Weak", 2, 0)])
        # 同样 2-0：弱队爆冷对强队评分的冲击 > 强队常规取胜对弱队的冲击
        self.assertGreater(abs(upset["Strong"]["elo"]), abs(expected["Weak"]["elo"]))

    def test_symmetric_elo(self):
        d = adj.compute_result_deltas(_model(), [_match("Mid", "Strong", 1, 1)])
        self.assertAlmostEqual(d["Mid"]["elo"], -d["Strong"]["elo"], places=9)

    def test_result_source_records_prediction_vs_actual_and_style(self):
        d = adj.compute_result_deltas(_model(), [_match("Weak", "Strong", 3, 0)])
        src = d["Weak"]["sources"][0]

        self.assertEqual(src["type"], "result")
        self.assertEqual(src["actual"], {"home_score": 3, "away_score": 0, "total_goals": 3, "outcome": "home"})
        self.assertIn("predicted", src)
        self.assertIn("home_xg", src["predicted"])
        self.assertIn("away_xg", src["predicted"])
        self.assertIn("outcomes_1x2", src["predicted"])
        self.assertIn("top_scores", src["predicted"])
        self.assertIn("errors", src)
        self.assertGreater(src["errors"]["home_goal"], 0)
        self.assertIn("delta_attack", src)
        self.assertIn("delta_defense", src)
        self.assertIn("style", src)
        self.assertEqual(src["style"]["home"]["lean"], "未知")
        self.assertIn("goal_calibration", src)
        self.assertIn("process_weight", src)
        self.assertIn("time_decay", src)

    def test_process_data_reduces_update_when_score_contradicts_xg(self):
        m = _model()
        plain = adj.compute_result_deltas(m, [_match("Weak", "Strong", 1, 0)])
        noisy = adj.compute_result_deltas(m, [_match("Weak", "Strong", 1, 0, home_xg=0.3, away_xg=2.4)])

        self.assertLess(abs(noisy["Weak"]["elo"]), abs(plain["Weak"]["elo"]))
        self.assertLess(noisy["Weak"]["sources"][0]["process_weight"], 1.0)

    def test_ft_espn_stats_reduce_update_when_score_contradicts_process(self):
        stats = {
            "Weak": {"shots": 4, "possession": 0.35},
            "Strong": {"shots": 18, "possession": 0.65},
        }
        match = _match("Weak", "Strong", 1, 0, result_status="FT",
                       match_stats_json=json.dumps(stats))

        result = adj.compute_result_deltas(_model(), [match])
        source = result["Weak"]["sources"][0]

        self.assertLess(source["process_weight"], 1.0)
        self.assertIn("ESPN", " ".join(source["weight_notes"]))

    def test_aet_espn_stats_never_weight_regulation_process(self):
        stats = {
            "Weak": {"shots": 4, "possession": 0.35},
            "Strong": {"shots": 18, "possession": 0.65},
        }
        match = _match(
            "Weak", "Strong", 2, 1, result_status="AET", round_number=4,
            regulation_home_score=1, regulation_away_score=1,
            match_stats_json=json.dumps(stats),
        )

        result = adj.compute_result_deltas(_model(), [match])
        source = result["Weak"]["sources"][0]

        self.assertEqual(source["process_weight"], 1.0)
        self.assertIn("不用于90分钟", " ".join(source["weight_notes"]))

    def test_recent_matches_get_more_weight_than_old_matches(self):
        m = _model()
        old = adj.compute_result_deltas(m, [_match("Weak", "Strong", 2, 0, "2026-06-01")],
                                        as_of="2026-07-01")
        recent = adj.compute_result_deltas(m, [_match("Weak", "Strong", 2, 0, "2026-06-30")],
                                           as_of="2026-07-01")

        self.assertGreater(abs(recent["Weak"]["elo"]), abs(old["Weak"]["elo"]))
        self.assertGreater(recent["Weak"]["sources"][0]["time_decay"], old["Weak"]["sources"][0]["time_decay"])

    def test_uses_locked_top_three_and_regulation_score_for_aet_match(self):
        match = _match(
            "Weak", "Strong", 3, 2, match_number=80, round_number=4,
            regulation_home_score=1, regulation_away_score=1,
            result_status="AET", event_flags=["extra_time"],
        )
        snapshots = {80: {
            "outcomes": {"home": 0.25, "draw": 0.30, "away": 0.45},
            "expected_goals": {"home": 1.1, "away": 1.2},
            "top_scores": [
                {"score": "1-1", "prob": 0.16},
                {"score": "0-1", "prob": 0.14},
                {"score": "1-2", "prob": 0.12},
            ],
        }}

        result = adj.compute_result_deltas(_model(), [match], snapshots=snapshots)
        source = result["Weak"]["sources"][0]

        self.assertEqual(source["actual"]["home_score"], 1)
        self.assertEqual(source["actual"]["away_score"], 1)
        self.assertEqual(source["predicted"]["home_xg"], 1.1)
        self.assertEqual(source["predicted"]["top_scores"][0]["score"], "1-1")
        self.assertEqual(source["scoreline_calibration"]["weight"], 0.70)
        self.assertTrue(source["scoreline_calibration"]["comparison"]["top1_hit"])
        self.assertIn("特殊事件降权", source["weight_notes"])

    def test_skips_unverified_knockout_total(self):
        match = _match("Weak", "Strong", 3, 2, match_number=80, round_number=4,
                       result_status="AET")

        self.assertEqual(adj.compute_result_deltas(_model(), [match], snapshots={}), {})

    def test_legacy_snapshot_does_not_backfill_current_model_scorelines(self):
        match = _match("Weak", "Strong", 1, 0, match_number=1)
        snapshots = {1: {
            "outcomes": {"home": 0.3, "draw": 0.3, "away": 0.4},
            "expected_goals": {"home": 1.0, "away": 1.2},
        }}

        result = adj.compute_result_deltas(_model(), [match], snapshots=snapshots)
        source = result["Weak"]["sources"][0]

        self.assertEqual(source["predicted"]["top_scores"], [])
        self.assertEqual(source["predicted"]["top_scores_source"], "unavailable_legacy_snapshot")
        self.assertFalse(source["scoreline_calibration"]["comparison"]["available"])


class MergeBoundsTest(unittest.TestCase):
    def test_bounds_clip(self):
        m = _model()
        many = [_match("Weak", "Strong", 9, 0, f"2026-06-2{i}") for i in range(6)]
        merged = adj._merge(adj.compute_result_deltas(m, many))
        self.assertLessEqual(abs(merged["Weak"]["elo"]), adj.ELO_CAP + 1e-6)
        self.assertLessEqual(abs(merged["Weak"]["attack"]), adj.ATK_CAP + 1e-6)
        self.assertLessEqual(abs(merged["Weak"]["defense"]), adj.DEF_CAP + 1e-6)


class ApplyTest(unittest.TestCase):
    def test_empty_returns_same_object(self):
        m = _model()
        self.assertIs(adj.apply_adjustments(m, {}), m)

    def test_apply_does_not_mutate_original(self):
        m = _model()
        adj.apply_adjustments(m, {"Weak": {"elo": 100.0, "attack": 0.3, "defense": -0.2}})
        self.assertEqual(m.elo.ratings["Weak"], 1400.0)
        self.assertEqual(m.attack["Weak"], -0.5)

    def test_apply_changes_prediction(self):
        m = _model()
        boosted = adj.apply_adjustments(
            m, {"Weak": {"elo": 150.0, "attack": 0.4, "defense": -0.3}})
        self.assertAlmostEqual(boosted.elo.ratings["Weak"], 1550.0)
        self.assertAlmostEqual(boosted.attack["Weak"], -0.1)
        before = outcomes_1x2(m.score_matrix("Weak", "Mid", True))["home"]
        after = outcomes_1x2(boosted.score_matrix("Weak", "Mid", True))["home"]
        self.assertGreater(after, before)            # 被增强后胜率上升


class LoadAdjustmentsTest(unittest.TestCase):
    def test_ignores_unversioned_adjustments_to_prevent_double_counting(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "team_adjustments.json"
            path.write_text(json.dumps({
                "trained_through": "",
                "teams": {"Weak": {"elo": 40.0, "attack": 0.1, "defense": -0.1}},
            }), encoding="utf-8")
            with patch.object(adj, "ADJ_PATH", path):
                loaded = adj.load_adjustments()

        self.assertEqual(loaded, {})

    def test_reports_unversioned_adjustments_as_ignored(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "team_adjustments.json"
            path.write_text(json.dumps({
                "trained_through": "",
                "teams": {"Weak": {"elo": 40.0}},
            }), encoding="utf-8")
            with patch.object(adj, "ADJ_PATH", path):
                status = adj.adjustment_artifact_status()

        self.assertEqual(status["state"], "unversioned")
        self.assertFalse(status["applied"])
        self.assertIn("重复", status["reason"])

    def test_loads_adjustments_with_training_cutoff(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "team_adjustments.json"
            path.write_text(json.dumps({
                "trained_through": "2026-07-13",
                "teams": {"Weak": {"elo": 40.0, "attack": 0.1, "defense": -0.1}},
            }), encoding="utf-8")
            with patch.object(adj, "ADJ_PATH", path):
                loaded = adj.load_adjustments()

        self.assertEqual(loaded["Weak"]["elo"], 40.0)


class CutoffTest(unittest.TestCase):
    def test_filter_after_cutoff(self):
        rows = [{"date_utc": "2026-06-11 19:00:00Z"}, {"date_utc": "2026-06-15 01:00:00Z"}]
        self.assertEqual(len(adj._filter_after_cutoff(rows, "2026-06-12")), 1)   # 仅保留晚于 cutoff
        self.assertEqual(len(adj._filter_after_cutoff(rows, "")), 2)             # 空 cutoff 全保留
        self.assertEqual(len(adj._filter_after_cutoff(rows, "2026-06-15")), 0)   # 同日不计(防双计)


class EventWeightTest(unittest.TestCase):
    def test_knockout_weight_and_special_event_discount(self):
        ko_weight, ko_notes = adj._event_weight({"round_number": 4})
        noisy_weight, noisy_notes = adj._event_weight({"round_number": 4, "event_flags": ["penalty_shootout"]})
        self.assertGreater(ko_weight, 1.0)
        self.assertLess(noisy_weight, ko_weight)
        self.assertIn("淘汰赛高权重", ko_notes)
        self.assertIn("特殊事件降权", noisy_notes)


if __name__ == "__main__":
    unittest.main()
