"""赛后审计：模型预测 vs 市场赔率 vs 实际赛果 三方对比。

对应 docs/product_optimization_requirements.md §6.4 / §11.3 / §12 阶段4：
- 模型概率：优先取赛前锁定快照（imminent.lock_prematch_snapshot 落库的 outcomes），
  无快照则用当前模型事后复算，并标注 model_source（事后复算存在数据泄漏，仅参考）。
- 市场隐含：取开赛前最后一次 h2h 赔率快照（odds_history）去水得 fair 概率；无则降级。
- 实际赛果：fixtures 的 home_score/away_score。
- 指标（Brier / Log Loss / top-pick 准确率 / 校准）复用 backtest.runner.prob_metrics，
  与历届回测同一口径，便于横向比较。

纯函数，不依赖 Streamlit；无快照、无赔率也能跑（对应字段降级，不编造）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from wc2026.analysis import clemente
from wc2026.backtest.runner import prob_metrics
from wc2026.data import odds_history
from wc2026.data.team_names import zh
from wc2026.markets import derive, value

_OUTCOME_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}


def _parse_utc(s) -> datetime | None:
    """兼容 fixtures 的 '2026-06-11 19:00:00Z' 与 ISO 的 '...+00:00'。"""
    if not s:
        return None
    t = str(s).strip().replace(" ", "T")
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def actual_outcome(home_score, away_score) -> str | None:
    if home_score is None or away_score is None:
        return None
    return "home" if home_score > away_score else ("draw" if home_score == away_score else "away")


def _model_probs(model, home, away, neutral, fixture, fixtures, snapshot):
    """返回 (probs{home,draw,away}, source_label, locked_at|None)。"""
    if snapshot and snapshot.get("outcomes"):
        o = snapshot["outcomes"]
        if all(k in o for k in ("home", "draw", "away")):
            return ({k: float(o[k]) for k in ("home", "draw", "away")},
                    "赛前锁定快照", snapshot.get("locked_at"))
    pred = clemente.predict(model, home, away, neutral, fixture=fixture, fixtures=fixtures)
    x = derive.outcomes_1x2(pred["matrix"])
    return ({k: float(x[k]) for k in ("home", "draw", "away")},
            "事后复算（当前模型，非赛前锁定）", None)


def _market_probs(home, away, kickoff_utc, conn=None):
    """开赛前最后一次 h2h 赔率快照 → fair 概率。返回 (probs|None, captured_at|None, odds|None)。"""
    series = odds_history.load_history(home, away, "h2h", conn=conn)
    if not series:
        return None, None, None
    ko = _parse_utc(kickoff_utc)
    odds, captured = {}, None
    for sel in ("home", "draw", "away"):
        chosen = None
        for ts, o in (series.get(sel) or []):   # 升序
            t = _parse_utc(ts)
            if ko is not None and t is not None and t >= ko:
                break                            # 只采赛前快照
            chosen = (ts, o)
        if chosen is None:
            return None, None, None
        odds[sel] = chosen[1]
        captured = chosen[0] if captured is None else max(captured, chosen[0])
    if not all((odds.get(k) or 0) > 1.0 for k in ("home", "draw", "away")):
        return None, None, None
    fair = value.implied_probs(odds)["fair"]
    return ({k: float(fair[k]) for k in ("home", "draw", "away")}, captured, odds)


def _pick(probs: dict) -> str:
    return max(probs, key=probs.get)


def _stage(fixture: dict) -> dict:
    rn = fixture.get("round_number")
    try:
        rn_int = int(rn)
    except (TypeError, ValueError):
        rn_int = 0
    if rn_int >= 4:
        labels = {4: "32强淘汰赛", 5: "16强淘汰赛", 6: "四分之一决赛", 7: "半决赛", 8: "决赛/三四名"}
        return {"type": "knockout", "label": labels.get(rn_int, "淘汰赛")}
    return {"type": "group", "label": fixture.get("group_name") or "小组赛"}


def _insight_entry(home: str, away: str, insights: dict | None) -> dict | None:
    if insights is None:
        try:
            from wc2026.analysis import match_insights
            insights = match_insights.load_insights()
        except Exception:
            insights = {}
    matches = (insights or {}).get("matches", {})
    keys = (f"{home}::{away}", f"{away}::{home}", f"{home}__{away}", f"{away}__{home}")
    return next((matches[k] for k in keys if k in matches), None)


def _team_process(entry: dict | None, team: str) -> dict:
    out = {"xg": None, "shots": None}
    for row in (entry or {}).get("prior_matches", []):
        if row.get("team") != team:
            continue
        if row.get("xg_for") is not None:
            out["xg"] = float(row["xg_for"])
        if row.get("shots_for") is not None:
            out["shots"] = int(row["shots_for"])
        break
    return out


def _event_flags(entry: dict | None) -> list[str]:
    text = " ".join(
        [str((entry or {}).get("deep_analysis", {}).get("text", ""))]
        + [str(x) for x in (entry or {}).get("tactical_notes", [])]
        + [str(x) for x in (entry or {}).get("availability_notes", [])]
    )
    checks = [
        ("penalty_shootout", ("点球大战", "点球")),
        ("red_card", ("红牌", "罚下")),
        ("injury_exit", ("伤退", "受伤离场")),
        ("own_goal", ("乌龙", "own goal")),
    ]
    return [key for key, words in checks if any(w in text for w in words)]


def _model_update_signal(audit: dict, fixture: dict, entry: dict | None) -> dict:
    """把赛后偏差分成：实力偏差 / 对位偏差 / 随机事件 / 无需修正。"""
    home, away = audit["match"]["home"], audit["match"]["away"]
    hs, as_ = int(fixture.get("home_score") or 0), int(fixture.get("away_score") or 0)
    h_proc, a_proc = _team_process(entry, home), _team_process(entry, away)
    flags = _event_flags(entry)
    notes = []
    primary = "model_aligned" if audit["model"].get("hit") else "strength_bias"
    should_update = not audit["model"].get("hit")
    weight = "medium" if should_update else "low"

    h_xg, a_xg = h_proc.get("xg"), a_proc.get("xg")
    if h_xg is not None and a_xg is not None:
        xg_diff = h_xg - a_xg
        score_diff = hs - as_
        if abs(xg_diff) <= 0.35 and abs(score_diff) <= 1:
            notes.append("xG与比分差距都较小，本场随机性占比较高。")
        elif (xg_diff > 0.6 and score_diff <= 0) or (xg_diff < -0.6 and score_diff >= 0):
            primary = "random_event"
            should_update = False
            weight = "low"
            notes.append("过程数据与结果方向相反，更像效率/运气波动，不宜直接改写实力。")
        elif (xg_diff > 0.6 and score_diff > 0) or (xg_diff < -0.6 and score_diff < 0):
            primary = "strength_bias"
            should_update = True
            weight = "high" if audit["stage"]["type"] == "knockout" else "medium"
            notes.append("xG优势与比分方向一致，具备实力修正信号。")

    text = " ".join(str(x) for x in (entry or {}).get("tactical_notes", []))
    if text and any(w in text for w in ("压制", "克制", "逼抢", "边路", "阵型")):
        if primary not in {"random_event", "strength_bias"}:
            primary = "matchup_bias"
            should_update = True
            weight = "medium"
        notes.append("战术/对位证据明显，后续单场应作为对位修正因子。")

    if flags:
        primary = "random_event"
        should_update = False
        weight = "low"
        notes.append("检测到点球/红牌/伤退/乌龙等特殊事件，应独立入账，降低实力回灌权重。")

    if not notes:
        notes.append("缺少足够过程数据，保持低权重渐进修正。")

    labels = {
        "model_aligned": "模型方向基本匹配",
        "strength_bias": "实力判断偏差",
        "matchup_bias": "对位判断偏差",
        "random_event": "随机/特殊事件偏差",
    }
    return {
        "primary_bias": primary,
        "primary_bias_cn": labels[primary],
        "should_update_strength": should_update,
        "weight": weight,
        "event_flags": flags,
        "notes": notes,
    }


def _postmatch_review(audit: dict, fixture: dict, insights: dict | None) -> dict:
    stage = audit["stage"]
    home, away = audit["match"]["home"], audit["match"]["away"]
    entry = _insight_entry(home, away, insights)
    evidence = []
    if entry:
        for row in entry.get("prior_matches", [])[:4]:
            bits = [zh(row.get("team"))]
            if row.get("xg_for") is not None:
                bits.append(f"xG {float(row['xg_for']):.1f}")
            if row.get("shots_for") is not None:
                bits.append(f"射门 {int(row['shots_for'])}")
            if row.get("possession") is not None:
                bits.append(f"控球 {float(row['possession']) * 100:.0f}%")
            if len(bits) > 1:
                evidence.append(" / ".join(bits))
        evidence += [str(x).rstrip("。") + "。" for x in entry.get("tactical_notes", [])[:2]]
        evidence += [str(x).rstrip("。") + "。" for x in entry.get("availability_notes", [])[:2]]
        deep = entry.get("deep_analysis") or {}
        if deep.get("text"):
            evidence.append(str(deep["text"]).strip())
    if not evidence:
        evidence.append("暂无联网补全的xG、射门、控球或阵容数据，本场复盘仅基于比分、模型概率与市场基准。")

    factors = []
    m, mk = audit["model"], audit["market"]
    if m.get("hit"):
        factors.append("赛前模型方向与实际赛果一致，可小幅强化相关攻防假设。")
    else:
        factors.append("赛前模型方向与实际赛果偏离，应检查是否低估胜方真实强度或高估热门稳定性。")
    if mk.get("enabled"):
        if mk.get("hit") and not m.get("hit"):
            factors.append("市场比模型更贴近实际结果，后续需关注临场赔率是否提前反映阵容或战术信息。")
        elif m.get("hit") and not mk.get("hit"):
            factors.append("模型比市场更贴近实际结果，可保留模型分歧信号但仍需复核风险来源。")
    if stage["type"] == "knockout":
        factors.append("淘汰赛样本少且平局会进入加时/点球，应单独记录点球风险、保守节奏与抗压能力。")
    factors.append("红牌、伤退、点球大战等特殊事件应作为独立事件因子，不直接等同于常规实力变化。")

    if stage["type"] == "knockout":
        summary = (f"{stage['label']}复盘：{audit['match']['home_cn']} {audit['match']['score']} "
                   f"{audit['match']['away_cn']}，实际为{audit['actual_cn']}；{audit['verdict']}")
    else:
        summary = audit["verdict"]
    update_signal = _model_update_signal(audit, fixture, entry)
    return {
        "enabled": True,
        "stage": stage["label"],
        "data_as_of": entry.get("data_as_of") if entry else None,
        "summary": summary,
        "evidence": evidence,
        "correction_factors": factors,
        "model_update": update_signal,
        "model_feedback": ("球队实力修正采用渐进式权重：攻防效率、防守稳定性、强强对话、淘汰赛抗压与点球风险"
                           "分开记录，避免单场爆冷或极端事件造成过拟合。"),
    }


def _source_for_match(team_adj: dict, home: str, away: str, score: str) -> dict | None:
    detail = f"{home} {score} {away}"
    for src in (team_adj or {}).get("sources", []):
        if src.get("type") == "result" and src.get("detail") == detail:
            return src
    return None


def _learning_feedback(home: str, away: str, score: str | None, adjustments: dict | None) -> dict:
    if not score:
        return {"enabled": False, "reason": "未完赛或无比分"}
    adjustments = adjustments if adjustments is not None else {}
    home_src = _source_for_match(adjustments.get(home, {}), home, away, score)
    away_src = _source_for_match(adjustments.get(away, {}), home, away, score)
    src = home_src or away_src
    if not src:
        return {"enabled": False, "reason": "暂无该场赛后学习记录；请先执行一键全量刷新/重算赛中实力修正。"}

    def team_delta(team: str, side: str, source: dict | None) -> dict:
        return {
            "team": team,
            "team_cn": zh(team),
            "side": side,
            "delta_elo": (source or {}).get("delta_elo"),
            "delta_attack": (source or {}).get("delta_attack"),
            "delta_defense": (source or {}).get("delta_defense"),
        }

    actual = src.get("actual", {})
    predicted = src.get("predicted", {})
    errors = src.get("errors", {})
    home_delta = team_delta(home, "home", home_src)
    away_delta = team_delta(away, "away", away_src)
    outcome_text = "命中" if not errors.get("outcome_missed") else "未命中"
    pred_1x2 = predicted.get("outcomes_1x2") or {}
    pred_pick = max(pred_1x2, key=pred_1x2.get) if pred_1x2 else None
    summary = (
        f"{zh(home)} vs {zh(away)}：模型赛前倾向"
        f"{_OUTCOME_CN.get(pred_pick, '—')}，"
        f"实际{_OUTCOME_CN.get(actual.get('outcome'), '—')}，赛果方向{outcome_text}；"
        f"总进球预测 {predicted.get('total_goals', '—')}，实际 {actual.get('total_goals', '—')}，"
        f"误差 {errors.get('total_goals', '—')}。"
    )
    return {
        "enabled": True,
        "summary": summary,
        "actual": actual,
        "predicted": predicted,
        "errors": errors,
        "goal_calibration": src.get("goal_calibration", {}),
        "style": src.get("style", {}),
        "weights": {
            "final": src.get("weight"),
            "event": src.get("event_weight"),
            "process": src.get("process_weight"),
            "time_decay": src.get("time_decay"),
            "notes": src.get("weight_notes", []),
        },
        "teams": {"home": home_delta, "away": away_delta},
    }


def match_audit(model, fixture, *, neutral=True, fixtures=None, snapshot=None, conn=None,
                insights=None, adjustments=None) -> dict:
    """单场赛后审计三方对比。fixture 需含 home_team/away_team/home_score/away_score/date_utc。"""
    home, away = fixture["home_team"], fixture["away_team"]
    hs, as_ = fixture.get("home_score"), fixture.get("away_score")
    actual = actual_outcome(hs, as_)

    m_probs, m_src, locked_at = _model_probs(model, home, away, neutral, fixture, fixtures, snapshot)
    mk_probs, captured_at, mk_odds = _market_probs(home, away, fixture.get("date_utc"), conn=conn)

    m_pick = _pick(m_probs)
    rows = [{
        "outcome": _OUTCOME_CN[k], "key": k,
        "model_prob": round(m_probs[k], 4),
        "market_prob": (round(mk_probs[k], 4) if mk_probs else None),
        "is_actual": (k == actual),
    } for k in ("home", "draw", "away")]

    out = {
        "match": {"home": home, "away": away, "home_cn": zh(home), "away_cn": zh(away),
                  "match_number": fixture.get("match_number"),
                  "kickoff_utc": fixture.get("date_utc"),
                  "score": (f"{hs}-{as_}" if actual else None)},
        "stage": _stage(fixture),
        "finished": actual is not None,
        "actual": actual,
        "actual_cn": (_OUTCOME_CN.get(actual) if actual else None),
        "model": {
            "source": m_src, "locked_at": locked_at,
            "probs": {k: round(v, 4) for k, v in m_probs.items()},
            "pick": m_pick, "pick_cn": _OUTCOME_CN[m_pick],
            "hit": (m_pick == actual if actual else None),
            "prob_on_actual": (round(m_probs[actual], 4) if actual else None),
        },
        "rows": rows,
    }
    if mk_probs:
        mk_pick = _pick(mk_probs)
        out["market"] = {
            "enabled": True, "captured_at": captured_at, "odds": mk_odds,
            "probs": {k: round(v, 4) for k, v in mk_probs.items()},
            "pick": mk_pick, "pick_cn": _OUTCOME_CN[mk_pick],
            "hit": (mk_pick == actual if actual else None),
            "prob_on_actual": (round(mk_probs[actual], 4) if actual else None),
        }
    else:
        out["market"] = {"enabled": False,
                         "reason": "无赛前赔率快照（未在赛前拉取或缺 ODDS_API_KEY）"}
    out["verdict"] = _verdict(out)
    out["postmatch_review"] = _postmatch_review(out, fixture, insights) if actual else {"enabled": False}
    if adjustments is None:
        try:
            from wc2026.analysis.adjustments import load_adjustments
            adjustments = load_adjustments()
        except Exception:
            adjustments = {}
    out["learning"] = _learning_feedback(home, away, out["match"]["score"], adjustments) if actual else {
        "enabled": False,
        "reason": "未完赛或无比分",
    }
    return out


def _verdict(a: dict) -> str:
    """规则生成命中/偏差说明（不编造，仅基于概率与赛果）。"""
    if not a["finished"]:
        return "未完赛，暂不审计。"
    actual_cn, m = a["actual_cn"], a["model"]
    parts = []
    if m["hit"]:
        parts.append(f"模型命中（看好{m['pick_cn']} {m['probs'][m['pick']]:.0%}，实际{actual_cn}）")
    else:
        parts.append(f"模型未中（最看好{m['pick_cn']} {m['probs'][m['pick']]:.0%}，"
                     f"实际{actual_cn}，模型给实际仅 {m['prob_on_actual']:.0%}）")
    mk = a["market"]
    if mk.get("enabled"):
        parts.append(f"市场{'命中' if mk['hit'] else '亦未中'}（隐含最高{mk['pick_cn']}）")
        pa_m, pa_k = m["prob_on_actual"], mk["prob_on_actual"]
        if pa_m is not None and pa_k is not None:
            if pa_m > pa_k + 0.02:
                parts.append("模型对实际结果概率高于市场，校准更好")
            elif pa_k > pa_m + 0.02:
                parts.append("市场对实际结果概率高于模型，模型偏差更大")
            else:
                parts.append("模型与市场对实际结果判断接近")
    else:
        parts.append("无赛前赔率，未做市场对比")
    return "；".join(parts) + "。"


def audit_summary(model, fixtures, *, neutral=True, snapshots=None, conn=None, insights=None) -> dict:
    """所有已完赛 predictable 比赛汇总：模型/市场 Brier/LogLoss/命中率 + 对比 + 逐场列表。

    snapshots: {match_number: snapshot_dict}（赛前锁定）；缺失的场次模型用事后复算。"""
    snapshots = snapshots or {}
    finished = [f for f in fixtures
                if actual_outcome(f.get("home_score"), f.get("away_score")) is not None]
    audits, model_recs, market_recs = [], [], []
    n_snapshot = 0
    for f in finished:
        a = match_audit(model, f, neutral=neutral, fixtures=fixtures,
                        snapshot=snapshots.get(f.get("match_number")), conn=conn,
                        insights=insights)
        audits.append(a)
        model_recs.append({**a["model"]["probs"], "actual": a["actual"]})
        if a["model"]["source"] == "赛前锁定快照":
            n_snapshot += 1
        if a["market"].get("enabled"):
            market_recs.append({**a["market"]["probs"], "actual": a["actual"]})

    model_metrics = prob_metrics(model_recs)
    market_metrics = prob_metrics(market_recs) if market_recs else {"n": 0}
    return {
        "n_finished": len(finished),
        "n_with_snapshot": n_snapshot,
        "n_with_market": len(market_recs),
        "scope": _scope(audits),
        "model_metrics": model_metrics,
        "market_metrics": market_metrics,
        "comparison": _compare(model_metrics, market_metrics),
        "matches": audits,
        "note": ("模型概率优先用赛前锁定快照；无快照的场次用当前模型事后复算"
                 "（模型已含该场赛果，存在数据泄漏，仅供参考）。市场仅作基准对比，不参与建模。"),
    }


def _scope(audits: list[dict]) -> dict:
    group_stage = [a for a in audits if a.get("stage", {}).get("type") != "knockout"]
    knockout = [a for a in audits if a.get("stage", {}).get("type") == "knockout"]
    return {
        "group_stage_finished": len(group_stage),
        "knockout_finished": len(knockout),
        "knockout_reviewed": sum(1 for a in knockout if a.get("postmatch_review", {}).get("enabled")),
    }


def _compare(mm: dict, km: dict) -> dict:
    """模型 vs 市场指标对比（§11.3：赔率验证偏差与实际结果相关性的产品化呈现）。"""
    if not km or km.get("n", 0) == 0:
        return {"enabled": False, "reason": "无可比对的市场样本（赛前赔率快照不足）"}
    out = {"enabled": True, "n": km["n"]}
    for key in ("log_loss", "brier", "accuracy"):
        mv, kv = mm.get(key), km.get(key)
        better = None
        if mv is not None and kv is not None:
            if key == "accuracy":
                better = "模型" if mv > kv else ("市场" if kv > mv else "持平")
            else:                                # log_loss / brier 越低越好
                better = "模型" if mv < kv else ("市场" if kv < mv else "持平")
        out[key] = {"model": mv, "market": kv, "better": better}
    return out
