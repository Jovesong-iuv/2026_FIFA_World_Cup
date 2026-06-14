"""单场 AI 对话：把该场已算出的预测与已拉取/库内数据汇总成上下文，调用 LLM 作答。

build_context 为纯函数（dict → 文本），便于测试；ask 调用 provider.chat（需 LLM，费 token）。
只回答基于给定数据的问题，不编造数字；分析仅供参考、非投注建议。
"""
from __future__ import annotations

from wc2026.llm import provider

_SYSTEM = (
    "你是一名世界杯赔率与比赛分析师。严格依据【比赛数据】中给出的信息用中文回答，"
    "简洁专业、有条理。数据中没有的内容要明说「数据未提供」，不要编造具体数字或赔率。"
    "始终提醒：模型与概率存在误差，内容仅供参考，非投注建议。"
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
    if d.get("news_titles"):
        L.append("相关新闻标题：" + "；".join(d["news_titles"][:8]))
    if d.get("extra_text"):
        L.append("用户补充材料：" + d["extra_text"])
    return "\n".join(L)


def ask(question: str, context: str, history: list[dict] | None = None,
        max_tokens: int = 800) -> dict:
    """返回 {text, source}。source: 'llm' 成功 / 'error' 失败（含原因，不抛出）。"""
    convo = ""
    for h in (history or [])[-6:]:
        who = "用户" if h.get("role") == "user" else "助手"
        convo += f"{who}：{h.get('content', '')}\n"
    prompt = (f"【比赛数据】\n{context}\n\n"
              f"【对话历史】\n{convo or '（无）'}\n"
              f"【当前问题】{question}\n请基于上面的比赛数据回答：")
    try:
        text = provider.chat(prompt, system=_SYSTEM, max_tokens=max_tokens, temperature=0.3)
        return {"text": text, "source": "llm"}
    except provider.LLMError as exc:
        return {"text": f"LLM 调用失败：{exc}", "source": "error"}
