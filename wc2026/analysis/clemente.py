"""克莱门特组合预测模型：以多维加权为主链，对模型期望进球做有界调整，赔率只做后验（不在此）。

设计（见 docs 与用户定义的「克莱门特预测原理」组合模型）：
- ② 多维加权为主链：在 context.adjusted_prediction（东道主/末轮战意/控分，已有且经赛果校准）基础上，
  再叠加模型 λ 未涵盖的「软信号」——战术取向、体能/旅行/海拔、近况射门效率残差——作为有界乘子。
- ③ 低比分/平局修正：DC 的 ρ 在 matrix_from_goals 内自动生效，无需额外处理。
- ① 高概率/稳健导向：产出 confidence(高/中/低) 与 data_quality，低置信时由展示层弱化单一比分。

所有新增调整严格有界（每队新增乘子夹紧在 ±15%），并产出 notes 解释；不接触任何赔率。
"""
from __future__ import annotations

from wc2026.analysis import context, dimensions, evidence as _evidence
from wc2026.analysis.environment import match_environment_report
from wc2026.data.team_names import zh

HOSTS = {"Mexico", "Canada", "United States"}

# 新增软信号乘子的单侧上下界（参照 adjustments.py 的 cap 哲学，保持模型严谨）
_FACTOR_LO, _FACTOR_HI = 0.85, 1.15


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _gather_evidence(home: str, away: str) -> dict:
    return {
        "h2h": _evidence.head_to_head(home, away),
        "home_form": _evidence.recent_form(home),
        "away_form": _evidence.recent_form(away),
    }


def _tactics_factor(home, away, home_formation, away_formation) -> tuple[float, list[str]]:
    """战术取向 → 总进球方向性乘子（对双方对称）。无阵型时为中性 1.0。"""
    from wc2026.analysis import tactics
    tr = tactics.tactical_read(home, away, home_formation, away_formation)
    hint = tr.get("goals_hint", "中性")
    if hint == "偏多":
        return 1.04, [f"战术取向偏进攻（{zh(home)}/{zh(away)} 阵型开放），总进球小幅上调"]
    if hint == "偏少":
        return 0.96, [f"战术取向偏防守，总进球小幅下调"]
    return 1.0, []


def _fatigue_factors(home, away, fixtures, fixture) -> tuple[float, float, list[str]]:
    """体能/旅行/海拔 → 各队 λ 乘子（劣势方下调）。缺赛程数据时为 1.0。"""
    if not fixtures or not fixture:
        return 1.0, 1.0, []
    from wc2026.analysis import fatigue as _fatigue
    mf = _fatigue.match_fatigue(home, away, fixtures, fixture)
    fh, fa = 1.0, 1.0
    notes: list[str] = []
    h, a = mf.get("home"), mf.get("away")
    if not (h and a):
        return 1.0, 1.0, []
    # 休息天数差 ≥ 2：少休息的一方小幅下调
    rh, ra = h.get("rest_days"), a.get("rest_days")
    if rh is not None and ra is not None and abs(rh - ra) >= 2:
        if rh < ra:
            fh *= 0.97; notes.append(f"{zh(home)} 少休息 {ra - rh} 天，体能略劣，进攻效率小幅下调")
        else:
            fa *= 0.97; notes.append(f"{zh(away)} 少休息 {rh - ra} 天，体能略劣，进攻效率小幅下调")
    # 长途转场 ≥ 2500km
    if (h.get("travel_km") or 0) >= 2500:
        fh *= 0.97; notes.append(f"{zh(home)} 长途转场约 {h['travel_km']}km，旅途消耗，小幅下调")
    if (a.get("travel_km") or 0) >= 2500:
        fa *= 0.97; notes.append(f"{zh(away)} 长途转场约 {a['travel_km']}km，旅途消耗，小幅下调")
    # 高海拔 ≥ 1500m：客队若非东道主、缺高原适应，小幅下调
    if (h.get("alt") or 0) >= 1500 and away not in HOSTS:
        fa *= 0.98; notes.append(f"本场海拔约 {h['alt']}m，{zh(away)} 高原适应不足，小幅下调")
    return fh, fa, notes


