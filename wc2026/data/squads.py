"""球员大名单：FotMob 拉取 → 缓存(SQLite) → 读取。纯展示，不参与模型/概率。

只在用户手动点击时拉取当前两队，结果落库；再次查看走缓存、不重复联网。
俱乐部名经本地映射转中文，球员名可选 LLM 音译并缓存。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from wc2026.data import club_names
from wc2026.data.db import get_conn, init_db
from wc2026.data.sources import fotmob as fm
from wc2026.llm import provider

# 位置分组顺序（FotMob squad 的 position 已归一到这些）
POS_ORDER = ["Goalkeeper", "Defender", "Midfielder", "Attacker"]
POS_ZH = {"Goalkeeper": "门将", "Defender": "后卫", "Midfielder": "中场",
          "Attacker": "前锋", "Other": "其他"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_fm_id(conn, team_lib: str) -> tuple[int, str]:
    row = conn.execute(
        "SELECT fm_id, fm_name FROM fm_teams WHERE team_lib=?", (team_lib,)).fetchone()
    if row and row["fm_id"] is not None:
        return int(row["fm_id"]), row["fm_name"]
    res = fm.resolve_team_id(team_lib)
    if not res:
        raise fm.FotmobError(f"FotMob 未找到球队：{team_lib}")
    fm_id, fm_name = res
    conn.execute("INSERT OR REPLACE INTO fm_teams VALUES (?,?,?,?)",
                 (team_lib, fm_id, fm_name, _now()))
    return fm_id, fm_name


def refresh_fm_squad(team_lib: str) -> dict:
    """FotMob 拉 squad(含评分/伤停/俱乐部/头像id) 落库；保留已有中文名缓存。"""
    init_db()
    with get_conn() as conn:
        fm_id, fm_name = _get_fm_id(conn, team_lib)
        players = fm.fetch_squad(fm_id, fm_name)
        old_zh = {r["player_name"]: r["name_zh"] for r in conn.execute(
            "SELECT player_name, name_zh FROM fm_squads WHERE team_lib=?", (team_lib,))}
        now = _now()
        rows = [(
            team_lib, p["name"], p["number"], p["position"], p["age"], p["club"],
            p["rating"], 1 if p["injury"] else 0, p["injury"], now,
            p.get("player_id"), p.get("club_id"), old_zh.get(p["name"]), p.get("value"),
        ) for p in players if p["name"]]
        conn.execute("DELETE FROM fm_squads WHERE team_lib=?", (team_lib,))
        conn.executemany(
            "INSERT OR REPLACE INTO fm_squads "
            "(team_lib, player_name, number, position, age, club, rating, injured, injury_note, "
            "updated_at, player_id, club_id, name_zh, value) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return {"team_lib": team_lib, "fm_name": fm_name, "count": len(rows),
            "rated": sum(1 for p in players if p["rating"] is not None),
            "injured": sum(1 for p in players if p["injury"])}


def load_fm_squad(team_lib: str) -> dict | None:
    """读 FotMob 缓存 → {fm_name, updated_at, groups}；每名球员附中文俱乐部 + 头像/队徽 URL。"""
    with get_conn() as conn:
        trow = conn.execute(
            "SELECT fm_name FROM fm_teams WHERE team_lib=?", (team_lib,)).fetchone()
        rows = conn.execute(
            "SELECT player_name, number, position, age, club, rating, injured, injury_note, "
            "updated_at, player_id, club_id, name_zh, value "
            "FROM fm_squads WHERE team_lib=? ORDER BY COALESCE(number, 999)", (team_lib,)).fetchall()
    if not rows:
        return None
    groups: dict = {p: [] for p in POS_ORDER}
    updated = None
    for r in rows:
        d = dict(r)
        d["club_zh"] = club_names.club_zh(d.get("club"))
        d["photo_url"] = fm.player_photo(d.get("player_id"))
        d["logo_url"] = fm.club_logo(d.get("club_id"))
        pos = d["position"] if d["position"] in groups else "Other"
        groups.setdefault(pos, []).append(d)
        updated = d["updated_at"]
    groups = {k: v for k, v in groups.items() if v}
    return {"fm_name": trow["fm_name"] if trow else team_lib,
            "updated_at": updated, "groups": groups}


def squad_value_summary(groups: dict | None) -> dict:
    """从 load_fm_squad 的 groups 聚合身价（FotMob transferValue，单位欧元）。

    返回 {total, by_position, top5, count, valued_count}。
    无 value 的球员计入人数但不计身价；total 为 0 时表示该队暂无身价数据（需重新拉取）。
    """
    players = [p for plist in (groups or {}).values() for p in plist]
    valued = [p for p in players if p.get("value")]
    by_position: dict = {}
    for p in players:
        pos = p.get("position") or "Other"
        by_position[pos] = by_position.get(pos, 0.0) + float(p.get("value") or 0.0)
    top5 = sorted(valued, key=lambda p: float(p["value"]), reverse=True)[:5]
    return {
        "total": sum(float(p["value"]) for p in valued),
        "by_position": by_position,
        "top5": top5,
        "count": len(players),
        "valued_count": len(valued),
    }


FORMATIONS = {
    "4-3-3": {"Goalkeeper": 1, "Defender": 4, "Midfielder": 3, "Attacker": 3},
    "4-4-2": {"Goalkeeper": 1, "Defender": 4, "Midfielder": 4, "Attacker": 2},
    "3-5-2": {"Goalkeeper": 1, "Defender": 3, "Midfielder": 5, "Attacker": 2},
}


def estimate_lineup(groups: dict | None, formation: str = "4-3-3") -> dict:
    """启发式「预计首发 XI」：按阵型，每个位置取身价(次选评分)最高、未伤停的球员。

    首发是不确定的——这只是基于身价/评分的估计。返回 {formation, xi, total_value, size}。
    """
    counts = FORMATIONS.get(formation, FORMATIONS["4-3-3"])
    xi = []
    for pos, n in counts.items():
        avail = [p for p in (groups or {}).get(pos, []) if not p.get("injured")]
        avail.sort(key=lambda p: (float(p.get("value") or 0.0), float(p.get("rating") or 0.0)),
                   reverse=True)
        xi.extend(avail[:n])
    return {
        "formation": formation,
        "xi": xi,
        "total_value": sum(float(p.get("value") or 0.0) for p in xi),
        "size": len(xi),
    }


def _strip_json(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", t, re.S)
    return m.group(1).strip() if m else t


def _llm_translate_names(names: list[str]) -> dict:
    """英文球员名 → {英文名: 中文音译}；LLM 失败/解析失败返回空。

    MiMo 等思考型模型偶尔耗尽 token 预算导致正文为空，故给足预算并重试一次。
    """
    listing = "\n".join(f"- {n}" for n in names)
    prompt = (
        "把下列足球球员的名字翻译成中文：知名球员用约定俗成的通用译名，其余按发音音译。"
        "严格只输出一个 JSON 对象，键为原英文名、值为中文名，不要任何多余文字：\n" + listing
    )
    for _ in range(2):
        try:
            text = provider.chat(prompt, max_tokens=16000, temperature=0.2, timeout=180)
        except provider.LLMError:
            continue
        try:
            data = json.loads(_strip_json(text))
        except Exception:
            continue
        if isinstance(data, dict) and data:
            return {k: v for k, v in data.items() if isinstance(v, str)}
    return {}


def translate_player_names(team_lib: str) -> dict:
    """对该队尚无中文名的球员做 LLM 音译并写回缓存。返回 {translated, total}。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT player_name FROM fm_squads WHERE team_lib=? AND (name_zh IS NULL OR name_zh='')",
            (team_lib,)).fetchall()
    names = [r["player_name"] for r in rows]
    if not names:
        return {"translated": 0, "total": 0}
    mapping = _llm_translate_names(names)
    if mapping:
        with get_conn() as conn:
            for en, zhn in mapping.items():
                conn.execute("UPDATE fm_squads SET name_zh=? WHERE team_lib=? AND player_name=?",
                             (zhn, team_lib, en))
    return {"translated": len(mapping), "total": len(names)}
