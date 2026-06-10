"""理由生成（"为什么"）+ 证据。

数学模型给数值概率；这里把"强弱 / 主场 / 期望进球 / 各市场 + 历史交锋 + 近期战绩"
组织成可读的"为什么"：
- LLM 可用 → 把这些事实串成自然中文解释；
- 不可用 → 规则模板生成同样基于事实的中文理由。
两条路径都只引用提供的事实，避免编造。队名显示用中文。
"""
from __future__ import annotations

from wc2026.analysis import evidence
from wc2026.data.team_names import zh
from wc2026.llm import provider
from wc2026.markets import derive

_SYSTEM = (
    "你是足球赛事概率分析助手。只能依据用户提供的结构化数据(含交锋、近况)进行解释，"
    "禁止编造未给出的伤停、阵容或新闻。用简洁中文输出 3-5 句，说明强弱依据、"
    "交锋/近况是否支持判断、关键市场含义，并提醒这是基于历史数据的概率参考、非盈利保证。"
)


def build_factors(model, home: str, away: str, neutral: bool) -> dict:
    lam, mu = model.expected_goals(home, away, neutral)
    edge = (model.attack[home] + model.defense[away]) - (model.attack[away] + model.defense[home])
    return {
        "home": home, "away": away, "neutral": neutral,
        "exp_goals_home": round(lam, 2), "exp_goals_away": round(mu, 2),
        "attack_home": round(model.attack[home], 3), "defense_home": round(model.defense[home], 3),
        "attack_away": round(model.attack[away], 3), "defense_away": round(model.defense[away], 3),
        "home_adv": 0.0 if neutral else round(model.home_adv, 3),
        "strength_edge": round(edge, 3),  # >0 主队占优(log 尺度)
    }


def _form_str(form: dict, name_zh: str) -> str:
    return f"{name_zh}近 {form['n']} 场 {form['w']}胜{form['d']}平{form['l']}负(进{form['gf']}失{form['ga']})"


def rule_based_reason(factors: dict, markets: dict, ev: dict | None = None) -> str:
    f, x = factors, markets["1x2"]
    home_zh, away_zh = zh(f["home"]), zh(f["away"])
    edge = f["strength_edge"]
    if edge > 0.25:
        strength = f"{home_zh}综合实力明显强于{away_zh}"
    elif edge > 0.05:
        strength = f"{home_zh}略强于{away_zh}"
    elif edge < -0.25:
        strength = f"{away_zh}综合实力明显强于{home_zh}"
    elif edge < -0.05:
        strength = f"{away_zh}略强于{home_zh}"
    else:
        strength = f"{home_zh}与{away_zh}实力接近"
    venue = "中立场，无主场加成" if f["neutral"] else f"{home_zh}有主场之利"
    odds = markets["1x2_fair_odds"]
    ou25 = markets["over_under"].get("2.5", {})
    btts = markets["btts"]

    lines = [f"【强弱】{strength}：模型预期进球约 {f['exp_goals_home']} : {f['exp_goals_away']}（{venue}）。"]
    if ev and ev["h2h"]["total"] > 0:
        h = ev["h2h"]
        lines.append(f"【交锋】双方近 {h['total']} 次交手：{home_zh} {h['a_win']}胜{h['draw']}平{h['a_loss']}负，"
                     f"场均进球 {h['avg_gf']} : {h['avg_ga']}。")
    if ev:
        lines.append(f"【近况】{_form_str(ev['home_form'], home_zh)}；{_form_str(ev['away_form'], away_zh)}。")
    lines.append(f"【胜平负】{home_zh}胜 {x['home']:.1%} / 平 {x['draw']:.1%} / {away_zh}胜 {x['away']:.1%}，"
                 f"公平赔率约 {odds['home']:.2f} / {odds['draw']:.2f} / {odds['away']:.2f}。")
    lines.append(f"【进球】大于 2.5 球 {ou25.get('over', 0):.0%}，双方进球 {btts['yes']:.0%}。")
    lines.append("注：以上为基于历史战绩的概率估计，仅供参考，非盈利保证。")
    return "\n".join(lines)


def _llm_prompt(factors: dict, markets: dict, ev: dict | None = None) -> str:
    import json
    home_zh, away_zh = zh(factors["home"]), zh(factors["away"])
    compact = {
        "对阵": f"{home_zh}(主) vs {away_zh}(客)",
        "中立场": factors["neutral"],
        "预期进球": [factors["exp_goals_home"], factors["exp_goals_away"]],
        "强度优势(log,>0主队占优)": factors["strength_edge"],
        "胜平负": markets["1x2"],
        "公平赔率": {k: round(v, 2) for k, v in markets["1x2_fair_odds"].items()},
        "大小球2.5": markets["over_under"].get("2.5", {}),
        "双方进球": markets["btts"],
        "最可能比分": markets["correct_score_top"][:4],
    }
    if ev:
        h = ev["h2h"]
        compact["历史交锋"] = {
            "总场次": h["total"],
            f"{home_zh}胜/平/负": [h["a_win"], h["draw"], h["a_loss"]],
            "场均进球": [h["avg_gf"], h["avg_ga"]],
        }
        compact["近期战绩"] = {
            home_zh: f"{ev['home_form']['w']}胜{ev['home_form']['d']}平{ev['home_form']['l']}负",
            away_zh: f"{ev['away_form']['w']}胜{ev['away_form']['d']}平{ev['away_form']['l']}负",
        }
    return ("请依据以下结构化预测数据(含历史交锋与近期战绩)，用中文解释这场比赛的强弱依据、"
            "交锋/近况是否支持模型判断、关键市场含义：\n"
            + json.dumps(compact, ensure_ascii=False, indent=2))


def generate_reason(model, home: str, away: str, neutral: bool = True,
                    markets: dict | None = None, use_llm: bool = True) -> dict:
    """返回 {text, source, factors, evidence}。
    use_llm=False 时只用规则模板(不调 LLM，零外部请求)，供看板默认懒加载。"""
    factors = build_factors(model, home, away, neutral)
    if markets is None:
        markets = derive.summarize(model.score_matrix(home, away, neutral))
    ev = {
        "h2h": evidence.head_to_head(home, away),
        "home_form": evidence.recent_form(home),
        "away_form": evidence.recent_form(away),
    }
    if use_llm:
        try:
            text = provider.chat(_llm_prompt(factors, markets, ev), system=_SYSTEM,
                                 max_tokens=700, temperature=0.4)
            source = "llm"
        except provider.LLMError:
            text = rule_based_reason(factors, markets, ev)
            source = "rule"
    else:
        text = rule_based_reason(factors, markets, ev)
        source = "rule"
    return {"text": text, "source": source, "factors": factors, "evidence": ev}
