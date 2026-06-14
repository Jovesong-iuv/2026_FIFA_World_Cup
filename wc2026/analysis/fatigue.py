"""体能与旅行：从赛程算每队的休息天数与旅行距离（haversine），并提示高原/连续作战压力。

场馆经纬度/海拔为 2026 承办城市的公开地理数据（近似，足够算距离与高原判断）。
仅作方向性体能提示，不直接改写模型概率。
"""
from __future__ import annotations

import math

# 场馆名（fixtures.location）→ {lat, lon, alt(米), city}
VENUES = {
    "Atlanta Stadium": {"lat": 33.755, "lon": -84.401, "alt": 320, "city": "亚特兰大"},
    "BC Place Vancouver": {"lat": 49.277, "lon": -123.112, "alt": 0, "city": "温哥华"},
    "Boston Stadium": {"lat": 42.091, "lon": -71.264, "alt": 30, "city": "波士顿/福克斯堡"},
    "Dallas Stadium": {"lat": 32.747, "lon": -97.093, "alt": 150, "city": "达拉斯/阿灵顿"},
    "Guadalajara Stadium": {"lat": 20.682, "lon": -103.462, "alt": 1560, "city": "瓜达拉哈拉"},
    "Houston Stadium": {"lat": 29.685, "lon": -95.411, "alt": 15, "city": "休斯顿"},
    "Kansas City Stadium": {"lat": 39.049, "lon": -94.484, "alt": 270, "city": "堪萨斯城"},
    "Los Angeles Stadium": {"lat": 33.953, "lon": -118.339, "alt": 30, "city": "洛杉矶/英格尔伍德"},
    "Mexico City Stadium": {"lat": 19.303, "lon": -99.150, "alt": 2240, "city": "墨西哥城"},
    "Miami Stadium": {"lat": 25.958, "lon": -80.239, "alt": 3, "city": "迈阿密"},
    "Monterrey Stadium": {"lat": 25.669, "lon": -100.244, "alt": 500, "city": "蒙特雷"},
    "New York/New Jersey Stadium": {"lat": 40.814, "lon": -74.074, "alt": 3, "city": "纽约/新泽西"},
    "Philadelphia Stadium": {"lat": 39.901, "lon": -75.168, "alt": 3, "city": "费城"},
    "San Francisco Bay Area Stadium": {"lat": 37.403, "lon": -121.970, "alt": 3, "city": "旧金山湾区"},
    "Seattle Stadium": {"lat": 47.595, "lon": -122.332, "alt": 10, "city": "西雅图"},
    "Toronto Stadium": {"lat": 43.633, "lon": -79.418, "alt": 80, "city": "多伦多"},
}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def _date(s: str | None) -> str:
    return (s or "")[:10]


def rest_and_travel(team: str, fixtures: list[dict], match_number: int) -> dict:
    """该队在指定场次的 休息天数 / 旅行公里 / 当前海拔。首战或缺数据时相应字段为 None。"""
    mine = sorted([f for f in fixtures if f.get("home_team") == team or f.get("away_team") == team],
                  key=lambda f: f.get("date_utc") or "")
    cur = next((f for f in mine if f.get("match_number") == match_number), None)
    if cur is None:
        return {"rest_days": None, "travel_km": None, "alt": None, "prev_city": None}
    cv = VENUES.get(cur.get("location"))
    prev = [f for f in mine if (f.get("date_utc") or "") < (cur.get("date_utc") or "")]
    out = {"rest_days": None, "travel_km": None, "alt": cv["alt"] if cv else None,
           "city": cv["city"] if cv else None, "prev_city": None}
    if prev:
        p = prev[-1]
        try:
            from datetime import date
            d1 = date.fromisoformat(_date(p["date_utc"]))
            d2 = date.fromisoformat(_date(cur["date_utc"]))
            out["rest_days"] = (d2 - d1).days
        except Exception:
            pass
        pv = VENUES.get(p.get("location"))
        if cv and pv:
            out["travel_km"] = round(haversine_km(pv["lat"], pv["lon"], cv["lat"], cv["lon"]))
            out["prev_city"] = pv["city"]
    return out


def match_fatigue(home: str, away: str, fixtures: list[dict], fixture: dict | None) -> dict:
    """两队体能/旅行对比 + 提示。"""
    if not fixture or fixture.get("match_number") is None:
        return {"home": None, "away": None, "notes": []}
    mn = fixture["match_number"]
    h, a = rest_and_travel(home, fixtures, mn), rest_and_travel(away, fixtures, mn)
    notes = []
    if h["rest_days"] is not None and a["rest_days"] is not None:
        diff = h["rest_days"] - a["rest_days"]
        if abs(diff) >= 2:
            more = home if diff > 0 else away
            notes.append(f"{more} 多休息 {abs(diff)} 天，体能/恢复占优。")
    for who, d in ((home, h), (away, a)):
        if d["travel_km"] and d["travel_km"] >= 2500:
            notes.append(f"{who} 上一场后长途转场约 {d['travel_km']} 公里（{d['prev_city']}→{d['city']}），旅途消耗大。")
    alt = h.get("alt")
    if alt and alt >= 1500:
        notes.append(f"本场海拔约 {alt} 米（{h.get('city')}）：高原影响体能与球速，"
                     "客队若缺乏高原适应更吃亏，大小球与体能拼抢需谨慎。")
    if not notes:
        notes.append("两队休息与旅行差异不大；本场无明显体能/海拔倾向。")
    return {"home": h, "away": a, "notes": notes}
