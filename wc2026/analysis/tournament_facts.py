"""Validated tournament facts extracted from committed results and dashboard snapshots.

This layer is intentionally descriptive: it exposes score, player and process
facts for reports, dashboards and prediction explanations without mutating the
core model probabilities.
"""
from __future__ import annotations

import json
from pathlib import Path

from wc2026.config import settings
from wc2026.data.team_names import zh

FACTS_PATH = settings.data_dir / "tournament_facts.json"


def empty_facts() -> dict:
    return {
        "metadata": {},
        "reconciliation": {},
        "matches": [],
        "team_records": {},
        "team_process": {},
        "player_events": [],
    }


def load_facts(path: Path | None = None) -> dict:
    src = Path(path) if path else FACTS_PATH
    if not src.exists():
        return empty_facts()
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        return empty_facts()
    out = empty_facts()
    out.update({k: data.get(k, out[k]) for k in out})
    return out


def player_leaderboard(data: dict | None = None, *, limit: int | None = None) -> list[dict]:
    data = load_facts() if data is None else data
    rows: dict[tuple[str, str], dict] = {}
    for ev in data.get("player_events", []):
        if ev.get("event") != "goal":
            continue
        key = (ev.get("team") or "", ev.get("player") or "")
        row = rows.setdefault(key, {
            "team": key[0],
            "team_cn": zh(key[0]),
            "player": key[1],
            "goals": 0,
            "penalty_goals": 0,
            "free_kick_goals": 0,
            "minutes": [],
        })
        row["goals"] += 1
        detail = str(ev.get("detail") or "").lower()
        if "pen" in detail:
            row["penalty_goals"] += 1
        if "fk" in detail or "free" in detail:
            row["free_kick_goals"] += 1
        if ev.get("minute") is not None:
            row["minutes"].append(ev["minute"])
    board = sorted(rows.values(), key=lambda r: (-r["goals"], r["team"], r["player"]))
    return board[:limit] if limit else board


def _team_scorers(team: str, data: dict) -> list[dict]:
    return [r for r in player_leaderboard(data) if r["team"] == team]


def _team_mom(team: str, data: dict) -> list[dict]:
    out = []
    for ev in data.get("player_events", []):
        if ev.get("event") == "mom" and ev.get("team") == team:
            out.append({"player": ev.get("player"), "match_number": ev.get("match_number")})
    return out


def _process_summary(raw: dict | None) -> dict:
    raw = raw or {}
    matches = int(raw.get("matches") or 0)
    if matches <= 0:
        return {"matches": 0}
    return {
        **raw,
        "avg_shots_for": round(float(raw.get("shots_for", 0)) / matches, 2),
        "avg_shots_against": round(float(raw.get("shots_against", 0)) / matches, 2),
        "avg_possession": round(float(raw.get("possession_for", 0)) / matches, 2),
    }


def team_summary(team: str, data: dict | None = None) -> dict:
    data = load_facts() if data is None else data
    return {
        "team": team,
        "team_cn": zh(team),
        "record": data.get("team_records", {}).get(team, {}),
        "process": _process_summary(data.get("team_process", {}).get(team)),
        "top_scorers": _team_scorers(team, data),
        "mom": _team_mom(team, data),
    }


def match_facts(match_number: int, data: dict | None = None) -> dict | None:
    data = load_facts() if data is None else data
    return next((m for m in data.get("matches", []) if m.get("match_number") == match_number), None)


def compare_teams(home: str, away: str, data: dict | None = None) -> dict:
    data = load_facts() if data is None else data
    return {
        "home": team_summary(home, data),
        "away": team_summary(away, data),
        "leaderboard": player_leaderboard(data, limit=10),
    }
