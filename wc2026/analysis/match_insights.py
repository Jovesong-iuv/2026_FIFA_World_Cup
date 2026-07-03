"""分场分析：把本届已赛统计补充成大屏可读的赛前推演。

数据来自 data/match_insights.json。这里不抓取、不编造；缺数据时明确降级。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from wc2026.config import settings
from wc2026.analysis import groups
from wc2026.data.team_names import zh
from wc2026.data import squads
from wc2026.data.db import get_conn
from wc2026.data.sources import fbref, fotmob, news

INSIGHTS_PATH = settings.data_dir / "match_insights.json"


def load_insights(path=INSIGHTS_PATH) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"matches": {}}


def save_insights(data: dict, path=INSIGHTS_PATH) -> None:
    settings.ensure_dirs()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _key(home: str, away: str) -> str:
    return f"{home}::{away}"


def _match_entry(home: str, away: str, insights: dict) -> dict | None:
    matches = (insights or {}).get("matches", {})
    return matches.get(_key(home, away)) or matches.get(_key(away, home))


def _pct(v) -> str:
    return f"{float(v) * 100:.0f}%"


def _prob(v) -> str:
    return f"{float(v):.0%}" if v is not None else "—"


def _prior_sentence(row: dict) -> str:
    source = str(row.get("source") or "")
    if not row.get("opponent") and "聚合" in source:
        bits = [f"{zh(row.get('team'))}本届聚合数据"]
    else:
        bits = [f"{zh(row.get('team'))}首轮"]
    if row.get("score"):
        bits.append(f"面对{zh(row.get('opponent'))} {row['score']}")
    elif row.get("opponent"):
        bits.append(f"面对{zh(row.get('opponent'))}")
    stats = []
    if row.get("possession") is not None:
        stats.append(f"{_pct(row['possession'])}控球")
    if row.get("shots_for") is not None:
        stats.append(f"{int(row['shots_for'])}次射门")
    if row.get("xg_for") is not None:
        stats.append(f"约{row['xg_for']:.1f}预期进球")
    if source:
        stats.append(source)
    if row.get("shots_against") is not None:
        stats.append(f"承受{int(row['shots_against'])}次射门")
    if stats:
        bits.append("，" + "、".join(stats))
    takeaway = (row.get("takeaway") or "").rstrip("。")
    if takeaway and not (row.get("shots_against") is not None and takeaway.startswith("承受")):
        bits.append("，" + takeaway)
    elif takeaway:
        bits.append("，" + takeaway.replace("承受大量射门，", "", 1))
    return "".join(bits).rstrip("。") + "。"


def _shooting_row(team: str, data: dict | None) -> dict | None:
    if not data:
        return None
    row = {"team": team, "source": "FBref聚合"}
    if data.get("shots") is not None:
        row["shots_for"] = data["shots"]
    if data.get("xg") is not None:
        row["xg_for"] = data["xg"]
    notes = []
    if data.get("goals") is not None:
        notes.append(f"进球 {data['goals']}")
    if data.get("sot") is not None:
        notes.append(f"射正 {data['sot']}")
    row["takeaway"] = "；".join(notes) if notes else "该数据为球队聚合射门/xG，不等同于单场技术统计。"
    return row


def _fotmob_stats_row(team: str, data: dict | None) -> dict | None:
    if not data:
        return None
    row = {"team": team, "source": "FotMob本届聚合"}
    if data.get("possession") is not None:
        row["possession"] = data["possession"]
    if data.get("xg") is not None:
        row["xg_for"] = data["xg"]
    notes = []
    if data.get("goals_per_match") is not None:
        notes.append(f"场均进球 {data['goals_per_match']}")
    if data.get("shots_on_target_per_match") is not None:
        notes.append(f"场均射正 {data['shots_on_target_per_match']}")
    if data.get("xga") is not None:
        notes.append(f"累计预期失球 {data['xga']}")
    row["takeaway"] = "；".join(notes) if notes else "该数据为球队本届聚合统计，不等同于单场技术统计。"
    return row


def _fotmob_stats_for_team(team: str) -> dict | None:
    with get_conn() as conn:
        fm_id, fm_name = squads._get_fm_id(conn, team)
    return fotmob.fetch_team_stats(fm_id, fm_name)


def _profile_notes(home: str, away: str) -> list[str]:
    try:
        profiles = json.loads((settings.data_dir / "team_profiles.json").read_text(encoding="utf-8"))
    except Exception:
        return []
    notes = []
    for team in (home, away):
        p = profiles.get(team) or {}
        style = p.get("style_detail") or p.get("background")
        formation = p.get("formation")
        if style or formation:
            prefix = f"{zh(team)}本地球队画像"
            if formation and style:
                notes.append(f"{prefix}：{formation}，{style}。")
            elif formation:
                notes.append(f"{prefix}：预计阵型 {formation}。")
            else:
                notes.append(f"{prefix}：{style}。")
    return notes


def _web_search_stats(team: str) -> dict | None:
    """联网搜索后备：当 FBref/FotMob 均失败时，用搜索引擎+LLM 获取球队统计摘要。"""
    from wc2026.data.sources import web_search as ws
    from wc2026.llm import provider as llm

    team_zh = zh(team)
    results = ws.web_search(
        f"{team_zh} 2026世界杯 射门 控球 xG 数据 统计",
        max_results=5, timeout=20,
    )
    if not results:
        return None

    snippets = "\n".join(
        f"- {r['title']}: {r['snippet'][:120]}" for r in results if r.get("snippet")
    )
    if not snippets:
        return None

    prompt = (
        f"以下是关于「{team_zh}」在 2026 世界杯的搜索结果摘要。\n\n{snippets}\n\n"
        "请从中提取该队在本届世界杯的统计数据（如果有的话），输出 JSON：\n"
        '{"goals":数字或null, "matches_played":数字或null, "xg":数字或null, '
        '"possession_pct":数字或null, "shots_per_game":数字或null, '
        '"takeaway":"一句话概括"}\n'
        "只提取搜索结果中明确提到的数据，没有的填 null，不要编造。"
    )
    try:
        text = llm.chat(prompt, max_tokens=400, temperature=0.2, timeout=30)
        import json as _json
        data = _json.loads(text.strip().strip("`").strip("json").strip())
        data["source"] = "联网搜索+LLM"
        return data
    except Exception:
        return None


def _current_group_rows(home: str, away: str, model) -> list[dict]:
    if model is None:
        return []
    gd = groups.load_group_data(model)
    standings = groups.compute_standings(gd) if gd else {}
    out = []
    for group, rows in standings.items():
        wanted = [r for r in rows if r["team"] in {home, away}]
        if not wanted:
            continue
        teams = gd[group]["teams"]
        for r in wanted:
            form = []
            for hi, ai, hs, as_ in gd[group]["matches"]:
                if hs is None or as_ is None:
                    continue
                h, a = teams[hi], teams[ai]
                if r["team"] not in {h, a}:
                    continue
                gf = hs if r["team"] == h else as_
                ga = as_ if r["team"] == h else hs
                form.append("W" if gf > ga else ("D" if gf == ga else "L"))
            out.append({
                "team": r["team"],
                "source": "本地小组赛战绩",
                "takeaway": (
                    f"小组赛{r['w']}胜{r['d']}平{r['l']}负，"
                    f"进{r['gf']}失{r['ga']}，积分{r['pts']}，"
                    f"当前{group.replace('Group ', '')}组第{r['rank']}，"
                    f"近三场走势{''.join(form[-3:]) or '—'}。"
                ),
            })
        break
    return out


def refresh_match_insight(home: str, away: str, *, path=INSIGHTS_PATH, model=None) -> dict:
    """联网补全本场分场分析缓存。

    数据源优先级：FBref → FotMob → 联网搜索+LLM。
    新闻源：Google News(中+英) → 英文RSS → 联网搜索后备 → 深度搜索+LLM综合分析。
    单个源失败不影响其他源写入。
    """
    data = load_insights(path)
    data.setdefault("matches", {})
    entry = data["matches"].setdefault(_key(home, away), {})
    entry["data_as_of"] = datetime.now(timezone.utc).date().isoformat()
    errors: list[str] = []

    # --- 1) 射门/统计数据：FBref → FotMob → 联网搜索 ---
    rows = []
    for team in (home, away):
        got_data = False
        try:
            row = _shooting_row(team, fbref.fetch_team_shooting(team))
            if row:
                rows.append(row)
                got_data = True
        except Exception as exc:
            errors.append(f"FBref {zh(team)}: {exc}")

        if not got_data:
            try:
                row = _fotmob_stats_row(team, _fotmob_stats_for_team(team))
                if row:
                    rows.append(row)
                    got_data = True
            except Exception as fm_exc:
                errors.append(f"FotMob统计 {zh(team)}: {fm_exc}")

        if not got_data:
            # 联网搜索后备
            try:
                ws_data = _web_search_stats(team)
                if ws_data:
                    row = {
                        "team": team,
                        "source": ws_data.get("source", "联网搜索"),
                    }
                    if ws_data.get("goals") is not None:
                        row["shots_for"] = ws_data["goals"]
                    if ws_data.get("xg") is not None:
                        row["xg_for"] = ws_data["xg"]
                    if ws_data.get("takeaway"):
                        row["takeaway"] = ws_data["takeaway"]
                    rows.append(row)
            except Exception as ws_exc:
                errors.append(f"联网搜索 {zh(team)}: {ws_exc}")

    rows = [r for r in rows if r]
    if len(rows) < 2:
        known = {r.get("team") for r in rows}
        rows.extend(r for r in _current_group_rows(home, away, model) if r.get("team") not in known)
    if rows:
        entry["prior_matches"] = rows

    # --- 2) 战术/阵容/伤停：FotMob → 本地画像 ---
    tactical_notes = []
    availability_notes = []
    for team in (home, away):
        try:
            sq = squads.refresh_fm_squad(team)
            if sq.get("formation"):
                tactical_notes.append(f"{zh(team)} FotMob最近阵型：{sq['formation']}。")
            if sq.get("injured"):
                availability_notes.append(f"{zh(team)} FotMob伤停/缺阵人数：{sq['injured']}。")
        except Exception as exc:
            errors.append(f"FotMob {zh(team)}: {exc}")

    # --- 3) 新闻 + 深度搜索 ---
    news_items = []
    try:
        news_items = news.fetch_for_teams([home, away], limit=8)
        if news_items:
            titles = "；".join(i.get("title", "") for i in news_items[:3] if i.get("title"))
            if titles:
                availability_notes.append("相关新闻标题：" + titles)
    except Exception as exc:
        errors.append(f"News: {exc}")

    # 深度搜索+LLM综合分析（当常规新闻不足 4 条时触发）
    if len(news_items) < 4:
        try:
            deep = news.deep_search_and_analyze(home, away, existing_items=news_items)
            if deep and deep.get("text"):
                entry["deep_analysis"] = {
                    "text": deep["text"],
                    "sources": deep.get("sources", []),
                    "source": deep.get("source", "deep_search"),
                }
                availability_notes.append(
                    f"深度搜索情报（来源：{', '.join(deep.get('sources', ['联网']))}）"
                )
        except Exception as exc:
            errors.append(f"深度搜索: {exc}")

    if tactical_notes:
        entry["tactical_notes"] = tactical_notes
    else:
        fallback_notes = _profile_notes(home, away)
        if fallback_notes:
            entry["tactical_notes"] = fallback_notes
    if availability_notes:
        entry["availability_notes"] = availability_notes
    entry.setdefault("market_view", {})
    entry["refresh_errors"] = errors
    save_insights(data, path)
    return {"ok": not errors, "errors": errors, "entry": entry}


def build_match_analysis(home: str, away: str, report: dict, insights: dict | None = None) -> dict:
    """返回大屏分场分析块。

    report 为 intelligence/build_dashboard_payload 中的报告或 payload 片段，至少含 prediction。
    """
    insights = load_insights() if insights is None else insights
    entry = _match_entry(home, away, insights)
    pred = (report or {}).get("prediction", {})
    margins = pred.get("win_margins", {})
    top = pred.get("top_scores") or pred.get("top_scorelines") or []
    if not entry:
        return {
            "available": False,
            "text": "暂无本场已赛控球、射门、xG 等补充数据；当前仅展示模型概率与常规风险提示。",
            "data_as_of": None,
            "markets": margins,
            "recommendations": {},
        }

    parts = [_prior_sentence(r) for r in entry.get("prior_matches", [])]
    parts += [n.rstrip("。") + "。" for n in entry.get("availability_notes", [])]
    parts += [n.rstrip("。") + "。" for n in entry.get("tactical_notes", [])]

    # 深度搜索情报（联网搜索+LLM综合分析）
    deep = entry.get("deep_analysis")
    if deep and deep.get("text"):
        deep_text = deep["text"].strip()
        if deep_text:
            parts.append(f"【深度情报】{deep_text}")

    if entry.get("refresh_errors"):
        parts.append("数据源提示：" + "；".join(entry["refresh_errors"][:3]) + "。")

    market_view = entry.get("market_view", {})
    home_zh = zh(home)
    market_bits = []
    if margins:
        market_bits.append(
            f"{home_zh}赢3球或以上：约 {_prob(margins.get('home_by_3_plus'))}；"
            f"{home_zh}赢4球或以上：约 {_prob(margins.get('home_by_4_plus'))}。"
        )
    if market_view.get("primary"):
        market_bits.append(f"主推：{market_view['primary']}。")
    if market_view.get("avoid"):
        market_bits.append(f"不建议：{market_view['avoid']}。")
    if market_view.get("scoreline_primary"):
        sec = f"，次选{market_view['scoreline_secondary']}" if market_view.get("scoreline_secondary") else ""
        market_bits.append(f"波胆：{market_view['scoreline_primary']}{sec}。")
    market_bits += [n.rstrip("。") + "。" for n in market_view.get("notes", [])]
    if top and not market_view.get("scoreline_primary"):
        market_bits.append("模型最可能比分：" + "、".join(f"{r['score']}({_prob(r.get('probability') or r.get('prob'))})"
                                                       for r in top[:3]) + "。")

    return {
        "available": True,
        "text": "\n".join(parts + market_bits),
        "data_as_of": entry.get("data_as_of"),
        "markets": margins,
        "recommendations": {
            "primary": market_view.get("primary"),
            "avoid": market_view.get("avoid"),
            "scoreline_primary": market_view.get("scoreline_primary"),
            "scoreline_secondary": market_view.get("scoreline_secondary"),
        },
    }
