"""Open-Meteo hourly weather with a small JSON cache for match pages."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from wc2026.config import settings


API_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_PATH = settings.data_dir / "weather_cache.json"
CACHE_TTL_HOURS = 6
_FIELDS = {
    "temperature_2m": "temperature_c",
    "relative_humidity_2m": "humidity_pct",
    "precipitation_probability": "precipitation_probability_pct",
    "wind_speed_10m": "wind_kmh",
}


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


def parse_hourly(payload: dict, kickoff_utc: str) -> dict | None:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    kickoff = _utc(kickoff_utc)
    parsed_times = [_utc(value) for value in times]
    candidates = [(i, value) for i, value in enumerate(parsed_times) if value is not None]
    if kickoff is None or not candidates:
        return None
    index, forecast_time = min(candidates, key=lambda item: abs((item[1] - kickoff).total_seconds()))
    if abs((forecast_time - kickoff).total_seconds()) > 3 * 3600:
        return None
    result = {"forecast_time_utc": times[index]}
    for source, target in _FIELDS.items():
        values = hourly.get(source) or []
        if index >= len(values) or values[index] is None:
            return None
        result[target] = values[index]
    return result


def _key(venue: str, kickoff_utc: str) -> str:
    return f"{venue}::{kickoff_utc}"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("weather", {})
    except Exception:
        return {}


def fetch_weather(venue: str, lat: float, lon: float, kickoff_utc: str, *,
                  timeout: float | None = None, path: Path | None = None) -> dict | None:
    cache_path = Path(path) if path else CACHE_PATH
    date = kickoff_utc[:10]
    response = requests.get(
        API_URL,
        params={
            "latitude": lat, "longitude": lon,
            "hourly": ",".join(_FIELDS), "timezone": "UTC",
            "start_date": date, "end_date": date,
        },
        timeout=timeout or settings.refresh_http_timeout,
    )
    response.raise_for_status()
    result = parse_hourly(response.json(), kickoff_utc)
    if result is None:
        return None
    result.update({"source": "Open-Meteo",
                   "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    data = _load(cache_path)
    data[_key(venue, kickoff_utc)] = result
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"weather": data}, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def load_cached_weather(venue: str, kickoff_utc: str, *, path: Path | None = None) -> dict | None:
    cache_path = Path(path) if path else CACHE_PATH
    return _load(cache_path).get(_key(venue, kickoff_utc))


def _cache_is_fresh(entry: dict | None, now: datetime, ttl_hours: int) -> bool:
    fetched_at = _utc((entry or {}).get("fetched_at"))
    return bool(fetched_at and ttl_hours > 0 and fetched_at >= now - timedelta(hours=ttl_hours))


def refresh_upcoming_weather(fixtures: list[dict], *, now: str | None = None,
                             horizon_days: int = 16, timeout: float | None = None,
                             path: Path | None = None,
                             cache_ttl_hours: int = CACHE_TTL_HOURS) -> dict:
    from wc2026.analysis.fatigue import VENUES

    now_dt = _utc(now) if now else datetime.now(timezone.utc)
    end = now_dt + timedelta(days=horizon_days)
    updated, cached, errors, seen = 0, 0, [], set()
    for fixture in fixtures:
        venue, kickoff_text = fixture.get("location"), fixture.get("date_utc")
        kickoff, geo = _utc(kickoff_text), VENUES.get(venue)
        key = (venue, kickoff_text)
        if not venue or not geo or kickoff is None or not (now_dt <= kickoff <= end) or key in seen:
            continue
        seen.add(key)
        if _cache_is_fresh(load_cached_weather(venue, kickoff_text, path=path),
                           now_dt, cache_ttl_hours):
            cached += 1
            continue
        try:
            if fetch_weather(venue, geo["lat"], geo["lon"], kickoff_text,
                             timeout=timeout, path=path):
                updated += 1
        except Exception as exc:
            errors.append({"venue": venue, "kickoff_utc": kickoff_text, "error": str(exc)})
    return {"checked": len(seen), "updated": updated, "cached": cached,
            "errors": errors[:5], "source": "Open-Meteo"}
