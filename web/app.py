"""2026 世界杯预测 Streamlit 看板（赛程驱动 + 中文 + 证据 + 资讯）。

启动： streamlit run web/app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.data.ingest import ingest_international_results
from wc2026.data.sources import news as news_mod
from wc2026.data.sources.fixtures_2026 import fetch_and_store_fixtures
from wc2026.data.team_names import zh
from wc2026.llm import reasoning
from wc2026.markets import derive, value
from wc2026.models.predictor import get_model, train_and_save

st.set_page_config(page_title="2026 世界杯预测", page_icon="⚽", layout="wide")
HOSTS = {"Mexico", "Canada", "United States"}


@st.cache_resource
def load_model():
    return get_model()


@st.cache_data
def load_fixtures():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT match_number, date_utc, home_team, away_team, group_name, location "
            "FROM fixtures WHERE predictable=1 ORDER BY date_utc"
        ).fetchall()
    return [dict(r) for r in rows]


def llm_configured():
    return settings.llm_enabled and bool(settings.llm_api_key)


def load_news(home, away):
    items = news_mod.fetch_for_teams([home, away])
    if items:
        return items, False
    return news_mod.fetch_all()[:8], True


def render_quota(quota: dict, label: str = "The Odds API") -> None:
    if not quota:
        return
    remaining = quota.get("remaining")
    used = quota.get("used")
    last = quota.get("last")
    limit = quota.get("limit")
    parts = []
    if remaining is not None:
        parts.append(f"剩余请求 {remaining}")
    if used is not None:
        parts.append(f"已用 {used}")
    if limit is not None:
        parts.append(f"上限 {limit}")
    if last is not None:
        parts.append(f"本次消耗 {last}")
    if parts:
        st.caption(f"{label} 配额：" + " · ".join(parts))


model = load_model()
fixtures = load_fixtures()

st.title("⚽ 2026 世界杯 · 比分 / 赔率 预测")
st.caption("基于 Dixon-Coles + 历史证据的概率参考 — 非盈利保证，请理性参与并遵守当地法规。")

with st.sidebar:
    st.header("选择比赛")
    mode = st.radio("方式", ["按赛程", "自定义对阵"], horizontal=True)
    venue_info = None
    if mode == "按赛程" and fixtures:
        groups = sorted({f["group_name"] for f in fixtures})
        g = st.selectbox("分组", ["全部"] + groups)
        flist = [f for f in fixtures if g == "全部" or f["group_name"] == g]
        idx = st.selectbox(
            "场次", range(len(flist)),
            format_func=lambda i: f"{zh(flist[i]['home_team'])} vs {zh(flist[i]['away_team'])} ({flist[i]['date_utc'][:10]})",
        )
        sel = flist[idx]
        home, away = sel["home_team"], sel["away_team"]
        venue_info = f"🗓 {sel['date_utc'][:16]} · {sel['group_name']} · 📍{sel['location']}"
        default_neutral = home not in HOSTS
    else:
        teams = model.teams
        di = teams.index("Spain") if "Spain" in teams else 0
        ai = teams.index("Germany") if "Germany" in teams else 1
        home = st.selectbox("主队", teams, index=di, format_func=zh)
        away = st.selectbox("客队", teams, index=ai, format_func=zh)
        default_neutral = True

    neutral = st.checkbox("中立场", value=default_neutral,
                         help="世界杯多数为中立场；东道主(美/加/墨)在本国默认非中立")
    use_context = st.checkbox("应用情境调整", value=False,
                             help="东道主额外加成；小组赛末轮出线压力(赛事中)")
    tank_risk = (st.checkbox("⚠️ 疑似控分/默契球", value=False,
                            help="末轮出线已定可能消极比赛/算计排名：下调进球并提示爆冷风险")
                 if use_context else False)
    st.divider()
    if st.button("🔄 一键全量刷新", help="重抓历史数据+重训模型+更新赛程"):
        with st.spinner("抓数据 + 重训 + 赛程中…"):
            ingest_international_results()
            train_and_save()
            try:
                fetch_and_store_fixtures()
            except Exception as exc:
                st.warning(f"赛程刷新失败：{exc}")
            st.cache_resource.clear()
            st.cache_data.clear()
        st.success("已刷新")
        st.rerun()
    st.divider()
    st.caption("LLM 理由/分析：" + ("✅ 已配置，可手动触发" if llm_configured() else "⚠️ 规则模板(未接入)"))

if home == away:
    st.warning("请选择两支不同的球队。")
    st.stop()

st.subheader(f"{zh(home)}　vs　{zh(away)}")
if venue_info:
    st.caption(venue_info)

if use_context:
    from wc2026.analysis import context
    adj = context.adjusted_prediction(model, home, away, neutral, tank_risk=tank_risk)
    mat, (lam, mu), context_notes = adj["matrix"], adj["exp_goals"], adj["notes"]
else:
    mat = model.score_matrix(home, away, neutral)
    lam, mu = model.expected_goals(home, away, neutral)
    context_notes = []
markets = derive.summarize(mat)
reason = reasoning.generate_reason(model, home, away, neutral, markets, use_llm=False)
x, odds = markets["1x2"], markets["1x2_fair_odds"]

if context_notes:
    st.info("🎯 情境调整：" + "；".join(context_notes))

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{zh(home)} 胜", f"{x['home']:.1%}", f"公平赔率 {odds['home']:.2f}")
c2.metric("平局", f"{x['draw']:.1%}", f"公平赔率 {odds['draw']:.2f}")
c3.metric(f"{zh(away)} 胜", f"{x['away']:.1%}", f"公平赔率 {odds['away']:.2f}")
c4.metric("模型预期进球", f"{lam:.2f} : {mu:.2f}")

left, right = st.columns([3, 2])
with left:
    st.markdown("**比分概率热力图**")
    n = mat.shape[0]
    fig = go.Figure(go.Heatmap(
        z=mat, x=[str(j) for j in range(n)], y=[str(i) for i in range(n)],
        colorscale="Blues",
        hovertemplate=f"{zh(home)} %{{y}} - %{{x}} {zh(away)}<br>概率 %{{z:.1%}}<extra></extra>"))
    fig.update_layout(xaxis_title=f"{zh(away)} 进球", yaxis_title=f"{zh(home)} 进球",
                      height=400, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
with right:
    st.markdown("**为什么 · 理由**")
    reason_key = f"reason:{home}:{away}:{neutral}:{use_context}:{tank_risk}"
    display_reason = st.session_state.get(reason_key, reason)
    if llm_configured() and st.button("🤖 手动生成 AI 理由", key=f"ai_reason:{home}:{away}:{neutral}:{use_context}:{tank_risk}"):
        with st.spinner("生成 AI 理由…"):
            display_reason = reasoning.generate_reason(model, home, away, neutral, markets, use_llm=True)
        st.session_state[reason_key] = display_reason
    st.info(display_reason["text"])
    st.caption("来源：" + ("🤖 AI 生成" if display_reason["source"] == "llm" else "📋 规则模板"))

st.markdown("**各市场概率**")
m1, m2, m3 = st.columns(3)
with m1:
    st.caption("大小球")
    st.dataframe(pd.DataFrame([{"盘口": l, "大": f"{d['over']:.1%}", "小": f"{d['under']:.1%}"}
                              for l, d in markets["over_under"].items()]),
                 hide_index=True, width="stretch")
with m2:
    st.caption(f"亚盘让球（{zh(home)}视角）")
    st.dataframe(pd.DataFrame([{"线": l, "主赢": f"{d['home_win']:.1%}", "走": f"{d['push']:.1%}", "主输": f"{d['home_loss']:.1%}"}
                              for l, d in markets["asian_handicap"].items()]),
                 hide_index=True, width="stretch")
with m3:
    st.caption("最可能比分")
    st.dataframe(pd.DataFrame([{"比分": d["score"], "概率": f"{d['prob']:.1%}"}
                              for d in markets["correct_score_top"]]),
                 hide_index=True, width="stretch")

with st.expander("💰 价值 & 凯利（输入体彩/盘口赔率）", expanded=False):
    st.caption("输入该场实际赔率(十进制/欧赔)，对比模型概率找价值盘。默认填的是模型公平赔率。")
    vc1, vc2, vc3 = st.columns(3)
    o_home = vc1.number_input(f"{zh(home)}胜 赔率", min_value=1.01, value=float(round(odds["home"], 2)), step=0.01)
    o_draw = vc2.number_input("平局 赔率", min_value=1.01, value=float(round(odds["draw"], 2)), step=0.01)
    o_away = vc3.number_input(f"{zh(away)}胜 赔率", min_value=1.01, value=float(round(odds["away"], 2)), step=0.01)
    analysis = value.analyze_1x2(x, {"home": o_home, "draw": o_draw, "away": o_away})
    imp = analysis["implied"]
    st.caption(f"盘口水位 overround = {imp['overround']:.3f}（超过 1 的部分是博彩抽水）")
    labels = {"home": f"{zh(home)}胜", "draw": "平局", "away": f"{zh(away)}胜"}
    vrows = []
    for k in ("home", "draw", "away"):
        r = analysis["results"][k]
        if not r:
            continue
        vrows.append({
            "结果": labels[k],
            "模型概率": f"{r['model_prob']:.1%}",
            "盘口隐含(剔水)": f"{imp['fair'].get(k, 0):.1%}",
            "赔率": f"{r['odds']:.2f}",
            "价值": f"{r['edge']:+.1%}",
            "判断": "✅ 有价值" if r["value"] else "—",
            "建议注码(¼凯利)": f"{r['kelly_frac']:.1%}",
        })
    st.dataframe(pd.DataFrame(vrows), hide_index=True, width="stretch")
    st.caption("⚠️ 价值>0 才有长期正期望；注码为占本金比例(已用 1/4 分数凯利)。模型有误差，仅供参考、量力而行。")

ev = reason["evidence"]
with st.expander("📊 证据 · 数据支撑（交锋 + 近况）", expanded=True):
    e1, e2 = st.columns(2)
    with e1:
        h2h = ev["h2h"]
        st.caption(f"历史交锋：共 {h2h['total']} 场，{zh(home)} {h2h['a_win']}胜{h2h['draw']}平{h2h['a_loss']}负，"
                   f"场均 {h2h['avg_gf']} : {h2h['avg_ga']}")
        if h2h["recent"]:
            st.dataframe(pd.DataFrame([
                {"日期": r["date"], "对阵": f"{zh(r['home'])} {r['score']} {zh(r['away'])}", "赛事": r["tournament"]}
                for r in h2h["recent"]]), hide_index=True, width="stretch")
        else:
            st.write("无历史交锋记录。")
    with e2:
        for side, name in [("home_form", zh(home)), ("away_form", zh(away))]:
            fm = ev[side]
            st.caption(f"{name} 近 {fm['n']} 场：{fm['w']}胜{fm['d']}平{fm['l']}负（进{fm['gf']}失{fm['ga']}）")
            st.dataframe(pd.DataFrame([
                {"日期": r["date"], "主客": r["ha"], "对手": zh(r["opponent"]), "比分": r["score"], "结果": r["outcome"]}
                for r in fm["matches"]]), hide_index=True, width="stretch")

with st.expander("📰 相关资讯", expanded=False):
    news_key = f"news:{home}:{away}"
    if st.button("🔄 手动刷新资讯", key=f"refresh_news:{home}:{away}"):
        with st.spinner("抓取相关资讯…"):
            items, fallback = load_news(home, away)
        st.session_state[news_key] = {"items": items, "fallback": fallback}

    cached_news = st.session_state.get(news_key)
    if cached_news:
        items, fallback = cached_news["items"], cached_news["fallback"]
        if fallback:
            st.caption("（暂无直接相关的国家队新闻，以下为综合足球头条）")
        if items:
            for it in items[:8]:
                st.markdown(f"- [{it['title']}]({it['link']}) · {it['source']}")
            if llm_configured():
                if st.button("🤖 手动分析资讯", key=f"analyze_news:{home}:{away}"):
                    ana = news_mod.analyze_news(home, away, items)
                    if ana:
                        st.info("🤖 AI 资讯分析：" + ana["text"])
                inj_key = f"injuries_data:{home}:{away}"
                if st.button("🤖 提取伤停 / 缺阵线索", key=f"injuries:{home}:{away}"):
                    with st.spinner("AI 从新闻抽取伤停线索…"):
                        st.session_state[inj_key] = news_mod.extract_injuries(home, away, items)
                inj = st.session_state.get(inj_key)
                if inj:
                    for side, nm in [("home", zh(home)), ("away", zh(away))]:
                        rows = inj.get(side) or []
                        if rows:
                            st.caption(f"🤕 {nm} 伤停 / 缺阵线索（新闻 + AI，粗粒度）")
                            st.dataframe(pd.DataFrame([
                                {"球员": r.get("player", ""), "状态": r.get("status", ""), "说明": r.get("note", "")}
                                for r in rows]), hide_index=True, width="stretch")
                        else:
                            st.caption(f"🤕 {nm}：标题中未见明确伤停信息")
                    st.caption("⚠️ 仅据新闻标题由 AI 推断，可能不全 / 滞后，仅供参考。")
            else:
                st.caption("ℹ️ AI 资讯分析需接入 LLM（当前不可用，仅展示资讯列表）。")
        else:
            st.write("暂无资讯。")
    else:
        st.caption("点击按钮后才会联网刷新资讯。")

with st.expander("👥 阵容 / 评分 / 伤停（FotMob · 免费无需 key · 仅展示，不影响概率）", expanded=False):
    from wc2026.data import squads as squads_mod

    st.caption("数据来自 FotMob（解析其公开页面，免费无需 key）。⚠️ 球员**评分**按赛季统计，"
               "世界杯赛前多为空（显示 —），开赛后逐场填充；**伤停**通常已实时（来自俱乐部伤情）。"
               "📋 本面板纯展示，不改变上方任何概率。已内置限速，请勿高频刷新。")

    if st.button("🔄 拉取本场两队阵容（FotMob）"):
        try:
            with st.spinner("从 FotMob 拉取两队阵容…"):
                r_home = squads_mod.refresh_fm_squad(home)
                r_away = squads_mod.refresh_fm_squad(away)
            st.success(
                f"已更新：{zh(home)} {r_home['count']} 人（评分 {r_home['rated']}·伤停 {r_home['injured']}） · "
                f"{zh(away)} {r_away['count']} 人（评分 {r_away['rated']}·伤停 {r_away['injured']}）")
        except Exception as exc:
            st.error(f"拉取失败：{exc}（FotMob 为非官方页面解析，结构变动/限流都可能导致失败）")

    if llm_configured() and st.button("🤖 AI 音译球员名（两队 · 结果缓存）"):
        try:
            with st.spinner("AI 音译球员名…"):
                t_home = squads_mod.translate_player_names(home)
                t_away = squads_mod.translate_player_names(away)
            st.success(f"已音译：{zh(home)} {t_home['translated']}/{t_home['total']} · "
                       f"{zh(away)} {t_away['translated']}/{t_away['total']}（以「中文（英文）」显示）")
        except Exception as exc:
            st.error(f"音译失败：{exc}")
    elif not llm_configured():
        st.caption("（接入 LLM 后可「AI 音译球员名」；当前未配置，球员名显示英文原名。）")

    sq_home = squads_mod.load_fm_squad(home)
    sq_away = squads_mod.load_fm_squad(away)
    if not sq_home and not sq_away:
        st.caption("点「🔄 拉取本场两队阵容（FotMob）」后展示（结果会缓存，再次查看不重复联网）。")
    else:
        sc1, sc2 = st.columns(2)
        for col, team, sq in [(sc1, home, sq_home), (sc2, away, sq_away)]:
            with col:
                st.markdown(f"**{zh(team)}**" + (f" · 更新 {sq['updated_at'][:10]}" if sq else ""))
                if not sq:
                    st.caption("无缓存数据。")
                    continue
                for pos, players in sq["groups"].items():
                    st.caption(squads_mod.POS_ZH.get(pos, pos))
                    st.dataframe(pd.DataFrame([{
                        "头像": p.get("photo_url"),
                        "号": p["number"],
                        "球员": (f"{p['name_zh']}（{p['player_name']}）" if p.get("name_zh") else p["player_name"]),
                        "队徽": p.get("logo_url"),
                        "俱乐部": p.get("club_zh") or p.get("club"),
                        "评分": (f"{p['rating']:.2f}" if p["rating"] is not None else "—"),
                        "状态": ("🤕 " + (p["injury_note"] or "伤停")) if p["injured"] else "",
                    } for p in players]), hide_index=True, width="stretch",
                    column_config={
                        "头像": st.column_config.ImageColumn("", width="small"),
                        "队徽": st.column_config.ImageColumn("", width="small"),
                    })

        def _pos_avg(sq):
            out = {}
            if not sq:
                return out
            for pos, players in sq["groups"].items():
                vals = [p["rating"] for p in players if p["rating"] is not None]
                if vals:
                    out[pos] = round(sum(vals) / len(vals), 2)
            return out

        avg_h, avg_a = _pos_avg(sq_home), _pos_avg(sq_away)
        poses = [p for p in squads_mod.POS_ORDER if p in avg_h or p in avg_a]
        if poses:
            st.markdown("**位置分组平均评分对比**")
            figp = go.Figure()
            figp.add_bar(name=zh(home), x=[squads_mod.POS_ZH.get(p, p) for p in poses],
                         y=[avg_h.get(p) for p in poses])
            figp.add_bar(name=zh(away), x=[squads_mod.POS_ZH.get(p, p) for p in poses],
                         y=[avg_a.get(p) for p in poses])
            figp.update_layout(barmode="group", height=300,
                               margin=dict(l=10, r=10, t=10, b=10), yaxis_title="平均评分")
            st.plotly_chart(figp, width="stretch")
        else:
            st.caption("（暂无评分数据——世界杯赛前 FotMob 评分多为空，开赛后逐场填充；伤停信息仍有效。）")


with st.expander("💰 价值扫描（全场次自动找价值盘，需 The Odds API key）", expanded=False):
    from wc2026.config import settings as _settings
    if not _settings.odds_api_key:
        st.warning("未配置 ODDS_API_KEY。注册 the-odds-api.com（免费）拿 key 填进 .env 重启即可。")
        st.caption("（上方「💰 价值 & 凯利」可手动输入单场赔率分析。）")
    else:
        st.warning("⚠️ 纯模型 vs 市场会产生大量**假价值**（本模型对部分队伍有高估、回测显示会失灵）。"
                   "超大 edge(>50%) 几乎一定是模型错而非庄家错。用下方滑块向市场收缩，只留温和分歧。")
        blend = st.slider("模型权重（越低越信市场，推荐 0.4–0.6）", 0.0, 1.0, 0.5, 0.1)
        if st.button("📟 查询 The Odds API 剩余请求"):
            from wc2026.data.sources import odds_api
            try:
                with st.spinner("查询配额…"):
                    st.session_state["odds_quota"] = odds_api.get_quota()
            except Exception as exc:
                st.error(f"配额查询失败：{exc}")
        render_quota(st.session_state.get("odds_quota", {}))
        if st.button("🔍 拉取当前赔率并扫描"):
            from wc2026.data.sources import odds_api
            try:
                with st.spinner("拉取赔率并扫描…"):
                    odds_map = odds_api.fetch_h2h_odds()
                    st.session_state["odds_quota"] = odds_api.last_quota()
                    scan = value.scan_value(model, odds_map, blend=blend)
                render_quota(st.session_state.get("odds_quota", {}))
                st.caption(f"共 {len(odds_map)} 场，找到 {len(scan)} 个价值项（模型权重={blend}）")
                if scan:
                    st.dataframe(pd.DataFrame([{
                        "对阵": f"{zh(r['home'])} vs {zh(r['away'])}",
                        "押": {"home": zh(r["home"]), "draw": "平", "away": zh(r["away"])}[r["outcome"]],
                        "赔率": r["odds"], "概率": f"{r['model_prob']:.0%}",
                        "价值": f"{r['edge']:+.0%}", "凯利¼": f"{r['kelly_frac']:.1%}",
                        "提示": ("⚠️模型偏差嫌疑" if r["edge"] > 0.5
                                else ("分歧较大需谨慎" if r["edge"] > 0.15 else "温和价值")),
                    } for r in scan]), hide_index=True, width="stretch")
                else:
                    st.write("收缩后无价值项——说明模型与市场无显著分歧（正常、健康）。")
            except Exception as exc:
                st.error(f"赔率获取失败：{exc}")

with st.expander("📈 模型回测（历届世界杯校准验证）", expanded=False):
    st.caption("样本外：用开赛前数据训练、预测该届。每届需训练约 10 秒。")
    if st.button("▶️ 运行回测（2014 / 2018 / 2022）"):
        from wc2026.backtest.runner import backtest_ensemble
        rows = []
        with st.spinner("训练并回测中…"):
            for y in ["2014", "2018", "2022"]:
                r = backtest_ensemble(y)
                rows.append({"届": y, "场次": r["n"], "LogLoss": f"{r['log_loss']:.4f}",
                             "基准": f"{r['baseline_log_loss']:.4f}", "Brier": f"{r['brier']:.3f}",
                             "准确率": f"{r['accuracy']:.1%}"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("LogLoss < 1.0986 = 比瞎猜有预测力。2022 是史上最大冷门届，模型会失灵——真实局限，不粉饰。")
