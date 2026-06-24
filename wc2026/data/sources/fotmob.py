"""FotMob 数据（无需 key/token）：解析球队页内嵌的 __NEXT_DATA__，取阵容 + 评分 + 伤停。

FotMob 是 Next.js 应用，球队页 HTML 内嵌 __NEXT_DATA__，其 SWR fallback 含 squad
(按位置分组，每名球员带 rating / injury / 所属俱乐部)。无官方 API，属解析页面数据，
请礼貌限速 + 缓存。注意：赛季无数据时 rating 为 null（赛前常见，开赛后逐场填充）；
injury 通常已实时（来自俱乐部伤情）。队名 → 队 ID 经 apigw suggest 解析。
"""
from __future__ import annotations

import json
import re
import time

import requests

_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
_SUGGEST = "https://apigw.fotmob.com/searchapi/suggest"
_MIN_INTERVAL = 1.0  # 礼貌限速：相邻请求至少间隔 1s
_LAST = {"t": 0.0}

# 个别队名 FotMob 搜索词与库名不一致时的覆写（库名 → 搜索词）
SEARCH_ALIAS = {"United States": "USA", "Czech Republic": "Czechia"}

# FotMob squad 分组标题 → 标准位置
_GROUP_POS = {"keepers": "Goalkeeper", "defenders": "Defender",
              "midfielders": "Midfielder", "attackers": "Attacker"}


class FotmobError(Exception):
    pass


def _throttle() -> None:
    dt = time.monotonic() - _LAST["t"]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _LAST["t"] = time.monotonic()


def _get(url: str, timeout: float = 25):
    _throttle()
    r = requests.get(url, headers=_UA, timeout=timeout)
    if r.status_code != 200:
        raise FotmobError(f"HTTP {r.status_code}: {url}")
    return r


def resolve_team_id(team_lib: str) -> tuple[int, str] | None:
    """库名 → (fotmob_id, fotmob_name)。优先精确同名的成年男队（排除 (W)/U23 等）。"""
    term = SEARCH_ALIAS.get(team_lib, team_lib)
    data = _get(f"{_SUGGEST}?term={requests.utils.quote(term)}&lang=en").json()
    options = []
    for blk in data.get("teamSuggest", []):
        for opt in blk.get("options", []):
            txt = opt.get("text", "")  # "Name|id"
            if "|" in txt:
                nm, tid = txt.rsplit("|", 1)
                if tid.isdigit():
                    options.append((nm.strip(), int(tid)))
    if not options:
        return None
    bad = ("(w)", " u23", " u21", " u20", " u19", "women")
    exact = [(nm, tid) for nm, tid in options
             if nm.lower() == term.lower() and not any(b in nm.lower() for b in bad)]
    clean = [(nm, tid) for nm, tid in options if not any(b in nm.lower() for b in bad)]
    nm, tid = (exact or clean or options)[0]
    return tid, nm


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "team"


def _to_float(v):
    try:
        return round(float(v), 2) if v is not None else None
    except (TypeError, ValueError):
        return None


def _injury_text(inj) -> str | None:
    """把 injury 字段归一为一句中文/英文说明；无伤返回 None。"""
    if not inj:
        return None
    if isinstance(inj, str):
        return inj
    if isinstance(inj, dict):
        for k in ("title", "type", "injuryType", "reason", "name"):
            if inj.get(k):
                txt = str(inj[k])
                ret = inj.get("expectedReturn") or inj.get("returnDate")
                return f"{txt}（预计复出 {ret}）" if ret else txt
        return "伤停/缺阵"
    return "伤停/缺阵"


