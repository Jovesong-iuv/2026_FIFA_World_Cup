"""通用联网搜索模块：DuckDuckGo HTML 搜索（无需 API Key）。

作为 FBref / FotMob / RSS 新闻的后备数据源。
返回结构化结果：[{title, url, snippet}]。
"""
from __future__ import annotations

import re
import time
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_LAST_CALL = 0.0
_MIN_INTERVAL = 2.0  # 请求间隔（秒），避免被限流


def _throttle():
    global _LAST_CALL
    elapsed = time.time() - _LAST_CALL
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _LAST_CALL = time.time()


def search_duckduckgo(query: str, max_results: int = 8, timeout: float = 20) -> list[dict]:
    """DuckDuckGo HTML 搜索，返回 [{title, url, snippet}]。

    Args:
        query: 搜索关键词
        max_results: 最大返回数
        timeout: 请求超时（秒）

    Returns:
        搜索结果列表，每项包含 title, url, snippet 字段。
        失败返回空列表。
    """
    _throttle()
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}
    try:
        resp = requests.post(url, data=params, headers=_UA, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for r in soup.select(".result"):
        title_el = r.select_one(".result__title a")
        snippet_el = r.select_one(".result__snippet")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        # DuckDuckGo 的 href 可能是 //duckduckgo.com/l/?uddg=... 格式
        if "uddg=" in href:
            import urllib.parse
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
            href = parsed.get("uddg", [href])[0]
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        if title and href:
            results.append({
                "title": title,
                "url": href,
                "snippet": snippet,
            })
        if len(results) >= max_results:
            break
    return results


def search_bing(query: str, max_results: int = 8, timeout: float = 20) -> list[dict]:
    """Bing 搜索后备（当 DuckDuckGo 失败时使用）。

    Args:
        query: 搜索关键词
        max_results: 最大返回数
        timeout: 请求超时（秒）

    Returns:
        搜索结果列表，每项包含 title, url, snippet 字段。
        失败返回空列表。
    """
    _throttle()
    url = "https://www.bing.com/search"
    params = {"q": query, "count": max_results}
    try:
        resp = requests.get(url, params=params, headers=_UA, timeout=timeout)
        resp.raise_for_status()
    except Exception:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for li in soup.select("#b_results .b_algo"):
        title_el = li.select_one("h2 a")
        snippet_el = li.select_one(".b_caption p")
        if not title_el:
            continue
        title = title_el.get_text(strip=True)
        href = title_el.get("href", "")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        if title and href:
            results.append({
                "title": title,
                "url": href,
                "snippet": snippet,
            })
        if len(results) >= max_results:
            break
    return results


def web_search(query: str, max_results: int = 8, timeout: float = 20) -> list[dict]:
    """多引擎联网搜索（DuckDuckGo → Bing 后备）。

    Args:
        query: 搜索关键词
        max_results: 最大返回数
        timeout: 请求超时（秒）

    Returns:
        搜索结果列表，每项包含 title, url, snippet 字段。
        所有引擎失败返回空列表。
    """
    results = search_duckduckgo(query, max_results, timeout)
    if not results:
        results = search_bing(query, max_results, timeout)
    return results


def search_team_news(team_cn: str, max_results: int = 10, timeout: float = 20) -> list[dict]:
    """搜索球队相关新闻（中文 + 英文混合搜索）。

    Args:
        team_cn: 球队中文名
        max_results: 最大返回数
        timeout: 请求超时（秒）

    Returns:
        新闻搜索结果列表。
    """
    query = f"{team_cn} 世界杯 2026 足球 国家队 最新"
    return web_search(query, max_results, timeout)


def search_match_preview(home_cn: str, away_cn: str, max_results: int = 8, timeout: float = 20) -> list[dict]:
    """搜索比赛前瞻/分析文章。

    Args:
        home_cn: 主队中文名
        away_cn: 客队中文名
        max_results: 最大返回数
        timeout: 请求超时（秒）

    Returns:
        搜索结果列表。
    """
    query = f"{home_cn} vs {away_cn} 世界杯 2026 前瞻 分析"
    return web_search(query, max_results, timeout)


def search_injury_news(team_cn: str, max_results: int = 6, timeout: float = 20) -> list[dict]:
    """搜索球队伤停/阵容新闻。

    Args:
        team_cn: 球队中文名
        max_results: 最大返回数
        timeout: 请求超时（秒）

    Returns:
        搜索结果列表。
    """
    query = f"{team_cn} 伤停 缺阵 阵容 世界杯 2026"
    return web_search(query, max_results, timeout)
