"""球队名映射。

两件事：
1) ALIAS：把赛程源(fixturedownload)的队名标准化到历史库(martj42)的队名，
   否则模型查不到该队的强度。
2) ZH：库名 → 中文，用于界面显示。逻辑/查询一律用库名（英文），仅展示用中文。
"""
from __future__ import annotations

# 赛程源队名 → 历史库标准队名（经核对，库中确实存在）
ALIAS = {
    "USA": "United States",
    "Korea Republic": "South Korea",
    "Czechia": "Czech Republic",
    "Türkiye": "Turkey",
    "IR Iran": "Iran",
    "Cabo Verde": "Cape Verde",
    "Congo DR": "DR Congo",
    "Côte d'Ivoire": "Ivory Coast",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
}

# 库名 → 中文（覆盖 2026 参赛队 + 常见强队；缺失则回退英文原名）
ZH = {
    # —— 2026 参赛 / 占位已知队 ——
    "Mexico": "墨西哥", "Canada": "加拿大", "United States": "美国",
    "South Africa": "南非", "South Korea": "韩国", "Czech Republic": "捷克",
    "Bosnia and Herzegovina": "波黑", "Algeria": "阿尔及利亚", "Argentina": "阿根廷",
    "Australia": "澳大利亚", "Austria": "奥地利", "Belgium": "比利时", "Brazil": "巴西",
    "Cape Verde": "佛得角", "Colombia": "哥伦比亚", "DR Congo": "刚果(金)",
    "Croatia": "克罗地亚", "Curaçao": "库拉索", "Ivory Coast": "科特迪瓦",
    "Ecuador": "厄瓜多尔", "Egypt": "埃及", "England": "英格兰", "France": "法国",
    "Germany": "德国", "Ghana": "加纳", "Haiti": "海地", "Iran": "伊朗", "Iraq": "伊拉克",
    "Japan": "日本", "Jordan": "约旦", "Morocco": "摩洛哥", "Netherlands": "荷兰",
    "New Zealand": "新西兰", "Norway": "挪威", "Panama": "巴拿马", "Paraguay": "巴拉圭",
    "Portugal": "葡萄牙", "Qatar": "卡塔尔", "Saudi Arabia": "沙特阿拉伯",
    "Scotland": "苏格兰", "Senegal": "塞内加尔", "Spain": "西班牙", "Sweden": "瑞典",
    "Switzerland": "瑞士", "Tunisia": "突尼斯", "Turkey": "土耳其", "Uruguay": "乌拉圭",
    "Uzbekistan": "乌兹别克斯坦",
    # —— 常见强队（H2H / 新闻可能涉及）——
    "Italy": "意大利", "Poland": "波兰", "Denmark": "丹麦", "Serbia": "塞尔维亚",
    "Wales": "威尔士", "Nigeria": "尼日利亚", "Cameroon": "喀麦隆", "Chile": "智利",
    "Peru": "秘鲁", "Russia": "俄罗斯", "Ukraine": "乌克兰", "Greece": "希腊",
    "Romania": "罗马尼亚", "Hungary": "匈牙利", "Mali": "马里", "Costa Rica": "哥斯达黎加",
    "Northern Ireland": "北爱尔兰", "Republic of Ireland": "爱尔兰", "Slovakia": "斯洛伐克",
    "Slovenia": "斯洛文尼亚", "Finland": "芬兰", "Iceland": "冰岛", "Albania": "阿尔巴尼亚",
    "Bolivia": "玻利维亚", "Venezuela": "委内瑞拉", "China PR": "中国", "Thailand": "泰国",
    "Vietnam": "越南", "Cameroon": "喀麦隆", "Mali": "马里",
}


def to_lib(name: str) -> str:
    """赛程源队名 → 历史库标准队名。"""
    return ALIAS.get(name, name)


def zh(name: str) -> str:
    """任意队名 → 中文显示名（先标准化再查；查不到回退英文原名）。"""
    return ZH.get(to_lib(name), name)
