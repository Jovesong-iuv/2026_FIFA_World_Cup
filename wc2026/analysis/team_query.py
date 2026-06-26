"""单队信息查询：排名、近况、画像、阵容与联网新闻提示。

本模块只做展示聚合；新闻中的轮换/替补/休息主力只作为风险提示，
不写入球队实力修正，也不改变模型预测参数。
"""
from __future__ import annotations

import json

from wc2026.analysis import evidence, ranking
from wc2026.config import settings
from wc2026.data.team_names import zh

ROTATION_KEYWORDS = (
    "rotate", "rotation", "rotated", "bench", "rest starters", "rest key",
    "second string", "reserve", "替补", "轮换", "主力休息", "休息主力",
    "大轮换", "替补上场", "替补出场",
)


def _load_profiles() -> dict:
    try:
        return json.loads((settings.data_dir / "team_profiles.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _current_record(team: str, fixtures: list[dict] | None) -> dict:
    played = w = d = l = gf = ga = 0
    recent = []
    for f in sorted(fixtures or [], key=lambda r: r.get("date_utc") or "", reverse=True):
        if f.get("home_score") is None or f.get("away_score") is None:
            continue
        if team not in {f.get("home_team"), f.get("away_team")}:
            continue
        played += 1
        is_home = f.get("home_team") == team
        ts = int(f["home_score"] if is_home else f["away_score"])
        os_ = int(f["away_score"] if is_home else f["home_score"])
        opp = f["away_team"] if is_home else f["home_team"]
        gf += ts
        ga += os_
        outcome = "胜" if ts > os_ else ("平" if ts == os_ else "负")
        w += outcome == "胜"
        d += outcome == "平"
        l += outcome == "负"
        if len(recent) < 5:
            recent.append({
                "date": (f.get("date_utc") or "")[:10],
                "opponent": opp,
                "opponent_cn": zh(opp),
                "score": f"{ts}-{os_}",
                "outcome": outcome,
                "group": f.get("group_name") or "",
            })
    return {
        "played": played, "w": w, "d": d, "l": l,
        "gf": gf, "ga": ga, "gd": gf - ga,
        "recent": recent,
    }


def rotation_signals(items: list[dict] | None) -> dict:
    hits = []
    for item in items or []:
        title = str(item.get("title") or "")
        summary = str(item.get("summary") or "")
        hay = f"{title} {summary}".lower()
        if any(k.lower() in hay for k in ROTATION_KEYWORDS):
            hits.append({
                "title": title,
                "source": item.get("source") or "",
                "link": item.get("link") or "",
            })
    return {
        "detected": bool(hits),
        "items": hits[:5],
        "policy": "轮换/替补/休息主力仅作为赛前风险提示展示，不修正球队基础强弱，不写入弱队或强队实力数据。",
    }


def build_team_snapshot(model, team: str, fixtures: list[dict] | None = None) -> dict:
    rank, source = ranking.world_rank(model, team)
    profiles = _load_profiles()
    profile = profiles.get(team, {})
    return {
        "team": team,
        "team_cn": zh(team),
        "rank": rank,
        "rank_source": source,
        "ranking_date": ranking.ranking_date(),
        "profile": {
            "formation": profile.get("formation") or "",
            "style_detail": profile.get("style_detail") or profile.get("background") or "",
            "best_achievement": profile.get("best_achievement") or "",
            "wc_appearances": profile.get("wc_appearances") or "",
            "key_players": profile.get("key_players") or [],
            "training_base": profile.get("training_base") or "",
        },
        "current_record": _current_record(team, fixtures),
        "recent_form": evidence.recent_form(team, limit=6),
    }
