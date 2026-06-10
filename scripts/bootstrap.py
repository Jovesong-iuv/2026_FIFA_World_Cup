"""容器启动初始化：库为空则抓数据，模型缺失则训练。幂等，可重复运行。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.data.db import get_conn, init_db
from wc2026.data.ingest import ingest_international_results
from wc2026.data.sources.fixtures_2026 import fetch_and_store_fixtures
from wc2026.models.predictor import DC_PATH, train_and_save


def main() -> None:
    init_db()
    with get_conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    if n == 0:
        print("库为空，抓取历史数据 …")
        stats = ingest_international_results()
        print(f"  入库 {stats['total']} 场")
    else:
        print(f"已有 {n} 场比赛，跳过抓取。")

    if not DC_PATH.exists():
        print("训练 Dixon-Coles + Elo 集成模型 …")
        train_and_save()
        print("  模型已保存。")
    else:
        print("模型已存在，跳过训练。")

    print("抓取 2026 赛程 …")
    try:
        fx = fetch_and_store_fixtures()
        print(f"  赛程 {fx['fixtures']} 场（可预测 {fx['predictable']}）")
    except Exception as exc:
        print(f"  赛程抓取失败（稍后可在看板刷新）：{exc}")
    print("初始化完成。")


if __name__ == "__main__":
    main()
