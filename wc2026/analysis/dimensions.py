"""九维度评分：把项目已有信号折算为「开发需求文档版」9 维评分(各 0-100)+ 加权综合分。

延续 strength.py 的诚实口径：缺数据维度用 model-derived proxy 或中性 50 分并标「降级」，不编造。
赔率不作为维度（单列后验校验，见 markets/value.py 与 intelligence.market_check）。

数据来源（全部复用现有模块）：
- 近期状态 / 历史交锋 / 射门效率 ← evidence.recent_form / head_to_head
- 阵容实力 / 战术素养 / 战术匹配 / 防守组织 ← Elo + Dixon-Coles attack/defense
- 赛事动机 ← motivation 末轮状态 + 东道主
- 外部条件 ← environment 适应分（已折合时区/海拔/旅行/东道主）

输出结构与 strength.strength_profile 兼容（dims_home/dims_away/score_home/score_away），
便于单场页雷达图直接复用。
"""
from __future__ import annotations

import math

from wc2026.data.team_names import zh

# (key, 中文名, 权重)：采用开发需求文档版九维，权重之和 = 1.00
NINE_DIMS = [
    ("recent_form", "近期状态", 0.15),
    ("squad_strength", "阵容实力", 0.22),
    ("team_style", "战术素养", 0.10),
    ("tactical_matchup", "战术匹配", 0.08),
    ("motivation", "赛事动机", 0.10),
    ("defensive_org", "防守组织", 0.12),
    ("h2h", "历史交锋", 0.05),
    ("external", "外部条件", 0.08),
    ("finishing", "射门效率", 0.10),
]
DIMENSIONS = [name for _k, name, _w in NINE_DIMS]  # 供雷达图/条形图复用
_WEIGHTS = {name: w for _k, name, w in NINE_DIMS}

# 数据真实度 → data_quality 贡献权重
_CONF_Q = {"real": 1.0, "proxy": 0.5, "degraded": 0.0}

# 末轮战意状态 → 0-100 动机分（生死战最高，已出线因轮换风险下调）
_MOTIV_SCORE = {"must_win": 72.0, "alive": 55.0, "qualified": 45.0, "eliminated": 38.0}

HOSTS = {"Mexico", "Canada", "United States"}


def _minmax(value: float, lo: float, hi: float) -> float:
    if hi <= lo:
        return 50.0
    return max(0.0, min(100.0, (value - lo) / (hi - lo) * 100.0))


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


def _value_score(total_eur: float | None) -> float | None:
    """球队总身价(欧元) → 0-100。对数刻度：≈€3M→0、€100M→55、€1B→86、€2.5B→100。"""
    if not total_eur or total_eur <= 0:
        return None
    lg = math.log10(total_eur)
    return _clamp((lg - 6.5) / (9.4 - 6.5) * 100.0)


def _form_rate(form: dict | None) -> float | None:
    """近况场均得分率折 0-100；无样本返回 None。"""
    n = (form or {}).get("n", 0) or 0
    if not n:
        return None
    return (form.get("w", 0) * 3 + form.get("d", 0)) / (n * 3) * 100.0


