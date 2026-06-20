"""单场 AI 对话：把该场已算出的预测与已拉取/库内数据汇总成上下文，调用 LLM 作答。

build_context 为纯函数（dict → 文本），便于测试；ask 调用 provider.chat（需 LLM，费 token）。
只回答基于给定数据的问题，不编造数字；分析仅供参考、非投注建议。
"""
from __future__ import annotations

from wc2026.llm import provider

ANALYSIS_PRINCIPLES = (
    "分析时遵循以下专业原则：\n"
    "1) 区分盘口类型——竞彩让球（强队赢2球+为让胜、赢1球为让平、不胜为让负）、亚盘（结合水位/升降盘/赢半输半）、"
    "欧赔（胜平负倾向）、大小球；切勿把竞彩让1与亚盘-1.5混为一谈。\n"
    "2) 不低估亚非/中北美等非传统强队的防守韧性、低位防守与受让价值——强队≠稳胜。\n"
    "3) 也不低估超级巨星面对密集防守的破局能力；区分超级巨星型强队、体系型强队、低效热门队三类，给出不同盘口倾向。\n"
    "4) 市场热度≠真实稳妥——留意热门降赔但让球不升盘、平局降赔、强队深盘水位升高、大球降水过快过热等矛盾信号。\n"
    "5) 不要绝对化（禁用「必胜/稳胆/稳赢/一定打穿」），结论须给出主要依据、最可能剧本、潜在冷门路径与最大不确定性。"
)

_SYSTEM = (
    "你是一名世界杯赔率与比赛分析师。严格依据【比赛数据】中给出的信息用中文回答，"
    "简洁专业、有条理。数据中没有的内容要明说「数据未提供」，不要编造具体数字或赔率。"
    "始终提醒：模型与概率存在误差，内容仅供参考，非投注建议。\n" + ANALYSIS_PRINCIPLES
)


def _pct(v) -> str:
    try:
        return f"{float(v):.0%}"
    except Exception:
        return "—"


def build_context(d: dict) -> str:
    """d 为单场各项已算结果（缺项自动跳过）→ 给 LLM 的中文上下文。"""
    L = []
    L.append(f"比赛：{d.get('home','?')} vs {d.get('away','?')}")
    if d.get("home_rank") or d.get("away_rank"):
        L.append(f"世界排名(FIFA 官方,缺失回退Elo)：{d.get('home')} 第 {d.get('home_rank','—')} · "
                 f"{d.get('away')} 第 {d.get('away_rank','—')}")
    L.append(f"赛果：{d['result']}" if d.get("result") else "赛果：未开赛（以下为赛前模型预测）")
    if d.get("context_notes"):
        L.append("情境调整：" + "；".join(d["context_notes"]))
    if d.get("xg"):
        lam, mu = d["xg"]
        L.append(f"模型期望进球：{lam:.2f} : {mu:.2f}（合计 {lam + mu:.2f}）")
    if d.get("probs"):
        p = d["probs"]
        L.append(f"胜平负：主胜 {_pct(p.get('home'))} / 平 {_pct(p.get('draw'))} / 客胜 {_pct(p.get('away'))}")
    if d.get("over_under25"):
        ou = d["over_under25"]
        L.append(f"大小球2.5：大 {_pct(ou.get('over'))} / 小 {_pct(ou.get('under'))}")
    if d.get("goal_bands"):
        L.append("进球区间：" + " / ".join(f"{k} {_pct(v)}" for k, v in d["goal_bands"].items()))
    if d.get("btts") is not None:
        L.append(f"双方进球(BTTS)：是 {_pct(d['btts'])}")
    if d.get("correct_score_top"):
        L.append("最可能比分：" + "，".join(f"{x['score']} {_pct(x['prob'])}" for x in d["correct_score_top"][:5]))
    if d.get("upset"):
        u = d["upset"]
        facs = "；".join(f["detail"] for f in u.get("factors", []))
        L.append(f"爆冷指数：{u.get('index')}/100（{u.get('level')}）。因子：{facs}")
    if d.get("strength"):
        s = d["strength"]
        dims = " / ".join(f"{k}:{s['dims_home'].get(k):.0f}-{s['dims_away'].get(k):.0f}"
                          for k in s.get("dims_home", {}))
        L.append(f"综合实力(0-100)：{d.get('home')} {s.get('score_home'):.0f} · "
                 f"{d.get('away')} {s.get('score_away'):.0f}；分项(主-客) {dims}")
    if d.get("goal_rec"):
        g = d["goal_rec"]
        L.append(f"进球区间推荐：{g.get('recommend')}（{'/'.join(r for r in g.get('reasons', []))}）")
    if d.get("h2h"):
        h = d["h2h"]
        L.append(f"历史交锋：共 {h.get('total')} 场，{d.get('home')} {h.get('a_win')}胜{h.get('draw')}平{h.get('a_loss')}负，"
                 f"场均 {h.get('avg_gf')}:{h.get('avg_ga')}")
    for side in ("home_form", "away_form"):
        f = d.get(side)
        if f:
            nm = d.get("home") if side == "home_form" else d.get("away")
            L.append(f"{nm} 近 {f.get('n')} 场：{f.get('w')}胜{f.get('d')}平{f.get('l')}负（进{f.get('gf')}失{f.get('ga')}）")
    if d.get("odds_value"):
        L.append("赔率价值(用户输入赔率)：" + d["odds_value"])
    if d.get("squad_value"):
        L.append("阵容身价：" + d["squad_value"])
    if d.get("tactics"):
        L.append("战术研判：" + d["tactics"])
    if d.get("fatigue"):
        L.append("体能与旅行：" + d["fatigue"])
    if d.get("news_titles"):
        L.append("相关新闻标题：" + "；".join(d["news_titles"][:8]))
    if d.get("extra_text"):
        L.append("用户补充材料：" + d["extra_text"])
    return "\n".join(L)


