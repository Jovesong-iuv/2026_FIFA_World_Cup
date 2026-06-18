"""单场智能体报告聚合：把克莱门特组合模型 + 九维度 + 市场后验 + 风险/总结聚成一个契约对象。

对应 docs/product_optimization_requirements.md §7 的 MatchIntelligenceReport：
match / data_quality / dimensions / prediction / market_check / risks / summary。

原则（文档硬约束）：
- 赔率只做后验校验（market_check），绝不进入 prediction 主链（prediction 仅来自克莱门特矩阵）。
- 每个结论可溯源；缺数据维度标降级，不编造。
- 概率结论 + 置信度表达，避免确定性措辞。

纯函数：无赔率 key 也能跑（market_check.enabled=false）；不依赖 Streamlit。
"""
from __future__ import annotations

from datetime import datetime, timezone

from wc2026.analysis import clemente, upset as _upset
from wc2026.markets import derive, value
from wc2026.data.team_names import zh

_MARKET_LABELS = {"home": "主胜", "draw": "平局", "away": "客胜"}
# 市场后验偏差阈值（文档 5.4：±8%）
_MKT_THRESHOLD = 0.08


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_report(model, home: str, away: str, neutral: bool = True, *,
                 fixture: dict | None = None, fixtures: list | None = None,
                 odds_1x2: dict | None = None, group_state: dict | None = None,
                 home_formation: str | None = None, away_formation: str | None = None,
                 squad_value_home: float | None = None, squad_value_away: float | None = None,
                 finishing_home: float | None = None, finishing_away: float | None = None,
                 pred: dict | None = None) -> dict:
    """生成单场 MatchIntelligenceReport。odds_1x2 形如 {'home','draw','away'} 十进制赔率，可空。

    pred 可传入已算好的 clemente.predict 结果（单场页复用，避免重复计算）。"""
    if pred is None:
        pred = clemente.predict(model, home, away, neutral, fixtures=fixtures, fixture=fixture,
                                group_state=group_state, home_formation=home_formation,
                                away_formation=away_formation,
                                squad_value_home=squad_value_home, squad_value_away=squad_value_away,
                                finishing_home=finishing_home, finishing_away=finishing_away)
    mat = pred["matrix"]
    prof = pred["dimensions"]
    lam, mu = pred["exp_goals"]
    markets = derive.summarize(mat)
    x = markets["1x2"]

    report = {
        "match": _match_block(home, away, fixture),
        "data_quality": _data_quality_block(prof),
        "dimensions": prof["dims"],
        "dimension_summary": {
            "score_home": prof["score_home"], "score_away": prof["score_away"],
            "explanation": prof["explanation"],
        },
        "prediction": _prediction_block(markets, lam, mu, pred),
        "market_check": _market_check_block(x, odds_1x2),
        "risks": _risk_block(model, home, away, x, pred, prof),
        "confidence": pred["confidence"],
        "notes": pred["notes"],
        "summary": None,  # 下面填
        "generated_at": _now(),
    }
    report["summary"] = _summary_block(home, away, report)
    return report


def _match_block(home, away, fixture) -> dict:
    f = fixture or {}
    return {
        "home": home, "away": away, "home_cn": zh(home), "away_cn": zh(away),
        "venue": f.get("location") or "", "kickoff_utc": f.get("date_utc") or "",
        "group": f.get("group_name") or "", "round": f.get("round_number"),
    }


def _data_quality_block(prof: dict) -> dict:
    missing = [d["name"] for d in prof["dims"] if d["confidence"] == "degraded"]
    proxy = [d["name"] for d in prof["dims"] if d["confidence"] == "proxy"]
    return {"score": prof["data_quality"], "missing": missing, "proxy": proxy, "updated_at": _now()}


def _prediction_block(markets: dict, lam: float, mu: float, pred: dict) -> dict:
    x = markets["1x2"]
    ou = markets["over_under"].get("2.5", {})
    return {
        "expected_goals": {"home": lam, "away": mu, "total": round(lam + mu, 3)},
        "base_expected_goals": {"home": pred["base_exp_goals"][0], "away": pred["base_exp_goals"][1]},
        "outcomes": {k: round(v, 4) for k, v in x.items()},
        "fair_odds": {k: round(v, 2) for k, v in markets["1x2_fair_odds"].items()},
        "top_scores": [{"score": s["score"], "probability": round(s["prob"], 4)}
                       for s in markets["correct_score_top"][:5]],
        "totals": {"over_2_5": round(ou.get("over", 0.0), 4), "under_2_5": round(ou.get("under", 0.0), 4)},
        "goal_bands": markets["goal_bands"],
        "adj_factors": pred["adj_factors"],
    }


def market_check(model_1x2: dict, odds: dict | None) -> dict:
    """公开包装：赔率后验校验（文档 5.4 口径）。供单场页直接复用。

    返回 {enabled, source, overround, note, items:[{market,odds,model_prob,
    implied_prob,diff,label,edge}]}。赔率仅校验，不反写预测。"""
    return _market_check_block(model_1x2, odds)


