"""世界杯赛中实力修正：用已完赛结果(+可选新闻)给参赛队算有界的实力增量 δ。

为什么需要：模型是赛前静态评级(见 models/predictor.py)，世界杯已完赛结果不回流到
实力评估，导致剩余场次预测偏差。这里在不改原模型的前提下叠加一层可解释、有界、可回滚
的修正：
- 赛果增量：实际结果 vs 赛前模型基线 → Elo 风格增量 + 攻防微调(高权重纠偏)。
- 新闻增量：复用 sources/news.py 的 LLM 风险抽取，映射成温和负向微调；LLM 缺失自动跳过。

防双重计数：只处理 fixtures 已完赛中 date_utc 晚于训练快照 trained_through 的比赛
(重训后该日期前移，已纳入训练的比赛自动移出增量集合)。

权威存储 data/team_adjustments.json(可提交、部署持久、可回滚)，同步镜像到 DB 表。
修正应用为「构造调整后的 dc/elo 副本再重组 EnsembleModel」，下游(groups/tournament/
strength/context)零改动自动生效。
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone

from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.models.elo import _goal_mult
from wc2026.models.predictor import EnsembleModel

ADJ_PATH = settings.data_dir / "team_adjustments.json"
META_PATH = settings.data_dir / "model_meta.json"

HOSTS = {"Mexico", "Canada", "United States"}

# 赛果增量参数
K_WC = 70.0          # 世界杯赛果 Elo 修正力度(高于常规 60，强力纠偏)
ETA = 0.06           # 攻防增量学习率(实际进球 vs 赛前期望)
KNOCKOUT_WEIGHT = 1.35
SPECIAL_EVENT_WEIGHT = 0.45

# 有界(单队累计上限)
ELO_CAP = 120.0
ATK_CAP = 0.40
DEF_CAP = 0.40

# 新闻 severity → 增量(温和、负向，幅度小于赛果)
_NEWS_ELO = {"高": -25.0, "中": -12.0, "低": -5.0}
_NEWS_ATK = {"高": -0.06, "中": -0.03, "低": -0.01}


def _clip(v: float, cap: float) -> float:
    return max(-cap, min(cap, v))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty() -> dict:
    return {"elo": 0.0, "attack": 0.0, "defense": 0.0, "sources": []}


# ---------------- 训练快照 cutoff（防双重计数） ----------------
def load_meta() -> dict:
    if META_PATH.exists():
        try:
            return json.loads(META_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def trained_through() -> str:
    """模型训练数据覆盖到的最新比赛日期(YYYY-MM-DD)。空串表示不过滤。"""
    return (load_meta().get("trained_through") or "")[:10]


# ---------------- 赛果增量 ----------------
def _filter_after_cutoff(rows: list[dict], cutoff: str) -> list[dict]:
    """保留日期严格晚于 cutoff 的比赛(cutoff 为空则全保留)。防双重计数核心。"""
    if not cutoff:
        return list(rows)
    return [r for r in rows if (r.get("date_utc") or "")[:10] > cutoff]


def _finished_wc_matches(cutoff: str) -> list[dict]:
    """fixtures 已完赛、日期严格晚于 cutoff 的世界杯比赛(防双重计数)。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT match_number, round_number, date_utc, home_team, away_team, home_score, away_score "
            "FROM fixtures WHERE predictable=1 AND home_score IS NOT NULL "
            "AND away_score IS NOT NULL ORDER BY date_utc"
        ).fetchall()
    return _filter_after_cutoff([dict(r) for r in rows], cutoff)


def _event_weight(m: dict) -> tuple[float, list[str]]:
    weight, notes = 1.0, []
    try:
        if int(m.get("round_number") or 0) >= 4:
            weight *= KNOCKOUT_WEIGHT
            notes.append("淘汰赛高权重")
    except (TypeError, ValueError):
        pass
    text = " ".join(str(x) for x in (m.get("event_flags") or m.get("notes") or []))
    if any(w in text for w in ("点球", "红牌", "伤退", "乌龙", "penalty", "red_card", "injury_exit", "own_goal")):
        weight *= SPECIAL_EVENT_WEIGHT
        notes.append("特殊事件降权")
    return weight, notes


def compute_result_deltas(base_model: EnsembleModel, matches: list[dict]) -> dict:
    """用赛前基线模型逐场算增量。返回 {team: {elo,attack,defense,sources}}。"""
    elo = getattr(base_model, "elo", None)
    adj: dict = {}

    def ensure(t: str) -> dict:
        return adj.setdefault(t, _empty())

    for m in matches:
        h, a = m["home_team"], m["away_team"]
        if not (base_model.has_team(h) and base_model.has_team(a)):
            continue
        hs, as_ = int(m["home_score"]), int(m["away_score"])
        neutral = h not in HOSTS                       # 东道主保留主场优势
        event_weight, weight_notes = _event_weight(m)

        # Elo 增量：实际胜负 vs 赛前期望胜率(主队视角 We=胜+半平)
        if elo is not None and getattr(elo, "ratings", None):
            qx = elo.prob_1x2(h, a, neutral)
            we = qx["home"] + 0.5 * qx["draw"]
        else:
            we = 0.5
        w = 1.0 if hs > as_ else (0.5 if hs == as_ else 0.0)
        d_elo = K_WC * event_weight * _goal_mult(hs - as_) * (w - we)

        # 攻防增量：实际进/失球 vs 赛前期望进球(符号与 DC 一致：defense 越大失球越多)
        lam, mu = base_model.expected_goals(h, a, neutral)
        eh, ea = ensure(h), ensure(a)
        eh["elo"] += d_elo
        ea["elo"] -= d_elo
        eh["attack"] += ETA * event_weight * (hs - lam)
        eh["defense"] += ETA * event_weight * (as_ - mu)
        ea["attack"] += ETA * event_weight * (as_ - mu)
        ea["defense"] += ETA * event_weight * (hs - lam)

        at = (m.get("date_utc") or "")[:10]
        detail = f"{h} {hs}-{as_} {a}"
        eh["sources"].append({"type": "result", "detail": detail,
                              "delta_elo": round(d_elo, 1), "at": at,
                              "weight": round(event_weight, 2), "weight_notes": weight_notes})
        ea["sources"].append({"type": "result", "detail": detail,
                              "delta_elo": round(-d_elo, 1), "at": at,
                              "weight": round(event_weight, 2), "weight_notes": weight_notes})
    return adj


