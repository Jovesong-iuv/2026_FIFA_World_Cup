"""投注台账：记录实际下注并结算，统计 ROI / 收益率 / 命中率 / 盈亏曲线 / 最大回撤。

pnl 由 状态+赔率+本金 即时计算（不落库），改状态即自动重算。summary 为纯函数，便于测试。
仅供所有者使用。conn 参数用于测试注入内存库。
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime

from wc2026.data.db import get_conn

STATUSES = ("pending", "won", "lost", "push")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def add_bet(match: str, market: str, selection: str, odds: float, stake: float,
            note: str = "", conn=None) -> None:
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        c.execute(
            "INSERT INTO bets (created_at, match, market, selection, odds, stake, status, note) "
            "VALUES (?,?,?,?,?,?, 'pending', ?)",
            (_now(), match, market, selection, float(odds), float(stake), note))


def set_status(bet_id: int, status: str, conn=None) -> None:
    if status not in STATUSES:
        return
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        c.execute("UPDATE bets SET status=? WHERE id=?", (status, bet_id))


def set_close(bet_id: int, close_odds, conn=None) -> None:
    """记录收盘赔率（用于 CLV）。<=1 或空则清空。"""
    val = float(close_odds) if close_odds and float(close_odds) > 1.0 else None
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        c.execute("UPDATE bets SET close_odds=? WHERE id=?", (val, bet_id))


def delete_bet(bet_id: int, conn=None) -> None:
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        c.execute("DELETE FROM bets WHERE id=?", (bet_id,))


def list_bets(conn=None) -> list[dict]:
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        rows = c.execute(
            "SELECT id, created_at, match, market, selection, odds, stake, status, note, close_odds "
            "FROM bets ORDER BY created_at, id").fetchall()
    return [dict(r) for r in rows]


def pnl_of(bet: dict) -> float:
    """单注盈亏：won=本金×(赔率-1)，lost=-本金，push/pending=0。"""
    stake = float(bet.get("stake") or 0.0)
    odds = float(bet.get("odds") or 0.0)
    status = bet.get("status")
    if status == "won":
        return stake * (odds - 1.0)
    if status == "lost":
        return -stake
    return 0.0


def summary(bets: list[dict]) -> dict:
    """汇总。返回 staked/returned/profit/roi/settled/wins/win_rate/pending/curve/max_drawdown。

    curve: 按时间顺序的累计盈亏列表（仅已结算注）；max_drawdown 为该曲线最大回撤（正数）。
    roi = 已结算盈亏 / 已结算本金。
    """
    settled = [b for b in bets if b.get("status") in ("won", "lost", "push")]
    pending = [b for b in bets if b.get("status") == "pending"]
    staked = sum(float(b.get("stake") or 0.0) for b in settled)
    profit = sum(pnl_of(b) for b in settled)
    wins = sum(1 for b in settled if b.get("status") == "won")
    decided = [b for b in settled if b.get("status") in ("won", "lost")]  # push 不计胜率
    curve, run, peak, max_dd = [], 0.0, 0.0, 0.0
    for b in settled:
        run += pnl_of(b)
        curve.append(round(run, 2))
        peak = max(peak, run)
        max_dd = max(max_dd, peak - run)
    # CLV：你的赔率 vs 收盘赔率（仅记录了收盘赔率的注）
    clv_bets = [b for b in bets if b.get("close_odds") and float(b.get("close_odds")) > 1.0
                and float(b.get("odds") or 0) > 1.0]
    clvs = [float(b["odds"]) / float(b["close_odds"]) - 1.0 for b in clv_bets]
    beat = sum(1 for v in clvs if v > 0)
    return {
        "total": len(bets),
        "settled": len(settled),
        "pending": len(pending),
        "staked": staked,
        "returned": staked + profit,
        "profit": profit,
        "roi": (profit / staked) if staked > 0 else 0.0,
        "wins": wins,
        "win_rate": (wins / len(decided)) if decided else 0.0,
        "pending_stake": sum(float(b.get("stake") or 0.0) for b in pending),
        "curve": curve,
        "max_drawdown": round(max_dd, 2),
        "clv_count": len(clv_bets),
        "beat_close_rate": (beat / len(clvs)) if clvs else 0.0,
        "avg_clv": (sum(clvs) / len(clvs)) if clvs else 0.0,
    }
