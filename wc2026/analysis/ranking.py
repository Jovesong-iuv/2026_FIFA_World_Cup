"""世界排名：基于模型 Elo 评分排序。

项目无 FIFA 官方排名数据源，这里用 Elo 评分给出「模型世界排名」（越强 Elo 越高，排名越靠前）。
展示层须注明非 FIFA 官方排名。
"""
from __future__ import annotations


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
