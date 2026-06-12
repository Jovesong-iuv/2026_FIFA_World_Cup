"""市场换算：由比分概率矩阵推导各投注市场的概率与公平赔率。

矩阵约定：mat[i, j] = P(主队进 i 球, 客队进 j 球)，行=主队，列=客队。
"""
from __future__ import annotations

import math

import numpy as np

_EPS = 1e-9


def to_fair_odds(prob: float) -> float:
    """概率 → 公平十进制赔率（无水位）。"""
    return float(1.0 / prob) if prob > _EPS else float("inf")


def outcomes_1x2(mat: np.ndarray) -> dict:
    """胜平负：主队胜=下三角，平=对角，客队胜=上三角。"""
    home = float(np.tril(mat, -1).sum())
    draw = float(np.trace(mat))
    away = float(np.triu(mat, 1).sum())
    return {"home": home, "draw": draw, "away": away}


def over_under(mat: np.ndarray, line: float = 2.5) -> dict:
    """大小球。整数盘(如 3.0)会有走盘 push。"""
    i, j = np.indices(mat.shape)
    tot = i + j
    return {
        "line": line,
        "over": float(mat[tot > line].sum()),
        "under": float(mat[tot < line].sum()),
        "push": float(mat[np.isclose(tot, line)].sum()),
    }


def both_teams_to_score(mat: np.ndarray) -> dict:
    yes = float(mat[1:, 1:].sum())
    return {"yes": yes, "no": float(1.0 - yes)}


def _single_ah(mat: np.ndarray, line: float) -> tuple[float, float, float]:
    """单一盘(2*line 为整数)从主队视角的 赢/走/输 概率。

    line 为主队让球数：负=主队让球(强队)，正=主队受让。
    结算 margin = (主队净胜球) + line。
    """
    i, j = np.indices(mat.shape)
    margin = (i - j) + line
    win = float(mat[margin > _EPS].sum())
    push = float(mat[np.abs(margin) <= _EPS].sum())
    loss = float(mat[margin < -_EPS].sum())
    return win, push, loss


def _split_lines(line: float) -> list[tuple[float, float]]:
    """四分之一盘(.25/.75)拆成两条半权重盘；整盘/半盘原样。"""
    if abs(line * 2 - round(line * 2)) < _EPS:
        return [(line, 1.0)]
    return [(line - 0.25, 0.5), (line + 0.25, 0.5)]


def asian_handicap(mat: np.ndarray, line: float) -> dict:
    """亚盘让球。支持整数/半球/四分之一球盘。

    四分之一盘下 win/push/loss 为两条半注的期望占比
    （体现"赢半/输半/走半"）。
    """
    win = push = loss = 0.0
    for ln, wt in _split_lines(line):
        w, p, l = _single_ah(mat, ln)
        win += wt * w
        push += wt * p
        loss += wt * l
    return {"line": line, "home_win": win, "push": push, "home_loss": loss}


def correct_score_top(mat: np.ndarray, n: int = 6) -> list[dict]:
    """最可能的前 n 个正确比分。"""
    flat = mat.flatten()
    cols = mat.shape[1]
    out = []
    for f in np.argsort(flat)[::-1][:n]:
        ii, jj = divmod(int(f), cols)
        out.append({"score": f"{ii}-{jj}", "prob": float(flat[f])})
    return out


def goal_bands(mat: np.ndarray) -> dict:
    """总进球数分组：0-1、2-3、4+。"""
    i, j = np.indices(mat.shape)
    tot = i + j
    return {
        "0-1球": float(mat[tot <= 1].sum()),
        "2-3球": float(mat[(tot >= 2) & (tot <= 3)].sum()),
        "4+球": float(mat[tot >= 4].sum()),
    }


def half_time_1x2(lam: float, mu: float) -> dict:
    """半场胜平负；用全场预期进球的 45/90 比例近似半场进球率。"""
    mat = _poisson_score_matrix(lam * 0.5, mu * 0.5)
    return outcomes_1x2(mat)


def half_full_time(lam: float, mu: float) -> dict:
    """半全场 9 选项；假设上下半场独立且进球率各占 50%。"""
    first = _poisson_score_matrix(lam * 0.5, mu * 0.5)
    second = _poisson_score_matrix(lam * 0.5, mu * 0.5)
    labels = {"home": "胜", "draw": "平", "away": "负"}
    out = {f"{a}{b}": 0.0 for a in labels.values() for b in labels.values()}
    for hi in range(first.shape[0]):
        for ai in range(first.shape[1]):
            ht = _result_key(hi - ai)
            p1 = first[hi, ai]
            if p1 <= 0:
                continue
            for hs in range(second.shape[0]):
                for a_s in range(second.shape[1]):
                    ft = _result_key((hi + hs) - (ai + a_s))
                    out[f"{labels[ht]}{labels[ft]}"] += float(p1 * second[hs, a_s])
    s = sum(out.values())
    return {k: v / s for k, v in out.items()} if s > 0 else out