def _finishing_factors(home, away, base_lam, base_mu, ev) -> tuple[float, float, list[str]]:
    """近况场均进球显著偏离模型期望 → 各队 λ 小幅修正（射门效率残差，≤5%）。"""
    notes: list[str] = []

    def one(team, form, base):
        n = (form or {}).get("n", 0) or 0
        if not n:
            return 1.0
        gf_pg = (form.get("gf", 0) or 0) / n
        diff = gf_pg - base
        if diff >= 0.8:
            return 1.05
        if diff <= -0.8:
            return 0.95
        return 1.0

    fh = one(home, ev.get("home_form"), base_lam)
    fa = one(away, ev.get("away_form"), base_mu)
    if fh > 1.0:
        notes.append(f"{zh(home)} 近况场均进球高于模型期望，射门效率残差上调")
    elif fh < 1.0:
        notes.append(f"{zh(home)} 近况进球低迷，射门效率残差下调")
    if fa > 1.0:
        notes.append(f"{zh(away)} 近况场均进球高于模型期望，射门效率残差上调")
    elif fa < 1.0:
        notes.append(f"{zh(away)} 近况进球低迷，射门效率残差下调")
    return fh, fa, notes


def _confidence(data_quality: float, gap: float, tank_risk: bool) -> str:
    if tank_risk:
        return "低"
    if data_quality >= 0.70 and gap >= 12:
        return "高"
    if data_quality < 0.50:
        return "低"
    return "中"


def predict(model, home: str, away: str, neutral: bool = True, *,
            fixtures: list | None = None, fixture: dict | None = None,
            group_state: dict | None = None, tank_risk: bool = False,
            home_formation: str | None = None, away_formation: str | None = None,
            squad_value_home: float | None = None, squad_value_away: float | None = None,
            finishing_home: float | None = None, finishing_away: float | None = None,
            evidence: dict | None = None, env_report: dict | None = None) -> dict:
    """组合预测。返回 {matrix, exp_goals, base_exp_goals, adj_factors, notes,
    confidence, data_quality, tank_risk, dimensions}。"""
    base_lam, base_mu = model.expected_goals(home, away, neutral)

    # 主链第一层：东道主 / 末轮战意 / 控分（复用 context，已按赛果校准、有界）
    adj = context.adjusted_prediction(model, home, away, neutral,
                                      group_state=group_state, tank_risk=tank_risk)
    ctx_lam, ctx_mu = adj["exp_goals"]
    notes = list(adj["notes"])
    effective_tank = adj["tank_risk"]

    # 主链第二层：模型 λ 未涵盖的软信号（有界）
    ev = evidence or _gather_evidence(home, away)
    tac_f, tac_notes = _tactics_factor(home, away, home_formation, away_formation)
    fat_h, fat_a, fat_notes = _fatigue_factors(home, away, fixtures, fixture)
    fin_h, fin_a, fin_notes = _finishing_factors(home, away, base_lam, base_mu, ev)

    # 各队新增乘子（不含 context 已应用的部分），夹紧 ±15%
    f_home = _clip(tac_f * fat_h * fin_h, _FACTOR_LO, _FACTOR_HI)
    f_away = _clip(tac_f * fat_a * fin_a, _FACTOR_LO, _FACTOR_HI)
    notes += tac_notes + fat_notes + fin_notes

    lam = ctx_lam * f_home
    mu = ctx_mu * f_away
    matrix = model.matrix_from_goals(lam, mu)

    # 九维度（同一上下文，供报告复用，避免重复计算）
    prof = dimensions.nine_dimension_profile(
        model, home, away, evidence=ev,
        env_report=env_report or match_environment_report(home, away, matrix, fixture=fixture),
        group_state=group_state, neutral=neutral,
        squad_value_home=squad_value_home, squad_value_away=squad_value_away,
        finishing_home=finishing_home, finishing_away=finishing_away)
    gap = abs(prof["score_home"] - prof["score_away"])
    confidence = _confidence(prof["data_quality"], gap, effective_tank)

    return {
        "matrix": matrix,
        "exp_goals": (round(lam, 3), round(mu, 3)),
        "base_exp_goals": (round(base_lam, 3), round(base_mu, 3)),
        "adj_factors": {"tactics": round(tac_f, 4),
                        "home_total": round(f_home, 4), "away_total": round(f_away, 4),
                        "fatigue_home": round(fat_h, 4), "fatigue_away": round(fat_a, 4),
                        "finishing_home": round(fin_h, 4), "finishing_away": round(fin_a, 4)},
        "notes": notes,
        "confidence": confidence,
        "data_quality": prof["data_quality"],
        "tank_risk": effective_tank,
        "dimensions": prof,
    }
