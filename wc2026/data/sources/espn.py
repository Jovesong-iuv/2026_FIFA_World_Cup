"""Structured ESPN World Cup results and postmatch statistics."""
from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

import requests

from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.data.team_names import to_lib


_STATUS = {
    "STATUS_FULL_TIME": "FT",
    "STATUS_FINAL_AET": "AET",
    "STATUS_FINAL_PEN": "PEN",
}
SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary"


def _number(value, *, integer: bool = False):
    try:
        number = float(str(value).replace("%", ""))
        return int(number) if integer else number
    except (TypeError, ValueError):
        return None


def _competitors(competition: dict) -> tuple[dict, dict]:
    by_side = {r.get("homeAway"): r for r in competition.get("competitors", [])}
    return by_side.get("home", {}), by_side.get("away", {})


def _utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def match_scoreboard_event(events: list[dict], fixture: dict, max_hours: float = 3.0) -> dict | None:
    """Return the unique event matching normalized teams and kickoff time."""
    kickoff = _utc(fixture.get("date_utc"))
    matches = []
    for event in events or []:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        home, away = _competitors(competitions[0])
        event_home = to_lib((home.get("team") or {}).get("displayName") or "")
        event_away = to_lib((away.get("team") or {}).get("displayName") or "")
        if (event_home, event_away) != (fixture.get("home_team"), fixture.get("away_team")):
            continue
        event_time = _utc(event.get("date"))
        if kickoff is None or event_time is None:
            continue
        if abs((event_time - kickoff).total_seconds()) <= max_hours * 3600:
            matches.append(event)
    return matches[0] if len(matches) == 1 else None


def scoreboard_dates(date_utc: str) -> list[str]:
    date = _utc(date_utc)
    if date is None:
        return []
    return [(date + timedelta(days=offset)).strftime("%Y%m%d") for offset in (-1, 0, 1)]


def _period_scores(competitor: dict) -> list[int]:
    out = []
    for row in competitor.get("linescores") or []:
        value = _number(row.get("displayValue"), integer=True)
        if value is not None:
            out.append(value)
    return out


def _shootout_scores(rows: list[dict], home_name: str, away_name: str) -> tuple[int | None, int | None]:
    scores = {}
    for row in rows or []:
        team = to_lib(row.get("team") or row.get("teamName") or "")
        scores[team] = sum(bool(shot.get("didScore")) for shot in row.get("shots", []))
    return scores.get(home_name), scores.get(away_name)


def _match_stats(rows: list[dict]) -> dict:
    names = {
        "possessionPct": ("possession", lambda v: round(v / 100.0, 4)),
        "totalShots": ("shots", int),
        "shotsOnTarget": ("shots_on_target", int),
        "redCards": ("red_cards", int),
    }
    out = {}
    for row in rows or []:
        team = to_lib((row.get("team") or {}).get("displayName") or "")
        values = {}
        for stat in row.get("statistics", []):
            spec = names.get(stat.get("name"))
            value = _number(stat.get("displayValue"))
            if spec and value is not None:
                key, convert = spec
                values[key] = convert(value)
        if team and values:
            out[team] = values
    return out


def parse_summary(payload: dict) -> dict:
    """Parse one ESPN summary while keeping regulation, extra time and shootout separate."""
    competitions = (payload.get("header") or {}).get("competitions") or []
    if not competitions:
        raise ValueError("ESPN summary missing competition")
    competition = competitions[0]
    home, away = _competitors(competition)
    home_name = to_lib((home.get("team") or {}).get("displayName") or "")
    away_name = to_lib((away.get("team") or {}).get("displayName") or "")
    home_periods, away_periods = _period_scores(home), _period_scores(away)
    status_name = ((competition.get("status") or {}).get("type") or {}).get("name")
    status = _STATUS.get(status_name, "")
    home_final = _number(home.get("score"), integer=True)
    away_final = _number(away.get("score"), integer=True)
    final_is_regulation = status == "FT"
    home_reg = (sum(home_periods[:2]) if len(home_periods) >= 2
                else (home_final if final_is_regulation else None))
    away_reg = (sum(away_periods[:2]) if len(away_periods) >= 2
                else (away_final if final_is_regulation else None))
    penalty_home, penalty_away = _shootout_scores(payload.get("shootout") or [], home_name, away_name)

    flags = []
    if status in {"AET", "PEN"}:
        flags.append("extra_time")
    if status == "PEN":
        flags.append("penalty_shootout")
    for event in competition.get("details") or []:
        if event.get("redCard") and "red_card" not in flags:
            flags.append("red_card")
        if event.get("ownGoal") and "own_goal" not in flags:
            flags.append("own_goal")

    winner = next((to_lib((r.get("team") or {}).get("displayName") or "")
                   for r in competition.get("competitors", []) if r.get("winner")), None)
    if winner is None:
        if status == "PEN" and penalty_home is not None and penalty_away is not None:
            winner = home_name if penalty_home > penalty_away else away_name
        elif home_final is not None and away_final is not None and home_final != away_final:
            winner = home_name if home_final > away_final else away_name

    return {
        "home_team": home_name,
        "away_team": away_name,
        "regulation_home_score": home_reg,
        "regulation_away_score": away_reg,
        "final_home_score": home_final,
        "final_away_score": away_final,
        "penalty_home_score": penalty_home,
        "penalty_away_score": penalty_away,
        "result_status": status,
        "winner_team": winner,
        "event_flags": flags,
        "match_stats": _match_stats((payload.get("boxscore") or {}).get("teams") or []),
    }