def _result_key(goal_diff: int) -> str:
    if goal_diff > 0:
        return "home"
    if goal_diff < 0:
        return "away"
    return "draw"


def _poisson_score_matrix(lam: float, mu: float, max_goals: int = 10) -> np.ndarray:
    hs = np.arange(max_goals + 1)
    home = np.exp(-lam) * np.power(lam, hs) / np.array([math.factorial(int(i)) for i in hs])
    away = np.exp(-mu) * np.power(mu, hs) / np.array([math.factorial(int(i)) for i in hs])
    mat = np.outer(home, away)
    return mat / mat.sum()


def summarize(
    mat: np.ndarray,
    ou_lines: tuple[float, ...] = (1.5, 2.5, 3.5),
    ah_lines: tuple[float, ...] = (-1.5, -1.0, -0.5, 0.0, 0.5, 1.0, 1.5),
) -> dict:
    """一次性产出常用市场，附公平赔率，供 API/前端直接使用。"""
    x12 = outcomes_1x2(mat)
    return {
        "1x2": x12,
        "1x2_fair_odds": {k: to_fair_odds(v) for k, v in x12.items()},
        "over_under": {str(l): over_under(mat, l) for l in ou_lines},
        "asian_handicap": {str(l): asian_handicap(mat, l) for l in ah_lines},
        "btts": both_teams_to_score(mat),
        "goal_bands": goal_bands(mat),
        "correct_score_top": correct_score_top(mat),
    }


def market_candidates(mat: np.ndarray, lam: float, mu: float, home_label: str,
                      away_label: str) -> list[dict]:
    """生成单场可选市场候选项，供串关组合复用。赔率默认公平赔率。"""
    markets = summarize(mat)
    rows = []
    x = markets["1x2"]
    rows.extend([
        {"key": "1x2_home", "market": "胜平负", "label": f"{home_label}胜",
         "model_prob": x["home"], "odds": to_fair_odds(x["home"])},
        {"key": "1x2_draw", "market": "胜平负", "label": "平局",
         "model_prob": x["draw"], "odds": to_fair_odds(x["draw"])},
        {"key": "1x2_away", "market": "胜平负", "label": f"{away_label}胜",
         "model_prob": x["away"], "odds": to_fair_odds(x["away"])},
    ])
    for line, ah in markets["asian_handicap"].items():
        rows.extend([
            {"key": f"ah_{line}_home", "market": "让球", "label": f"{home_label} {line} 赢",
             "model_prob": ah["home_win"], "push_prob": ah["push"], "odds": to_fair_odds(ah["home_win"])},
            {"key": f"ah_{line}_away", "market": "让球", "label": f"{away_label} {-float(line):g} 赢",
             "model_prob": ah["home_loss"], "push_prob": ah["push"], "odds": to_fair_odds(ah["home_loss"])},
        ])
    for line, ou in markets["over_under"].items():
        rows.extend([
            {"key": f"ou_{line}_over", "market": "大小球", "label": f"大 {line}",
             "model_prob": ou["over"], "push_prob": ou["push"], "odds": to_fair_odds(ou["over"])},
            {"key": f"ou_{line}_under", "market": "大小球", "label": f"小 {line}",
             "model_prob": ou["under"], "push_prob": ou["push"], "odds": to_fair_odds(ou["under"])},
        ])
    for label, prob in markets["goal_bands"].items():
        rows.append({"key": f"goal_band_{label}", "market": "进球个数", "label": label,
                     "model_prob": prob, "odds": to_fair_odds(prob)})
    for item in markets["correct_score_top"]:
        rows.append({"key": f"score_{item['score']}", "market": "比分", "label": item["score"],
                     "model_prob": item["prob"], "odds": to_fair_odds(item["prob"])})
    for label, prob in half_full_time(lam, mu).items():
        rows.append({"key": f"half_full_{label}", "market": "半全场胜平负", "label": label,
                     "model_prob": prob, "odds": to_fair_odds(prob)})
    return [r for r in rows if r["model_prob"] > _EPS and 1.0 < r["odds"] < float("inf")]
