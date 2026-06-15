"""模型编排：训练 Dixon-Coles + Elo，集成预测。

Elo 按对手强度加权(拉正 DC 的赛区互刷偏差)，用于锚定胜平负；
Dixon-Coles 提供比分分布形状(大小球/让球)。
集成：1X2 = w·DC + (1-w)·Elo，再把 DC 比分矩阵按集成后的 1X2 重新标定。
"""
from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np
import pandas as pd

from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.models.dixon_coles import DixonColesModel
from wc2026.models.elo import EloModel

DC_PATH = settings.data_dir / "dc_model.json"
ELO_PATH = settings.data_dir / "elo_model.json"
META_PATH = settings.data_dir / "model_meta.json"
ENSEMBLE_W = 0.5  # DC 权重；其余给 Elo


def load_matches(since: str | None = None) -> pd.DataFrame:
    q = ("SELECT date, home_team, away_team, home_score, away_score, "
         "tournament, neutral, is_competitive FROM matches")
    params: list = []
    if since:
        q += " WHERE date >= ?"
        params.append(since)
    with get_conn() as conn:
        return pd.read_sql_query(q, conn, params=params)


def _recalibrate(mat: np.ndarray, px: dict, target: dict) -> np.ndarray:
    """把比分矩阵的 胜/平/负 三块按 target 概率重新缩放(保留比分形状)。"""
    i, j = np.indices(mat.shape)
    out = mat.astype(float).copy()
    for region, key in (((i > j), "home"), ((i == j), "draw"), ((i < j), "away")):
        if px[key] > 1e-9:
            out[region] *= target[key] / px[key]
    s = out.sum()
    return out / s if s > 0 else out


class EnsembleModel:
    """对外与 DixonColesModel 接口兼容；score_matrix 用 Elo 集成拉正胜平负。"""

    def __init__(self, dc: DixonColesModel, elo: EloModel | None = None, w: float = ENSEMBLE_W):
        self.dc = dc
        self.elo = elo
        self.w = w

    @property
    def teams(self):
        return self.dc.teams

    @property
    def attack(self):
        return self.dc.attack

    @property
    def defense(self):
        return self.dc.defense

    @property
    def home_adv(self):
        return self.dc.home_adv

    def has_team(self, t):
        return self.dc.has_team(t)

    def expected_goals(self, h, a, neutral=True):
        return self.dc.expected_goals(h, a, neutral)

    def matrix_from_goals(self, lam, mu):
        return self.dc.matrix_from_goals(lam, mu)

    def score_matrix(self, home, away, neutral=True):
        mat = self.dc.score_matrix(home, away, neutral)
        if self.elo is None or not self.elo.ratings:
            return mat
        from wc2026.markets.derive import outcomes_1x2
        px = outcomes_1x2(mat)
        qx = self.elo.prob_1x2(home, away, neutral)
        ens = {k: self.w * px[k] + (1 - self.w) * qx[k] for k in px}
        return _recalibrate(mat, px, ens)


def _write_meta(df: pd.DataFrame) -> None:
    """记录训练数据覆盖到的最新比赛日期，供赛中增量修正防双重计数。"""
    try:
        mx = str(pd.to_datetime(df["date"]).max().date())
        META_PATH.write_text(
            json.dumps({"trained_through": mx, "trained_at": date.today().isoformat()},
                       ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def train_and_save(since_years: int = 12, xi: float = 0.0010) -> EnsembleModel:
    since = (date.today() - timedelta(days=365 * since_years)).isoformat()
    df = load_matches(since=since)
    if df.empty:
        raise RuntimeError("库中无数据，请先运行 scripts/update_data.py")
    settings.ensure_dirs()
    dc = DixonColesModel(xi=xi).fit(df)
    dc.save(DC_PATH)
    elo = EloModel().fit(df)
    elo.save(ELO_PATH)
    _write_meta(df)
    return EnsembleModel(dc, elo)


def get_model(force_retrain: bool = False, adjusted: bool = True) -> EnsembleModel:
    if not force_retrain and DC_PATH.exists():
        dc = DixonColesModel.load(DC_PATH)
        elo = EloModel.load(ELO_PATH) if ELO_PATH.exists() else None
        model = EnsembleModel(dc, elo)
    else:
        model = train_and_save()
    if adjusted:
        # 叠加赛中实力修正(已完赛结果/新闻)；缺修正或异常时退回原模型
        try:
            from wc2026.analysis.adjustments import apply_adjustments
            model = apply_adjustments(model)
        except Exception:
            pass
    return model
