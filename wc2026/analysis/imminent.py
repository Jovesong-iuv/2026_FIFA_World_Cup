"""临场刷新与赛前锁定快照（文档 §6.3 / §12 阶段3）。

职责：
- imminent_fixtures：扫描赛程，找出进入 T-window（默认 2 小时）内、尚未开赛的比赛。
- lock_prematch_snapshot：为一场比赛生成 MatchIntelligenceReport，锁定时间戳，
  写入 predictions 表（kind=prematch_lock）并合并导出 data/prematch_snapshots.json
  （线上服务器 DB 为临时文件系统，靠可提交 JSON 持久化，与 wc_results.json 同思路）。
- detect_key_changes：对比上一锁定版与当前版，输出关键变化清单 + 是否需风险升级，
  并生成可注入报告的风险条目（关键球员变化触发重算/风险升级）。

官方首发说明：无免费官方首发 API，lineup_meta 由上层传入可靠替代源（FotMob 等）的
数据等级与时间戳；未确认时报告以「预计首发」降级标注，不做硬性修正（文档原则）。
"""
from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path

from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.analysis.intelligence import build_report, match_phase, _parse_utc, _now_dt

SNAPSHOTS_JSON = settings.data_dir / "prematch_snapshots.json"
_OUTCOME_CN = {"home": "主胜", "draw": "平局", "away": "客胜"}


def imminent_fixtures(fixtures: list, now=None, window_hours: float = 2.0) -> list:
    """未完赛且距开赛 (0, window_hours] 小时内的比赛，按开赛时间升序。

    每项附 `_hours_to_kickoff`，便于上层展示/排序。"""
    now_dt = _now_dt(now)
    out = []
    for f in fixtures:
        if f.get("home_score") is not None:        # 已完赛
            continue
        ko = _parse_utc(f.get("date_utc"))
        if ko is None:
            continue
        hrs = (ko - now_dt).total_seconds() / 3600.0
        if 0 < hrs <= window_hours:
            out.append({**f, "_hours_to_kickoff": round(hrs, 2)})
    out.sort(key=lambda x: x["_hours_to_kickoff"])
    return out


def _snap_from_report(fixture: dict, report: dict, now) -> dict:
    pred = report["prediction"]
    return {
        "match_number": fixture.get("match_number"),
        "home": fixture["home_team"], "away": fixture["away_team"],
        "home_cn": report["match"]["home_cn"], "away_cn": report["match"]["away_cn"],
        "kickoff_utc": fixture.get("date_utc"),
        "locked_at": now or report.get("generated_at"),
        "phase": report.get("phase"),
        "outcomes": pred["outcomes"],
        "expected_goals": pred["expected_goals"],
        "data_quality": report["data_quality"],
        "lineup": report.get("lineup"),
        "confidence": report.get("confidence"),
        "risks": [r for r in report["risks"] if r["level"] in ("高", "中")],
    }