# ---------------- 新闻增量(默认降级) ----------------
def compute_news_deltas(teams: list[str], limit_per_team: int = 12) -> dict:
    """复用 news.py 的 LLM 风险抽取 → 温和负向 δ。LLM 缺失/失败/无命中 → {}。"""
    try:
        from wc2026.data.sources import news
    except Exception:
        return {}
    adj: dict = {}
    for t in teams:
        try:
            items = news.fetch_for_teams([t], limit=limit_per_team)
            tags = news.extract_risk_tags(t, t, items)   # LLMError → None
        except Exception:
            tags = None
        risks = (tags or {}).get("home", []) if tags else []
        if not risks:
            continue
        e = adj.setdefault(t, _empty())
        for rk in risks:
            sev = rk.get("severity", "中")
            e["elo"] += _NEWS_ELO.get(sev, _NEWS_ELO["中"])
            e["attack"] += _NEWS_ATK.get(sev, _NEWS_ATK["中"])
            note = f"{rk.get('tag', '')}: {rk.get('note', '')}".strip(": ").strip()
            e["sources"].append({"type": "news", "detail": note, "severity": sev})
    return adj


# ---------------- 合并 / 落盘 / 读取 ----------------
def _merge(*adjs: dict) -> dict:
    out: dict = {}
    for a in adjs:
        for t, e in a.items():
            o = out.setdefault(t, _empty())
            o["elo"] += e.get("elo", 0.0)
            o["attack"] += e.get("attack", 0.0)
            o["defense"] += e.get("defense", 0.0)
            o["sources"] += e.get("sources", [])
    for e in out.values():                              # 合并后统一有界
        e["elo"] = round(_clip(e["elo"], ELO_CAP), 2)
        e["attack"] = round(_clip(e["attack"], ATK_CAP), 4)
        e["defense"] = round(_clip(e["defense"], DEF_CAP), 4)
    return out


def load_adjustments() -> dict:
    """读取 team_adjustments.json 的 teams 段；缺失/损坏 → {}。"""
    if not ADJ_PATH.exists():
        return {}
    try:
        return json.loads(ADJ_PATH.read_text(encoding="utf-8")).get("teams", {}) or {}
    except Exception:
        return {}


def save_adjustments(teams_adj: dict) -> None:
    settings.ensure_dirs()
    updated_at = _now()
    payload = {"trained_through": trained_through(), "updated_at": updated_at, "teams": teams_adj}
    ADJ_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _mirror_to_db(teams_adj, updated_at)


def _mirror_to_db(teams_adj: dict, updated_at: str) -> None:
    """镜像到 DB 表(展示/查询用)；失败不影响 JSON 权威存储。"""
    try:
        with get_conn() as conn:
            conn.execute("DELETE FROM team_adjustments")
            conn.executemany(
                "INSERT INTO team_adjustments (team, elo, attack, defense, sources_json, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                [(t, e.get("elo", 0.0), e.get("attack", 0.0), e.get("defense", 0.0),
                  json.dumps(e.get("sources", []), ensure_ascii=False), updated_at)
                 for t, e in teams_adj.items()],
            )
    except Exception:
        pass


# ---------------- 应用 / 重算 / 回滚 ----------------
def apply_adjustments(model: EnsembleModel, teams_adj: dict | None = None) -> EnsembleModel:
    """把 δ 叠加到模型，返回新的 EnsembleModel(原模型不变)。无修正 → 原样返回。"""
    teams_adj = load_adjustments() if teams_adj is None else teams_adj
    if not teams_adj:
        return model

    dc2 = copy.copy(model.dc)
    dc2.attack = dict(model.dc.attack)
    dc2.defense = dict(model.dc.defense)
    for t, e in teams_adj.items():
        if t in dc2.attack:
            dc2.attack[t] += e.get("attack", 0.0)
            dc2.defense[t] += e.get("defense", 0.0)

    elo2 = None
    if getattr(model, "elo", None) is not None:
        elo2 = copy.copy(model.elo)
        elo2.ratings = dict(model.elo.ratings)
        for t, e in teams_adj.items():
            if t in elo2.ratings:
                elo2.ratings[t] += e.get("elo", 0.0)

    return EnsembleModel(dc2, elo2, model.w)


def recompute(base_model: EnsembleModel, with_news: bool = False,
              news_teams: list[str] | None = None) -> dict:
    """重算修正并落盘。base_model 必须是未修正模型(get_model(adjusted=False))。"""
    matches = _finished_wc_matches(trained_through())
    result_adj = compute_result_deltas(base_model, matches)
    if with_news:
        teams = news_teams if news_teams is not None else sorted(
            {m["home_team"] for m in matches} | {m["away_team"] for m in matches})
        merged = _merge(result_adj, compute_news_deltas(teams))
    else:
        merged = _merge(result_adj)
    save_adjustments(merged)
    return merged


def reset() -> None:
    """清空修正：get_model 退回纯赛前模型。"""
    save_adjustments({})
