"""价值与凯利：对比模型概率与盘口赔率，找"价值盘"并给注码建议。

- 剔水(去 vig)：把含水位的盘口赔率归一为隐含概率
- 价值 edge = 模型概率 × 赔率 − 1（>0 表示长期正期望）
- 凯利比例：建议下注占资金的比例；默认 1/4 分数凯利以降低波动
输入赔率均为十进制(欧赔)。
"""
from __future__ import annotations


def implied_probs(odds: dict) -> dict:
    """盘口赔率 → 隐含概率(raw)与剔水后(fair)，及水位 overround。"""
    raw = {k: (1.0 / v) for k, v in odds.items() if v and v > 1.0}
    s = sum(raw.values())
    fair = {k: (v / s) for k, v in raw.items()} if s > 0 else {}
    return {"raw": raw, "fair": fair, "overround": round(s, 4)}


def value_and_kelly(model_p: dict, odds: dict, kelly_fraction: float = 0.25) -> dict:
    """对每个结果计算 edge 与凯利比例。"""
    out = {}
    for k, p in model_p.items():
        o = odds.get(k)
        if not o or o <= 1.0:
            out[k] = None
            continue
        b = o - 1.0
        edge = p * o - 1.0
        kelly_full = edge / b if b > 0 else 0.0
        out[k] = {
            "odds": o,
            "model_prob": p,
            "edge": edge,                       # >0 有价值
            "value": edge > 0,
            "kelly_full": max(kelly_full, 0.0),
            "kelly_frac": max(kelly_full, 0.0) * kelly_fraction,
        }
    return out


def allocate_stakes(candidates: list[dict], bankroll: float, kelly_fraction: float = 0.25,
                    max_total_fraction: float = 1.0) -> list[dict]:
    """按正期望候选项的分数凯利权重，把指定金额分配为下注建议。

    candidates 每项至少包含 key/label/market/model_prob/odds；让球等可退本金市场可传 push_prob。
    返回只包含 edge>0 且建议权重大于 0 的项，stake 合计不超过 bankroll * max_total_fraction。
    """
    if bankroll <= 0:
        return []
    rows = []
    for item in candidates:
        p = float(item.get("model_prob") or 0.0)
        push = float(item.get("push_prob") or 0.0)
        odds = float(item.get("odds") or 0.0)
        if p <= 0 or odds <= 1.0:
            continue
        b = odds - 1.0
        loss_prob = max(0.0, 1.0 - p - push)
        edge = p * b - loss_prob
        kelly_full = edge / b if b > 0 else 0.0
        weight = max(kelly_full, 0.0) * kelly_fraction
        if edge <= 0 or weight <= 0:
            continue
        rows.append({
            **item,
            "model_prob": p,
            "push_prob": push,
            "odds": odds,
            "edge": edge,
            "kelly_full": max(kelly_full, 0.0),
            "kelly_frac": weight,
        })
    total_weight = sum(r["kelly_frac"] for r in rows)
    if total_weight <= 0:
        return []
    stake_pool = bankroll * max(0.0, min(max_total_fraction, 1.0))
    for r in rows:
        r["allocation_pct"] = r["kelly_frac"] / total_weight
        r["stake"] = stake_pool * r["allocation_pct"]
        r["expected_profit"] = r["stake"] * r["edge"]
    rows.sort(key=lambda r: (r["stake"], r["edge"]), reverse=True)
    return rows


def parlay_summary(legs: list[dict], stake: float) -> dict:
    """串关汇总：组合概率=各关概率相乘，组合赔率=各关赔率相乘。"""
    valid = []
    combined_prob = 1.0
    combined_odds = 1.0
    for leg in legs:
        p = float(leg.get("model_prob") or 0.0)
        odds = float(leg.get("odds") or 0.0)
        if p <= 0 or odds <= 1.0:
            continue
        row = {**leg, "model_prob": p, "odds": odds}
        row["edge"] = p * odds - 1.0
        valid.append(row)
        combined_prob *= p
        combined_odds *= odds
    if not valid:
        return {
            "legs": [],
            "combined_prob": 0,
            "combined_odds": 0,
            "edge": 0,
            "potential_return": 0,
            "expected_profit": 0,
        }
    edge = combined_prob * combined_odds - 1.0
    potential_return = max(stake, 0) * combined_odds
    return {
        "legs": valid,
        "combined_prob": combined_prob,
        "combined_odds": combined_odds,
        "edge": edge,
        "potential_return": potential_return,
        "expected_profit": max(stake, 0) * edge,
    }


def analyze_1x2(model_1x2: dict, odds: dict, kelly_fraction: float = 0.25) -> dict:
    """便捷：1X2 价值分析。model_1x2/odds 形如 {'home':..,'draw':..,'away':..}。"""
    return {
        "implied": implied_probs(odds),
        "results": value_and_kelly(model_1x2, odds, kelly_fraction),
    }


def scan_value(model, odds_map: dict, neutral: bool = True,
               kelly_fraction: float = 0.25, blend: float = 1.0,
               min_prob: float = 0.10, max_odds: float = 7.0) -> list:
    """对多场赔率扫描价值盘。

    odds_map: {(home_lib, away_lib): {"home":赔率,"draw":赔率,"away":赔率}}。
    blend: 模型权重(0~1)。<1 时把模型概率向市场剔水概率收缩，滤除模型偏差导致的假价值。
    min_prob / max_odds: 过滤"彩票型"长尾——超低概率×超高赔率会把微小误差放大成虚假巨额 edge。
    返回按 edge 降序的有价值项(edge>0)。
    """
    from wc2026.markets import derive
    out = []
    for (h, a), odds in odds_map.items():
        if not (model.has_team(h) and model.has_team(a)):
            continue
        if any((not odds.get(k) or odds[k] <= 1.0) for k in ("home", "draw", "away")):
            continue
        x = derive.outcomes_1x2(model.score_matrix(h, a, neutral))
        if blend < 1.0:
            fair = implied_probs(odds)["fair"]
            x = {k: blend * x[k] + (1 - blend) * fair.get(k, x[k]) for k in x}
            s = sum(x.values()) or 1.0
            x = {k: v / s for k, v in x.items()}
        for k, r in value_and_kelly(x, odds, kelly_fraction).items():
            if (r and r["value"] and r["model_prob"] >= min_prob and r["odds"] <= max_odds):
                out.append({"home": h, "away": a, "outcome": k,
                            "model_prob": r["model_prob"], "odds": r["odds"],
                            "edge": r["edge"], "kelly_frac": r["kelly_frac"]})
    out.sort(key=lambda r: r["edge"], reverse=True)
    return out
