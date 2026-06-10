"""冒烟测试：训练 Dixon-Coles，预测几场对阵，检查概率合理性。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np

from wc2026.models.predictor import train_and_save


def main() -> None:
    t = time.time()
    m = train_and_save(since_years=12)
    print(f"训练完成：耗时 {time.time()-t:.1f}s，球队数={len(m.teams)}，"
          f"home_adv={m.home_adv:.3f}，rho={m.rho:.3f}")

    # 强度榜前 10（attack - defense 综合）
    rank = sorted(m.teams, key=lambda t: m.attack[t] - m.defense[t], reverse=True)[:10]
    print("综合强度前 10：", "、".join(rank))

    print("\n样例对阵（中立场）：")
    for h, a in [("Brazil", "Argentina"), ("Spain", "Germany"),
                 ("France", "Morocco"), ("Japan", "United States")]:
        if not (m.has_team(h) and m.has_team(a)):
            print(f"  跳过 {h} vs {a}（缺数据）")
            continue
        lam, mu = m.expected_goals(h, a, neutral=True)
        mat = m.score_matrix(h, a, neutral=True)
        ph = np.tril(mat, -1).sum()
        pdr = np.trace(mat)
        pa = np.triu(mat, 1).sum()
        ij = np.unravel_index(np.argmax(mat), mat.shape)
        print(f"  {h} vs {a}: λ={lam:.2f} μ={mu:.2f} | "
              f"胜 {ph:.1%} / 平 {pdr:.1%} / 负 {pa:.1%} | "
              f"最可能比分 {ij[0]}-{ij[1]} ({mat[ij]:.1%}) | Σ={mat.sum():.3f}")


if __name__ == "__main__":
    main()
