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


def match_audit(model, fixture, *, neutral=True, fixtures=None, snapshot=None, conn=None) -> dict:
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


def audit_summary(model, fixtures, *, neutral=True, snapshots=None, conn=None) -> dict:
    """所有已完赛 predictable 比赛汇总：模型/市场 Brier/LogLoss/命中率 + 对比 + 逐场列表。

    snapshots: {match_number: snapshot_dict}（赛前锁定）；缺失的场次模型用事后复算。"""
    snapshots = snapshots or {}
    finished = [f for f in fixtures
                if actual_outcome(f.get("home_score"), f.get("away_score")) is not None]
    audits, model_recs, market_recs = [], [], []
    n_snapshot = 0
    for f in finished:
        a = match_audit(model, f, neutral=neutral, fixtures=fixtures,
                        snapshot=snapshots.get(f.get("match_number")), conn=conn)
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
        "model_metrics": model_metrics,
        "market_metrics": market_metrics,
        "comparison": _compare(model_metrics, market_metrics),
        "matches": audits,
        "note": ("模型概率优先用赛前锁定快照；无快照的场次用当前模型事后复算"
                 "（模型已含该场赛果，存在数据泄漏，仅供参考）。市场仅作基准对比，不参与建模。"),
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
