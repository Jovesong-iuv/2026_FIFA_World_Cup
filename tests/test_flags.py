import unittest

from wc2026.data.flags import TEAM_ISO, flag_emoji


class FlagsTest(unittest.TestCase):
    def test_known_team_emoji(self):
        self.assertEqual(flag_emoji("Mexico"), "\U0001F1F2\U0001F1FD")   # MX
        self.assertEqual(flag_emoji("Brazil"), "\U0001F1E7\U0001F1F7")   # BR

    def test_england_scotland_special(self):
        self.assertTrue(flag_emoji("England").startswith("🏴"))
        self.assertTrue(flag_emoji("Scotland").startswith("🏴"))
        self.assertNotEqual(flag_emoji("England"), flag_emoji("Scotland"))

    def test_unknown_team_placeholder(self):
        self.assertEqual(flag_emoji("Atlantis"), "🏳️")

    def test_all_fixture_teams_have_iso(self):
        # 48 支参赛队应都有映射（England/Scotland 在特殊表）
        self.assertEqual(len(TEAM_ISO), 46)
        for iso in TEAM_ISO.values():
            self.assertEqual(len(iso), 2)


if __name__ == "__main__":
    unittest.main()
