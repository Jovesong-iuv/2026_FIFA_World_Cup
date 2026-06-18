"""Dashboard bridge payload for the embedded HTML/Chart.js match view.

The bridge keeps the existing Python model as the source of truth and only
adapts data into the reference dashboard's UI-friendly shape.
"""
from __future__ import annotations

import json
from pathlib import Path

from wc2026.analysis import groups, intelligence, ranking, tournament, wc_history
from wc2026.config import settings
from wc2026.data.flags import flag_emoji
from wc2026.data.team_names import zh

PROFILE_PATH = settings.data_dir / "team_profiles.json"
HOSTS = {"Mexico", "Canada", "United States"}


def _load_profiles() -> dict:
    try:
        return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _team_standing(group_rows: list[dict], team: str) -> dict | None:
    return next((r for r in group_rows if r["team"] == team), None)


def _recent_world_cup_results(fixtures: list[dict] | None, team: str, limit: int = 3) -> list[dict]:
    rows = []
    for f in sorted(fixtures or [], key=lambda r: r.get("date_utc") or "", reverse=True):
        if f.get("home_score") is None or f.get("away_score") is None:
            continue
        if team not in {f.get("home_team"), f.get("away_team")}:
            continue
        is_home = f["home_team"] == team
        gf = f["home_score"] if is_home else f["away_score"]
        ga = f["away_score"] if is_home else f["home_score"]
        opp = f["away_team"] if is_home else f["home_team"]
        result = "胜" if gf > ga else ("平" if gf == ga else "负")
        rows.append({
            "date": (f.get("date_utc") or "")[:10],
            "opponent": opp,
            "opponent_cn": zh(opp),
            "score": f"{gf}-{ga}",
            "result": result,
            "group": f.get("group_name") or "",
        })
        if len(rows) >= limit:
            break
    return rows


def _current_wc_record(team: str, fixture: dict | None, fixtures: list[dict] | None,
                       standings: dict) -> dict:
    group = (fixture or {}).get("group_name") or ""
    group_rows = standings.get(group, [])
    row = _team_standing(group_rows, team)
    if row:
        return {
            "group": group,
            "rank": row["rank"],
            "played": row["played"],
            "w": row["w"],
            "d": row["d"],
            "l": row["l"],
            "gf": row["gf"],
            "ga": row["ga"],
            "gd": row["gd"],
            "pts": row["pts"],
            "zone": _standings_zone(row["rank"]),
            "recent": _recent_world_cup_results(fixtures, team),
        }
    played = w = d = l = gf = ga = 0
    for f in fixtures or []:
        if f.get("home_score") is None or f.get("away_score") is None:
            continue
        if team not in {f.get("home_team"), f.get("away_team")}:
            continue
        played += 1
        is_home = f["home_team"] == team
        ts = f["home_score"] if is_home else f["away_score"]
        os_ = f["away_score"] if is_home else f["home_score"]
        gf += ts
        ga += os_
        if ts > os_:
            w += 1
        elif ts == os_:
            d += 1
        else:
            l += 1
    return {
        "group": group,
        "rank": None,
        "played": played,
        "w": w,
        "d": d,
        "l": l,
        "gf": gf,
        "ga": ga,
        "gd": gf - ga,
        "pts": w * 3 + d,
        "zone": "待定区",
        "recent": _recent_world_cup_results(fixtures, team),
    }


def _standings_zone(rank: int | None) -> str:
    if rank in (1, 2):
        return "晋级32强区"
    if rank == 3:
        return "晋级待定区"
    return "淘汰风险区"


def _profile_for(model, team: str, report: dict, fixture: dict | None,
                 standings: dict, fixtures: list[dict] | None, profiles: dict) -> dict:
    prof = profiles.get(team, {})
    record = _current_wc_record(team, fixture, fixtures, standings)
    hist = wc_history.wc_record(team)
    rank, rank_source = ranking.world_rank(model, team)
    return {
        "team": team,
        "name_cn": zh(team),
        "flag": flag_emoji(team),
        "score": report["dimension_summary"]["score_home"]
        if team == report["match"]["home"] else report["dimension_summary"]["score_away"],
        "fifa_rank": rank,
        "rank_source": rank_source,
        "population": prof.get("population") or "—",
        "wc_appearances": prof.get("wc_appearances") or hist.get("editions") or "—",
        "best_achievement": prof.get("best_achievement") or "历史库未提供最佳成绩",
        "formation": prof.get("formation") or "—",
        "style_detail": prof.get("style_detail") or prof.get("background") or "—",
        "background": prof.get("background") or "—",
        "starting_lineup": prof.get("starting_lineup") or "暂无预计首发",
        "training_base": prof.get("training_base") or ((fixture or {}).get("location") or "—"),
        "wc_history": hist,
        "current_record": record,
    }


