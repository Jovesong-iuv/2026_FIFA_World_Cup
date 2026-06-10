"""Dixon-Coles 进球模型。

拟合每支国家队的进攻/防守强度、主场优势与低比分相关修正，
输出任意两队对阵的"比分概率矩阵" P(主队 i 球, 客队 j 球)，
一切市场（胜平负/让球/大小球…）都由该矩阵推导。

要点：
- λ(主队期望进球) = exp(attack_home + defense_away + γ·主场)
  μ(客队期望进球) = exp(attack_away + defense_home)
- τ 修正低比分(0-0/1-0/0-1/1-1)的相关性
- 时间衰减 exp(-ξ·距今天数)：近期比赛权重更高
- L2 收缩：把数据稀少的球队拉向平均强度（贝叶斯先验式正则）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson


@dataclass
class DixonColesModel:
    max_goals: int = 10
    xi: float = 0.0010          # 时间衰减(每天)，~半衰期 1.9 年
    reg: float = 1e-3           # L2 收缩强度
    friendly_weight: float = 1.0  # 友谊赛权重(实测降权会加重南美偏差，默认不降)
    teams: list = field(default_factory=list)
    attack: dict = field(default_factory=dict)
    defense: dict = field(default_factory=dict)
    home_adv: float = 0.0
    rho: float = 0.0
    fitted: bool = False

    # ---------------- 拟合 ----------------
    def fit(self, matches: pd.DataFrame, ref_date: object = None) -> "DixonColesModel":
        df = matches.dropna(subset=["home_score", "away_score"]).copy()
        if df.empty:
            raise ValueError("没有可用于拟合的比赛数据")

        teams = sorted(set(df["home_team"]) | set(df["away_team"]))
        idx = {t: i for i, t in enumerate(teams)}
        n = len(teams)

        home_idx = df["home_team"].map(idx).to_numpy()
        away_idx = df["away_team"].map(idx).to_numpy()
        hs = df["home_score"].to_numpy(dtype=float)
        as_ = df["away_score"].to_numpy(dtype=float)
        if "neutral" in df:
            neutral = df["neutral"].to_numpy(dtype=float)
        else:
            neutral = np.zeros(len(df))

        ref = pd.to_datetime(ref_date) if ref_date is not None else pd.to_datetime(df["date"]).max()
        days = (ref - pd.to_datetime(df["date"])).dt.days.to_numpy(dtype=float)
        weights = np.exp(-self.xi * np.clip(days, 0, None))
        if "is_competitive" in df:
            comp = df["is_competitive"].to_numpy(dtype=float)
            weights = weights * np.where(comp > 0, 1.0, self.friendly_weight)

        def nll(params: np.ndarray) -> float:
            a = params[:n]
            d = params[n:2 * n]
            rho = params[2 * n]
            gamma = params[2 * n + 1]
            lam = np.exp(a[home_idx] + d[away_idx] + gamma * (1.0 - neutral))
            mu = np.exp(a[away_idx] + d[home_idx])
            tau = self._tau_vec(hs, as_, lam, mu, rho)
            tau = np.clip(tau, 1e-12, None)
            ll = weights * (np.log(tau) + hs * np.log(lam) - lam + as_ * np.log(mu) - mu)
            penalty = self.reg * (float(a @ a) + float(d @ d))
            return -float(ll.sum()) + penalty

        x0 = np.concatenate([np.zeros(n), np.zeros(n), [-0.05], [0.25]])
        bounds = [(-3, 3)] * n + [(-3, 3)] * n + [(-0.2, 0.2), (-1.0, 1.5)]
        res = minimize(nll, x0, method="L-BFGS-B", bounds=bounds)

        a = res.x[:n]
        d = res.x[n:2 * n]
        c = a.mean()                 # 识别约束：attack 均值归零
        a, d = a - c, d + c
        self.teams = teams
        self.attack = {t: float(a[idx[t]]) for t in teams}
        self.defense = {t: float(d[idx[t]]) for t in teams}
        self.rho = float(res.x[2 * n])
        self.home_adv = float(res.x[2 * n + 1])
        self.fitted = True
        return self

    @staticmethod
    def _tau_vec(hs, as_, lam, mu, rho):
        tau = np.ones_like(lam, dtype=float)
        tau = np.where((hs == 0) & (as_ == 0), 1.0 - lam * mu * rho, tau)
        tau = np.where((hs == 0) & (as_ == 1), 1.0 + lam * rho, tau)
        tau = np.where((hs == 1) & (as_ == 0), 1.0 + mu * rho, tau)
        tau = np.where((hs == 1) & (as_ == 1), 1.0 - rho, tau)
        return tau

    # ---------------- 预测 ----------------
    def has_team(self, team: str) -> bool:
        return team in self.attack

    def expected_goals(self, home: str, away: str, neutral: bool = True) -> tuple[float, float]:
        for t in (home, away):
            if t not in self.attack:
                raise KeyError(f"球队不在训练集中：{t}")
        gamma = 0.0 if neutral else self.home_adv
        lam = float(np.exp(self.attack[home] + self.defense[away] + gamma))
        mu = float(np.exp(self.attack[away] + self.defense[home]))
        return lam, mu

    def matrix_from_goals(self, lam: float, mu: float) -> np.ndarray:
        """由期望进球(λ,μ)构造比分概率矩阵，含 τ 低比分修正。"""
        k = np.arange(self.max_goals + 1)
        mat = np.outer(poisson.pmf(k, lam), poisson.pmf(k, mu))
        rho = self.rho
        mat[0, 0] *= 1.0 - lam * mu * rho
        mat[0, 1] *= 1.0 + lam * rho
        mat[1, 0] *= 1.0 + mu * rho
        mat[1, 1] *= 1.0 - rho
        mat = np.clip(mat, 0.0, None)
        total = mat.sum()
        return mat / total if total > 0 else mat

    def score_matrix(self, home: str, away: str, neutral: bool = True) -> np.ndarray:
        """返回 (max_goals+1)×(max_goals+1) 的比分概率矩阵，行=主队进球，列=客队进球。"""
        lam, mu = self.expected_goals(home, away, neutral)
        return self.matrix_from_goals(lam, mu)

    # ---------------- 持久化 ----------------
    def save(self, path: Path) -> None:
        Path(path).write_text(json.dumps({
            "max_goals": self.max_goals, "xi": self.xi, "reg": self.reg,
            "attack": self.attack, "defense": self.defense,
            "home_adv": self.home_adv, "rho": self.rho,
        }, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "DixonColesModel":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        m = cls(max_goals=d["max_goals"], xi=d["xi"], reg=d.get("reg", 1e-3))
        m.attack, m.defense = d["attack"], d["defense"]
        m.home_adv, m.rho = d["home_adv"], d["rho"]
        m.teams = sorted(m.attack)
        m.fitted = True
        return m
