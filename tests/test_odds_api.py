import unittest

from wc2026.data.sources import odds_api


class OddsApiParseTest(unittest.TestCase):
    def test_parse_event_markets_extracts_best_prices(self):
        event = {
            "home_team": "Mexico",
            "away_team": "South Africa",
            "bookmakers": [
                {"markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Mexico", "price": 1.8},
                        {"name": "Draw", "price": 3.3},
                        {"name": "South Africa", "price": 4.6},
                    ]},
                    {"key": "totals", "outcomes": [
                        {"name": "Over", "price": 1.9, "point": 2.5},
                        {"name": "Under", "price": 1.95, "point": 2.5},
                    ]},
                ]},
                {"markets": [
                    {"key": "h2h", "outcomes": [
                        {"name": "Mexico", "price": 1.85},
                        {"name": "Draw", "price": 3.2},
                        {"name": "South Africa", "price": 4.7},
                    ]},
                ]},
            ],
        }

        parsed = odds_api.parse_event_markets(event)

        self.assertEqual(parsed["h2h"]["home"], 1.85)
        self.assertEqual(parsed["h2h"]["draw"], 3.3)
        self.assertEqual(parsed["h2h"]["away"], 4.7)
        self.assertEqual(parsed["totals"]["2.5"]["over"], 1.9)
        self.assertEqual(parsed["totals"]["2.5"]["under"], 1.95)


if __name__ == "__main__":
    unittest.main()
