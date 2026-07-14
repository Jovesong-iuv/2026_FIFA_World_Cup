"""2026 世界杯赛程：fixturedownload.com 的结构化 JSON（104 场）。

- 队名经 ALIAS 标准化到历史库名，才能匹配模型强度。
- predictable=1 表示两队都是库中真实队（小组赛对阵）；
  占位符(1A/2B/3ABCDF/To be announced 等淘汰赛与待定)为 0，不预测。
- 全量替换：赛程会随出线/附加赛结果更新，每次刷新重建表最简单。
- 比分字段(home_score/away_score)源会在赛后回填，可用于后续回测。
"""
from __future__ import annotations

from datetime import datetime, timezone
from time import sleep

import requests

from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.data.team_names import to_lib

FEED = "https://fixturedownload.com/feed/json/fifa-world-cup-2026"

_REBUILD = """
DROP TABLE IF EXISTS fixtures;
CREATE TABLE fixtures (
    match_number INTEGER PRIMARY KEY,
    round_number INTEGER,
    date_utc TEXT,
    home_src TEXT,
    away_src TEXT,
    home_team TEXT,
    away_team TEXT,
    group_name TEXT,
    location TEXT,
    predictable INTEGER DEFAULT 0,
    home_score INTEGER,
    away_score INTEGER
);
"""


def _normalize_fixture_feed(data: list[dict], known: set[str]) -> list[dict]:
    fetched_at = datetime.now(timezone.utc).isoformat()
    fixtures = []
    for m in data:
        h_src, a_src = m["HomeTeam"], m["AwayTeam"]
        home, away = to_lib(h_src), to_lib(a_src)
        predictable = 1 if (home in known and away in known) else 0
        fixtures.append({
            "match_number": m["MatchNumber"],
            "round_number": m["RoundNumber"],
            "date_utc": m["DateUtc"],
            "home_src": h_src,
            "away_src": a_src,
            "home_team": home,
            "away_team": away,
            "group_name": m.get("Group"),
            "location": m.get("Location"),
            "predictable": predictable,
            "home_score": m.get("HomeTeamScore"),
            "away_score": m.get("AwayTeamScore"),
            "data_source": "live_fixture_feed",
            "fetched_at": fetched_at,
        })
    return fixtures


def fetch_fixture_snapshot(timeout: float | None = None) -> list[dict]:
    """Fetch the current fixture feed without changing the local database."""
    from wc2026.models.predictor import get_model

    for attempt in range(3):
        try:
            resp = requests.get(FEED, timeout=timeout or settings.refresh_http_timeout)
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt == 2:
                raise
            sleep(0.2 * (attempt + 1))
    return _normalize_fixture_feed(resp.json(), set(get_model().teams))


def merge_fixture_snapshots(cached: list[dict], live: list[dict]) -> list[dict]:
    """Overlay live fields while retaining cached values omitted by the feed."""
    merged = {int(f["match_number"]): dict(f) for f in cached}
    for fresh in live:
        match_number = int(fresh["match_number"])
        row = merged.setdefault(match_number, {})
        for key, value in fresh.items():
            if value is not None and value != "":
                row[key] = value
        row["match_number"] = match_number
    return [merged[key] for key in sorted(merged)]


def fetch_and_store_fixtures() -> dict:
    fixtures = fetch_fixture_snapshot()
    rows = [(
        f["match_number"], f["round_number"], f["date_utc"],
        f["home_src"], f["away_src"], f["home_team"], f["away_team"],
        f.get("group_name"), f.get("location"), f["predictable"],
        f.get("home_score"), f.get("away_score"),
    ) for f in fixtures]
    with get_conn() as conn:
        conn.executescript(_REBUILD)
        conn.executemany(
            "INSERT INTO fixtures VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return {"fixtures": len(rows), "predictable": sum(r[9] for r in rows)}
