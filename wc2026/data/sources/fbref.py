"""FBref(Sports Reference)球队射门/xG 源：cloudscraper 绕 Cloudflare → 解析 shooting 表 → JSON 缓存。

为「射门效率」维度提供真实 xG/射门数据（项目其余来源 FotMob 赛前无 xG）。

重要约束：
- FBref 对数据中心/沙箱 IP 常 403（Cloudflare）。cloudscraper 在普通住宅/服务器 IP 上通常可通过；
  本仓库的开发沙箱 IP 被封，故抓取需在你的部署环境验证。
- 一切失败优雅降级（返回 None），绝不阻塞主预测；射门效率维度无数据时回退 proxy。
- FBref 把多数数据表包在 HTML 注释里以懒渲染，解析前先剥离注释。
- 限速严格（官方建议 ≤10 次/分钟），内置 ≥4s/请求 节流。cloudscraper / bs4 为可选依赖，惰性导入。
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

from wc2026.config import settings

CACHE_PATH = settings.data_dir / "fbref_shooting.json"
_SEARCH = "https://fbref.com/en/search/search.fcgi?search="
_MIN_INTERVAL = 4.0  # FBref 限速严格
_LAST = {"t": 0.0}

# 库名 → FBref 搜索词（个别命名不一致；其余直接用库名搜索）
SEARCH_ALIAS = {
    "United States": "United States", "South Korea": "Korea Republic",
    "Czech Republic": "Czechia", "DR Congo": "Congo DR", "Ivory Coast": "Côte d'Ivoire",
    "Cape Verde": "Cabo Verde", "Curaçao": "Curaçao", "Turkey": "Türkiye",
    "Iran": "IR Iran",
}


class FBrefError(Exception):
    pass


def _scraper():
    """惰性创建 cloudscraper 会话；未安装则抛错（上层捕获并降级）。"""
    import cloudscraper  # 惰性导入：可选依赖
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "mobile": False})


def _throttle() -> None:
    dt = time.monotonic() - _LAST["t"]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _LAST["t"] = time.monotonic()


def _get(url: str, timeout: float = 40):
    _throttle()
    r = _scraper().get(url, timeout=timeout)
    if r.status_code != 200:
        raise FBrefError(f"HTTP {r.status_code}: {url}")
    return r


def _uncomment(html: str) -> str:
    """剥离 HTML 注释包裹（FBref 把表格藏在 <!-- --> 里）。"""
    return html.replace("<!--", "").replace("-->", "")


def _load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {"teams": {}, "urls": {}}
    try:
        d = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        d.setdefault("teams", {})
        d.setdefault("urls", {})
        return d
    except Exception:
        return {"teams": {}, "urls": {}}


def _save_cache(cache: dict) -> None:
    settings.ensure_dirs()
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_team_url(team_lib: str) -> str:
    """库名 → FBref 球队 stats 页 URL。先查缓存，再走搜索（搜索可能直接 302 到球队页）。"""
    cache = _load_cache()
    if team_lib in cache["urls"]:
        return cache["urls"][team_lib]
    term = SEARCH_ALIAS.get(team_lib, team_lib)
    r = _get(_SEARCH + quote(term))
    url = None
    # 搜索命中唯一实体时 FBref 直接跳转到该页
    if "/en/squads/" in r.url:
        url = r.url
    else:
        # 否则从结果页取第一个国家队链接（排除明显的青年队/女足）
        for path in re.findall(r'href="(/en/squads/[a-z0-9]{8}/[^"]+)"', r.text):
            low = path.lower()
            if any(b in low for b in ("-u23", "-u21", "-u20", "-u19", "women", "-w-")):
                continue
            url = "https://fbref.com" + path
            break
    if not url:
        raise FBrefError(f"FBref 未解析到球队页：{team_lib}")
    url = url.split("?")[0]
    cache["urls"][team_lib] = url
    _save_cache(cache)
    return url


def _parse_shooting(html: str) -> dict:
    """从球队页解析射门聚合：goals/shots/sot/xg/npxg。优先 shooting 表，回退 standard 表。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(_uncomment(html), "lxml")

    table = None
    for t in soup.find_all("table"):
        if "shooting" in (t.get("id") or ""):
            table = t
            break
    if table is None:
        for t in soup.find_all("table"):
            if "standard" in (t.get("id") or ""):
                table = t
                break
    if table is None:
        raise FBrefError("未找到 shooting/standard 表（FBref 结构可能已变）")

    # 取合计行：优先 tfoot，否则 tbody 最后一行
    row = None
    foot = table.find("tfoot")
    if foot:
        row = foot.find("tr")
    if row is None:
        body = table.find("tbody")
        rows = body.find_all("tr") if body else []
        row = rows[-1] if rows else None
    if row is None:
        raise FBrefError("未找到合计行")

    def cell(*stats):
        for s in stats:
            c = row.find(attrs={"data-stat": s})
            if c:
                txt = c.get_text(strip=True).replace(",", "")
                try:
                    return float(txt)
                except ValueError:
                    continue
        return None

    data = {
        "goals": cell("goals"),
        "shots": cell("shots_total", "shots"),
        "sot": cell("shots_on_target"),
        "xg": cell("xg"),
        "npxg": cell("npxg"),
    }
    if data["shots"] is None and data["goals"] is None:
        raise FBrefError("合计行无可用射门字段")
    return data


def fetch_team_shooting(team_lib: str) -> dict:
    """抓取并缓存某队 FBref 射门聚合。失败抛 FBrefError（上层捕获降级）。"""
    url = resolve_team_url(team_lib)
    data = _parse_shooting(_get(url).text)
    data["source_url"] = url
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cache = _load_cache()
    cache["teams"][team_lib] = data
    _save_cache(cache)
    return data


def load_shooting(team_lib: str) -> dict | None:
    """读 FBref 射门缓存（无网络）；未缓存返回 None。"""
    return _load_cache()["teams"].get(team_lib)


def finishing_score(shooting: dict | None) -> float | None:
    """射门聚合 → 0-100 射门效率分。需至少有 shots 与 goals；有 xg 时叠加超预期修正。

    转化率(goals/shots) 映射：0.05→30、0.11→55、0.18→85；
    再按 (goals−xg)/shots 的射手超预期 ±10 修正。无足量数据返回 None。
    """
    if not shooting:
        return None
    goals, shots, xg = shooting.get("goals"), shooting.get("shots"), shooting.get("xg")
    if not shots or shots <= 0 or goals is None:
        return None
    conv = goals / shots
    score = 30.0 + (conv - 0.05) / (0.18 - 0.05) * (85.0 - 30.0)
    if xg is not None:
        delta = (goals - xg) / shots          # 每脚射门的超预期
        score += max(-10.0, min(10.0, delta * 200.0))
    return max(0.0, min(100.0, score))
