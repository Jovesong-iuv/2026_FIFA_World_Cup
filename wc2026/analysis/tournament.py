"""整届世界杯蒙特卡洛：小组 → 淘汰赛（32 强→决赛）→ 各队 进16/8/4强、进决赛、夺冠 概率。

复用模型比分概率。近似与假设（仅供参考）：
1) 淘汰赛对阵树按 match_number 顺序两两配对（fixtures 中 round5+ 为 TBA，采用标准顺序 bracket）；
2) 8 个最佳小组第三按 slot 资格做二分匹配分配（官方为确定分配表，此处取一个合法分配）；
3) 平局用「加时/点球」近似：以 P(胜)/(P(胜)+P(负)) 决出（强队略占优）。
"""
from __future__ import annotations

import numpy as np

from wc2026.markets import derive

GROUPS = list("ABCDEFGHIJKL")
HOSTS = {"Mexico", "Canada", "United States"}

# R32 对阵（2026，按 match_number 73..88）
R32_SLOTS = [
    ("2A", "2B"), ("1E", "3ABCDF"), ("1F", "2C"), ("1C", "2F"),
    ("1I", "3CDFGH"), ("2E", "2I"), ("1A", "3CEFHI"), ("1L", "3EHIJK"),
    ("1D", "3BEFIJ"), ("1G", "3AEHIJ"), ("2K", "2L"), ("1H", "2J"),
    ("1B", "3EFGIJ"), ("1J", "2H"), ("1K", "3DEIJL"), ("2D", "2G"),
]
_THIRD_SLOTS = [s for pair in R32_SLOTS for s in pair if s.startswith("3")]


def _goal_samples(model, home, away, hs, as_, n, rng):
    if hs is not None and as_ is not None:
        return np.full(n, int(hs)), np.full(n, int(as_))
    neutral = home not in HOSTS
    mat = np.asarray(model.score_matrix(home, away, neutral), dtype=float)
    ncols = mat.shape[1]
    flat = mat.ravel()
    tot = flat.sum()
    flat = flat / tot if tot > 0 else np.full_like(flat, 1.0 / flat.size)
    idx = rng.choice(flat.size, size=n, p=flat)
    return idx // ncols, idx % ncols


def _advance_prob(model, teams: list[str]) -> dict:
    """P(a 淘汰赛淘汰 b)（中立、含加时点球近似），对所有无序对各算一次比分矩阵。"""
    P = {}
    for i in range(len(teams)):
        for j in range(i + 1, len(teams)):
            a, b = teams[i], teams[j]
            x = derive.outcomes_1x2(model.score_matrix(a, b, True))
            pw, pd, pl = x["home"], x["draw"], x["away"]
            pens_a = pw / (pw + pl) if (pw + pl) > 0 else 0.5
            P[(a, b)] = pw + pd * pens_a
            P[(b, a)] = pl + pd * (1 - pens_a)
    return P


def _match_thirds(adv_groups: list[str], slot_sets: list[set]):
    """把 8 个晋级小组第三按 slot 资格二分匹配。返回 [slot_idx 对应的 group]，失败 None。"""
    n = len(slot_sets)
    order = sorted(range(n), key=lambda i: len(slot_sets[i]))  # 选项少的先分配
    used, assign = set(), {}
    advset = set(adv_groups)

    def bt(k):
        if k == n:
            return True
        i = order[k]
        for g in slot_sets[i]:
            if g in advset and g not in used:
                used.add(g); assign[i] = g
                if bt(k + 1):
                    return True
                used.discard(g); assign.pop(i, None)
        return False

    return assign if bt(0) else None


def simulate_tournament(model, group_data: dict, n_sims: int = 2000, seed: int = 20260611) -> dict:
    """返回 {team: {r16, qf, sf, final, champion}}（概率 0~1）。"""
    rng = np.random.default_rng(seed)
    glist = [g for g in GROUPS if f"Group {g}" in group_data]
    teams_of = {g: group_data[f"Group {g}"]["teams"] for g in glist}

    # —— 向量化小组名次 ——
    first, second, third, third_key = {}, {}, {}, {}
    for g in glist:
        gd = group_data[f"Group {g}"]
        teams = gd["teams"]
        pts = np.zeros((4, n_sims)); gf = np.zeros((4, n_sims)); ga = np.zeros((4, n_sims))
        for (hi, ai, hs, as_) in gd["matches"]:
            hg, ag = _goal_samples(model, teams[hi], teams[ai], hs, as_, n_sims, rng)
            gf[hi] += hg; ga[hi] += ag; gf[ai] += ag; ga[ai] += hg
            draw = hg == ag
            pts[hi] += 3 * (hg > ag) + draw
            pts[ai] += 3 * (hg < ag) + draw
        key = pts * 1e7 + (gf - ga + 100.0) * 1e4 + gf * 10.0 + rng.random((4, n_sims))
        order = np.argsort(-key, axis=0)
        sims = np.arange(n_sims)
        first[g], second[g], third[g] = order[0], order[1], order[2]
        third_key[g] = key[order[2], sims]

    # 跨组最佳 8 个第三
    tk = np.vstack([third_key[g] for g in glist])  # (G, N)
    adv_rank = np.argsort(-tk, axis=0)
    n_adv = min(8, len(glist))
    adv_mask = np.zeros((len(glist), n_sims), dtype=bool)
    for slot in range(n_adv):
        adv_mask[adv_rank[slot], np.arange(n_sims)] = True

    all_teams = sorted({t for g in glist for t in teams_of[g]})
    adv = _advance_prob(model, all_teams)
    slot_sets = [set(s[1:]) for s in _THIRD_SLOTS]

    reach = {t: {"r16": 0, "qf": 0, "sf": 0, "final": 0, "champion": 0} for t in all_teams}
    rounds = ["r16", "qf", "sf", "final", "champion"]

    for s in range(n_sims):
        slotmap = {}
        for gi, g in enumerate(glist):
            slotmap[f"1{g}"] = teams_of[g][first[g][s]]
            slotmap[f"2{g}"] = teams_of[g][second[g][s]]
        adv_groups = [g for gi, g in enumerate(glist) if adv_mask[gi, s]]
        assign = _match_thirds(adv_groups, slot_sets)
        if assign is None:
            continue
        for slot_idx, grp in assign.items():
            slotmap[_THIRD_SLOTS[slot_idx]] = teams_of[grp][third[grp][s]]

        # R32 对阵 → 逐轮顺序推进
        bracket = [(slotmap[h], slotmap[a]) for (h, a) in R32_SLOTS]
        for rnd in rounds:
            winners = []
            for (A, B) in bracket:
                w = A if rng.random() < adv.get((A, B), 0.5) else B
                reach[w][rnd] += 1
                winners.append(w)
            bracket = [(winners[i], winners[i + 1]) for i in range(0, len(winners), 2)] if len(winners) > 1 else []
            if not bracket:
                break

    return {t: {k: reach[t][k] / n_sims for k in rounds} for t in all_teams}
