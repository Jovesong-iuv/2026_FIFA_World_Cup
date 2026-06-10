"""市场换算：由比分概率矩阵推导各投注市场的概率与公平赔率。

矩阵约定：mat[i, j] = P(主队进 i 球, 客队进 j 球)，行=主队，列=客队。
"""
from __future__ import annotations

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
        "correct_score_top": correct_score_top(mat),
    }
