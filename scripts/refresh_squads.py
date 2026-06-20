"""批量重抓全部参赛队的 FotMob 阵容（身价 + 阵型 + 评分），落库缓存。

用途：让九维度的「阵容实力」用上真实身价、组合模型用上真实阵型。
- 队名来自 fixtures(predictable=1) 的全部 48 队。
- FotMob 每队约 3 次请求（suggest + squad + formation），内置 1s 礼貌限速，
  全程约 2-3 分钟。逐队失败不中断，最后汇总身价/阵型覆盖率。

用法： python scripts/refresh_squads.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.data.db import get_conn
from wc2026.data import squads


def all_teams() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT home_team t FROM fixtures WHERE predictable=1 "
            "UNION SELECT DISTINCT away_team FROM fixtures WHERE predictable=1"
        ).fetchall()
    return sorted(r["t"] for r in rows)


def main() -> None:
    teams = all_teams()
    print(f"开始批量刷新 {len(teams)} 队 FotMob 阵容（礼貌限速，约 2-3 分钟）…\n")
    ok = valued = formed = 0
    failed: list[tuple[str, str]] = []
    for i, t in enumerate(teams, 1):
        try:
            r = squads.refresh_fm_squad(t)
            sq = squads.load_fm_squad(t)
            vs = squads.squad_value_summary(sq["groups"]) if sq else {"total": 0.0, "valued_count": 0}
            has_val = vs["total"] > 0
            has_form = bool(r.get("formation"))
            ok += 1
            valued += has_val
            formed += has_form
            print(f"[{i:2d}/{len(teams)}] {t:28s} 人{r['count']:2d} "
                  f"身价{'€%.0fM' % (vs['total'] / 1e6) if has_val else '—':>9s} "
                  f"阵型{r.get('formation') or '—':>8s}")
        except Exception as e:
            failed.append((t, f"{type(e).__name__}: {str(e)[:80]}"))
            print(f"[{i:2d}/{len(teams)}] {t:28s} ❌ {type(e).__name__}: {str(e)[:80]}")

    print(f"\n完成：成功 {ok}/{len(teams)}，含身价 {valued}，含阵型 {formed}。")
    if failed:
        print(f"失败 {len(failed)} 队：")
        for t, why in failed:
            print(f"  - {t}: {why}")


if __name__ == "__main__":
    main()
