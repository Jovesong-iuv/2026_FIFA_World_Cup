"""世界排名：优先 FIFA 官方排名（data/fifa_ranking.json），无则回退模型 Elo 排名。

FIFA 排名经 scripts/update_fifa_ranking.py 抓取；Elo 排名为模型评分排序，作兜底。
展示层应标注来源（FIFA / Elo）。
"""
from __future__ import annotations

from wc2026.data import fifa_ranking


def elo_ratings(model) -> dict:
    elo = getattr(model, "elo", None)
    return dict(getattr(elo, "ratings", {}) or {})


def elo_rank(model, team: str) -> tuple[int | None, int]:
    """返回 (排名, 参与排名球队数)。无 Elo 数据或队不在评分中 → (None, total)。"""
    ratings = elo_ratings(model)
    total = len(ratings)
    if team not in ratings:
        return None, total
    r = ratings[team]
    rank = 1 + sum(1 for v in ratings.values() if v > r)  # 竞争名次（并列同名次）
    return rank, total


def elo_rank_map(model) -> dict:
    """返回 {team: 竞争名次}，供批量场景（如首页卡片）一次性查表。"""
    ratings = elo_ratings(model)
    return {t: 1 + sum(1 for v in ratings.values() if v > r) for t, r in ratings.items()}


def world_rank(model, team: str) -> tuple[int | None, str]:
    """世界排名：优先 FIFA 官方，无则回退 Elo。返回 (rank, source)，source ∈ {'FIFA','Elo',''}。"""
    fr = fifa_ranking.fifa_rank(team)
    if fr is not None:
        return fr, "FIFA"
    er, _total = elo_rank(model, team)
    return (er, "Elo") if er is not None else (None, "")


def world_rank_map(model) -> dict:
    """{team: (rank, source)}：覆盖 Elo 评分中的所有队，FIFA 优先。供批量展示。"""
    emap = elo_rank_map(model)
    out = {t: ((fifa_ranking.fifa_rank(t), "FIFA") if fifa_ranking.fifa_rank(t) is not None
               else (er, "Elo")) for t, er in emap.items()}
    return out


def ranking_date() -> str | None:
    return fifa_ranking.ranking_date()

