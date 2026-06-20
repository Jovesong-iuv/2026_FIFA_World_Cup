"""全局赛事 AI 对话：统筹整届赛事数据（夺冠概率、各组形势、模型校准、价值/冷门），
汇总成中文上下文供 LLM 作答——回答宏观问题（谁被低估、哪个组最乱、模型整体准不准、
最大冷门在哪），而非单场。对应「统筹分析所有数据」的全局问答页。

build_global_context 分层：默认给赛事总览摘要；focus_team / focus_group 时按需深挖，
避免把 72 场 + 48 队全塞进 prompt 导致 token 爆炸、答非所重点。
ask 复用 match_chat.ask（传全局 system / 上下文标签），只依据给定数据作答、不编造。
"""
from __future__ import annotations

from wc2026.analysis import audit, dashboard_bridge, groups
from wc2026.data.team_names import zh
from wc2026.llm import match_chat

_SYSTEM = (
    "你是一名世界杯赛事首席分析师，能统筹整届赛事的所有数据（夺冠概率、各小组形势、"
    "模型对已赛的校准表现、价值与冷门提示）回答宏观问题。严格依据【赛事数据】作答，"
    "用中文、简洁专业、有条理；数据中没有的要明说「数据未提供」，不要编造具体数字。"
    "始终提醒：模型与概率存在误差，仅供参考、非投注建议。\n" + match_chat.ANALYSIS_PRINCIPLES
)


def _pct(v) -> str:
    try:
        return f"{float(v):.0%}"
    except Exception:
        return "—"


def _overview(model, fixtures, n_sims, snapshots) -> list:
    L = []
    finished = [f for f in fixtures if f.get("home_score") is not None]
    L.append(f"赛事进度：共 {len(fixtures)} 场可预测比赛，已完赛 {len(finished)} 场。")

    champ = dashboard_bridge._championship_payload(model, n_sims=n_sims)
    if champ:
        L.append(f"夺冠概率 Top10（蒙特卡洛 {n_sims} 次模拟）：")
        for c in champ[:10]:
            L.append(f"  {zh(c['team'])}：夺冠 {_pct(c['champion'])}、进决赛 {_pct(c['final'])}、"
                     f"进16强 {_pct(c['r16'])}")

    gd = groups.load_group_data(model)
    standings = groups.compute_standings(gd) if gd else {}
    if standings:
        L.append("各小组当前形势（名次.球队(积分)，已赛计真实、未赛用模型期望）：")
        for gname in sorted(standings):
            line = "，".join(f"{r['rank']}.{zh(r['team'])}({r['pts']})" for r in standings[gname])
            L.append(f"  {gname}：{line}")

    summ = audit.audit_summary(model, fixtures, snapshots=snapshots or {})
    if summ["n_finished"] > 0:
        mm = summ["model_metrics"]
        L.append(f"模型校准（已复盘 {summ['n_finished']} 场）：命中率 {_pct(mm['accuracy'])}、"
                 f"LogLoss {mm['log_loss']:.3f}（瞎猜基准 {mm['baseline_log_loss']:.3f}）、"
                 f"Brier {mm['brier']:.3f}。")
        cmp = summ["comparison"]
        if cmp.get("enabled"):
            L.append(f"  模型 vs 市场：LogLoss 更优方 {cmp['log_loss']['better']}、"
                     f"命中率更优方 {cmp['accuracy']['better']}（{cmp['n']} 场有赛前赔率）。")
        misses = [a for a in summ["matches"] if a["model"]["hit"] is False][:3]
        for a in misses:
            L.append(f"  偏差案例：{a['match']['home_cn']} {a['match']['score']} "
                     f"{a['match']['away_cn']} — {a['verdict']}")
    return L, standings, champ


def _focus_team_block(team, fixtures, standings, champ) -> str:
    parts = [f"【聚焦球队 {zh(team)}】"]
    c = next((x for x in (champ or []) if x["team"] == team), None)
    if c:
        parts.append(f"夺冠 {_pct(c['champion'])}、进决赛 {_pct(c['final'])}、进16强 {_pct(c['r16'])}")
    for gname, rows in standings.items():
        r = next((x for x in rows if x["team"] == team), None)
        if r:
            parts.append(f"{gname} 第 {r['rank']} 名 {r['pts']} 分"
                         f"（{r['w']}胜{r['d']}平{r['l']}负，进{r['gf']}失{r['ga']}）")
            break
    played = [f for f in fixtures
              if team in (f.get("home_team"), f.get("away_team")) and f.get("home_score") is not None]
    for f in played[-3:]:
        is_home = f["home_team"] == team
        opp = f["away_team"] if is_home else f["home_team"]
        gf = f["home_score"] if is_home else f["away_score"]
        ga = f["away_score"] if is_home else f["home_score"]
        parts.append(f"对 {zh(opp)} {gf}-{ga}")
    return "；".join(parts) if len(parts) > 1 else f"【聚焦球队 {zh(team)}】数据未提供"


def _focus_group_block(group_name, standings) -> str:
    rows = standings.get(group_name) or standings.get(f"Group {group_name}")
    if not rows:
        return f"【聚焦小组 {group_name}】数据未提供"
    detail = "；".join(
        f"{r['rank']}.{zh(r['team'])} {r['pts']}分（{r['w']}-{r['d']}-{r['l']}，净胜{r['gd']}）"
        for r in rows)
    return f"【聚焦小组 {group_name}】{detail}"


def build_global_context(model, *, fixtures=None, n_sims: int = 2000,
                         focus_team: str | None = None, focus_group: str | None = None,
                         snapshots=None) -> str:
    """聚合全局赛事上下文。focus_team/focus_group 用球队库名 / 组名时追加深挖段。"""
    fixtures = fixtures or []
    L, standings, champ = _overview(model, fixtures, n_sims, snapshots)
    if focus_team:
        L.append(_focus_team_block(focus_team, fixtures, standings, champ))
    if focus_group:
        L.append(_focus_group_block(focus_group, standings))
    return "\n".join(x for x in L if x)


def ask(question: str, context: str, history: list[dict] | None = None,
        max_tokens: int = 1000) -> dict:
    """全局赛事问答：复用 match_chat.ask 的骨架，注入全局 system 与「赛事数据」标签。"""
    return match_chat.ask(question, context, history=history, max_tokens=max_tokens,
                          system=_SYSTEM, context_label="赛事数据")
