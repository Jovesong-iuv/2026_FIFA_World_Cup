"""The Odds API 接入（需 ODDS_API_KEY，免费 tier 约 500 次/月）。

拉世界杯 1X2(h2h) 赔率，取各家最优(最高)赔率；队名经 ALIAS 标准化到库名。
每次请求后记录剩余配额，供前端显示。
"""
from __future__ import annotations

import requests
from datetime import datetime, timezone

from wc2026.config import settings
from wc2026.data.team_names import to_lib

HOST = "https://api.the-odds-api.com/v4"
WC_SPORT = "soccer_fifa_world_cup"
DEFAULT_MARKETS = (
    "h2h,spreads,totals,btts,draw_no_bet,double_chance,"
    "h2h_3_way_h1,spreads_h1,totals_h1"
)

_LAST_META: dict = {}


class OddsError(Exception):
    pass


def _key() -> str:
    if not settings.odds_api_key:
        raise OddsError("未配置 ODDS_API_KEY（注册 the-odds-api.com 获取，填入 .env）")
    return settings.odds_api_key


def _record(resp) -> None:
    _LAST_META["remaining"] = resp.headers.get("x-requests-remaining")
    _LAST_META["used"] = resp.headers.get("x-requests-used")
    _LAST_META["last"] = resp.headers.get("x-requests-last")
    _LAST_META["updated_at"] = datetime.now(timezone.utc).isoformat()


def last_quota() -> dict:
    return dict(_LAST_META)


def get_quota() -> dict:
    """查询剩余请求次数（/sports 不消耗配额）。"""
    r = requests.get(f"{HOST}/sports", params={"apiKey": _key()}, timeout=15)
    if r.status_code != 200:
        raise OddsError(f"HTTP {r.status_code}: {r.text[:200]}")
    _record(r)
    return last_quota()


def list_sports() -> list:
    r = requests.get(f"{HOST}/sports", params={"apiKey": _key()}, timeout=20)
    if r.status_code != 200:
        raise OddsError(f"HTTP {r.status_code}: {r.text[:200]}")
    _record(r)
    return r.json()


def parse_event_markets(ev: dict) -> dict:
    """解析单场多市场赔率，取各 bookmaker 的最高价。"""
    home_src, away_src = ev["home_team"], ev["away_team"]
    out: dict = {}
    for bm in ev.get("bookmakers", []):
        for mk in bm.get("markets", []):
            key = mk.get("key")
            if not key:
                continue
            if key in {"h2h", "h2h_3_way_h1"}:
                dest = out.setdefault(key, {"home": 0.0, "draw": 0.0, "away": 0.0})
                for oc in mk.get("outcomes", []):
                    name, price = oc.get("name", ""), float(oc.get("price") or 0.0)
                    if name == home_src:
                        dest["home"] = max(dest["home"], price)
                    elif name == away_src:
                        dest["away"] = max(dest["away"], price)
                    elif name.lower() == "draw":
                        dest["draw"] = max(dest["draw"], price)
            elif key in {"spreads", "spreads_h1"}:
                dest = out.setdefault(key, {})
                for oc in mk.get("outcomes", []):
                    point = oc.get("point")
                    if point is None:
                        continue
                    raw_point = float(point)
                    name, price = oc.get("name", ""), float(oc.get("price") or 0.0)
                    if name == home_src:
                        line = _fmt_point(raw_point)
                        row = dest.setdefault(line, {"home": 0.0, "away": 0.0})
                        row["home"] = max(row["home"], price)
                    elif name == away_src:
                        line = _fmt_point(-raw_point)
                        row = dest.setdefault(line, {"home": 0.0, "away": 0.0})
                        row["away"] = max(row["away"], price)
            elif key in {"totals", "totals_h1"}:
                dest = out.setdefault(key, {})
                for oc in mk.get("outcomes", []):
                    point = oc.get("point")
                    if point is None:
                        continue
                    line = _fmt_point(point)
                    row = dest.setdefault(line, {"over": 0.0, "under": 0.0})
                    name, price = oc.get("name", "").lower(), float(oc.get("price") or 0.0)
                    if name == "over":
                        row["over"] = max(row["over"], price)
                    elif name == "under":
                        row["under"] = max(row["under"], price)
            elif key in {"btts", "draw_no_bet", "double_chance"}:
                dest = out.setdefault(key, {})
                for oc in mk.get("outcomes", []):
                    name = oc.get("name", "")
                    price = float(oc.get("price") or 0.0)
                    dest[name] = max(dest.get(name, 0.0), price)
    return out


def fetch_event_odds(sport_key: str = WC_SPORT, regions: str = "us,uk,eu",
                     markets: str = DEFAULT_MARKETS) -> dict:
    """返回 {(home_lib, away_lib): 多市场赔率}，用于页面预填。"""
    r = requests.get(
        f"{HOST}/sports/{sport_key}/odds",
        params={"apiKey": _key(), "regions": regions, "markets": markets, "oddsFormat": "decimal"},
        timeout=25,
    )
    if r.status_code != 200:
        raise OddsError(f"HTTP {r.status_code}: {r.text[:200]}")
    _record(r)
    return {
        (to_lib(ev["home_team"]), to_lib(ev["away_team"])): parse_event_markets(ev)
        for ev in r.json()
    }


def _fmt_point(point) -> str:
    v = float(point)
    return str(int(v)) if v.is_integer() else str(v)


def fetch_h2h_odds(sport_key: str = WC_SPORT, regions: str = "us,uk,eu") -> dict:
    """返回 {(home_lib, away_lib): {"home":赔率,"draw":赔率,"away":赔率}}，取各家最优。"""
    r = requests.get(
        f"{HOST}/sports/{sport_key}/odds",
        params={"apiKey": _key(), "regions": regions, "markets": "h2h", "oddsFormat": "decimal"},
        timeout=25,
    )
    if r.status_code != 200:
        raise OddsError(f"HTTP {r.status_code}: {r.text[:200]}")
    _record(r)
    out = {}
    for ev in r.json():
        home_src, away_src = ev["home_team"], ev["away_team"]
        best = {"home": 0.0, "draw": 0.0, "away": 0.0}
        for bm in ev.get("bookmakers", []):
            for mk in bm.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                for oc in mk.get("outcomes", []):
                    name, price = oc.get("name", ""), oc.get("price", 0.0)
                    if name == home_src:
                        best["home"] = max(best["home"], price)
                    elif name == away_src:
                        best["away"] = max(best["away"], price)
                    elif name.lower() == "draw":
                        best["draw"] = max(best["draw"], price)
        out[(to_lib(home_src), to_lib(away_src))] = best
    return out