def fetch_scoreboard(date_utc: str, timeout: float | None = None) -> list[dict]:
    query_date = date_utc if len(date_utc) == 8 and date_utc.isdigit() else date_utc[:10].replace("-", "")
    response = requests.get(SCOREBOARD_URL, params={"dates": query_date},
                            timeout=timeout or settings.refresh_http_timeout)
    response.raise_for_status()
    return response.json().get("events") or []


def fetch_summary(event_id: str, timeout: float | None = None) -> dict:
    response = requests.get(SUMMARY_URL, params={"event": event_id},
                            timeout=timeout or settings.refresh_http_timeout)
    response.raise_for_status()
    return response.json()


def refresh_fixture_results(*, conn=None, limit: int = 32,
                            timeout: float | None = None) -> dict:
    """Enrich recently concluded fixtures; failures never erase existing results."""
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as db:
        rows = db.execute(
            "SELECT * FROM fixtures WHERE predictable=1 "
            "AND datetime(date_utc) <= datetime('now','-2 hours') "
            "AND (COALESCE(result_source,'') != 'ESPN' OR "
            "(result_status IN ('AET','PEN') AND "
            "(regulation_home_score IS NULL OR regulation_away_score IS NULL))) "
            "ORDER BY date_utc DESC LIMIT ?", (limit,)).fetchall()
        fixtures = [dict(row) for row in rows]
        scoreboards, updated, checked, errors = {}, 0, 0, []
        for fixture in fixtures:
            checked += 1
            try:
                events = {}
                for query_date in scoreboard_dates(fixture.get("date_utc") or ""):
                    if query_date not in scoreboards:
                        scoreboards[query_date] = fetch_scoreboard(query_date, timeout=timeout)
                    for candidate in scoreboards[query_date]:
                        events[str(candidate.get("id"))] = candidate
                event = match_scoreboard_event(list(events.values()), fixture)
                if event is None:
                    continue
                parsed = parse_summary(fetch_summary(str(event["id"]), timeout=timeout))
                if not parsed.get("result_status"):
                    continue
                parsed["source_event_id"] = str(event["id"])
                parsed["result_source"] = "ESPN"
                parsed["result_fetched_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                db.execute(
                    "UPDATE fixtures SET home_score=?, away_score=?, regulation_home_score=?, "
                    "regulation_away_score=?, final_home_score=?, final_away_score=?, "
                    "penalty_home_score=?, penalty_away_score=?, result_status=?, winner_team=?, "
                    "result_source=?, source_event_id=?, result_fetched_at=?, event_flags=?, "
                    "match_stats_json=? WHERE match_number=?",
                    (parsed["final_home_score"], parsed["final_away_score"],
                     parsed["regulation_home_score"], parsed["regulation_away_score"],
                     parsed["final_home_score"], parsed["final_away_score"],
                     parsed["penalty_home_score"], parsed["penalty_away_score"],
                     parsed["result_status"], parsed["winner_team"], parsed["result_source"],
                     parsed["source_event_id"], parsed["result_fetched_at"],
                     json.dumps(parsed["event_flags"], ensure_ascii=False),
                     json.dumps(parsed["match_stats"], ensure_ascii=False), fixture["match_number"]),
                )
                updated += 1
            except Exception as exc:
                errors.append({"match_number": fixture.get("match_number"), "error": str(exc)})
        return {"checked": checked, "updated": updated, "errors": errors[:5],
                "source": "ESPN scoreboard/summary"}