def _market_check_block(model_1x2: dict, odds: dict | None) -> dict:
    """赔率后验：模型概率 vs 市场隐含（去水）。仅校验，不反写预测。"""
    if not odds or not all((odds.get(k) or 0) > 1.0 for k in ("home", "draw", "away")):
        return {"enabled": False, "reason": "无可用赔率（未拉取或缺 ODDS_API_KEY）",
                "note": "赔率仅作验证参考，不影响上方预测结论。", "items": []}
    imp = value.implied_probs(odds)
    fair = imp["fair"]
    kelly = value.value_and_kelly(model_1x2, odds)
    items = []
    for k in ("home", "draw", "away"):
        mp = model_1x2.get(k, 0.0)
        ip = fair.get(k, 0.0)
        diff = mp - ip  # 模型 - 市场（正=模型更看好）
        if abs(diff) <= _MKT_THRESHOLD:
            label = "基本一致"
        elif diff > _MKT_THRESHOLD:
            label = "潜在价值（模型偏高）"
        else:
            label = "市场高估"
        r = kelly.get(k) or {}
        items.append({
            "market": _MARKET_LABELS[k], "odds": odds.get(k),
            "model_prob": round(mp, 4), "implied_prob": round(ip, 4),
            "diff": round(diff, 4), "label": label,
            "edge": round(r.get("edge", 0.0), 4) if r else None,
        })
    return {"enabled": True, "source": "The Odds API", "overround": imp["overround"],
            "note": "赔率仅作验证参考，不影响上方预测结论。", "items": items}


def _risk_block(model, home, away, model_1x2, pred, prof) -> list[dict]:
    """分级风险：高/中/低。汇总控分、爆冷、数据不足、体能、临场等。"""
    risks: list[dict] = []

    # 爆冷（把热门当稳胆的风险）
    ui = _upset.upset_index(model_1x2, home, away, None, pred["tank_risk"])
    if ui["index"] >= 81:
        lvl = "高"
    elif ui["index"] >= 61:
        lvl = "中"
    else:
        lvl = "低"
    risks.append({"level": lvl, "tag": "爆冷风险",
                  "detail": f"爆冷指数 {ui['index']}/100（{ui['level']}）；"
                            f"{ui['factors'][0]['detail'] if ui['factors'] else ''}",
                  "sources": ["模型 1X2 + 爆冷指数"]})

    # 控分 / 默契球
    if pred["tank_risk"]:
        risks.append({"level": "高", "tag": "控分/默契球",
                      "detail": "出线形势已定，可能消极比赛或算计排名，结果随机性上升、比分参考价值下降",
                      "sources": ["末轮积分形势"]})

    # 数据不足（降级维度）
    dq = prof["data_quality"]
    missing = [d["name"] for d in prof["dims"] if d["confidence"] == "degraded"]
    if missing:
        risks.append({"level": "中" if dq < 0.55 else "低", "tag": "数据有限",
                      "detail": f"以下维度数据不足、按中性/代理处理，结论置信度下调：{'、'.join(missing)}",
                      "sources": ["数据完整度"]})

    # 体能/旅行/海拔（取 clemente 注入的相关 notes）
    fat_notes = [n for n in pred["notes"] if any(k in n for k in ("休息", "转场", "海拔", "旅途"))]
    for n in fat_notes:
        risks.append({"level": "低", "tag": "体能/旅行", "detail": n, "sources": ["赛程+场馆地理"]})

    # 临场首发/伤停（静态提示，需赛前刷新）
    risks.append({"level": "低", "tag": "临场变量",
                  "detail": "首发/伤停/天气以赛前官方为准；本报告未纳入实时官方名单，开赛前请刷新确认",
                  "sources": ["静态提示"]})
    return risks


def _summary_block(home, away, report) -> dict:
    """结构化 5 段式总结（规则生成，可由 LLM 仅做语言润色，不编造）。"""
    pred = report["prediction"]
    x = pred["outcomes"]
    fav_key = max(x, key=x.get)
    fav_label = {"home": zh(home), "draw": "平局", "away": zh(away)}[fav_key]
    lam, mu = pred["expected_goals"]["home"], pred["expected_goals"]["away"]
    top = pred["top_scores"][0]["score"] if pred["top_scores"] else "—"
    over = pred["totals"]["over_2_5"]
    goal_lean = "大球" if over >= 0.55 else ("小球" if over <= 0.45 else "中性")
    ds = report["dimension_summary"]

    main = (f"模型倾向：{fav_label}（{x[fav_key]:.0%}）；最可能比分 {top}；"
            f"总进球倾向 {goal_lean}（大 2.5 球 {over:.0%}）。")
    basis = f"预期进球 {lam:.2f} : {mu:.2f}。{ds['explanation']}"
    variables = "；".join(r["detail"] for r in report["risks"] if r["level"] in ("高", "中")) or \
        "无显著高/中风险变量；常规临场因素（首发/天气）以赛前为准"
    mc = report["market_check"]
    if mc["enabled"]:
        diverge = [it["market"] for it in mc["items"] if it["label"] != "基本一致"]
        market = ("赔率验证：" + ("模型与市场基本一致" if not diverge
                  else "模型与市场存在分歧（" + "、".join(diverge) + "），仅作提示不改写预测"))
    else:
        market = "赔率验证：暂无赔率，未做市场后验。"
    dq_score = report["data_quality"]["score"]
    conf = (f"置信度：{report['confidence']}（数据完整度 {dq_score:.0%}）；"
            "比分高度随机，概率仅供参考、非确定结果。")

    text = " ".join([main, basis, "关键变量：" + variables.rstrip("。") + "。",
                     market.rstrip("。") + "。", conf])
    return {"main": main, "basis": basis, "variables": variables,
            "market": market, "confidence": conf, "text": text}
