import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

from wc2026.data.sources import weather


PAYLOAD = {
    "hourly": {
        "time": ["2026-07-14T18:00", "2026-07-14T19:00", "2026-07-14T20:00"],
        "temperature_2m": [29.0, 28.0, 27.0],
        "relative_humidity_2m": [58, 61, 64],
        "precipitation_probability": [10, 20, 35],
        "wind_speed_10m": [8.0, 11.0, 14.0],
    }
}


class WeatherSourceTest(unittest.TestCase):
    def test_selects_hour_nearest_to_kickoff(self):
        result = weather.parse_hourly(PAYLOAD, "2026-07-14T19:20:00Z")

        self.assertEqual(result["forecast_time_utc"], "2026-07-14T19:00")
        self.assertEqual(result["temperature_c"], 28.0)
        self.assertEqual(result["humidity_pct"], 61)
        self.assertEqual(result["precipitation_probability_pct"], 20)
        self.assertEqual(result["wind_kmh"], 11.0)

    def test_fetch_writes_cache_and_loads_it_without_network(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = PAYLOAD
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weather.json"
            with patch("wc2026.data.sources.weather.requests.get", return_value=response):
                fetched = weather.fetch_weather(
                    "Miami Stadium", 25.958, -80.239, "2026-07-14T19:20:00Z", path=path)
            cached = weather.load_cached_weather(
                "Miami Stadium", "2026-07-14T19:20:00Z", path=path)

        self.assertEqual(cached, fetched)
        self.assertEqual(cached["source"], "Open-Meteo")
        self.assertIn("fetched_at", cached)

    def test_malformed_hourly_payload_degrades_to_none(self):
        self.assertIsNone(weather.parse_hourly({"hourly": {}}, "2026-07-14T19:20:00Z"))

    def test_refreshes_only_upcoming_fixtures_with_known_venue(self):
        fixtures = [
            {"location": "Miami Stadium", "date_utc": "2026-07-15T19:00:00Z"},
            {"location": "Unknown", "date_utc": "2026-07-15T20:00:00Z"},
            {"location": "Miami Stadium", "date_utc": "2026-07-01T19:00:00Z"},
        ]
        with tempfile.TemporaryDirectory() as tmp, \
                patch("wc2026.data.sources.weather.fetch_weather",
                      return_value={"source": "Open-Meteo"}) as fetch:
            result = weather.refresh_upcoming_weather(
                fixtures, now="2026-07-14T00:00:00Z", path=Path(tmp) / "weather.json")

        self.assertEqual(result["updated"], 1)
        fetch.assert_called_once()

    def test_refresh_uses_recent_cached_forecast_without_network(self):
        fixture = {"location": "Miami Stadium", "date_utc": "2026-07-15T19:00:00Z"}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "weather.json"
            key = "Miami Stadium::2026-07-15T19:00:00Z"
            path.write_text(json.dumps({"weather": {key: {
                "source": "Open-Meteo", "fetched_at": "2026-07-14T01:00:00+00:00",
            }}}), encoding="utf-8")
            with patch("wc2026.data.sources.weather.fetch_weather") as fetch:
                result = weather.refresh_upcoming_weather(
                    [fixture], now="2026-07-14T03:00:00Z", path=path, cache_ttl_hours=6)

        self.assertEqual(result["cached"], 1)
        self.assertEqual(result["updated"], 0)
        fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
