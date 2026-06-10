"""情境/动机因子：在模型期望进球上做有界调整，再重算比分矩阵。

- 东道主加成：美/加/墨在本国主场，世界杯东道主常超常发挥，给温和额外加成。
- 末轮出线情境(框架)：已出线可能轮换、已淘汰动机下降、生死战维持，
  需小组积分/出线状态(group_state)，赛事进行中传入；赛前为空操作。
所有调整有界，并产出 notes 说明，供理由展示。
"""
from __future__ import annotations

from wc2026.data.team_names import zh

HOSTS = {"Mexico", "Canada", "United States"}

# 末轮动机对期望进球的系数（有界）
_MOTIV = {"qualified": 0.95, "eliminated": 0.90, "must_win": 1.0, "alive": 1.0}


def adjusted_prediction(model, home, away, neutral=True,
                        host_boost: float = 0.12, group_state: dict | None = None,
                        tank_risk: bool = False) -> dict:
    """返回 {matrix, exp_goals, notes, tank_risk}。无任何情境时与基础预测一致。"""
    lam, mu = model.expected_goals(home, away, neutral)
    notes = []

    if (not neutral) and home in HOSTS:
        lam *= 1.0 + host_boost
        notes.append(f"东道主 {zh(home)} 本土作战，额外动机加成 +{host_boost:.0%}")

    if group_state:
        hf, af, gnotes = _motivation(home, away, group_state)
        lam *= hf
        mu *= af
        notes += gnotes
        # 双方均已出线 → 自动标记控分/默契球风险
        if (group_state.get("home", {}).get("status") == "qualified"
                and group_state.get("away", {}).get("status") == "qualified"):
            tank_risk = True

    if tank_risk:
        # 消极比赛/控分：双方倾向保守，结果更随机；下调进球，弱化模型确定性
        lam *= 0.85
        mu *= 0.85
        notes.append("⚠️ 控分/默契球风险：出线形势已定，可能为操纵排名或规避强敌而非全力争胜，"
                     "比分预测参考价值下降、爆冷概率上升")

    return {"matrix": model.matrix_from_goals(lam, mu),
            "exp_goals": (round(lam, 3), round(mu, 3)), "notes": notes, "tank_risk": tank_risk}


def _motivation(home, away, group_state: dict):
    """末轮出线情境调整。group_state 形如
    {"home": {"status": "qualified|eliminated|must_win|alive"}, "away": {...}}。"""
    hs = group_state.get("home", {}).get("status", "alive")
    as_ = group_state.get("away", {}).get("status", "alive")
    notes = []
    desc = {"qualified": "已出线，可能轮换", "eliminated": "已出局，动机下降", "must_win": "生死战，全力争胜"}
    if hs in desc:
        notes.append(f"{zh(home)} {desc[hs]}")
    if as_ in desc:
        notes.append(f"{zh(away)} {desc[as_]}")
    return _MOTIV.get(hs, 1.0), _MOTIV.get(as_, 1.0), notes
