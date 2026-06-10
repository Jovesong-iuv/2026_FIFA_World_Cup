"""证据：从历史库提取双方交锋(H2H)与各队近期战绩。

这些是"为什么"的事实支撑，完全基于已有历史数据，不依赖外部/LLM。
所有 team 参数均为历史库标准队名（英文）。
"""
from __future__ import annotations

from wc2026.data.db import get_conn


def head_to_head(team_a: str, team_b: str, limit: int = 10) -> dict:
    """双方历史交锋，统计从 team_a 视角的胜平负与场均进球。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, home_team, away_team, home_score, away_score, tournament "
            "FROM matches WHERE (home_team=? AND away_team=?) OR (home_team=? AND away_team=?) "
            "ORDER BY date DESC",
            (team_a, team_b, team_b, team_a),
        ).fetchall()

    w = d = l = gf = ga = 0
    recent = []
    for r in rows:
        if r["home_team"] == team_a:
            a_s, b_s = r["home_score"], r["away_score"]
        else:
            a_s, b_s = r["away_score"], r["home_score"]
        gf += a_s
        ga += b_s
        if a_s > b_s:
            w += 1
        elif a_s == b_s:
            d += 1
        else:
            l += 1
        if len(recent) < limit:
            recent.append({
                "date": r["date"], "home": r["home_team"], "away": r["away_team"],
                "score": f"{r['home_score']}-{r['away_score']}", "tournament": r["tournament"],
            })

    total = len(rows)
    return {
        "team_a": team_a, "team_b": team_b, "total": total,
        "a_win": w, "draw": d, "a_loss": l,
        "avg_gf": round(gf / total, 2) if total else 0.0,
        "avg_ga": round(ga / total, 2) if total else 0.0,
        "recent": recent,
    }


def recent_form(team: str, limit: int = 6) -> dict:
    """某队最近 limit 场战绩（含主客、对手、比分、胜平负）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT date, home_team, away_team, home_score, away_score, tournament "
            "FROM matches WHERE home_team=? OR away_team=? ORDER BY date DESC LIMIT ?",
            (team, team, limit),
        ).fetchall()

    w = d = l = gf = ga = 0
    matches = []
    for r in rows:
        if r["home_team"] == team:
            ts, os_, opp, ha = r["home_score"], r["away_score"], r["away_team"], "主"
        else:
            ts, os_, opp, ha = r["away_score"], r["home_score"], r["home_team"], "客"
        gf += ts
        ga += os_
        outcome = "胜" if ts > os_ else ("平" if ts == os_ else "负")
        w += outcome == "胜"
        d += outcome == "平"
        l += outcome == "负"
        matches.append({"date": r["date"], "opponent": opp, "ha": ha,
                        "score": f"{ts}-{os_}", "outcome": outcome})

    return {"team": team, "n": len(matches), "w": w, "d": d, "l": l,
            "gf": gf, "ga": ga, "matches": matches}
