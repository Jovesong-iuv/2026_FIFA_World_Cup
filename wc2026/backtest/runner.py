"""回测：样本外验证模型校准。

对某届世界杯：用开赛前 N 年的数据训练(不含该届正赛)，预测该届全部比赛，
与实际结果比较。指标：Log Loss、Brier、Top-pick 准确率、校准曲线，
并与均匀基准(1/3)对比以判断是否有预测力。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from wc2026.data.db import get_conn
from wc2026.markets import derive
from wc2026.models.dixon_coles import DixonColesModel
from wc2026.models.elo import EloModel

UNIFORM_LOGLOSS = float(-np.log(1 / 3))  # ≈1.0986：三分类瞎猜的 log loss


def _load_train(since: str, until: str) -> pd.DataFrame:
    with get_conn() as c:
        return pd.read_sql_query(
            "SELECT date,home_team,away_team,home_score,away_score,neutral,is_competitive "
            "FROM matches WHERE date>=? AND date<?",
            c, params=[since, until])


def _load_wc(year: str) -> pd.DataFrame:
    with get_conn() as c:
        return pd.read_sql_query(
            "SELECT date,home_team,away_team,home_score,away_score,neutral "
            "FROM matches WHERE tournament='FIFA World Cup' AND date LIKE ?",
            c, params=[f"{year}%"])


def backtest_world_cup(year: str, train_years: int = 12, xi: float = 0.0010) -> dict:
    cutoff = f"{year}-05-01"                  # 世界杯 6 月开赛，5 月截断
    since = f"{int(year) - train_years}-01-01"
    model = DixonColesModel(xi=xi).fit(_load_train(since, cutoff))

    recs, skipped = [], 0
    for _, m in _load_wc(year).iterrows():
        h, a = m["home_team"], m["away_team"]
        if not (model.has_team(h) and model.has_team(a)):
            skipped += 1
            continue
        x = derive.outcomes_1x2(model.score_matrix(h, a, bool(m["neutral"])))
        hs, as_ = m["home_score"], m["away_score"]
        actual = "home" if hs > as_ else ("draw" if hs == as_ else "away")
        recs.append({"home": x["home"], "draw": x["draw"], "away": x["away"], "actual": actual})

    return _metrics(recs, year, skipped)


def _metrics(recs: list, year: str, skipped: int) -> dict:
    n = len(recs)
    if n == 0:
        return {"year": year, "n": 0, "skipped": skipped}
    ll = brier = correct = 0.0
    for r in recs:
        probs = {k: r[k] for k in ("home", "draw", "away")}
        ll += -np.log(max(probs[r["actual"]], 1e-12))
        for k in ("home", "draw", "away"):
            brier += (probs[k] - (1.0 if k == r["actual"] else 0.0)) ** 2
        if max(probs, key=probs.get) == r["actual"]:
            correct += 1
    return {
        "year": year, "n": n, "skipped": skipped,
        "log_loss": ll / n,
        "baseline_log_loss": UNIFORM_LOGLOSS,
        "brier": brier / n,
        "accuracy": correct / n,
        "calibration": _calibration(recs),
    }


def _calibration(recs: list, bins: int = 5) -> list:
    pairs = [(r[k], 1.0 if r["actual"] == k else 0.0)
             for r in recs for k in ("home", "draw", "away")]
    arr = np.array(pairs)
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        mask = (arr[:, 0] >= edges[i]) & (arr[:, 0] < edges[i + 1])
        if mask.sum() > 0:
            out.append({
                "range": f"{edges[i]:.1f}-{edges[i+1]:.1f}",
                "pred_mean": round(float(arr[mask, 0].mean()), 3),
                "actual_freq": round(float(arr[mask, 1].mean()), 3),
                "n": int(mask.sum()),
            })
    return out


def backtest_multi(years: list, train_years: int = 12, xi: float = 0.0010) -> list:
    return [backtest_world_cup(y, train_years, xi) for y in years]


def backtest_ensemble(year: str, train_years: int = 12, xi: float = 0.0010, w: float = 0.5) -> dict:
    """集成回测：1X2 = w·DC + (1-w)·Elo。w=1 即纯 DC，w=0 即纯 Elo。"""
    cutoff = f"{year}-05-01"
    since = f"{int(year) - train_years}-01-01"
    train = _load_train(since, cutoff)
    dc = DixonColesModel(xi=xi).fit(train)
    elo = EloModel().fit(train)

    recs, skipped = [], 0
    for _, m in _load_wc(year).iterrows():
        h, a = m["home_team"], m["away_team"]
        if not (dc.has_team(h) and dc.has_team(a)):
            skipped += 1
            continue
        neutral = bool(m["neutral"])
        px = derive.outcomes_1x2(dc.score_matrix(h, a, neutral))
        qx = elo.prob_1x2(h, a, neutral)
        ens = {k: w * px[k] + (1 - w) * qx[k] for k in px}
        hs, as_ = m["home_score"], m["away_score"]
        actual = "home" if hs > as_ else ("draw" if hs == as_ else "away")
        recs.append({"home": ens["home"], "draw": ens["draw"], "away": ens["away"], "actual": actual})

    return _metrics(recs, year, skipped)
