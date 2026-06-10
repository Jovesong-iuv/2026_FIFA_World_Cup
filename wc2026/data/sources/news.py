"""新闻资讯：抓取足球 RSS，按球队过滤。

英文源(BBC/ESPN)，故按英文队名+少量别名匹配；命中为空时上层可回退综合头条。
"分析"(从新闻抽取伤停/状态信号)依赖 LLM，见 analyze_news()，LLM 未通时返回 None。
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

import requests

from wc2026.data.team_names import zh
from wc2026.llm import provider

FEEDS = {
    "BBC": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN": "https://www.espn.com/espn/rss/soccer/news",
}

# 部分球队的新闻别名（英文源里的常见写法）
_EXTRA = {
    "United States": ["USA", "USMNT"],
    "South Korea": ["Korea"],
    "Netherlands": ["Dutch"],
    "Germany": ["German"],
    "Spain": ["Spanish"],
    "Ivory Coast": ["Cote d'Ivoire"],
}

_UA = {"User-Agent": "Mozilla/5.0 (compatible; WC2026Predictor/0.1)"}


def _parse_feed(name: str, url: str, timeout: float = 20) -> list[dict]:
    try:
        resp = requests.get(url, timeout=timeout, headers=_UA)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return []
    items = []
    for it in root.iter("item"):
        items.append({
            "source": name,
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "pub": (it.findtext("pubDate") or "").strip(),
            "summary": (it.findtext("description") or "").strip(),
        })
    return items


def fetch_all(timeout: float = 20) -> list[dict]:
    out, seen = [], set()
    for name, url in FEEDS.items():
        for it in _parse_feed(name, url, timeout):
            key = it["link"] or it["title"]
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(it)
    return out


def _keywords(team: str) -> list[str]:
    return [k.lower() for k in ([team] + _EXTRA.get(team, []))]


def fetch_for_teams(teams: list[str], limit: int = 15, timeout: float = 20) -> list[dict]:
    kws = {kw for t in teams for kw in _keywords(t)}
    matched = []
    for it in fetch_all(timeout):
        text = (it["title"] + " " + it["summary"]).lower()
        hit = next((kw for kw in kws if kw and kw in text), None)
        if hit:
            it = dict(it, matched=hit)
            matched.append(it)
    return matched[:limit]


def analyze_news(team_home: str, team_away: str, items: list[dict]) -> dict | None:
    """用 LLM 从新闻提取与两队相关的伤停/状态/士气信号。LLM 不可用则返回 None。"""
    if not items:
        return None
    headlines = "\n".join(f"- [{x['source']}] {x['title']}" for x in items[:15])
    prompt = (
        f"以下是与 {zh(team_home)} 和 {zh(team_away)} 可能相关的足球新闻标题。"
        "请只基于这些标题，用中文简要总结对这两队有参考价值的信息"
        "(如伤停、状态、士气、阵容变动)；若标题信息不足，直接说明信息有限，不要编造：\n"
        + headlines
    )
    try:
        text = provider.chat(prompt, max_tokens=400, temperature=0.3)
        return {"text": text, "source": "llm"}
    except provider.LLMError:
        return None


def _strip_json(text: str) -> str:
    """去掉可能的 ```json ... ``` 围栏，取出 JSON 主体。"""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", t, re.S)
    return m.group(1).strip() if m else t


def extract_injuries(team_home: str, team_away: str, items: list[dict]) -> dict | None:
    """用 LLM 从新闻标题抽取两队的伤停/缺阵/复出线索（粗粒度、头条级）。

    返回 {"home":[...], "away":[...], "source":"llm", "raw":...}；LLM 不可用返回 None。
    每条形如 {"player":.., "status":"伤停|存疑|停赛|复出", "note":..}；信息不足则对应队为空数组。
    """
    if not items:
        return None
    headlines = "\n".join(f"- [{x['source']}] {x['title']}" for x in items[:20])
    prompt = (
        f"下面是足球新闻标题。只依据这些标题，分别为「{zh(team_home)}」(键 home) 和"
        f"「{zh(team_away)}」(键 away) 抽取与**球员可用性**相关的线索："
        "伤停 / 存疑 / 停赛 / 复出。\n"
        "严格只输出 JSON，形如："
        '{"home":[{"player":"姓名","status":"伤停|存疑|停赛|复出","note":"简述"}],"away":[]}\n'
        "规则：只写标题中明确提到的；没有就给空数组；不要编造、不要输出 JSON 以外任何字符。\n\n"
        + headlines
    )
    try:
        text = provider.chat(prompt, max_tokens=8000, temperature=0.1, timeout=120)
    except provider.LLMError:
        return None
    try:
        data = json.loads(_strip_json(text))
    except Exception:
        return {"home": [], "away": [], "source": "llm", "raw": text}
    home = data.get("home", []) if isinstance(data, dict) else []
    away = data.get("away", []) if isinstance(data, dict) else []
    return {"home": home, "away": away, "source": "llm", "raw": text}
