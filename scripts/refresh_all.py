"""一键全量刷新：抓历史赛果 + 更新赛程 + 回填赛果 + 导出 wc_results.json + 重训模型。

供 cron / GitHub Actions / 手动运行：python scripts/refresh_all.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.refresh import format_refresh_summary, resilient_refresh


def main() -> None:
    print(format_refresh_summary(resilient_refresh()))


if __name__ == "__main__":
    main()
