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
from wc2026.analysis.environment import match_environment_report
from wc2026.llm import reasoning
from wc2026.markets import derive, value
from wc2026.models.predictor import DC_PATH, ELO_PATH, get_model, train_and_save
from wc2026.access import owner_key_matches

st.set_page_config(page_title="2026 世界杯预测", page_icon="⚽", layout="wide")
HOSTS = {"Mexico", "Canada", "United States"}

# 登录开关：暂时关闭用户登录（登录/用户管理代码全部保留，置 True 即恢复登录墙）。
LOGIN_ENABLED = False


def current_theme() -> str:
    """返回当前 Streamlit 主题类型（'light'/'dark'），用于让自定义样式自适应。"""
    try:
        return st.context.theme.type or "light"
    except Exception:
        return "light"


def inject_design_system() -> None:
    dark = current_theme() == "dark"
    palette = (
        """
            --wc-bg: #0e1117;
            --wc-surface: #1b2130;
            --wc-surface-2: #232c3b;
            --wc-text: #f1f5f9;
            --wc-muted: #9aa7b6;
            --wc-line: #2c3442;
            --wc-primary: #14b8a6;
            --wc-accent: #f59e0b;
            --wc-danger: #ef4444;
        """
        if dark
        else """
            --wc-bg: #f5f7fb;
            --wc-surface: #ffffff;
            --wc-surface-2: #eef4f8;
            --wc-text: #17202a;
            --wc-muted: #64748b;
            --wc-line: #d8e1ea;
            --wc-primary: #0f766e;
            --wc-accent: #b45309;
            --wc-danger: #b91c1c;
        """
    )
    st.markdown(f"<style>:root {{{palette}}}</style>", unsafe_allow_html=True)
    st.markdown(
        """
        <style>
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
        /* 侧边栏始终为深色：下拉框/输入框/展开器自带浅色背景会让强制的浅色文字看不清，
           这里统一给它们深色背景，保证选项文字（分组/场次等）可读。 */
        section[data-testid="stSidebar"] [data-baseweb="select"] > div,
        section[data-testid="stSidebar"] [data-baseweb="input"],
        section[data-testid="stSidebar"] [data-baseweb="base-input"],
        section[data-testid="stSidebar"] [data-testid="stExpander"] {
            background-color: rgba(255,255,255,.06) !important;
            border-color: rgba(255,255,255,.16) !important;
        }
        section[data-testid="stSidebar"] [data-baseweb="select"] svg {
            fill: #e8f1f2 !important;
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
            background: var(--wc-surface);
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
            background: var(--wc-surface);
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
    if not LOGIN_ENABLED:
        return {"username": "guest", "role": "user"}  # 登录已关闭：直接放行为访客
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


def is_owner() -> bool:
    """所有者(可执行拉取/训练/AI 等费用动作)：未设 OWNER_KEY 则全功能(本机/单人)；
    设了 OWNER_KEY 则需 URL ?owner=<该值> 匹配，否则为只读访客。"""
    try:
        supplied_owner = st.query_params.get("owner", "")
    except Exception:
        supplied_owner = None
    return owner_key_matches(settings.owner_key, supplied_owner)


def action_button(label: str, **kwargs) -> bool:
    """需所有者权限的动作按钮：所有者正常渲染按钮；访客显示锁定提示并返回 False。"""
    if is_owner():
        return st.button(label, **kwargs)
    st.caption(f"🔒 {label} — 仅所有者可操作（访客只读）")
    return False


def render_access_banner() -> None:
    """侧栏显示当前访问模式；访客提示如何成为所有者。"""
    if is_owner():
        if settings.owner_key:
            st.caption("🔑 所有者模式：可拉取赔率 / 训练 / AI。")
    else:
        st.caption("👀 只读访客：可浏览与选择查看；拉取 / 训练 / AI 按钮已锁定（避免消耗配额与 token）。")


def get_client_ip() -> tuple[str, str]:
    """返回 (ip, user_agent)。优先取代理头 X-Forwarded-For / X-Real-Ip；本地无代理时回退。"""
    try:
        h = st.context.headers or {}
        ua = h.get("User-Agent") or h.get("user-agent") or ""
        xff = h.get("X-Forwarded-For") or h.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip(), ua
        xri = h.get("X-Real-Ip") or h.get("x-real-ip")
        if xri:
            return xri.strip(), ua
        return "本地/未知", ua
    except Exception:
        return "本地/未知", ""


def render_access_log() -> None:
    """所有者后台：访问 IP 记录 + 备注编辑（同 IP 再访问自动保留备注）。"""
    from wc2026.data import access_log
    section_title("访问记录（所有者后台）")
    rows = access_log.list_access()
    if not rows:
        st.caption("暂无访问记录。")
        return
    st.caption(f"共 {len(rows)} 个 IP。可在「备注」列填写姓名等并保存；同一 IP 再次访问会自动保留备注。")
    df = pd.DataFrame([{
        "IP": r["ip"], "备注": r["note"] or "", "访问次数": r["visits"],
        "首次": r["first_seen"], "最近": r["last_seen"],
        "User-Agent": (r["user_agent"] or "")[:60],
    } for r in rows])
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key="access_editor",
        column_config={c: st.column_config.Column(disabled=True)
                       for c in ["IP", "访问次数", "首次", "最近", "User-Agent"]},
    )
    if st.button("💾 保存备注"):
        before = {r["ip"]: (r["note"] or "") for r in rows}
        changed = 0
        for _, row in edited.iterrows():
            ip, note = row["IP"], (row["备注"] or "").strip()
            if before.get(ip, "") != note:
                access_log.set_note(ip, note)
                changed += 1
        st.success(f"已保存 {changed} 条备注。")
        st.rerun()


def render_bet_log() -> None:
    """所有者：投注台账（记注 + 结算 + ROI / 盈亏曲线 / 回撤）。"""
    from wc2026.data import bets as bet_db
    section_title("投注台账（所有者）")
    st.caption("记录你实际下的注，结算后自动算 ROI、命中率、盈亏曲线、最大回撤。仅本地数据库，仅供复盘。")
    with st.form("add_bet_form", clear_on_submit=True):
        a1, a2, a3 = st.columns(3)
        bm = a1.text_input("场次", placeholder="墨西哥 vs 南非")
        bmk = a2.text_input("市场", placeholder="胜平负 / 大小球 / 让球…")
        bsel = a3.text_input("选择", placeholder="主胜 / 大 2.5 / 主-0.5…")
        a4, a5, a6 = st.columns(3)
        bodds = a4.number_input("赔率", min_value=1.01, value=2.00, step=0.01)
        bstake = a5.number_input("本金", min_value=0.0, value=100.0, step=10.0)
        bnote = a6.text_input("备注")
        if st.form_submit_button("➕ 记一注") and bm.strip():
            bet_db.add_bet(bm.strip(), bmk.strip(), bsel.strip(), bodds, bstake, bnote.strip())
            st.success("已记录")
            st.rerun()

    rows = bet_db.list_bets()
    if not rows:
        st.caption("还没有投注记录。")
        return
    s = bet_db.summary(rows)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("总盈亏", f"{s['profit']:+.2f}")
    m2.metric("ROI（已结算）", f"{s['roi']:+.1%}")
    m3.metric("命中率", f"{s['win_rate']:.0%}", f"{s['wins']} 胜", delta_color="off")
    m4.metric("最大回撤", f"{s['max_drawdown']:.2f}")
    st.caption(f"已结算 {s['settled']} 注 · 待结 {s['pending']} 注（待结本金 {s['pending_stake']:.0f}）· "
               f"已投本金 {s['staked']:.0f} · 回收 {s['returned']:.0f}")
    if s.get("clv_count"):
        st.caption(f"📈 收盘线价值(CLV，{s['clv_count']} 注有收盘赔率)：击败收盘 {s['beat_close_rate']:.0%} · "
                   f"平均 CLV {s['avg_clv']:+.1%}。长期看 CLV>0 比短期盈亏更能说明你下注有价值。")
    if s["curve"]:
        cfig = go.Figure(go.Scatter(y=s["curve"], mode="lines+markers", name="累计盈亏"))
        cfig.update_layout(height=260, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="累计盈亏",
                           template="plotly_dark" if current_theme() == "dark" else "plotly_white",
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(cfig, width="stretch")

    df = pd.DataFrame([{
        "id": r["id"], "时间": (r["created_at"] or "")[5:16], "场次": r["match"],
        "市场": r["market"], "选择": r["selection"], "赔率": r["odds"], "本金": r["stake"],
        "状态": r["status"], "盈亏": round(bet_db.pnl_of(r), 2), "收盘赔率": r.get("close_odds"),
        "备注": r["note"] or "",
    } for r in rows])
    edited = st.data_editor(
        df, hide_index=True, width="stretch", key="bets_editor",
        column_config={
            "状态": st.column_config.SelectboxColumn("状态", options=list(bet_db.STATUSES)),
            "收盘赔率": st.column_config.NumberColumn("收盘赔率", min_value=1.01, step=0.01, format="%.2f"),
            **{c: st.column_config.Column(disabled=True)
               for c in ["id", "时间", "场次", "市场", "选择", "赔率", "本金", "盈亏", "备注"]},
        })
    cc1, cc2 = st.columns([1, 2])
    if cc1.button("💾 保存结算 / 收盘赔率"):
        before = {r["id"]: (r["status"], r.get("close_odds")) for r in rows}
        changed = 0
        for _, row in edited.iterrows():
            st0, co0 = before.get(row["id"], (None, None))
            if st0 != row["状态"]:
                bet_db.set_status(int(row["id"]), row["状态"]); changed += 1
            co_new = row["收盘赔率"] if row["收盘赔率"] and float(row["收盘赔率"]) > 1.0 else None
            if (co0 or None) != co_new:
                bet_db.set_close(int(row["id"]), co_new); changed += 1
        st.success(f"已更新 {changed} 项。")
        st.rerun()
    del_id = cc2.selectbox("删除某注", ["（不删）"] + [r["id"] for r in rows], key="del_bet")
    if del_id != "（不删）" and cc2.button("🗑 删除所选"):
        bet_db.delete_bet(int(del_id))
        st.rerun()


def render_admin_user_panel() -> None:
    if not LOGIN_ENABLED:
        return  # 登录已关闭：不显示账号/退出/建用户面板（代码保留）
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
            "SELECT match_number, round_number, date_utc, home_team, away_team, group_name, "
            "location, home_score, away_score "
            "FROM fixtures WHERE predictable=1 ORDER BY date_utc"
        ).fetchall()
    fixtures = [dict(r) for r in rows]
    # 叠加已提交的赛果（部署服务器 DB 可能无比分时仍能显示）
    try:
        from wc2026.data.results import load_results_overlay
        overlay = load_results_overlay()
        if overlay:
            for f in fixtures:
                if f.get("home_score") is None and f["match_number"] in overlay:
                    f["home_score"], f["away_score"] = overlay[f["match_number"]]
    except Exception:
        pass
    return fixtures


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
    rec_legs = []
    if selected_idx:
        section_title("🎯 概率最高串关推荐")
        rec_detail = []
        for idx in selected_idx:
            match = flist[idx]
            cands = [c for c in value_candidates_for_match(match, neutral=match["home_team"] not in HOSTS)
                     if c["market"] in parlay_markets]
            if not cands:
                continue
            cands.sort(key=lambda c: c["model_prob"], reverse=True)
            mm = f"{zh(match['home_team'])} vs {zh(match['away_team'])}"
            best = cands[0]
            rec_legs.append({"match": mm, "market": best["market"], "label": best["label"],
                             "model_prob": best["model_prob"], "odds": best["odds"]})
            for rk, c in enumerate(cands[:3], 1):
                rec_detail.append({"场次": mm, "排序": rk, "市场": c["market"], "选项": c["label"],
                                   "模型概率": f"{c['model_prob']:.1%}", "公平赔率": f"{c['odds']:.2f}"})
        if rec_legs:
            rec_sum = value.parlay_summary(rec_legs, stake)
            r1, r2, r3 = st.columns(3)
            r1.metric("稳胆串关总概率", f"{rec_sum['combined_prob']:.2%}")
            r2.metric("总赔率", f"{rec_sum['combined_odds']:.2f}")
            r3.metric("关数", len(rec_legs))
            st.caption("「稳胆」推荐：每场取模型概率最高的选项串一起（命中率最高、赔率最低）。"
                       "下表为各场前 3 选项(按模型概率排序)，想换更高赔率/价值在下方「逐场参数选择」里自行勾选。")
            st.dataframe(pd.DataFrame(rec_detail), hide_index=True, width="stretch")
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
    eff_legs = legs if legs else rec_legs
    summary = value.parlay_summary(eff_legs, stake)
    if not summary["legs"]:
        st.info("请选择至少一场比赛（勾选具体参数则按你的选择，否则默认分析上方「概率最高推荐」组合）。")
        return
    st.divider()
    if not legs and rec_legs:
        st.caption("ℹ️ 你未手动勾选，以下按「概率最高推荐」组合分析；可在上方逐场勾选自定义。")
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
    n_legs = len(summary["legs"])
    _matches = [r["match"] for r in summary["legs"]]
    if len(_matches) != len(set(_matches)):
        st.error("⚠️ 同一场比赛被串了多个选项：同场结果高度相关，「总概率＝各关相乘」会严重高估真实命中率，"
                 "建议每场只保留一项。")
    if n_legs >= 4:
        st.warning(f"🚩 高风险串关：共 {n_legs} 关，每关都要命中。命中率随关数指数下降，建议控制在 2–3 关。")
    st.caption("串关假设各场结果近似独立；实际模型有误差、结果也可能相关，"
               "「总概率（相乘）」是乐观上限，真实命中率通常更低、关数越多衰减越快。仅供参考，不代表盈利保证。")

    st.divider()
    section_title("🤖 串关 AI 问答")
    if not llm_configured():
        st.caption("需接入 LLM（.env 配置 LLM_API_KEY）后可用。")
    elif not is_owner():
        st.caption("🔒 AI 问答仅所有者可用（消耗 LLM token）；访客只读。")
    else:
        from wc2026.llm import match_chat
        pctx = match_chat.build_parlay_context(summary["legs"], summary)
        pkey = "parlaychat"
        phist = st.session_state.setdefault(pkey, [])
        for mmsg in phist:
            st.markdown(f"**{'🧑 你' if mmsg['role'] == 'user' else '🤖 AI'}：** {mmsg['content']}")
        pq = st.text_area("问串关相关问题（如：这串风险在哪？该减到几关？哪关最可能爆？换哪个选项更稳？）",
                          key="parlay_q", height=80)
        pcc1, pcc2 = st.columns([1, 1])
        if pcc1.button("发送", key="parlay_send") and pq.strip():
            phist.append({"role": "user", "content": pq.strip()})
            with st.spinner("AI 分析串关中…"):
                pans = match_chat.ask(pq.strip(), pctx, phist)
            phist.append({"role": "assistant", "content": pans["text"]})
            st.rerun()
        if pcc2.button("清空对话", key="parlay_clear"):
            st.session_state[pkey] = []
            st.rerun()
        if st.checkbox("查看 AI 看到的串关上下文", key="parlay_ctx"):
            st.code(pctx)
        st.caption("AI 依据模型概率与你当前所串的各关作答；如需实时赔率价值，请先在「💰 价值扫描」拉取赔率(所有者)再来问。"
                   "AI 不会自动联网/拉取，避免消耗配额与 token。")


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


def _qualify_color(p: float) -> str:
    """出线概率颜色(需求 5.2.3)：绿=高 / 黄=边缘 / 红=低。"""
    if p >= 0.66:
        return "#16a34a"
    if p >= 0.33:
        return "#d97706"
    return "#dc2626"


def _standings_table_html(group: str, rows: list[dict], state: dict | None = None) -> str:
    """小组真实积分榜表格：前二绿条、第三黄条；末轮标注战意。"""
    from wc2026.analysis.motivation import STATUS_LABEL
    state = state or {}
    head = (f'<div style="display:inline-block;background:#2563eb;color:#fff;padding:2px 10px;'
            f'border-radius:6px;font-weight:700;margin-bottom:8px;">{group} 积分榜</div>')
    cols = ["#", "球队", "赛", "胜", "平", "负", "进", "失", "净", "分"]
    thead = "<tr>" + "".join(
        f'<th style="padding:2px 4px;text-align:center;color:var(--wc-muted);font-weight:600;">{c}</th>'
        for c in cols) + "</tr>"
    body = ""
    for r in rows:
        bar = "#16a34a" if r["rank"] <= 2 else ("#d97706" if r["rank"] == 3 else "transparent")
        s = state.get(r["team"], "alive")
        tag = ("" if s == "alive"
               else f'<span style="font-size:10px;color:var(--wc-muted);margin-left:4px;">{STATUS_LABEL[s]}</span>')
        tds = [f'<td style="text-align:center;border-left:3px solid {bar};padding:2px 4px;">{r["rank"]}</td>',
               f'<td style="padding:2px 4px;white-space:nowrap;">{zh(r["team"])}{tag}</td>']
        tds += [f'<td style="text-align:center;padding:2px 4px;">{r[k]}</td>'
                for k in ("played", "w", "d", "l", "gf", "ga")]
        tds.append(f'<td style="text-align:center;padding:2px 4px;">{r["gd"]:+d}</td>')
        tds.append(f'<td style="text-align:center;padding:2px 4px;font-weight:700;">{r["pts"]}</td>')
        body += "<tr>" + "".join(tds) + "</tr>"
    return (f'<div style="border:1px solid var(--wc-line);border-radius:10px;padding:10px 12px;'
            f'margin-bottom:14px;background:var(--wc-surface);">{head}'
            f'<table style="width:100%;border-collapse:collapse;font-size:12px;">'
            f'<thead>{thead}</thead><tbody>{body}</tbody></table></div>')


def _adjustments_expander() -> None:
    """展示当前赛中实力修正明细(各队 δ + 依据)，可回滚说明。"""
    from wc2026.analysis.adjustments import load_adjustments
    adj = load_adjustments()
    with st.expander(f"🔧 赛中实力修正明细（{len(adj)} 支球队）", expanded=False):
        if not adj:
            st.caption("暂无修正：尚无超出训练快照的完赛结果，或已重置。预测使用赛前模型。")
            return
        rows = sorted(adj.items(), key=lambda kv: abs(kv[1].get("elo", 0)), reverse=True)
        st.dataframe(pd.DataFrame([{
            "球队": zh(t),
            "Elo δ": f'{e.get("elo", 0):+.0f}',
            "进攻 δ": f'{e.get("attack", 0):+.3f}',
            "防守 δ": f'{e.get("defense", 0):+.3f}',
            "依据": "；".join(s.get("detail", "") for s in e.get("sources", [])[:4]),
        } for t, e in rows]), hide_index=True, width="stretch")
        st.caption("修正来自已完赛结果(高权重)与可选新闻；有界、可解释、可回滚"
                   "(删除 data/team_adjustments.json 或重置即恢复赛前模型)。")


def _auto_group_state(model, fixture, home: str, away: str):
    """末轮(赛事进行中)从当前积分自动推导战意 group_state；非末轮/无意义 → (None, '')。"""
    if not fixture or not fixture.get("group_name"):
        return None, ""
    g = fixture["group_name"]
    try:
        from wc2026.analysis import groups as _grp, motivation as _motiv
        states = _motiv.derive_group_states(_grp.load_group_data(model))
        if g not in states or (home not in states[g] and away not in states[g]):
            return None, ""
        gs = _motiv.group_state_for(states, g, home, away)
        if all(v["status"] == "alive" for v in gs.values()):
            return None, ""
        return gs, _motiv.status_note(states, g, home, away)
    except Exception:
        return None, ""


def _group_card_html(group: str, rows: list[dict]) -> str:
    head = (f'<div style="display:inline-block;background:#2563eb;color:#fff;padding:2px 10px;'
            f'border-radius:6px;font-weight:700;margin-bottom:8px;">{group}</div>')
    body = ""
    for r in rows:
        color = _qualify_color(r["qualify"])
        body += (
            '<div style="margin:8px 0;">'
            '<div style="display:flex;justify-content:space-between;font-weight:600;">'
            f'<span>{zh(r["team"])}</span><span style="color:{color};">{r["qualify"]:.1%}</span></div>'
            '<div style="background:var(--wc-surface-2);border-radius:6px;height:8px;margin:3px 0;">'
            f'<div style="width:{r["qualify"] * 100:.0f}%;background:{color};height:8px;border-radius:6px;"></div></div>'
            f'<div style="font-size:12px;color:var(--wc-muted);">头名 {r["first"]:.1%} · 前二 {r["top2"]:.1%} · 第三递补 {r["third_advance"]:.1%}</div>'
            '</div>'
        )
    return (f'<div style="border:1px solid var(--wc-line);border-radius:10px;padding:12px 14px;'
            f'margin-bottom:14px;background:var(--wc-surface);">{head}{body}</div>')


def render_group_stage(model) -> None:
    from wc2026.analysis import groups as groups_mod
    from wc2026.analysis import motivation as motiv_mod
    gd = groups_mod.load_group_data(model)
    if not gd:
        section_title("小组出线概率")
        st.warning("暂无可用的小组赛程数据（需先刷新 2026 赛程）。")
        return

    section_title("小组积分榜")
    st.caption("基于已完赛比分的真实积分(积分>净胜球>进球>相互战绩)；"
               "绿条=前二出线区，黄条=小组第三(争最佳第三递补)。末轮自动标注战意。")
    _adjustments_expander()
    standings = groups_mod.compute_standings(gd)
    states = motiv_mod.derive_group_states(gd)
    scols = st.columns(3)
    for i, g in enumerate(sorted(standings)):
        with scols[i % 3]:
            st.markdown(_standings_table_html(g, standings[g], states.get(g, {})),
                        unsafe_allow_html=True)

    st.markdown("---")
    section_title("小组出线概率")
    st.caption("每组前 2 名直接晋级，12 个小组第三中成绩最好的 8 个递补晋级。"
               "系统基于蒙特卡洛模拟，结合模型比分概率实时计算。")
    sig = groups_mod.played_signature(gd)
    total = sum(len(v["matches"]) for v in gd.values())
    c1, c2 = st.columns([2, 1])
    n_sims = c1.select_slider("蒙特卡洛模拟次数", options=[2000, 5000, 10000, 20000], value=10000)
    if sig:
        c2.metric("已结合真实赛果", f"{len(sig)} / {total} 场")
    else:
        c2.caption("赛前：全部为模型模拟")
    cache_key = f"groupsim:{n_sims}:{hash(sig)}"
    if st.button("🔄 重新模拟", help="赛果更新或调整次数后点此重算") or cache_key not in st.session_state:
        with st.spinner(f"蒙特卡洛模拟 {n_sims:,} 次…"):
            st.session_state[cache_key] = groups_mod.simulate_groups(model, gd, n_sims=n_sims)
    res = st.session_state[cache_key]
    cols = st.columns(3)
    for i, g in enumerate(sorted(res)):
        with cols[i % 3]:
            st.markdown(_group_card_html(g, res[g]), unsafe_allow_html=True)
    st.caption("⚽ 小组出线概率会随每轮赛果快速变化；末轮尤其注意战意差异：已出线可能轮换、已淘汰战意下降、"
               "积分相近可能更保守。排序近似 积分>净胜球>进球数，未完全实现相互战绩等次级规则；"
               "未显示 FIFA 排名（项目暂无该数据源）。")

    st.markdown("---")
    section_title("🏆 整届夺冠 / 进决赛概率")
    from wc2026.analysis import tournament as _tour
    from wc2026.analysis import ranking as _rk
    from wc2026.data.flags import flag_emoji as _flag
    tkey = f"toursim:{n_sims}:{hash(sig)}"
    if st.button("🎲 重新模拟整届", key="run_tour") or tkey not in st.session_state:
        with st.spinner(f"整届蒙特卡洛（小组→决赛）{n_sims:,} 次…"):
            st.session_state[tkey] = _tour.simulate_tournament(model, gd, n_sims=n_sims)
    tour_res = st.session_state[tkey]
    rmap = _rk.world_rank_map(model)

    def _tcell(t):
        rs = rmap.get(t)
        return f"{_flag(t)} {zh(t)}" + (f"（{rs[1]} #{rs[0]}）" if rs and rs[0] else "")

    trows = sorted(tour_res.items(), key=lambda kv: kv[1]["champion"], reverse=True)
    st.dataframe(pd.DataFrame([{
        "球队": _tcell(t), "进16强": f"{r['r16']:.0%}", "进8强": f"{r['qf']:.0%}",
        "进4强": f"{r['sf']:.0%}", "进决赛": f"{r['final']:.1%}", "夺冠": f"{r['champion']:.1%}",
    } for t, r in trows]), hide_index=True, width="stretch")
    st.caption("整届模拟：小组 → 淘汰赛（32 强→决赛）。近似：淘汰赛对阵按标准顺序树；8 个最佳小组第三按 slot 资格匹配；"
               "平局按加时/点球以强弱近似决出。概率随赛果更新；仅供参考。")

    st.markdown("---")
    section_title("🗺 淘汰赛对阵（32 强 · 小组投影）")

    def _slot_proj(slot: str) -> str:
        g = slot[1] if len(slot) == 2 and slot[0] in "12" else None
        if slot.startswith("3"):
            return f"{'/'.join(list(slot[1:]))} 组第三"
        rws = res.get(f"Group {g}", [])
        if not rws:
            return slot
        if slot.startswith("1"):
            b = max(rws, key=lambda r: r["first"])
            return f"{zh(b['team'])}（{b['first']:.0%} 头名）"
        b = max(rws, key=lambda r: r["top2"] - r["first"])
        return f"{zh(b['team'])}（次名）"

    from wc2026.analysis.tournament import R32_SLOTS
    bcols = st.columns(2)
    for half, col in enumerate(bcols):
        with col:
            st.caption("上半区" if half == 0 else "下半区")
            for mn, (hs, as_) in enumerate(R32_SLOTS[half * 8:half * 8 + 8], start=73 + half * 8):
                st.markdown(
                    f'<div style="border:1px solid var(--wc-line);border-radius:8px;padding:8px 10px;'
                    f'margin-bottom:6px;background:var(--wc-surface);font-size:13px;">'
                    f'<span style="color:var(--wc-muted);">M{mn} · {hs} vs {as_}</span><br>'
                    f'<b>{_slot_proj(hs)}</b> <span style="color:var(--wc-muted);">vs</span> <b>{_slot_proj(as_)}</b>'
                    f'</div>', unsafe_allow_html=True)
    st.caption("对阵 slot 来自官方赛程（1A=A 组头名、2B=B 组次名、3XXXX=列出小组中的最佳第三）；"
               "投影球队为当前小组模拟的最可能占位，随赛果变化。R16 之后由 32 强结果决定，晋级概率见上方夺冠表。")


def _group_short(group: str) -> str:
    return group.replace("Group ", "") + "组" if group and group.startswith("Group ") else (group or "")


def _match_labels(probs: dict, upset_idx: int, home: str, neutral: bool) -> list[tuple]:
    """基于模型可得数据的标签(需求 5.1.4 的可计算子集)。颜色随类型。"""
    labels = []
    if upset_idx >= 61:
        labels.append(("爆冷预警", "#dc2626"))
    if max(probs.values()) < 0.45:
        labels.append(("实力接近", "#d97706"))
    if probs.get("draw", 0) >= 0.30:
        labels.append(("平局偏高", "#2563eb"))
    if (not neutral) and home in HOSTS:
        labels.append(("主场加成", "#16a34a"))
    return labels


def _home_rows(_sig: str) -> list[dict]:
    """逐场计算胜平负 + 爆冷指数 + 标签。_sig 用于按模型版本缓存。"""
    from wc2026.analysis import upset
    from wc2026.analysis import ranking as rk
    rank_map = rk.world_rank_map(model)
    out = []
    for f in fixtures:
        home, away = f["home_team"], f["away_team"]
        neutral = home not in HOSTS
        probs = predict_1x2_for_match(f, neutral)["probs"]
        ui = upset.upset_index(probs, home, away)
        hr, ar = rank_map.get(home), rank_map.get(away)
        out.append({**f, "neutral": neutral, "probs": probs,
                    "upset": ui["index"], "upset_level": ui["level"],
                    "home_rank": hr[0] if hr else None, "home_src": hr[1] if hr else "",
                    "away_rank": ar[0] if ar else None, "away_src": ar[1] if ar else "",
                    "labels": _match_labels(probs, ui["index"], home, neutral)})
    return out


def _home_card_html(r: dict) -> str:
    from wc2026.analysis import schedule as sch
    from wc2026.data.flags import flag_emoji
    p = r["probs"]
    ph, pd, pa = p["home"], p["draw"], p["away"]
    bj = sch.beijing(r.get("date_utc"))
    res = sch.match_result(r.get("home_score"), r.get("away_score"),
                           zh(r["home_team"]), zh(r["away_team"]))
    head = f'{_group_short(r["group_name"])}第{r.get("round_number", "")}轮 · {bj["full"]}（北京）'
    status = (f'<span style="background:#16a34a;color:#fff;font-size:11px;padding:1px 8px;'
              f'border-radius:10px;margin-left:6px;">完场 {res["score"]}</span>') if res["finished"] else ""
    bar = (
        '<div style="display:flex;height:9px;border-radius:6px;overflow:hidden;margin:5px 0;">'
        f'<div style="width:{ph * 100:.0f}%;background:#16a34a;"></div>'
        f'<div style="width:{pd * 100:.0f}%;background:#9aa7b6;"></div>'
        f'<div style="width:{pa * 100:.0f}%;background:#2563eb;"></div></div>'
    )
    chips = "".join(
        f'<span style="background:{c};color:#fff;font-size:11px;padding:1px 7px;'
        f'border-radius:10px;margin-right:4px;">{t}</span>' for t, c in r["labels"]
    )
    result_line = (f'<div style="font-weight:700;color:#16a34a;margin:4px 0;">完场 {res["score"]} · {res["text"]}</div>'
                   if res["finished"] else "")
    return (
        '<div style="border:1px solid var(--wc-line);border-radius:10px;padding:12px 14px;'
        'margin-bottom:12px;background:var(--wc-surface);">'
        f'<div style="font-size:12px;color:var(--wc-muted);margin-bottom:4px;">{head}{status}</div>'
        '<div style="display:flex;justify-content:space-between;font-weight:700;font-size:15px;">'
        f'<span>{flag_emoji(r["home_team"])} {zh(r["home_team"])}</span>'
        f'<span>{zh(r["away_team"])} {flag_emoji(r["away_team"])}</span></div>'
        '<div style="display:flex;justify-content:space-between;font-size:11px;color:var(--wc-muted);">'
        f'<span>{r.get("home_src") or "世界"} #{r.get("home_rank") or "—"}</span>'
        f'<span>{r.get("away_src") or "世界"} #{r.get("away_rank") or "—"}</span></div>'
        f'{result_line}{bar}'
        '<div style="display:flex;justify-content:space-between;font-size:12px;color:var(--wc-muted);">'
        f'<span>胜 {ph:.0%}</span><span>平 {pd:.0%}</span><span>负 {pa:.0%}</span></div>'
        f'<div style="font-size:12px;color:var(--wc-muted);margin-top:6px;">📍 {r.get("location", "")}</div>'
        f'<div style="margin-top:6px;"><span style="font-weight:600;">爆冷 {r["upset"]}</span> '
        f'<span style="color:var(--wc-muted);font-size:12px;">{r["upset_level"]}</span>　{chips}</div>'
        '</div>'
    )


def render_home(model) -> None:
    render_hero("2026 世界杯 · AI 预测赛程",
                "FIFA World Cup 26 · 美国 / 加拿大 / 墨西哥",
                "AI-POWERED PREDICTION")
    st.caption("模型：Elo + Dixon-Coles + 赔率价值模型")
    if not fixtures:
        st.warning("暂无可预测赛程（需先刷新 2026 赛程或初始化数据）。")
        return
    sig = model_updated_label()
    ck = f"homerows:{sig}"
    if ck not in st.session_state:
        with st.spinner("计算全部场次预测…"):
            st.session_state[ck] = _home_rows(sig)
    rows = st.session_state[ck]

    s1, s2, s3 = st.columns(3)
    s1.metric("预测场次", len(rows))
    s2.metric("爆冷预警", sum(1 for r in rows if r["upset"] >= 61))
    s3.metric("模型更新", sig)

    f1, f2, f3 = st.columns([1, 1, 2])
    fg = f1.selectbox("小组", ["全部"] + sorted({r["group_name"] for r in rows}))
    fr = f2.selectbox("轮次", ["全部", 1, 2, 3])
    q = f3.text_input("搜索球队（中 / 英文）").strip().lower()
    only_upset = st.checkbox("只看爆冷预警（指数 ≥ 61）")

    def keep(r):
        if fg != "全部" and r["group_name"] != fg:
            return False
        if fr != "全部" and r.get("round_number") != fr:
            return False
        if only_upset and r["upset"] < 61:
            return False
        if q and q not in zh(r["home_team"]).lower() and q not in zh(r["away_team"]).lower() \
                and q not in r["home_team"].lower() and q not in r["away_team"].lower():
            return False
        return True

    from wc2026.analysis import schedule as _sch
    from datetime import datetime as _dt, timezone as _tz
    shown = _sch.sort_fixtures([r for r in rows if keep(r)], _dt.now(_tz.utc))
    st.caption(f"共 {len(shown)} 场（未开赛在前、已结束在后；时间为北京时间）。"
               "胜平负概率条：绿=主胜 / 灰=平 / 蓝=客胜。")
    cols = st.columns(2)
    for i, r in enumerate(shown):
        with cols[i % 2]:
            st.markdown(_home_card_html(r), unsafe_allow_html=True)
    st.caption("说明：国旗 + 世界排名（FIFA 官方，缺失回退模型 Elo）；已完赛显示比分并排到列表下方；"
               "价值 / 让球 / 身价 / 伤停类标签需拉取实时赔率或外部数据，未在首页批量计算。"
               "单场详情页可查看完整价值判断与爆冷因子。")


def render_schedule(model) -> None:
    from wc2026.analysis import schedule as sch, ranking as rk
    from wc2026.data.flags import flag_emoji
    from datetime import datetime, timezone
    section_title("小组赛赛程")
    if not fixtures:
        st.warning("暂无赛程数据（需先刷新 2026 赛程）。")
        return
    rank_map = rk.world_rank_map(model)
    groups = sorted({f["group_name"] for f in fixtures if f.get("group_name")})
    fg = st.selectbox("分组", ["全部"] + groups, key="sched_group")
    flist = [f for f in fixtures if fg == "全部" or f.get("group_name") == fg]
    flist = sch.sort_fixtures(flist, datetime.now(timezone.utc))

    def _cell(t):
        rs = rank_map.get(t)
        return f"{flag_emoji(t)} {zh(t)}（{rs[1]} #{rs[0]}）" if rs and rs[0] else f"{flag_emoji(t)} {zh(t)}"

    rows = []
    for f in flist:
        bj = sch.beijing(f.get("date_utc"))
        res = sch.match_result(f.get("home_score"), f.get("away_score"))
        rows.append({
            "小组": _group_short(f.get("group_name", "")),
            "轮次": f"第{f.get('round_number', '')}轮",
            "日期": bj["date"], "周": bj["weekday"], "北京时间": bj["time"],
            "主队": _cell(f["home_team"]), "客队": _cell(f["away_team"]),
            "比分 / 状态": (f"✅ {res['score']}" if res["finished"] else "未开赛"),
            "球场": f.get("location", ""),
        })
    st.caption(f"共 {len(rows)} 场（未开赛在前、已结束在后；时间为北京时间 UTC+8）。")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(f"世界排名：FIFA 官方{('（' + (rk.ranking_date() or '') + '）') if rk.ranking_date() else ''}，"
               "缺失回退模型 Elo；比分在赛程数据更新后自动显示。")


inject_design_system()
user = require_login()
model = load_model()
fixtures = load_fixtures()

# 每个会话记录一次访问 IP（建表 + upsert，同 IP 保留备注）
if not st.session_state.get("_visit_logged"):
    try:
        from wc2026.data.db import init_db
        from wc2026.data import access_log
        init_db()
        _ip, _ua = get_client_ip()
        access_log.record_visit(_ip, _ua)
    except Exception:
        pass
    st.session_state["_visit_logged"] = True

render_hero(
    "2026 世界杯预测工作台",
    "比分概率、盘口价值、串关组合与证据分析集中在一个可操作界面中。模型结论仅供参考，请理性参与并遵守当地法规。",
)

with st.sidebar:
    st.header("功能")
    page_options = ["首页", "小组赛赛程", "单场分析", "小组出线", "串关组合"]
    if is_owner():
        page_options.append("访问记录")
        page_options.append("投注台账")
    if user["role"] == "admin":
        page_options.append("用户管理")
    page = st.radio("页面", page_options, horizontal=True)
    render_admin_user_panel()
    render_access_banner()
    st.divider()
    if page == "串关组合":
        st.caption("LLM 理由/分析：" + ("✅ 已配置，可手动触发" if llm_configured() else "⚠️ 规则模板(未接入)"))

if page == "首页":
    render_home(model)
    st.stop()
if page == "访问记录":
    render_access_log()
    st.stop()
if page == "投注台账":
    render_bet_log()
    st.stop()
if page == "小组赛赛程":
    render_schedule(model)
    st.stop()
if page == "串关组合":
    render_parlay_builder()
    st.stop()
if page == "小组出线":
    render_group_stage(model)
    st.stop()
if page == "用户管理":
    render_user_management()
    st.stop()

with st.sidebar:
    st.header("选择比赛")
    mode = st.radio("方式", ["按赛程", "自定义对阵"], horizontal=True)
    venue_info = None
    if mode == "按赛程" and fixtures:
        from wc2026.analysis import schedule as _sch
        from datetime import datetime as _dt, timezone as _tz
        groups = sorted({f["group_name"] for f in fixtures})
        g = st.selectbox("分组", ["全部"] + groups)
        flist = _sch.sort_fixtures(
            [f for f in fixtures if g == "全部" or f["group_name"] == g], _dt.now(_tz.utc))

        def _fx_label(i):
            f = flist[i]
            res = _sch.match_result(f.get("home_score"), f.get("away_score"))
            tag = f"✅ {res['score']}" if res["finished"] else _sch.beijing(f["date_utc"])["full"]
            return f"{zh(f['home_team'])} vs {zh(f['away_team'])}（{tag}）"

        idx = st.selectbox("场次", range(len(flist)), format_func=_fx_label)
        sel = flist[idx]
        selected_fixture = sel
        home, away = sel["home_team"], sel["away_team"]
        venue_info = f"🗓 {_sch.beijing(sel['date_utc'])['full']}（北京） · {sel['group_name']} · 📍{sel['location']}"
        default_neutral = home not in HOSTS
    else:
        selected_fixture = None
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
    if action_button("🔄 一键全量刷新", help="重抓历史数据+回填赛果+重训模型+更新赛程"):
        with st.spinner("抓数据 + 回填赛果 + 重训 + 赛程中…"):
            ingest_international_results()
            try:
                fetch_and_store_fixtures()
            except Exception as exc:
                st.warning(f"赛程刷新失败：{exc}")
            from wc2026.data.results import backfill_fixture_scores, export_results_json
            backfill_fixture_scores()
            export_results_json()
            _m = train_and_save()
            from wc2026.analysis.adjustments import recompute
            recompute(_m, with_news=False)
            st.cache_resource.clear()
            st.cache_data.clear()
        st.success("已刷新（含赛果回填 + 赛中实力修正）")
        st.rerun()
    st.divider()
    st.caption("LLM 理由/分析：" + ("✅ 已配置，可手动触发" if llm_configured() else "⚠️ 规则模板(未接入)"))

if home == away:
    st.warning("请选择两支不同的球队。")
    st.stop()

section_title(f"{zh(home)} vs {zh(away)}")
if venue_info:
    st.caption(venue_info)
from wc2026.analysis import ranking as _ranking
_hr, _hsrc = _ranking.world_rank(model, home)
_ar, _asrc = _ranking.world_rank(model, away)
_rdate = _ranking.ranking_date()
_rtot = 211  # FIFA 榜规模（用于上下文展示）
st.caption(f"🌐 世界排名：{zh(home)} 第 {_hr or '—'} 名（{_hsrc or '—'}） · "
           f"{zh(away)} 第 {_ar or '—'} 名（{_asrc or '—'}）"
           f"　来源：FIFA 官方{('（' + _rdate + '）') if _rdate else ''}，缺失回退模型 Elo")

if selected_fixture is not None:
    from wc2026.analysis import schedule as _sch2
    from wc2026.data.flags import flag_emoji as _flag
    _res = _sch2.match_result(selected_fixture.get("home_score"), selected_fixture.get("away_score"),
                              zh(home), zh(away))
    if _res["finished"]:
        st.success(f"🏁 已完赛　{_flag(home)} {zh(home)}　**{_res['score']}**　{zh(away)} {_flag(away)}　·　{_res['text']}")
    else:
        st.info(f"⏳ 未开赛（{_sch2.beijing(selected_fixture.get('date_utc'))['full']} 北京时间）；以下为赛前模型预测。")

auto_group_state, auto_note = _auto_group_state(model, selected_fixture, home, away)
if use_context:
    from wc2026.analysis import context
    adj = context.adjusted_prediction(model, home, away, neutral,
                                      group_state=auto_group_state, tank_risk=tank_risk)
    mat, (lam, mu), context_notes = adj["matrix"], adj["exp_goals"], adj["notes"]
    effective_tank = adj["tank_risk"]
elif auto_group_state is not None:
    # 末轮：未手动开启情境，但当前积分形势显示有出线压力 → 自动应用战意修正
    from wc2026.analysis import context
    adj = context.adjusted_prediction(model, home, away, neutral, group_state=auto_group_state)
    mat, (lam, mu), context_notes = adj["matrix"], adj["exp_goals"], adj["notes"]
    effective_tank = adj["tank_risk"]
    if auto_note:
        st.info("🎯 末轮战意自动修正(按当前积分形势)：" + auto_note)
else:
    mat = model.score_matrix(home, away, neutral)
    lam, mu = model.expected_goals(home, away, neutral)
    context_notes = []
    effective_tank = tank_risk
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

env_report = match_environment_report(home, away, mat, fixture=selected_fixture)

left, right = st.columns([3, 2])
with left:
    section_title("比分概率热力图")
    n = mat.shape[0]
    fig = go.Figure(go.Heatmap(
        z=mat, x=[str(j) for j in range(n)], y=[str(i) for i in range(n)],
        colorscale="Blues",
        hovertemplate=f"{zh(home)} %{{y}} - %{{x}} {zh(away)}<br>概率 %{{z:.1%}}<extra></extra>"))
    fig.update_layout(xaxis_title=f"{zh(away)} 进球", yaxis_title=f"{zh(home)} 进球",
                      height=400, margin=dict(l=10, r=10, t=10, b=10),
                      template="plotly_dark" if current_theme() == "dark" else "plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")
with right:
    section_title("为什么")
    reason_key = f"reason:{home}:{away}:{neutral}:{use_context}:{tank_risk}"
    display_reason = st.session_state.get(reason_key, reason)
    if llm_configured() and action_button("🤖 手动生成 AI 理由", key=f"ai_reason:{home}:{away}:{neutral}:{use_context}:{tank_risk}"):
        with st.spinner("生成 AI 理由…"):
            display_reason = reasoning.generate_reason(model, home, away, neutral, markets, use_llm=True)
        st.session_state[reason_key] = display_reason
    st.info(display_reason["text"])
    st.caption("来源：" + ("🤖 AI 生成" if display_reason["source"] == "llm" else "📋 规则模板"))

section_title("爆冷指数")
from wc2026.analysis import upset
ui = upset.upset_index(x, home, away, reason["evidence"], effective_tank)
uc1, uc2 = st.columns([1, 2])
with uc1:
    st.metric("爆冷指数", f"{ui['index']} / 100", ui["level"], delta_color="off")
    st.progress(ui["index"] / 100)
with uc2:
    for f in ui["factors"]:
        st.markdown(f"- **{f['name']}**：{f['detail']}")
st.caption("爆冷指数衡量「把热门方当稳胆」的风险，不预测弱队一定爆冷；指数越高，越不适合作为无脑稳胆。"
           "暂未纳入伤停 / 海拔 / 时差 / 历史大赛不稳定性（项目无对应结构化数据源）。")

with st.expander("📥 分享海报（生成 PNG）", expanded=False):
    from wc2026.analysis import schedule as _sch_p
    _rtxt = None
    if selected_fixture is not None:
        _rp = _sch_p.match_result(selected_fixture.get("home_score"), selected_fixture.get("away_score"))
        _rtxt = _rp["score"].replace("-", " - ") if _rp["finished"] else None
    try:
        from wc2026.viz.poster import match_poster_png
        _png = match_poster_png(zh(home), zh(away), x, upset=ui, home_rank=_hr, away_rank=_ar,
                                result=_rtxt, subtitle=(venue_info or "").replace("🗓 ", ""))
        st.image(_png, caption="预览", width=680)
        st.download_button("📥 下载海报 PNG", _png, file_name=f"{home}_vs_{away}.png", mime="image/png")
        st.caption("无 CJK 字体的服务器上会自动改用英文队名。模型概率仅供参考。")
    except Exception as exc:
        st.caption(f"海报生成失败：{exc}")

section_title("赛前环境与背景适应性")
env_score = env_report["score_pick"]
ec1, ec2 = st.columns([1, 3])
with ec1:
    st.metric("环境/背景参考比分", env_score["score"], f"{env_score['prob']:.1%}", delta_color="off")
    st.caption(env_score["basis"])
with ec2:
    st.dataframe(pd.DataFrame(env_report["environment"]), hide_index=True, width="stretch")

from wc2026.analysis import fatigue as _fatigue
_mf = _fatigue.match_fatigue(home, away, fixtures, selected_fixture)
if _mf["home"] and _mf["away"]:
    st.markdown("**🏃 体能与旅行（按赛程量化）**")
    st.dataframe(pd.DataFrame([
        {"球队": zh(t),
         "休息天数": (d["rest_days"] if d["rest_days"] is not None else "首战"),
         "上场后旅行(km)": (d["travel_km"] or "—"),
         "本场海拔(m)": (d["alt"] if d["alt"] is not None else "—")}
        for t, d in [(home, _mf["home"]), (away, _mf["away"])]
    ]), hide_index=True, width="stretch")
    for _n in _mf["notes"]:
        st.markdown(f"- {_n}")
    st.caption("休息天数/旅行公里按赛程与场馆经纬度计算；海拔为承办城市公开数据。方向性体能提示，不改写概率。")

ad1, ad2 = st.columns([1, 1])
with ad1:
    st.caption("球队适应性")
    st.dataframe(pd.DataFrame(env_report["adaptation"]), hide_index=True, width="stretch")
with ad2:
    st.caption("国家背景关系")
    st.dataframe(pd.DataFrame(env_report["background"]), hide_index=True, width="stretch")
st.caption("说明：该模块参考时区、球场、海拔、气候、远征和宏观国家背景做定性补充；政治/经济关系不作为直接胜负变量，赛果仍以模型概率、阵容状态和临场信息为主。")

section_title("综合实力评分")
from wc2026.analysis import strength
sp = strength.strength_profile(model, home, away, reason["evidence"])
_radar_cats = strength.DIMENSIONS + [strength.DIMENSIONS[0]]  # 闭合多边形
sc1, sc2 = st.columns([3, 2])
with sc1:
    radar = go.Figure()
    for name, dims, color in [(zh(home), sp["dims_home"], "#14b8a6"),
                              (zh(away), sp["dims_away"], "#f59e0b")]:
        radar.add_trace(go.Scatterpolar(
            r=[dims[k] for k in strength.DIMENSIONS] + [dims[strength.DIMENSIONS[0]]],
            theta=_radar_cats, fill="toself", name=name, line=dict(color=color)))
    radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        height=380, margin=dict(l=40, r=40, t=30, b=30),
        legend=dict(orientation="h", y=-0.1),
        template="plotly_dark" if current_theme() == "dark" else "plotly_white",
        paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(radar, width="stretch")
with sc2:
    sm1, sm2 = st.columns(2)
    sm1.metric(f"{zh(home)} 综合", f"{sp['score_home']:.0f}")
    sm2.metric(f"{zh(away)} 综合", f"{sp['score_away']:.0f}")
    st.dataframe(pd.DataFrame([
        {"维度": k, zh(home): f"{sp['dims_home'][k]:.0f}", zh(away): f"{sp['dims_away'][k]:.0f}"}
        for k in strength.DIMENSIONS]), hide_index=True, width="stretch")
st.info(sp["explanation"])
st.caption("评分用于解释而非替代赔率；维度由 Elo / Dixon-Coles / 近况 / 交锋折算并跨全部球队归一（0-100）。"
           "未纳入身价 / FIFA 排名 / 世界杯历史 / 环境 / 体能 / 市场（项目无对应数据源）。")

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

section_title("进球区间推荐")
from wc2026.analysis import goal_strategy
gs = goal_strategy.recommend(mat, lam, mu)
_gs_emoji = {"满足": "✅ 满足", "不满足": "❌ 不满足", "需盘口确认": "🔶 需盘口确认"}
gcol1, gcol2 = st.columns([1, 2])
with gcol1:
    if gs["recommend"] == "回避":
        st.metric("推荐区间", "回避", "低进球/闷局风险", delta_color="off")
    else:
        st.metric("推荐区间", gs["recommend"], f"模型概率 {gs['confidence']:.0%}", delta_color="off")
    st.caption(f"期望进球 {gs['xg_home']:.2f} : {gs['xg_away']:.2f}（合计 {gs['xg_total']:.2f}）")
    bp = gs["probs"]
    st.caption(f"0-1球 {bp['0-1']:.0%} · 2-3球 {bp['2-3']:.0%} · 3-4球 {bp['3-4']:.0%} · 4+球 {bp['4+']:.0%}")
with gcol2:
    for r in gs["reasons"]:
        st.markdown(f"- {r}")
    if gs["checklist"]:
        st.dataframe(pd.DataFrame([{"条件": c, "状态": _gs_emoji.get(s, s)} for c, s in gs["checklist"]]),
                     hide_index=True, width="stretch")
st.caption("策略：放弃 1-3 球高风险区间（易遇 0-0 / 强队零封），聚焦 2-3 球与 3-4 球。"
           "盘口 / 水位类条件需结合真实赔率确认。风险控制：单场投注≤10% 资金，连黑 3 场停手，"
           "不碰冷门联赛与高水盘。模型有误差，仅供参考。")

with st.expander("🎲 比分蒙特卡洛（验证单场结论的自洽性）", expanded=False):
    from wc2026.markets import simulate as _sim
    _ns = st.select_slider("模拟次数", [2000, 10000, 50000], value=10000, key=f"simn:{home}:{away}")
    sm = _sim.simulate_match(mat, n_sims=int(_ns), top_k=8)
    st.caption(f"从本场比分概率矩阵抽样 {sm['n']:,} 次，统计最高频比分，与解析「模型概率」并排对比。"
               "二者吻合即说明单场分析里的比分/胜平负/大小球推导自洽（抽样的是同一模型，非独立预测）。")
    st.dataframe(pd.DataFrame([{
        "比分(主-客)": r["score"], "模拟频率": f"{r['sim_prob']:.1%}", "模型概率": f"{r['model_prob']:.1%}",
        "差": f"{(r['sim_prob'] - r['model_prob']):+.1%}",
    } for r in sm["top_scores"]]), hide_index=True, width="stretch")
    vc1, vc2 = st.columns(2)
    vc1.markdown(f"**胜平负**　模拟 {sm['sim_1x2']['home']:.0%}/{sm['sim_1x2']['draw']:.0%}/{sm['sim_1x2']['away']:.0%}　"
                 f"模型 {sm['model_1x2']['home']:.0%}/{sm['model_1x2']['draw']:.0%}/{sm['model_1x2']['away']:.0%}")
    vc2.markdown(f"**大/小 2.5**　模拟 {sm['sim_ou25']['over']:.0%}/{sm['sim_ou25']['under']:.0%}　"
                 f"模型 {sm['model_ou25']['over']:.0%}/{sm['model_ou25']['under']:.0%}")
    st.caption(f"模拟期望进球 {sm['exp_goals_sim'][0]:.2f} : {sm['exp_goals_sim'][1]:.2f}；"
               f"胜平负模拟-模型最大偏差 {sm['max_abs_err']:.1%}（次数越多越小，正常应 <2%）。")

with st.expander("💰 价值 & 凯利（输入体彩/盘口赔率）", expanded=False):
    st.caption("输入该场实际赔率(十进制/欧赔)，对比模型概率找价值盘。默认填的是模型公平赔率。")
    vc1, vc2, vc3 = st.columns(3)
    if action_button("🔄 拉取本场可用赔率预填", help="需要 ODDS_API_KEY；会尝试预填胜平负、让球、大小球等 The Odds API 支持的市场。"):
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
                from wc2026.data import odds_history
                snap_n = odds_history.record_event_snapshot(home, away, event_odds)
                st.success(f"已拉取可用赔率并预填；没有的市场仍保留模型公平赔率。已记录 {snap_n} 条赔率快照。")
            render_quota(st.session_state.get("odds_quota", {}))
        except Exception as exc:
            st.error(f"赔率拉取失败：{exc}")
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
        fair_odds = (1.0 / r["model_prob"]) if r["model_prob"] > 0 else 0.0
        vrows.append({
            "结果": labels[k],
            "模型概率": f"{r['model_prob']:.1%}",
            "公平赔率": f"{fair_odds:.2f}",
            "实际赔率": f"{r['odds']:.2f}",
            "盘口隐含(剔水)": f"{imp['fair'].get(k, 0):.1%}",
            "价值": f"{r['edge']:+.1%}",
            "判断": "✅ 有价值" if r["value"] else "—",
            "全凯利": f"{r['kelly_full']:.1%}",
            "½凯利": f"{r['kelly_full'] * 0.5:.1%}",
            "¼凯利": f"{r['kelly_frac']:.1%}",
        })
    st.dataframe(pd.DataFrame(vrows), hide_index=True, width="stretch")
    st.caption("⚠️ 价值>0 才有长期正期望；凯利为占本金比例，默认参考 ¼ 凯利(避免激进)。模型有误差，仅供参考、量力而行。")

    _picks = {k: r for k, r in analysis["results"].items() if r and r["edge"] > 0}
    st.markdown("**🎲 凯利风险模拟**（把「连黑停手」量化成破产概率）")
    if _picks:
        from wc2026.markets import risk as _risk
        _best = max(_picks, key=lambda k: _picks[k]["edge"])
        rc1, rc2, rc3 = st.columns(3)
        _opt = rc1.selectbox("价值选项", list(_picks.keys()), index=list(_picks).index(_best),
                             format_func=lambda k: labels[k], key=f"risk_pick:{home}:{away}")
        _kf = rc2.select_slider("凯利比例", ["1/8", "1/4", "1/2", "全凯利"], value="1/4",
                                key=f"risk_kf:{home}:{away}")
        _nb = rc3.select_slider("下注场次", [20, 50, 100, 200], value=50, key=f"risk_nb:{home}:{away}")
        _mult = {"1/8": 0.125, "1/4": 0.25, "1/2": 0.5, "全凯利": 1.0}[_kf]
        _pr = _picks[_opt]
        _f = _pr["kelly_full"] * _mult
        sim = _risk.bankroll_sim(_pr["model_prob"], _pr["odds"], _f, n_bets=int(_nb))
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("盈利概率", f"{sim['p_profit']:.0%}")
        s2.metric("资金中位增长", f"{sim['median_final'] - 1:+.0%}")
        s3.metric("回撤>20% 概率", f"{sim['p_drawdown_20']:.0%}")
        s4.metric("破产概率(跌破50%)", f"{sim['risk_of_ruin']:.0%}")
        st.caption(f"按「{labels[_opt]}」边际 {_pr['edge']:+.1%}、{_kf}(占本金 {_f:.1%})、连下 {_nb} 场，模拟 5000 次。"
                   "破产/回撤概率高=该比例过激进，应降比例或减少场次；若模型高估边际，真实结果会更差。")
    else:
        st.caption("当前无正期望选项，不做风险模拟（无价值则不下注）。")

    temp = value.market_temperature(x, imp["fair"])
    st.markdown("**市场冷热**（剔水后市场概率 vs 模型概率）")
    _temp_color = {"偏热": "#dc2626", "偏冷": "#2563eb", "中性": "#9aa7b6"}
    tcols = st.columns(3)
    for col, k in zip(tcols, ("home", "draw", "away")):
        r = temp["results"].get(k)
        if not r:
            continue
        c = _temp_color[r["label"]]
        col.markdown(
            f'<div style="font-size:13px;color:var(--wc-muted);">{labels[k]}</div>'
            f'<div style="font-weight:700;color:{c};">{r["label"]} {r["diff"]:+.1%}</div>'
            f'<div style="font-size:12px;color:var(--wc-muted);">模型 {r["model_prob"]:.0%} · 市场 {r["market_prob"]:.0%}</div>',
            unsafe_allow_html=True)
    if temp["favorite"]:
        fav_lbl = labels[temp["favorite"]]
        msg = {"偏热": f"🔴 热门「{fav_lbl}」被市场高估（过热），追热门需谨慎。",
               "偏冷": f"🔵 热门「{fav_lbl}」被市场低估，可能存在价值。",
               "中性": f"⚪ 热门「{fav_lbl}」市场与模型基本一致。"}[temp["verdict"]]
        st.caption(msg + "（已剔除博彩抽水，阈值 ±3%；偏热=市场比模型更看好，偏冷=市场更不看好。）")

    st.markdown("**赔率走势**（每次拉取赔率后累积；同一场多次拉取才形成曲线）")
    from wc2026.data import odds_history
    _mkt_label = {"h2h": "胜平负", "spreads": "让球", "totals": "大小球"}
    trend_mkt = st.selectbox("走势市场", ["h2h", "spreads", "totals"],
                             format_func=lambda m: _mkt_label[m], key=f"trend_mkt:{home}:{away}")
    trend_line = None
    if trend_mkt in ("spreads", "totals"):
        lines = odds_history.available_lines(home, away, trend_mkt)
        if lines:
            trend_line = st.selectbox("盘口线", lines, key=f"trend_line:{home}:{away}:{trend_mkt}")
    series = odds_history.load_history(home, away, trend_mkt, line=trend_line)
    if series and max((len(v) for v in series.values()), default=0) >= 2:
        _sel_label = {"home": zh(home), "draw": "平", "away": zh(away), "over": "大", "under": "小"}
        tfig = go.Figure()
        for sel, pts in series.items():
            tfig.add_trace(go.Scatter(x=[t for t, _o in pts], y=[o for _t, o in pts],
                                      mode="lines+markers", name=_sel_label.get(sel, sel)))
        tfig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), yaxis_title="赔率",
                           template="plotly_dark" if current_theme() == "dark" else "plotly_white",
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(tfig, width="stretch")
    else:
        st.caption("暂无足够历史快照——多次点上方「🔄 拉取本场可用赔率预填」后形成走势（v1 不自动定时抓取）。")

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

with st.expander("🏆 世界杯历史（历届战绩 + 世界杯交锋）", expanded=False):
    from wc2026.analysis import wc_history as wc_hist
    wh1, wh2 = st.columns(2)
    for col, team, rec in [(wh1, home, wc_hist.wc_record(home)),
                           (wh2, away, wc_hist.wc_record(away))]:
        with col:
            if rec["matches"]:
                st.metric(f"{zh(team)} · 世界杯参赛", f"{rec['editions']} 届")
                st.caption(f"{rec['first']}–{rec['last']} · {rec['matches']} 场 "
                           f"{rec['w']}胜{rec['d']}平{rec['l']}负 · 进 {rec['gf']} 失 {rec['ga']}")
            else:
                st.caption(f"{zh(team)}：无世界杯参赛记录。")
    st.markdown("**世界杯交锋**")
    meetings = wc_hist.wc_head_to_head(home, away)
    if meetings:
        st.dataframe(pd.DataFrame([
            {"年份": m["year"], "举办国": (zh(m["country"]) if m["country"] else "—"),
             "对阵": f"{zh(m['home'])} {m['score']} {zh(m['away'])}"}
            for m in meetings]), hide_index=True, width="stretch")
    else:
        st.caption("两队此前无世界杯交锋记录。")
    st.caption("样本较少，仅作辅助参考，不应单独作为投注依据；表格不含晋级轮次（数据源无阶段字段）。")

with st.expander("📰 相关资讯", expanded=False):
    news_key = f"news:{home}:{away}"
    if action_button("🔄 手动刷新资讯", key=f"refresh_news:{home}:{away}"):
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
                if action_button("🤖 手动分析资讯", key=f"analyze_news:{home}:{away}"):
                    ana = news_mod.analyze_news(home, away, items)
                    if ana:
                        st.info("🤖 AI 资讯分析：" + ana["text"])
                inj_key = f"injuries_data:{home}:{away}"
                if action_button("🤖 提取伤停 / 缺阵线索", key=f"injuries:{home}:{away}"):
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
                risk_key = f"risktags_data:{home}:{away}"
                if action_button("🚩 提取新闻风险标签", key=f"risktags:{home}:{away}"):
                    with st.spinner("AI 从新闻抽取风险标签…"):
                        st.session_state[risk_key] = news_mod.extract_risk_tags(home, away, items)
                risk = st.session_state.get(risk_key)
                if risk:
                    _sev_color = {"高": "#dc2626", "中": "#d97706", "低": "#9aa7b6"}
                    for side, nm in [("home", zh(home)), ("away", zh(away))]:
                        tags = risk.get(side) or []
                        if tags:
                            chips = "".join(
                                f'<span title="{t["note"]}" style="background:{_sev_color.get(t["severity"], "#d97706")};'
                                'color:#fff;font-size:12px;padding:2px 8px;border-radius:10px;'
                                f'margin:2px 4px 2px 0;display:inline-block;">{t["tag"]}·{t["severity"]}</span>'
                                for t in tags)
                            st.markdown(f"🚩 **{nm}** 风险：{chips}", unsafe_allow_html=True)
                        else:
                            st.caption(f"🚩 {nm}：标题中未见明显风险信号")
                    st.caption("⚠️ 风险标签由 AI 据新闻标题推断，可能不全 / 滞后，仅供参考。")
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

    if action_button("🔄 拉取本场两队阵容（FotMob）"):
        try:
            with st.spinner("从 FotMob 拉取两队阵容…"):
                r_home = squads_mod.refresh_fm_squad(home)
                r_away = squads_mod.refresh_fm_squad(away)
            st.success(
                f"已更新：{zh(home)} {r_home['count']} 人（评分 {r_home['rated']}·伤停 {r_home['injured']}） · "
                f"{zh(away)} {r_away['count']} 人（评分 {r_away['rated']}·伤停 {r_away['injured']}）")
        except Exception as exc:
            st.error(f"拉取失败：{exc}（FotMob 为非官方页面解析，结构变动/限流都可能导致失败）")

    if llm_configured() and action_button("🤖 AI 音译球员名（两队 · 结果缓存）"):
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

        vs_home = squads_mod.squad_value_summary(sq_home["groups"] if sq_home else None)
        vs_away = squads_mod.squad_value_summary(sq_away["groups"] if sq_away else None)
        if vs_home["total"] or vs_away["total"]:
            def _eur(v):
                return f"€{v / 1e9:.2f}b" if v >= 1e9 else f"€{v / 1e6:.1f}m"

            st.markdown("**身价对比**")
            vm1, vm2, vm3 = st.columns(3)
            vm1.metric(f"{zh(home)} 总身价", _eur(vs_home["total"]))
            vm2.metric(f"{zh(away)} 总身价", _eur(vs_away["total"]))
            hi, lo = max(vs_home["total"], vs_away["total"]), min(vs_home["total"], vs_away["total"])
            vm3.metric("身价差距", f"{hi / lo:.1f} 倍" if lo > 0 else "—")
            tv1, tv2 = st.columns(2)
            for col, team, vs in [(tv1, home, vs_home), (tv2, away, vs_away)]:
                with col:
                    st.caption(f"{zh(team)} · 位置身价结构")
                    st.dataframe(pd.DataFrame([
                        {"位置": squads_mod.POS_ZH.get(p, p), "身价": _eur(vs["by_position"][p])}
                        for p in squads_mod.POS_ORDER if vs["by_position"].get(p)]),
                        hide_index=True, width="stretch")
                    st.caption(f"{zh(team)} · Top5 身价")
                    st.dataframe(pd.DataFrame([{
                        "球员": (f"{p['name_zh']}（{p['player_name']}）" if p.get("name_zh") else p["player_name"]),
                        "位置": squads_mod.POS_ZH.get(p.get("position"), p.get("position")),
                        "身价": _eur(float(p["value"])),
                    } for p in vs["top5"]]), hide_index=True, width="stretch")
            st.caption("身价代表阵容上限，不等于比赛结果；低身价球队若防守纪律强、反击高效，仍可能守住让球盘。")
        else:
            st.caption("（暂无身价数据——请点上方「拉取本场两队阵容」重新拉取；FotMob transferValue 偶有缺失。）")

        st.markdown("**预计首发（估计）**")
        st.caption("⚠️ 大名单是确定的，但谁首发不确定；以下按身价 / 评分、排除伤停、按所选阵型估计，仅供参考。")
        formation = st.selectbox("阵型", list(squads_mod.FORMATIONS.keys()), key=f"formation:{home}:{away}")

        def _eur_xi(v):
            return f"€{v / 1e9:.2f}b" if v >= 1e9 else f"€{v / 1e6:.1f}m"

        lc1, lc2 = st.columns(2)
        for col, team, sq in [(lc1, home, sq_home), (lc2, away, sq_away)]:
            with col:
                if not sq:
                    st.caption(f"{zh(team)}：无阵容缓存。")
                    continue
                lineup = squads_mod.estimate_lineup(sq["groups"], formation)
                cap = f"{zh(team)} · {lineup['formation']} · {lineup['size']} 人"
                if lineup["total_value"]:
                    cap += f" · 预计首发身价 {_eur_xi(lineup['total_value'])}"
                st.caption(cap)
                st.dataframe(pd.DataFrame([{
                    "位置": squads_mod.POS_ZH.get(p.get("position"), p.get("position")),
                    "球员": (f"{p['name_zh']}（{p['player_name']}）" if p.get("name_zh") else p["player_name"]),
                    "号": p.get("number"),
                    "评分": (f"{p['rating']:.2f}" if p.get("rating") is not None else "—"),
                    "身价": (_eur_xi(float(p["value"])) if p.get("value") else "—"),
                } for p in lineup["xi"]]), hide_index=True, width="stretch")

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

        from wc2026.analysis import tactics as _tactics
        _tr = _tactics.tactical_read(
            zh(home), zh(away),
            sq_home.get("formation") if sq_home else None,
            sq_away.get("formation") if sq_away else None,
            gk_home=avg_h.get("Goalkeeper"), gk_away=avg_a.get("Goalkeeper"))
        st.markdown("**🎯 战术与阵容研判（判断修正参考）**")
        for _n in _tr["notes"]:
            st.markdown(f"- {_n}")
        st.caption("阵型取自 FotMob 最近一场；门将/球员评分赛前多为空、开赛后填充。"
                   "以上为方向性人工修正参考，不直接改写模型概率（模型按真实赛果校准）。")


with st.expander("🤖 AI 对话（结合本场全部已加载数据问答 / 粘贴材料分析）", expanded=False):
    if not llm_configured():
        st.caption("需接入 LLM（在 .env 配置 LLM_API_KEY）后可用；当前未配置。")
    elif not is_owner():
        st.caption("🔒 AI 对话仅所有者可用（会消耗 LLM token）；访客只读。")
    else:
        from wc2026.llm import match_chat
        from wc2026.analysis import schedule as _schx
        from wc2026.data import squads as _squads
        _cres = None
        if selected_fixture is not None:
            _rr = _schx.match_result(selected_fixture.get("home_score"), selected_fixture.get("away_score"),
                                     zh(home), zh(away))
            _cres = _rr["text"] if _rr["finished"] else None
        _news = st.session_state.get(f"news:{home}:{away}")
        _news_titles = [it["title"] for it in _news["items"][:8]] if _news and _news.get("items") else None
        _sv = None
        if sq_home or sq_away:
            _a = _squads.squad_value_summary(sq_home["groups"] if sq_home else None)
            _b = _squads.squad_value_summary(sq_away["groups"] if sq_away else None)
            if _a["total"] or _b["total"]:
                _sv = f"{zh(home)} €{_a['total'] / 1e6:.0f}m vs {zh(away)} €{_b['total'] / 1e6:.0f}m"
        _tact = None
        if (sq_home and sq_home.get("formation")) or (sq_away and sq_away.get("formation")):
            from wc2026.analysis import tactics as _tac
            _tr2 = _tac.tactical_read(zh(home), zh(away),
                                      sq_home.get("formation") if sq_home else None,
                                      sq_away.get("formation") if sq_away else None)
            _tact = "；".join(_tr2["notes"])
        from wc2026.analysis import fatigue as _fat_mod
        _fat_r = _fat_mod.match_fatigue(home, away, fixtures, selected_fixture)
        _fat = "；".join(_fat_r["notes"]) if _fat_r.get("notes") else None
        ev = reason["evidence"]
        ctx = match_chat.build_context({
            "home": zh(home), "away": zh(away),
            "home_rank": _hr, "away_rank": _ar, "rank_total": _rtot,
            "result": _cres, "context_notes": context_notes,
            "xg": (lam, mu), "probs": x,
            "over_under25": markets["over_under"].get("2.5"),
            "goal_bands": markets["goal_bands"], "btts": markets["btts"]["yes"],
            "correct_score_top": markets["correct_score_top"],
            "upset": ui, "strength": sp, "goal_rec": gs,
            "h2h": ev["h2h"], "home_form": ev["home_form"], "away_form": ev["away_form"],
            "squad_value": _sv, "news_titles": _news_titles, "tactics": _tact, "fatigue": _fat,
        })
        chat_key = f"matchchat:{home}:{away}"
        history = st.session_state.setdefault(chat_key, [])
        for m in history:
            st.markdown(f"**{'🧑 你' if m['role'] == 'user' else '🤖 AI'}：** {m['content']}")
        q = st.text_area("输入问题，或粘贴文字让 AI 结合本场数据分析", key=f"chatq:{home}:{away}", height=90,
                         placeholder="例：这场适合打什么盘口？爆冷风险来自哪？把我这段情报结合数据分析一下…")
        cc1, cc2, cc3 = st.columns([1, 1, 2])
        if cc1.button("发送", key=f"chatsend:{home}:{away}") and q.strip():
            history.append({"role": "user", "content": q.strip()})
            with st.spinner("AI 结合本场数据分析中…"):
                ans = match_chat.ask(q.strip(), ctx, history)
            history.append({"role": "assistant", "content": ans["text"]})
            st.rerun()
        if cc2.button("清空对话", key=f"chatclear:{home}:{away}"):
            st.session_state[chat_key] = []
            st.rerun()
        if st.checkbox("查看 AI 看到的本场数据摘要", key=f"chatctx:{home}:{away}"):
            st.code(ctx)
        st.caption("AI 仅依据本场已加载数据作答；未拉取的赔率/阵容/资讯不在其中（先在上方拉取可纳入）。仅供参考、非投注建议。")


with st.expander("💰 价值扫描（全场次自动找价值盘，需 The Odds API key）", expanded=False):
    from wc2026.config import settings as _settings
    if not _settings.odds_api_key:
        st.warning("未配置 ODDS_API_KEY。注册 the-odds-api.com（免费）拿 key 填进 .env 重启即可。")
        st.caption("（上方「💰 价值 & 凯利」可手动输入单场赔率分析。）")
    else:
        st.warning("⚠️ 纯模型 vs 市场会产生大量**假价值**（本模型对部分队伍有高估、回测显示会失灵）。"
                   "超大 edge(>50%) 几乎一定是模型错而非庄家错。用下方滑块向市场收缩，只留温和分歧。")
        blend = st.slider("模型权重（越低越信市场，推荐 0.4–0.6）", 0.0, 1.0, 0.5, 0.1)
        if action_button("📟 查询 The Odds API 剩余请求"):
            from wc2026.data.sources import odds_api
            try:
                with st.spinner("查询配额…"):
                    st.session_state["odds_quota"] = odds_api.get_quota()
            except Exception as exc:
                st.error(f"配额查询失败：{exc}")
        render_quota(st.session_state.get("odds_quota", {}))
        if action_button("🔍 拉取当前赔率并扫描"):
            from wc2026.data.sources import odds_api
            try:
                with st.spinner("拉取赔率并扫描…"):
                    odds_map = odds_api.fetch_h2h_odds()
                    st.session_state["odds_quota"] = odds_api.last_quota()
                    scan = value.scan_value(model, odds_map, blend=blend)
                    from wc2026.data import odds_history
                    odds_history.record_event_odds_map({k: {"h2h": v} for k, v in odds_map.items()})
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
    if action_button("▶️ 运行回测（2014 / 2018 / 2022）"):
        from wc2026.backtest.runner import backtest_ensemble
        rows, results = [], []
        with st.spinner("训练并回测中…"):
            for y in ["2014", "2018", "2022"]:
                r = backtest_ensemble(y)
                results.append(r)
                rows.append({"届": y, "场次": r["n"], "LogLoss": f"{r['log_loss']:.4f}",
                             "基准": f"{r['baseline_log_loss']:.4f}", "Brier": f"{r['brier']:.3f}",
                             "准确率": f"{r['accuracy']:.1%}"})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("LogLoss < 1.0986 = 比瞎猜有预测力；Brier 越低越好。2022 是史上最大冷门届，模型会失灵——真实局限，不粉饰。")

        agg = {}
        for r in results:
            for b in r.get("calibration", []):
                a = agg.setdefault(b["range"], {"n": 0, "ps": 0.0, "af": 0.0})
                a["n"] += b["n"]; a["ps"] += b["pred_mean"] * b["n"]; a["af"] += b["actual_freq"] * b["n"]
        if agg:
            cal = [{"预测概率区间": k, "平均预测": round(v["ps"] / v["n"], 3),
                    "实际频率": round(v["af"] / v["n"], 3), "样本": v["n"]}
                   for k, v in sorted(agg.items())]
            st.markdown("**校准曲线（预测概率 vs 实际发生频率，越贴近对角线越准）**")
            cfig = go.Figure()
            cfig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="完美校准",
                                      line=dict(dash="dash", color="#9aa7b6")))
            cfig.add_trace(go.Scatter(x=[c["平均预测"] for c in cal], y=[c["实际频率"] for c in cal],
                                      mode="lines+markers", name="模型(三届合并)"))
            cfig.update_layout(height=300, xaxis_title="平均预测概率", yaxis_title="实际频率",
                               xaxis_range=[0, 1], yaxis_range=[0, 1], margin=dict(l=10, r=10, t=10, b=10),
                               template="plotly_dark" if current_theme() == "dark" else "plotly_white",
                               paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
            st.plotly_chart(cfig, width="stretch")
            st.dataframe(pd.DataFrame(cal), hide_index=True, width="stretch")
            st.caption("⚠️ 校准是「价值」可信的前提：若预测 60% 实际只兑现 45%，说明模型高估，据此算出的「价值」多半是假 edge。"
                       "高关注度场次市场更有效，建议在「价值扫描」里把模型权重调低（更信市场，推荐 0.4–0.6）。")
