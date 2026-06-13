import unittest

from wc2026.access import owner_key_matches


class OwnerAccessTest(unittest.TestCase):
    def test_empty_owner_key_is_unrestricted(self):
        self.assertTrue(owner_key_matches("", None))
        self.assertTrue(owner_key_matches(None, "anything"))

    def test_matching_owner_query_unlocks_owner_mode(self):
        self.assertTrue(owner_key_matches("k7xQ9z", "k7xQ9z"))

    def test_missing_or_wrong_owner_query_is_visitor(self):
        self.assertFalse(owner_key_matches("k7xQ9z", None))
        self.assertFalse(owner_key_matches("k7xQ9z", "wrong"))
        self.assertFalse(owner_key_matches("k7xQ9z", " k7xQ9z "))


if __name__ == "__main__":
    unittest.main()
