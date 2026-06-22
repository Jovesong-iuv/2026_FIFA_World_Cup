"""稳健刷新流水线：每步独立失败、记录耗时，并尽量继续后续步骤。"""
from __future__ import annotations

import time
from collections.abc import Callable

from wc2026.analysis.adjustments import recompute
from wc2026.data.db import init_db
from wc2026.data.ingest import ingest_international_results
from wc2026.data.results import backfill_fixture_scores, export_results_json
from wc2026.data.sources.fixtures_2026 import fetch_and_store_fixtures
from wc2026.models.predictor import get_model, train_and_save


def _run_step(name: str, label: str, fn: Callable, *, critical: bool = False) -> dict:
    t0 = time.monotonic()
    try:
        value = fn()
        return {"name": name, "label": label, "ok": True, "seconds": round(time.monotonic() - t0, 2),
                "result": value, "critical": critical}
    except Exception as exc:
        return {"name": name, "label": label, "ok": False, "seconds": round(time.monotonic() - t0, 2),
                "error": str(exc), "critical": critical}


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
    steps.append(_run_step("export", "导出 data/wc_results.json", export_results_json))

    trained_model = None

    def train():
        nonlocal trained_model
        trained_model = train_and_save()
        return {"teams": len(trained_model.teams)}

    train_step = _run_step("train", "重训 Dixon-Coles + Elo", train, critical=True)
    steps.append(train_step)

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
