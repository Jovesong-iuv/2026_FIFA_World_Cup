"""推荐比分对比：保存外部来源、聚合共识，并让 LLM 做解释。

核心原则：程序先给稳定排序，LLM 只做分析和修正说明；LLM 不可用时仍能展示结果。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

import numpy as np

from wc2026.data.db import get_conn
from wc2026.data.team_names import zh
from wc2026.llm import provider
from wc2026.markets import derive


CONFIDENCE_WEIGHT = {"低": 0.8, "中": 1.0, "高": 1.18}
POSITION_WEIGHT = (1.0, 0.78, 0.58, 0.44, 0.34, 0.26)


def ensure_schema(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS match_recommendations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT, updated_at TEXT, "
        "match_number INTEGER, home_team TEXT NOT NULL, away_team TEXT NOT NULL, "
        "source TEXT NOT NULL, scores_json TEXT, goal_picks_json TEXT, half_full_json TEXT, "
        "confidence TEXT DEFAULT '中', weight REAL DEFAULT 1.0, note TEXT)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_match_recs_match "
        "ON match_recommendations(match_number, home_team, away_team)"
    )


def parse_scores(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        raw = " ".join(str(v) for v in value)
    else:
        raw = str(value or "")
    out = []
    for a, b in re.findall(r"(\d{1,2})\s*[-:：]\s*(\d{1,2})", raw):
        score = f"{int(a)}-{int(b)}"
        if score not in out:
            out.append(score)
    return out


def parse_tags(value) -> list[str]:
    if isinstance(value, (list, tuple)):
        parts = [str(v).strip() for v in value]
    else:
        parts = re.split(r"[,，、\s]+", str(value or ""))
    out = []
    for p in parts:
        if not p:
            continue
        p = p.replace("/", "").strip()
        if p and p not in out:
            out.append(p)
    return out


def save_recommendation(match_number: int | None, home_team: str, away_team: str, source: str,
                        scores=None, goal_picks=None, half_full_picks=None, *,
                        confidence: str = "中", weight: float = 1.0, note: str = "",
                        rec_id: int | None = None, conn=None) -> int:
    own = conn is None
    if own:
        cm = get_conn()
        conn = cm.__enter__()
    try:
        ensure_schema(conn)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        payload = (
            now, match_number, home_team, away_team, source.strip() or "未命名来源",
            json.dumps(parse_scores(scores), ensure_ascii=False),
            json.dumps(parse_tags(goal_picks), ensure_ascii=False),
            json.dumps(parse_tags(half_full_picks), ensure_ascii=False),
            confidence if confidence in CONFIDENCE_WEIGHT else "中",
            float(weight or 1.0),
            note or "",
        )
        if rec_id:
            conn.execute(
                "UPDATE match_recommendations SET updated_at=?, match_number=?, home_team=?, away_team=?, "
                "source=?, scores_json=?, goal_picks_json=?, half_full_json=?, confidence=?, weight=?, note=? "
                "WHERE id=?",
                payload + (rec_id,),
            )
            return int(rec_id)
        cur = conn.execute(
            "INSERT INTO match_recommendations (created_at, updated_at, match_number, home_team, away_team, "
            "source, scores_json, goal_picks_json, half_full_json, confidence, weight, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (now,) + payload,
        )
        return int(cur.lastrowid)
    finally:
        if own:
            cm.__exit__(None, None, None)


def _decode_list(text: str | None) -> list[str]:
    try:
        data = json.loads(text or "[]")
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _row(r) -> dict:
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "match_number": r["match_number"],
        "home_team": r["home_team"],
        "away_team": r["away_team"],
        "source": r["source"],
        "scores": _decode_list(r["scores_json"]),
        "goal_picks": _decode_list(r["goal_picks_json"]),
        "half_full_picks": _decode_list(r["half_full_json"]),
        "confidence": r["confidence"],
        "weight": float(r["weight"] or 1.0),
        "note": r["note"] or "",
    }


def list_recommendations(*, match_number: int | None = None, home_team: str | None = None,
                         away_team: str | None = None, conn=None) -> list[dict]:
    own = conn is None
    if own:
        cm = get_conn()
        conn = cm.__enter__()
    try:
        ensure_schema(conn)
        where, params = [], []
        if match_number is not None:
            where.append("match_number=?")
            params.append(match_number)
        if home_team and away_team:
            where.append("home_team=? AND away_team=?")
            params.extend([home_team, away_team])
        sql = "SELECT * FROM match_recommendations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY id"
        return [_row(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        if own:
            cm.__exit__(None, None, None)


def delete_recommendation(rec_id: int, conn=None) -> None:
    own = conn is None
    if own:
        cm = get_conn()
        conn = cm.__enter__()
    try:
        ensure_schema(conn)
        conn.execute("DELETE FROM match_recommendations WHERE id=?", (rec_id,))
    finally:
        if own:
            cm.__exit__(None, None, None)


def _score_probs_from_matrix(mat: np.ndarray, limit: int = 8) -> dict[str, float]:
    probs = {}
    rows, cols = mat.shape
    for i in range(rows):
        for j in range(cols):
            probs[f"{i}-{j}"] = float(mat[i, j])
    return dict(sorted(probs.items(), key=lambda kv: kv[1], reverse=True)[:limit])


def _external_scores(recs: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for rec in recs:
        base = float(rec.get("weight") or 1.0) * CONFIDENCE_WEIGHT.get(rec.get("confidence"), 1.0)
        for idx, score in enumerate(rec.get("scores") or []):
            out[score] = out.get(score, 0.0) + base * POSITION_WEIGHT[min(idx, len(POSITION_WEIGHT) - 1)]
    return out


def _external_tags(recs: list[dict], key: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for rec in recs:
        base = float(rec.get("weight") or 1.0) * CONFIDENCE_WEIGHT.get(rec.get("confidence"), 1.0)
        for idx, label in enumerate(rec.get(key) or []):
            out[label] = out.get(label, 0.0) + base * POSITION_WEIGHT[min(idx, len(POSITION_WEIGHT) - 1)]
    return out


def _normalize_scores(external: dict[str, float], model: dict[str, float],
                      *, external_weight: float = 0.48) -> list[dict]:
    keys = set(external) | set(model)
    max_ext = max(external.values(), default=0.0) or 1.0
    raw = []
    for k in keys:
        model_p = float(model.get(k, 0.0))
        ext_p = external.get(k, 0.0) / max_ext
        combined = model_p * (1.0 - external_weight) + ext_p * external_weight
        raw.append((k, combined, model_p, ext_p))
    total = sum(v for _k, v, _m, _e in raw) or 1.0
    rows = [{
        "score": k,
        "probability": round(v / total, 4),
        "model_prob": round(m, 4),
        "external_strength": round(e, 3),
    } for k, v, m, e in sorted(raw, key=lambda x: x[1], reverse=True)]
    return rows


def _normalize_tags(external: dict[str, float], model: dict[str, float] | None = None) -> list[dict]:
    model = model or {}
    keys = set(external) | set(model)
    max_ext = max(external.values(), default=0.0) or 1.0
    raw = []
    for k in keys:
        model_p = float(model.get(k, 0.0))
        ext_p = external.get(k, 0.0) / max_ext
        raw.append((k, model_p * 0.55 + ext_p * 0.45, model_p, ext_p))
    total = sum(v for _k, v, _m, _e in raw) or 1.0
    return [{
        "label": k,
        "probability": round(v / total, 4),
        "model_prob": round(m, 4),
        "external_strength": round(e, 3),
    } for k, v, m, e in sorted(raw, key=lambda x: x[1], reverse=True)]


def _goal_models(mat: np.ndarray | None) -> dict[str, float]:
    if mat is None:
        return {}
    bands = derive.goal_bands(mat)
    ou = derive.over_under(mat, 2.5)
    return {
        **bands,
        "大2.5": ou["over"],
        "小2.5": ou["under"],
    }


def consensus_report(home_team: str, away_team: str, recs: list[dict], *,
                     model_matrix: np.ndarray | None = None,
                     lambda_home: float | None = None,
                     lambda_away: float | None = None,
                     team_context: dict | None = None) -> dict:
    model_scores = _score_probs_from_matrix(model_matrix) if model_matrix is not None else {}
    score_rows = _normalize_scores(_external_scores(recs), model_scores)[:6]
    goal_rows = _normalize_tags(_external_tags(recs, "goal_picks"), _goal_models(model_matrix))[:6]
    half_full_model = (
        derive.half_full_time(lambda_home, lambda_away)
        if lambda_home is not None and lambda_away is not None else {}
    )
    half_rows = _normalize_tags(_external_tags(recs, "half_full_picks"), half_full_model)[:8]
    return {
        "match": {"home": home_team, "away": away_team, "home_cn": zh(home_team), "away_cn": zh(away_team)},
        "source_count": len(recs),
        "score_recommendations": score_rows[:4],
        "goal_recommendations": goal_rows[:4],
        "half_full_recommendations": half_rows[:6],
        "team_context": team_context or {},
    }


def build_ai_prompt(home_team: str, away_team: str, recs: list[dict], consensus: dict) -> str:
    lines = []
    for rec in recs:
        lines.append(
            f"- {rec.get('source')}: 比分 {', '.join(rec.get('scores') or ['—'])}; "
            f"进球数 {', '.join(rec.get('goal_picks') or ['—'])}; "
            f"半全场 {', '.join(rec.get('half_full_picks') or ['—'])}; "
            f"置信度 {rec.get('confidence') or '中'}; 备注 {rec.get('note') or '—'}"
        )
    ctx = consensus.get("team_context") or {}
    return (
        f"你是世界杯单场预测分析师。请综合外部推荐、模型概率、球队风格和强弱评分，"
        f"分析 {zh(home_team)} vs {zh(away_team)}。\n\n"
        f"【外部推荐】\n" + ("\n".join(lines) if lines else "暂无外部推荐") + "\n\n"
        f"【程序综合比分Top】\n{json.dumps(consensus.get('score_recommendations', []), ensure_ascii=False)}\n\n"
        f"【程序综合进球数Top】\n{json.dumps(consensus.get('goal_recommendations', []), ensure_ascii=False)}\n\n"
        f"【程序综合半全场Top】\n{json.dumps(consensus.get('half_full_recommendations', []), ensure_ascii=False)}\n\n"
        f"【球队上下文】\n{json.dumps(ctx, ensure_ascii=False)}\n\n"
        "请输出中文分析，必须包含：1) 最可能3-4个比分并排序；2) 进球数方向；"
        "3) 每队各两个半全场倾向或整体Top半全场；4) 为什么外部推荐与模型一致/冲突；"
        "5) 风险提示。不要承诺盈利。"
    )


def ai_analyze(home_team: str, away_team: str, recs: list[dict], consensus: dict) -> dict:
    prompt = build_ai_prompt(home_team, away_team, recs, consensus)
    try:
        text = provider.chat(
            prompt,
            system="你是严谨的足球数据分析师，只基于给定数据分析，不编造伤停和内幕。",
            max_tokens=1200,
            temperature=0.25,
        )
        return {"ok": True, "text": text, "source": "llm"}
    except Exception as exc:
        return {"ok": False, "text": f"AI 分析暂不可用：{exc}", "source": "error"}