def nine_dimension_profile(
    model, home: str, away: str, *,
    evidence: dict | None = None,
    env_report: dict | None = None,
    group_state: dict | None = None,
    squad_value_home: float | None = None,
    squad_value_away: float | None = None,
    finishing_home: float | None = None,
    finishing_away: float | None = None,
    neutral: bool = True,
) -> dict:
    """计算两队九维度评分。

    可选输入缺失时该维度降级（proxy 或中性 50），并在 data_quality 中体现。

    返回：{home, away, dims:[{key,name,weight,home,away,source,confidence}],
           dims_home/dims_away(按中文名), score_home, score_away,
           data_quality(0~1), explanation}
    """
    attack, defense = model.attack, model.defense
    a_lo, a_hi = min(attack.values()), max(attack.values())
    d_lo, d_hi = min(defense.values()), max(defense.values())

    elo = getattr(model, "elo", None)
    has_elo = bool(elo and getattr(elo, "ratings", None))
    if has_elo:
        e_lo, e_hi = min(elo.ratings.values()), max(elo.ratings.values())

    def elo_score(t: str) -> float:
        return _minmax(elo.rating(t), e_lo, e_hi) if has_elo else 50.0

    def atk_score(t: str) -> float:
        return _minmax(attack.get(t, a_lo), a_lo, a_hi)

    def def_quality(t: str) -> float:
        # defense 系数越低失球越少 → 反转为「防守质量」0-100
        return 100.0 - _minmax(defense.get(t, d_hi), d_lo, d_hi)

    ev = evidence or {}
    h2h = ev.get("h2h", {}) or {}
    total = int(h2h.get("total", 0) or 0)
    home_form = ev.get("home_form")
    away_form = ev.get("away_form")

    # 环境适应分（environment.match_environment_report 的 adaptation 段，按中文名键）
    adapt = {}
    for row in (env_report or {}).get("adaptation", []) or []:
        adapt[row.get("team")] = row.get("适应分")

    dims: list[dict] = []

    def add(key, h_val, a_val, source, confidence):
        name = next(n for k, n, _w in NINE_DIMS if k == key)
        dims.append({"key": key, "name": name, "weight": _WEIGHTS[name],
                     "home": round(_clamp(h_val), 1), "away": round(_clamp(a_val), 1),
                     "source": source, "confidence": confidence})

    # 1) 近期状态
    fh, fa = _form_rate(home_form), _form_rate(away_form)
    add("recent_form", fh if fh is not None else 50.0, fa if fa is not None else 50.0,
        "evidence.recent_form", "real" if (fh is not None and fa is not None) else "degraded")

    # 2) 阵容实力：Elo 为底；有 FotMob 身价(缓存)则混入并升级为真实
    vs_h, vs_a = _value_score(squad_value_home), _value_score(squad_value_away)
    if vs_h is not None or vs_a is not None:
        sq_h = 0.65 * elo_score(home) + 0.35 * (vs_h if vs_h is not None else elo_score(home))
        sq_a = 0.65 * elo_score(away) + 0.35 * (vs_a if vs_a is not None else elo_score(away))
        add("squad_strength", sq_h, sq_a, "Elo + FotMob 身价", "real")
    else:
        add("squad_strength", elo_score(home), elo_score(away),
            "Elo 评级（身价缺）", "real" if has_elo else "degraded")

    # 3) 战术素养：进攻系数 + 防守质量综合（整体技战术成熟度 proxy）
    add("team_style", (atk_score(home) + def_quality(home)) / 2.0,
        (atk_score(away) + def_quality(away)) / 2.0, "DC attack/defense", "proxy")

    # 4) 战术匹配：本队进攻 × 对手防守薄弱（按对手动态；无阵型时为 proxy）
    add("tactical_matchup",
        (atk_score(home) + (100.0 - def_quality(away))) / 2.0,
        (atk_score(away) + (100.0 - def_quality(home))) / 2.0,
        "DC 攻防对位", "proxy")

    # 5) 赛事动机：末轮战意状态 + 东道主
    gs = group_state or {}
    hs_status = gs.get("home", {}).get("status", "alive")
    as_status = gs.get("away", {}).get("status", "alive")
    mh = _MOTIV_SCORE.get(hs_status, 55.0)
    ma = _MOTIV_SCORE.get(as_status, 55.0)
    if (not neutral) and home in HOSTS:
        mh += 8.0
    motiv_real = hs_status != "alive" or as_status != "alive"
    add("motivation", mh, ma, "motivation 末轮状态/东道主", "real" if motiv_real else "degraded")

    # 6) 防守组织：DC 防守质量 + 近况失球微调
    def def_org(t: str, form: dict | None) -> float:
        s = def_quality(t)
        n = (form or {}).get("n", 0) or 0
        if n:
            ga_pg = (form.get("ga", 0) or 0) / n
            s += 8.0 if ga_pg <= 0.6 else (-8.0 if ga_pg >= 1.6 else 0.0)
        return s
    add("defensive_org", def_org(home, home_form), def_org(away, away_form),
        "DC defense + 近况失球", "real")

    # 7) 历史交锋：主队视角胜率；样本过少降级到中性
    if total >= 3:
        hw = h2h.get("a_win", 0) / total * 100.0
        aw = h2h.get("a_loss", 0) / total * 100.0
        add("h2h", hw, aw, f"H2H {total} 场", "real")
    else:
        add("h2h", 50.0, 50.0, f"H2H 样本不足({total} 场)", "degraded")

    # 8) 外部条件：环境适应分（已折合时区/海拔/旅行/东道主）
    ah, aa = adapt.get(zh(home)), adapt.get(zh(away))
    add("external", float(ah) if ah is not None else 50.0,
        float(aa) if aa is not None else 50.0,
        "environment 适应分", "real" if (ah is not None and aa is not None) else "degraded")

    # 9) 射门效率：有 FBref 真实 xG/射门分则用真实，否则回退近况进球 + 进攻系数(proxy)
    def finish_proxy(t: str, form: dict | None) -> float:
        base = atk_score(t)
        n = (form or {}).get("n", 0) or 0
        if n:
            gf_pg = (form.get("gf", 0) or 0) / n
            base = 0.6 * base + 0.4 * _clamp(gf_pg / 3.0 * 100.0)  # 3 球/场 ≈ 满分
        return base
    if finishing_home is not None or finishing_away is not None:
        fh = finishing_home if finishing_home is not None else finish_proxy(home, home_form)
        fa = finishing_away if finishing_away is not None else finish_proxy(away, away_form)
        add("finishing", fh, fa, "FBref 射门/xG", "real")
    else:
        add("finishing", finish_proxy(home, home_form), finish_proxy(away, away_form),
            "近况进球 + DC attack", "proxy")

    # 综合分（加权）与雷达兼容结构
    dims_home = {d["name"]: d["home"] for d in dims}
    dims_away = {d["name"]: d["away"] for d in dims}
    score_home = sum(d["weight"] * d["home"] for d in dims)
    score_away = sum(d["weight"] * d["away"] for d in dims)
    data_quality = sum(d["weight"] * _CONF_Q[d["confidence"]] for d in dims)

    explanation = _explain(home, away, dims, score_home, score_away)
    return {
        "home": home, "away": away, "dims": dims,
        "dims_home": dims_home, "dims_away": dims_away,
        "score_home": round(score_home, 1), "score_away": round(score_away, 1),
        "data_quality": round(data_quality, 3),
        "explanation": explanation,
    }


def _explain(home, away, dims, sh, sa) -> str:
    lead, _trail = (home, away) if sh >= sa else (away, home)
    gap = abs(sh - sa)
    tone = "明显" if gap >= 12 else "略" if gap >= 4 else "基本持平，"
    h_edge = max(dims, key=lambda d: d["home"] - d["away"])["name"]
    a_edge = max(dims, key=lambda d: d["away"] - d["home"])["name"]
    head = (f"{zh(home)} 综合 {sh:.0f} · {zh(away)} 综合 {sa:.0f}；"
            f"{'两队实力' + tone if tone == '基本持平，' else f'{zh(lead)} {tone}占优'}。")
    return head + f"{zh(home)} 相对优势在「{h_edge}」，{zh(away)} 相对优势在「{a_edge}」。"
