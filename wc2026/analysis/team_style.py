"""球队画像风格修正：把阵型与风格描述转成有界的进球期望微调。

核心模型仍由 Dixon-Coles / Elo 校准；这里仅用 team_profiles.json 中较稳定的
阵型与打法关键词，调整比分分布形状（进球多少、比分尾部），不单独决定胜负。
"""
from __future__ import annotations

import json

from wc2026.analysis.tactics import formation_lean
from wc2026.config import settings

PROFILE_PATH = settings.data_dir / "team_profiles.json"

_ATTACK_TERMS = (
    "进攻", "高位逼抢", "快速反击", "边路突破", "三叉戟", "压上",
    "创造进攻", "全攻全守", "攻守转换速度快", "offensive", "pressing",
)
_DEFENSE_TERMS = (
    "防守", "低位", "密集防守", "阵地战", "收缩", "韧性", "反击为核心",
    "defensive", "low block",
)
_VOLUME_TERMS = ("传控", "控球", "围攻", "持续", "高位逼抢", "压上", "进攻三区")
_QUALITY_TERMS = ("禁区", "三叉戟", "创造进攻", "核心区域", "终结", "高质量")
_TRANSITION_TERMS = ("快速反击", "反击", "转换", "身后", "攻守转换")
_PRESSING_TERMS = ("高位逼抢", "压迫", "反抢", "高位夺回")
_LOW_BLOCK_TERMS = ("低位", "密集防守", "五后卫", "收缩", "阵地战")
_SET_PIECE_TERMS = ("定位球", "角球", "任意球", "防空")
_TEMPO_TERMS = ("节奏快", "开放", "对攻", "全攻全守", "攻守转换速度快")

_LEAN_SCORE = {"进攻": 1.0, "均衡": 0.0, "防守": -1.0, "未知": 0.0}
_MIN_GOALS = 0.25
_MAX_MULT = 1.12
_MIN_MULT = 0.88


def load_team_profiles(path=PROFILE_PATH) -> dict:
    """读取球队画像；缺失或损坏时返回空字典，预测链路自动退回纯模型。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _keyword_score(text: str) -> float:
    s = (text or "").lower()
    attack = sum(1 for term in _ATTACK_TERMS if term.lower() in s)
    defense = sum(1 for term in _DEFENSE_TERMS if term.lower() in s)
    return max(-0.5, min(0.5, 0.18 * (attack - defense)))


def _term_score(text: str, terms: tuple[str, ...], scale: float = 0.25) -> float:
    s = (text or "").lower()
    return min(1.0, scale * sum(1 for term in terms if term.lower() in s))


def _style_dimensions(text: str, lean: str) -> dict:
    """把描述性画像拆成可进入 λ 修正的 proxy 维度。"""
    dims = {
        "attack_volume": _term_score(text, _VOLUME_TERMS),
        "chance_quality": _term_score(text, _QUALITY_TERMS),
        "transition_attack": _term_score(text, _TRANSITION_TERMS),
        "pressing": _term_score(text, _PRESSING_TERMS),
        "low_block": _term_score(text, _LOW_BLOCK_TERMS),
        "set_piece_attack": _term_score(text, _SET_PIECE_TERMS),
        "defensive_resistance": _term_score(text, _DEFENSE_TERMS, 0.18),
        "tempo": _term_score(text, _TEMPO_TERMS),
    }
    if lean == "进攻":
        dims["attack_volume"] = min(1.0, dims["attack_volume"] + 0.35)
        dims["tempo"] = min(1.0, dims["tempo"] + 0.15)
    elif lean == "防守":
        dims["low_block"] = min(1.0, dims["low_block"] + 0.35)
        dims["defensive_resistance"] = min(1.0, dims["defensive_resistance"] + 0.25)
        dims["tempo"] = max(-1.0, dims["tempo"] - 0.25)
    return {k: round(v, 3) for k, v in dims.items()}


def style_profile(team: str, profiles: dict | None = None) -> dict:
    """返回单队风格画像 {team, formation, lean, score}，score 约在 [-1.5, 1.5]。"""
    profiles = load_team_profiles() if profiles is None else profiles
    raw = profiles.get(team, {}) or {}
    lean = formation_lean(raw.get("formation"))
    style_text = " ".join(str(raw.get(k, "")) for k in ("style_detail", "background"))
    dims = _style_dimensions(style_text, lean["lean"])
    score = _LEAN_SCORE.get(lean["lean"], 0.0) + _keyword_score(style_text)
    return {
        "team": team,
        "formation": lean["formation"],
        "lean": lean["lean"],
        "score": round(score, 3),
        "dimensions": dims,
    }


def _bounded_multiplier(v: float) -> float:
    return max(_MIN_MULT, min(_MAX_MULT, v))


def style_goal_adjustment(home: str, away: str, home_goals: float, away_goals: float,
                          profiles: dict | None = None) -> dict:
    """用两队风格给期望进球做小幅修正。

    开放型球队会抬高自身进球，同时也略放大对手空间；低位防守球队则相反。
    """
    hp = style_profile(home, profiles)
    ap = style_profile(away, profiles)
    hd, ad = hp["dimensions"], ap["dimensions"]

    hs = (
        0.045 * hd["attack_volume"]
        + 0.040 * hd["chance_quality"]
        + 0.030 * hd["transition_attack"]
        + 0.025 * hd["set_piece_attack"]
        + 0.020 * hd["pressing"] * (1.0 - ad["low_block"])
        + 0.020 * ad["tempo"]
        - 0.050 * ad["low_block"]
        - 0.035 * ad["defensive_resistance"]
    )
    as_ = (
        0.045 * ad["attack_volume"]
        + 0.040 * ad["chance_quality"]
        + 0.030 * ad["transition_attack"]
        + 0.025 * ad["set_piece_attack"]
        + 0.020 * ad["pressing"] * (1.0 - hd["low_block"])
        + 0.020 * hd["tempo"]
        - 0.050 * hd["low_block"]
        - 0.035 * hd["defensive_resistance"]
    )
    pace = 0.015 * (hd["tempo"] + ad["tempo"])

    home_mult = _bounded_multiplier(1.0 + hs + pace)
    away_mult = _bounded_multiplier(1.0 + as_ + pace)
    return {
        "home_goals": max(_MIN_GOALS, float(home_goals) * home_mult),
        "away_goals": max(_MIN_GOALS, float(away_goals) * away_mult),
        "home_multiplier": home_mult,
        "away_multiplier": away_mult,
        "home_profile": hp,
        "away_profile": ap,
    }
