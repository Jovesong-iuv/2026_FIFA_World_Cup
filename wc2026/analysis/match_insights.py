"""分场分析：把本届已赛统计补充成大屏可读的赛前推演。

数据来自 data/match_insights.json。这里不抓取、不编造；缺数据时明确降级。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from wc2026.config import settings
from wc2026.data.team_names import zh
from wc2026.data import squads
from wc2026.data.sources import fbref, news

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
    if row.get("source"):
        stats.append(str(row["source"]))
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


def refresh_match_insight(home: str, away: str, *, path=INSIGHTS_PATH) -> dict:
    """联网补全本场分场分析缓存。

    使用现有免费源：FBref 射门/xG聚合、FotMob 阵容/阵型/伤停、新闻标题。
    单个源失败不影响其他源写入。
    """
    data = load_insights(path)
    data.setdefault("matches", {})
    entry = data["matches"].setdefault(_key(home, away), {})
    entry["data_as_of"] = datetime.now(timezone.utc).date().isoformat()
    errors: list[str] = []

    rows = []
    for team in (home, away):
        try:
            rows.append(_shooting_row(team, fbref.fetch_team_shooting(team)))
        except Exception as exc:
            errors.append(f"FBref {zh(team)}: {exc}")
    rows = [r for r in rows if r]
    if rows:
        entry["prior_matches"] = rows

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

    try:
        items = news.fetch_for_teams([home, away], limit=6)
        if items:
            titles = "；".join(i.get("title", "") for i in items[:3] if i.get("title"))
            if titles:
                availability_notes.append("相关新闻标题：" + titles)
    except Exception as exc:
        errors.append(f"News: {exc}")

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
