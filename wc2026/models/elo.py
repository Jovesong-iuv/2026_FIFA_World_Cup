"""World Football Elo 评级。

按时间顺序遍历历史比赛更新评级：
- K 因子随赛事重要性(世界杯 > 洲际杯 > 预选赛 > 友谊赛)
- 进球差修正(大胜加分更多)
- 主场优势 / 中立场
相比 Dixon-Coles，Elo 天然按对手强度加权(赢强队加分多)，
能缓解"赛区互刷高比分"导致的强度高估。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _k_factor(tournament, is_competitive) -> float:
    t = (tournament or "").lower()
    if "friendly" in t:
        return 20.0
    if "world cup" in t and "qual" not in t:
        return 60.0
    if "qualif" in t:
        return 40.0
    if any(x in t for x in ("euro", "copa", "nations league", "cup of nations",
                            "asian cup", "gold cup", "confederations")):
        return 50.0
    return 40.0 if is_competitive else 20.0


def _goal_mult(gd: int) -> float:
    g = abs(gd)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11.0 + g) / 8.0


class EloModel:
    def __init__(self, home_adv: float = 65.0, base: float = 1500.0, draw_max: float = 0.28):
        self.home_adv = home_adv
        self.base = base
        self.draw_max = draw_max
        self.ratings: dict = {}

    def fit(self, matches: pd.DataFrame) -> "EloModel":
        df = matches.dropna(subset=["home_score", "away_score"]).sort_values("date")
        r: dict = {}
        for m in df.itertuples(index=False):
            h, a = m.home_team, m.away_team
            rh, ra = r.get(h, self.base), r.get(a, self.base)
            ha = 0.0 if getattr(m, "neutral", 0) else self.home_adv
            we = 1.0 / (1.0 + 10 ** ((ra - rh - ha) / 400.0))
            hs, as_ = m.home_score, m.away_score
            w = 1.0 if hs > as_ else (0.5 if hs == as_ else 0.0)
            k = _k_factor(getattr(m, "tournament", ""), getattr(m, "is_competitive", 0)) * _goal_mult(hs - as_)
            delta = k * (w - we)
            r[h] = rh + delta
            r[a] = ra - delta
        self.ratings = r
        return self

    def rating(self, team: str) -> float:
        return self.ratings.get(team, self.base)

    def prob_1x2(self, home: str, away: str, neutral: bool = True) -> dict:
        """Elo → 胜平负概率。We=胜+半平，用经验公式按势均程度分配平局。"""
        ha = 0.0 if neutral else self.home_adv
        we = 1.0 / (1.0 + 10 ** ((self.rating(away) - self.rating(home) - ha) / 400.0))
        p_draw = self.draw_max * (1.0 - 2.0 * abs(we - 0.5))
        p = np.clip([we - 0.5 * p_draw, p_draw, 1.0 - we - 0.5 * p_draw], 1e-6, None)
        p = p / p.sum()
        return {"home": float(p[0]), "draw": float(p[1]), "away": float(p[2])}

    def save(self, path) -> None:
        import json
        from pathlib import Path
        Path(path).write_text(json.dumps({
            "home_adv": self.home_adv, "base": self.base,
            "draw_max": self.draw_max, "ratings": self.ratings,
        }, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "EloModel":
        import json
        from pathlib import Path
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        m = cls(home_adv=d["home_adv"], base=d["base"], draw_max=d["draw_max"])
        m.ratings = d["ratings"]
        return m
