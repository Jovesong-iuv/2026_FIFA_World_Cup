import tempfile
import unittest
from pathlib import Path

from wc2026.auth import create_user, list_users, load_users, reset_password, verify_login


class AuthTest(unittest.TestCase):
    def test_bootstraps_admin_and_verifies_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.json"

            users = load_users(path)

            self.assertIn("admin", users)
            self.assertEqual(users["admin"]["role"], "admin")
            self.assertTrue(verify_login("admin", "Shanghai123", path))
            self.assertFalse(verify_login("admin", "wrong", path))

    def test_admin_can_create_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.json"

            created = create_user("alice", "Secret123", path)
            duplicate = create_user("alice", "Other123", path)

            self.assertTrue(created)
            self.assertFalse(duplicate)
            self.assertTrue(verify_login("alice", "Secret123", path))
            self.assertEqual(load_users(path)["alice"]["role"], "user")

    def test_admin_can_reset_password_and_list_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "users.json"
            create_user("alice", "Secret123", path)

            changed = reset_password("alice", "NewSecret123", path)
            rows = list_users(path)

            self.assertTrue(changed)
            self.assertFalse(verify_login("alice", "Secret123", path))
            self.assertTrue(verify_login("alice", "NewSecret123", path))
            self.assertIn("password_hash_preview", rows[0])
            self.assertNotIn("NewSecret123", str(rows))


if __name__ == "__main__":
    unittest.main()
