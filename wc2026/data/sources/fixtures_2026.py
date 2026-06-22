"""2026 世界杯赛程：fixturedownload.com 的结构化 JSON（104 场）。

- 队名经 ALIAS 标准化到历史库名，才能匹配模型强度。
- predictable=1 表示两队都是库中真实队（小组赛对阵）；
  占位符(1A/2B/3ABCDF/To be announced 等淘汰赛与待定)为 0，不预测。
- 全量替换：赛程会随出线/附加赛结果更新，每次刷新重建表最简单。
- 比分字段(home_score/away_score)源会在赛后回填，可用于后续回测。
"""
from __future__ import annotations

import requests

from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.data.team_names import to_lib
from wc2026.models.predictor import get_model

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


def fetch_and_store_fixtures() -> dict:
    data = requests.get(FEED, timeout=settings.refresh_http_timeout).json()
    known = set(get_model().teams)
    rows = []
    for m in data:
        h_src, a_src = m["HomeTeam"], m["AwayTeam"]
        home, away = to_lib(h_src), to_lib(a_src)
        predictable = 1 if (home in known and away in known) else 0
        rows.append((
            m["MatchNumber"], m["RoundNumber"], m["DateUtc"],
            h_src, a_src, home, away,
            m.get("Group"), m.get("Location"), predictable,
            m.get("HomeTeamScore"), m.get("AwayTeamScore"),
        ))
    with get_conn() as conn:
        conn.executescript(_REBUILD)
        conn.executemany(
            "INSERT INTO fixtures VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return {"fixtures": len(rows), "predictable": sum(r[9] for r in rows)}
