"""赔率历史快照：把每次拉取的赔率（h2h / 让球 / 大小球）按时间落库，供「赔率走势」展示。

v1 手动驱动：用户在页面拉取赔率时写入快照，趋势随多次拉取累积；不含自动定时抓取。
表结构为长表（一行一选项），便于多市场多盘口线扩展。
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone

from wc2026.data.db import get_conn

_INSERT = ("INSERT INTO odds_snapshots "
           "(captured_at, home_team, away_team, market, selection, line, odds) "
           "VALUES (?,?,?,?,?,?,?)")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def flatten_event_odds(event_odds: dict) -> list[tuple]:
    """parse_event_markets 输出 → [(market, selection, line, odds)]，只取 odds>1。"""
    rows = []
    h2h = event_odds.get("h2h") or {}
    for sel in ("home", "draw", "away"):
        o = h2h.get(sel)
        if o and o > 1.0:
            rows.append(("h2h", sel, None, float(o)))
    for line, d in (event_odds.get("spreads") or {}).items():
        for sel in ("home", "away"):
            o = (d or {}).get(sel)
            if o and o > 1.0:
                rows.append(("spreads", sel, str(line), float(o)))
    for line, d in (event_odds.get("totals") or {}).items():
        for sel in ("over", "under"):
            o = (d or {}).get(sel)
            if o and o > 1.0:
                rows.append(("totals", sel, str(line), float(o)))
    return rows


def record_event_snapshot(home: str, away: str, event_odds: dict,
                          captured_at: str | None = None, conn=None) -> int:
    """写入单场一次快照，返回写入行数。conn 为可注入连接（测试用）。"""
    rows = flatten_event_odds(event_odds)
    if not rows:
        return 0
    ts = captured_at or _now()
    data = [(ts, home, away, m, s, ln, o) for (m, s, ln, o) in rows]
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        c.executemany(_INSERT, data)
    return len(data)


def record_event_odds_map(odds_map: dict, captured_at: str | None = None) -> int:
    """批量写入多场快照（价值扫描场景），返回总行数。"""
    ts = captured_at or _now()
    total = 0
    with get_conn() as c:
        for (home, away), ev in odds_map.items():
            rows = flatten_event_odds(ev)
            if rows:
                c.executemany(_INSERT, [(ts, home, away, m, s, ln, o) for (m, s, ln, o) in rows])
                total += len(rows)
    return total


def available_lines(home: str, away: str, market: str, conn=None) -> list[str]:
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        rows = c.execute(
            "SELECT DISTINCT line FROM odds_snapshots "
            "WHERE home_team=? AND away_team=? AND market=? AND line IS NOT NULL ORDER BY line",
            (home, away, market)).fetchall()
    return [r[0] for r in rows]


def load_history(home: str, away: str, market: str, line: str | None = None, conn=None) -> dict:
    """返回 {selection: [(captured_at, odds), ...]}，按时间升序。"""
    query = ("SELECT captured_at, selection, odds FROM odds_snapshots "
             "WHERE home_team=? AND away_team=? AND market=?")
    params: list = [home, away, market]
    if line is not None:
        query += " AND line=?"
        params.append(line)
    query += " ORDER BY captured_at"
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        rows = c.execute(query, params).fetchall()
    series: dict = {}
    for r in rows:
        series.setdefault(r["selection"], []).append((r["captured_at"], r["odds"]))
    return series
