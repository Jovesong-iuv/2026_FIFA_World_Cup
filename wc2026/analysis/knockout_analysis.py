"""淘汰赛单场扩展分析：90分钟、加时、点球、晋级与EV候选。

概率只从模型比分矩阵和可选市场赔率推导；新闻/网页数据作为证据层，不直接生成概率。
"""
from __future__ import annotations

import math

import numpy as np

from wc2026.data.team_names import zh
from wc2026.markets import derive


def _clip_prob(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def _poisson_matrix(lam: float, mu: float, max_goals: int = 7) -> np.ndarray:
    xs = np.arange(max_goals + 1)
    h = np.exp(-lam) * np.power(lam, xs) / np.array([math.factorial(int(i)) for i in xs])
    a = np.exp(-mu) * np.power(mu, xs) / np.array([math.factorial(int(i)) for i in xs])
    mat = np.outer(h, a)
    return mat / mat.sum()


def penalty_prob(home: str, away: str, *, home_bonus: float = 0.0, away_bonus: float = 0.0) -> dict:
    """点球胜率。基础各50%，可叠加门将/经验/心理等小幅修正。"""
    base = 0.5 + home_bonus - away_bonus
    home_p = _clip_prob(base)
    return {
        "home": round(home_p, 6),
        "away": round(1.0 - home_p, 6),
        "factors": "基础各50%，可由门将扑点、点球大战经验、心理优势做小幅修正",
        "label": f"{zh(home)} {home_p:.0%} / {zh(away)} {1.0 - home_p:.0%}",
    }


def extra_time_probabilities(lam: float, mu: float, rho_et: float = -0.10) -> dict:
    """加时赛三向概率。默认按90分钟λ的1/3再乘淘汰赛保守折扣。"""
    et_lam = max(0.03, lam / 3.0 * 0.90)
    et_mu = max(0.03, mu / 3.0 * 0.90)
    mat = _poisson_matrix(et_lam, et_mu)
    x = derive.outcomes_1x2(mat)
    return {
        "home": round(x["home"], 6),
        "draw": round(x["draw"], 6),
        "away": round(x["away"], 6),
        "lambda_home": round(et_lam, 3),
        "lambda_away": round(et_mu, 3),
        "rho_et": rho_et,
    }


def knockout_probabilities(mat: np.ndarray, lam: float, mu: float, home: str, away: str,
                           *, penalty_home_bonus: float = 0.0,
                           penalty_away_bonus: float = 0.0) -> dict:
    """90分钟 + 加时 + 点球的晋级概率完整分解。"""
    x90 = derive.outcomes_1x2(mat)
    et = extra_time_probabilities(lam, mu)
    pen = penalty_prob(home, away, home_bonus=penalty_home_bonus, away_bonus=penalty_away_bonus)
    home_adv = x90["home"] + x90["draw"] * et["home"] + x90["draw"] * et["draw"] * pen["home"]
    away_adv = x90["away"] + x90["draw"] * et["away"] + x90["draw"] * et["draw"] * pen["away"]
    total = home_adv + away_adv
    if total > 0:
        home_adv, away_adv = home_adv / total, away_adv / total
    h_cn, a_cn = zh(home), zh(away)
    return {
        "outcomes_90": {k: round(v, 6) for k, v in x90.items()},
        "extra_time": et,
        "penalties": pen,
        "advance": {
            "home": round(home_adv, 6),
            "away": round(away_adv, 6),
            "formula_home": (
                f"P({h_cn}晋级)=P(90赢)+P(平)*P(ET赢)+P(平)*P(ET平)*P(点球赢)"
            ),
            "formula_home_values": (
                f"{x90['home']:.1%}+{x90['draw']:.1%}×{et['home']:.1%}"
                f"+{x90['draw']:.1%}×{et['draw']:.1%}×{pen['home']:.1%}={home_adv:.1%}"
            ),
            "label": f"{h_cn} {home_adv:.1%} / {a_cn} {away_adv:.1%}",
        },
    }


def totals_90(mat: np.ndarray) -> dict:
    """90分钟大小球：2.5、亚洲2.75和进球区间。"""
    ou25 = derive.over_under(mat, 2.5)
    ou30 = derive.over_under(mat, 3.0)
    i, j = np.indices(mat.shape)
    total_goals = i + j
    dist = {
        "≤1球": float(mat[total_goals <= 1].sum()),
        "=2球": float(mat[total_goals == 2].sum()),
        "=3球": float(mat[total_goals == 3].sum()),
        "≥4球": float(mat[total_goals >= 4].sum()),
    }
    return {
        "lines": {
            "2.5": {"over": round(ou25["over"], 4), "under": round(ou25["under"], 4)},
            "2.75": {
                "over_full": round(float(mat[total_goals >= 4].sum()), 4),
                "over_half_win": round(float(mat[total_goals == 3].sum()), 4),
                "under_half_win": round(float(mat[total_goals == 3].sum()), 4),
                "under_full": round(float(mat[total_goals <= 2].sum()), 4),
                "push_3": round(ou30["push"], 4),
            },
        },
        "goal_distribution": {k: round(v, 4) for k, v in dist.items()},
        "note": "大小球仅计算90分钟，不含加时赛和点球。",
    }


def _fair(prob: float) -> float | None:
    return round(1.0 / prob, 2) if prob > 1e-9 else None


def _ev(prob: float, odds: float | None) -> float:
    odds = float(odds or 0)
    return round(prob * odds - 1.0, 3) if odds > 1.0 else 0.0


def ev_board(outcomes_90: dict, advance: dict, totals: dict, market_odds: dict | None,
             home: str, away: str, *, limit: int = 11) -> list[dict]:
    """候选下法按EV排序。市场赔率缺失时用公平赔率，EV为0。"""
    market_odds = market_odds or {}
    rows = [
        ("90分钟主胜", outcomes_90["home"], market_odds.get("home"), f"{zh(home)} 90分钟胜"),
        ("90分钟平局", outcomes_90["draw"], market_odds.get("draw"), "90分钟平局"),
        ("90分钟客胜", outcomes_90["away"], market_odds.get("away"), f"{zh(away)} 90分钟胜"),
        (f"{zh(home)}晋级", advance["home"], market_odds.get("home_advance"), f"{zh(home)}晋级"),
        (f"{zh(away)}晋级", advance["away"], market_odds.get("away_advance"), f"{zh(away)}晋级"),
        ("大2.5", totals["2.5"]["over"], market_odds.get("over_2_5"), "大于2.5球"),
        ("小2.5", totals["2.5"]["under"], market_odds.get("under_2_5"), "小于2.5球"),
        ("大2.75", totals["2.75"]["over_full"] + 0.5 * totals["2.75"]["over_half_win"],
         market_odds.get("over_2_75"), "亚洲2.75大球期望"),
        ("小2.75", totals["2.75"]["under_full"] + 0.5 * totals["2.75"]["under_half_win"],
         market_odds.get("under_2_75"), "亚洲2.75小球期望"),
    ]
    out = []
    for label, prob, odds, structure in rows:
        fair = _fair(prob)
        odds_used = float(odds) if odds and odds > 1.0 else fair
        ev = _ev(prob, odds_used if odds else None)
        out.append({
            "label": label,
            "prob": round(prob, 4),
            "probability_structure": structure,
            "fair_odds": fair,
            "market_odds": round(odds_used, 2) if odds_used else None,
            "ev": ev,
            "recommendation": "推荐" if ev > 0.03 else ("回避" if ev < -0.03 else "观察"),
        })
    out.sort(key=lambda r: r["ev"], reverse=True)
    return [dict(r, rank=i + 1) for i, r in enumerate(out[:limit])]


def build_knockout_payload(mat: np.ndarray, lam: float, mu: float, home: str, away: str,
                           *, market_odds: dict | None = None,
                           fatigue: dict | None = None) -> dict:
    ko = knockout_probabilities(mat, lam, mu, home, away)
    totals = totals_90(mat)
    ev = ev_board(ko["outcomes_90"], ko["advance"], totals["lines"], market_odds, home, away)
    return {
        **ko,
        "totals_90": totals,
        "ev_board": ev,
        "fatigue": fatigue or {},
        "analysis_summary": (
            f"{zh(home)}90分钟胜率{ko['outcomes_90']['home']:.1%}，"
            f"{zh(away)}90分钟胜率{ko['outcomes_90']['away']:.1%}；"
            f"若90分钟战平，加时赛主/平/客为"
            f"{ko['extra_time']['home']:.1%}/{ko['extra_time']['draw']:.1%}/{ko['extra_time']['away']:.1%}，"
            f"综合晋级概率为{ko['advance']['label']}。"
        ),
        "condition_triggers": [
            "若75分钟后仍落后，落后方强攻会提高尾段进球波动。",
            "若进入加时，淘汰赛经验、门将扑点能力与心理压力应作为点球修正因子。",
            "伤停、红牌、点球大战等事件应单独入账，避免过度改写常规实力。",
        ],
    }
