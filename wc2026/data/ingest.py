"""抓取 → 入库。INSERT OR IGNORE 去重，支持反复运行做增量更新。"""
from __future__ import annotations

from wc2026.data.db import get_conn, init_db
from wc2026.data.sources.international_results import fetch_results


def ingest_international_results() -> dict:
    init_db()
    df = fetch_results()
    rows = list(df.itertuples(index=False, name=None))
    with get_conn() as conn:
        before = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
        conn.executemany(
            """INSERT OR IGNORE INTO matches
               (date, home_team, away_team, home_score, away_score,
                tournament, city, country, neutral, is_competitive)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        after = conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    return {"total": after, "new": after - before}
