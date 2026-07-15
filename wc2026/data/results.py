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
RESULT_METADATA = (
    "regulation_home_score", "regulation_away_score", "final_home_score", "final_away_score",
    "penalty_home_score", "penalty_away_score", "result_status", "winner_team",
    "result_source", "source_event_id", "result_fetched_at", "event_flags", "match_stats_json",
)


def regulation_score(fixture: dict) -> tuple[int, int] | None:
    """Return a verified regulation-time score; never infer it from an unknown knockout total."""
    rh, ra = fixture.get("regulation_home_score"), fixture.get("regulation_away_score")
    if rh is not None and ra is not None:
        return int(rh), int(ra)
    try:
        knockout = int(fixture.get("round_number") or 0) >= 4
    except (TypeError, ValueError):
        knockout = False
    if knockout:
        return None
    home, away = fixture.get("home_score"), fixture.get("away_score")
    return (int(home), int(away)) if home is not None and away is not None else None

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
        available = {r[1] for r in c.execute("PRAGMA table_info(fixtures)")}
        metadata = [name for name in RESULT_METADATA if name in available]
        columns = ["match_number", "home_score", "away_score", *metadata]
        rows = c.execute(
            f"SELECT {','.join(columns)} FROM fixtures "
            "WHERE home_score IS NOT NULL AND away_score IS NOT NULL").fetchall()
    data = {}
    for row in rows:
        extra = {name: row[name] for name in metadata if row[name] is not None}
        data[str(row["match_number"])] = ({"home_score": row["home_score"],
                                           "away_score": row["away_score"], **extra}
                                          if extra else [row["home_score"], row["away_score"]])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"results": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(data)


def load_results_overlay(path: Path | None = None) -> dict:
    """Read old score arrays and new result metadata objects."""
    src = Path(path) if path else RESULTS_JSON
    if not src.exists():
        return {}
    try:
        data = json.loads(src.read_text(encoding="utf-8")).get("results", {})
        out = {}
        for key, value in data.items():
            if isinstance(value, list) and len(value) == 2:
                out[int(key)] = (value[0], value[1])
            elif isinstance(value, dict) and value.get("home_score") is not None \
                    and value.get("away_score") is not None:
                out[int(key)] = dict(value)
        return out
    except Exception:
        return {}


def apply_results_overlay(fixtures: list[dict], path: Path | None = None) -> list[dict]:
    """把 wc_results.json 叠加到 fixture 行；数据库已有比分优先。"""
    overlay = load_results_overlay(path)
    if not overlay:
        return [dict(f) for f in fixtures]
    out = []
    for f in fixtures:
        row = dict(f)
        if row.get("predictable") in (0, False):
            out.append(row)
            continue
        score = overlay.get(int(row["match_number"])) if row.get("match_number") is not None else None
        if isinstance(score, tuple):
            if row.get("home_score") is None or row.get("away_score") is None:
                row["home_score"], row["away_score"] = score
        elif isinstance(score, dict):
            for key, value in score.items():
                if value is not None and row.get(key) is None:
                    row[key] = value
        out.append(row)
    return out
