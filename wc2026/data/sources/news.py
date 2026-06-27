"""新闻资讯：抓取足球 RSS，按球队过滤。

英文源(BBC/ESPN)，故按英文队名+少量别名匹配；命中为空时上层可回退综合头条。
"分析"(从新闻抽取伤停/状态信号)依赖 LLM，见 analyze_news()，LLM 未通时返回 None。
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import requests

from wc2026.data.team_names import zh
from wc2026.llm import provider

FEEDS = {
    "BBC": "https://feeds.bbci.co.uk/sport/football/rss.xml",
    "ESPN": "https://www.espn.com/espn/rss/soccer/news",
    "Guardian": "https://www.theguardian.com/football/rss",
    "Sky Sports": "https://www.skysports.com/rss/12040",
    # 新增：更多足球新闻源
    "Goal.com": "https://www.goal.com/feeds/en/soccer/news",
    "Transfermarkt": "https://www.transfermarkt.com/rss/news",
}

# 中文新闻源（Google News RSS 定向搜索）
_GOOGLE_NEWS_ZH = "https://news.google.com/rss/search?q={q}&hl=zh-CN&gl=CN&ceid=CN:zh"
# 英文 Google News（覆盖更多国际源）
_GOOGLE_NEWS_EN = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"

# 部分球队的新闻别名（英文源里的常见写法）
_EXTRA = {
    "United States": ["USA", "USMNT"],
    "South Korea": ["Korea"],
    "North Korea": ["Korea DPR"],
    "Netherlands": ["Dutch", "Holland"],
    "Germany": ["German", "Die Mannschaft"],
    "Spain": ["Spanish", "La Roja"],
    "Ivory Coast": ["Cote d'Ivoire"],
    "England": ["Three Lions"],
    "Saudi Arabia": ["Saudi"],
    "Czech Republic": ["Czechia"],
    "South Africa": ["Bafana"],
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


def google_news_for(team: str, limit: int = 8, timeout: float = 15) -> list[dict]:
    """Google News RSS 按球队定向搜索（中文+英文双语）。失败返回 []。"""
    out, seen = [], set()
    team_zh = zh(team)

    # 中文搜索
    q_zh = quote(f"{team_zh} 足球 国家队")
    for it in _parse_feed("Google News(中)", _GOOGLE_NEWS_ZH.format(q=q_zh), timeout):
        key = it.get("link") or it.get("title")
        if key and key not in seen:
            seen.add(key)
            it["matched"] = team_zh
            out.append(it)

    # 英文搜索（补充国际源）
    q_en = quote(f"{team} World Cup 2026 national team")
    for it in _parse_feed("Google News(英)", _GOOGLE_NEWS_EN.format(q=q_en), timeout):
        key = it.get("link") or it.get("title")
        if key and key not in seen:
            seen.add(key)
            it["matched"] = team
            out.append(it)

    return out[:limit]


def web_search_for_team(team: str, limit: int = 8, timeout: float = 20) -> list[dict]:
    """联网搜索后备：当 RSS 结果不足时，用 DuckDuckGo/Bing 搜索球队新闻。

    返回与 fetch_for_teams 相同格式的 [{source, title, link, pub, summary, matched}]。
    """
    from wc2026.data.sources import web_search as ws

    team_zh = zh(team)
    results = []

    # 搜索中文新闻
    zh_results = ws.search_team_news(team_zh, max_results=limit // 2, timeout=timeout)
    for r in zh_results:
        results.append({
            "source": "Web搜索",
            "title": r.get("title", ""),
            "link": r.get("url", ""),
            "pub": "",
            "summary": r.get("snippet", ""),
            "matched": team_zh,
        })

    # 搜索英文新闻（补充）
    en_results = ws.search_duckduckgo(
        f"{team} World Cup 2026 news injury lineup",
        max_results=limit // 2,
        timeout=timeout,
    )
    for r in en_results:
        results.append({
            "source": "Web搜索(英)",
            "title": r.get("title", ""),
            "link": r.get("url", ""),
            "pub": "",
            "summary": r.get("snippet", ""),
            "matched": team,
        })

    return results[:limit]


def fetch_for_teams(teams: list[str], limit: int = 15, timeout: float = 20) -> list[dict]:
    """多源汇总：Google News(中+英) → 通用英文 RSS → 联网搜索后备。"""
    out, seen = [], set()

    def _add(it):
        key = it.get("link") or it.get("title")
        if key and key not in seen:
            seen.add(key)
            out.append(it)

    # 1) Google News 定向搜索（中文+英文双语）
    for t in teams:
        for it in google_news_for(t, timeout=timeout):
            _add(it)

    # 2) 通用英文 RSS 按队名匹配
    kws = {kw for t in teams for kw in _keywords(t)}
    for it in fetch_all(timeout):
        text = (it["title"] + " " + it["summary"]).lower()
        hit = next((kw for kw in kws if kw and kw in text), None)
        if hit:
            _add(dict(it, matched=hit))

    # 3) 联网搜索后备：当结果不足 limit 的 60% 时触发
    if len(out) < limit * 0.6:
        for t in teams:
            for it in web_search_for_team(t, limit=4, timeout=timeout):
                _add(it)

    return out[:limit]


def deep_search_and_analyze(team_home: str, team_away: str,
                            existing_items: list[dict] | None = None,
                            timeout: float = 25) -> dict | None:
    """深度联网搜索 + LLM 综合分析。

    当常规 RSS 新闻不足时，主动联网搜索并让 LLM 综合生成赛前情报摘要。
    包括：教练战术变化、伤停信息、士气/更衣室动态、近期表现、对手分析等。

    Returns:
        {"text": str, "sources": [str], "source": "deep_search"} 或 None
    """
    from wc2026.data.sources import web_search as ws

    home_zh = zh(team_home)
    away_zh = zh(team_away)

    # 收集已有新闻标题
    existing_headlines = []
    if existing_items:
        existing_headlines = [f"[{x.get('source','')}] {x.get('title','')}"
                              for x in existing_items[:10]]

    # 多维联网搜索
    search_results = []
    search_queries = [
        f"{home_zh} 世界杯 2026 最新 伤停 阵容",
        f"{away_zh} 世界杯 2026 最新 伤停 阵容",
        f"{home_zh} vs {away_zh} 世界杯 前瞻 分析",
        f"{team_home} World Cup 2026 injury news lineup",
        f"{team_away} World Cup 2026 coach tactics formation",
    ]
    for q in search_queries:
        try:
            results = ws.web_search(q, max_results=4, timeout=timeout)
            for r in results:
                search_results.append({
                    "source": "联网搜索",
                    "title": r.get("title", ""),
                    "snippet": r.get("snippet", ""),
                    "url": r.get("url", ""),
                })
        except Exception:
            continue

    if not search_results and not existing_headlines:
        return None

    # 构建 LLM prompt
    all_info = []
    if existing_headlines:
        all_info.append("【已有新闻标题】\n" + "\n".join(existing_headlines))
    if search_results:
        snippets = []
        for r in search_results[:15]:
            s = f"- [{r['source']}] {r['title']}"
            if r.get("snippet"):
                s += f"\n  摘要: {r['snippet'][:150]}"
            snippets.append(s)
        all_info.append("【联网搜索结果】\n" + "\n".join(snippets))

    info_text = "\n\n".join(all_info)

    prompt = (
        f"你是一位资深足球分析师。以下是关于 {home_zh} 和 {away_zh} 的最新情报"
        f"（来自 RSS 新闻 + 联网搜索）。\n\n"
        f"{info_text}\n\n"
        "请用中文生成一份简要的**赛前情报摘要**，包含以下方面（仅基于上述信息，不要编造）：\n"
        "1. **伤停/阵容**：两队已知的伤停、缺阵、复出球员\n"
        "2. **战术/教练**：教练近期战术调整、阵型变化、公开表态\n"
        "3. **士气/动态**：更衣室氛围、近期表现趋势、舆论压力\n"
        "4. **对比赛影响**：以上信息对比分预测的可能影响\n\n"
        "要求：每项 2-3 句话，信息不足的部分直接说明'暂无明确信息'。"
    )

    try:
        text = provider.chat(prompt, max_tokens=800, temperature=0.3, timeout=timeout)
        sources_used = list({r.get("source", "") for r in search_results})
        if existing_headlines:
            sources_used.append("RSS新闻")
        return {
            "text": text,
            "sources": sources_used,
            "source": "deep_search",
        }
    except provider.LLMError:
        # LLM 不可用时，直接返回搜索结果摘要
        if search_results:
            summary = "【联网搜索摘要】\n" + "\n".join(
                f"- {r['title']}: {r['snippet'][:80]}" for r in search_results[:5]
            )
            return {"text": summary, "sources": ["联网搜索"], "source": "deep_search_raw"}
        return None


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


_SEVERITY = ("高", "中", "低")


def _parse_risk_payload(text: str) -> dict:
    """解析风险标签 JSON → {"home":[{tag,severity,note}], "away":[...]}；非法输入降级为空。"""
    try:
        data = json.loads(_strip_json(text))
    except Exception:
        return {"home": [], "away": []}
    if not isinstance(data, dict):
        return {"home": [], "away": []}

    def clean(side: str) -> list:
        out = []
        for t in (data.get(side) or []):
            if isinstance(t, dict) and t.get("tag"):
                out.append({
                    "tag": str(t["tag"])[:12],
                    "severity": t["severity"] if t.get("severity") in _SEVERITY else "中",
                    "note": str(t.get("note", ""))[:60],
                })
        return out

    return {"home": clean("home"), "away": clean("away")}


def extract_risk_tags(team_home: str, team_away: str, items: list[dict]) -> dict | None:
    """用 LLM 从新闻标题抽取两队的「风险标签」（伤停/停赛/状态/内部矛盾/主帅/疲劳/舆论等）。

    返回 {"home":[{tag,severity,note}], "away":[...], "source":"llm", "raw":...}；
    LLM 不可用或无新闻返回 None。每条 severity 为 高/中/低；信息不足则对应队为空数组。
    """
    if not items:
        return None
    headlines = "\n".join(f"- [{x['source']}] {x['title']}" for x in items[:20])
    prompt = (
        f"下面是足球新闻标题。只依据这些标题，分别为「{zh(team_home)}」(键 home) 和"
        f"「{zh(team_away)}」(键 away) 抽取**对比赛有负面影响的风险标签**："
        "如 核心伤停 / 多人缺阵 / 停赛 / 状态低迷 / 内部矛盾 / 主帅问题 / 旅途疲劳 / 舆论压力 等。\n"
        "严格只输出 JSON，形如："
        '{"home":[{"tag":"核心伤停","severity":"高|中|低","note":"简述"}],"away":[]}\n'
        "规则：tag 不超过 12 字；只写标题中有依据的；没有就给空数组；不要编造、不要输出 JSON 以外任何字符。\n\n"
        + headlines
    )
    try:
        text = provider.chat(prompt, max_tokens=2000, temperature=0.1, timeout=120)
    except provider.LLMError:
        return None
    return {**_parse_risk_payload(text), "source": "llm", "raw": text}
