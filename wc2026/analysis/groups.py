"""小组出线蒙特卡洛模拟。

2026 赛制：每组 4 队单循环，前 2 名直接出线；12 个小组第三名里成绩最好的 8 个递补晋级。

- 未结束比赛：用模型比分概率矩阵抽样比分。
- 已结束比赛：用真实比分（支持赛事进行中重算，见需求 5.2.4 / 13.3）。
- 排序近似世界杯规则：积分 > 净胜球 > 进球数 > 随机。真实赛会还含相互战绩、公平竞赛分、
  抽签等次级规则，此处不完全实现，以随机打破剩余平局。

只依赖模型与数据库已有的赛程/比分，不引入外部数据。
"""
from __future__ import annotations

import numpy as np

from wc2026.data.db import get_conn

HOSTS = {"Mexico", "Canada", "United States"}
VALID_GROUPS = [f"Group {c}" for c in "ABCDEFGHIJKL"]


def load_group_data(model) -> dict:
    """从 DB 读取 12 个小组的对阵与真实比分。

    返回 {group: {"teams": [4 支队], "matches": [(home_idx, away_idx, hs, as), ...]}}。
    只保留两队都在模型中、且恰好 4 支队的完整小组。
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT group_name, home_team, away_team, home_score, away_score "
            "FROM fixtures WHERE predictable=1 AND group_name IS NOT NULL AND group_name!='' "
            "ORDER BY group_name, date_utc"
        ).fetchall()
    raw: dict = {}
    for r in rows:
        g = r["group_name"]
        if g not in VALID_GROUPS:
            continue
        h, a = r["home_team"], r["away_team"]
        if not (model.has_team(h) and model.has_team(a)):
            continue
        gd = raw.setdefault(g, {"teams": [], "matches": []})
        for t in (h, a):
            if t not in gd["teams"]:
                gd["teams"].append(t)
        gd["matches"].append((h, a, r["home_score"], r["away_score"]))
    out = {}
    for g, gd in raw.items():
        if len(gd["teams"]) != 4:
            continue
        ti = {t: i for i, t in enumerate(gd["teams"])}
        out[g] = {"teams": gd["teams"],
                  "matches": [(ti[h], ti[a], hs, a_) for (h, a, hs, a_) in gd["matches"]]}
    return out


def played_signature(group_data: dict) -> tuple:
    """已结束比赛的签名，用于缓存失效：赛果变化时重算。"""
    sig = []
    for g in sorted(group_data):
        for (hi, ai, hs, as_) in group_data[g]["matches"]:
            if hs is not None and as_ is not None:
                sig.append((g, hi, ai, int(hs), int(as_)))
    return tuple(sig)


def _goal_samples(model, home, away, hs, as_, n, rng):
    """单场 (home_goals[n], away_goals[n])：已结束用真实比分，否则按比分矩阵抽样。"""
    if hs is not None and as_ is not None:
        return np.full(n, int(hs)), np.full(n, int(as_))
    neutral = home not in HOSTS  # 东道主保留主场优势
    mat = np.asarray(model.score_matrix(home, away, neutral), dtype=float)
    ncols = mat.shape[1]
    flat = mat.ravel()
    total = flat.sum()
    flat = flat / total if total > 0 else np.full_like(flat, 1.0 / flat.size)
    idx = rng.choice(flat.size, size=n, p=flat)
    return idx // ncols, idx % ncols


def simulate_groups(model, group_data: dict, n_sims: int = 10000, seed: int = 12345) -> dict:
    """蒙特卡洛模拟所有小组，返回 {group: [按出线概率降序的球队字典]}。

    每支球队字典含 team / first / top2 / third / third_advance / qualify（均为概率 0~1）。
    第三名递补需跨组比较，因此所有小组在同一批模拟中联合统计。
    """
    rng = np.random.default_rng(seed)
    glist = sorted(group_data)
    G = len(glist)
    per_group = {}
    thirds_key = np.empty((G, n_sims))  # 各组第三名的排序键，用于跨组比较

    for gi, g in enumerate(glist):
        gd = group_data[g]
        teams = gd["teams"]
        pts = np.zeros((4, n_sims))
        gf = np.zeros((4, n_sims))
        ga = np.zeros((4, n_sims))
        for (hi, ai, hs, as_) in gd["matches"]:
            hg, ag = _goal_samples(model, teams[hi], teams[ai], hs, as_, n_sims, rng)
            gf[hi] += hg; ga[hi] += ag
            gf[ai] += ag; ga[ai] += hg
            draw = hg == ag
            pts[hi] += 3 * (hg > ag) + draw
            pts[ai] += 3 * (hg < ag) + draw
        gdiff = gf - ga
        # 排序键：积分 > 净胜球 > 进球数 > 随机；各权重保证字典序不串位
        key = pts * 1e7 + (gdiff + 100.0) * 1e4 + gf * 10.0 + rng.random((4, n_sims))
        order = np.argsort(-key, axis=0)  # order[0]=第一名队索引, [1]=第二, [2]=第三
        first, second, third = order[0], order[1], order[2]
        sims = np.arange(n_sims)
        per_group[g] = {
            "teams": teams,
            "first": np.array([(first == i).sum() for i in range(4)]),
            "top2": np.array([((first == i) | (second == i)).sum() for i in range(4)]),
            "third": np.array([(third == i).sum() for i in range(4)]),
            "third_order": third,
        }
        thirds_key[gi] = key[third, sims]

    # 跨组：成绩最好的 min(8, G) 个小组第三递补晋级
    n_adv = min(8, G)
    adv_groups = np.argsort(-thirds_key, axis=0)[:n_adv]  # (n_adv, n_sims) 晋级的组索引
    adv_mask = np.zeros((G, n_sims), dtype=bool)
    sims = np.arange(n_sims)
    for slot in range(n_adv):
        adv_mask[adv_groups[slot], sims] = True

    result = {}
    for gi, g in enumerate(glist):
        pg = per_group[g]
        third = pg["third_order"]
        mask = adv_mask[gi]
        rows = []
        for i, t in enumerate(pg["teams"]):
            top2 = int(pg["top2"][i])
            third_adv = int(((third == i) & mask).sum())
            rows.append({
                "team": t,
                "first": pg["first"][i] / n_sims,
                "top2": top2 / n_sims,
                "third": pg["third"][i] / n_sims,
                "third_advance": third_adv / n_sims,
                "qualify": (top2 + third_adv) / n_sims,  # 前二与第三递补互斥，可直接相加
            })
        rows.sort(key=lambda d: d["qualify"], reverse=True)
        result[g] = rows
    return result


def _h2h_order(block: list[dict], played_pairs: list[tuple]) -> list[dict]:
    """对积分/净胜球/进球完全并列的子集，用其内部已赛比赛(相互战绩)细分。"""
    names = {r["team"] for r in block}
    mini = {t: {"pts": 0, "gd": 0, "gf": 0} for t in names}
    for (h, a, hs, as_) in played_pairs:
        if h in names and a in names:
            mini[h]["gf"] += hs; mini[h]["gd"] += hs - as_
            mini[a]["gf"] += as_; mini[a]["gd"] += as_ - hs
            if hs > as_:
                mini[h]["pts"] += 3
            elif hs < as_:
                mini[a]["pts"] += 3
            else:
                mini[h]["pts"] += 1; mini[a]["pts"] += 1
    return sorted(block, key=lambda r: (-mini[r["team"]]["pts"], -mini[r["team"]]["gd"],
                                        -mini[r["team"]]["gf"], r["team"]))


def compute_standings(group_data: dict) -> dict:
    """基于已完赛比分算各组真实积分榜。返回 {group: [row...]}（按名次升序）。

    row: team / played / w / d / l / gf / ga / gd / pts / rank。
    排序：积分 > 净胜球 > 进球 > 相互战绩 > 队名（近似世界杯规则；未实现公平竞赛分等更次级规则）。
    只统计已结束比赛（小组赛进行中即为当前榜）。
    """
    out = {}
    for g in sorted(group_data):
        teams = group_data[g]["teams"]
        st = {t: {"team": t, "played": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0} for t in teams}
        played_pairs = []
        for (hi, ai, hs, as_) in group_data[g]["matches"]:
            if hs is None or as_ is None:
                continue
            h, a, hs, as_ = teams[hi], teams[ai], int(hs), int(as_)
            st[h]["played"] += 1; st[h]["gf"] += hs; st[h]["ga"] += as_
            st[a]["played"] += 1; st[a]["gf"] += as_; st[a]["ga"] += hs
            if hs > as_:
                st[h]["w"] += 1; st[a]["l"] += 1
            elif hs < as_:
                st[a]["w"] += 1; st[h]["l"] += 1
            else:
                st[h]["d"] += 1; st[a]["d"] += 1
            played_pairs.append((h, a, hs, as_))

        rows = list(st.values())
        for r in rows:
            r["gd"] = r["gf"] - r["ga"]
            r["pts"] = r["w"] * 3 + r["d"]
        rows.sort(key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["team"]))

        # 对 (pts,gd,gf) 完全并列的连续段做相互战绩细分
        ordered, i, n = [], 0, len(rows)
        while i < n:
            j = i
            while j < n and (rows[j]["pts"], rows[j]["gd"], rows[j]["gf"]) == \
                    (rows[i]["pts"], rows[i]["gd"], rows[i]["gf"]):
                j += 1
            block = rows[i:j]
            ordered.extend(_h2h_order(block, played_pairs) if len(block) > 1 else block)
            i = j
        for k, r in enumerate(ordered, 1):
            r["rank"] = k
        out[g] = ordered
    return out
