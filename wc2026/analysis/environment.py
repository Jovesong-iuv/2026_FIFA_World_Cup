"""赛前环境、适应性与国家背景分析。

这些因素用于补充单场解释，不直接改写模型概率。政治/经济背景只做宏观语境提示，
避免把场外关系当作可量化的硬胜负变量。
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

from wc2026.data.team_names import zh


STADIUMS = {
    "Los Angeles Stadium": {
        "name_zh": "洛杉矶体育场",
        "city_zh": "洛杉矶/英格尔伍德",
        "timezone": "America/Los_Angeles",
        "altitude_m": 38,
        "surface": "天然草/临时世界杯草皮方案",
        "climate": "6月夜间通常温和偏干，海风影响下体感较舒适",
        "weather_hint": "预计更接近低海拔、温和干燥环境；实时天气需赛前刷新确认",
    },
    "Seattle Stadium": {
        "name_zh": "西雅图体育场",
        "city_zh": "西雅图",
        "timezone": "America/Los_Angeles",
        "altitude_m": 52,
        "surface": "世界杯临时草皮方案",
        "climate": "6月偏凉爽，可能有海洋性湿润影响",
        "weather_hint": "低海拔，气温压力通常不高，但湿度和降雨需赛前确认",
    },
    "San Francisco Bay Area Stadium": {
        "name_zh": "旧金山湾区体育场",
        "city_zh": "圣克拉拉/湾区",
        "timezone": "America/Los_Angeles",
        "altitude_m": 2,
        "surface": "天然草/世界杯草皮方案",
        "climate": "6月多为温和干燥，夜间可能转凉",
        "weather_hint": "低海拔、温差不大；风和夜间体感需临场关注",
    },
}


TEAM_CONTEXT = {
    "United States": {
        "home_region": "北美",
        "timezone": "America/New_York",
        "altitude_home_m": 200,
        "climate": "美国队对北美长途旅行、低海拔和美式场馆环境更熟悉",
        "travel": "本土作战，后勤与场地熟悉度优势明显",
        "country": "东道主之一，经济与体育产业基础强，主场关注度高",
    },
    "Paraguay": {
        "home_region": "南美",
        "timezone": "America/Asuncion",
        "altitude_home_m": 120,
        "climate": "巴拉圭球员通常适应温暖环境，低海拔不是明显障碍",
        "travel": "跨洲北上，旅行距离和赛前适应安排更关键",
        "country": "南美传统硬朗球队，整体国家体量与经济资源小于美国",
    },
    "Australia": {
        "home_region": "大洋洲/亚洲赛区",
        "timezone": "Australia/Sydney",
        "altitude_home_m": 58,
        "climate": "长期跨洲比赛经验较多，但北美时差压力大",
        "travel": "远征距离长，倒时差和恢复管理很关键",
        "country": "发达经济体，职业体育体系成熟，国家队远征经验丰富",
    },
    "Turkey": {
        "home_region": "欧洲/西亚",
        "timezone": "Europe/Istanbul",
        "altitude_home_m": 39,
        "climate": "对温暖气候适应较好，北美西海岸需要倒时差",
        "travel": "跨大西洋远征，前期集训质量会影响比赛强度",
        "country": "足球文化强，国内联赛强度较高，政治经济背景复杂但不直接决定比赛",
    },
    "Mexico": {
        "home_region": "北美",
        "timezone": "America/Mexico_City",
        "altitude_home_m": 2240,
        "climate": "高原经验强，来到低海拔场地通常氧耗压力下降",
        "travel": "东道主之一，北美作战适应成本较低",
        "country": "区域足球强国，主场球迷与北美旅行便利度较高",
    },
    "Canada": {
        "home_region": "北美",
        "timezone": "America/Toronto",
        "altitude_home_m": 76,
        "climate": "更适应低温和温和环境，炎热天气下需关注消耗",
        "travel": "东道主之一，北美赛地后勤压力较小",
        "country": "发达经济体，足球资源近年提升，阵容上限更多取决于球员状态",
    },
}


REGION_CONTEXT = {
    "政治关系": "双方无直接隶属关系；若同属美洲体系，交流与区域影响更多体现在宏观背景，不等同于赛果优势。",
    "国家实力与经济背景": "国家经济、体育产业和后勤资源会影响长期建设与备战保障，但单场仍主要由阵容、状态和战术决定。",
    "国情与足球背景": "足球文化、旅欧球员数量、国内联赛强度和大赛经验，比宏观政治叙事更接近比赛层面的变量。",
    "附庸/上下关系": "本模块不把国家间关系写成附庸判断；仅提示是否存在明显资源与区域影响力不对称。",
}


def match_environment_report(home: str, away: str, mat: np.ndarray, fixture: dict | None = None) -> dict:
    fixture = fixture or {}
    venue = fixture.get("location") or ""
    stadium = STADIUMS.get(venue)
    local_time = _local_kickoff(fixture.get("date_utc"), stadium)
    home_ctx = _team_context(home)
    away_ctx = _team_context(away)
    home_score = _adaptation_score(home, home_ctx, stadium)
    away_score = _adaptation_score(away, away_ctx, stadium)

    environment = [
        _timezone_row(home, away, local_time, stadium, home_ctx, away_ctx),
        _stadium_row(stadium, venue),
        _altitude_row(stadium, home_ctx, away_ctx),
        _weather_row(stadium),
        _travel_row(home, away, home_ctx, away_ctx, home_score, away_score),
    ]
    adaptation = [
        _adaptation_row(home, home_ctx, home_score, stadium),
        _adaptation_row(away, away_ctx, away_score, stadium),
    ]
    background = _background_rows(home, away, home_ctx, away_ctx)
    score_pick = _score_pick(mat, home_score, away_score)
    return {
        "environment": environment,
        "adaptation": adaptation,
        "background": background,
        "score_pick": score_pick,
        "local_kickoff": local_time,
    }


def _team_context(team: str) -> dict:
    return TEAM_CONTEXT.get(team, {
        "home_region": "暂无结构化资料",
        "timezone": "UTC",
        "altitude_home_m": None,
        "climate": "暂无该队气候适应资料，按中性处理",
        "travel": "暂无该队远征资料，按中性处理",
        "country": "暂无该队国家背景资料，按中性处理",
    })


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.replace("Z", "+00:00").replace(" ", "T")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _local_kickoff(date_utc: str | None, stadium: dict | None) -> str:
    dt = _parse_utc(date_utc)
    if not dt or not stadium:
        return "暂无赛程当地时间"
    local = dt.astimezone(ZoneInfo(stadium["timezone"]))
    return local.strftime("%Y-%m-%d %H:%M")


def _timezone_row(home: str, away: str, local_time: str, stadium: dict | None,
                  home_ctx: dict, away_ctx: dict) -> dict:
    if not stadium:
        return {"factor": "跨时区", "detail": "暂无球场时区资料", "impact": "按中性处理"}
    h_gap = _tz_gap(home_ctx["timezone"], stadium["timezone"])
    a_gap = _tz_gap(away_ctx["timezone"], stadium["timezone"])
    detail = f"当地开球 {local_time}；{zh(home)}约 {h_gap} 小时时差，{zh(away)}约 {a_gap} 小时时差"
    impact = "时差越大，赛前到达时间、睡眠和恢复越关键"
    return {"factor": "跨时区", "detail": detail, "impact": impact}


def _stadium_row(stadium: dict | None, venue: str) -> dict:
    if not stadium:
        return {"factor": "球场信息", "detail": f"{venue or '自定义场地'} 暂无结构化球场资料", "impact": "无法评估场地偏向"}
    detail = f"{stadium['name_zh']} · {stadium['city_zh']} · {stadium['surface']}"
    return {"factor": "球场信息", "detail": detail, "impact": "熟悉北美场馆、草皮和旅行节奏的一方适应成本更低"}


def _altitude_row(stadium: dict | None, home_ctx: dict, away_ctx: dict) -> dict:
    if not stadium:
        return {"factor": "海拔影响", "detail": "暂无球场海拔资料", "impact": "按中性处理"}
    alt = stadium["altitude_m"]
    h_home = home_ctx.get("altitude_home_m")
    a_home = away_ctx.get("altitude_home_m")
    detail = f"球场海拔约 {alt}m；主队常驻参考 {h_home or '—'}m，客队常驻参考 {a_home or '—'}m"
    impact = "低海拔场地通常不会造成明显缺氧压力，高原队伍可能体能压力下降"
    return {"factor": "海拔影响", "detail": detail, "impact": impact}


def _weather_row(stadium: dict | None) -> dict:
    if not stadium:
        return {"factor": "气温与天气", "detail": "暂无球场气候资料", "impact": "赛前需结合实时天气"}
    return {"factor": "气温与天气", "detail": stadium["climate"], "impact": stadium["weather_hint"]}


def _travel_row(home: str, away: str, home_ctx: dict, away_ctx: dict,
                home_score: int, away_score: int) -> dict:
    diff = home_score - away_score
    lean = zh(home) if diff >= 6 else zh(away) if diff <= -6 else "双方接近"
    detail = f"{zh(home)}：{home_ctx['travel']}；{zh(away)}：{away_ctx['travel']}"
    return {"factor": "远征与场地适应", "detail": detail, "impact": f"综合适应分 {home_score}:{away_score}，倾向：{lean}"}


def _adaptation_row(team: str, ctx: dict, score: int, stadium: dict | None) -> dict:
    venue_note = "暂无场地资料" if not stadium else f"{stadium['city_zh']}低海拔场地"
    return {
        "team": zh(team),
        "适应分": score,
        "气候": ctx["climate"],
        "远征": ctx["travel"],
        "场地": venue_note,
    }


def _adaptation_score(team: str, ctx: dict, stadium: dict | None) -> int:
    score = 55
    if team in {"United States", "Mexico", "Canada"}:
        score += 14
    if stadium:
        gap = _tz_gap(ctx["timezone"], stadium["timezone"])
        score += max(0, 10 - gap * 3)
        altitude = stadium["altitude_m"]
        home_alt = ctx.get("altitude_home_m")
        if home_alt is not None and abs(home_alt - altitude) <= 500:
            score += 6
        elif home_alt is not None and home_alt >= 1500 and altitude < 500:
            score += 4
    if "远征距离长" in ctx["travel"] or "跨洲" in ctx["travel"]:
        score -= 8
    if "本土作战" in ctx["travel"]:
        score += 10
    return max(25, min(95, score))


def _background_rows(home: str, away: str, home_ctx: dict, away_ctx: dict) -> list[dict]:
    asymmetry = "美国" in {zh(home), zh(away)}
    relation = "同处美洲区域语境，政治/经贸联系存在但不构成足球层面的直接控制关系" if (
        {home_ctx["home_region"], away_ctx["home_region"]} <= {"北美", "南美"}
    ) else "跨区域对阵，政治关系更多是背景信息，不宜直接量化为胜负优势"
    return [
        {"factor": "政治关系", "summary": relation, "match_impact": REGION_CONTEXT["政治关系"]},
        {"factor": "国家实力与经济背景",
         "summary": f"{zh(home)}：{home_ctx['country']}；{zh(away)}：{away_ctx['country']}",
         "match_impact": REGION_CONTEXT["国家实力与经济背景"]},
        {"factor": "国情与足球背景",
         "summary": f"{zh(home)}与{zh(away)}的足球强弱仍优先看模型、阵容、状态和战术匹配",
         "match_impact": REGION_CONTEXT["国情与足球背景"]},
        {"factor": "附庸/上下关系",
         "summary": "存在资源与区域影响力不对称" if asymmetry else "暂无明确结构化上下关系信号",
         "match_impact": REGION_CONTEXT["附庸/上下关系"]},
    ]


def _score_pick(mat: np.ndarray, home_score: int, away_score: int) -> dict:
    top = _top_scores(mat, 5)
    if home_score - away_score >= 6:
        preferred = [s for s in top if s[0] >= s[1]]
    elif away_score - home_score >= 6:
        preferred = [s for s in top if s[1] >= s[0]]
    else:
        preferred = top
    hi, ai, prob = preferred[0] if preferred else top[0]
    return {
        "score": f"{hi}-{ai}",
        "prob": prob,
        "basis": "以模型最高比分为底座，叠加环境、时区、海拔、天气、远征和国家背景适应性后的参考比分",
    }


def _top_scores(mat: np.ndarray, n: int) -> list[tuple[int, int, float]]:
    arr = np.asarray(mat, dtype=float)
    flat = arr.flatten()
    cols = arr.shape[1]
    out = []
    for idx in np.argsort(flat)[::-1][:n]:
        hi, ai = divmod(int(idx), cols)
        out.append((hi, ai, float(flat[idx])))
    return out


def _tz_gap(team_tz: str, venue_tz: str) -> int:
    base = datetime(2026, 6, 1, 12, tzinfo=ZoneInfo(venue_tz))
    team = base.astimezone(ZoneInfo(team_tz))
    return abs(int((team.utcoffset().total_seconds() - base.utcoffset().total_seconds()) / 3600))
