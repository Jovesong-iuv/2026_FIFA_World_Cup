"""FastAPI 后端：赛程 / 预测 / 证据 / 新闻 / 刷新。

启动： uvicorn wc2026.api.app:app --reload
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException

from wc2026.analysis import evidence
from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.data.ingest import ingest_international_results
from wc2026.data.sources import news
from wc2026.data.sources.fixtures_2026 import fetch_and_store_fixtures
from wc2026.data.team_names import to_lib, zh
from wc2026.llm import provider, reasoning
from wc2026.markets import derive
from wc2026.models.predictor import get_model, train_and_save

app = FastAPI(title="2026 World Cup Predictor", version="0.2.0")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _predict(home: str, away: str, neutral: bool, use_context: bool = False) -> dict:
    home, away = to_lib(home), to_lib(away)
    model = get_model()
    missing = [t for t in (home, away) if not model.has_team(t)]
    if missing:
        raise HTTPException(status_code=404, detail=f"球队不在训练集中: {missing}")
    context_notes: list = []
    if use_context:
        from wc2026.analysis import context
        adj = context.adjusted_prediction(model, home, away, neutral)
        mat, (lam, mu), context_notes = adj["matrix"], adj["exp_goals"], adj["notes"]
    else:
        mat = model.score_matrix(home, away, neutral)
        lam, mu = model.expected_goals(home, away, neutral)
    markets = derive.summarize(mat)
    reason = reasoning.generate_reason(model, home, away, neutral, markets)
    return {
        "home": home, "away": away, "home_zh": zh(home), "away_zh": zh(away),
        "neutral": neutral,
        "expected_goals": {"home": round(lam, 3), "away": round(mu, 3)},
        "score_matrix": mat.round(5).tolist(),
        "markets": markets,
        "reason": reason,
        "context_notes": context_notes,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm_enabled": settings.llm_enabled,
            "llm_configured": bool(settings.llm_api_key)}


@app.get("/llm/ping")
def llm_ping() -> dict:
    return {"available": provider.is_available()}


@app.get("/teams")
def teams() -> dict:
    return {"teams": get_model().teams}


@app.get("/fixtures")
def fixtures(predictable_only: bool = False, group: str | None = None) -> dict:
    q = ("SELECT match_number, round_number, date_utc, home_team, away_team, "
         "group_name, location, predictable, home_score, away_score FROM fixtures")
    conds, params = [], []
    if predictable_only:
        conds.append("predictable=1")
    if group:
        conds.append("group_name=?")
        params.append(group)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY date_utc, match_number"
    with get_conn() as conn:
        rows = conn.execute(q, params).fetchall()
    return {"fixtures": [{
        "match_number": r["match_number"], "round": r["round_number"],
        "date_utc": r["date_utc"], "home": r["home_team"], "away": r["away_team"],
        "home_zh": zh(r["home_team"]), "away_zh": zh(r["away_team"]),
        "group": r["group_name"], "location": r["location"],
        "predictable": bool(r["predictable"]),
        "score": (f"{r['home_score']}-{r['away_score']}" if r["home_score"] is not None else None),
    } for r in rows]}


@app.get("/predict")
def predict(home: str, away: str, neutral: bool = True, save: bool = True,
            use_context: bool = False) -> dict:
    result = _predict(home, away, neutral, use_context)
    if save:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO predictions(created_at, home_team, away_team, model, payload) "
                "VALUES (?,?,?,?,?)",
                (_now(), result["home"], result["away"], "dixon_coles",
                 json.dumps({"expected_goals": result["expected_goals"],
                             "markets": result["markets"],
                             "reason": result["reason"]}, ensure_ascii=False)),
            )
    return result


@app.get("/intelligence")
def intelligence_ep(home: str, away: str, neutral: bool = True,
                    match_number: int | None = None,
                    odds_home: float | None = None, odds_draw: float | None = None,
                    odds_away: float | None = None) -> dict:
    """单场智能体报告（MatchIntelligenceReport）：九维度 + 组合模型预测 + 赔率后验 + 风险/总结。

    赔率仅做后验校验，不进入预测主链。可选 match_number 加载赛程/场馆与末轮战意。
    """
    from wc2026.analysis.intelligence import build_report
    h, a = to_lib(home), to_lib(away)
    model = get_model()
    missing = [t for t in (h, a) if not model.has_team(t)]
    if missing:
        raise HTTPException(status_code=404, detail=f"球队不在训练集中: {missing}")

    fixture = fixtures = group_state = None
    if match_number is not None:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT match_number, round_number, date_utc, home_team, away_team, "
                "group_name, location, home_score, away_score FROM fixtures WHERE match_number=?",
                (match_number,)).fetchone()
            frows = conn.execute(
                "SELECT match_number, date_utc, home_team, away_team, location "
                "FROM fixtures WHERE predictable=1").fetchall()
        fixture = dict(row) if row else None
        fixtures = [dict(r) for r in frows]
        if fixture and fixture.get("group_name"):
            try:
                from wc2026.analysis import groups as _groups, motivation as _motiv
                states = _motiv.derive_group_states(_groups.load_group_data(model))
                group_state = _motiv.group_state_for(states, fixture["group_name"], h, a)
            except Exception:
                group_state = None

    odds_1x2 = None
    if all(o and o > 1.0 for o in (odds_home, odds_draw, odds_away)):
        odds_1x2 = {"home": odds_home, "draw": odds_draw, "away": odds_away}

    return build_report(model, h, a, neutral, fixture=fixture, fixtures=fixtures,
                        odds_1x2=odds_1x2, group_state=group_state)


@app.get("/evidence")
def evidence_ep(home: str, away: str) -> dict:
    h, a = to_lib(home), to_lib(away)
    return {"home": h, "away": a, "home_zh": zh(h), "away_zh": zh(a),
            "h2h": evidence.head_to_head(h, a),
            "home_form": evidence.recent_form(h),
            "away_form": evidence.recent_form(a)}


@app.get("/news")
def news_ep(home: str, away: str, analyze: bool = False) -> dict:
    h, a = to_lib(home), to_lib(away)
    items = news.fetch_for_teams([h, a])
    out: dict = {"items": items}
    if analyze:
        out["analysis"] = news.analyze_news(h, a, items)
    return out


@app.get("/history")
def history(home: str, away: str, limit: int = 20) -> dict:
    h, a = to_lib(home), to_lib(away)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT created_at, payload FROM predictions "
            "WHERE home_team=? AND away_team=? ORDER BY id DESC LIMIT ?",
            (h, a, limit),
        ).fetchall()
    return {"home": h, "away": a,
            "snapshots": [{"created_at": r["created_at"], **json.loads(r["payload"])} for r in rows]}


@app.post("/refresh")
def refresh() -> dict:
    """一键全量刷新：历史数据 + 重训模型 + 赛程。"""
    stats = ingest_international_results()
    model = train_and_save()
    try:
        fx = fetch_and_store_fixtures()
    except Exception as exc:
        fx = {"error": str(exc)}
    return {"data": stats, "teams": len(model.teams), "fixtures": fx, "refreshed_at": _now()}


@app.get("/backtest")
def backtest_ep(years: str = "2014,2018,2022") -> dict:
    """历届世界杯样本外回测（每届需训练，较慢）。"""
    from wc2026.backtest.runner import backtest_world_cup
    return {"results": [backtest_world_cup(y) for y in years.split(",")]}


@app.get("/odds/sports")
def odds_sports() -> dict:
    """列出赔率源 sports，筛出世界杯相关（需 ODDS_API_KEY）。"""
    from wc2026.data.sources import odds_api
    try:
        sports = odds_api.list_sports()
    except odds_api.OddsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    wc = [s for s in sports if "world_cup" in s.get("key", "").lower() or "world cup" in s.get("title", "").lower()]
    return {"world_cup_sports": wc, "total_sports": len(sports)}


@app.get("/value/scan")
def value_scan(neutral: bool = True, blend: float = 0.5) -> dict:
    """拉全部世界杯赔率并扫描价值盘（需 ODDS_API_KEY）。blend=模型权重，<1 向市场收缩滤假价值。"""
    from wc2026.data.sources import odds_api
    from wc2026.markets import value as value_mod
    try:
        odds_map = odds_api.fetch_h2h_odds()
    except odds_api.OddsError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    scan = value_mod.scan_value(get_model(), odds_map, neutral=neutral, blend=blend)
    for r in scan:
        r["home_zh"], r["away_zh"] = zh(r["home"]), zh(r["away"])
    return {"value_bets": scan, "n_matches": len(odds_map)}
