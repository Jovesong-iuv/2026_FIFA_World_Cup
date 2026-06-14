"""世界杯历史：从 matches 表（tournament='FIFA World Cup'）提取两队的世界杯交锋与各自历届战绩。

matches 表无晋级轮次字段，因此只给「参赛年份 + 胜负净球记录 + 两队世界杯交锋时间轴」，
不臆测「打入决赛/夺冠」等最佳成绩。纯历史展示，样本有限，仅作辅助参考。
"""
from __future__ import annotations

from wc2026.data.db import get_conn

WC = "FIFA World Cup"


def summarize_record(rows: list[dict], team: str) -> dict:
    """聚合某队的世界杯战绩。rows 为该队的世界杯比赛行（含 date/home_team/away_team/比分）。"""
    w = d = l = gf = ga = 0
    years = set()
    for r in rows:
        is_home = r["home_team"] == team
        ts = r["home_score"] if is_home else r["away_score"]
        os_ = r["away_score"] if is_home else r["home_score"]
        if ts is None or os_ is None:
            continue
        gf += ts
        ga += os_
        if ts > os_:
            w += 1
        elif ts == os_:
            d += 1
        else:
            l += 1
        years.add(int(str(r["date"])[:4]))
    return {"team": team, "matches": w + d + l, "w": w, "d": d, "l": l, "gf": gf, "ga": ga,
            "editions": len(years), "first": min(years) if years else None,
            "last": max(years) if years else None}


def meeting_row(r: dict) -> dict:
    """把一场世界杯交锋格式化为时间轴条目。"""
    return {"year": int(str(r["date"])[:4]), "date": r["date"], "country": r.get("country"),
            "home": r["home_team"], "away": r["away_team"],
            "score": f'{r["home_score"]}-{r["away_score"]}'}


def wc_head_to_head(team_a: str, team_b: str) -> list[dict]:
    """两队的世界杯交锋时间轴（按时间倒序）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, home_team, away_team, home_score, away_score, country "
            "FROM matches WHERE tournament=? AND "
            "((home_team=? AND away_team=?) OR (home_team=? AND away_team=?)) "
            "ORDER BY date DESC", (WC, team_a, team_b, team_b, team_a)).fetchall()
    return [meeting_row(dict(r)) for r in rows]


def wc_record(team: str) -> dict:
    """某队历届世界杯战绩汇总。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, home_team, away_team, home_score, away_score "
            "FROM matches WHERE tournament=? AND (home_team=? OR away_team=?) ORDER BY date",
            (WC, team, team)).fetchall()
    return summarize_record([dict(r) for r in rows], team)
