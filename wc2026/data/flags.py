"""国旗 emoji：球队（库名）→ ISO 3166-1 alpha-2 → 区域指示符 emoji。

仅覆盖 2026 世界杯 fixtures 中的参赛队，避免对未知队伍臆测。
英格兰 / 苏格兰使用各自的子地区旗 emoji（非 GB 国旗）。
"""
from __future__ import annotations

# 球队库名 → ISO2
TEAM_ISO = {
    "Algeria": "DZ", "Argentina": "AR", "Australia": "AU", "Austria": "AT",
    "Belgium": "BE", "Bosnia and Herzegovina": "BA", "Brazil": "BR", "Canada": "CA",
    "Cape Verde": "CV", "Colombia": "CO", "Croatia": "HR", "Curaçao": "CW",
    "Czech Republic": "CZ", "DR Congo": "CD", "Ecuador": "EC", "Egypt": "EG",
    "France": "FR", "Germany": "DE", "Ghana": "GH", "Haiti": "HT", "Iran": "IR",
    "Iraq": "IQ", "Ivory Coast": "CI", "Japan": "JP", "Jordan": "JO", "Mexico": "MX",
    "Morocco": "MA", "Netherlands": "NL", "New Zealand": "NZ", "Norway": "NO",
    "Panama": "PA", "Paraguay": "PY", "Portugal": "PT", "Qatar": "QA",
    "Saudi Arabia": "SA", "Senegal": "SN", "South Africa": "ZA", "South Korea": "KR",
    "Spain": "ES", "Sweden": "SE", "Switzerland": "CH", "Tunisia": "TN",
    "Turkey": "TR", "United States": "US", "Uruguay": "UY", "Uzbekistan": "UZ",
}

# 子地区旗（England / Scotland 用 tag sequence，非 ISO 国家）
_SPECIAL = {
    "England": "🏴\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f",
    "Scotland": "🏴\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f",
}


def _iso_to_emoji(iso2: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso2.upper())


def flag_emoji(team: str) -> str:
    """返回球队国旗 emoji；未知队伍返回 🏳️（白旗占位，不臆测）。"""
    if team in _SPECIAL:
        return _SPECIAL[team]
    iso = TEAM_ISO.get(team)
    return _iso_to_emoji(iso) if iso else "🏳️"
