"""联网赛果补全：ESPN/Yahoo/FIFA 公开页搜索后备。

这里不把网页文本直接作为预测，只用于赛果证据与 fixtures 比分回填。
结构化源不可用时返回空结果，让刷新流水线降级继续。
"""
from __future__ import annotations

import re

from wc2026.data.sources import web_search
from wc2026.data.team_names import zh


_SCORE_RE = re.compile(r"(\b\d{1,2})\s*[-–]\s*(\d{1,2}\b)")


def _extract_score(text: str) -> tuple[int, int] | None:
    m = _SCORE_RE.search(text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def search_match_result(home: str, away: str, *, timeout: float = 20) -> dict | None:
    """搜索单场赛果。返回 {home_score, away_score, source, title, url} 或 None。"""
    home_zh, away_zh = zh(home), zh(away)
    queries = [
        f"ESPN 2026 FIFA World Cup {home} {away} score result",
        f"Yahoo Sports 2026 World Cup {home} {away} score result",
        f"FIFA World Cup 2026 {home} vs {away} score result",
        f"{home_zh} {away_zh} 2026世界杯 比分 赛果",
    ]
    for q in queries:
        for r in web_search.web_search(q, max_results=5, timeout=timeout):
            text = " ".join([r.get("title", ""), r.get("snippet", "")])
            if home.lower() not in text.lower() and home_zh not in text:
                continue
            if away.lower() not in text.lower() and away_zh not in text:
                continue
            score = _extract_score(text)
            if score is None:
                continue
            return {
                "home_score": score[0],
                "away_score": score[1],
                "source": "联网搜索",
                "title": r.get("title", ""),
                "url": r.get("url", ""),
            }
    return None
