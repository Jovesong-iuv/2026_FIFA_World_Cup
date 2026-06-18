"""临场刷新：锁定进入 T-window 的比赛赛前快照（文档 §6.3 / §12 阶段3）。

供更频繁的 cron / GitHub Actions 调用：python scripts/refresh_imminent.py [window_hours]
- 扫描赛程，找出距开赛 window_hours（默认 3）内、尚未开赛的比赛；
- 为每场生成并锁定 MatchIntelligenceReport 快照（含较上一锁定版的关键变化检测与风险升级）；
- 写入 predictions 表 + 合并导出 data/prematch_snapshots.json（可提交，供线上单场页/赛后复盘
  复用真正的赛前锁定值，而非事后复算）。

无 ODDS_API_KEY 时市场后验自动降级，不阻塞锁定。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.analysis.imminent import imminent_fixtures, lock_prematch_snapshot, SNAPSHOTS_JSON
from wc2026.data.db import get_conn, init_db
from wc2026.models.predictor import get_model


def _load_fixtures() -> list:
    cols = ("match_number, round_number, date_utc, home_team, away_team, "
            "group_name, location, home_score, away_score")
    with get_conn() as c:
        rows = c.execute(f"SELECT {cols} FROM fixtures WHERE predictable=1").fetchall()
    return [dict(r) for r in rows]


def main(window_hours: float = 3.0) -> None:
    init_db()
    model = get_model()
    fixtures = _load_fixtures()
    imm = imminent_fixtures(fixtures, window_hours=window_hours)
    print(f"临场窗口 {window_hours}h 内未开赛比赛：{len(imm)} 场")
    if not imm:
        print("无需锁定。")
        return
    for f in imm:
        snap = lock_prematch_snapshot(model, f, fixtures=fixtures)
        ch = snap["changes"]
        tag = ("（重大变化，已升级风险）" if ch.get("escalate")
               else ("（有变化）" if ch.get("changed") else ""))
        o = snap["outcomes"]
        print(f"  #{f['match_number']} {snap['home_cn']} vs {snap['away_cn']} "
              f"T-{f['_hours_to_kickoff']:.1f}h 锁定 "
              f"主/平/客={o['home']:.0%}/{o['draw']:.0%}/{o['away']:.0%} {tag}")
        for c in ch.get("changes", []):
            print(f"      • {c}")
    print(f"快照已写入 {SNAPSHOTS_JSON}")


if __name__ == "__main__":
    win = float(sys.argv[1]) if len(sys.argv) > 1 else 3.0
    main(win)
