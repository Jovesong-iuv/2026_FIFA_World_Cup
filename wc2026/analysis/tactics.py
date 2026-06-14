"""战术研判：从阵型（如 4-4-2 / 5-4-1 / 4-2-3-1）与门将/球员评分，给出对球队判断的「方向性修正」提示。

不直接改写 Dixon-Coles/Elo 概率（那是按真实赛果校准的），而是作为分析师叠加层：
指出阵型攻防取向、门将与阵容强弱可能让实际结果偏离模型的方向（进球高/低、谁更可能爆冷）。
门将/球员评分赛前 FotMob 多为空，开赛后填充；空缺时仅用阵型。
"""
from __future__ import annotations

import re


def parse_formation(f: str | None) -> list[int]:
    """'4-2-3-1' → [4,2,3,1]；非法或非 10 人(不含门将)返回 []。"""
    parts = [int(x) for x in re.findall(r"\d+", f or "")]
    return parts if 2 <= len(parts) <= 5 and sum(parts) == 10 else []


def formation_lean(f: str | None) -> dict:
    """返回 {formation, valid, defenders, forwards, lean}；lean ∈ {进攻, 均衡, 防守, 未知}。"""
    parts = parse_formation(f)
    if not parts:
        return {"formation": f or "—", "valid": False, "defenders": None, "forwards": None, "lean": "未知"}
    d, fw = parts[0], parts[-1]
    if d >= 5 or fw <= 1:
        lean = "防守"
    elif fw >= 3 and d <= 4:
        lean = "进攻"
    else:
        lean = "均衡"
    return {"formation": f, "valid": True, "defenders": d, "forwards": fw, "lean": lean}


def tactical_read(home: str, away: str, home_formation: str | None, away_formation: str | None,
                  gk_home: float | None = None, gk_away: float | None = None) -> dict:
    """综合两队阵型(+可选门将均分)给方向性研判。

    返回 {home_lean, away_lean, goals_hint, notes:[...]}；goals_hint ∈ {偏少, 中性, 偏多}。
    """
    lh, la = formation_lean(home_formation), formation_lean(away_formation)
    notes = []
    if lh["valid"]:
        notes.append(f"{home} 阵型 {lh['formation']}（{lh['lean']}取向）")
    if la["valid"]:
        notes.append(f"{away} 阵型 {la['formation']}（{la['lean']}取向）")

    leans = {lh["lean"], la["lean"]}
    goals_hint = "中性"
    if lh["lean"] == "防守" and la["lean"] == "防守":
        goals_hint = "偏少"
        notes.append("两队均偏防守，阵地战为主，进球与大球概率参考下调、平局风险上调。")
    elif leans == {"进攻"} :
        goals_hint = "偏多"
        notes.append("两队均偏进攻，对攻开放，大球 / 双方进球概率参考上调。")
    elif "防守" in leans and "进攻" in leans:
        defender = home if lh["lean"] == "防守" else away
        attacker = away if defender == home else home
        notes.append(f"{attacker} 压上、{defender} 收缩反击：{attacker} 控球但破密集防守难，"
                     f"低比分 / 平局与 {defender} 反击爆冷的概率参考上调。")

    # 门将评分（若有）：门将明显更好的一方更可能少失球
    if gk_home is not None and gk_away is not None and abs(gk_home - gk_away) >= 0.3:
        better, gh = (home, gk_home) if gk_home > gk_away else (away, gk_away)
        notes.append(f"门将状态：{better} 门将近期评分更高（{gh:.2f}），其被击穿难度参考上调。")
    elif gk_home is None and gk_away is None:
        notes.append("门将/球员近期评分暂缺（赛前 FotMob 评分多为空，开赛后填充）。")

    return {"home_lean": lh["lean"], "away_lean": la["lean"], "goals_hint": goals_hint, "notes": notes}