def _dimensions_map(report: dict) -> dict:
    return {
        "team_a": {d["key"]: round(d["home"] / 10.0, 1) for d in report["dimensions"]},
        "team_b": {d["key"]: round(d["away"] / 10.0, 1) for d in report["dimensions"]},
        "labels": {d["key"]: d["name"] for d in report["dimensions"]},
        "weights": {d["key"]: int(round(d["weight"] * 100)) for d in report["dimensions"]},
    }


def _market_for_dashboard(report: dict) -> dict:
    out = {}
    key_map = {"主胜": "home_win", "平局": "draw", "客胜": "away_win"}
    for item in report["market_check"].get("items", []):
        key = key_map.get(item["market"])
        if not key:
            continue
        out[key] = {
            "market_odds": item["odds"],
            "model_prob": item["model_prob"],
            "implied_prob": item["implied_prob"],
            "deviation": round(item["diff"] * 100, 2),
            "label": item["label"],
        }
    pred = report["prediction"]
    if pred.get("totals"):
        out.setdefault("over_2_5", {
            "market_odds": None,
            "model_prob": pred["totals"].get("over_2_5", 0),
            "implied_prob": None,
            "deviation": None,
            "label": "模型概率",
        })
        out.setdefault("under_2_5", {
            "market_odds": None,
            "model_prob": pred["totals"].get("under_2_5", 0),
            "implied_prob": None,
            "deviation": None,
            "label": "模型概率",
        })
    return out


def _championship_payload(model, n_sims: int = 2000) -> list[dict]:
    gd = groups.load_group_data(model)
    if not gd:
        return []
    sim = tournament.simulate_tournament(model, gd, n_sims=n_sims)
    rows = sorted(sim.items(), key=lambda kv: kv[1]["champion"], reverse=True)
    return [{
        "team": t,
        "team_cn": zh(t),
        "flag": flag_emoji(t),
        "r16": round(v["r16"], 4),
        "final": round(v["final"], 4),
        "champion": round(v["champion"], 4),
    } for t, v in rows[:16]]


def build_dashboard_payload(model, home: str, away: str, neutral: bool = True, *,
                            fixture: dict | None = None, fixtures: list | None = None,
                            odds_1x2: dict | None = None, group_state: dict | None = None,
                            pred: dict | None = None) -> dict:
    report = intelligence.build_report(model, home, away, neutral, fixture=fixture,
                                       fixtures=fixtures, odds_1x2=odds_1x2,
                                       group_state=group_state, pred=pred)
    gd = groups.load_group_data(model)
    standings = groups.compute_standings(gd) if gd else {}
    profiles = _load_profiles()
    p_home = _profile_for(model, home, report, fixture, standings, fixtures, profiles)
    p_away = _profile_for(model, away, report, fixture, standings, fixtures, profiles)
    pred_block = report["prediction"]
    return {
        "match": {
            **report["match"],
            "home_flag": flag_emoji(home),
            "away_flag": flag_emoji(away),
        },
        "teams": {"home": p_home, "away": p_away},
        "dimensions": _dimensions_map(report),
        "prediction": {
            "team_a_win_prob": pred_block["outcomes"]["home"],
            "draw_prob": pred_block["outcomes"]["draw"],
            "team_b_win_prob": pred_block["outcomes"]["away"],
            "lambda_a": pred_block["expected_goals"]["home"],
            "lambda_b": pred_block["expected_goals"]["away"],
            "expected_total_goals": pred_block["expected_goals"]["total"],
            "top_scorelines": pred_block["top_scores"][:3],
            "over_2_5_prob": pred_block["totals"]["over_2_5"],
            "under_2_5_prob": pred_block["totals"]["under_2_5"],
        },
        "odds_validation": _market_for_dashboard(report),
        "summary": report["summary"],
        "risks": report["risks"],
        "championship_odds": _championship_payload(model),
        "generated_at": report["generated_at"],
    }
