"""一次性工具：拉所有 2026 世界杯参赛队的 FotMob 阵容，收集全部俱乐部名，
找出 club_names.CLUB_ZH 未覆盖的，用 LLM 批量翻译，打印可合并的 dict 片段。

用法： python scripts/build_club_map.py
（联网 FotMob ~每队 2 请求 + 内置 1s 限速；再走 LLM 翻译未命中俱乐部）
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.data.db import get_conn
from wc2026.data.sources import fotmob as fm
from wc2026.data.club_names import club_zh
from wc2026.llm import provider


def wc_teams() -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT home_team FROM fixtures WHERE predictable=1 "
            "UNION SELECT away_team FROM fixtures WHERE predictable=1"
        ).fetchall()
    return sorted({r[0] for r in rows if r[0]})


def collect_clubs(teams: list[str]) -> tuple[set, list]:
    clubs, failed = set(), []
    for t in teams:
        try:
            res = fm.resolve_team_id(t)
            if not res:
                failed.append(t)
                continue
            for p in fm.fetch_squad(res[0], res[1]):
                if p.get("club"):
                    clubs.add(p["club"])
            print(f"  ok {t} -> {res[1]} ({len(clubs)} clubs so far)")
        except Exception as e:
            failed.append(f"{t}: {type(e).__name__}")
    return clubs, failed


def translate_clubs(names: list[str]) -> dict:
    listing = "\n".join(f"- {n}" for n in names)
    prompt = (
        "把下列足球俱乐部名翻译成通用中文译名（用约定俗成的官方/媒体常用译名）。"
        "严格只输出一个 JSON 对象，键为原英文名、值为中文名，不要任何多余文字：\n" + listing
    )
    for _ in range(2):
        try:
            text = provider.chat(prompt, max_tokens=16000, temperature=0.2, timeout=180)
        except provider.LLMError:
            continue
        m = re.search(r"```(?:json)?\s*(.+?)\s*```", text.strip(), re.S)
        body = m.group(1).strip() if m else text.strip()
        try:
            d = json.loads(body)
            if isinstance(d, dict) and d:
                return {k: v for k, v in d.items() if isinstance(v, str)}
        except Exception:
            continue
    return {}


def main() -> None:
    teams = wc_teams()
    print(f"{len(teams)} 参赛队:", teams)
    if not teams:
        print("fixtures 表为空，请先运行 scripts/update_data.py")
        return
    clubs, failed = collect_clubs(teams)
    print(f"\n收集到 {len(clubs)} 个不同俱乐部；失败队: {failed}")
    unmapped = sorted(c for c in clubs if club_zh(c) == c)
    print(f"未映射 {len(unmapped)} 个:\n", unmapped)

    mapping = {}
    for i in range(0, len(unmapped), 40):
        mapping.update(translate_clubs(unmapped[i:i + 40]))
    print(f"\n已翻译 {len(mapping)}/{len(unmapped)}")

    out_path = Path("/tmp/club_map.json")
    out_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out_path}")

    print("\n===== 合并进 club_names.CLUB_ZH 的片段 =====")
    for k in sorted(mapping):
        print(f"    {json.dumps(k, ensure_ascii=False)}: {json.dumps(mapping[k], ensure_ascii=False)},")
    miss = [c for c in unmapped if c not in mapping]
    if miss:
        print("\n# 仍未翻译(可手动补):", miss)


if __name__ == "__main__":
    main()