def build_parlay_context(legs: list[dict], summary: dict) -> str:
    """串关上下文：各关 + 组合概率/赔率/价值。"""
    L = ["这是一个串关（多场组合）。请基于以下各关与组合信息回答。"]
    L.append(f"共 {len(legs)} 关；串关总概率 {summary.get('combined_prob', 0):.2%}、"
             f"总赔率 {summary.get('combined_odds', 0):.2f}、模型期望价值 {summary.get('edge', 0):+.1%}。")
    for i, lg in enumerate(legs, 1):
        L.append(f"第{i}关：{lg.get('match')} · {lg.get('market', '')} · {lg.get('label')}"
                 f"（模型概率 {lg.get('model_prob', 0):.0%}，赔率 {lg.get('odds', 0):.2f}）")
    L.append("注意：串关假设各关独立，关数越多命中率指数下降，组合概率是乐观上限；仅供参考、非投注建议。")
    return "\n".join(L)


def ask(question: str, context: str, history: list[dict] | None = None,
        max_tokens: int = 800, system: str | None = None,
        context_label: str = "比赛数据") -> dict:
    """返回 {text, source}。source: 'llm' 成功 / 'error' 失败（含原因，不抛出）。

    system/context_label 可覆盖，供全局赛事对话等场景复用同一问答骨架。"""
    convo = ""
    for h in (history or [])[-6:]:
        who = "用户" if h.get("role") == "user" else "助手"
        convo += f"{who}：{h.get('content', '')}\n"
    prompt = (f"【{context_label}】\n{context}\n\n"
              f"【对话历史】\n{convo or '（无）'}\n"
              f"【当前问题】{question}\n请基于上面的{context_label}回答：")
    try:
        text = provider.chat(prompt, system=system or _SYSTEM,
                             max_tokens=max_tokens, temperature=0.3)
        return {"text": text, "source": "llm"}
    except provider.LLMError as exc:
        return {"text": f"LLM 调用失败：{exc}", "source": "error"}
