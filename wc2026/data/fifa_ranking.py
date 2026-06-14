"""FIFA 男足世界排名：从 data/fifa_ranking.json 读取（按中文队名键，源自 FIFA 官方）。

查找：team_names.zh(库名) → 中文名 → 排名；3 个中文写法差异用 _ZH_ALIAS 校正。
查不到（不在 211 名内或中文名不匹配）返回 None，由上层回退 Elo。
更新榜单：编辑 data/fifa_ranking_raw.txt 后运行 scripts/update_fifa_ranking.py 重新生成本 JSON。
"""
from __future__ import annotations

import json
from functools import lru_cache

from wc2026.config import settings
from wc2026.data.team_names import zh

# zh() 输出 → FIFA 榜中文写法（仅写法不同的；其余 45 支参赛队一致）
_ZH_ALIAS = {
    "波黑": "波斯尼亚和黑塞哥维那",
    "刚果(金)": "刚果民主共和国",
    "伊朗": "伊朗伊斯兰共和国",
}


@lru_cache(maxsize=1)
def _data() -> dict:
    path = settings.data_dir / "fifa_ranking.json"
    if not path.exists():
        return {"date": None, "ranks_zh": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"date": None, "ranks_zh": {}}


def ranking_date() -> str | None:
    return _data().get("date")


def fifa_rank(team_lib: str) -> int | None:
    cn = zh(team_lib)
    cn = _ZH_ALIAS.get(cn, cn)
    return _data().get("ranks_zh", {}).get(cn)