def _find_squad(obj, depth: int = 0):
    """在 __NEXT_DATA__ 里递归找 squad（list of {title, members}）。"""
    if depth > 7:
        return None
    if isinstance(obj, dict):
        sq = obj.get("squad")
        if isinstance(sq, list) and any(isinstance(x, dict) and "members" in x for x in sq):
            return sq
        for v in obj.values():
            r = _find_squad(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_squad(v, depth + 1)
            if r:
                return r
    return None


def fetch_squad(team_id: int, name_for_slug: str = "team") -> list[dict]:
    """球队页 __NEXT_DATA__ → [{name, number, position, age, club, rating, injury}]。"""
    r = _get(f"https://www.fotmob.com/teams/{team_id}/squad/{_slug(name_for_slug)}")
    m = _NEXT_RE.search(r.text)
    if not m:
        raise FotmobError("未找到 __NEXT_DATA__（FotMob 页面结构可能已变）")
    squad = _find_squad(json.loads(m.group(1)))
    if not squad:
        raise FotmobError("__NEXT_DATA__ 中未找到 squad")
    out = []
    for grp in squad:
        if not isinstance(grp, dict) or grp.get("title") == "coach":
            continue
        pos = _GROUP_POS.get(grp.get("title"), "Other")
        for mb in grp.get("members", []):
            if not mb.get("name"):
                continue
            out.append({
                "player_id": mb.get("id"),
                "name": mb.get("name"),
                "number": mb.get("shirtNumber"),
                "position": pos,
                "age": mb.get("age"),
                "club": mb.get("cname"),
                "club_id": mb.get("ccode"),
                "rating": _to_float(mb.get("rating")),
                "injury": _injury_text(mb.get("injury")),
                "value": mb.get("transferValue"),
            })
    return out


def _find_formation(obj, depth: int = 0):
    """递归找 lastLineupStats.formation（最近一场阵型）。"""
    if depth > 10:
        return None
    if isinstance(obj, dict):
        lls = obj.get("lastLineupStats")
        if isinstance(lls, dict) and isinstance(lls.get("formation"), str):
            return lls["formation"]
        for v in obj.values():
            r = _find_formation(v, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_formation(v, depth + 1)
            if r:
                return r
    return None


def fetch_team_formation(team_id: int, name_for_slug: str = "team") -> str | None:
    """球队 overview 页 → 最近一场阵型（如 '4-2-3-1'）。失败返回 None。"""
    try:
        r = _get(f"https://www.fotmob.com/teams/{team_id}/overview/{_slug(name_for_slug)}")
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', r.text, re.S)
        if not m:
            return None
        return _find_formation(json.loads(m.group(1)))
    except Exception:
        return None


def fetch_team_stats(team_id: int, name_for_slug: str = "team") -> dict:
    """球队 overview 页 → 本届赛事球队聚合统计。

    返回字段为聚合值，不等同于单场技术统计。
    """
    r = _get(f"https://www.fotmob.com/teams/{team_id}/overview/{_slug(name_for_slug)}")
    m = _NEXT_RE.search(r.text)
    if not m:
        raise FotmobError("未找到 __NEXT_DATA__（FotMob 页面结构可能已变）")
    data = json.loads(m.group(1))
    fallback = data.get("props", {}).get("pageProps", {}).get("fallback", {})
    team = fallback.get(f"team-{team_id}", {})
    rows = ((team.get("stats") or {}).get("teams") or [])

    def val(stat_name: str):
        for row in rows:
            if row.get("stat") != stat_name:
                continue
            stat = ((row.get("participant") or {}).get("stat") or {})
            return _to_float(stat.get("value"))
        return None

    possession = val("possession_percentage_team")
    return {
        "possession": possession / 100.0 if possession is not None else None,
        "xg": val("expected_goals_team"),
        "xga": val("expected_goals_conceded_team"),
        "goals_per_match": val("goals_team_match"),
        "goals_conceded_per_match": val("goals_conceded_team_match"),
        "shots_on_target_per_match": val("ontarget_scoring_att_team"),
        "set_piece_goals": val("_set_piece_goals_team"),
        "source_url": r.url,
    }


def player_photo(player_id) -> str | None:
    return f"https://images.fotmob.com/image_resources/playerimages/{player_id}.png" if player_id else None


def club_logo(club_id) -> str | None:
    return f"https://images.fotmob.com/image_resources/logo/teamlogo/{club_id}.png" if club_id else None
