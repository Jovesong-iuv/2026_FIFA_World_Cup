"""凯利下注的资金风险模拟：在固定边际/赔率/凯利比例下反复下注，蒙特卡洛资金曲线。

把「连黑 N 场停手」量化成 破产概率 / 回撤分布。纯数值，不联网。
单注用分数凯利下注当前资金的固定比例 f；胜则 ×(1+f·(odds-1))，负则 ×(1-f)。
"""
from __future__ import annotations

import numpy as np


def kelly_fraction(p: float, odds: float) -> float:
    """全凯利比例 = edge / (odds-1)，下限 0。"""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    return max(0.0, (p * odds - 1.0) / b)


def bankroll_sim(p: float, odds: float, fraction: float, n_bets: int = 50,
                 n_sims: int = 5000, ruin_level: float = 0.5, seed: int = 12345) -> dict:
    """模拟 n_bets 注后的资金分布（起始 1.0）。

    fraction：实际下注的资金比例（如 1/4 凯利 = kelly_fraction*0.25）。
    返回 p_profit / median_final / p10 / p90 / p_drawdown_20 / risk_of_ruin / median_max_drawdown。
    risk_of_ruin：过程中任一时点资金跌破 ruin_level（默认 50%）的概率。
    """
    f = max(0.0, min(float(fraction), 1.0))
    if f == 0 or n_bets <= 0:
        return {"p_profit": 0.0, "median_final": 1.0, "p10": 1.0, "p90": 1.0,
                "p_drawdown_20": 0.0, "risk_of_ruin": 0.0, "median_max_drawdown": 0.0, "fraction": f}
    rng = np.random.default_rng(seed)
    wins = rng.random((n_sims, n_bets)) < p
    step = np.where(wins, 1.0 + f * (odds - 1.0), 1.0 - f)
    bankroll = np.cumprod(step, axis=1)
    bankroll = np.hstack([np.ones((n_sims, 1)), bankroll])  # 含起点
    final = bankroll[:, -1]
    running_peak = np.maximum.accumulate(bankroll, axis=1)
    drawdown = 1.0 - bankroll / running_peak           # 各时点回撤
    max_dd = drawdown.max(axis=1)
    troughs = bankroll.min(axis=1)
    return {
        "fraction": f,
        "p_profit": float((final > 1.0).mean()),
        "median_final": float(np.median(final)),
        "p10": float(np.percentile(final, 10)),
        "p90": float(np.percentile(final, 90)),
        "p_drawdown_20": float((max_dd >= 0.20).mean()),
        "risk_of_ruin": float((troughs < ruin_level).mean()),
        "median_max_drawdown": float(np.median(max_dd)),
    }
