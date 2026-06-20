"""大胆预测：为小组赛每场生成比分预测、进球量与冷门推荐。

产出：
- top-3 比分及概率
- 期望总进球、进球区间推荐
- 爆冷指数与风险等级
- 是否推荐为「冷门关注」场次（爆冷指数 ≥ 60）

全部依赖模型现有比分矩阵、爆冷指数和进球策略模块，不引入外部数据。
"""
from __future__ import annotations

import numpy as np

from wc2026.analysis.environment import _top_scores
from wc2026.analysis.goal_strategy import recommend as goal_recommend
from wc2026.analysis.schedule import beijing, match_result, sort_fixtures
from wc2026.analysis.upset import upset_index as compute_upset
from wc2026.data.team_names import zh
from wc2026.data.flags import flag_emoji
from wc2026.data.db import get_conn


def load_group_fixtures():
    """从 DB 读取所有小组赛场次（predictable=1）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT match_number, group_name, home_team, away_team, date_utc, location, "
            "round_number, home_score, away_score "
            "FROM fixtures WHERE predictable=1 AND group_name IS NOT NULL AND group_name!='' "
            "ORDER BY group_name, date_utc"
        ).fetchall()
    return [dict(r) for r in rows]


def _group_short(group_name: str) -> str:
    """将 'Group A' 映射为 'A 组'。"""
    return group_name.replace("Group ", "") + " 组" if group_name else ""


def predict_match(model, fixture: dict, upset_evidence: dict | None = None) -> dict:
    """为单场小组赛生成预测汇总。

    返回字典含比分、进球、爆冷三块：
    - top_scores: [{score, prob}]
    - goal: {recommend, xg_total, probs}
    - upset: {index, level, favorite, factors}
    - is_upset_watch: 是否推荐为冷门关注场次
    """
    home = fixture["home_team"]
    away = fixture["away_team"]
    neutral = home not in {"Mexico", "Canada", "United States"}
    hs = fixture.get("home_score")
    as_ = fixture.get("away_score")
    finished = hs is not None and as_ is not None

    if finished:
        # 已完赛：用真实比分，不预测
        return {
            "finished": True,
            "score_display": f"{int(hs)}-{int(as_)}",
            "top_scores": [],
            "goal": None,
            "upset": None,
            "is_upset_watch": False,
        }

    # 比分矩阵
    mat = np.asarray(model.score_matrix(home, away, neutral), dtype=float)

    # Top-3 比分
    top_raw = _top_scores(mat, 5)
    top_scores = [{"score": f"{h}-{a}", "prob": round(p, 4)} for h, a, p in top_raw[:3]]

    # 进球区间推荐
    lam, mu = model.expected_goals(home, away, neutral)
    goal_info = goal_recommend(mat, lam, mu)

    # 爆冷指数
    x = derive_outcomes(mat)
    upset = compute_upset(x, home, away, upset_evidence)

    # 冷门关注判定：爆冷指数 ≥ 60（比首页「爆冷预警 ≥ 61」门槛略宽，鼓励大胆关注）
    is_upset_watch = upset["index"] >= 60

    return {
        "finished": False,
        "top_scores": top_scores,
        "goal": {
            "recommend": goal_info["recommend"],
            "xg_total": goal_info["xg_total"],
            "confidence": goal_info["confidence"],
            "probs": goal_info["probs"],
            "reasons": goal_info["reasons"][:2],
        },
        "upset": upset,
        "is_upset_watch": is_upset_watch,
        "lam": round(lam, 2),
        "mu": round(mu, 2),
    }


def derive_outcomes(mat: np.ndarray) -> dict:
    """从比分矩阵提取胜平负概率。"""
    arr = np.asarray(mat, dtype=float)
    n = arr.shape[0]
    i, j = np.indices((n, n))
    return {
        "home": float(arr[i > j].sum()),
        "draw": float(arr[i == j].sum()),
        "away": float(arr[i < j].sum()),
    }


def format_score_display(top_scores: list[dict]) -> str:
    """将 top-3 比分格式化为显示文本。"""
    if not top_scores:
        return "—"
    parts = [f"{s['score']} ({s['prob']:.1%})" for s in top_scores]
    return " · ".join(parts)


def fixture_predictions(model) -> list[dict]:
    """为全部小组赛场次生成预测列表，分组排序。"""
    fixtures = load_group_fixtures()
    from datetime import datetime, timezone

    fixtures = sort_fixtures(fixtures, datetime.now(timezone.utc))
    rows = []
    for f in fixtures:
        home = f["home_team"]
        away = f["away_team"]
        pred = predict_match(model, f)

        bj = beijing(f.get("date_utc"))
        res = match_result(f.get("home_score"), f.get("away_score"))

        row = {
            "group": _group_short(f.get("group_name", "")),
            "group_raw": f.get("group_name", ""),
            "round": f.get("round_number", 1),
            "date_str": bj["date"],
            "weekday": bj["weekday"],
            "time": bj["time"],
            "home": home,
            "away": away,
            "home_flag": flag_emoji(home),
            "away_flag": flag_emoji(away),
            "finished": pred["finished"],
            "result": res["score"] if res["finished"] else "—",
            "top_scores_display": format_score_display(pred["top_scores"]),
            "top_scores": pred["top_scores"],
            "goal": pred["goal"],
            "upset": pred["upset"],
            "is_upset_watch": pred["is_upset_watch"],
            "xg_total": pred.get("lam", 0) + pred.get("mu", 0),
            "location": f.get("location", ""),
        }
        rows.append(row)
    return rows
