"""ESPN public scoreboards for supported club competitions."""
from __future__ import annotations

from datetime import date, timedelta

import requests

from wc2026.config import settings


SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard"
COMPETITIONS = {
    "brasileirao": {
        "name": "巴甲",
        "leagues": ("bra.1",),
    },
    "champions_league": {
        "name": "欧冠",
        "leagues": ("uefa.champions", "uefa.champions_qual"),
    },
}


def _team(competitor: dict) -> dict:
    team = competitor.get("team") or {}
    record = next(
        (row.get("summary") for row in competitor.get("records") or []
         if row.get("type") == "total"),
        None,
    )
    return {
        "id": str(team.get("id") or competitor.get("id") or ""),
        "name": team.get("displayName") or team.get("shortDisplayName") or "待定",
        "short_name": team.get("shortDisplayName") or team.get("displayName") or "待定",
        "abbreviation": team.get("abbreviation") or "",
        "logo": team.get("logo") or "",
        "score": competitor.get("score"),
        "winner": bool(competitor.get("winner")),
        "record": record,
    }


def parse_scoreboard_event(event: dict, league_name: str = "") -> dict | None:
    competitions = event.get("competitions") or []
    if not competitions:
        return None
    competition = competitions[0]
    by_side = {
        row.get("homeAway"): row
        for row in competition.get("competitors") or []
    }
    if "home" not in by_side or "away" not in by_side:
        return None

    status_type = ((competition.get("status") or event.get("status") or {}).get("type") or {})
    state = status_type.get("state") or "pre"
    completed = bool(status_type.get("completed"))
    if completed:
        state = "post"
    elif state == "post":
        state = "other"
    venue = competition.get("venue") or {}
    address = venue.get("address") or {}
    season = event.get("season") or {}
    return {
        "id": str(event.get("id") or ""),
        "date_utc": event.get("date"),
        "home": _team(by_side["home"]),
        "away": _team(by_side["away"]),
        "state": state,
        "completed": completed,
        "status": status_type.get("shortDetail") or status_type.get("detail") or "",
        "stage": season.get("slug", "").replace("-", " ").title(),
        "venue": venue.get("fullName") or "",
        "city": address.get("city") or "",
        "league": league_name,
    }


def fetch_competition_events(
    competition: str,
    *,
    reference_date: date | None = None,
    days_before: int = 10,
    days_after: int = 14,
    timeout: float | None = None,
) -> dict:
    spec = COMPETITIONS.get(competition)
    if spec is None:
        raise ValueError(f"unsupported club competition: {competition}")

    center = reference_date or date.today()
    dates = (
        f"{center - timedelta(days=days_before):%Y%m%d}-"
        f"{center + timedelta(days=days_after):%Y%m%d}"
    )
    events_by_id: dict[str, dict] = {}
    seasons: list[str] = []
    errors: list[str] = []

    for league in spec["leagues"]:
        try:
            response = requests.get(
                SCOREBOARD_URL.format(league=league),
                params={"dates": dates, "limit": 200},
                timeout=timeout or settings.refresh_http_timeout,
            )
            response.raise_for_status()
            payload = response.json()
            league_info = (payload.get("leagues") or [{}])[0]
            raw_events = payload.get("events") or []
            season_name = (league_info.get("season") or {}).get("displayName")
            if raw_events and season_name and season_name not in seasons:
                seasons.append(season_name)
            league_name = league_info.get("name") or league
            for raw in raw_events:
                parsed = parse_scoreboard_event(raw, league_name)
                if parsed and parsed["id"]:
                    events_by_id[parsed["id"]] = parsed
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{league}: {exc}")

    events = sorted(
        events_by_id.values(),
        key=lambda row: (row.get("date_utc") or "", row["id"]),
    )
    if errors and not events:
        raise RuntimeError("；".join(errors))
    return {
        "competition": competition,
        "name": spec["name"],
        "seasons": seasons,
        "events": events,
        "errors": errors,
        "date_range": dates,
    }
