"""赛程展示工具：UTC 时间 → 北京时间/周几；比赛赛果状态；按「未开赛在上、已完赛在下」排序。

date_utc 形如 "2026-06-11 19:00:00Z"（UTC）。北京时间 = UTC + 8 小时。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

_WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
_BEIJING = timezone(timedelta(hours=8))


def parse_utc(date_utc: str | None):
    """解析 "YYYY-MM-DD HH:MM:SSZ"（或带 T）为带 UTC 时区的 datetime；失败返回 None。"""
    if not date_utc:
        return None
    s = str(date_utc).strip().rstrip("Z").replace("T", " ").strip()
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except Exception:
        return None


def beijing(date_utc: str | None) -> dict:
    """返回 {date, time, weekday, full}（北京时间）；无法解析时各字段为 '—'。"""
    dt = parse_utc(date_utc)
    if dt is None:
        return {"date": "—", "time": "—", "weekday": "—", "full": "—"}
    b = dt.astimezone(_BEIJING)
    wd = _WEEKDAYS[b.weekday()]
    return {"date": b.strftime("%Y-%m-%d"), "time": b.strftime("%H:%M"),
            "weekday": wd, "full": f"{b.strftime('%m-%d')} {wd} {b.strftime('%H:%M')}"}


def match_result(home_score, away_score, home: str = "主", away: str = "客") -> dict:
    """已完赛返回 {finished:True, score, winner, text}；未完赛 finished:False。"""
    if home_score is None or away_score is None:
        return {"finished": False, "score": None, "winner": None, "text": ""}
    hs, as_ = int(home_score), int(away_score)
    winner = "home" if hs > as_ else "away" if hs < as_ else "draw"
    if winner == "draw":
        text = f"平局 {hs}-{as_}"
    else:
        text = f"{(home if winner == 'home' else away)}胜 {hs}-{as_}"
    return {"finished": True, "score": f"{hs}-{as_}", "winner": winner, "text": text}


def is_concluded(fixture: dict, now_utc: datetime) -> bool:
    """已完赛（有比分）或开赛时间已过 → 视为已结束（排到下面）。"""
    if fixture.get("home_score") is not None and fixture.get("away_score") is not None:
        return True
    dt = parse_utc(fixture.get("date_utc"))
    return dt is not None and dt <= now_utc


def sort_fixtures(fixtures: list[dict], now_utc: datetime) -> list[dict]:
    """未开赛在上（按时间升序，最近的在前）；已结束在下（按时间降序，最新结果在前）。"""
    upcoming = [f for f in fixtures if not is_concluded(f, now_utc)]
    concluded = [f for f in fixtures if is_concluded(f, now_utc)]
    upcoming.sort(key=lambda f: f.get("date_utc") or "")
    concluded.sort(key=lambda f: f.get("date_utc") or "", reverse=True)
    return upcoming + concluded
