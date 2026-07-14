import unittest
from unittest.mock import patch

from wc2026.data.sources import news


def _item(source: str, title: str, link: str) -> dict:
    return {
        "source": source,
        "title": title,
        "link": link,
        "pub": "Tue, 14 Jul 2026 08:00:00 GMT",
        "summary": "",
    }


class NewsSourceAggregationTest(unittest.TestCase):
    @patch("wc2026.data.sources.news.web_search_for_team", return_value=[])
    @patch("wc2026.data.sources.news.fetch_all", return_value=[
        _item("BBC", "France prepare for Spain", "https://bbc.test/france-spain")
    ])
    @patch("wc2026.data.sources.news.gdelt_news_for", side_effect=RuntimeError("GDELT down"))
    @patch("wc2026.data.sources.news.yahoo_news_for", return_value=[])
    @patch("wc2026.data.sources.news.authoritative_news_for", return_value=[
        _item("FIFA / official", "France prepare for Spain", "https://fifa.test/france-spain")
    ])
    @patch("wc2026.data.sources.news.google_news_for", return_value=[])
    def test_one_failed_source_does_not_discard_other_results(
        self, _google, _authoritative, _yahoo, _gdelt, _feeds, _web
    ):
        report = news.fetch_news_report(["France", "Spain"], limit=8, timeout=1)

        self.assertEqual(len(report["items"]), 2)
        self.assertEqual(report["status"], "partial")
        self.assertGreaterEqual(report["summary"]["failed"], 1)
        self.assertTrue(any(s["provider"] == "GDELT" and s["status"] == "failed"
                            for s in report["sources"]))
        self.assertTrue(all(item.get("source_tier") for item in report["items"]))

    @patch("wc2026.data.sources.news.fetch_all", return_value=[])
    @patch("wc2026.data.sources.news.gdelt_news_for", return_value=[])
    @patch("wc2026.data.sources.news.yahoo_news_for", return_value=[])
    @patch("wc2026.data.sources.news.authoritative_news_for", return_value=[])
    @patch("wc2026.data.sources.news.google_news_for", return_value=[])
    @patch("wc2026.data.sources.news.web_search_for_team", return_value=[
        _item("Web search", "Spain latest team news", "https://search.test/spain")
    ])
    def test_web_search_is_used_when_primary_sources_are_empty(
        self, web, _google, _authoritative, _yahoo, _gdelt, _feeds
    ):
        report = news.fetch_news_report(["Spain"], limit=8, timeout=1)

        self.assertEqual(report["items"][0]["title"], "Spain latest team news")
        self.assertEqual(report["items"][0]["source_tier"], "网页搜索兜底")
        self.assertEqual(web.call_count, 1)
        self.assertTrue(report["fallback_used"])

    @patch("wc2026.data.sources.news.web_search_for_team", return_value=[])
    @patch("wc2026.data.sources.news.fetch_all", return_value=[])
    @patch("wc2026.data.sources.news.gdelt_news_for", return_value=[])
    @patch("wc2026.data.sources.news.yahoo_news_for", return_value=[])
    @patch("wc2026.data.sources.news.authoritative_news_for", return_value=[])
    @patch("wc2026.data.sources.news.google_news_for", return_value=[])
    def test_all_empty_sources_return_degraded_report_instead_of_raising(
        self, _google, _authoritative, _yahoo, _gdelt, _feeds, _web
    ):
        report = news.fetch_news_report(["England", "Argentina"], limit=8, timeout=1)

        self.assertEqual(report["items"], [])
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["summary"]["available"], 0)
        self.assertIn("fetched_at", report)


if __name__ == "__main__":
    unittest.main()
