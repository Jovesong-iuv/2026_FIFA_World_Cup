"""一键全量刷新：抓历史赛果 + 更新赛程 + 回填赛果 + 导出 wc_results.json + 重训模型。

供 cron / GitHub Actions / 手动运行：python scripts/refresh_all.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.analysis.adjustments import recompute
from wc2026.data.db import init_db
from wc2026.data.ingest import ingest_international_results
from wc2026.data.results import backfill_fixture_scores, export_results_json
from wc2026.data.sources.fixtures_2026 import fetch_and_store_fixtures
from wc2026.models.predictor import train_and_save


def main() -> None:
    init_db()
    print("1/6 抓取国际赛历史结果 …")
    s = ingest_international_results()
    print(f"    库内共 {s['total']} 场，新增 {s['new']} 场")

    print("2/6 更新 2026 赛程 …")
    try:
        fetch_and_store_fixtures()
        print("    赛程已更新")
    except Exception as exc:
        print(f"    赛程刷新失败（忽略）：{exc}")

    print("3/6 回填 fixtures 赛果 …")
    print(f"    回填 {backfill_fixture_scores()} 场")

    print("4/6 导出 data/wc_results.json …")
    print(f"    导出 {export_results_json()} 场")

    print("5/6 重训 Dixon-Coles + Elo …")
    model = train_and_save()
    print("    完成。")

    print("6/6 重算赛中实力修正(已完赛结果) …")
    adj = recompute(model, with_news=False)
    print(f"    修正 {len(adj)} 支球队。模型与赛果已更新。")


if __name__ == "__main__":
    main()
