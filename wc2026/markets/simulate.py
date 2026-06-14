"""比分蒙特卡洛：从模型比分矩阵抽样 N 次，统计最高频比分，与解析概率并排对比。

用途：自洽验证——单场分析里「最可能比分 / 胜平负 / 大小球」是从矩阵解析算出的；
抽样频率应收敛到解析概率。两者吻合即验证了推导正确（抽的是同一模型，非独立预测）。
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from wc2026.markets import derive


def simulate_match(mat, n_sims: int = 10000, top_k: int = 8, seed: int = 12345) -> dict:
    """返回 {n, top_scores:[{score,sim_prob,model_prob}], sim_1x2, model_1x2,
    sim_ou25, model_ou25, exp_goals_sim, max_abs_err}。"""
    mat = np.asarray(mat, dtype=float)
    rows, cols = mat.shape
    flat = mat.ravel()
    total = flat.sum()
    p = flat / total if total > 0 else np.full(flat.size, 1.0 / flat.size)
    rng = np.random.default_rng(seed)
    idx = rng.choice(flat.size, size=n_sims, p=p)
    hg, ag = idx // cols, idx % cols

    cnt = Counter(zip(hg.tolist(), ag.tolist()))
    top = []
    for (i, j), c in cnt.most_common(top_k):
        top.append({"score": f"{i}-{j}", "sim_prob": c / n_sims, "model_prob": float(mat[i, j])})

    sim_1x2 = {"home": float((hg > ag).mean()), "draw": float((hg == ag).mean()),
               "away": float((hg < ag).mean())}
    model_1x2 = derive.outcomes_1x2(mat)
    tot = hg + ag
    sim_ou = {"over": float((tot > 2.5).mean()), "under": float((tot < 2.5).mean())}
    ou = derive.over_under(mat, 2.5)
    model_ou = {"over": ou["over"], "under": ou["under"]}
    max_err = max(abs(sim_1x2[k] - model_1x2[k]) for k in sim_1x2)
    return {
        "n": n_sims, "top_scores": top,
        "sim_1x2": sim_1x2, "model_1x2": model_1x2,
        "sim_ou25": sim_ou, "model_ou25": model_ou,
        "exp_goals_sim": (float(hg.mean()), float(ag.mean())),
        "max_abs_err": max_err,
    }
