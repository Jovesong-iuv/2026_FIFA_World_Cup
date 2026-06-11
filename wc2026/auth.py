"""本地用户认证：JSON 存储 + PBKDF2 密码哈希。"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from wc2026.config import settings

USERS_PATH = settings.data_dir / "users.json"
ADMIN_USER = "admin"
ADMIN_PASSWORD = "Shanghai123"


def load_users(path: Path = USERS_PATH) -> dict:
    """读取用户文件；不存在时初始化默认管理员。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        users = {ADMIN_USER: _user_record(ADMIN_PASSWORD, "admin")}
        _save_users(users, path)
        return users
    with path.open("r", encoding="utf-8") as f:
        users = json.load(f)
    changed = False
    if ADMIN_USER not in users:
        users[ADMIN_USER] = _user_record(ADMIN_PASSWORD, "admin")
        changed = True
    for record in users.values():
        now = _now()
        if "created_at" not in record:
            record["created_at"] = now
            changed = True
        if "updated_at" not in record:
            record["updated_at"] = record["created_at"]
            changed = True
    if changed:
        _save_users(users, path)
    return users


def verify_login(username: str, password: str, path: Path = USERS_PATH) -> bool:
    users = load_users(path)
    record = users.get(username.strip())
    if not record:
        return False
    return _verify_password(password, record["password_hash"])


def create_user(username: str, password: str, path: Path = USERS_PATH, role: str = "user") -> bool:
    username = username.strip()
    if not username or not password:
        return False
    users = load_users(path)
    if username in users:
        return False
    users[username] = _user_record(password, role)
    _save_users(users, path)
    return True


def reset_password(username: str, password: str, path: Path = USERS_PATH) -> bool:
    username = username.strip()
    if not username or not password:
        return False
    users = load_users(path)
    if username not in users:
        return False
    users[username]["password_hash"] = _hash_password(password)
    users[username]["updated_at"] = _now()
    _save_users(users, path)
    return True


def list_users(path: Path = USERS_PATH) -> list[dict]:
    rows = []
    for username, record in sorted(load_users(path).items()):
        password_hash = record.get("password_hash", "")
        rows.append({
            "username": username,
            "role": record.get("role", ""),
            "password_hash_preview": _hash_preview(password_hash),
            "created_at": record.get("created_at", ""),
            "updated_at": record.get("updated_at", ""),
        })
    return rows


def user_role(username: str, path: Path = USERS_PATH) -> str:
    return load_users(path).get(username, {}).get("role", "")


def _user_record(password: str, role: str) -> dict:
    now = _now()
    return {"password_hash": _hash_password(password), "role": role, "created_at": now, "updated_at": now}


def _hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"pbkdf2_sha256${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_hex, digest_hex = stored.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return hmac.compare_digest(actual, expected)


def _save_users(users: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def _hash_preview(password_hash: str) -> str:
    if len(password_hash) <= 18:
        return password_hash
    return f"{password_hash[:16]}...{password_hash[-8:]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
