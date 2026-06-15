"""末轮晋级压力 / 战意推导：从真实积分 + 剩余赛程判定每队处境，自动生成 group_state
喂给 context.adjusted_prediction（其 _motivation 已能消费），实现末轮预测的自动战意修正。

判定只在「末轮」(每队已赛 2 场、整组剩 2 场未赛)进行：枚举本组末轮 2 场 × 3 结果 = 9 种
组合，看每支球队最终是否进前二：
- 9 种组合都进前二 → qualified(已锁定出线，可能轮换)
- 部分进、且「本队赢」的所有情形都进前二 → must_win(生死战)
- 9 种组合都进不了前二，且恒为小组第 4 → eliminated
- 其余 → alive（含仍可争小组第三递补的情形；跨组递补不精确，故不武断判淘汰）

非末轮一律 alive。仅依赖 group_data(含真实比分)，不引入外部数据。
"""
from __future__ import annotations

from itertools import product

from wc2026.data.team_names import zh

# 末轮每场的代表性结果(胜 / 平 / 负)，用于枚举出线形势
_OUTCOMES = [(2, 0), (1, 1), (0, 2)]

STATUS_LABEL = {
    "qualified": "已出线",
    "must_win": "生死战",
    "eliminated": "已出局",
    "alive": "未定",
}


def _base_and_remaining(group_data_g: dict):
    """返回 (base, played, remaining)：已完赛累计积分、各队已赛场数、未赛对阵列表。"""
    teams = group_data_g["teams"]
    base = {t: {"pts": 0, "gd": 0, "gf": 0} for t in teams}
    played = {t: 0 for t in teams}
    remaining = []
    for (hi, ai, hs, as_) in group_data_g["matches"]:
        h, a = teams[hi], teams[ai]
        if hs is None or as_ is None:
            remaining.append((h, a))
            continue
        hs, as_ = int(hs), int(as_)
        played[h] += 1; played[a] += 1
        base[h]["gf"] += hs; base[h]["gd"] += hs - as_
        base[a]["gf"] += as_; base[a]["gd"] += as_ - hs
        if hs > as_:
            base[h]["pts"] += 3
        elif hs < as_:
            base[a]["pts"] += 3
        else:
            base[h]["pts"] += 1; base[a]["pts"] += 1
    return base, played, remaining


def _final_order(teams: list[str], base: dict, results: list[tuple]) -> list[str]:
    """在 base 基础上叠加末轮 results，返回按 积分>净胜球>进球 的最终名次顺序。"""
    stat = {t: dict(base[t]) for t in teams}
    for (h, a, hs, as_) in results:
        stat[h]["gf"] += hs; stat[h]["gd"] += hs - as_
        stat[a]["gf"] += as_; stat[a]["gd"] += as_ - hs
        if hs > as_:
            stat[h]["pts"] += 3
        elif hs < as_:
            stat[a]["pts"] += 3
        else:
            stat[h]["pts"] += 1; stat[a]["pts"] += 1
    return sorted(teams, key=lambda t: (stat[t]["pts"], stat[t]["gd"], stat[t]["gf"]), reverse=True)


def _win_secures_top2(t: str, teams: list[str], base: dict, remaining: list[tuple]) -> bool:
    """本队末轮取胜时，对手另一场的所有结果下是否都进前二。"""
    mine = [(h, a) for (h, a) in remaining if t in (h, a)]
    other = [(h, a) for (h, a) in remaining if t not in (h, a)]
    if len(mine) != 1:
        return False
    h, a = mine[0]
    my_res = (h, a, 2, 0) if h == t else (h, a, 0, 2)
    if not other:
        return t in set(_final_order(teams, base, [my_res])[:2])
    oh, oa = other[0]
    for (hh, aa) in _OUTCOMES:
        if t not in set(_final_order(teams, base, [my_res, (oh, oa, hh, aa)])[:2]):
            return False
    return True


def derive_group_states(group_data: dict) -> dict:
    """返回 {group: {team: status}}，status ∈ qualified/must_win/eliminated/alive。"""
    out = {}
    for g in sorted(group_data):
        teams = group_data[g]["teams"]
        base, played, remaining = _base_and_remaining(group_data[g])
        # 末轮：每队恰好剩 1 场，且整组剩 2 场未赛
        is_final = len(remaining) == 2 and all(played.get(t) == 2 for t in teams)
        if not is_final:
            out[g] = {t: "alive" for t in teams}
            continue

        pos_counts = {t: [0, 0, 0, 0] for t in teams}
        scenarios = list(product(_OUTCOMES, repeat=2))
        for combo in scenarios:
            results = [(h, a, sc[0], sc[1]) for (h, a), sc in zip(remaining, combo)]
            for pos, t in enumerate(_final_order(teams, base, results)):
                pos_counts[t][pos] += 1

        n = len(scenarios)
        states = {}
        for t in teams:
            top2 = pos_counts[t][0] + pos_counts[t][1]
            if top2 == n:
                states[t] = "qualified"
            elif top2 == 0:
                states[t] = "eliminated" if pos_counts[t][3] == n else "alive"
            else:
                states[t] = "must_win" if _win_secures_top2(t, teams, base, remaining) else "alive"
        out[g] = states
    return out


def group_state_for(states: dict, group: str, home: str, away: str) -> dict:
    """转成 context.adjusted_prediction 所需的 group_state 结构。"""
    g = states.get(group, {})
    return {"home": {"status": g.get(home, "alive")},
            "away": {"status": g.get(away, "alive")}}


def status_note(states: dict, group: str, home: str, away: str) -> str:
    """末轮战意一句话说明(供展示)；双方均 alive 时返回空串。"""
    g = states.get(group, {})
    parts = []
    for t in (home, away):
        s = g.get(t, "alive")
        if s != "alive":
            parts.append(f"{zh(t)}：{STATUS_LABEL[s]}")
    return " · ".join(parts)