def detect_key_changes(prev: dict | None, curr: dict, *,
                       prob_threshold: float = 0.05, escalate_threshold: float = 0.10) -> dict:
    """对比上一锁定版与当前版。返回 {changed, escalate, changes:[文字], risks:[可注入风险]}。"""
    out = {"changed": False, "escalate": False, "changes": [], "risks": []}
    if not prev:
        return out
    po, co = prev.get("outcomes") or {}, curr.get("outcomes") or {}
    max_diff = 0.0
    for k in ("home", "draw", "away"):
        if k in po and k in co:
            d = co[k] - po[k]
            max_diff = max(max_diff, abs(d))
            if abs(d) >= prob_threshold:
                out["changes"].append(f"{_OUTCOME_CN[k]}概率 {po[k]:.0%}→{co[k]:.0%}（{d:+.0%}）")
    pl = (prev.get("lineup") or {}).get("confidence")
    cl = (curr.get("lineup") or {}).get("confidence")
    if cl and pl != cl:
        out["changes"].append(f"首发数据等级 {pl or '—'}→{cl}")
    pq = (prev.get("data_quality") or {}).get("score")
    cq = (curr.get("data_quality") or {}).get("score")
    if pq is not None and cq is not None and pq - cq >= 0.1:
        out["changes"].append(f"数据完整度下降 {pq:.0%}→{cq:.0%}")
    ph = sum(1 for r in (prev.get("risks") or []) if r.get("level") == "高")
    ch = sum(1 for r in (curr.get("risks") or []) if r.get("level") == "高")
    if ch > ph:
        out["changes"].append(f"高风险项增加 {ph}→{ch}")
        out["escalate"] = True
    if max_diff >= escalate_threshold:
        out["escalate"] = True
    out["changed"] = bool(out["changes"])
    src = [f"临场刷新对比（上版 {prev.get('locked_at', '?')}）"]
    if out["escalate"] and out["changes"]:
        out["risks"].append({"level": "高", "tag": "临场重大变化",
                             "detail": "较上一锁定版出现显著变化：" + "；".join(out["changes"])
                                       + "，已触发重算与风险升级", "sources": src})
    elif out["changed"]:
        out["risks"].append({"level": "中", "tag": "临场变化",
                             "detail": "较上一锁定版有变化：" + "；".join(out["changes"]),
                             "sources": src})
    return out


def lock_prematch_snapshot(model, fixture: dict, *, fixtures=None, neutral: bool = True,
                           now=None, odds_1x2=None, lineup_meta=None, group_state=None,
                           persist: bool = True, conn=None, json_path=None) -> dict:
    """生成并锁定一场比赛的赛前快照。返回 snapshot（含 report、changes）。"""
    home, away = fixture["home_team"], fixture["away_team"]
    mn = fixture.get("match_number")
    prev = load_prematch_snapshot(mn, path=json_path) if mn is not None else None

    report = build_report(model, home, away, neutral, fixture=fixture, fixtures=fixtures,
                          odds_1x2=odds_1x2, group_state=group_state, now=now,
                          lineup_meta=lineup_meta)
    snap = _snap_from_report(fixture, report, now)

    changes = detect_key_changes(prev, snap)
    for r in changes["risks"]:        # 关键变化并入报告与快照（风险升级）
        report["risks"].append(r)
        snap["risks"].append(r)
    snap["changes"] = {k: changes[k] for k in ("changed", "escalate", "changes")}
    snap["report"] = report

    if persist:
        _persist(snap, conn=conn, json_path=json_path)
    return snap


def _persist(snap: dict, conn=None, json_path=None) -> None:
    payload = json.dumps({"kind": "prematch_lock",
                          **{k: v for k, v in snap.items() if k != "report"},
                          "report": snap.get("report")}, ensure_ascii=False)
    cm = nullcontext(conn) if conn is not None else get_conn()
    with cm as c:
        c.execute("INSERT INTO predictions(created_at, home_team, away_team, model, payload) "
                  "VALUES (?,?,?,?,?)",
                  (snap["locked_at"], snap["home"], snap["away"], "prematch_lock", payload))
    _merge_json(snap, path=json_path)


def _merge_json(snap: dict, path=None) -> None:
    p = Path(path) if path else SNAPSHOTS_JSON
    data = {}
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8")).get("snapshots", {})
        except Exception:
            data = {}
    data[str(snap["match_number"])] = {k: v for k, v in snap.items() if k != "report"}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"snapshots": data}, ensure_ascii=False, indent=2), encoding="utf-8")


def load_all_prematch_snapshots(path=None) -> dict:
    """读 prematch_snapshots.json → {match_number(int): snapshot_lite}；缺失返回 {}。"""
    p = Path(path) if path else SNAPSHOTS_JSON
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8")).get("snapshots", {})
        return {int(k): v for k, v in data.items()}
    except Exception:
        return {}


def load_prematch_snapshot(match_number, path=None) -> dict | None:
    if match_number is None:
        return None
    return load_all_prematch_snapshots(path).get(int(match_number))
