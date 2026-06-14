"""访问 IP 记录：每个 IP 一行，记录访问次数与首末时间；所有者可加备注（姓名等）。

再次访问同一 IP 时自动累加次数、更新最近时间，并**保留已有备注**（auto-match）。
仅供所有者后台查看。conn 参数用于测试时注入内存库。
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime

from wc2026.data.db import get_conn

_INSERT = (
    "INSERT INTO ip_access (ip, first_seen, last_seen, visits, user_agent) VALUES (?,?,?,1,?) "
    "ON CONFLICT(ip) DO UPDATE SET last_seen=excluded.last_seen, "
    "visits=ip_access.visits+1, user_agent=excluded.user_agent"
)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_visit(ip: str, user_agent: str = "", conn=None) -> None:
    """记录一次访问（同 IP 累加、保留备注）。"""
    if not ip:
        return
    ts = _now()
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        c.execute(_INSERT, (ip, ts, ts, user_agent))


def set_note(ip: str, note: str, conn=None) -> None:
    """所有者给某 IP 设/改备注（不影响访问计数）。"""
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        c.execute("UPDATE ip_access SET note=? WHERE ip=?", (note, ip))


def list_access(conn=None) -> list[dict]:
    """按最近访问时间倒序返回全部记录。"""
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        rows = c.execute(
            "SELECT ip, note, first_seen, last_seen, visits, user_agent "
            "FROM ip_access ORDER BY last_seen DESC").fetchall()
    return [dict(r) for r in rows]
