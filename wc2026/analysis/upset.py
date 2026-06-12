"""爆冷指数：衡量"把热门方当稳胆"的风险，而非预测谁一定爆冷。

只使用项目已有数据：
- 模型 1X2 概率（核心：热门方不取胜的概率 = 平局 + 爆冷方取胜）
- 近期防守波动（热门方近况场均失球，evidence.recent_form）
- 战意 / 控分情境（context 的 tank_risk）

伤停、海拔、气候时差、历史大赛不稳定性等文档列出的来源暂无结构化数据源，
不纳入计算、也不编造，由展示层说明。等级规则照搬需求文档 5.3.4。
"""
from __future__ import annotations

from wc2026.data.team_names import zh

# (上界, 等级名)；index <= 上界即归入该等级
_BANDS = [(20, "低风险"), (40, "中低风险"), (60, "中风险"), (80, "高风险"), (100, "极高风险")]


def risk_level(index: int) -> str:
    for hi, name in _BANDS:
        if index <= hi:
            return name
    return "极高风险"


def upset_index(x: dict, home: str, away: str, evidence: dict | None = None,
                tank_risk: bool = False) -> dict:
    """计算爆冷指数。

    x: {'home','draw','away'} 模型概率。
    evidence: reason['evidence']，可选；用其中 home_form/away_form 的失球评估热门方防守。
    tank_risk: 出线已定 / 控分默契球风险。

    返回 {index, level, favorite, factors:[{name, detail}]}。
    """
    fav = "home" if x.get("home", 0.0) >= x.get("away", 0.0) else "away"
    fav_team = home if fav == "home" else away
    dog_team = away if fav == "home" else home
    fav_prob = float(x.get(fav, 0.0))
    not_fav = max(0.0, 1.0 - fav_prob)  # 平局 + 爆冷方取胜

    factors = [{
        "name": "比赛悬念",
        "detail": f"模型给热门方 {zh(fav_team)} 胜率 {fav_prob:.0%}，"
                  f"平局 + {zh(dog_team)} 取胜合计 {not_fav:.0%}",
    }]
    score = not_fav * 100.0

    # 强队近期防守波动：热门方近况场均失球
    if evidence:
        fav_form = evidence.get("home_form" if fav == "home" else "away_form") or {}
        n = int(fav_form.get("n", 0) or 0)
        if n > 0:
            ga_pg = float(fav_form.get("ga", 0) or 0) / n
            if ga_pg >= 1.5:
                score += 8
                factors.append({"name": "强队防守波动",
                                "detail": f"{zh(fav_team)} 近 {n} 场场均失 {ga_pg:.1f} 球，防线不稳，更易被爆"})
            elif ga_pg <= 0.6:
                score -= 5
                factors.append({"name": "强队防线稳固",
                                "detail": f"{zh(fav_team)} 近 {n} 场场均仅失 {ga_pg:.1f} 球，爆冷概率下降"})

    # 战意 / 控分情境
    if tank_risk:
        score += 10
        factors.append({"name": "战意风险",
                        "detail": "出线形势已定或存在控分/默契球可能，结果更随机，低概率事件兑现概率上升"})

    index = int(max(0, min(100, round(score))))
    return {"index": index, "level": risk_level(index), "favorite": fav_team, "factors": factors}
