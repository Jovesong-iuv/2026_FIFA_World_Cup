"""SQLite 连接与 schema。迁移到 Postgres 时主要改这一层。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from wc2026.config import settings

SCHEMA = """
-- 历史国际比赛
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    tournament TEXT,
    city TEXT,
    country TEXT,
    neutral INTEGER NOT NULL DEFAULT 0,
    is_competitive INTEGER NOT NULL DEFAULT 0,
    UNIQUE(date, home_team, away_team)
);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(date);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_team);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_team);

-- 2026 赛程（由 fixtures_2026 全量刷新；此处仅保证空表存在）
CREATE TABLE IF NOT EXISTS fixtures (
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

-- 预测快照（版本化：支持"随新闻/伤停变化"的对比）
CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    model TEXT NOT NULL,
    payload TEXT NOT NULL          -- JSON：概率矩阵 / 各市场 / 理由
);
CREATE INDEX IF NOT EXISTS idx_pred_teams ON predictions(home_team, away_team);

-- FotMob 队名 → 队 ID 映射缓存
CREATE TABLE IF NOT EXISTS fm_teams (
    team_lib TEXT PRIMARY KEY,
    fm_id INTEGER,
    fm_name TEXT,
    updated_at TEXT,
    formation TEXT,
    formation_at TEXT
);

-- FotMob 大名单缓存（评分 + 伤停 + 俱乐部 + 头像/队徽 id + 中文名缓存；纯展示）
CREATE TABLE IF NOT EXISTS fm_squads (
    team_lib TEXT NOT NULL,
    player_name TEXT NOT NULL,
    number INTEGER,
    position TEXT,
    age INTEGER,
    club TEXT,
    rating REAL,
    injured INTEGER DEFAULT 0,
    injury_note TEXT,
    updated_at TEXT,
    player_id INTEGER,
    club_id TEXT,
    name_zh TEXT,
    value REAL,
    PRIMARY KEY (team_lib, player_name)
);

-- 赔率快照（赔率走势）：每次拉取按市场/选项落一行，captured_at 为抓取时间
CREATE TABLE IF NOT EXISTS odds_snapshots (
    captured_at TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    market TEXT NOT NULL,        -- h2h / spreads / totals
    selection TEXT NOT NULL,     -- h2h: home/draw/away；spreads: home/away；totals: over/under
    line TEXT,                   -- 让球/大小球盘口线；h2h 为 NULL
    odds REAL
);
CREATE INDEX IF NOT EXISTS idx_odds_snap ON odds_snapshots(home_team, away_team, market, captured_at);

-- 访问 IP 记录（仅所有者后台可见）：每 IP 一行，note 为所有者备注，再次访问自动保留 note
CREATE TABLE IF NOT EXISTS ip_access (
    ip TEXT PRIMARY KEY,
    note TEXT,
    first_seen TEXT,
    last_seen TEXT,
    visits INTEGER DEFAULT 0,
    user_agent TEXT
);

-- 投注台账（仅所有者）：记录实际下注，结算后算 ROI / 盈亏曲线
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT,
    match TEXT,
    market TEXT,
    selection TEXT,
    odds REAL,
    stake REAL,
    status TEXT DEFAULT 'pending',   -- pending / won / lost / push
    note TEXT,
    close_odds REAL
);

-- 球队实力修正镜像（权威源为 data/team_adjustments.json，此表供查询/展示）
CREATE TABLE IF NOT EXISTS team_adjustments (
    team TEXT PRIMARY KEY,
    elo REAL DEFAULT 0,
    attack REAL DEFAULT 0,
    defense REAL DEFAULT 0,
    sources_json TEXT,
    updated_at TEXT
);
"""


def _ensure_columns(conn) -> None:
    """对已存在的表补齐后加的列（ALTER ADD，幂等），避免旧库缺列。"""
    have = {r[1] for r in conn.execute("PRAGMA table_info(fm_squads)")}
    for col, decl in (("player_id", "INTEGER"), ("club_id", "TEXT"), ("name_zh", "TEXT"),
                      ("value", "REAL")):
        if col not in have:
            conn.execute(f"ALTER TABLE fm_squads ADD COLUMN {col} {decl}")
    have_t = {r[1] for r in conn.execute("PRAGMA table_info(fm_teams)")}
    for col, decl in (("formation", "TEXT"), ("formation_at", "TEXT")):
        if col not in have_t:
            conn.execute(f"ALTER TABLE fm_teams ADD COLUMN {col} {decl}")
    have_b = {r[1] for r in conn.execute("PRAGMA table_info(bets)")}
    if "close_odds" not in have_b:
        conn.execute("ALTER TABLE bets ADD COLUMN close_odds REAL")


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _ensure_columns(conn)
