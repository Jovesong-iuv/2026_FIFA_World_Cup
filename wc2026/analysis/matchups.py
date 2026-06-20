"""关键对位、破局点与强队类型分析（借鉴 deep-analysis skill 的对位 / 巨星破局思路）。

务实规则版：基于阵容身价 / 评分 top（FotMob）+ 模型期望进球 + 九维度综合实力，
给出三类强队分类（超级巨星型 / 体系型 / 低效热门）、破局点（最强进攻个体）、
强弱对位与受让韧性提示。纯函数、输入驱动，无阵容数据时按模型实力降级、不臆造。
"""
from __future__ import annotations

from wc2026.data.squads import POS_ZH, squad_value_summary
from wc2026.data.team_names import zh

_ATTACK_POS = {"Attacker", "Midfielder"}
_STRONG_SQUAD = 3.0e8       # €300m+ 粗略视为身价强队
_STRONG_ATTACK = 1.6        # 模型期望进球阈值


def _pos_zh(p) -> str:
    return POS_ZH.get(p, p or "—")


def _name(p) -> str:
    return p.get("name_zh") or p.get("name") or "—"


def _breaker(sq) -> dict | None:
    """阵容里身价最高的进攻球员（前锋/中场优先，否则身价 top1）。无数据返回 None。"""
    if not sq:
        return None
    top5 = (squad_value_summary(sq.get("groups")).get("top5")) or []
    if not top5:
        return None
    atk = [p for p in top5 if p.get("position") in _ATTACK_POS]
    p = (atk or top5)[0]
    return {"name": _name(p), "position": p.get("position"),
            "value": p.get("value"), "rating": p.get("rating")}


def classify_team(team: str, sq, exp_goal: float) -> dict:
    """三类：超级巨星型 / 巨星依赖型 / 体系型强队 / 低效热门 / 常规 / 数据有限。"""
    summ = squad_value_summary(sq.get("groups")) if sq else {}
    total = summ.get("total", 0) or 0
    n = summ.get("valued_count", 0) or 0
    top5 = summ.get("top5") or []
    star = top5[0] if top5 else None
    avg = (total / n) if n else 0
    dominance = (float(star["value"]) / avg) if (star and star.get("value") and avg) else 0
    strong_attack = exp_goal >= _STRONG_ATTACK
    strong_squad = total >= _STRONG_SQUAD

    if star and dominance >= 2.2:
        t = "超级巨星型" if strong_attack else "巨星依赖型"
        reason = f"{zh(team)} 拥有突出个人（{_name(star)}，身价约队内均值 {dominance:.1f} 倍）"
    elif strong_squad and strong_attack:
        t, reason = "体系型强队", f"{zh(team)} 整体身价高、攻击力强，但无碾压级单点，依赖体系"
    elif strong_squad and not strong_attack:
        t, reason = "低效热门", f"{zh(team)} 纸面身价高但模型期望进球偏低（{exp_goal:.2f}），警惕赢球不穿盘"
    elif total:
        t, reason = "常规球队", f"{zh(team)} 非顶级身价，模型期望进球 {exp_goal:.2f}"
    else:
        t, reason = "数据有限", f"{zh(team)} 无身价数据，按模型实力评估"
    return {"team": team, "type": t, "reason": reason,
            "dominance": round(dominance, 2), "exp_goal": round(exp_goal, 2),
            "squad_value": total}


def analyze_matchups(home: str, away: str, *, exp_goals,
                     sq_home=None, sq_away=None,
                     score_home: float | None = None, score_away: float | None = None) -> dict:
    """返回 {home_type, away_type, home_breaker, away_breaker, notes}。exp_goals=(lam,mu)。"""
    lam, mu = exp_goals
    ch, ca = classify_team(home, sq_home, lam), classify_team(away, sq_away, mu)
    bh, ba = _breaker(sq_home), _breaker(sq_away)
    notes = []

    if score_home is not None and score_away is not None:
        gap = score_home - score_away
        if abs(gap) >= 12:
            strong, weak = (home, away) if gap > 0 else (away, home)
            notes.append(
                f"{zh(strong)} 综合实力占优（{abs(gap):.0f} 分），进攻端主要冲击 {zh(weak)} 防线组织；"
                f"{zh(weak)} 若低位防守+反击则有受让韧性价值，不宜简单按弱队看待。")
        else:
            notes.append(f"{zh(home)} 与 {zh(away)} 综合实力接近（差 {abs(gap):.0f} 分），"
                         "对位更取决于临场状态与战术执行。")
    if bh:
        notes.append(f"{zh(home)} 破局点：{bh['name']}（{_pos_zh(bh['position'])}）"
                     "——密集防守下的主要打穿手段。")
    if ba:
        notes.append(f"{zh(away)} 破局点：{ba['name']}（{_pos_zh(ba['position'])}）。")
    for c in (ch, ca):
        if c["type"] == "低效热门":
            notes.append(f"⚠️ {zh(c['team'])} 属「低效热门」：防赢球不穿盘 / 防冷平。")
        elif c["type"] == "超级巨星型":
            notes.append(f"{zh(c['team'])} 属「超级巨星型」：面对摆大巴仍有打穿与大球潜力。")

    return {"home_type": ch, "away_type": ca,
            "home_breaker": bh, "away_breaker": ba, "notes": notes}
