import unittest
from unittest.mock import patch

from wc2026.api import app as api


class TournamentFactsApiTest(unittest.TestCase):
    def test_tournament_facts_endpoint_returns_full_or_match_payload(self):
        with patch("wc2026.api.app.tournament_facts.load_facts", return_value={"matches": [{"match_number": 82}]}), \
                patch("wc2026.api.app.tournament_facts.match_facts", return_value={"match_number": 82}):
            self.assertEqual(api.tournament_facts_ep()["matches"], [{"match_number": 82}])
            self.assertEqual(api.tournament_facts_ep(match_number=82), {"match_number": 82})


if __name__ == "__main__":
    unittest.main()
