"""稳健刷新流水线：每步独立失败、记录耗时，并尽量继续后续步骤。"""
from __future__ import annotations

import time
from collections.abc import Callable

from wc2026.analysis.adjustments import recompute
from wc2026.analysis.match_insights import INSIGHTS_PATH, load_insights, refresh_match_insight
from wc2026.data.db import init_db
from wc2026.data.db import get_conn
from wc2026.data.ingest import ingest_international_results
from wc2026.data.results import backfill_fixture_scores, export_results_json
from wc2026.data.sources.fixtures_2026 import fetch_and_store_fixtures
from wc2026.data.sources.live_results import search_match_result
from wc2026.models.predictor import get_model, train_and_save

LIVE_SCORE_SETTLE_HOURS = 3
LIVE_SCORE_LIMIT = 24
LIVE_SCORE_TIMEOUT = 6
LIVE_SCORE_TIME_BUDGET = 90
LIVE_SCORE_LOOKBACK_DAYS = 7


def _run_step(name: str, label: str, fn: Callable, *, critical: bool = False) -> dict:
    t0 = time.monotonic()
    try:
        value = fn()
        return {"name": name, "label": label, "ok": True, "seconds": round(time.monotonic() - t0, 2),
                "result": value, "critical": critical}
    except Exception as exc:
        return {"name": name, "label": label, "ok": False, "seconds": round(time.monotonic() - t0, 2),
                "error": str(exc), "critical": critical}


def _finished_knockout_fixtures() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT match_number, home_team, away_team FROM fixtures "
            "WHERE predictable=1 AND round_number>=4 AND home_score IS NOT NULL "
            "AND away_score IS NOT NULL ORDER BY date_utc"
        ).fetchall()
    return [dict(r) for r in rows]


def _has_match_insight(home: str, away: str, *, path=INSIGHTS_PATH) -> bool:
    matches = load_insights(path).get("matches", {})
    entry = matches.get(f"{home}::{away}") or matches.get(f"{away}::{home}") or {}
    return bool(entry.get("data_as_of"))


def refresh_knockout_postmatch_insights(*, path=INSIGHTS_PATH, force: bool = False) -> dict:
    """联网补全已完赛淘汰赛分场数据，供赛后复盘和后续实力修正解释使用。"""
    rows = _finished_knockout_fixtures()
    ok, failed, skipped, errors = 0, 0, 0, []
    for r in rows:
        if not force and _has_match_insight(r["home_team"], r["away_team"], path=path):
            skipped += 1
            continue
        try:
            res = refresh_match_insight(r["home_team"], r["away_team"], path=path)
            if res.get("ok"):
                ok += 1
            else:
                failed += 1
                errors.append({"match_number": r["match_number"], "errors": res.get("errors", [])[:3]})
        except Exception as exc:
            failed += 1
            errors.append({"match_number": r["match_number"], "errors": [str(exc)]})
    return {"matches": len(rows), "processed": ok + failed, "skipped": skipped,
            "ok": ok, "failed": failed, "errors": errors[:5]}


def _live_score_candidates(conn, *, limit: int, now_utc: str | None = None,
                           settle_hours: int = LIVE_SCORE_SETTLE_HOURS,
                           lookback_days: int = LIVE_SCORE_LOOKBACK_DAYS) -> list[dict]:
    now_expr = "?" if now_utc else "'now'"
    now_params = [now_utc] if now_utc else []
    params = now_params + [f"-{settle_hours} hours"] + now_params + [f"-{lookback_days} days", limit]
    rows = conn.execute(
        "SELECT match_number, home_team, away_team FROM fixtures "
        "WHERE predictable=1 AND home_score IS NULL AND away_score IS NULL "
        f"AND datetime(date_utc) <= datetime({now_expr}, ?) "
        f"AND datetime(date_utc) >= datetime({now_expr}, ?) "
        "ORDER BY match_number LIMIT ?",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def refresh_live_fixture_scores(limit: int = LIVE_SCORE_LIMIT, *,
                                timeout: float = LIVE_SCORE_TIMEOUT,
                                time_budget: float = LIVE_SCORE_TIME_BUDGET) -> dict:
    """从 ESPN/Yahoo/FIFA 等公开搜索结果尽量补全 fixtures 已完赛比分。"""
    started = time.monotonic()
    with get_conn() as conn:
        rows = _live_score_candidates(conn, limit=limit)
        updated, errors = 0, []
        checked = 0
        stopped = None
        for r in rows:
            if time.monotonic() - started >= time_budget:
                stopped = f"达到联网补分时间预算 {time_budget}s"
                break
            checked += 1
            try:
                found = search_match_result(r["home_team"], r["away_team"], timeout=timeout)
            except Exception as exc:
                errors.append({"match_number": r["match_number"], "error": str(exc)})
                continue
            if not found:
                continue
            conn.execute(
                "UPDATE fixtures SET home_score=?, away_score=? WHERE match_number=?",
                (found["home_score"], found["away_score"], r["match_number"]),
            )
            updated += 1
    return {"checked": checked, "candidates": len(rows), "updated": updated,
            "skipped_recent_or_future": True, "stopped": stopped, "errors": errors[:5],
            "sources": ["ESPN/Yahoo/FIFA公开页搜索", "中文新闻搜索后备"]}


def resilient_refresh(*, with_news: bool = False) -> dict:
    """一键刷新，遇到单步失败不中断。

    返回 {status, steps, seconds}；status=ok/partial/failed。
    """
    started = time.monotonic()
    init_db()
    steps = []

    steps.append(_run_step("history", "抓取国际赛历史结果", ingest_international_results))
    steps.append(_run_step("fixtures", "更新 2026 赛程", fetch_and_store_fixtures))
    steps.append(_run_step("backfill", "回填 fixtures 赛果", backfill_fixture_scores))
    steps.append(_run_step("live_scores", "联网补全世界杯赛果", refresh_live_fixture_scores))
    steps.append(_run_step("export", "导出 data/wc_results.json", export_results_json))

    trained_model = None

    def train():
        nonlocal trained_model
        trained_model = train_and_save()
        return {"teams": len(trained_model.teams)}

    train_step = _run_step("train", "重训 Dixon-Coles + Elo", train, critical=True)
    steps.append(train_step)
    steps.append(_run_step("knockout_review", "补全淘汰赛赛后分场复盘数据",
                           refresh_knockout_postmatch_insights))

    def adjust():
        model = trained_model
        if model is None:
            try:
                model = get_model(adjusted=False)
            except Exception as exc:
                raise RuntimeError(f"训练失败且无可用缓存模型，跳过赛中修正：{exc}") from exc
        return {"teams": len(recompute(model, with_news=with_news))}

    steps.append(_run_step("adjustments", "重算赛中实力修正", adjust))

    failed = [s for s in steps if not s["ok"]]
    critical_failed = [s for s in failed if s.get("critical")]
    if not failed:
        status = "ok"
    elif critical_failed and len(failed) == len(steps):
        status = "failed"
    else:
        status = "partial"
    return {"status": status, "steps": steps, "seconds": round(time.monotonic() - started, 2)}


def format_refresh_summary(result: dict) -> str:
    labels = {"ok": "完成", "partial": "部分完成", "failed": "失败"}
    lines = [f"刷新{labels.get(result.get('status'), result.get('status'))}，总耗时 {result.get('seconds', 0)}s。"]
    for step in result.get("steps", []):
        mark = "OK" if step.get("ok") else "FAIL"
        detail = step.get("result") if step.get("ok") else step.get("error")
        lines.append(f"[{mark}] {step.get('label')} ({step.get('seconds')}s): {detail}")
    return "\n".join(lines)
