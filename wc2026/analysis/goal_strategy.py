"""进球区间策略推荐：基于「放弃 1-3 球高风险，聚焦 2-3 球与 3-4 球」的经验。

从模型比分矩阵算总进球分布与各区间概率，结合期望进球与攻防均衡，给出推荐区间与理由清单。
盘口 / 水位类条件（大球水位<0.95、优选盘口等）需真实赔率，清单中标注「需盘口确认」。
模型可验证的条件（如「1 球赔率>4.5」等价于「P(1球)<22.2%」）直接由概率判断。
"""
from __future__ import annotations

import numpy as np


def total_goals_dist(mat) -> dict:
    """比分矩阵 → {总进球数: 概率}。"""
    mat = np.asarray(mat, dtype=float)
    rows, cols = mat.shape
    tot = np.add.outer(np.arange(rows), np.arange(cols))
    maxk = int(tot.max())
    return {k: float(mat[tot == k].sum()) for k in range(maxk + 1)}


def band_probs(dist: dict) -> dict:
    """从总进球分布算各区间概率（2-3 与 3-4 有意重叠，对应两种打法）。"""
    g = lambda *ks: float(sum(dist.get(k, 0.0) for k in ks))
    return {
        "0-1": g(0, 1), "2-3": g(2, 3), "3-4": g(3, 4),
        "4+": float(sum(v for k, v in dist.items() if k >= 4)),
        "p1": dist.get(1, 0.0), "p2": dist.get(2, 0.0),
        "p3": dist.get(3, 0.0), "p4": dist.get(4, 0.0),
    }


def _status(ok: bool) -> str:
    return "满足" if ok else "不满足"


def recommend(mat, lam: float, mu: float) -> dict:
    """返回 {recommend, confidence, xg_total, xg_home, xg_away, balance, probs, reasons, checklist}。

    recommend ∈ {"2-3球", "3-4球", "回避"}；checklist 每项 (条件, 状态)，状态含「需盘口确认」。
    """
    bp = band_probs(total_goals_dist(mat))
    xg, mx, bal = lam + mu, max(lam, mu), abs(lam - mu)
    p01, p1, p2, p3, p4 = bp["0-1"], bp["p1"], bp["p2"], bp["p3"], bp["p4"]
    reasons: list[str] = []

    if xg < 1.9 or p01 >= 0.42:
        return {
            "recommend": "回避", "confidence": p01,
            "xg_total": xg, "xg_home": lam, "xg_away": mu, "balance": bal, "probs": bp,
            "reasons": [f"期望总进球 {xg:.2f}、0-1 球概率 {p01:.0%} 偏低，闷局/低进球风险高；"
                        "按策略回避 1-3 球高风险区间，本场不建议进球区间投注。"],
            "checklist": [],
        }

    fit34 = xg >= 2.7 and mx > 1.5
    fit23 = 1.9 <= xg <= 2.9 and bal <= 0.8
    if fit34 and (not fit23 or bp["3-4"] >= bp["2-3"]):
        rec = "3-4球"
    elif fit23:
        rec = "2-3球"
    else:
        rec = "3-4球" if bp["3-4"] >= bp["2-3"] else "2-3球"
        reasons.append("两套打法条件均不完全满足，按区间概率给倾向，仅供参考。")

    if rec == "2-3球":
        reasons.append(f"期望总进球 {xg:.2f}、两队较均衡（差 {bal:.2f}），常见 1-1/2-0/2-1，适合中上游 vs 中游。")
        checklist = [
            ("攻防均衡、非极端风格", _status(bal <= 0.8)),
            ("期望总进球适中（约 2.0-2.8）", _status(2.0 <= xg <= 2.8)),
            ("1 球概率偏低（≈1 球赔率>4.5）", _status(p1 < 0.2222)),
            ("2 球 / 3 球概率接近", _status(abs(p2 - p3) <= 0.05)),
            ("盘口 2.25 / 2.5、大球水位<0.95", "需盘口确认"),
        ]
    else:  # 3-4球
        reasons.append(f"期望总进球 {xg:.2f}、强侧期望进球 {mx:.2f}（>1.5），常见 3-1/2-2，"
                       "适合强队主场 / 淘汰赛 / 后防薄弱方。")
        checklist = [
            ("至少一队期望进球>1.5", _status(mx > 1.5)),
            ("期望总进球偏高（≥2.7）", _status(xg >= 2.7)),
            ("2 球概率偏低（≈2 球赔率>3.0）", _status(p2 < 0.3333)),
            ("3 球 / 4 球概率接近", _status(abs(p3 - p4) <= 0.05)),
            ("盘口≥2.5（优选 2.75）、大球水位<0.90", "需盘口确认"),
        ]

    return {
        "recommend": rec, "confidence": bp[rec.replace("球", "")],
        "xg_total": xg, "xg_home": lam, "xg_away": mu, "balance": bal, "probs": bp,
        "reasons": reasons, "checklist": checklist,
    }
