"""综合实力评分：把模型 Elo / Dixon-Coles 系数与近况、交锋折算为 0-100 分项，用于「解释」（非替代赔率）。

维度（均跨模型全部球队做 min-max 归一）：
- 基础实力：Elo 评分。
- 进攻：Dixon-Coles attack 系数（越高越强）。
- 防守：Dixon-Coles defense 系数（出现在对手期望进球里，越低越好，故反转）。
- 近期状态：近况胜平负折算的场均得分率。
- 历史交锋：H2H 胜率（低权重）。

本模块保留为五维基础解释器；身价、FIFA 排名、世界杯历史、环境和体能由九维模型与展示层处理，
市场数据仍只作后验验证。默认权重按本模块可用维度归一。
"""
from __future__ import annotations

from wc2026.data.team_names import zh

DIMENSIONS = ["基础实力", "进攻", "防守", "近期状态", "历史交锋"]
_WEIGHTS = {"基础实力": 0.30, "进攻": 0.22, "防守": 0.22, "近期状态": 0.18, "历史交锋": 0.08}


def _minmax(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))


def _form_score(form: dict | None) -> float:
    n = (form or {}).get("n", 0) or 0
    if not n:
        return 50.0
    return (form.get("w", 0) * 3 + form.get("d", 0)) / (n * 3) * 100.0


def strength_profile(model, home: str, away: str, evidence: dict | None = None) -> dict:
    """返回 {home, away, dims_home, dims_away, score_home, score_away, explanation}。"""
    attack, defense = model.attack, model.defense
    a_lo, a_hi = min(attack.values()), max(attack.values())
    d_lo, d_hi = min(defense.values()), max(defense.values())

    elo = getattr(model, "elo", None)
    if elo and getattr(elo, "ratings", None):
        e_lo, e_hi = min(elo.ratings.values()), max(elo.ratings.values())
        def elo_score(t):
            return _minmax(elo.rating(t), e_lo, e_hi)
    else:
        def elo_score(_t):
            return 50.0

    ev = evidence or {}
    h2h = ev.get("h2h", {}) or {}
    total = h2h.get("total", 0) or 0

    def dims(team: str, is_home: bool) -> dict:
        if total:
            wins = h2h.get("a_win" if is_home else "a_loss", 0)
            h2h_score = wins / total * 100.0
        else:
            h2h_score = 50.0
        return {
            "基础实力": elo_score(team),
            "进攻": _minmax(attack.get(team, a_lo), a_lo, a_hi),
            "防守": 100.0 - _minmax(defense.get(team, d_hi), d_lo, d_hi),  # 反转：系数越低防守越好
            "近期状态": _form_score(ev.get("home_form" if is_home else "away_form")),
            "历史交锋": h2h_score,
        }

    dh, da = dims(home, True), dims(away, False)

    def composite(d: dict) -> float:
        return sum(_WEIGHTS[k] * d[k] for k in _WEIGHTS)

    sh, sa = composite(dh), composite(da)
    explanation = _explain(home, away, dh, da, sh, sa)
    return {"home": home, "away": away, "dims_home": dh, "dims_away": da,
            "score_home": sh, "score_away": sa, "explanation": explanation}


def _explain(home, away, dh, da, sh, sa) -> str:
    lead, trail = (home, away) if sh >= sa else (away, home)
    gap = abs(sh - sa)
    tone = "明显" if gap >= 12 else "略" if gap >= 4 else "基本持平，"
    # 各队相对对手优势最大的维度
    h_edge = max(DIMENSIONS, key=lambda k: dh[k] - da[k])
    a_edge = max(DIMENSIONS, key=lambda k: da[k] - dh[k])
    head = (f"{zh(home)} 综合 {sh:.0f} · {zh(away)} 综合 {sa:.0f}；"
            f"{'两队实力' + tone if tone == '基本持平，' else f'{zh(lead)} {tone}占优'}。")
    return head + f"{zh(home)} 相对优势在「{h_edge}」，{zh(away)} 相对优势在「{a_edge}」。"
