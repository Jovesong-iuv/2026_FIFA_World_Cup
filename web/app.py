"""2026 世界杯预测 Streamlit 看板（赛程驱动 + 中文 + 证据 + 资讯）。

启动： streamlit run web/app.py
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from wc2026 import auth
from wc2026.config import settings
from wc2026.data.db import get_conn
from wc2026.data.ingest import ingest_international_results
from wc2026.data.sources import news as news_mod
from wc2026.data.sources.fixtures_2026 import fetch_and_store_fixtures
from wc2026.data.team_names import zh
from wc2026.llm import reasoning
from wc2026.markets import derive, value
from wc2026.models.predictor import DC_PATH, ELO_PATH, get_model, train_and_save

st.set_page_config(page_title="2026 世界杯预测", page_icon="⚽", layout="wide")
HOSTS = {"Mexico", "Canada", "United States"}


def inject_design_system() -> None:
    st.markdown(
        """
        <style>
        :root {
            --wc-bg: #f5f7fb;
            --wc-surface: #ffffff;
            --wc-surface-2: #eef4f8;
            --wc-text: #17202a;
            --wc-muted: #64748b;
            --wc-line: #d8e1ea;
            --wc-primary: #0f766e;
            --wc-accent: #b45309;
            --wc-danger: #b91c1c;
        }
        .stApp {
            background:
                linear-gradient(180deg, rgba(15, 118, 110, .08), rgba(15, 118, 110, 0) 260px),
                var(--wc-bg);
            color: var(--wc-text);
        }
        section[data-testid="stSidebar"] {
            background: #102026;
            border-right: 1px solid rgba(255,255,255,.08);
        }
        section[data-testid="stSidebar"] * {
            color: #e8f1f2 !important;
        }
        section[data-testid="stSidebar"] div[data-baseweb="radio"] label,
        section[data-testid="stSidebar"] div[data-baseweb="checkbox"] label {
            background: rgba(255,255,255,.06);
            border: 1px solid rgba(255,255,255,.10);
            border-radius: 8px;
            padding: 7px 9px;
            margin-bottom: 6px;
        }
        .block-container {
            padding-top: 2rem;
            max-width: 1360px;
        }
        div[data-testid="stMetric"] {
            background: var(--wc-surface);
            border: 1px solid var(--wc-line);
            border-radius: 8px;
            padding: 14px 16px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, .05);
        }
        div[data-testid="stMetric"] label {
            color: var(--wc-muted) !important;
            font-weight: 600;
        }
        div[data-testid="stDataFrame"],
        div[data-testid="stDataEditor"] {
            border: 1px solid var(--wc-line);
            border-radius: 8px;
            overflow: hidden;
            background: var(--wc-surface);
        }
        div[data-testid="stExpander"] {
            border: 1px solid var(--wc-line);
            border-radius: 8px;
            background: rgba(255,255,255,.82);
        }
        .stButton > button,
        .stFormSubmitButton > button {
            border-radius: 8px;
            border: 1px solid rgba(15, 118, 110, .24);
            background: #0f766e;
            color: white;
            font-weight: 700;
            min-height: 42px;
        }
        .stButton > button:hover,
        .stFormSubmitButton > button:hover {
            border-color: #0f766e;
            background: #115e59;
            color: white;
        }
        .wc-hero {
            background: linear-gradient(135deg, #102026 0%, #123c3a 52%, #6b3f12 100%);
            border: 1px solid rgba(255,255,255,.08);
            border-radius: 8px;
            padding: 22px 24px;
            margin-bottom: 18px;
            color: #f8fafc;
            box-shadow: 0 18px 44px rgba(15, 23, 42, .16);
        }
        .wc-hero h1 {
            margin: 0;
            font-size: 30px;
            line-height: 1.2;
            letter-spacing: 0;
        }
        .wc-hero p {
            margin: 8px 0 0;
            color: #d7e5e5;
            font-size: 15px;
            line-height: 1.55;
        }
        .wc-kicker {
            color: #facc15;
            font-size: 12px;
            font-weight: 800;
            letter-spacing: .08em;
            text-transform: uppercase;
            margin-bottom: 6px;
        }
        .wc-section {
            color: var(--wc-text);
            font-size: 18px;
            font-weight: 800;
            margin: 20px 0 10px;
        }
        .wc-note {
            color: var(--wc-muted);
            font-size: 13px;
            line-height: 1.55;
        }
        .wc-login {
            max-width: 460px;
            margin: 10vh auto 0;
            background: white;
            border: 1px solid var(--wc-line);
            border-radius: 8px;
            padding: 26px;
            box-shadow: 0 24px 60px rgba(15, 23, 42, .12);
        }
        .wc-login h1 {
            font-size: 26px;
            margin: 0 0 6px;
        }
        .wc-login p {
            margin: 0 0 18px;
            color: var(--wc-muted);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(title: str, subtitle: str, kicker: str = "WORLD CUP MODEL") -> None:
    st.markdown(
        f"""
        <div class="wc-hero">
            <div class="wc-kicker">{kicker}</div>
            <h1>{title}</h1>
            <p>{subtitle}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_title(text: str) -> None:
    st.markdown(f'<div class="wc-section">{text}</div>', unsafe_allow_html=True)


def require_login() -> dict:
    if st.session_state.get("auth_user"):
        return {"username": st.session_state["auth_user"], "role": st.session_state.get("auth_role", "user")}
    st.markdown(
        """
        <div class="wc-login">
            <h1>2026 世界杯预测</h1>
            <p>登录后进入模型预测、价值分析与串关组合工作台。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("login_form"):
        username = st.text_input("账号")
        password = st.text_input("密码", type="password")
        submitted = st.form_submit_button("登录")
    if submitted:
        if auth.verify_login(username, password):
            st.session_state["auth_user"] = username.strip()
            st.session_state["auth_role"] = auth.user_role(username.strip())
            st.rerun()
        else:
            st.error("账号或密码错误。")
    st.stop()


def render_admin_user_panel() -> None:
    st.divider()
    st.caption(f"当前用户：{st.session_state.get('auth_user')}")
    if st.button("退出登录"):
        for key in ("auth_user", "auth_role"):
            st.session_state.pop(key, None)
        st.rerun()
    if st.session_state.get("auth_role") != "admin":
        return
    with st.expander("管理员 · 创建用户", expanded=False):
        with st.form("create_user_form"):
            new_username = st.text_input("新账号")
            new_password = st.text_input("新密码", type="password")
            submitted = st.form_submit_button("创建")
        if submitted:
            if auth.create_user(new_username, new_password):
                st.success(f"已创建用户：{new_username.strip()}")
            else:
                st.error("创建失败：账号为空、密码为空或账号已存在。")


def render_user_management() -> None:
    render_hero("用户管理", "查看本地账号信息、创建用户，并为用户重置密码。", "ADMIN")
    if st.session_state.get("auth_role") != "admin":
        st.error("仅管理员可访问。")
        return
    rows = auth.list_users()
    st.dataframe(pd.DataFrame([{
        "账号": r["username"],
        "角色": r["role"],
        "密码哈希摘要": r["password_hash_preview"],
        "创建时间": r["created_at"],
        "更新时间": r["updated_at"],
    } for r in rows]), hide_index=True, width="stretch")
    st.caption("密码采用哈希存储，不能查看明文；需要变更时请重置密码。")
    st.markdown("**重置密码**")
    usernames = [r["username"] for r in rows]
    with st.form("reset_password_form"):
        username = st.selectbox("账号", usernames)
        new_password = st.text_input("新密码", type="password")
        submitted = st.form_submit_button("重置密码")
    if submitted:
        if auth.reset_password(username, new_password):
            st.success(f"已重置 {username} 的密码。")
            st.rerun()
        else:
            st.error("重置失败：账号不存在或密码为空。")


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


def model_updated_label() -> str:
    stamps = [p.stat().st_mtime for p in (DC_PATH, ELO_PATH) if p.exists()]
    if not stamps:
        return "暂无本地模型文件时间"
    return datetime.fromtimestamp(max(stamps)).strftime("%Y-%m-%d %H:%M:%S")


def best_odds_value(key: str, fallback: float) -> float:
    val = st.session_state.get(key)
    if val and val > 1.0:
        return float(round(val, 2))
    return float(round(fallback, 2))


def odds_key(prefix: str, *parts) -> str:
    return ":".join([prefix, home, away, *[str(p) for p in parts]])


def predict_1x2_for_match(match: dict, neutral: bool = True) -> dict:
    mat = model.score_matrix(match["home_team"], match["away_team"], neutral)
    probs = derive.outcomes_1x2(mat)
    fair = {k: derive.to_fair_odds(v) for k, v in probs.items()}
    return {"probs": probs, "fair_odds": fair}


def value_candidates_for_match(match: dict, neutral: bool = True) -> list[dict]:
    home_team, away_team = match["home_team"], match["away_team"]
    mat = model.score_matrix(home_team, away_team, neutral)
    lam, mu = model.expected_goals(home_team, away_team, neutral)
    return derive.market_candidates(mat, lam, mu, zh(home_team), zh(away_team))


def render_parlay_builder() -> None:
    render_hero(
        "串关组合",
        "选择多场比赛；每场从单场「价值 & 凯利」同口径参数里单选一个，再计算串关总概率、总赔率和期望值。",
        "PARLAY BUILDER",
    )
    if not fixtures:
        st.warning("暂无可预测赛程，请先刷新赛程或初始化数据。")
        return
    groups = sorted({f["group_name"] for f in fixtures})
    g = st.selectbox("筛选分组", ["全部"] + groups, key="parlay_group")
    flist = [f for f in fixtures if g == "全部" or f["group_name"] == g]
    selected_idx = st.multiselect(
        "选择串关场次",
        range(len(flist)),
        default=[],
        format_func=lambda i: f"{zh(flist[i]['home_team'])} vs {zh(flist[i]['away_team'])} ({flist[i]['date_utc'][:10]})",
    )
    stake = st.number_input("本组串关投注金额", min_value=0.0, value=100.0, step=10.0)
    parlay_markets = st.multiselect(
        "显示参数类型",
        ["胜平负", "半全场胜平负", "让球", "大小球", "进球个数", "比分"],
        default=["胜平负", "半全场胜平负", "让球", "大小球", "进球个数", "比分"],
    )
    legs = []
    if selected_idx:
        section_title("逐场参数选择")
    for pos, idx in enumerate(selected_idx, start=1):
        match = flist[idx]
        candidates = [
            c for c in value_candidates_for_match(match, neutral=match["home_team"] not in HOSTS)
            if c["market"] in parlay_markets
        ]
        if not candidates:
            st.warning(f"{zh(match['home_team'])} vs {zh(match['away_team'])} 暂无可选参数。")
            continue
        st.markdown(f"**{pos}. {zh(match['home_team'])} vs {zh(match['away_team'])}**")
        top_by_market = {}
        market_order = {name: i for i, name in enumerate(["胜平负", "半全场胜平负", "让球", "大小球", "进球个数", "比分"])}
        sorted_candidates = sorted(
            candidates,
            key=lambda r: (market_order.get(r["market"], 99), -r["model_prob"], r["label"]),
        )
        for row in sorted_candidates:
            cur = top_by_market.get(row["market"])
            if cur is None or row["model_prob"] > cur["model_prob"]:
                top_by_market[row["market"]] = row
        top_keys = {row["key"] for row in top_by_market.values()}
        table_rows = []
        for row in sorted_candidates:
            table_rows.append({
                "选择": False,
                "key": row["key"],
                "市场": row["market"],
                "选项": row["label"],
                "概率": row["model_prob"],
                "概率显示": f"{row['model_prob']:.1%}",
                "默认赔率": round(row["odds"], 2),
                "实际赔率": round(row["odds"], 2),
                "标记": "本类最高概率" if row["key"] in top_keys else "",
            })
        edited = st.data_editor(
            pd.DataFrame(table_rows),
            hide_index=True,
            width="stretch",
            disabled=["key", "市场", "选项", "概率显示", "默认赔率", "标记"],
            column_order=["选择", "市场", "选项", "概率显示", "默认赔率", "实际赔率", "标记"],
            column_config={
                "选择": st.column_config.CheckboxColumn("选择"),
                "默认赔率": st.column_config.NumberColumn("默认赔率", format="%.2f"),
                "实际赔率": st.column_config.NumberColumn("实际赔率", min_value=1.01, step=0.01, format="%.2f"),
            },
            key=f"parlay_table:{match['match_number']}:{pos}",
        )
        selected_rows = edited[edited["选择"]]
        if len(selected_rows) > 1:
            st.warning("每场只能选一个参数；当前按表格中第一个勾选项计算。")
        if selected_rows.empty:
            st.caption("本场未选择参数，暂不纳入串关。")
            continue
        selected = selected_rows.iloc[0]
        chosen = next(c for c in candidates if c["key"] == selected["key"])
        odds_input = float(selected["实际赔率"])
        legs.append({
            "match": f"{zh(match['home_team'])} vs {zh(match['away_team'])}",
            "market": chosen["market"],
            "label": chosen["label"],
            "model_prob": chosen["model_prob"],
            "odds": odds_input,
        })
    summary = value.parlay_summary(legs, stake)
    if not summary["legs"]:
        st.info("请选择至少一场比赛，并在每场表格中勾选一个参数。")
        return
    st.divider()
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("串关总概率", f"{summary['combined_prob']:.2%}")
    m2.metric("串关总赔率", f"{summary['combined_odds']:.2f}")
    m3.metric("潜在返还", f"{summary['potential_return']:.2f}")
    m4.metric("模型期望收益", f"{summary['expected_profit']:.2f}", f"{summary['edge']:+.1%}")
    st.dataframe(pd.DataFrame([{
        "场次": r["match"],
        "市场": r.get("market", ""),
        "选择": r["label"],
        "模型概率": f"{r['model_prob']:.1%}",
        "赔率": f"{r['odds']:.2f}",
        "单关价值": f"{r['edge']:+.1%}",
    } for r in summary["legs"]]), hide_index=True, width="stretch")
    st.caption("串关假设各场结果近似独立；关数越多，命中率会快速下降。仅供概率辅助，不代表盈利保证。")


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


inject_design_system()
user = require_login()
model = load_model()
fixtures = load_fixtures()

render_hero(
    "2026 世界杯预测工作台",
    "比分概率、盘口价值、串关组合与证据分析集中在一个可操作界面中。模型结论仅供参考，请理性参与并遵守当地法规。",
)

with st.sidebar:
    st.header("功能")
    page_options = ["单场分析", "串关组合"]
    if user["role"] == "admin":
        page_options.append("用户管理")
    page = st.radio("页面", page_options, horizontal=True)
    render_admin_user_panel()
    st.divider()
    if page == "串关组合":
        st.caption("LLM 理由/分析：" + ("✅ 已配置，可手动触发" if llm_configured() else "⚠️ 规则模板(未接入)"))

if page == "串关组合":
    render_parlay_builder()
    st.stop()
if page == "用户管理":
    render_user_management()
    st.stop()

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

section_title(f"{zh(home)} vs {zh(away)}")
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
st.caption(f"数据刷新说明：胜平负和模型预期进球由当前本地模型即时计算；模型文件最近更新时间 {model_updated_label()}。侧边栏「一键全量刷新」或脚本/API 刷新后才会重训并更新。")

left, right = st.columns([3, 2])
with left:
    section_title("比分概率热力图")
    n = mat.shape[0]
    fig = go.Figure(go.Heatmap(
        z=mat, x=[str(j) for j in range(n)], y=[str(i) for i in range(n)],
        colorscale="Blues",
        hovertemplate=f"{zh(home)} %{{y}} - %{{x}} {zh(away)}<br>概率 %{{z:.1%}}<extra></extra>"))
    fig.update_layout(xaxis_title=f"{zh(away)} 进球", yaxis_title=f"{zh(home)} 进球",
                      height=400, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")
with right:
    section_title("为什么")
    reason_key = f"reason:{home}:{away}:{neutral}:{use_context}:{tank_risk}"
    display_reason = st.session_state.get(reason_key, reason)
    if llm_configured() and st.button("🤖 手动生成 AI 理由", key=f"ai_reason:{home}:{away}:{neutral}:{use_context}:{tank_risk}"):
        with st.spinner("生成 AI 理由…"):
            display_reason = reasoning.generate_reason(model, home, away, neutral, markets, use_llm=True)
        st.session_state[reason_key] = display_reason
    st.info(display_reason["text"])
    st.caption("来源：" + ("🤖 AI 生成" if display_reason["source"] == "llm" else "📋 规则模板"))

section_title("各市场概率")
half_full = derive.half_full_time(lam, mu)
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
m4, m5, m6 = st.columns(3)
with m4:
    st.caption("半全场胜平负")
    st.dataframe(pd.DataFrame([{"半全场": k, "概率": f"{v:.1%}"}
                              for k, v in sorted(half_full.items(), key=lambda kv: kv[1], reverse=True)]),
                 hide_index=True, width="stretch")
with m5:
    st.caption("进球个数")
    st.dataframe(pd.DataFrame([{"进球数": k, "概率": f"{v:.1%}"}
                              for k, v in markets["goal_bands"].items()]),
                 hide_index=True, width="stretch")
with m6:
    st.caption("说明")
    st.write("半全场按主队视角：第一个字=上半场结果，第二个字=全场结果。")

with st.expander("💰 价值 & 凯利（输入体彩/盘口赔率）", expanded=False):
    st.caption("输入该场实际赔率(十进制/欧赔)，对比模型概率找价值盘。默认填的是模型公平赔率。")
    vc1, vc2, vc3 = st.columns(3)
    if st.button("🔄 拉取本场可用赔率预填", help="需要 ODDS_API_KEY；会尝试预填胜平负、让球、大小球等 The Odds API 支持的市场。"):
        from wc2026.data.sources import odds_api
        try:
            with st.spinner("拉取 The Odds API 赔率…"):
                odds_map = odds_api.fetch_event_odds()
                st.session_state["odds_quota"] = odds_api.last_quota()
            event_odds = odds_map.get((home, away)) or odds_map.get((away, home)) or {}
            if not event_odds:
                st.warning("没有找到本场赔率，可能该场还未开放或队名未匹配。")
            else:
                h2h = event_odds.get("h2h", {})
                st.session_state[odds_key("odds_1x2", "home")] = h2h.get("home", 0.0)
                st.session_state[odds_key("odds_1x2", "draw")] = h2h.get("draw", 0.0)
                st.session_state[odds_key("odds_1x2", "away")] = h2h.get("away", 0.0)
                if h2h.get("home", 0.0) > 1.0:
                    st.session_state[odds_key("odds_1x2_input", "home")] = float(h2h["home"])
                if h2h.get("draw", 0.0) > 1.0:
                    st.session_state[odds_key("odds_1x2_input", "draw")] = float(h2h["draw"])
                if h2h.get("away", 0.0) > 1.0:
                    st.session_state[odds_key("odds_1x2_input", "away")] = float(h2h["away"])
                st.session_state[odds_key("event_odds")] = event_odds
                st.success("已拉取可用赔率并预填；没有的市场仍保留模型公平赔率。")
            render_quota(st.session_state.get("odds_quota", {}))
        except Exception as exc:
            st.error(f"赔率拉取失败：{exc}")
    event_odds = st.session_state.get(odds_key("event_odds"), {})
    o_home = vc1.number_input(f"{zh(home)}胜 赔率", min_value=1.01,
                              value=best_odds_value(odds_key("odds_1x2", "home"), odds["home"]),
                              step=0.01, key=odds_key("odds_1x2_input", "home"))
    o_draw = vc2.number_input("平局 赔率", min_value=1.01,
                              value=best_odds_value(odds_key("odds_1x2", "draw"), odds["draw"]),
                              step=0.01, key=odds_key("odds_1x2_input", "draw"))
    o_away = vc3.number_input(f"{zh(away)}胜 赔率", min_value=1.01,
                              value=best_odds_value(odds_key("odds_1x2", "away"), odds["away"]),
                              step=0.01, key=odds_key("odds_1x2_input", "away"))
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

    st.divider()
    st.markdown("**投注分配器**")
    st.caption("输入总金额与实际赔率，按当前页面概率计算正期望候选项，并用 1/4 凯利权重归一分配。未出现正期望时不会建议下注。")
    bankroll = st.number_input("计划投入金额", min_value=0.0, value=100.0, step=10.0)
    include_markets = st.multiselect(
        "纳入计算的市场",
        ["胜平负", "半全场胜平负", "让球", "大小球", "进球个数", "比分"],
        default=["胜平负", "半全场胜平负", "让球", "大小球", "进球个数", "比分"],
    )
    stake_candidates = []
    if "胜平负" in include_markets:
        stake_candidates.extend([
            {"key": "1x2_home", "market": "胜平负", "label": f"{zh(home)}胜",
             "model_prob": x["home"], "odds": o_home},
            {"key": "1x2_draw", "market": "胜平负", "label": "平局",
             "model_prob": x["draw"], "odds": o_draw},
            {"key": "1x2_away", "market": "胜平负", "label": f"{zh(away)}胜",
             "model_prob": x["away"], "odds": o_away},
        ])
    if "让球" in include_markets:
        ah_line = st.selectbox("让球盘口线（主队视角）", list(markets["asian_handicap"].keys()), index=3)
        ah = markets["asian_handicap"][ah_line]
        ah1, ah2 = st.columns(2)
        fair_ah_home = derive.to_fair_odds(ah["home_win"])
        fair_ah_away = derive.to_fair_odds(ah["home_loss"])
        pulled_ah = event_odds.get("spreads", {}).get(ah_line, {})
        o_ah_home = ah1.number_input(
            f"{zh(home)} 让球赢 赔率",
            min_value=1.01,
            value=float(round(pulled_ah.get("home") or fair_ah_home, 2)),
            step=0.01,
            key=f"ah_home:{home}:{away}:{ah_line}",
        )
        o_ah_away = ah2.number_input(
            f"{zh(away)} 让球赢 赔率",
            min_value=1.01,
            value=float(round(pulled_ah.get("away") or fair_ah_away, 2)),
            step=0.01,
            key=f"ah_away:{home}:{away}:{ah_line}",
        )
        stake_candidates.extend([
            {"key": f"ah_{ah_line}_home", "market": "让球", "label": f"{zh(home)} {ah_line} 赢",
             "model_prob": ah["home_win"], "push_prob": ah["push"], "odds": o_ah_home},
            {"key": f"ah_{ah_line}_away", "market": "让球", "label": f"{zh(away)} {-float(ah_line):g} 赢",
             "model_prob": ah["home_loss"], "push_prob": ah["push"], "odds": o_ah_away},
        ])
    if "大小球" in include_markets:
        ou_line = st.selectbox("大小球盘口", list(markets["over_under"].keys()), index=1)
        ou = markets["over_under"][ou_line]
        ou1, ou2 = st.columns(2)
        pulled_ou = event_odds.get("totals", {}).get(ou_line, {})
        o_over = ou1.number_input(
            f"大 {ou_line} 赔率",
            min_value=1.01,
            value=float(round(pulled_ou.get("over") or derive.to_fair_odds(ou["over"]), 2)),
            step=0.01,
            key=f"ou_over:{home}:{away}:{ou_line}",
        )
        o_under = ou2.number_input(
            f"小 {ou_line} 赔率",
            min_value=1.01,
            value=float(round(pulled_ou.get("under") or derive.to_fair_odds(ou["under"]), 2)),
            step=0.01,
            key=f"ou_under:{home}:{away}:{ou_line}",
        )
        stake_candidates.extend([
            {"key": f"ou_{ou_line}_over", "market": "大小球", "label": f"大 {ou_line}",
             "model_prob": ou["over"], "push_prob": ou["push"], "odds": o_over},
            {"key": f"ou_{ou_line}_under", "market": "大小球", "label": f"小 {ou_line}",
             "model_prob": ou["under"], "push_prob": ou["push"], "odds": o_under},
        ])
    if "进球个数" in include_markets:
        st.caption("进球个数按总进球分组：0-1、2-3、4+。")
        gb_cols = st.columns(3)
        for idx, (label, prob) in enumerate(markets["goal_bands"].items()):
            gb_odds = gb_cols[idx].number_input(
                f"{label} 赔率",
                min_value=1.01,
                value=float(round(derive.to_fair_odds(prob), 2)),
                step=0.01,
                key=f"goal_band:{home}:{away}:{label}",
            )
            stake_candidates.append({
                "key": f"goal_band_{label}",
                "market": "进球个数",
                "label": label,
                "model_prob": prob,
                "odds": gb_odds,
            })
    if "比分" in include_markets:
        st.caption("比分只展示当前模型 Top 6；请填你实际能买到的正确比分赔率。")
        for idx, item in enumerate(markets["correct_score_top"]):
            fair_score = derive.to_fair_odds(item["prob"])
            score_odds = st.number_input(
                f"{item['score']} 赔率（模型概率 {item['prob']:.1%}）",
                min_value=1.01,
                value=float(round(fair_score, 2)),
                step=0.1,
                key=f"score_odds:{home}:{away}:{idx}:{item['score']}",
            )
            stake_candidates.append({
                "key": f"score_{item['score']}",
                "market": "比分",
                "label": item["score"],
                "model_prob": item["prob"],
                "odds": score_odds,
            })
    if "半全场胜平负" in include_markets:
        st.caption("半全场胜平负为 9 种组合，按主队视角显示：胜胜、胜平、胜负、平胜、平平、平负、负胜、负平、负负。请填实际赔率。")
        for idx, (label, prob) in enumerate(sorted(half_full.items(), key=lambda kv: kv[1], reverse=True)):
            hf_odds = st.number_input(
                f"{label} 赔率（模型概率 {prob:.1%}）",
                min_value=1.01,
                value=float(round(derive.to_fair_odds(prob), 2)),
                step=0.1,
                key=f"half_full:{home}:{away}:{idx}:{label}",
            )
            stake_candidates.append({
                "key": f"half_full_{label}",
                "market": "半全场胜平负",
                "label": label,
                "model_prob": prob,
                "odds": hf_odds,
            })
    allocation = value.allocate_stakes(stake_candidates, bankroll)
    if allocation:
        st.dataframe(pd.DataFrame([{
            "市场": r["market"],
            "选择": r["label"],
            "模型概率": f"{r['model_prob']:.1%}",
            "赔率": f"{r['odds']:.2f}",
            "价值": f"{r['edge']:+.1%}",
            "分配比例": f"{r['allocation_pct']:.1%}",
            "建议金额": f"{r['stake']:.2f}",
            "模型期望收益": f"{r['expected_profit']:.2f}",
        } for r in allocation]), hide_index=True, width="stretch")
    else:
        st.info("当前输入赔率下没有正期望候选项，建议不下注或重新核对赔率。")

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
