"""赔率走势矛盾 / 过热信号检测（借鉴 deep-analysis skill 的「市场热度≠真实稳妥」原则）。

基于 odds_history 的时间序列（同一对阵多次快照），识别市场走势中的矛盾或过热信号：
平局降赔、热门降赔升温、大球降水过快、让球深盘水位升高等。纯提示，不改写模型概率
（遵循项目「赔率只做后验」原则）。快照不足 2 个时降级、不臆测。
"""
from __future__ import annotations

from wc2026.data import odds_history


def _trend(pts) -> tuple | None:
    """pts=[(ts,odds)...] 升序；返回 (first, last, rel_change) 或 None（有效点不足两个）。"""
    valid = [(t, o) for (t, o) in (pts or []) if o and o > 1.0]
    if len(valid) < 2:
        return None
    first, last = valid[0][1], valid[-1][1]
    if first <= 0:
        return None
    return first, last, (last - first) / first


def detect_odds_signals(home: str, away: str, conn=None,
                        drop: float = 0.05, rise: float = 0.05) -> dict:
    """返回 {enabled, signals:[{tag,level,detail}], note/reason}。signals 为定性风险提示。"""
    signals = []
    h2h = odds_history.load_history(home, away, "h2h", conn=conn)
    has_any = bool(h2h)

    d = _trend(h2h.get("draw")) if h2h else None
    if d and d[2] <= -drop:
        signals.append({"tag": "平局降赔", "level": "中",
                        "detail": f"平局赔率 {d[0]:.2f}→{d[1]:.2f}（{d[2]:+.0%}），"
                                  "市场更看好平局/不看好分出大胜，强队穿盘难度上升"})
    for sel, name in (("home", "主胜"), ("away", "客胜")):
        t = _trend(h2h.get(sel)) if h2h else None
        if t and t[2] <= -0.08:
            signals.append({"tag": f"{name}降赔（市场升温）", "level": "低",
                            "detail": f"{name}赔率 {t[0]:.2f}→{t[1]:.2f}（{t[2]:+.0%}），"
                                      "资金流入该方向，留意是否过热"})

    for line in odds_history.available_lines(home, away, "totals", conn=conn):
        has_any = True
        series = odds_history.load_history(home, away, "totals", line=line, conn=conn)
        o = _trend(series.get("over"))
        if o and o[2] <= -0.08:
            signals.append({"tag": f"大球过热（大{line}）", "level": "中",
                            "detail": f"大{line}赔率 {o[0]:.2f}→{o[1]:.2f}（{o[2]:+.0%}），"
                                      "大球降水过快，警惕节奏被拖慢的过热回撤"})

    for line in odds_history.available_lines(home, away, "spreads", conn=conn):
        has_any = True
        series = odds_history.load_history(home, away, "spreads", line=line, conn=conn)
        hh = _trend(series.get("home"))
        if hh and hh[2] >= rise:
            signals.append({"tag": f"深盘水位升高（让{line}）", "level": "中",
                            "detail": f"让球方水位 {hh[0]:.2f}→{hh[1]:.2f}（{hh[2]:+.0%}），"
                                      "市场对强队大胜/穿盘的信心下降（支持赢、未必支持大胜）"})

    if not has_any:
        return {"enabled": False, "signals": [],
                "reason": "无赔率快照（需在赛前多次拉取赔率以累积走势）"}
    if not signals:
        return {"enabled": True, "signals": [],
                "note": "赔率走势暂无明显矛盾/过热信号。"}
    return {"enabled": True, "signals": signals,
            "note": "以上为赔率走势的定性信号，仅作风险参考、不改写模型概率（赔率只做后验）。"}
