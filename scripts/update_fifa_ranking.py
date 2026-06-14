"""从 data/fifa_ranking_raw.txt 生成 data/fifa_ranking.json（按中文队名键）。

为什么不直接抓网络：FIFA 官网与 Sofascore 均为 JS 渲染 + 反爬，HTTP 抓不到完整表；
Wikipedia 的 FIFA 数据模块会滞后官网一个版本（实测与官方不一致）。因此采用
「人工从 FIFA 官网复制 → 存到本地 raw 文件 → 本脚本解析」的可靠方式。

raw 文件格式：每行一支球队，「<排名> <中文队名> ...任意杂项... <积分>」，例如
    13 墨西哥 FT 1700.98
解析规则：第一个 token = 排名，第二个 token = 中文名，最后一个 token = 积分。

用法：编辑 data/fifa_ranking_raw.txt 后运行  python scripts/update_fifa_ranking.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "fifa_ranking_raw.txt"
OUT = ROOT / "data" / "fifa_ranking.json"
DATE = "2026-06-11"   # FIFA 官方该期发布日；如换期次请一并更新
SOURCE = "FIFA 官方（inside.fifa.com，用户校对）"


def parse(path: Path) -> dict:
    ranks, pts = {}, []
    for line in path.read_text(encoding="utf-8").splitlines():
        toks = line.split()
        if len(toks) < 3 or not toks[0].isdigit():
            continue
        rank, name, points = int(toks[0]), toks[1], float(toks[-1])
        ranks[name] = rank
        pts.append((rank, points))
    if not ranks:
        raise RuntimeError("未解析到任何排名，请检查 raw 文件格式")
    if [r for r, _ in pts] != list(range(1, len(pts) + 1)):
        raise RuntimeError("排名非连续 1..N，raw 文件可能有缺漏")
    if not all(pts[i][1] > pts[i + 1][1] for i in range(len(pts) - 1)):
        raise RuntimeError("积分非严格递减，排名与队名可能错位")
    return ranks


if __name__ == "__main__":
    if not RAW.exists():
        sys.exit(f"找不到 {RAW}；请先把 FIFA 官网排名按「排名 中文名 … 积分」格式贴进该文件。")
    ranks = parse(RAW)
    OUT.write_text(json.dumps({"date": DATE, "source": SOURCE, "ranks_zh": ranks},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {OUT}：{len(ranks)} 支队伍，日期 {DATE}")
