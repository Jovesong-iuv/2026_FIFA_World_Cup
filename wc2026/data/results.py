"""赛果回填：把 matches 表（ingest 的真实赛果）写入 fixtures 比分，并导出可提交的 wc_results.json。

- fixtures 的 home_score/away_score 驱动「完赛比分 / 小组出线重算」。
- matches 表含已踢比赛真实比分，按 队名 + 日期(±2 天) 匹配回填。
- 导出 JSON：部署服务器的 DB 可能为空（临时文件系统），用提交进仓库的 wc_results.json 叠加显示赛果。
"""
from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

from wc2026.config import settings
from wc2026.data.db import get_conn

RESULTS_JSON = settings.data_dir / "wc_results.json"

_LOOKUP = (
    "SELECT home_score, away_score FROM matches "
    "WHERE home_team=? AND away_team=? AND home_score IS NOT NULL "
    "AND ABS(julianday(date) - julianday(substr(?,1,10))) <= 2 "
    "ORDER BY ABS(julianday(date) - julianday(substr(?,1,10))) LIMIT 1"
)


def backfill_fixture_scores(conn=None) -> int:
    """用 matches 真实赛果回填 fixtures 缺失的比分，返回回填场次数。"""
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        todo = c.execute(
            "SELECT match_number, home_team, away_team, date_utc FROM fixtures "
            "WHERE predictable=1 AND home_score IS NULL").fetchall()
        filled = 0
        for r in todo:
            m = c.execute(_LOOKUP, (r["home_team"], r["away_team"], r["date_utc"], r["date_utc"])).fetchone()
            if m:
                c.execute("UPDATE fixtures SET home_score=?, away_score=? WHERE match_number=?",
                          (m["home_score"], m["away_score"], r["match_number"]))
                filled += 1
    return filled


def export_results_json(path: Path | None = None, conn=None) -> int:
    """把 fixtures 已有比分导出到 wc_results.json（可提交，供服务器叠加）。返回导出场次数。"""
    out = Path(path) if path else RESULTS_JSON
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        rows = c.execute(
            "SELECT match_number, home_score, away_score FROM fixtures "
            "WHERE home_score IS NOT NULL AND away_score IS NOT NULL").fetchall()
    data = {str(r["match_number"]): [r["home_score"], r["away_score"]] for r in rows}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"results": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(data)


def load_results_overlay(path: Path | None = None) -> dict:
    """读取 wc_results.json → {match_number(int): (home_score, away_score)}；缺失返回 {}。"""
    src = Path(path) if path else RESULTS_JSON
    if not src.exists():
        return {}
    try:
        data = json.loads(src.read_text(encoding="utf-8")).get("results", {})
        return {int(k): (v[0], v[1]) for k, v in data.items() if isinstance(v, list) and len(v) == 2}
    except Exception:
        return {}
