import unittest

from wc2026.data.sources.news import _parse_risk_payload


class ParseRiskPayloadTest(unittest.TestCase):
    def test_valid_payload(self):
        text = '{"home":[{"tag":"核心伤停","severity":"高","note":"主力前锋受伤"}],"away":[]}'
        res = _parse_risk_payload(text)
        self.assertEqual(len(res["home"]), 1)
        self.assertEqual(res["home"][0]["tag"], "核心伤停")
        self.assertEqual(res["home"][0]["severity"], "高")
        self.assertEqual(res["away"], [])

    def test_strips_code_fence(self):
        text = '```json\n{"home":[],"away":[{"tag":"停赛","severity":"中"}]}\n```'
        res = _parse_risk_payload(text)
        self.assertEqual(res["away"][0]["tag"], "停赛")
        self.assertEqual(res["away"][0]["note"], "")  # 缺 note → 空串

    def test_invalid_severity_defaults_medium(self):
        res = _parse_risk_payload('{"home":[{"tag":"舆论压力","severity":"爆表"}],"away":[]}')
        self.assertEqual(res["home"][0]["severity"], "中")

    def test_entries_without_tag_dropped(self):
        res = _parse_risk_payload('{"home":[{"severity":"高"},{"tag":"疲劳"}],"away":[]}')
        self.assertEqual([t["tag"] for t in res["home"]], ["疲劳"])

    def test_garbage_returns_empty(self):
        for bad in ("not json", "[1,2,3]", "", "{}"):
            res = _parse_risk_payload(bad)
            self.assertEqual(res, {"home": [], "away": []})

    def test_long_tag_and_note_truncated(self):
        res = _parse_risk_payload('{"home":[{"tag":"' + "标" * 20 + '","note":"' + "x" * 100 + '"}],"away":[]}')
        self.assertEqual(len(res["home"][0]["tag"]), 12)
        self.assertEqual(len(res["home"][0]["note"]), 60)


if __name__ == "__main__":
    unittest.main()
