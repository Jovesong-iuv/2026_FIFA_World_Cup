"""抓取并更新数据源。核心版：国际赛历史结果。

用法： python scripts/update_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.data.ingest import ingest_international_results


def main() -> None:
    print("抓取国际赛历史结果 ...")
    stats = ingest_international_results()
    print(f"完成：库内共 {stats['total']} 场，本次新增 {stats['new']} 场。")


if __name__ == "__main__":
    main()
