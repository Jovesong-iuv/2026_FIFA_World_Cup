import unittest

from wc2026.viz.poster import match_poster_png


class PosterTest(unittest.TestCase):
    def test_returns_png_bytes(self):
        png = match_poster_png("墨西哥", "南非", {"home": 0.62, "draw": 0.24, "away": 0.14},
                               upset={"index": 21, "level": "中低风险"},
                               home_rank=13, away_rank=61, subtitle="A组第1轮 · 06-12 周五")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))  # PNG 魔数
        self.assertGreater(len(png), 1000)

    def test_finished_result_variant(self):
        png = match_poster_png("Mexico", "South Africa", {"home": 0.6, "draw": 0.25, "away": 0.15},
                               result="2 - 0")
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_minimal_inputs(self):
        png = match_poster_png("A", "B", {})
        self.assertTrue(png.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
