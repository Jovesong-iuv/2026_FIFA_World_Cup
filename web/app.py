"""2026 世界杯预测 Streamlit 看板（赛程驱动 + 中文 + 证据 + 资讯）。

启动： streamlit run web/app.py
"""
import sys
import hmac
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from wc2026 import auth
from wc2026.config import settings
from wc2026.data.db import get_conn, init_db
from wc2026.data.results import apply_results_overlay
from wc2026.data.ingest import ingest_international_results
from wc2026.data.sources import news as news_mod
from wc2026.data.sources.fixtures_2026 import (fetch_fixture_snapshot,
                                               merge_fixture_snapshots)
from wc2026.data.team_names import zh
from wc2026.analysis.environment import match_environment_report
from wc2026.llm import reasoning
from wc2026.markets import derive, value
from wc2026.models.predictor import DC_PATH, ELO_PATH, get_model, train_and_save
from wc2026.access import owner_key_matches

st.set_page_config(page_title="足球赛事预测", page_icon="⚽", layout="wide")
HOSTS = {"Mexico", "Canada", "United States"}
COMPETITION_OPTIONS = ["巴甲", "欧冠", "世界杯"]
WORLD_CUP_PAGE_OPTIONS = [
    "首页", "淘汰赛", "单场分析", "推荐对比", "晋级之路", "小组赛赛程",
    "小组出线", "球队查询", "大胆预测", "赛后复盘", "AI 分析师",
]

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
        [data-baseweb="select"] input,
        [data-baseweb="input"] input,
        textarea {
            font-size: 16px !important;
        }
        div[data-testid="stPills"] [role="group"],
        div[data-testid="stSegmentedControl"] [role="group"],
        div[data-testid="stButtonGroup"] div[role="radiogroup"] {
            display: flex;
            gap: 6px;
            overflow-x: auto;
            padding-bottom: 2px;
            scrollbar-width: thin;
        }
        div[data-testid="stButtonGroup"] div[role="radiogroup"] {
            flex-wrap: nowrap !important;
        }
        div[data-testid="stButtonGroup"] div[role="radiogroup"] button {
            flex: 0 0 auto;
            max-width: min(340px, 86vw);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
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
        .wc-topbar {
            position: sticky;
            top: 0;
            z-index: 20;
            margin: -12px 0 16px;
            padding: 8px 10px;
            border: 1px solid var(--wc-line);
            border-radius: 8px;
            background: color-mix(in srgb, var(--wc-surface) 94%, transparent);
            backdrop-filter: blur(14px);
            box-shadow: 0 10px 28px rgba(15, 23, 42, .08);
        }
        .wc-brand {
            display: flex;
            align-items: center;
            gap: 8px;
            min-height: 38px;
            font-weight: 900;
            color: var(--wc-text);
            white-space: nowrap;
        }
        .wc-brand-mark {
            display: inline-grid;
            place-items: center;
            width: 28px;
            height: 28px;
            border-radius: 8px;
            background: #0f766e;
            color: white;
            font-size: 15px;
        }
        div[data-testid="stHorizontalBlock"]:has(.wc-brand) {
            position: sticky;
            top: 0;
            z-index: 20;
            margin: -12px 0 16px;
            padding: 8px 10px;
            border: 1px solid var(--wc-line);
            border-radius: 8px;
            background: color-mix(in srgb, var(--wc-surface) 94%, transparent);
            backdrop-filter: blur(14px);
            box-shadow: 0 10px 28px rgba(15, 23, 42, .08);
        }
        div[data-testid="stHorizontalBlock"]:has(.wc-brand) div[role="radiogroup"] {
            display: flex;
            gap: 6px;
            justify-content: flex-end;
            overflow-x: auto;
            padding-bottom: 2px;
        }
        div[data-testid="stHorizontalBlock"]:has(.wc-brand) div[role="radiogroup"] label {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 38px;
            margin: 0;
            padding: 0 12px;
            border: 1px solid transparent;
            border-radius: 8px;
            background: transparent;
            white-space: nowrap;
        }
        div[data-testid="stHorizontalBlock"]:has(.wc-brand) div[role="radiogroup"] label:has(input:checked) {
            border-color: rgba(15, 118, 110, .28);
            background: rgba(15, 118, 110, .12);
            font-weight: 800;
        }
        div[data-testid="stHorizontalBlock"]:has(.wc-brand) div[role="radiogroup"] label > div:first-child {
            display: none;
        }
        div[data-testid="stHorizontalBlock"]:has(.wc-brand) div[role="radiogroup"] label p {
            margin: 0;
        }
        .wc-analysis-panel {
            border: 1px solid var(--wc-line);
            border-radius: 8px;
            padding: 14px 16px;
            margin-bottom: 16px;
            background: var(--wc-surface);
            box-shadow: 0 8px 24px rgba(15, 23, 42, .05);
        }
        .wc-schedule-head {
            display: flex;
            justify-content: space-between;
            gap: 12px;
            align-items: flex-end;
            margin-bottom: 10px;
        }
        .wc-schedule-head h3 {
            margin: 0;
            font-size: 20px;
            color: var(--wc-text);
        }
        .wc-schedule-head p {
            margin: 4px 0 0;
            color: var(--wc-muted);
            font-size: 13px;
        }
        .wc-timeline {
            position: relative;
            display: grid;
            gap: 10px;
            margin-top: 14px;
        }
        .wc-timeline::before {
            content: "";
            position: absolute;
            left: 74px;
            top: 6px;
            bottom: 6px;
            width: 2px;
            background: var(--wc-line);
        }
        .wc-match-card {
            position: relative;
            display: grid;
            grid-template-columns: 86px 1fr;
            gap: 14px;
            align-items: stretch;
        }
        .wc-match-time {
            z-index: 1;
            display: grid;
            align-content: center;
            justify-items: end;
            padding-right: 18px;
            color: var(--wc-text);
            font-weight: 900;
            font-size: 18px;
        }
        .wc-match-time small {
            margin-top: 4px;
            color: var(--wc-muted);
            font-size: 12px;
            font-weight: 700;
        }
        .wc-match-body {
            border: 1px solid var(--wc-line);
            border-radius: 8px;
            padding: 12px 14px;
            background: var(--wc-surface);
            box-shadow: 0 8px 22px rgba(15, 23, 42, .05);
        }
        .wc-match-meta {
            display: flex;
            justify-content: space-between;
            gap: 10px;
            color: var(--wc-muted);
            font-size: 12px;
            margin-bottom: 8px;
        }
        .wc-team-row {
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 12px;
            align-items: center;
            min-height: 36px;
            margin: 4px 0;
            font-size: 16px;
            font-weight: 800;
        }
        .wc-score {
            min-width: 42px;
            text-align: center;
            border-radius: 8px;
            padding: 7px 8px;
            background: var(--wc-surface-2);
            color: var(--wc-text);
            font-weight: 900;
            line-height: 1.1;
        }
        .wc-status {
            color: var(--wc-primary);
            font-size: 12px;
            font-weight: 800;
        }
        .wc-group-grid,
        .wc-ko-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 14px;
            align-items: start;
        }
        .wc-ko-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .wc-group-card,
        .wc-ko-card {
            border: 1px solid var(--wc-line);
            border-radius: 10px;
            background: var(--wc-surface);
            min-width: 0;
        }
        .wc-group-card {
            padding: 10px 12px;
            margin-bottom: 0;
        }
        .wc-ko-card {
            padding: 12px 14px;
        }
        .wc-ko-card.finished {
            opacity: .75;
        }
        .wc-ko-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 10px;
            margin-bottom: 6px;
        }
        .wc-ko-head span {
            min-width: 0;
        }
        .wc-ko-meta {
            color: var(--wc-muted);
            font-size: 12px;
        }
        .wc-ko-team-main {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 8px;
        }
        .wc-ko-team-note {
            margin-top: 2px;
            font-size: 11px;
            color: var(--wc-muted);
        }
        .wc-ko-divider {
            border-top: 1px solid var(--wc-line);
            margin: 6px 0;
        }
        @media (max-width: 760px) {
            .block-container {
                padding: .85rem .8rem 2rem;
                max-width: 100%;
            }
            div[data-testid="stHorizontalBlock"]:has(.wc-brand) {
                position: static;
                margin: -4px 0 12px;
                padding: 8px;
            }
            .wc-brand {
                justify-content: center;
                margin-bottom: 4px;
            }
            div[data-testid="stHorizontalBlock"]:has(.wc-brand) div[role="radiogroup"] {
                justify-content: flex-start;
            }
            div[data-testid="stHorizontalBlock"]:has(.wc-brand) div[role="radiogroup"] label {
                min-height: 34px;
                padding: 0 10px;
                font-size: 13px;
            }
            .wc-hero {
                padding: 16px;
                margin-bottom: 12px;
            }
            .wc-hero h1 {
                font-size: 22px;
            }
            .wc-hero p {
                font-size: 13px;
            }
            .wc-schedule-head {
                display: block;
            }
            .wc-timeline::before {
                left: 56px;
            }
            .wc-match-card {
                grid-template-columns: 66px 1fr;
                gap: 10px;
            }
            .wc-match-time {
                padding-right: 12px;
                font-size: 16px;
            }
            .wc-match-body {
                padding: 10px;
            }
            .wc-match-meta {
                display: block;
                line-height: 1.7;
            }
            .wc-team-row {
                font-size: 14px;
                grid-template-columns: minmax(0, 1fr) auto;
                min-height: 34px;
                margin: 5px 0;
            }
            .wc-team-row span:first-child {
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
            div[data-testid="stDataFrame"],
            div[data-testid="stDataEditor"] {
                overflow-x: auto;
            }
            div[data-testid="stPills"] [role="group"],
            div[data-testid="stSegmentedControl"] [role="group"],
            div[data-testid="stButtonGroup"] div[role="radiogroup"] {
                flex-wrap: nowrap;
            }
            .wc-group-grid,
            .wc-ko-grid {
                grid-template-columns: 1fr;
                gap: 10px;
            }
            .wc-group-card {
                overflow-x: auto;
            }
            .wc-ko-card {
                padding: 11px 12px;
            }
            .wc-ko-head,
            .wc-ko-team-main {
                align-items: flex-start;
                flex-direction: column;
            }
            .wc-ko-meta {
                line-height: 1.45;
            }
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


def _group_sort_key(group: str) -> tuple[int, str]:
    name = group or ""
    if name == "淘汰赛":
        return (99, name)
    if name.startswith("Group ") and len(name) >= 7:
        letter = name.replace("Group ", "", 1).strip()[:1].upper()
        if "A" <= letter <= "Z":
            return (ord(letter) - ord("A"), name)
    if len(name) >= 2 and name[1] == "组" and "A" <= name[0].upper() <= "Z":
        return (ord(name[0].upper()) - ord("A"), name)
    return (50, name)


def _sorted_groups(groups) -> list[str]:
    return sorted(groups, key=_group_sort_key)


def render_top_nav(page_options: list[str]) -> tuple[str, str | None]:
    brand_col, competition_col, nav_col = st.columns([1.3, 2, 5.3])
    with brand_col:
        st.markdown(
            '<div class="wc-brand"><span class="wc-brand-mark">AI</span><span>足球赛事预测</span></div>',
            unsafe_allow_html=True,
        )
    with competition_col:
        competition = st.radio(
            "赛事", COMPETITION_OPTIONS, horizontal=True, label_visibility="collapsed",
            key="top_competition_nav",
        )
    page = None
    if competition == "世界杯":
        with nav_col:
            page = st.radio(
                "页面", page_options, horizontal=True, label_visibility="collapsed",
                key="top_page_nav",
            )
    return competition, page


def _build_group_strategic_analysis(model, home: str, away: str,
                                    fixture: dict | None, fixtures: list) -> dict:
    """构建小组赛深度战略分析：出线形势 + R32对位 + 战略考量 + 跨组联动。"""
    from wc2026.analysis import groups as _grp, tournament as _tour
    from wc2026.data.flags import flag_emoji as _flag
    from wc2026.data.team_names import zh as _zh

    gd = _grp.load_group_data(model)
    if not gd:
        return {"available": False, "text": "暂无小组赛数据"}

    standings = _grp.compute_standings(gd)

    # 蒙特卡洛模拟（缓存）
    try:
        sig = _grp.played_signature(gd)
        key = f"gsa_sim:{hash(sig)}"
        if key not in st.session_state:
            st.session_state[key] = _grp.simulate_groups(model, gd, n_sims=2000)
        sim = st.session_state[key]
    except Exception:
        sim = {}

    r32 = _tour.R32_SLOTS

    def _group_of(team):
        for gname, data in gd.items():
            if team in data["teams"]:
                return gname
        return None

    def _team_sim(team):
        for rows in sim.values():
            for r in rows:
                if r["team"] == team:
                    return r
        return {}

    def _team_row(team, gname):
        for r in standings.get(gname, []):
            if r["team"] == team:
                return r
        return None

    def _parse_slot(code):
        if code.startswith("3"):
            gl = list(code[1:])
            return {"type": "third", "desc": f"最佳第三({'/'.join(gl)}组)", "groups": gl}
        if code.startswith("1"):
            g = code[1:]
            return {"type": "winner", "desc": f"{g}组头名", "group": g}
        if code.startswith("2"):
            g = code[1:]
            return {"type": "runner_up", "desc": f"{g}组次名", "group": g}
        return {"type": "unknown", "desc": code}

    def _slot_proj(code):
        """投影 slot 对应的最可能球队。"""
        if code.startswith("3"):
            best_t, best_p = None, 0
            for g in code[1:]:
                for r in sim.get(f"Group {g}", []):
                    if r.get("third_advance", 0) > best_p:
                        best_p = r["third_advance"]
                        best_t = r["team"]
            return best_t, best_p
        if code.startswith("1"):
            g = code[1:]
            rows = sim.get(f"Group {g}", [])
            if rows:
                b = max(rows, key=lambda r: r.get("first", 0))
                return b["team"], b.get("first", 0)
        if code.startswith("2"):
            g = code[1:]
            rows = sim.get(f"Group {g}", [])
            if rows:
                b = max(rows, key=lambda r: r.get("top2", 0) - r.get("first", 0))
                return b["team"], b.get("top2", 0) - b.get("first", 0)
        return None, 0

    def _find_r32(gletter, pos):
        """查找某组某名次对应的 R32 对阵信息。"""
        code = f"{pos}{gletter}"
        for idx, (h, a) in enumerate(r32):
            mn = 73 + idx
            if h == code or a == code:
                opp = a if h == code else h
                opp_info = _parse_slot(opp)
                opp_t, opp_p = _slot_proj(opp)
                return {
                    "match_num": mn,
                    "my_slot": code,
                    "opponent_slot": opp,
                    "opponent_desc": opp_info["desc"],
                    "opponent_team": opp_t,
                    "opponent_team_cn": _zh(opp_t) if opp_t else "待定",
                    "opponent_flag": _flag(opp_t) if opp_t else "",
                    "opponent_prob": round(opp_p, 3),
                }
        return None

    def _find_r32_third(gletter):
        """查找某组第三名若递补晋级，可能的 R32 对阵信息。"""
        candidates = []
        for idx, (h, a) in enumerate(r32):
            for slot in (h, a):
                if slot.startswith("3") and gletter in slot[1:]:
                    opp = a if h == slot else h
                    opp_info = _parse_slot(opp)
                    opp_t, opp_p = _slot_proj(opp)
                    candidates.append({
                        "match_num": 73 + idx,
                        "my_slot": slot,
                        "opponent_slot": opp,
                        "opponent_desc": opp_info["desc"],
                        "opponent_team": opp_t,
                        "opponent_team_cn": _zh(opp_t) if opp_t else "待定",
                        "opponent_flag": _flag(opp_t) if opp_t else "",
                        "opponent_prob": round(opp_p, 3),
                    })
        return candidates

    def _standings_json(gname):
        return [{
            "team": r["team"], "team_cn": _zh(r["team"]),
            "flag": _flag(r["team"]), "rank": r["rank"],
            "pts": r["pts"], "gd": r["gd"], "gf": r["gf"], "ga": r["ga"],
            "played": r["played"], "w": r["w"], "d": r["d"], "l": r["l"],
        } for r in standings.get(gname, [])]

    def _elo(team):
        try:
            return model.elo.ratings.get(team, 1500)
        except Exception:
            return 1500

    def _build_one(team):
        gname = _group_of(team)
        if not gname:
            return None
        gl = gname.replace("Group ", "")
        row = _team_row(team, gname)
        sprobs = _team_sim(team)
        return {
            "team": team, "team_cn": _zh(team), "flag": _flag(team),
            "group": gname, "group_letter": gl,
            "standings": _standings_json(gname),
            "rank": row["rank"] if row else None,
            "pts": row["pts"] if row else 0,
            "gd": row["gd"] if row else 0,
            "gf": row["gf"] if row else 0,
            "ga": row["ga"] if row else 0,
            "played": row["played"] if row else 0,
            "w": row["w"] if row else 0,
            "d": row["d"] if row else 0,
            "l": row["l"] if row else 0,
            "sim_first": round(sprobs.get("first", 0), 3),
            "sim_top2": round(sprobs.get("top2", 0), 3),
            "sim_qualify": round(sprobs.get("qualify", 0), 3),
            "sim_third": round(sprobs.get("third", 0), 3),
            "sim_third_advance": round(sprobs.get("third_advance", 0), 3),
            "r32_first": _find_r32(gl, "1"),
            "r32_second": _find_r32(gl, "2"),
            "r32_third": _find_r32_third(gl),
            "elo": _elo(team),
        }

    ha = _build_one(home)
    aa = _build_one(away)
    if not ha and not aa:
        return {"available": False, "text": "当前比赛不涉及小组赛球队"}

    # --- 生成战略分析文本 ---
    notes = []

    def _add(cat, text):
        notes.append({"category": cat, "text": text})

    _STAR = {"Argentina": "梅西", "France": "姆巴佩", "Norway": "哈兰德",
             "Brazil": "维尼修斯", "England": "凯恩", "Portugal": "C罗",
             "Spain": "亚马尔", "Germany": "穆西亚拉", "Netherlands": "德佩",
             "Italy": "基耶萨", "Belgium": "德布劳内", "Croatia": "莫德里奇"}

    for label, ta in [("主队", ha), ("客队", aa)]:
        if not ta:
            continue
        cn = ta["team_cn"]
        gl = ta["group_letter"]
        pts = ta["pts"]
        rk = ta["rank"]
        sq = ta["sim_qualify"]
        sf = ta["sim_first"]
        gd = ta["gd"]
        gf = ta["gf"]

        # 出线形势
        if sq > 0.9:
            qual_text = f"{cn}（{gl}组）已基本确认出线，模拟出线概率 {sq:.0%}"
        elif sq > 0.6:
            qual_text = f"{cn}（{gl}组）出线形势较好，模拟出线概率 {sq:.0%}"
        elif sq > 0.3:
            qual_text = f"{cn}（{gl}组）出线形势不明朗，模拟出线概率 {sq:.0%}"
        else:
            qual_text = f"{cn}（{gl}组）出线形势危急，模拟出线概率仅 {sq:.0%}"

        if rk:
            qual_text += f"，当前排名第{rk}（{pts}分，净胜球{'+' if gd >= 0 else ''}{gd}，进{gf}球）"
        if sf > 0.7:
            qual_text += f"，头名概率 {sf:.0%}"
        elif sf > 0.3:
            qual_text += f"，头名概率 {sf:.0%}，仍有争首机会"
        _add("出线形势", qual_text)

        # R32 对位
        r1 = ta.get("r32_first")
        r2 = ta.get("r32_second")
        if r1:
            r32_text = f"若以头名出线 → 第{r1['match_num']}场 vs {r1['opponent_desc']}"
            if r1.get("opponent_team_cn") and r1["opponent_team_cn"] != "待定":
                r32_text += f"（投影：{r1['opponent_flag']} {r1['opponent_team_cn']} {r1['opponent_prob']:.0%}）"
            _add("R32对位", r32_text)
        if r2:
            r32_text = f"若以次名出线 → 第{r2['match_num']}场 vs {r2['opponent_desc']}"
            if r2.get("opponent_team_cn") and r2["opponent_team_cn"] != "待定":
                r32_text += f"（投影：{r2['opponent_flag']} {r2['opponent_team_cn']} {r2['opponent_prob']:.0%}）"
            _add("R32对位", r32_text)

        # R32 对位：第三名递补
        r3 = ta.get("r32_third", [])
        st = ta.get("sim_third", 0)
        sta = ta.get("sim_third_advance", 0)
        if r3 and (st > 0.1 or sta > 0.05):
            r3_text = f"若以第三名递补 → "
            r3_matches = [f"第{c['match_num']}场 vs {c['opponent_desc']}" for c in r3]
            r3_text += " / ".join(r3_matches)
            # 找最可能的对手
            best_c = max(r3, key=lambda c: c.get("opponent_prob", 0))
            if best_c.get("opponent_team_cn") and best_c["opponent_team_cn"] != "待定":
                r3_text += f"（最可能：第{best_c['match_num']}场 vs {best_c['opponent_flag']} {best_c['opponent_team_cn']} {best_c['opponent_prob']:.0%}）"
            _add("R32对位", r3_text)

        # 战略考量：R32 对手实力分析
        likely_first = sf > 0.5
        r_proj = r1 if likely_first else r2
        if r_proj and r_proj.get("opponent_team"):
            opp_elo = _elo(r_proj["opponent_team"])
            opp_cn = r_proj["opponent_team_cn"]
            if opp_elo > 1850:
                _add("战略考量", f"{cn}{'大概率头名' if likely_first else '可能次名'}出线，32强投影对手 {opp_cn} 实力较强（Elo {opp_elo:.0f}），相关小组末轮排名变化需密切关注")
            elif opp_elo < 1600:
                _add("战略考量", f"{cn}{'大概率头名' if likely_first else '可能次名'}出线，32强投影对手 {opp_cn} 实力一般（Elo {opp_elo:.0f}），出线后赛程相对有利")

        # 战略考量：出线已定 vs 需要拼争
        if sq > 0.9 and ta["played"] >= 2:
            if sf > 0.8:
                _add("战略考量", f"{cn}已确认出线且大概率锁定头名，末轮可能轮换主力保存体能，但需权衡头名归属以确保淘汰赛有利对阵")
            else:
                _add("战略考量", f"{cn}已确认出线但头名尚未锁定，末轮仍需积极争胜以确保头名，获得更有利的32强对阵")
        elif sq < 0.4 and ta["played"] >= 2:
            _add("战略考量", f"{cn}出线形势危急，本场必须全力争胜，战意极高")

        # 第三名争夺：争取最佳第三递补
        if st > 0.15 and ta["played"] >= 2 and sq < 0.8:
            _add("第三名争夺", f"{cn}有 {st:.0%} 概率获得小组第三，需争取作为最佳第三名之一递补晋级（12组第三取前8名）")
            if sta > 0.05:
                _add("第三名争夺", f"当前模拟递补晋级概率 {sta:.0%}，净胜球({'+' if gd >= 0 else ''}{gd})和进球数({gf})对最佳第三排名至关重要，需尽可能争取进球")
            if st > 0.4 and sf < 0.3:
                _add("战略考量", f"{cn}大概率获得第三名（{st:.0%}），本场不仅要争胜还要争取多进球，净胜球和进球数直接影响能否作为最佳第三递补晋级")

        # 进球动机
        if sq > 0.9 and sf > 0.7:
            star = _STAR.get(ta["team"])
            if star:
                _add("进球动机", f"{cn}已基本锁定出线，{star}可能为争夺金靴奖而寻求进球，进球数可能偏高")

    # 同组对决 / 跨组联动
    if ha and aa and ha["group"] == aa["group"]:
        gl = ha["group_letter"]
        _add("同组对决", f"双方同处{gl}组，本场结果直接决定小组排名与出线归属，胜者占据主动权")
        if ha["sim_qualify"] > 0.8 and aa["sim_qualify"] > 0.8:
            _add("同组对决", f"双方均已接近出线，本场可能演变为争夺头名之战，平局亦可接受的情况下战意可能降低")
        if ha.get("sim_third", 0) > 0.2 and aa.get("sim_third", 0) > 0.2:
            _add("同组对决", f"双方均有较大概率获得第三名（{ha['team_cn']} {ha.get('sim_third',0):.0%} / {aa['team_cn']} {aa.get('sim_third',0):.0%}），本场净胜球和进球数直接影响最佳第三递补排名，战意极高")
    elif ha and aa:
        for ta in [ha, aa]:
            r1 = ta.get("r32_first")
            if r1 and r1.get("opponent_slot", "").startswith("3"):
                _add("跨组联动", f"{ta['team_cn']}若头名出线，对手来自{r1['opponent_desc']}，相关小组末轮结果将直接影响32强对位")
            r2 = ta.get("r32_second")
            if r2 and r2.get("opponent_slot", "").startswith("2"):
                opp_g = r2["opponent_slot"][1:]
                _add("跨组联动", f"{ta['team_cn']}若次名出线，将对阵 {opp_g}组次名，{opp_g}组末轮排名同样关键")
    elif ha:
        for ta in [ha]:
            r1 = ta.get("r32_first")
            if r1 and r1.get("opponent_slot", "").startswith("3"):
                _add("跨组联动", f"{ta['team_cn']}若头名出线，对手来自{r1['opponent_desc']}，相关小组末轮结果将直接影响32强对位")

    return {
        "available": True,
        "home": ha,
        "away": aa,
        "notes": notes,
    }


def _strategic_factors(gsa: dict, model, home: str, away: str) -> tuple:
    """根据战略分析计算有界调整因子。返回 (home_mult, away_mult, notes)。"""
    if not gsa or not gsa.get("available"):
        return 1.0, 1.0, []

    _STAR = {"Argentina": "梅西", "France": "姆巴佩", "Norway": "哈兰德",
             "Brazil": "维尼修斯", "England": "凯恩", "Portugal": "C罗",
             "Spain": "亚马尔", "Germany": "穆西亚拉", "Netherlands": "德佩",
             "Italy": "基耶萨", "Belgium": "德布劳内", "Croatia": "莫德里奇"}

    def _elo(team):
        try:
            return model.elo.ratings.get(team, 1500)
        except Exception:
            return 1500

    home_mult = 1.0
    away_mult = 1.0
    notes = []

    for side, ta in [("home", gsa.get("home")), ("away", gsa.get("away"))]:
        if not ta:
            continue

        mult = 1.0
        sq = ta.get("sim_qualify", 0.5)
        sf = ta.get("sim_first", 0.5)
        played = ta.get("played", 0)
        cn = ta.get("team_cn", "")

        # 出线已定 + 大概率头名 → 轮换
        if sq > 0.9 and sf > 0.8 and played >= 2:
            mult *= 0.90
            notes.append(f"{cn}已确认出线且大概率头名，预期轮换主力，进球×0.90")

        # 已出线但头名未定 → 战意提升
        elif sq > 0.9 and 0.3 < sf <= 0.8 and played >= 2:
            mult *= 1.06
            notes.append(f"{cn}已出线但头名未定，末轮仍需争胜，进球×1.06")

        # 出线形势危急 → 全力进攻
        elif sq < 0.5 and played >= 2:
            mult *= 1.08
            notes.append(f"{cn}出线形势危急，全力争胜，进球×1.08")

        # 基本出局 → 战意下降
        elif sq < 0.1 and played >= 2:
            mult *= 0.93
            notes.append(f"{cn}基本出局，战意下降，进球×0.93")

        # 争夺最佳第三递补 → 战意提升（净胜球/进球数关键）
        st = ta.get("sim_third", 0)
        if st > 0.3 and sq < 0.8 and played >= 2:
            mult *= 1.05
            notes.append(f"{cn}大概率小组第三({st:.0%})，争取最佳第三递补，净胜球/进球关键，进球×1.05")

        # 金靴奖动机
        if sq > 0.9 and sf > 0.7:
            star = _STAR.get(ta.get("team", ""))
            if star:
                mult *= 1.04
                notes.append(f"{cn}{star}争夺金靴，进球×1.04")

        # R32 对手实力影响
        r1 = ta.get("r32_first")
        if r1 and r1.get("opponent_team"):
            opp_elo = _elo(r1["opponent_team"])
            if opp_elo > 1850 and sq > 0.6 and sf > 0.5:
                mult *= 1.03
                notes.append(f"{cn}32强对手{r1['opponent_team_cn']}实力强(Elo {opp_elo:.0f})，需保排名，进球×1.03")
            elif opp_elo < 1600 and sq > 0.9 and sf > 0.8:
                mult *= 0.96
                notes.append(f"{cn}32强对手{r1['opponent_team_cn']}实力一般(Elo {opp_elo:.0f})，赛程有利可轮换，进球×0.96")

        # 有界夹紧 ±15%
        mult = max(0.85, min(1.15, mult))

        if side == "home":
            home_mult = mult
        else:
            away_mult = mult

    return home_mult, away_mult, notes


def _apply_strategic_adjustment(cl: dict, home_mult: float, away_mult: float,
                                notes: list) -> None:
    """将战略修正因子应用到 clemente 预测结果上（原地修改 cl）。"""
    if abs(home_mult - 1.0) < 1e-6 and abs(away_mult - 1.0) < 1e-6:
        return

    import numpy as np
    from math import exp, factorial

    orig_lam, orig_mu = cl["exp_goals"]
    new_lam = orig_lam * home_mult
    new_mu = orig_mu * away_mult

    cl["strategic"] = {
        "applied": True,
        "home_mult": round(home_mult, 3),
        "away_mult": round(away_mult, 3),
        "notes": notes,
        "original_lambda": round(orig_lam, 3),
        "original_mu": round(orig_mu, 3),
        "adjusted_lambda": round(new_lam, 3),
        "adjusted_mu": round(new_mu, 3),
    }

    def _poisson_pmf(k, lam):
        if lam <= 0:
            return 1.0 if k == 0 else 0.0
        return exp(-lam) * (lam ** k) / factorial(k)

    def _top_scores(mat, n=3):
        scores = []
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                scores.append({"score": f"{i}-{j}", "probability": round(float(mat[i, j]), 4)})
        scores.sort(key=lambda x: x["probability"], reverse=True)
        return scores[:n]

    mat = np.array(cl["matrix"], dtype=float)
    # 保存原始 top scorelines
    cl["strategic"]["original_top_scores"] = _top_scores(mat)
    n = mat.shape[0]
    new_mat = np.zeros_like(mat)

    for i in range(n):
        for j in range(n):
            old_pi = _poisson_pmf(i, orig_lam)
            old_pj = _poisson_pmf(j, orig_mu)
            new_pi = _poisson_pmf(i, new_lam)
            new_pj = _poisson_pmf(j, new_mu)
            ratio_i = new_pi / old_pi if old_pi > 1e-15 else 1.0
            ratio_j = new_pj / old_pj if old_pj > 1e-15 else 1.0
            new_mat[i, j] = mat[i, j] * ratio_i * ratio_j

    total = new_mat.sum()
    if total > 0:
        new_mat /= total

    # 修正后 top scorelines
    cl["strategic"]["adjusted_top_scores"] = _top_scores(new_mat)

    cl["matrix"] = new_mat
    cl["exp_goals"] = (round(new_lam, 3), round(new_mu, 3))
    cl["notes"] = list(cl.get("notes", [])) + [f"🎯 战略修正：{n}" for n in notes]


def render_bridge_dashboard(payload: dict) -> None:
    """Embed the reference-style HTML dashboard with current project data."""
    import json
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = f"""
<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root {{
  --bg:#0a0e1a; --glass:rgba(255,255,255,.055); --line:rgba(255,255,255,.10);
  --text:#f1f5f9; --muted:#94a3b8; --dim:#64748b;
  --blue:#3b82f6; --red:#ef4444; --gold:#f59e0b; --green:#10b981;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; font-family:-apple-system,BlinkMacSystemFont,"Noto Sans SC","Segoe UI",sans-serif;
  color:var(--text);
  background:radial-gradient(circle at 20% 20%,rgba(59,130,246,.16),transparent 34%),
             radial-gradient(circle at 82% 12%,rgba(139,92,246,.16),transparent 30%),
             linear-gradient(135deg,#070b14,#172044 48%,#211033);
  overflow-y:auto;
}}
/* 隐藏滚动条但保留滚动功能 */
body::-webkit-scrollbar {{ display:none; }}
body {{ scrollbar-width:none; -ms-overflow-style:none; }}
html {{ scrollbar-width:none; -ms-overflow-style:none; }}
html::-webkit-scrollbar {{ display:none; }}
.wrap {{ padding:22px; }}
.card {{
  border:1px solid var(--line); border-radius:18px; background:var(--glass);
  backdrop-filter:blur(18px); box-shadow:0 20px 60px rgba(0,0,0,.28); margin-bottom:18px;
}}
.title {{ display:flex; justify-content:space-between; gap:12px; align-items:flex-end; padding:18px 20px 0; }}
.title h2 {{ margin:0; font-size:20px; }}
.title p {{ margin:4px 0 0; color:var(--muted); font-size:13px; }}
.team-card {{ display:grid; grid-template-columns:1fr 96px 1fr; gap:26px; padding:28px 34px; }}
.side {{ min-width:0; }}
.hero-team {{ text-align:center; margin-bottom:22px; }}
.flag {{ font-size:48px; line-height:1; }}
.name {{ font-size:24px; font-weight:900; margin-top:8px; }}
.score {{ font-size:54px; line-height:1; margin-top:14px; font-weight:950; }}
.score.blue {{ color:var(--blue); }} .score.red {{ color:var(--red); }}
.score-label {{ color:var(--dim); font-weight:700; margin-top:8px; }}
.vs {{ display:grid; place-items:center; color:var(--red); font-size:42px; font-weight:950; }}
.info-row {{ display:grid; grid-template-columns:112px 1fr; gap:12px; padding:10px 0; border-bottom:1px solid rgba(255,255,255,.07); }}
.info-row .label {{ color:var(--dim); font-weight:800; }}
.info-row .value {{ color:var(--muted); text-align:right; font-weight:700; line-height:1.45; }}
.records {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; padding:0 20px 20px; }}
.record-box {{ padding:16px; border-radius:14px; background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.07); }}
.record-top {{ display:flex; justify-content:space-between; gap:10px; align-items:center; }}
.zone {{ padding:4px 9px; border-radius:999px; font-size:12px; font-weight:900; }}
.zone.advance {{ background:rgba(16,185,129,.18); color:#7bf7c5; }}
.zone.pending {{ background:rgba(245,158,11,.18); color:#ffd58a; }}
.zone.risk {{ background:rgba(239,68,68,.18); color:#ffaaa9; }}
.record-stats {{ display:grid; grid-template-columns:repeat(5,1fr); gap:8px; margin-top:14px; text-align:center; }}
.record-stats b {{ display:block; font-size:20px; }}
.record-stats span {{ color:var(--dim); font-size:12px; }}
.recent {{ margin-top:12px; color:var(--muted); font-size:13px; line-height:1.7; }}
.group-standings {{ padding:18px 20px 20px; }}
.group-standings h3 {{ margin:0 0 10px; font-size:15px; color:#ffd58a; }}
.group-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
.group-table th {{ color:var(--dim); padding:7px 6px; text-align:center; border-bottom:1px solid rgba(255,255,255,.08); }}
.group-table td {{ padding:8px 6px; text-align:center; border-bottom:1px solid rgba(255,255,255,.05); }}
.group-table td.team {{ text-align:left; font-weight:800; }}
.group-table tr.highlight td {{ background:rgba(59,130,246,.13); color:#dbeafe; }}
.group-pill {{ display:inline-block; padding:3px 8px; border-radius:999px; font-size:11px; font-weight:900; }}
.group-pill.advance {{ background:rgba(16,185,129,.18); color:#7bf7c5; }}
.group-pill.pending {{ background:rgba(245,158,11,.18); color:#ffd58a; }}
.group-pill.risk {{ background:rgba(239,68,68,.18); color:#ffaaa9; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; padding:20px; }}
.radar-wrap {{ display:grid; place-items:center; min-height:340px; }}
canvas {{ max-width:100%; }}
.bars {{ padding:12px 6px; }}
.bar-row {{ margin-bottom:10px; }}
.bar-head {{ display:flex; justify-content:space-between; color:var(--muted); font-size:12px; margin-bottom:4px; }}
.bar-track {{ display:flex; height:24px; border-radius:999px; overflow:hidden; background:rgba(255,255,255,.05); }}
.bar-a {{ background:linear-gradient(90deg,rgba(59,130,246,.35),rgba(59,130,246,.85)); display:grid; place-items:center; font-size:11px; font-weight:900; }}
.bar-b {{ background:linear-gradient(90deg,rgba(239,68,68,.85),rgba(239,68,68,.35)); display:grid; place-items:center; font-size:11px; font-weight:900; }}
.prob-grid {{ display:grid; grid-template-columns:330px 1fr; gap:18px; padding:20px; }}
.donut {{ position:relative; display:grid; place-items:center; min-height:260px; }}
.donut-center {{ position:absolute; text-align:center; pointer-events:none; }}
.donut-center b {{ font-size:30px; }}
.matrix {{ display:grid; grid-template-columns:34px repeat(8,1fr); gap:3px; }}
.cell {{ min-height:32px; border-radius:5px; display:grid; place-items:center; color:#dbeafe; font-size:11px; font-weight:800; }}
.axis {{ color:var(--muted); font-size:11px; display:grid; place-items:center; }}
.guide {{ padding:0 20px 20px; }}
.guide-list {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
.guide-item {{ border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:14px; text-align:center; background:rgba(255,255,255,.035); }}
.guide-item.reco {{ border-color:rgba(245,158,11,.45); background:rgba(245,158,11,.10); box-shadow:0 0 30px rgba(245,158,11,.08); }}
.guide-item .s {{ font-size:28px; font-weight:950; }}
.guide-item .p {{ color:var(--muted); font-size:13px; }}
.lambda-panel {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; padding:0 20px 20px; }}
.lambda-box {{ border:1px solid rgba(255,255,255,.08); border-radius:14px; padding:14px; background:rgba(255,255,255,.035); }}
.lambda-box h3 {{ margin:0 0 10px; font-size:14px; }}
.factor-row {{ display:grid; grid-template-columns:92px 1fr 42px; gap:8px; align-items:center; margin:7px 0; color:var(--muted); font-size:12px; }}
.factor-track {{ height:8px; border-radius:999px; background:rgba(255,255,255,.07); overflow:hidden; }}
.factor-fill {{ height:100%; border-radius:999px; background:linear-gradient(90deg,var(--blue),var(--gold)); }}
.margin-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
.margin-pill {{ border:1px solid rgba(255,255,255,.08); border-radius:12px; padding:10px; text-align:center; background:rgba(255,255,255,.03); }}
.margin-pill b {{ display:block; font-size:18px; }}
.margin-pill span {{ color:var(--dim); font-size:12px; }}
.odds {{ padding:20px; overflow:auto; }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ padding:11px 10px; border-bottom:1px solid rgba(255,255,255,.07); text-align:left; white-space:nowrap; }}
th {{ color:var(--dim); font-size:12px; }}
.dev-pos {{ color:#7bf7c5; font-weight:900; }} .dev-neg {{ color:#ffaaa9; font-weight:900; }} .dev-neu {{ color:var(--muted); font-weight:900; }}
.summary {{ display:grid; grid-template-columns:1.3fr 1fr; gap:18px; padding:20px; }}
.note {{ color:var(--muted); line-height:1.8; }}
.field-analysis {{ margin-top:14px; padding:14px; border-radius:14px; border:1px solid rgba(245,158,11,.22); background:rgba(245,158,11,.07); }}
.field-analysis h3 {{ margin:0 0 8px; font-size:15px; color:#ffd58a; }}
.field-analysis p {{ margin:0; white-space:pre-line; color:#dbe6f4; line-height:1.75; }}
.risk {{ border-left:3px solid var(--gold); padding:8px 0 8px 12px; color:var(--muted); margin:8px 0; }}
.champ {{ padding:20px; }}
.champ-row {{ display:grid; grid-template-columns:36px 1fr 80px; gap:10px; align-items:center; margin:10px 0; }}
.champ-bar {{ height:10px; border-radius:999px; background:rgba(255,255,255,.06); overflow:hidden; }}
.champ-fill {{ height:100%; background:linear-gradient(90deg,var(--blue),var(--gold)); border-radius:999px; }}
.gsa-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; padding:20px; }}
.gsa-team-box {{ padding:16px; border-radius:14px; background:rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.07); }}
.gsa-team-head {{ display:flex; align-items:center; gap:8px; margin-bottom:12px; }}
.gsa-team-head .flag {{ font-size:28px; }}
.gsa-team-head b {{ font-size:18px; }}
.gsa-group-tag {{ margin-left:auto; padding:2px 10px; border-radius:999px; font-size:12px; font-weight:800; background:rgba(59,130,246,.18); color:#93c5fd; }}
.gsa-probs {{ margin-bottom:14px; }}
.gsa-prob-row {{ display:grid; grid-template-columns:48px 1fr 48px; gap:8px; align-items:center; margin:5px 0; color:var(--muted); font-size:12px; }}
.gsa-prob-bar {{ height:8px; border-radius:999px; background:rgba(255,255,255,.07); overflow:hidden; }}
.gsa-fill {{ height:100%; border-radius:999px; }}
.gsa-prob-row b {{ text-align:right; font-size:13px; color:var(--text); }}
.gsa-section-title {{ font-size:13px; font-weight:800; color:var(--gold); margin:10px 0 6px; }}
.gsa-table {{ width:100%; border-collapse:collapse; font-size:12px; }}
.gsa-table th {{ color:var(--dim); padding:4px 3px; text-align:center; font-size:11px; border-bottom:1px solid rgba(255,255,255,.08); }}
.gsa-table td {{ padding:4px 3px; text-align:center; border-bottom:1px solid rgba(255,255,255,.04); }}
.gsa-table tr.highlight td {{ background:rgba(59,130,246,.12); color:#93c5fd; font-weight:800; }}
.gsa-r32-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
.gsa-r32-item {{ padding:10px; border-radius:10px; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); }}
.gsa-r32-cond {{ font-size:11px; color:var(--gold); font-weight:800; }}
.gsa-r32-match {{ font-size:12px; color:var(--muted); margin:2px 0; }}
.gsa-r32-opp {{ font-size:13px; font-weight:700; }}
.gsa-r32-proj {{ font-size:12px; color:var(--muted); margin-top:3px; }}
.gsa-r32-proj.muted {{ color:var(--dim); }}
.gsa-prob-tag {{ padding:1px 6px; border-radius:999px; font-size:10px; background:rgba(245,158,11,.15); color:#ffd58a; }}
.gsa-notes {{ padding:0 20px 20px; }}
.gsa-note {{ display:grid; grid-template-columns:88px 1fr; gap:10px; padding:8px 0; border-bottom:1px solid rgba(255,255,255,.05); }}
.gsa-note-cat {{ color:var(--gold); font-weight:800; font-size:12px; }}
.gsa-note-text {{ color:var(--muted); font-size:13px; line-height:1.6; }}
.strat-panel {{ margin:0 20px 16px; padding:14px; border-radius:14px; border:1px solid rgba(245,158,11,.25); background:rgba(245,158,11,.06); }}
.strat-header {{ font-size:14px; font-weight:800; color:#ffd58a; margin-bottom:8px; }}
.strat-factors {{ display:flex; gap:12px; margin:6px 0; }}
.strat-factor {{ padding:4px 12px; border-radius:999px; font-size:12px; font-weight:700; background:rgba(59,130,246,.12); color:#93c5fd; }}
.strat-factor.away {{ background:rgba(239,68,68,.12); color:#ffaaa9; }}
.strat-notes {{ margin-top:8px; }}
.strat-note {{ font-size:12px; color:var(--muted); padding:3px 0; line-height:1.5; }}
.strat-scores {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; margin:8px 0; }}
.strat-score-col {{ padding:10px; border-radius:10px; background:rgba(255,255,255,.03); border:1px solid rgba(255,255,255,.06); }}
.strat-score-title {{ font-size:11px; font-weight:800; color:var(--dim); margin-bottom:6px; }}
.strat-score-item {{ display:flex; justify-content:space-between; align-items:center; padding:3px 0; font-size:13px; color:var(--muted); }}
.strat-score-item .ss {{ font-weight:800; color:var(--text); }}
.strat-score-item.reco .ss {{ color:var(--gold); }}
.strat-score-item .sp {{ font-size:11px; color:var(--dim); }}
.ko-hero {{ padding:20px; }}
.ko-bar {{ display:flex; height:44px; border-radius:8px; overflow:hidden; border:1px solid rgba(255,255,255,.08); background:rgba(255,255,255,.04); }}
.ko-home {{ background:linear-gradient(90deg,#e83f5f,#c93454); display:grid; place-items:center; font-weight:900; }}
.ko-away {{ background:linear-gradient(90deg,#123a66,#0b2d52); display:grid; place-items:center; font-weight:900; }}
.ko-formula {{ text-align:center; color:var(--muted); line-height:1.8; margin-top:12px; }}
.ko-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; padding:0 20px 20px; }}
.ko-metric-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }}
.ko-metric {{ padding:14px; border-radius:12px; background:rgba(255,255,255,.035); border:1px solid rgba(255,255,255,.07); text-align:center; }}
.ko-metric b {{ display:block; font-size:22px; }}
.ko-metric span {{ color:var(--dim); font-size:12px; }}
.penalty-bar {{ display:flex; height:34px; border-radius:8px; overflow:hidden; margin-top:10px; }}
.total-split {{ display:grid; grid-template-columns:1fr auto 1fr; gap:18px; align-items:center; padding:16px 20px 6px; text-align:center; }}
.total-big {{ font-size:42px; font-weight:950; color:var(--green); }}
.total-small {{ font-size:42px; font-weight:950; color:#f43f5e; }}
.goal-bands {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; padding:8px 20px 20px; }}
.ev-table tr.reco td {{ background:rgba(16,185,129,.10); }}
.ev-table tr.avoid td {{ background:rgba(239,68,68,.10); }}
.tag-reco {{ display:inline-block; padding:2px 8px; border-radius:999px; background:rgba(16,185,129,.2); color:#7bf7c5; font-size:11px; font-weight:900; margin-left:6px; }}
.tag-avoid {{ display:inline-block; padding:2px 8px; border-radius:999px; background:rgba(239,68,68,.2); color:#ffaaa9; font-size:11px; font-weight:900; margin-left:6px; }}
.fatigue-cards {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; padding:0 20px 16px; }}
.fat-card {{ padding:16px; border-radius:14px; border:1px solid rgba(255,255,255,.07); background:rgba(255,255,255,.035); text-align:center; }}
.fat-card b {{ display:block; font-size:18px; margin-bottom:6px; }}
.trigger {{ display:inline-block; margin:5px 8px 5px 0; padding:7px 10px; border-radius:8px; background:rgba(245,158,11,.15); color:#ffd58a; font-size:12px; font-weight:800; }}
@media(max-width:760px) {{
  .wrap {{ padding:12px; }} .team-card,.grid2,.prob-grid,.records,.summary {{ grid-template-columns:1fr; padding:16px; }}
  .vs {{ display:none; }} .score {{ font-size:44px; }} .info-row {{ grid-template-columns:92px 1fr; }}
  .guide-list,.lambda-panel,.margin-grid,.ko-grid,.goal-bands,.fatigue-cards {{ grid-template-columns:1fr; }}
  .gsa-grid,.gsa-r32-grid {{ grid-template-columns:1fr; }}
  .strat-scores {{ grid-template-columns:1fr; }}
}}
.back-to-top {{ position:fixed; right:28px; top:50%; transform:translateY(-50%); width:44px; height:44px; border-radius:50%;
  background:rgba(59,130,246,.85); color:#fff; border:none; cursor:pointer; font-size:20px; line-height:44px;
  text-align:center; z-index:9999; opacity:0; pointer-events:none; transition:opacity .3s, transform .3s;
  box-shadow:0 4px 16px rgba(0,0,0,.35); backdrop-filter:blur(6px); }}
.back-to-top.show {{ opacity:1; pointer-events:auto; }}
.back-to-top:hover {{ background:rgba(59,130,246,1); transform:translateY(-50%) scale(1.08); }}
</style>
</head>
<body>
<div class="wrap">
  <div id="app"></div>
</div>
<button class="back-to-top" id="backTop" title="回到顶部">↑</button>
<script>
const DATA = {data_json};
const $ = s => document.querySelector(s);
const pct = (v, d=1) => ((v || 0) * 100).toFixed(d) + '%';
function zoneClass(z) {{ return z.includes('32') ? 'advance' : (z.includes('待定') ? 'pending' : 'risk'); }}
function esc(x) {{ return String(x ?? '—').replace(/[&<>"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c])); }}
function infoRows(t) {{
  const rankLabel = (t.rank_source || 'FIFA') + '排名';
  const rows = [
    [rankLabel, t.fifa_rank ? '#' + t.fifa_rank : '—'], ['人口', t.population], ['世界杯届数', t.wc_appearances],
    ['最佳成绩', t.best_achievement], ['阵型', t.formation], ['风格', t.style_detail],
    ['背景', t.background], ['首发阵容', t.starting_lineup], ['训练基地', t.training_base]
  ];
  return rows.map(r => `<div class="info-row"><span class="label">${{esc(r[0])}}</span><span class="value">${{esc(r[1])}}</span></div>`).join('');
}}
function recordBox(t) {{
  const r = t.current_record || {{}};
  const recent = (r.recent || []).map(x => `${{x.date}} vs ${{x.opponent_cn}} ${{x.score}}(${{x.result}})`).join(' · ') || '本届暂无已完赛记录';
  return `<div class="record-box">
    <div class="record-top"><b>${{t.flag}} ${{t.name_cn}} · ${{r.group || '小组'}}</b><span class="zone ${{zoneClass(r.zone || '')}}">${{r.zone || '待定区'}}</span></div>
    <div class="record-stats">
      <div><b>${{r.played || 0}}</b><span>赛</span></div><div><b>${{r.w || 0}}</b><span>胜</span></div>
      <div><b>${{r.d || 0}}</b><span>平</span></div><div><b>${{r.l || 0}}</b><span>负</span></div>
      <div><b>${{r.gf || 0}}/${{r.ga || 0}}</b><span>进/失</span></div>
    </div>
    <div class="recent">积分 ${{r.pts || 0}} · 排名 ${{r.rank || '—'}} · 近期：${{esc(recent)}}</div>
  </div>`;
}}
function renderTeamComparison() {{
  const h = DATA.teams.home, a = DATA.teams.away;
  return `<div class="card">
    <div class="title"><div><h2>球队对比卡</h2><p>当前项目数据优先，缺口用静态 team_profiles.json 补齐</p></div></div>
    <div class="team-card">
      <div class="side"><div class="hero-team"><div class="flag">${{h.flag}}</div><div class="name">${{h.name_cn}}</div><div class="score blue">${{(h.score/10).toFixed(1)}}</div><div class="score-label">综合评分</div></div>${{infoRows(h)}}</div>
      <div class="vs">VS</div>
      <div class="side"><div class="hero-team"><div class="flag">${{a.flag}}</div><div class="name">${{a.name_cn}}</div><div class="score red">${{(a.score/10).toFixed(1)}}</div><div class="score-label">综合评分</div></div>${{infoRows(a)}}</div>
    </div>
    <div class="records">${{recordBox(h)}}${{recordBox(a)}}</div>
  </div>`;
}}
function renderGroupStandings() {{
  const gs = DATA.group_standings || {{}}, rows = gs.rows || [];
  if (!rows.length) return '';
  const body = rows.map(r => {{
    const cls = r.highlight ? 'highlight' : '';
    const zone = zoneClass(r.zone || '');
    return `<tr class="${{cls}}"><td>${{r.rank || '—'}}</td><td class="team">${{r.flag}} ${{r.team_cn}}</td><td>${{r.played}}</td><td>${{r.w}}-${{r.d}}-${{r.l}}</td><td>${{r.gf}}/${{r.ga}}</td><td>${{r.gd>0?'+':''}}${{r.gd}}</td><td><b>${{r.pts}}</b></td><td>${{esc(r.form || '—')}}</td><td><span class="group-pill ${{zone}}">${{esc(r.zone || '待定')}}</span></td></tr>`;
  }}).join('');
  return `<div class="card group-standings"><h3>${{esc(gs.group_letter || gs.group || '小组')}}组小组赛战绩</h3><table class="group-table"><thead><tr><th>#</th><th>球队</th><th>赛</th><th>胜平负</th><th>进/失</th><th>净</th><th>分</th><th>走势</th><th>区域</th></tr></thead><tbody>${{body}}</tbody></table></div>`;
}}
function renderDimensions() {{
  const dims = DATA.dimensions, keys = Object.keys(dims.team_a || {{}});
  const bars = keys.map(k => {{
    const va = dims.team_a[k] || 5, vb = dims.team_b[k] || 5, total = va + vb || 1;
    const pa = Math.round(va / total * 100), pb = 100 - pa;
    return `<div class="bar-row"><div class="bar-head"><span>${{dims.labels[k] || k}} (${{dims.weights[k] || 0}}%)</span><span>${{va.toFixed(1)}} / ${{vb.toFixed(1)}}</span></div><div class="bar-track"><div class="bar-a" style="width:${{pa}}%">${{pa}}%</div><div class="bar-b" style="width:${{pb}}%">${{pb}}%</div></div></div>`;
  }}).join('');
  return `<div class="card"><div class="title"><div><h2>九维度能力对比</h2><p>雷达图 + 对抗条形图</p></div></div><div class="grid2"><div class="radar-wrap"><canvas id="radar" width="330" height="330"></canvas></div><div class="bars">${{bars}}</div></div></div>`;
}}
function matrixHtml() {{
  const la = DATA.prediction.lambda_a, lb = DATA.prediction.lambda_b;
  function poisson(k,l) {{ let r=Math.exp(-l); for(let i=1;i<=k;i++) r*=l/i; return r; }}
  let html = '<div class="matrix"><div></div>';
  for(let j=0;j<=7;j++) html += `<div class="axis">${{j}}</div>`;
  for(let i=0;i<=7;i++) {{
    html += `<div class="axis">${{i}}</div>`;
    for(let j=0;j<=7;j++) {{
      const p = poisson(i,la)*poisson(j,lb), inten = Math.min(p*22,1);
      const c = i>j ? `rgba(59,130,246,${{.15+inten*.6}})` : (i===j ? `rgba(245,158,11,${{.15+inten*.6}})` : `rgba(239,68,68,${{.15+inten*.6}})`);
      html += `<div class="cell" style="background:${{c}}" title="${{i}}-${{j}}">${{(p*100).toFixed(1)}}%</div>`;
    }}
  }}
  return html + '</div>';
}}
function renderStrategicAdjustment() {{
  const s = DATA.prediction?.strategic;
  if (!s || !s.applied) return '';
  const notesHtml = (s.notes || []).map(n => `<div class="strat-note">· ${{esc(n)}}</div>`).join('');
  const origScores = (s.original_top_scores || []).map(sc => `<div class="strat-score-item"><span class="ss">${{sc.score}}</span><span class="sp">${{pct(sc.probability)}}</span></div>`).join('');
  const adjScores = (s.adjusted_top_scores || []).map((sc,i) => `<div class="strat-score-item ${{i===0?'reco':''}}"><span class="ss">${{i===0?'⭐ ':''}}${{sc.score}}</span><span class="sp">${{pct(sc.probability)}}</span></div>`).join('');
  const scoresHtml = (origScores || adjScores) ? `<div class="strat-scores"><div class="strat-score-col"><div class="strat-score-title">原始推荐</div>${{origScores}}</div><div class="strat-score-col"><div class="strat-score-title">修正后推荐</div>${{adjScores}}</div></div>` : '';
  return `<div class="strat-panel"><div class="strat-header">🎯 战略修正 · λ ${{s.original_lambda}} : ${{s.original_mu}} → 修正后 ${{s.adjusted_lambda}} : ${{s.adjusted_mu}}</div><div class="strat-factors"><span class="strat-factor">主队 ×${{s.home_mult}}</span><span class="strat-factor away">客队 ×${{s.away_mult}}</span></div>${{scoresHtml}}<div class="strat-notes">${{notesHtml}}</div></div>`;
}}
function renderPrediction() {{
  const p = DATA.prediction, top = p.top_scorelines || [];
  const guides = top.map((s,i)=>`<div class="guide-item ${{i===0?'reco':''}}"><div>${{i===0?'⭐ 推荐':'参考'}}</div><div class="s">${{s.score}}</div><div class="p">${{pct(s.probability)}}</div></div>`).join('');
  return `<div class="card"><div class="title"><div><h2>胜平负 / 比分矩阵 / 指导比分</h2><p>Dixon-Coles 组合模型 · λ ${{p.lambda_a.toFixed(2)}} : ${{p.lambda_b.toFixed(2)}}</p></div></div><div class="prob-grid"><div class="donut"><canvas id="donut" width="260" height="260"></canvas><div class="donut-center"><b>${{top[0]?.score || '—'}}</b><br><span>最可能比分</span></div></div><div>${{matrixHtml()}}</div></div><div class="guide"><div class="guide-list">${{guides}}</div></div>${{renderStrategicAdjustment()}}${{renderLambdaPanel()}}</div>`;
}}
function factorRows(profile) {{
  const labels = {{attack_volume:'机会量',chance_quality:'机会质量',transition_attack:'转换',pressing:'逼抢',low_block:'低位',set_piece_attack:'定位球',defensive_resistance:'防守韧性',tempo:'节奏'}};
  const dims = profile?.dimensions || {{}};
  return Object.entries(labels).map(([k,label]) => {{
    const raw = Number(dims[k] || 0), v = Math.max(0, Math.min(1, raw));
    return `<div class="factor-row"><span>${{label}}</span><div class="factor-track"><div class="factor-fill" style="width:${{Math.round(v*100)}}%"></div></div><b>${{raw.toFixed(2)}}</b></div>`;
  }}).join('');
}}
function renderLambdaPanel() {{
  const p = DATA.prediction, sp = p.style_profiles || {{}}, m = p.win_margins || {{}};
  const homeName = DATA.match.home_cn, awayName = DATA.match.away_cn;
  return `<div class="lambda-panel">
    <div class="lambda-box"><h3>λ 风格 proxy · ${{homeName}}</h3>${{factorRows(sp.home)}}<p class="note">阵型 ${{esc(sp.home?.formation || '—')}} · ${{esc(sp.home?.lean || '未知')}}取向</p></div>
    <div class="lambda-box"><h3>λ 风格 proxy · ${{awayName}}</h3>${{factorRows(sp.away)}}<p class="note">阵型 ${{esc(sp.away?.formation || '—')}} · ${{esc(sp.away?.lean || '未知')}}取向</p></div>
    <div class="lambda-box"><h3>${{homeName}} 净胜阶梯</h3><div class="margin-grid"><div class="margin-pill"><b>${{pct(m.home_by_2_plus)}}</b><span>净胜2+</span></div><div class="margin-pill"><b>${{pct(m.home_by_3_plus)}}</b><span>净胜3+</span></div><div class="margin-pill"><b>${{pct(m.home_by_4_plus)}}</b><span>净胜4+</span></div></div></div>
    <div class="lambda-box"><h3>${{awayName}} 净胜阶梯</h3><div class="margin-grid"><div class="margin-pill"><b>${{pct(m.away_by_2_plus)}}</b><span>净胜2+</span></div><div class="margin-pill"><b>${{pct(m.away_by_3_plus)}}</b><span>净胜3+</span></div><div class="margin-pill"><b>${{pct(m.away_by_4_plus)}}</b><span>净胜4+</span></div></div></div>
  </div>`;
}}
function renderOdds() {{
  const rows = Object.entries(DATA.odds_validation || {{}}).map(([k,o]) => {{
    const dev = o.deviation;
    const cls = dev == null ? 'dev-neu' : (dev > 8 ? 'dev-pos' : (dev < -8 ? 'dev-neg' : 'dev-neu'));
    return `<tr><td>${{k}}</td><td>${{o.market_odds ? o.market_odds.toFixed(2) : '—'}}</td><td>${{pct(o.model_prob)}}</td><td>${{o.implied_prob == null ? '—' : pct(o.implied_prob)}}</td><td class="${{cls}}">${{dev == null ? o.label : (dev>0?'+':'') + dev.toFixed(1) + '%'}}</td></tr>`;
  }}).join('');
  return `<div class="card odds"><h2>赔率偏差颜色编码</h2><table><thead><tr><th>市场</th><th>赔率</th><th>模型概率</th><th>市场隐含</th><th>偏差</th></tr></thead><tbody>${{rows}}</tbody></table><p class="note">绿色=潜在价值，红色=市场高估，灰色=基本一致；赔率只做后验验证，不改写预测。</p></div>`;
}}
function renderKnockout() {{
  const k = DATA.knockout || {{}};
  if (!k.advance) return '';
  const hName = DATA.match.home_cn, aName = DATA.match.away_cn;
  const advH = k.advance.home || 0, advA = k.advance.away || 0;
  const t25 = k.totals_90?.lines?.['2.5'] || {{}};
  const t275 = k.totals_90?.lines?.['2.75'] || {{}};
  const bands = k.totals_90?.goal_distribution || {{}};
  const et = k.extra_time || {{}}, pen = k.penalties || {{}};
  const fat = k.fatigue || {{}};
  const fatBox = (team, d) => `<div class="fat-card"><b>${{team}}</b><div>休息${{d?.rest_days ?? '—'}}天 | 疲劳因子×1.00</div><div>ET λ=${{team===hName ? (et.lambda_home||0).toFixed(3) : (et.lambda_away||0).toFixed(3)}}</div></div>`;
  const evRows = (k.ev_board || []).map(r => {{
    const cls = r.recommendation === '推荐' ? 'reco' : (r.recommendation === '回避' ? 'avoid' : '');
    const tag = r.recommendation === '推荐' ? '<span class="tag-reco">推荐</span>' : (r.recommendation === '回避' ? '<span class="tag-avoid">回避</span>' : '');
    return `<tr class="${{cls}}"><td>${{esc(r.label)}} ${{tag}}</td><td>${{esc(r.probability_structure)}}</td><td>${{r.fair_odds || '—'}}</td><td>${{r.market_odds || '—'}}</td><td class="${{r.ev>=0?'dev-pos':'dev-neg'}}">${{r.ev>0?'+':''}}${{Number(r.ev||0).toFixed(3)}}</td></tr>`;
  }}).join('');
  const triggers = (k.condition_triggers || []).map(x => `<span class="trigger">${{esc(x)}}</span>`).join('');
  return `<div class="card"><div class="title"><div><h2>淘汰赛晋级模型</h2><p>90分钟 + 加时 + 点球 · 晋级概率完整公式分解</p></div></div>
    <div class="ko-hero"><div class="ko-bar"><div class="ko-home" style="width:${{Math.round(advH*100)}}%">${{hName}} ${{pct(advH)}}</div><div class="ko-away" style="width:${{Math.round(advA*100)}}%">${{aName}} ${{pct(advA)}}</div></div>
    <div class="ko-formula">${{esc(k.advance.formula_home)}}<br>${{esc(k.advance.formula_home_values)}}<br>⚠ 晋级盘含加时+点球；多数盘口仅计90分钟。</div></div>
    <div class="ko-grid">
      <div class="lambda-box"><h3>大小球分析（仅90分钟）</h3><div class="total-split"><div><div class="total-small">${{pct(t25.over)}}</div><span>大球(&gt;2.5)</span></div><b>VS</b><div><div class="total-big">${{pct(t25.under)}}</div><span>小球(≤2.5)</span></div></div>
        <div class="goal-bands">${{Object.entries(bands).map(([name,v])=>`<div class="ko-metric"><b>${{pct(v)}}</b><span>${{name}}</span></div>`).join('')}}</div>
        <p class="note">亚洲2.75：大球全赢${{pct(t275.over_full)}} / 半赢${{pct(t275.over_half_win)}}；小球全赢${{pct(t275.under_full)}} / 半赢${{pct(t275.under_half_win)}}。</p></div>
      <div class="lambda-box"><h3>加时赛 + 点球</h3><div class="ko-metric-grid"><div class="ko-metric"><b>${{pct(et.home)}}</b><span>${{hName}} ET胜</span></div><div class="ko-metric"><b>${{pct(et.draw)}}</b><span>进入点球</span></div><div class="ko-metric"><b>${{pct(et.away)}}</b><span>${{aName}} ET胜</span></div></div>
        <div class="penalty-bar"><div class="ko-home" style="width:${{Math.round((pen.home||.5)*100)}}%">${{hName}} ${{pct(pen.home)}}</div><div class="ko-away" style="width:${{Math.round((pen.away||.5)*100)}}%">${{aName}} ${{pct(pen.away)}}</div></div><p class="note">${{esc(pen.factors || '')}}</p></div>
    </div>
    <div class="fatigue-cards">${{fatBox(hName, fat.home)}}${{fatBox(aName, fat.away)}}</div>
    <div class="odds"><h2>投注EV排序（模型概率 vs 市场赔率）</h2><table class="ev-table"><thead><tr><th>下法</th><th>概率结构</th><th>公平赔率</th><th>市场赔率</th><th>EV</th></tr></thead><tbody>${{evRows}}</tbody></table><p class="note">市场赔率缺失时仅展示公平赔率，EV不作推荐依据。所有概率仅供模型分析，不构成下注建议。</p></div>
    <div class="guide"><h3>分析总结</h3><p class="note">${{esc(k.analysis_summary || '')}}</p><div>${{triggers}}</div></div>
  </div>`;
}}
function renderSummary() {{
  const s = DATA.summary || {{}}, risks = DATA.risks || [];
  const a = DATA.match_analysis || {{}};
  const analysis = a.text ? `<div class="field-analysis"><h3>分场分析</h3><p>${{esc(a.text)}}</p></div>` : '';
  return `<div class="card"><div class="title"><div><h2>分析总结与风险提示</h2><p>保留当前项目逐场详情核心解释</p></div></div><div class="summary"><div class="note">${{esc(s.text || '')}}${{analysis}}</div><div>${{risks.map(r=>`<div class="risk"><b>[${{r.level}}] ${{r.tag}}</b><br>${{esc(r.detail)}}</div>`).join('')}}</div></div></div>`;
}}
function renderChampion() {{
  const rows = (DATA.championship_odds || []).slice(0,10);
  const max = rows[0]?.champion || 1;
  return `<div class="card champ"><h2>夺冠概率排名</h2>${{rows.map((r,i)=>`<div class="champ-row"><div>${{i+1}}</div><div><b>${{r.flag}} ${{r.team_cn}}</b><div class="champ-bar"><div class="champ-fill" style="width:${{Math.max(2,r.champion/max*100)}}%"></div></div></div><div>${{pct(r.champion,1)}}</div></div>`).join('')}}</div>`;
}}
function renderGroupStrategicAnalysis() {{
  const gsa = DATA.group_strategic_analysis;
  if (!gsa || !gsa.available) return '';
  function sTable(rows, hl) {{
    if (!rows || !rows.length) return '<p class="note">暂无积分数据</p>';
    let h = '<table class="gsa-table"><thead><tr><th>#</th><th>队</th><th>赛</th><th>胜</th><th>平</th><th>负</th><th>进/失</th><th>净</th><th>分</th></tr></thead><tbody>';
    rows.forEach(r => {{
      const c = r.team === hl ? 'highlight' : '';
      h += `<tr class="${{c}}"><td>${{r.rank||'—'}}</td><td>${{r.flag}} ${{r.team_cn}}</td><td>${{r.played}}</td><td>${{r.w}}</td><td>${{r.d}}</td><td>${{r.l}}</td><td>${{r.gf}}/${{r.ga}}</td><td>${{r.gd>0?'+':''}}${{r.gd}}</td><td><b>${{r.pts}}</b></td></tr>`;
    }});
    return h + '</tbody></table>';
  }}
  function tBox(t) {{
    if (!t) return '';
    let h = `<div class="gsa-team-box">`;
    h += `<div class="gsa-team-head"><span class="flag">${{t.flag}}</span><b>${{t.team_cn}}</b><span class="gsa-group-tag">${{t.group_letter}}组</span></div>`;
    h += `<div class="gsa-probs">`;
    h += `<div class="gsa-prob-row"><span>出线</span><div class="gsa-prob-bar"><div class="gsa-fill" style="width:${{Math.round(t.sim_qualify*100)}}%;background:#10b981"></div></div><b>${{pct(t.sim_qualify)}}</b></div>`;
    h += `<div class="gsa-prob-row"><span>头名</span><div class="gsa-prob-bar"><div class="gsa-fill" style="width:${{Math.round(t.sim_first*100)}}%;background:#3b82f6"></div></div><b>${{pct(t.sim_first)}}</b></div>`;
    if (t.sim_third_advance > 0.01) {{
      h += `<div class="gsa-prob-row"><span>第三递补</span><div class="gsa-prob-bar"><div class="gsa-fill" style="width:${{Math.round(t.sim_third_advance*100)}}%;background:#f59e0b"></div></div><b>${{pct(t.sim_third_advance)}}</b></div>`;
    }}
    h += `</div>`;
    h += `<div class="gsa-section-title">小组积分榜</div>`;
    h += sTable(t.standings, t.team);
    h += `<div class="gsa-section-title">32强对位投影</div><div class="gsa-r32-grid">`;
    if (t.r32_first) {{
      const r = t.r32_first;
      h += `<div class="gsa-r32-item"><div class="gsa-r32-cond">若头名出线</div><div class="gsa-r32-match">第${{r.match_num}}场</div><div class="gsa-r32-opp">${{r.opponent_desc}}</div>`;
      if (r.opponent_team_cn && r.opponent_team_cn !== '待定') {{
        h += `<div class="gsa-r32-proj">${{r.opponent_flag}} ${{r.opponent_team_cn}} <span class="gsa-prob-tag">${{pct(r.opponent_prob)}}</span></div>`;
      }} else {{
        h += `<div class="gsa-r32-proj muted">待定</div>`;
      }}
      h += `</div>`;
    }}
    if (t.r32_second) {{
      const r = t.r32_second;
      h += `<div class="gsa-r32-item"><div class="gsa-r32-cond">若次名出线</div><div class="gsa-r32-match">第${{r.match_num}}场</div><div class="gsa-r32-opp">${{r.opponent_desc}}</div>`;
      if (r.opponent_team_cn && r.opponent_team_cn !== '待定') {{
        h += `<div class="gsa-r32-proj">${{r.opponent_flag}} ${{r.opponent_team_cn}} <span class="gsa-prob-tag">${{pct(r.opponent_prob)}}</span></div>`;
      }} else {{
        h += `<div class="gsa-r32-proj muted">待定</div>`;
      }}
      h += `</div>`;
    }}
    if (t.r32_third && t.r32_third.length > 0) {{
      t.r32_third.forEach(r => {{
        h += `<div class="gsa-r32-item" style="border-color:rgba(245,158,11,.3)"><div class="gsa-r32-cond">若第三递补</div><div class="gsa-r32-match">第${{r.match_num}}场</div><div class="gsa-r32-opp">${{r.opponent_desc}}</div>`;
        if (r.opponent_team_cn && r.opponent_team_cn !== '待定') {{
          h += `<div class="gsa-r32-proj">${{r.opponent_flag}} ${{r.opponent_team_cn}} <span class="gsa-prob-tag">${{pct(r.opponent_prob)}}</span></div>`;
        }} else {{
          h += `<div class="gsa-r32-proj muted">待定</div>`;
        }}
        h += `</div>`;
      }});
    }}
    h += `</div></div>`;
    return h;
  }}
  let nHtml = '';
  if (gsa.notes && gsa.notes.length) {{
    nHtml = '<div class="gsa-notes">' + gsa.notes.map(n =>
      `<div class="gsa-note"><span class="gsa-note-cat">${{n.category}}</span><span class="gsa-note-text">${{esc(n.text)}}</span></div>`
    ).join('') + '</div>';
  }}
  return `<div class="card"><div class="title"><div><h2>小组赛深度战略分析</h2><p>出线形势 · 32强对位 · 第三名递补 · 战略考量 · 跨组联动 · 进球动机</p></div></div><div class="gsa-grid">${{tBox(gsa.home)}}${{tBox(gsa.away)}}</div>${{nHtml}}</div>`;
}}
function drawRadar() {{
  const c = $('#radar'); if(!c) return; const ctx=c.getContext('2d'), W=c.width,H=c.height,cx=W/2,cy=H/2,R=120;
  const dims=DATA.dimensions, keys=Object.keys(dims.team_a||{{}}), labels=keys.map(k=>dims.labels[k]||k);
  ctx.clearRect(0,0,W,H); ctx.strokeStyle='rgba(255,255,255,.10)'; ctx.fillStyle='rgba(148,163,184,.9)'; ctx.font='11px sans-serif';
  for(let ring=1;ring<=5;ring++) {{ ctx.beginPath(); for(let i=0;i<keys.length;i++) {{ const a=-Math.PI/2+i*2*Math.PI/keys.length, r=R*ring/5; const x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r; i?ctx.lineTo(x,y):ctx.moveTo(x,y); }} ctx.closePath(); ctx.stroke(); }}
  labels.forEach((l,i)=>{{ const a=-Math.PI/2+i*2*Math.PI/keys.length; ctx.fillText(l,cx+Math.cos(a)*(R+24)-24,cy+Math.sin(a)*(R+24)); }});
  function poly(vals,color,fill) {{ ctx.beginPath(); keys.forEach((k,i)=>{{ const a=-Math.PI/2+i*2*Math.PI/keys.length,r=R*(vals[k]||5)/10,x=cx+Math.cos(a)*r,y=cy+Math.sin(a)*r; i?ctx.lineTo(x,y):ctx.moveTo(x,y); }}); ctx.closePath(); ctx.fillStyle=fill; ctx.strokeStyle=color; ctx.lineWidth=2; ctx.fill(); ctx.stroke(); }}
  poly(dims.team_a,'#3b82f6','rgba(59,130,246,.18)'); poly(dims.team_b,'#ef4444','rgba(239,68,68,.16)');
}}
function drawDonut() {{
  const c=$('#donut'); if(!c) return; const ctx=c.getContext('2d'), p=DATA.prediction, vals=[p.team_a_win_prob,p.draw_prob,p.team_b_win_prob], cols=['#3b82f6','#f59e0b','#ef4444'];
  let start=-Math.PI/2; vals.forEach((v,i)=>{{ ctx.beginPath(); ctx.moveTo(130,130); ctx.arc(130,130,112,start,start+v*Math.PI*2); ctx.closePath(); ctx.fillStyle=cols[i]; ctx.fill(); start+=v*Math.PI*2; }}); ctx.globalCompositeOperation='destination-out'; ctx.beginPath(); ctx.arc(130,130,72,0,Math.PI*2); ctx.fill(); ctx.globalCompositeOperation='source-over';
}}
$('#app').innerHTML = renderTeamComparison()+renderGroupStandings()+renderDimensions()+renderPrediction()+renderGroupStrategicAnalysis()+renderKnockout()+renderOdds()+renderSummary()+renderChampion();
drawRadar(); drawDonut();
(function() {{
  var btn = document.getElementById('backTop');
  if (!btn) return;

  // 点击按钮：同时滚动 iframe 和父页面回顶部
  btn.addEventListener('click', function() {{
    window.scrollTo({{ top: 0, behavior: 'smooth' }});
    try {{ window.parent.scrollTo({{ top: 0, behavior: 'smooth' }}); }} catch(e) {{}}
  }});

  // 监听滚动：iframe 内滚动 + 父页面滚动
  function checkScroll() {{
    var iframeY = window.scrollY || window.pageYOffset || 0;
    var parentY = 0;
    try {{ parentY = window.parent.scrollY || window.parent.pageYOffset || 0; }} catch(e) {{}}
    if (iframeY > 300 || parentY > 300) {{
      btn.classList.add('show');
    }} else {{
      btn.classList.remove('show');
    }}
  }}

  window.addEventListener('scroll', checkScroll);
  try {{ window.parent.addEventListener('scroll', checkScroll); }} catch(e) {{}}
  checkScroll();
}})();
</script>
</body>
</html>
"""
    components.html(html, height=3400, scrolling=True)


def require_login() -> dict:
    if not LOGIN_ENABLED:
        return {"username": "guest", "role": "user"}  # 登录已关闭：直接放行为访客
    if st.session_state.get("auth_user"):
        return {"username": st.session_state["auth_user"], "role": st.session_state.get("auth_role", "user")}
    st.markdown(
        """
        <div class="wc-login">
            <h1>2026 世界杯预测</h1>
            <p>登录后进入模型预测、价值分析与晋级之路工作台。</p>
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


def require_view_access() -> None:
    """站点访问口令墙：设了 ACCESS_PASSWORD 时，普通网址访问需先输入口令才能查看；
    带正确 ?owner=<OWNER_KEY> 的管理员沿用老方式直接放行（免口令）。留空=不限制。

    注意：仅当 OWNER_KEY 已设置且参数匹配才免口令；OWNER_KEY 为空时不放行任何人，
    避免“设了访问口令却人人免验”。"""
    pwd = (settings.access_password or "").strip()
    if not pwd:
        return  # 未配置访问口令：不限制（本机/单人使用时全功能）
    if settings.owner_key and is_owner():
        return  # 管理员带正确 ?owner= 参数：老方式不变，免口令
    if st.session_state.get("_view_ok"):
        return
    st.markdown(
        """
        <div class="wc-login">
            <h1>2026 世界杯预测</h1>
            <p>本看板需访问口令，请输入后查看。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("view_gate_form"):
        supplied = st.text_input("访问口令", type="password")
        submitted = st.form_submit_button("进入")
    if submitted:
        if hmac.compare_digest(supplied.strip(), pwd):
            st.session_state["_view_ok"] = True
            st.rerun()
        else:
            st.error("口令错误。")
    st.stop()


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


@st.cache_data(ttl=300, show_spinner=False)
def load_live_fixture_state() -> dict:
    try:
        fixtures = fetch_fixture_snapshot(timeout=8)
        return {
            "fixtures": fixtures,
            "fetched_at": fixtures[0].get("fetched_at") if fixtures else None,
            "error": None,
        }
    except Exception as exc:
        return {"fixtures": [], "fetched_at": None, "error": str(exc)}


@st.cache_data(ttl=300)
def load_fixtures():
    init_db()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT match_number, round_number, date_utc, home_src, away_src, home_team, away_team, "
            "group_name, location, predictable, home_score, away_score, regulation_home_score, "
            "regulation_away_score, final_home_score, final_away_score, penalty_home_score, "
            "penalty_away_score, result_status, winner_team, result_source, source_event_id, "
            "result_fetched_at, event_flags, match_stats_json "
            "FROM fixtures ORDER BY date_utc"
        ).fetchall()
    fixtures = merge_fixture_snapshots(
        [dict(r) for r in rows], load_live_fixture_state()["fixtures"])
    fixtures = [f for f in fixtures if f.get("predictable") == 1]
    return apply_results_overlay(fixtures)


@st.cache_data(ttl=600, show_spinner=False)
def load_club_competition(competition: str) -> dict:
    from wc2026.data.sources.club_competitions import fetch_competition_events

    return fetch_competition_events(competition, timeout=8)


def _club_event_time(value: str | None) -> tuple[str, str]:
    if not value:
        return "日期待定", "时间待定"
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return "日期待定", "时间待定"
    local = parsed.tz_convert("Asia/Shanghai")
    return f"{local.month:02d}月{local.day:02d}日", local.strftime("%H:%M")


def _club_stage_label(stage: str) -> str:
    labels = {
        "Regular Season": "联赛",
        "First Round": "资格赛第一轮",
        "Second Round": "资格赛第二轮",
        "Third Round": "资格赛第三轮",
        "Playoffs": "附加赛",
        "League Phase": "联赛阶段",
        "Round Of 16": "1/8 决赛",
        "Quarterfinals": "1/4 决赛",
        "Semifinals": "半决赛",
        "Final": "决赛",
    }
    if stage.endswith("Brasileiro Serie A"):
        return "巴甲联赛"
    return labels.get(stage, stage or "赛事")


def render_club_competition(competition: str) -> None:
    from wc2026.data.club_names import club_zh

    config = {
        "巴甲": {
            "key": "brasileirao",
            "title": "巴西足球甲级联赛",
            "subtitle": "2026 Brasileirão Série A · 近期赛程与实时赛果",
            "kicker": "BRASILEIRÃO",
        },
        "欧冠": {
            "key": "champions_league",
            "title": "欧洲冠军联赛",
            "subtitle": "UEFA Champions League · 主赛与资格赛统一赛程",
            "kicker": "ROAD TO THE FINAL",
        },
    }[competition]
    render_hero(config["title"], config["subtitle"], config["kicker"])

    try:
        data = load_club_competition(config["key"])
    except Exception as exc:
        st.error(f"赛事数据暂时无法加载：{exc}")
        if st.button("重新加载", key=f"reload:{config['key']}"):
            load_club_competition.clear()
            st.rerun()
        return

    events = data["events"]
    completed = sum(row["completed"] for row in events)
    live = sum(row["state"] == "in" for row in events)
    upcoming = sum(row["state"] == "pre" for row in events)
    other = sum(row["state"] == "other" for row in events)
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("窗口内比赛", len(events))
    m2.metric("未开赛", upcoming)
    m3.metric("进行中", live)
    m4.metric("已结束", completed)
    m5.metric("延期 / 取消", other)

    seasons = " / ".join(data["seasons"]) or "当前赛季"
    st.caption(f"{seasons} · 北京时间 · ESPN 公开赛程 · 查询窗口 {data['date_range']}")
    if data["errors"]:
        st.warning("部分赛事源暂不可用，当前展示其余可用赛程。")
    if not events:
        st.info("当前日期窗口内暂无比赛。")
        return

    filter_col, search_col = st.columns([1.2, 2])
    state_label = filter_col.selectbox(
        "赛况", ["全部", "未开赛", "进行中", "已结束", "延期 / 取消"],
        key=f"club_state:{config['key']}",
    )
    query = search_col.text_input(
        "搜索球队", placeholder="输入球队中文名或英文名",
        key=f"club_search:{config['key']}",
    ).strip().lower()
    state_map = {
        "未开赛": "pre", "进行中": "in", "已结束": "post", "延期 / 取消": "other",
    }

    def keep(row: dict) -> bool:
        if state_label != "全部" and row["state"] != state_map[state_label]:
            return False
        names = (
            row["home"]["name"], row["away"]["name"],
            club_zh(row["home"]["name"]), club_zh(row["away"]["name"]),
        )
        return not query or any(query in name.lower() for name in names)

    shown = [row for row in events if keep(row)]
    shown.sort(
        key=lambda row: (
            {"in": 0, "pre": 1, "post": 2}.get(row["state"], 3),
            row["date_utc"] or "",
        )
    )
    st.caption(f"显示 {len(shown)} 场")
    for row in shown:
        date_label, time_label = _club_event_time(row["date_utc"])
        status = row["status"] or {
            "pre": "未开赛", "in": "进行中", "post": "已结束", "other": "延期 / 取消",
        }.get(row["state"], "状态待定")
        with st.container(border=True):
            meta, matchup, score = st.columns([1.2, 4, 1])
            with meta:
                st.caption(_club_stage_label(row["stage"]))
                st.caption(f"{date_label} · {time_label} · {status}")
            with matchup:
                home_logo, home_name = st.columns([0.35, 4])
                if row["home"]["logo"]:
                    home_logo.image(row["home"]["logo"], width=28)
                home_name.markdown(f"**{club_zh(row['home']['name'])}**")
                away_logo, away_name = st.columns([0.35, 4])
                if row["away"]["logo"]:
                    away_logo.image(row["away"]["logo"], width=28)
                away_name.markdown(f"**{club_zh(row['away']['name'])}**")
                place = " · ".join(part for part in (row["venue"], row["city"]) if part)
                if place:
                    st.caption(place)
            with score:
                if row["state"] in {"in", "post"}:
                    st.markdown(
                        f"<div style='font-size:28px;font-weight:900;text-align:center;'>"
                        f"{row['home']['score'] or '—'}<br>{row['away']['score'] or '—'}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("VS")


def _get_wc_teams(model, fixtures):
    """从 fixtures 中提取世界杯参赛队伍（排除淘汰赛占位符如 1A、2B 等）。"""
    wc_set = set()
    for f in fixtures:
        for key in ("home_team", "away_team"):
            t = f.get(key, "")
            if t and t in model.teams:
                wc_set.add(t)
    return sorted(wc_set, key=zh)


@st.cache_data(ttl=300)
def load_knockout_fixtures():
    """加载全部淘汰赛赛程（round_number≥4），含 home_src/away_src slot 码。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT match_number, round_number, date_utc, home_src, away_src, "
            "home_team, away_team, location, home_score, away_score "
            "FROM fixtures WHERE round_number >= 4 ORDER BY match_number"
        ).fetchall()
    fixtures = merge_fixture_snapshots(
        [dict(r) for r in rows], load_live_fixture_state()["fixtures"])
    return [f for f in fixtures if f.get("round_number", 0) >= 4]


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


def render_bracket(model) -> None:
    """晋级之路：淘汰赛对阵树（R32→R16→QF→SF→决赛+三四名）。"""
    render_hero("晋级之路", "2026 世界杯淘汰赛完整对阵树", "KNOCKOUT BRACKET")

    ko = load_knockout_fixtures()
    if not ko:
        st.warning("暂无淘汰赛赛程数据，请先刷新赛程。")
        return

    fmap = {f["match_number"]: f for f in ko}

    # --- 小组模拟结果（用于 slot 投影）---
    res: dict = {}
    try:
        from wc2026.analysis import groups as groups_mod
        gd = groups_mod.load_group_data(model)
        if gd:
            sig = groups_mod.played_signature(gd)
            key = f"bk_groupsim:{hash(sig)}"
            if key not in st.session_state:
                st.session_state[key] = groups_mod.simulate_groups(model, gd, n_sims=2000)
            res = st.session_state[key]
    except Exception:
        pass

    def _slot_proj(slot: str) -> str:
        g = slot[1] if len(slot) == 2 and slot[0] in "12" else None
        if slot.startswith("3"):
            return "/".join(list(slot[1:])) + "组第三"
        rws = res.get(f"Group {g}", [])
        if not rws:
            return slot
        if slot.startswith("1"):
            return zh(max(rws, key=lambda r: r["first"])["team"])
        return zh(max(rws, key=lambda r: r["top2"] - r["first"])["team"])

    from wc2026.data.flags import flag_emoji
    from wc2026.analysis import schedule as sch

    def _team_label(f: dict, side: str) -> tuple[str, str]:
        src = (f.get(f"{side}_src") or "").strip()
        team = (f.get(f"{side}_team") or "").strip()
        if team in model.teams:
            return flag_emoji(team), zh(team)
        if src and src[0] in "123" and len(src) >= 2:
            return "", _slot_proj(src)
        return "", "待定"

    # --- 坐标参数 ---
    BW, BH = 160, 64
    R32_Y = [50 + i * 100 for i in range(8)]
    R16_Y = [(R32_Y[i] + R32_Y[i + 1]) / 2 for i in range(0, 8, 2)]
    QF_Y = [(R16_Y[i] + R16_Y[i + 1]) / 2 for i in range(0, 4, 2)]
    SF_Y = (QF_Y[0] + QF_Y[1]) / 2

    CW = 178  # column width (left-edge to left-edge)
    XL = {"r32": 0, "r16": CW, "qf": CW * 2, "sf": CW * 3}
    CGAP = 22  # extra gap between SF and center
    XC = XL["sf"] + BW + CGAP
    XR = {"sf": XC + BW + CGAP, "qf": XC + BW + CGAP + CW,
          "r16": XC + BW + CGAP + CW * 2, "r32": XC + BW + CGAP + CW * 3}

    final_cy = SF_Y - 55
    third_cy = SF_Y + 55

    def _box(mn: int, x: float, cy: float) -> str:
        f = fmap.get(mn)
        if not f:
            return ""
        bj = sch.beijing(f.get("date_utc"))
        hf, hn = _team_label(f, "home")
        af, an = _team_label(f, "away")
        hs, as_ = f.get("home_score"), f.get("away_score")
        if hs is not None and as_ is not None:
            hn, an = f"{hn} <b>{hs}</b>", f"{an} <b>{as_}</b>"
        return (
            f'<div class="mb" style="left:{x}px;top:{cy - BH / 2}px;">'
            f'<div class="mb-h">{bj["date"]} {bj["time"]}</div>'
            f'<div class="mb-b"><div class="mb-t">{hf} {hn}</div>'
            f'<div class="mb-t">{af} {an}</div></div></div>'
        )

    def _mobile_match(mn: int, label: str) -> str:
        f = fmap.get(mn)
        if not f:
            return ""
        bj = sch.beijing(f.get("date_utc"))
        hf, hn = _team_label(f, "home")
        af, an = _team_label(f, "away")
        hs, as_ = f.get("home_score"), f.get("away_score")
        score = f"{int(hs)} : {int(as_)}" if hs is not None and as_ is not None else "vs"
        return (
            '<div class="bm-card">'
            f'<div class="bm-meta">{label} · M{mn} · {bj["date"]} {bj["time"]}</div>'
            f'<div class="bm-row"><span>{hf} {hn}</span><b>{score}</b><span>{af} {an}</span></div>'
            f'<div class="bm-loc">{f.get("location", "")}</div>'
            '</div>'
        )

    boxes = []
    # 左半区
    for i, mn in enumerate(range(73, 81)):
        boxes.append(_box(mn, XL["r32"], R32_Y[i]))
    for i, mn in enumerate(range(89, 93)):
        boxes.append(_box(mn, XL["r16"], R16_Y[i]))
    for i, mn in enumerate(range(97, 99)):
        boxes.append(_box(mn, XL["qf"], QF_Y[i]))
    boxes.append(_box(101, XL["sf"], SF_Y))
    # 右半区
    for i, mn in enumerate(range(81, 89)):
        boxes.append(_box(mn, XR["r32"], R32_Y[i]))
    for i, mn in enumerate(range(93, 97)):
        boxes.append(_box(mn, XR["r16"], R16_Y[i]))
    for i, mn in enumerate(range(99, 101)):
        boxes.append(_box(mn, XR["qf"], QF_Y[i]))
    boxes.append(_box(102, XR["sf"], SF_Y))
    # 决赛 + 三四名
    boxes.append(_box(103, XC, final_cy))
    boxes.append(_box(104, XC, third_cy))

    # --- 轮次标签 ---
    rl_labels = [
        (XL["r32"], "32强"), (XL["r16"], "16强"), (XL["qf"], "八强"), (XL["sf"], "半决赛"),
        (XC, "决赛"),
        (XR["sf"], "半决赛"), (XR["qf"], "八强"), (XR["r16"], "16强"), (XR["r32"], "32强"),
    ]
    rl_html = "\n".join(
        f'<div class="rl" style="left:{x}px;">{label}</div>' for x, label in rl_labels
    )

    # --- SVG 连线 ---
    def _conn(x1, y1, y2, x2, ym):
        mx = (x1 + x2) / 2
        return (f'M {x1},{y1} L {mx},{y1} L {mx},{y2} L {x1},{y2}'
                f' M {mx},{ym} L {x2},{ym}')

    paths = []
    for i in range(4):
        paths.append(_conn(XL["r32"] + BW, R32_Y[i * 2], R32_Y[i * 2 + 1], XL["r16"], R16_Y[i]))
    for i in range(2):
        paths.append(_conn(XL["r16"] + BW, R16_Y[i * 2], R16_Y[i * 2 + 1], XL["qf"], QF_Y[i]))
    paths.append(_conn(XL["qf"] + BW, QF_Y[0], QF_Y[1], XL["sf"], SF_Y))
    for i in range(4):
        paths.append(_conn(XR["r32"], R32_Y[i * 2], R32_Y[i * 2 + 1], XR["r16"] + BW, R16_Y[i]))
    for i in range(2):
        paths.append(_conn(XR["r16"], R16_Y[i * 2], R16_Y[i * 2 + 1], XR["qf"] + BW, QF_Y[i]))
    paths.append(_conn(XR["qf"], QF_Y[0], QF_Y[1], XR["sf"] + BW, SF_Y))
    ml = (XL["sf"] + BW + XC) / 2
    paths.append(f'M {XL["sf"] + BW},{SF_Y} L {ml},{SF_Y} L {ml},{final_cy} L {XC},{final_cy}')
    mr = (XR["sf"] + XC + BW) / 2
    paths.append(f'M {XR["sf"]},{SF_Y} L {mr},{SF_Y} L {mr},{final_cy} L {XC + BW},{final_cy}')

    svg = "\n".join(f'<path d="{p}" stroke="rgba(255,255,255,0.35)" stroke-width="2" fill="none"/>' for p in paths)
    boxes_html = "\n".join(boxes)
    total_w = XR["r32"] + BW + 20
    total_h = R32_Y[-1] + BH / 2 + 20
    mobile_sections = []
    for label, mns in [
        ("32强", range(73, 89)),
        ("16强", range(89, 97)),
        ("八强", range(97, 101)),
        ("半决赛", range(101, 103)),
        ("决赛 / 三四名", range(103, 105)),
    ]:
        mobile_sections.append(
            f'<section class="bm-sec"><h3>{label}</h3>'
            + "".join(_mobile_match(mn, label) for mn in mns)
            + '</section>'
        )
    mobile_html = "\n".join(mobile_sections)

    css = """<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:transparent}
.bw{background:linear-gradient(135deg,#0a1628 0%,#0f2548 30%,#1a3a6e 60%,#2563eb 100%);border-radius:14px;padding:18px;overflow:hidden}
.bt{text-align:center;font-size:22px;font-weight:800;color:#fbbf24;background:linear-gradient(90deg,#1a1a1a,#333 50%,#1a1a1a);padding:10px 0;border-radius:8px;margin-bottom:14px;border:1px solid #fbbf24;letter-spacing:6px}
.ba{position:relative;margin:0 auto}
.ba svg{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none}
.rl{position:absolute;top:2px;text-align:center;width:160px;font-size:13px;font-weight:700;color:#93c5fd;text-shadow:0 1px 4px rgba(0,0,0,0.6)}
.mb{position:absolute;width:160px;height:64px;border-radius:5px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.35);font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;transition:box-shadow .15s}
.mb:hover{box-shadow:0 4px 14px rgba(251,191,36,0.4)}
.mb-h{background:#dc2626;color:#fff;font-size:10px;font-weight:600;text-align:center;padding:2px 0;line-height:14px}
.mb-b{background:#fff;padding:1px 0}
.mb-t{color:#1a1a1a;font-size:11px;padding:2px 7px;line-height:15px;white-space:normal;word-break:break-word;overflow:hidden}
.cl{position:absolute;text-align:center;width:160px;font-size:13px;font-weight:700;color:#fbbf24}
.bm{display:none}
.bm-sec{display:grid;gap:8px}
.bm-sec h3{font-size:15px;color:#fbbf24;margin:2px 0 0}
.bm-card{border:1px solid rgba(255,255,255,.14);border-radius:8px;background:rgba(255,255,255,.96);padding:9px 10px;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
.bm-meta{font-size:11px;color:#64748b;font-weight:700;margin-bottom:6px}
.bm-row{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);gap:8px;align-items:center;color:#111827;font-size:13px;font-weight:800}
.bm-row span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bm-row b{color:#dc2626}
.bm-loc{margin-top:5px;color:#64748b;font-size:11px}
@media(max-width:700px){
  .bw{padding:12px}
  .bt{font-size:18px;letter-spacing:2px;margin-bottom:10px}
  .ba{display:none}
  .bm{display:grid;gap:12px}
}
</style>
<script>
function fitBracket(){
  var a=document.querySelector('.ba'),w=document.querySelector('.bw');
  if(!a||!w)return;
  var aw=w.clientWidth-36,ow=a.offsetWidth,oh=a.offsetHeight;
  if(ow>aw){var s=aw/ow;a.style.transform='scale('+s+')';a.style.transformOrigin='top left';a.style.marginBottom='-'+Math.round(oh-oh*s)+'px';}
  else{a.style.transform='none';a.style.marginBottom='0';}
}
window.addEventListener('load',fitBracket);
window.addEventListener('resize',fitBracket);
</script>"""

    html = f"""{css}
<div class="bw">
  <div class="bt">晋 级 之 路</div>
  <div class="ba" style="width:{total_w}px;height:{total_h}px;">
    <svg viewBox="0 0 {total_w} {total_h}">{svg}</svg>
    {rl_html}
    {boxes_html}
    <div class="cl" style="left:{XC}px;top:{final_cy - BH / 2 - 22}px;">决赛</div>
    <div class="cl" style="left:{XC}px;top:{third_cy - BH / 2 - 22}px;">三四名决赛</div>
  </div>
  <div class="bm">{mobile_html}</div>
</div>"""

    components.html(html, height=int(total_h) + 140, scrolling=True)
    st.caption("对阵 slot：1A=A组头名、2B=B组次名、3XXXX=列出小组中最佳第三。"
               "投影球队来自当前小组模拟的最可能占位，随赛果变化。R16 之后由 32 强结果决定。")


def load_news(home, away):
    return news_mod.fetch_news_report([home, away], limit=16, timeout=10)


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
    cols = ["#", "球队", "赛", "胜", "平", "负", "进", "失", "净", "分", "区域"]
    thead = "<tr>" + "".join(
        f'<th style="padding:2px 4px;text-align:center;color:var(--wc-muted);font-weight:600;">{c}</th>'
        for c in cols) + "</tr>"
    body = ""
    for r in rows:
        bar = "#16a34a" if r["rank"] <= 2 else ("#d97706" if r["rank"] == 3 else "transparent")
        bg = "rgba(22,163,74,.20)" if r["rank"] <= 2 else (
            "rgba(217,119,6,.18)" if r["rank"] == 3 else "rgba(239,68,68,.07)")
        zone = "晋级32强区" if r["rank"] <= 2 else ("晋级待定区" if r["rank"] == 3 else "淘汰风险区")
        s = state.get(r["team"], "alive")
        tag = ("" if s == "alive"
               else f'<span style="font-size:10px;color:var(--wc-muted);margin-left:4px;">{STATUS_LABEL[s]}</span>')
        tds = [f'<td style="text-align:center;border-left:3px solid {bar};padding:4px 4px;">{r["rank"]}</td>',
               f'<td style="padding:2px 4px;white-space:nowrap;">{zh(r["team"])}{tag}</td>']
        tds += [f'<td style="text-align:center;padding:2px 4px;">{r[k]}</td>'
                for k in ("played", "w", "d", "l", "gf", "ga")]
        tds.append(f'<td style="text-align:center;padding:2px 4px;">{r["gd"]:+d}</td>')
        tds.append(f'<td style="text-align:center;padding:2px 4px;font-weight:700;">{r["pts"]}</td>')
        tds.append(f'<td style="text-align:right;padding:2px 4px;color:{bar};font-size:11px;font-weight:700;">{zone}</td>')
        body += f'<tr style="background:{bg};">' + "".join(tds) + "</tr>"
    return (f'<div class="wc-group-card">{head}'
            f'<table style="width:100%;border-collapse:collapse;font-size:12px;">'
            f'<thead>{thead}</thead><tbody>{body}</tbody></table></div>')


def _adjustments_expander() -> None:
    """展示当前赛中实力修正明细(各队 δ + 依据)，可回滚说明。"""
    from wc2026.analysis.adjustments import adjustment_artifact_status, load_adjustments
    adj = load_adjustments()
    artifact = adjustment_artifact_status()
    with st.expander(f"🔧 赛中实力修正明细（{len(adj)} 支球队）", expanded=False):
        if not adj:
            if artifact["state"] == "unversioned":
                st.warning(artifact["reason"])
            else:
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


_STAGE_LABELS = {4: "32进16", 5: "16进8", 6: "8进4", 7: "半决赛", 8: "决赛"}


def _detect_current_stage(ko_fixtures):
    """根据淘汰赛完赛情况检测当前阶段。
    返回 (label, round_number) 如 ("32进16", 4)。淘汰赛尚未开始返回 None。"""
    if not ko_fixtures:
        return None
    rounds_unplayed, rounds_played = set(), set()
    for f in ko_fixtures:
        rn = f["round_number"]
        if f.get("home_score") is not None:
            rounds_played.add(rn)
        else:
            rounds_unplayed.add(rn)
    current = min(rounds_unplayed) if rounds_unplayed else (max(rounds_played) if rounds_played else None)
    if current is None:
        return None
    return _STAGE_LABELS.get(current, f"第{current}轮"), current


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
    return f'<div class="wc-group-card">{head}{body}</div>'


def render_group_stage(model) -> None:
    from wc2026.analysis import groups as groups_mod
    from wc2026.analysis import motivation as motiv_mod
    gd = groups_mod.load_group_data(model)
    if not gd:
        section_title("小组出线概率")
        st.warning("暂无可用的小组赛程数据（需先刷新 2026 赛程）。")
        return

    # 淘汰赛阶段提示
    _ko_stg = _detect_current_stage(load_knockout_fixtures())
    if _ko_stg:
        st.info(f"小组赛已全部结束，以下为最终积分榜与出线结果。淘汰赛详情请查看「淘汰赛」页面。")

    section_title("小组积分榜")
    st.caption("基于已完赛比分的真实积分(积分>净胜球>进球>相互战绩)；"
               "绿条=前二出线区，黄条=小组第三(争最佳第三递补)。末轮自动标注战意。")
    _adjustments_expander()
    standings = groups_mod.compute_standings(gd)
    states = motiv_mod.derive_group_states(gd)
    standings_html = "".join(
        _standings_table_html(g, standings[g], states.get(g, {}))
        for g in _sorted_groups(standings)
    )
    st.markdown(f'<div class="wc-group-grid">{standings_html}</div>', unsafe_allow_html=True)

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
    groups_html = "".join(_group_card_html(g, res[g]) for g in _sorted_groups(res))
    st.markdown(f'<div class="wc-group-grid">{groups_html}</div>', unsafe_allow_html=True)
    st.caption("⚽ 小组出线概率会随每轮赛果快速变化；末轮尤其注意战意差异：已出线可能轮换、已淘汰战意下降、"
               "积分相近可能更保守。排序近似 积分>净胜球>进球数，未完全实现相互战绩等次级规则；"
               "FIFA 官方排名用于球队信息展示，不直接改写小组赛蒙特卡洛概率。")

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
    slot_cards = []
    for mn, (hs, as_) in enumerate(R32_SLOTS, start=73):
        half_label = "上半区" if mn < 81 else "下半区"
        slot_cards.append(
            f'<div class="wc-ko-card">'
            f'<span class="wc-ko-meta">{half_label} · M{mn} · {hs} vs {as_}</span><br>'
            f'<b>{_slot_proj(hs)}</b> <span style="color:var(--wc-muted);">vs</span> <b>{_slot_proj(as_)}</b>'
            f'</div>'
        )
    st.markdown(f'<div class="wc-ko-grid">{"".join(slot_cards)}</div>', unsafe_allow_html=True)
    st.caption("对阵 slot 来自官方赛程（1A=A 组头名、2B=B 组次名、3XXXX=列出小组中的最佳第三）；"
               "投影球队为当前小组模拟的最可能占位，随赛果变化。R16 之后由 32 强结果决定，晋级概率见上方夺冠表。")


def render_knockout_stage(model) -> None:
    """淘汰赛：实时对阵卡片 + 晋级概率 + 焦点分析。"""
    render_hero("淘汰赛", "2026 世界杯淘汰赛实时对阵与晋级分析", "KNOCKOUT STAGE")
    ko = load_knockout_fixtures()
    if not ko:
        st.warning("暂无淘汰赛赛程数据，请先刷新赛程。")
        return

    from wc2026.analysis import groups as _grp, tournament as _tour
    from wc2026.data.flags import flag_emoji as _flag
    from wc2026.analysis import ranking as _rk
    from wc2026.analysis import schedule as _sch

    stage_info = _detect_current_stage(ko)
    current_round = stage_info[1] if stage_info else 4
    current_label = stage_info[0] if stage_info else "32进16"

    # 阶段选择器
    available_rounds = sorted({f["round_number"] for f in ko})
    round_options = [(r, _STAGE_LABELS.get(r, f"第{r}轮")) for r in available_rounds]
    round_labels = [lbl for _, lbl in round_options]
    default_idx = round_options.index((current_round, current_label)) if (current_round, current_label) in round_options else 0
    sel_label = st.segmented_control(
        "选择轮次", round_labels, default=round_labels[default_idx],
        key="ko_round_segment", width="stretch"
    )
    if sel_label is None:
        sel_label = round_labels[default_idx]
    sel_round = [r for r, lbl in round_options if lbl == sel_label][0]

    matches = sorted([f for f in ko if f["round_number"] == sel_round],
                     key=lambda f: f.get("match_number", 0))

    # 小组赛 standings 用于历史数据参考
    gd = _grp.load_group_data(model)
    standings = _grp.compute_standings(gd) if gd else {}
    rank_map = _rk.world_rank_map(model)

    # slot 投影（用于未确定队伍）
    def _find_group_of(team):
        for gname, data in gd.items():
            if team in data["teams"]:
                return gname
        return None

    def _team_standings(team):
        """返回该队在小组赛中的战绩摘要 dict。"""
        for gname, rows in standings.items():
            for r in rows:
                if r["team"] == team:
                    return r
        return None

    def _resolve_team(f, side):
        """解析一边的队伍：优先 home_team/away_team（已确定），否则用 slot code。"""
        team = f.get(f"{side}_team")
        src = f.get(f"{side}_src")
        if team and team in model.teams:
            return team, False  # (team_name, is_slot)
        if src:
            return src, True  # (slot_code, is_slot)
        return "待定", True

    # ── 对阵卡片 ──
    section_title(f"{_STAGE_LABELS.get(sel_round, sel_label)} · 对阵一览")
    cards = []
    for f in matches:
        mn = f["match_number"]
        h, h_slot = _resolve_team(f, "home")
        a, a_slot = _resolve_team(f, "away")
        finished = f.get("home_score") is not None
        bj = _sch.beijing(f.get("date_utc")) if f.get("date_utc") else {"full": "—"}

        def _team_line(team, is_slot, side):
            if is_slot:
                return (f'<span style="color:var(--wc-muted);font-style:italic;">{team}</span>')
            rk_info = rank_map.get(team)
            rk_str = f'<span style="color:var(--wc-muted);font-size:11px;">#{rk_info[0]}</span>' if rk_info else ""
            ts = _team_standings(team)
            ts_str = ""
            if ts:
                ts_str = (f'<span style="font-size:11px;color:var(--wc-muted);">'
                          f'小组赛 {ts["w"]}-{ts["d"]}-{ts["l"]} · {ts["pts"]}分 · '
                          f'净胜{ts["gd"]:+d} · 进{ts["gf"]}</span>')
            return (f'<div class="wc-ko-team-main">'
                    f'<span>{_flag(team)} <b>{zh(team)}</b> {rk_str}</span></div>'
                    + (f'<div class="wc-ko-team-note">{ts_str}</div>' if ts_str else ""))

        # 胜率条（仅未完赛且两队都已确定时计算）
        prob_bar = ""
        if not finished and not h_slot and not a_slot:
            try:
                probs = predict_1x2_for_match(f, neutral=True)["probs"]
                ph, pd, pa = probs["home"], probs["draw"], probs["away"]
                prob_bar = (
                    f'<div style="display:flex;height:7px;border-radius:5px;overflow:hidden;margin:6px 0;">'
                    f'<div style="width:{ph * 100:.0f}%;background:#16a34a;"></div>'
                    f'<div style="width:{pd * 100:.0f}%;background:#9aa7b6;"></div>'
                    f'<div style="width:{pa * 100:.0f}%;background:#2563eb;"></div></div>'
                    f'<div style="display:flex;justify-content:space-between;font-size:11px;color:var(--wc-muted);">'
                    f'<span>胜 {ph:.0%}</span><span>平 {pd:.0%}</span><span>负 {pa:.0%}</span></div>'
                )
            except Exception:
                pass

        score_html = ""
        if finished:
            score_html = (f'<div style="font-size:20px;font-weight:800;color:#16a34a;text-align:center;'
                          f'margin:6px 0;">{int(f["home_score"])} : {int(f["away_score"])}</div>')
            time_html = f'<span style="color:var(--wc-muted);font-size:12px;">{bj["full"]}（北京）· 已完赛</span>'
        else:
            time_html = f'<span style="color:var(--wc-muted);font-size:12px;">⏳ {bj["full"]}（北京）</span>'

        border_style = "dashed" if (h_slot or a_slot) else "solid"
        finished_class = " finished" if finished else ""
        slot_tag = ('<span style="background:#f59e0b;color:#000;font-size:10px;padding:1px 6px;'
                    'border-radius:8px;margin-left:6px;">待定</span>') if (h_slot or a_slot) else ""

        cards.append(
            f'<div class="wc-ko-card{finished_class}" style="border-style:{border_style};">'
            f'<div class="wc-ko-head">'
            f'<span class="wc-ko-meta">M{mn} · 📍{f.get("location", "")}</span>'
            f'{time_html}{slot_tag}</div>'
            f'{_team_line(h, h_slot, "home")}'
            f'{score_html}'
            f'<div class="wc-ko-divider"></div>'
            f'{_team_line(a, a_slot, "away")}'
            f'{prob_bar}'
            f'</div>'
        )
    st.markdown(f'<div class="wc-ko-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    # ── 晋级概率总览 ──
    st.markdown("---")
    section_title("🏆 晋级概率总览")
    try:
        sig = _grp.played_signature(gd) if gd else ""
        n_sims = 5000
        tkey = f"ko_toursim:{n_sims}:{hash(sig)}"
        if tkey not in st.session_state:
            with st.spinner(f"蒙特卡洛模拟 {n_sims} 次…"):
                st.session_state[tkey] = _tour.simulate_tournament(model, gd, n_sims=n_sims)
        tour = st.session_state[tkey]
        import pandas as pd
        # tour = {team: {r16, qf, sf, final, champion}}
        col_labels = {"r16": "进16强", "qf": "进8强", "sf": "进4强", "final": "进决赛", "champion": "夺冠"}
        # 根据当前阶段隐藏已过去的列
        skip_before = {4: [], 5: ["r16"], 6: ["r16", "qf"], 7: ["r16", "qf", "sf"], 8: ["r16", "qf", "sf", "final"]}
        skip_cols = skip_before.get(sel_round, [])
        show_keys = [k for k in ["r16", "qf", "sf", "final", "champion"] if k not in skip_cols]
        trows = sorted(tour.items(), key=lambda kv: kv[1]["champion"], reverse=True)

        def _tcell(t):
            rs = rank_map.get(t)
            return f"{_flag(t)} {zh(t)}" + (f"（#{rs[0]}）" if rs and rs[0] else "")

        df_rows = []
        for t, r in trows:
            row = {"球队": _tcell(t)}
            for k in show_keys:
                row[col_labels[k]] = f"{r[k]:.1%}" if r[k] < 0.1 else f"{r[k]:.0%}"
            df_rows.append(row)
        st.dataframe(pd.DataFrame(df_rows), hide_index=True, width="stretch")
        st.caption(f"基于 {n_sims} 次蒙特卡洛模拟；平局按加时/点球近似处理。")
    except Exception as exc:
        st.warning(f"晋级概率模拟暂不可用：{exc}")

    # ── 焦点对决 ──
    st.markdown("---")
    section_title("🔥 本轮焦点")
    spotlights = []
    for f in matches:
        h, h_slot = _resolve_team(f, "home")
        a, a_slot = _resolve_team(f, "away")
        if h_slot or a_slot or f.get("home_score") is not None:
            continue
        try:
            probs = predict_1x2_for_match(f, neutral=True)["probs"]
            margin = abs(probs["home"] - probs["away"])
            spotlights.append((margin, f, probs))
        except Exception:
            pass
    spotlights.sort(key=lambda x: x[0])  # 最接近的排前面
    for _, f, probs in spotlights[:3]:
        h, a = f["home_team"], f["away_team"]
        hr, ar = rank_map.get(h), rank_map.get(a)
        ph, pd, pa = probs["home"], probs["draw"], probs["away"]
        h_ts, a_ts = _team_standings(h), _team_standings(a)
        h_line = f"{_flag(h)} {zh(h)}" + (f" (#{hr[0]})" if hr else "")
        a_line = f"{_flag(a)} {zh(a)}" + (f" (#{ar[0]})" if ar else "")
        st.markdown(f"**{h_line}** vs **{a_line}**")
        if h_ts and a_ts:
            st.caption(f"小组赛：{zh(h)} {h_ts['w']}-{h_ts['d']}-{h_ts['l']} {h_ts['pts']}分 · "
                       f"{zh(a)} {a_ts['w']}-{a_ts['d']}-{a_ts['l']} {a_ts['pts']}分")
        bar = (
            f'<div style="display:flex;height:9px;border-radius:6px;overflow:hidden;margin:4px 0 8px;">'
            f'<div style="width:{ph * 100:.0f}%;background:#16a34a;"></div>'
            f'<div style="width:{pd * 100:.0f}%;background:#9aa7b6;"></div>'
            f'<div style="width:{pa * 100:.0f}%;background:#2563eb;"></div></div>'
        )
        st.markdown(bar, unsafe_allow_html=True)
        st.caption(f"胜 {ph:.0%} · 平 {pd:.0%} · 负 {pa:.0%} · "
                   f"📍 {f.get('location', '')} · ⏳ {_sch.beijing(f.get('date_utc'))['full']}")




def _group_short(group: str) -> str:
    if group and group.startswith("Group "):
        return group.replace("Group ", "") + "组"
    return group or "淘汰赛"


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
    # 淘汰赛阶段提示
    _ko_fixtures = load_knockout_fixtures()
    _stage_info = _detect_current_stage(_ko_fixtures)
    if _stage_info:
        st.info(f"🏆 淘汰赛进行中 · **{_stage_info[0]}** · 查看「淘汰赛」页面获取对阵详情与晋级概率。")
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
    fg = f1.selectbox("小组", ["全部"] + _sorted_groups({r.get("group_name") or "淘汰赛" for r in rows}))
    fr = f2.selectbox("轮次", ["全部", 1, 2, 3])
    q = f3.text_input("搜索球队（中 / 英文）").strip().lower()
    only_upset = st.checkbox("只看爆冷预警（指数 ≥ 61）")

    def keep(r):
        if fg != "全部" and (r.get("group_name") or "淘汰赛") != fg:
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


def render_team_query(model) -> None:
    from wc2026.analysis import team_query
    from wc2026.data import squads as squads_mod
    from wc2026.data.flags import flag_emoji
    from wc2026.data.sources import fotmob as fotmob_mod

    render_hero("球队查询", "单队排名、近况、阵容、新闻与轮换风险", "TEAM LOOKUP")
    teams = _get_wc_teams(model, fixtures)
    c1, c2 = st.columns([1.2, 2])
    selected = c1.selectbox("选择球队", teams, format_func=lambda t: f"{flag_emoji(t)} {zh(t)}")
    query = c2.text_input("快速搜索（中 / 英文）", key="team_lookup_q").strip().lower()
    if query:
        filtered = [t for t in teams if query in t.lower() or query in zh(t).lower()]
        if filtered:
            selected = c1.selectbox("搜索结果", filtered, format_func=lambda t: f"{flag_emoji(t)} {zh(t)}",
                                    key="team_lookup_filtered")
        else:
            st.warning("未找到匹配球队，当前展示下拉选择的球队。")

    snap = team_query.build_team_snapshot(model, selected, fixtures)
    prof = snap["profile"]
    st.markdown(f"### {flag_emoji(selected)} {snap['team_cn']}")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("世界排名", f"#{snap['rank'] or '—'}", snap["rank_source"] or "无来源")
    m2.metric("本届战绩", f"{snap['current_record']['w']}-{snap['current_record']['d']}-{snap['current_record']['l']}")
    m3.metric("本届进/失", f"{snap['current_record']['gf']}/{snap['current_record']['ga']}")
    m4.metric("常用阵型", prof.get("formation") or "—")
    st.caption(f"排名来源：{snap['rank_source'] or '—'}"
               f"{(' · ' + snap['ranking_date']) if snap.get('ranking_date') else ''}。"
               "本页仅查询展示，新闻轮换信息不会写入模型强弱修正。")

    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("**球队画像**")
        st.write(prof.get("style_detail") or "暂无画像。")
        details = []
        if prof.get("best_achievement"):
            details.append({"项目": "世界杯最佳成绩", "内容": prof["best_achievement"]})
        if prof.get("wc_appearances"):
            details.append({"项目": "世界杯届数", "内容": prof["wc_appearances"]})
        if prof.get("training_base"):
            details.append({"项目": "训练基地", "内容": prof["training_base"]})
        if prof.get("key_players"):
            details.append({"项目": "关键球员", "内容": "、".join(prof["key_players"])})
        if details:
            st.dataframe(pd.DataFrame(details), hide_index=True, width="stretch")
    with right:
        st.markdown("**本届已赛记录**")
        rec = snap["current_record"]
        if rec["recent"]:
            st.dataframe(pd.DataFrame([{
                "日期": r["date"], "对手": r["opponent_cn"],
                "比分": r["score"], "结果": r["outcome"], "阶段": r["group"],
            } for r in rec["recent"]]), hide_index=True, width="stretch")
        else:
            st.caption("本届暂无已完赛记录。")

    st.markdown("**历史近况（本地历史库）**")
    rf = snap["recent_form"]
    st.caption(f"最近 {rf['n']} 场：{rf['w']}胜 {rf['d']}平 {rf['l']}负，进 {rf['gf']} / 失 {rf['ga']}。")
    if rf["matches"]:
        st.dataframe(pd.DataFrame([{
            "日期": r["date"], "主客": r["ha"], "对手": zh(r["opponent"]),
            "比分": r["score"], "结果": r["outcome"],
        } for r in rf["matches"]]), hide_index=True, width="stretch")

    with st.expander("联网补充：FotMob 阵容 / 本届聚合统计 / 新闻", expanded=True):
        cstat, csquad, cnews = st.columns(3)
        if action_button("📊 拉取本届聚合统计", key=f"team_stats:{selected}"):
            try:
                with st.spinner("从 FotMob 拉取球队统计…"):
                    with get_conn() as conn:
                        fm_id, fm_name = squads_mod._get_fm_id(conn, selected)
                    st.session_state[f"team_stats_data:{selected}"] = fotmob_mod.fetch_team_stats(fm_id, fm_name)
                st.success("已更新本届聚合统计。")
            except Exception as exc:
                st.error(f"统计拉取失败：{exc}")
        stats = st.session_state.get(f"team_stats_data:{selected}")
        if stats:
            cstat.metric("控球率", f"{stats['possession']:.0%}" if stats.get("possession") is not None else "—")
            cstat.metric("累计 xG", f"{stats['xg']:.1f}" if stats.get("xg") is not None else "—")
            cstat.metric("累计 xGA", f"{stats['xga']:.1f}" if stats.get("xga") is not None else "—")
            st.caption("FotMob 本届聚合统计，不等同于单场技术统计。")

        if action_button("👥 拉取阵容 / 伤停", key=f"team_squad:{selected}"):
            try:
                with st.spinner("从 FotMob 拉取阵容…"):
                    res = squads_mod.refresh_fm_squad(selected)
                st.success(f"已更新：{res['count']} 人，伤停/缺阵 {res['injured']}，最近阵型 {res.get('formation') or '—'}。")
            except Exception as exc:
                st.error(f"阵容拉取失败：{exc}")
        sq = squads_mod.load_fm_squad(selected)
        if sq:
            csquad.metric("最近阵型", sq.get("formation") or "—")
            injured = [p for players in sq["groups"].values() for p in players if p.get("injured")]
            csquad.metric("伤停/缺阵", len(injured))
            if injured:
                st.dataframe(pd.DataFrame([{
                    "球员": p.get("name_zh") or p["player_name"],
                    "位置": squads_mod.POS_ZH.get(p.get("position"), p.get("position")),
                    "说明": p.get("injury_note") or "伤停/缺阵",
                } for p in injured]), hide_index=True, width="stretch")

        news_key = f"team_news_data:{selected}"
        if action_button("📰 拉取球队新闻", key=f"team_news:{selected}"):
            try:
                with st.spinner("联网抓取球队新闻…"):
                    st.session_state[news_key] = news_mod.fetch_for_teams([selected], limit=8)
                st.success("新闻已更新。")
            except Exception as exc:
                st.error(f"新闻拉取失败：{exc}")
        items = st.session_state.get(news_key) or []
        rot = team_query.rotation_signals(items)
        cnews.metric("新闻条数", len(items))
        cnews.metric("轮换信号", "有" if rot["detected"] else "未见")
        if rot["detected"]:
            st.warning(rot["policy"])
            st.dataframe(pd.DataFrame(rot["items"]), hide_index=True, width="stretch")
        if items:
            st.dataframe(pd.DataFrame([{
                "来源": i.get("source", ""), "标题": i.get("title", ""),
                "时间": i.get("pub", ""), "链接": i.get("link", ""),
            } for i in items]), hide_index=True, width="stretch")
        else:
            st.caption("点击“拉取球队新闻”后显示；轮换/替补信息只作提示，不改变模型基础强弱。")


def render_schedule(model) -> None:
    from wc2026.analysis import schedule as sch, ranking as rk
    from wc2026.data.flags import flag_emoji
    from datetime import datetime, timezone
    section_title("小组赛赛程")
    # 淘汰赛阶段提示
    if _detect_current_stage(load_knockout_fixtures()):
        st.info("小组赛赛程已全部结束。淘汰赛赛程请查看「淘汰赛」页面。")
    if not fixtures:
        st.warning("暂无赛程数据（需先刷新 2026 赛程）。")
        return
    rank_map = rk.world_rank_map(model)
    groups = _sorted_groups({f["group_name"] for f in fixtures if f.get("group_name")})
    fg = st.selectbox("分组筛选", ["全部"] + groups, key="sched_group")
    flist = [f for f in fixtures if fg == "全部" or f.get("group_name") == fg]
    flist = sch.sort_fixtures(flist, datetime.now(timezone.utc))

    def _cell(t):
        rs = rank_map.get(t)
        return f"{flag_emoji(t)} {zh(t)}（{rs[1]} #{rs[0]}）" if rs and rs[0] else f"{flag_emoji(t)} {zh(t)}"

    by_date: dict[str, list[dict]] = {}
    for f in flist:
        bj = sch.beijing(f.get("date_utc"))
        by_date.setdefault(bj["date"], []).append({**f, "_bj": bj})
    date_keys = sorted(by_date)
    if not date_keys:
        st.info("当前筛选下暂无比赛。")
        return
    today_key = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    default_idx = next((i for i, d in enumerate(date_keys) if d >= today_key), 0)
    date_labels = []
    for d in date_keys:
        first = by_date[d][0]["_bj"]
        suffix = "今天" if d == today_key else first["weekday"]
        date_labels.append(f"{d[5:]} / {suffix}")
    selected_label = st.radio("日期", date_labels, index=default_idx, horizontal=True,
                              label_visibility="collapsed", key=f"sched_date:{fg}")
    selected_date = date_keys[date_labels.index(selected_label)]
    day_matches = sorted(by_date[selected_date], key=lambda f: f.get("date_utc") or "")

    st.markdown(
        f"""
        <div class="wc-schedule-head">
          <div>
            <h3>{selected_label}</h3>
            <p>当前日期 {len(day_matches)} 场 · 总计 {len(flist)} 场 · 北京时间 UTC+8</p>
          </div>
          <div class="wc-note">按时间线展示，已完赛显示比分，未开赛显示状态。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    cards = ['<div class="wc-timeline">']
    for f in day_matches:
        bj = f["_bj"]
        res = sch.match_result(f.get("home_score"), f.get("away_score"))
        home_score = f.get("home_score") if res["finished"] else "—"
        away_score = f.get("away_score") if res["finished"] else "—"
        status = "已结束" if res["finished"] else "未开赛"
        cards.append(
            '<div class="wc-match-card">'
            f'<div class="wc-match-time">{bj["time"]}<small>{bj["weekday"]}</small></div>'
            '<div class="wc-match-body">'
            '<div class="wc-match-meta">'
            f'<span>{_group_short(f.get("group_name", ""))} · 第{f.get("round_number", "")}轮</span>'
            f'<span>📍 {f.get("location", "")}</span>'
            '</div>'
            f'<div class="wc-team-row"><span>{_cell(f["home_team"])}</span><span class="wc-score">{home_score}</span></div>'
            f'<div class="wc-team-row"><span>{_cell(f["away_team"])}</span><span class="wc-score">{away_score}</span></div>'
            f'<div class="wc-status">{status}</div>'
            '</div>'
            '</div>'
        )
    cards.append("</div>")
    st.markdown("".join(cards), unsafe_allow_html=True)
    st.caption(f"世界排名：FIFA 官方{('（' + (rk.ranking_date() or '') + '）') if rk.ranking_date() else ''}，"
               "缺失回退模型 Elo；比分在赛程数据更新后自动显示。")


def render_bold_predictions(model) -> None:
    """大胆预测页面：比分预测 + 进球量 + 冷门推荐。"""
    from wc2026.analysis.bold_predictions import fixture_predictions
    from wc2026.analysis import ranking as rk

    section_title("⚡ 大胆预测 · 比分 / 进球 / 冷门")
    # 淘汰赛阶段提示
    if _detect_current_stage(load_knockout_fixtures()):
        st.info("小组赛预测已完成。淘汰赛逐场预测请在「单场分析」中查看。")
    st.caption("以下预测基于当前模型比分矩阵，结合实际比赛中比分的高度随机性，给出多比分参考与冷门提醒。"
               "模型结论仅供娱乐参考，请理性参与。")

    rows = fixture_predictions(model)
    if not rows:
        st.warning("暂无小组赛赛程数据。")
        return

    # 过滤控件
    groups = _sorted_groups({r["group_raw"] for r in rows})
    sel_group = st.selectbox("分组", ["全部"] + groups, key="bold_group")
    show_played = st.checkbox("显示已完赛场次", value=False, key="bold_played")
    only_upset = st.checkbox("只看冷门关注（爆冷指数 ≥ 60）", value=False, key="bold_upset")

    filtered = rows
    if sel_group != "全部":
        filtered = [r for r in filtered if r["group_raw"] == sel_group]
    if not show_played:
        filtered = [r for r in filtered if not r["finished"]]
    if only_upset:
        filtered = [r for r in filtered if r["is_upset_watch"]]

    # 统计
    unplayed = [r for r in rows if not r["finished"]]
    upset_count = sum(1 for r in unplayed if r["is_upset_watch"])

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("小组赛场次", len(rows))
    col2.metric("未开赛", len(unplayed))
    col3.metric("冷门关注", upset_count)
    col4.metric("当前筛选", len(filtered))

    if not filtered:
        st.info("当前筛选条件下无场次。")
        return

    st.divider()

    # 构建展示行
    display = []
    for r in filtered:
        home_zh = zh(r["home"])
        away_zh = zh(r["away"])
        upset = r["upset"]
        goal = r["goal"]

        # 比分预测
        score_pred = r["top_scores_display"] if not r["finished"] else f"✅ {r['result']}"

        # 进球区间
        if goal:
            goal_text = f"{goal['recommend']}（XG {goal['xg_total']:.1f}）"
        else:
            goal_text = "—"

        # 爆冷
        if upset:
            upset_level = upset["level"]
            upset_idx = upset["index"]
            fav = upset.get("favorite", "")  # favorite 是球队名（库名）
            dog_team = r["away"] if fav == r["home"] else r["home"]
            upset_text = f"{upset_idx}/100 {upset_level}"
            if upset_idx >= 60:
                upset_text += f" ⚠️ {zh(dog_team)}有机会"
        else:
            upset_text = "—"

        # 冷门标记
        upset_tag = "🔥" if r["is_upset_watch"] else ""

        display.append({
            "冷门": upset_tag,
            "小组": r["group"],
            "轮": f"第{r['round']}轮",
            "日期": r["date_str"],
            "北京时间": r["time"],
            "主队": f"{r['home_flag']} {home_zh}",
            "客队": f"{r['away_flag']} {away_zh}",
            "预测比分": score_pred,
            "推荐进球区间": goal_text,
            "爆冷指数": upset_text,
        })

    # 按小组排序
    display.sort(key=lambda d: (d["小组"], d["轮"]))

    st.dataframe(
        pd.DataFrame(display),
        hide_index=True,
        width="stretch",
        column_config={
            "冷门": st.column_config.TextColumn(width="small"),
            "小组": st.column_config.TextColumn(width="small"),
            "轮": st.column_config.TextColumn(width="small"),
        },
    )

    # 冷门详情
    upset_watch = [r for r in filtered if r["is_upset_watch"]]
    if upset_watch:
        st.divider()
        st.subheader("🔥 冷门关注场次详解")
        for r in upset_watch:
            home_zh = zh(r["home"])
            away_zh = zh(r["away"])
            upset = r["upset"]
            goal = r["goal"]

            with st.expander(
                f"{r['home_flag']} {home_zh} vs {away_zh} {r['away_flag']} "
                f"· {r['group']} 第{r['round']}轮 · 爆冷 {upset['index']}/100"
            ):
                col_a, col_b = st.columns(2)
                with col_a:
                    st.markdown("**🏟 赛程**")
                    st.write(f"🕐 {r['date_str']} {r['weekday']} {r['time']}（北京）")
                    st.write(f"📍 {r['location']}")
                    st.markdown("**🎯 比分预测（Top-3）**")
                    if r["top_scores"]:
                        for s in r["top_scores"]:
                            st.write(f"• {s['score']} — {s['prob']:.1%}")
                    st.markdown("**⚽ 进球区间**")
                    if goal:
                        st.write(f"推荐 **{goal['recommend']}** · 期望总进球 {goal['xg_total']:.1f}")
                        for reason in goal["reasons"]:
                            st.write(f"• {reason}")
                with col_b:
                    st.markdown("**⚠️ 爆冷因子**")
                    if upset:
                        fav = upset.get("favorite", "")  # favorite 是球队名（库名）
                        is_home_fav = fav == r["home"]
                        fav_name = zh(r["home"]) if is_home_fav else zh(r["away"])
                        dog_name = zh(r["away"]) if is_home_fav else zh(r["home"])
                        st.write(f"热门方：{fav_name} · 冷门方：{dog_name}")
                        st.write(f"爆冷指数：**{upset['index']}/100** — {upset['level']}")
                        for f in upset.get("factors", []):
                            st.write(f"• **{f['name']}**：{f['detail']}")

    st.caption(
        "🎲 比分高度随机：以上为模型概率最高的比分组合，不代表必然发生。"
        "小组赛末轮尤其留意出线形势——已出线可能轮换、已淘汰战意下降，结果更不可控。"
        "冷门指数衡量「把热门当稳胆」的风险，指数越高越不适合做无脑稳胆。"
    )


def render_audit(model) -> None:
    """赛后复盘页：模型预测 vs 市场赔率 vs 实际赛果（文档 §6.4 / §11.3）。"""
    from wc2026.analysis import audit as _audit
    from wc2026.analysis.imminent import load_all_prematch_snapshots
    section_title("赛后复盘：模型 vs 市场 vs 实际")
    if not fixtures:
        st.warning("暂无赛程数据（需先刷新 2026 赛程）。")
        return
    summary = _audit.audit_summary(model, fixtures, snapshots=load_all_prematch_snapshots())
    if summary["n_finished"] == 0:
        st.info("还没有已完赛比赛可供复盘。开赛并回填比分后，"
                "这里会逐场对比模型与市场的命中/偏差。")
        return

    scope = summary.get("scope", {})
    if scope.get("knockout_finished", 0):
        st.info(f"复盘已覆盖小组赛 {scope.get('group_stage_finished', 0)} 场、"
                f"淘汰赛 {scope.get('knockout_finished', 0)} 场；"
                f"淘汰赛分场专业复盘 {scope.get('knockout_reviewed', 0)} 场。"
                "每次一键全量刷新会自动联网补全已完赛淘汰赛的分场分析数据。")
    elif _detect_current_stage(load_knockout_fixtures()):
        st.info("淘汰赛进行中；已结束淘汰赛会在一键全量刷新后自动补全分场复盘。")

    mm = summary["model_metrics"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("已复盘场次", summary["n_finished"])
    c2.metric("模型命中率", f"{mm['accuracy']:.0%}")
    c3.metric("模型 LogLoss", f"{mm['log_loss']:.3f}")
    c4.metric("模型 Brier", f"{mm['brier']:.3f}")
    st.caption(f"LogLoss < 基准 {mm['baseline_log_loss']:.3f}（三分类瞎猜）即有预测力；"
               f"其中赛前锁定快照 {summary['n_with_snapshot']}/{summary['n_finished']} 场，"
               "其余为事后复算（当前模型已含赛果，仅参考）。")

    sm = summary["scoreline_metrics"]
    st.markdown("**赛前 Top 3 比分校准（90 分钟）**")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("可审计场次", sm["n"])
    s2.metric("首选比分命中", f"{sm['top1_accuracy']:.0%}" if sm["n"] else "—")
    s3.metric("Top 3 命中", f"{sm['top3_accuracy']:.0%}" if sm["n"] else "—")
    s4.metric("平均比分距离", f"{sm['mean_min_distance']:.2f}" if sm["n"] else "—")
    st.caption("只统计赛前已锁定三个推荐比分的比赛；淘汰赛统一采用 90 分钟含伤停补时比分，不含加时与点球。")

    cmp = summary["comparison"]
    if cmp.get("enabled"):
        st.markdown("**模型 vs 市场（赔率基准）**")
        _lab = {"log_loss": "LogLoss（越低越好）", "brier": "Brier（越低越好）",
                "accuracy": "命中率（越高越好）"}
        rows = []
        for k in ("log_loss", "brier", "accuracy"):
            d = cmp[k]
            fmt = (lambda v: f"{v:.0%}") if k == "accuracy" else (lambda v: f"{v:.3f}")
            rows.append({"指标": _lab[k], "模型": fmt(d["model"]),
                         "市场": fmt(d["market"]), "更优方": d["better"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(f"基于 {cmp['n']} 场有赛前赔率快照的比赛（文档 §11.3：赔率验证偏差与实际结果）。")
    else:
        st.caption("市场对比：暂无赛前赔率快照（需在赛前用 The Odds API 拉取入库），当前仅展示模型表现。")

    st.markdown("**逐场对比**")
    table = []
    for a in summary["matches"]:
        m, mk = a["model"], a["market"]
        scoreline = a.get("scoreline") or {}
        top_scores = scoreline.get("top_scores") or []
        score_hit = (f"第 {scoreline['hit_rank']} 位命中" if scoreline.get("top3_hit") else
                     "未命中" if scoreline.get("available") else "无锁定快照")
        table.append({
            "比赛": f"{a['match']['home_cn']} vs {a['match']['away_cn']}",
            "阶段": a.get("stage", {}).get("label", "—"),
            "推荐比分 Top 3": " / ".join(r["score"] for r in top_scores) or "—",
            "90分钟比分": a["match"]["score"],
            "比分命中": score_hit,
            "最小距离": scoreline.get("min_score_distance", "—"),
            "终场比分": (a["match"].get("final_score")
                         if a["match"].get("final_score") != a["match"]["score"] else "—"),
            "实际": a["actual_cn"],
            "模型预测": f"{m['pick_cn']} {m['probs'][m['pick']]:.0%}",
            "模型": "✅" if m["hit"] else "❌",
            "市场预测": (mk["pick_cn"] if mk.get("enabled") else "—"),
            "市场": (("✅" if mk["hit"] else "❌") if mk.get("enabled") else "—"),
            "学习修正": "已入账" if (a.get("learning") or {}).get("enabled") else "待重算",
            "赛果来源": a["match"].get("result_source") or "本地赛果",
            "数据": "锁定" if m["source"] == "赛前锁定快照" else "复算",
        })
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")

    with st.expander("命中 / 偏差详解", expanded=False):
        for a in summary["matches"]:
            st.markdown(f"- **{a['match']['home_cn']} {a['match']['score']} "
                        f"{a['match']['away_cn']}**：{a['verdict']}")
            review = a.get("postmatch_review") or {}
            learning = a.get("learning") or {}
            scoreline = a.get("scoreline") or {}
            if scoreline.get("available"):
                _scores = "、".join(r["score"] for r in scoreline.get("top_scores", []))
                _hit = (f"第 {scoreline['hit_rank']} 位命中" if scoreline.get("top3_hit") else "未命中")
                st.markdown(f"  - Top 3 对比：{_scores}；实际 {scoreline['actual_score']}（90分钟）；"
                            f"{_hit}，最小比分距离 {scoreline['min_score_distance']}。")
            else:
                st.markdown(f"  - Top 3 对比：{scoreline.get('reason', '无赛前锁定比分')}。")
            if learning.get("enabled"):
                pred = learning.get("predicted", {})
                err = learning.get("errors", {})
                teams = learning.get("teams", {})
                style = learning.get("style", {})
                weights = learning.get("weights", {})
                goal_cal = learning.get("goal_calibration", {})
                st.markdown(f"  - 赛后学习：{learning['summary']}")
                st.markdown(
                    "  - 预测/实际："
                    f"预测进球 {pred.get('home_xg', '—')} - {pred.get('away_xg', '—')} "
                    f"(总 {pred.get('total_goals', '—')})；"
                    f"真实比分 {a['match']['score']}；"
                    f"主队进球误差 {err.get('home_goal', '—')}，"
                    f"客队进球误差 {err.get('away_goal', '—')}。"
                )
                st.markdown(
                    "  - 校准权重："
                    f"{goal_cal.get('label', '总进球校准未知')}；"
                    f"事件 {weights.get('event', '—')} × 过程 {weights.get('process', '—')} × "
                    f"时间 {weights.get('time_decay', '—')} × 比分 {weights.get('scoreline', '—')} "
                    f"= 最终 {weights.get('final', '—')}。"
                )
                if weights.get("notes"):
                    st.markdown("  - 权重依据：" + "；".join(weights["notes"][:3]))
                hd, ad = teams.get("home", {}), teams.get("away", {})
                st.markdown(
                    "  - 队伍修正："
                    f"{hd.get('team_cn', '主队')} Elo {hd.get('delta_elo', '—')}，"
                    f"进攻 {hd.get('delta_attack', '—')}，防守 {hd.get('delta_defense', '—')}；"
                    f"{ad.get('team_cn', '客队')} Elo {ad.get('delta_elo', '—')}，"
                    f"进攻 {ad.get('delta_attack', '—')}，防守 {ad.get('delta_defense', '—')}。"
                )
                hp, ap = style.get("home", {}), style.get("away", {})
                st.markdown(
                    f"  - 风格上下文：{a['match']['home_cn']} {hp.get('lean', '—')} vs "
                    f"{a['match']['away_cn']} {ap.get('lean', '—')}，用于解释该场误差属于实力、对位还是随机事件。"
                )
            else:
                st.markdown(f"  - 赛后学习：{learning.get('reason', '暂无学习记录')}")
            if review.get("enabled") and a.get("stage", {}).get("type") == "knockout":
                st.markdown(f"  - 赛后复盘：{review['summary']}")
                st.markdown("  - 数据证据：" + "；".join(review.get("evidence", [])[:3]))
                _mu = review.get("model_update") or {}
                _update = "进入渐进修正" if _mu.get("should_update_strength") else "仅记录为证据，不直接改写实力"
                st.markdown(f"  - 偏差归因：{_mu.get('primary_bias_cn', '—')} · 权重 {_mu.get('weight', '—')} · {_update}")
                if _mu.get("notes"):
                    st.markdown("  - 归因依据：" + "；".join(_mu["notes"][:2]))
                st.markdown("  - 实力修正：" + review.get("model_feedback", ""))
    st.caption(summary["note"])


def render_global_chat(model) -> None:
    """AI 分析师：统筹全局数据的赛事级问答（夺冠概率 / 各组形势 / 模型校准 / 偏差）。"""
    from wc2026.analysis import audit as _audit, dashboard_bridge as _db
    from wc2026.analysis.imminent import load_all_prematch_snapshots
    from wc2026.llm import tournament_chat
    section_title("AI 分析师：统筹全局问答")
    if not fixtures:
        st.warning("暂无赛程数据（需先刷新 2026 赛程）。")
        return

    # 赛事总览（所有人可见）
    snaps = load_all_prematch_snapshots()
    summ = _audit.audit_summary(model, fixtures, snapshots=snaps)
    champ = _db._championship_payload(model)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("可预测场次", len(fixtures))
    c2.metric("已复盘", summ["n_finished"])
    c3.metric("模型命中率", f"{summ['model_metrics']['accuracy']:.0%}" if summ["n_finished"] else "—")
    c4.metric("夺冠热门", f"{zh(champ[0]['team'])} {champ[0]['champion']:.0%}" if champ else "—")
    if champ:
        st.caption("夺冠 Top5：" + " · ".join(f"{zh(c['team'])} {c['champion']:.0%}" for c in champ[:5]))

    if not llm_configured():
        st.info("需接入 LLM（在 .env 配置 LLM_API_KEY）后可对话；当前未配置。")
        return
    if not is_owner():
        st.caption("🔒 AI 对话仅所有者可用（会消耗 LLM token）；以上总览访客可见。")
        return

    teams = sorted({f["home_team"] for f in fixtures} | {f["away_team"] for f in fixtures})
    groups_list = _sorted_groups({f["group_name"] for f in fixtures if f.get("group_name")})
    fc1, fc2 = st.columns(2)
    sel_team = fc1.selectbox("聚焦球队（可选）", ["（全局）"] + [zh(t) for t in teams], key="gchat_team")
    sel_group = fc2.selectbox("聚焦小组（可选）", ["（全局）"] + groups_list, key="gchat_group")
    focus_team = next((t for t in teams if zh(t) == sel_team), None) if sel_team != "（全局）" else None
    focus_group = None if sel_group == "（全局）" else sel_group.replace("Group ", "")

    history = st.session_state.setdefault("gchat_history", [])
    for m in history:
        st.markdown(f"**{'🧑 你' if m['role'] == 'user' else '🤖 AI'}：** {m['content']}")
    q = st.text_area("问整届赛事的宏观问题", key="gchat_q", height=90,
                     placeholder="例：谁最被低估？哪个小组最乱？模型到目前准不准？最大冷门可能在哪？")
    cc1, cc2, _ = st.columns([1, 1, 2])
    if cc1.button("发送", key="gchat_send") and q.strip():
        history.append({"role": "user", "content": q.strip()})
        with st.spinner("AI 统筹全局数据分析中…"):
            ctx = tournament_chat.build_global_context(
                model, fixtures=fixtures, focus_team=focus_team,
                focus_group=focus_group, snapshots=snaps)
            ans = tournament_chat.ask(q.strip(), ctx, history=history[:-1])
        history.append({"role": "assistant", "content": ans["text"]})
        st.rerun()
    if cc2.button("清空对话", key="gchat_clear"):
        st.session_state["gchat_history"] = []
        st.rerun()
    if st.checkbox("查看 AI 看到的赛事数据摘要", key="gchat_ctx"):
        st.code(tournament_chat.build_global_context(
            model, fixtures=fixtures, focus_team=focus_team, focus_group=focus_group, snapshots=snaps))
    st.caption("AI 基于赛事统筹数据作答（夺冠模拟/各组形势/模型校准）；概率有误差、仅供参考、非投注建议。")


def _rec_stage_label(f: dict) -> str:
    rn = f.get("round_number") or 0
    return _STAGE_LABELS.get(rn, f"第{rn}轮") if rn >= 4 else (f.get("group_name") or "小组赛")


def _rec_fixture_label(f: dict) -> str:
    from wc2026.analysis import schedule as _sch
    bj = _sch.beijing(f.get("date_utc") or "")
    return f"M{f.get('match_number')} · {bj['full']} · {_rec_stage_label(f)} · {zh(f['home_team'])} vs {zh(f['away_team'])}"


def _rec_dates(fixtures: list[dict]) -> list[str]:
    from wc2026.analysis import schedule as _sch
    return sorted({_sch.beijing(f.get("date_utc") or "")["date"] for f in fixtures if f.get("date_utc")})


def _rec_context(model, fixture: dict, fixtures: list[dict]) -> tuple:
    from wc2026.analysis import recommendations as rec_mod
    from wc2026.analysis import dimensions as dims_mod
    from wc2026.analysis.team_style import style_profile

    h, a = fixture["home_team"], fixture["away_team"]
    neutral = h not in HOSTS
    mat = model.score_matrix(h, a, neutral)
    lam, mu = model.expected_goals(h, a, neutral)
    prof = dims_mod.nine_dimension_profile(model, h, a, neutral=neutral)
    style_h, style_a = style_profile(h), style_profile(a)
    team_context = {
        "home_score": prof["score_home"],
        "away_score": prof["score_away"],
        "dimension_note": prof["explanation"],
        "home_style": f"{style_h.get('formation')} · {style_h.get('lean')}",
        "away_style": f"{style_a.get('formation')} · {style_a.get('lean')}",
        "lambda_home": round(lam, 3),
        "lambda_away": round(mu, 3),
        "stage": _rec_stage_label(fixture),
    }
    recs = rec_mod.list_recommendations(match_number=fixture.get("match_number"))
    consensus = rec_mod.consensus_report(
        h, a, recs, model_matrix=mat, lambda_home=lam, lambda_away=mu,
        team_context=team_context,
    )
    return recs, consensus


def _rec_table(rows: list[dict], title: str, label_key: str) -> None:
    if not rows:
        st.caption(f"{title}：暂无推荐。")
        return
    st.markdown(f"**{title}**")
    st.dataframe(pd.DataFrame([{
        "推荐": r[label_key],
        "综合概率": f"{r['probability']:.1%}",
        "模型概率": f"{r.get('model_prob', 0):.1%}" if r.get("model_prob") is not None else "—",
        "外部共识": f"{r.get('external_strength', 0):.2f}",
    } for r in rows]), hide_index=True, width="stretch")


def render_recommendation_compare(model, fixtures: list[dict]) -> None:
    from wc2026.analysis import schedule as _sch
    from wc2026.analysis import recommendations as rec_mod
    from wc2026.data.db import init_db

    render_hero("推荐对比", "把 iuv、小红书、朋友和模型比分放在一块，统一做比分、进球数与半全场综合分析。", "CONSENSUS DESK")
    init_db()
    rows = [f for f in fixtures if f.get("home_team") in model.teams and f.get("away_team") in model.teams]
    if not rows:
        st.warning("暂无可用赛程。")
        return

    dates = _rec_dates(rows)
    focus = st.session_state.pop("rec_focus_match_number", None)
    today = datetime.now().strftime("%Y-%m-%d")
    focus_fixture = next((f for f in rows if f.get("match_number") == focus), None)
    default_date = (_sch.beijing(focus_fixture.get("date_utc"))["date"]
                    if focus_fixture else (today if today in dates else dates[0]))
    date_labels = {}
    for f in rows:
        bj = _sch.beijing(f.get("date_utc") or "")
        date_labels.setdefault(bj["date"], f"{bj['date']} · {bj['full'].rsplit(' ', 1)[0]}")
    dcol, mcol = st.columns([1, 2.2])
    date = dcol.selectbox("比赛日期（北京时间）", dates, index=dates.index(default_date),
                          format_func=lambda d: date_labels.get(d, d))
    day_rows = [f for f in rows if _sch.beijing(f.get("date_utc") or "")["date"] == date]
    if not day_rows:
        st.info("这一天没有可用比赛。")
        return

    st.markdown("**当天赛程表头**")
    header = []
    for f in day_rows:
        rec_count = len(rec_mod.list_recommendations(match_number=f.get("match_number")))
        bj = _sch.beijing(f.get("date_utc") or "")
        header.append({
            "场次": f"M{f.get('match_number')}",
            "时间": bj["time"],
            "阶段": _rec_stage_label(f),
            "比赛": f"{zh(f['home_team'])} vs {zh(f['away_team'])}",
            "推荐来源": rec_count,
        })
    st.dataframe(pd.DataFrame(header), hide_index=True, width="stretch")

    match_index = 0
    if focus_fixture in day_rows:
        match_index = day_rows.index(focus_fixture)
    selected = mcol.selectbox("选择比赛", day_rows, index=match_index, format_func=_rec_fixture_label)
    home_team, away_team = selected["home_team"], selected["away_team"]
    st.markdown(f"### {zh(home_team)} vs {zh(away_team)}")
    st.caption(f"{_rec_stage_label(selected)} · {_sch.beijing(selected.get('date_utc') or '')['full']} · M{selected.get('match_number')}")

    recs, consensus = _rec_context(model, selected, fixtures)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("来源数", len(recs))
    k2.metric(f"{zh(home_team)}强弱分", f"{consensus['team_context'].get('home_score', 0):.1f}")
    k3.metric(f"{zh(away_team)}强弱分", f"{consensus['team_context'].get('away_score', 0):.1f}")
    k4.metric("模型λ", f"{consensus['team_context'].get('lambda_home', 0):.2f}:{consensus['team_context'].get('lambda_away', 0):.2f}")
    st.caption(consensus["team_context"].get("dimension_note", ""))

    with st.form(f"rec_form:{selected.get('match_number')}"):
        st.markdown("**新增推荐来源**")
        c1, c2, c3 = st.columns([1.1, 2.2, 1])
        source = c1.text_input("名字 / 来源", placeholder="iuv / 小红书 / 朋友A")
        scores = c2.text_input("比分预测", placeholder="0-0 1-0 1-1 2-1")
        confidence = c3.selectbox("置信度", ["中", "高", "低"])
        g1, g2 = st.columns(2)
        goal_picks = g1.text_input("进球数预测", placeholder="0-1球, 1-2球, 小2.5")
        half_full = g2.text_input("半全场预测", placeholder="平平 平胜 平负")
        note = st.text_area("备注", placeholder="可粘贴推荐理由、盘口、来源链接或自己的判断", height=70)
        submitted = st.form_submit_button("保存推荐", disabled=not is_owner())
        if submitted:
            if not source.strip():
                st.error("请填写来源名。")
            elif not scores.strip() and not goal_picks.strip() and not half_full.strip():
                st.error("至少填写比分、进球数或半全场中的一项。")
            else:
                rec_mod.save_recommendation(
                    selected.get("match_number"), home_team, away_team, source,
                    scores, goal_picks, half_full, confidence=confidence, note=note,
                )
                st.success("已保存推荐。")
                st.rerun()
    if not is_owner():
        st.caption("🔒 访客只读；保存推荐和 AI 分析需要所有者模式。")

    recs, consensus = _rec_context(model, selected, fixtures)
    st.markdown("**已记录推荐**")
    if recs:
        st.dataframe(pd.DataFrame([{
            "来源": r["source"],
            "比分": " / ".join(r["scores"]) or "—",
            "进球数": " / ".join(r["goal_picks"]) or "—",
            "半全场": " / ".join(r["half_full_picks"]) or "—",
            "置信度": r["confidence"],
            "备注": r["note"],
        } for r in recs]), hide_index=True, width="stretch")
        del_cols = st.columns(min(4, len(recs)))
        for i, r in enumerate(recs):
            with del_cols[i % len(del_cols)]:
                if is_owner() and st.button(f"删除 {r['source']} #{r['id']}", key=f"del_rec:{r['id']}"):
                    rec_mod.delete_recommendation(r["id"])
                    st.rerun()
    else:
        st.caption("暂无外部推荐，先保存一个来源后再做共识对比。")

    section_title("综合排序")
    t1, t2 = st.columns([1.2, 1])
    with t1:
        _rec_table(consensus["score_recommendations"], "比分推荐 Top", "score")
    with t2:
        _rec_table(consensus["goal_recommendations"], "进球数推荐 Top", "label")
    _rec_table(consensus["half_full_recommendations"], "半全场推荐 Top", "label")

    with st.expander("🤖 AI 综合分析（ds-v4-pro / 当前 LLM 配置）", expanded=bool(recs)):
        st.caption("AI 会读取外部推荐、程序综合排序、球队风格、强弱分和模型 λ；程序排序即使无 AI 也可用。")
        if action_button("生成 AI 综合分析", key=f"rec_ai:{selected.get('match_number')}"):
            with st.spinner("AI 正在综合比分、进球数和半全场方向…"):
                st.session_state[f"rec_ai_text:{selected.get('match_number')}"] = rec_mod.ai_analyze(
                    home_team, away_team, recs, consensus
                )
        ai = st.session_state.get(f"rec_ai_text:{selected.get('match_number')}")
        if ai:
            (st.info if ai.get("ok") else st.warning)(ai["text"])
        elif not recs:
            st.caption("暂无外部推荐，建议先录入至少一个来源。")


inject_design_system()
user = require_login()
require_view_access()  # 访问口令墙：设了 ACCESS_PASSWORD 才生效；管理员 ?owner= 免口令

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

page_options = list(WORLD_CUP_PAGE_OPTIONS)
if is_owner():
    page_options.append("访问记录")
if user["role"] == "admin":
    page_options.append("用户管理")
_pending_nav = st.session_state.pop("_pending_nav_page", None)
if _pending_nav in page_options:
    st.session_state["top_page_nav"] = _pending_nav
competition, page = render_top_nav(page_options)
render_admin_user_panel()
render_access_banner()
if competition != "世界杯":
    render_club_competition(competition)
    st.stop()

model = load_model()
fixtures = load_fixtures()
render_hero(
    "2026 世界杯预测工作台",
    "比分概率、盘口价值、晋级之路与证据分析集中在一个可操作界面中。模型结论仅供参考，请理性参与并遵守当地法规。",
)
if page == "首页":
    render_home(model)
    st.stop()
if page == "淘汰赛":
    render_knockout_stage(model)
    st.stop()
if page == "访问记录":
    render_access_log()
    st.stop()
if page == "小组赛赛程":
    render_schedule(model)
    st.stop()
if page == "球队查询":
    render_team_query(model)
    st.stop()
if page == "晋级之路":
    render_bracket(model)
    st.stop()
if page == "小组出线":
    render_group_stage(model)
    st.stop()
if page == "大胆预测":
    render_bold_predictions(model)
    st.stop()
if page == "赛后复盘":
    render_audit(model)
    st.stop()
if page == "AI 分析师":
    render_global_chat(model)
    st.stop()
if page == "推荐对比":
    render_recommendation_compare(model, fixtures)
    st.stop()
if page == "用户管理":
    render_user_management()
    st.stop()

st.markdown('<div class="wc-analysis-panel">', unsafe_allow_html=True)
st.markdown("**选择比赛**")
mode = st.radio("方式", ["按赛程", "自定义对阵"], horizontal=True)
venue_info = None
if mode == "按赛程" and fixtures:
    from wc2026.analysis import schedule as _sch
    from datetime import datetime as _dt, timezone as _tz
    _ko_for_filter = load_knockout_fixtures()
    _fixture_groups = {f.get("group_name") for f in fixtures if f.get("group_name")}
    if _ko_for_filter:
        _fixture_groups.add("淘汰赛")
    groups = _sorted_groups(_fixture_groups)
    c1, c2 = st.columns([1, 2.4])
    group_options = ["全部"] + groups
    _current_ko = _detect_current_stage(_ko_for_filter)
    _default_group = "淘汰赛" if _current_ko and "淘汰赛" in group_options else "全部"
    group_default = st.session_state.get("single_group_pill", _default_group)
    if group_default not in group_options:
        group_default = "全部"
    g = c1.pills(
        "分组", group_options, default=group_default, key="single_group_pill",
        format_func=lambda value: "全部" if value == "全部" else _group_short(value),
        width="stretch"
    )
    if g is None:
        g = group_default

    _is_ko = (g == "淘汰赛")
    if _is_ko:
        _ko_all = _ko_for_filter
        _stage_round = _current_ko[1] if _current_ko else None
        _stage_matches = ([f for f in _ko_all if f.get("round_number") == _stage_round]
                          if _stage_round else _ko_all)
        _ko_resolved = [f for f in _stage_matches
                        if f.get("home_team") in model.teams and f.get("away_team") in model.teams]
        flist = _ko_resolved if _ko_resolved else _stage_matches
        flist = _sch.sort_fixtures(flist, _dt.now(_tz.utc))
    else:
        flist = _sch.sort_fixtures(
            [f for f in fixtures if g == "全部" or (f.get("group_name") or "淘汰赛") == g], _dt.now(_tz.utc))

    if not flist:
        st.warning("当前筛选下暂无比赛。")
        st.stop()

    def _fx_label(i):
        f = flist[i]
        ht = f.get("home_team", "") or f.get("home_src", "?")
        at = f.get("away_team", "") or f.get("away_src", "?")
        ht_zh = zh(ht) if ht in model.teams else ht
        at_zh = zh(at) if at in model.teams else at
        res = _sch.match_result(f.get("home_score"), f.get("away_score"))
        bj = _sch.beijing(f.get("date_utc"))
        tag = f"✅ {res['score']}" if res["finished"] else (f"{bj['date'][5:]} {bj['time']}" if bj["date"] != "—" else "—")
        rn = f.get("round_number", "")
        stage_tag = _STAGE_LABELS.get(rn, f"第{rn}轮") if rn and rn >= 4 else _group_short(f.get("group_name") or "")
        return f"M{f.get('match_number','')} · {stage_tag} · {ht_zh} vs {at_zh} · {tag}"

    idx_default = st.session_state.get(f"single_match_pill:{g}", 0)
    if not isinstance(idx_default, int) or idx_default >= len(flist):
        idx_default = 0
    idx = c2.pills(
        "场次", list(range(len(flist))), default=idx_default,
        key=f"single_match_pill:{g}", format_func=_fx_label,
        width="stretch"
    )
    if idx is None:
        idx = idx_default
    sel = flist[idx]
    selected_fixture = sel
    home = sel.get("home_team") or sel.get("home_src") or "Unknown"
    away = sel.get("away_team") or sel.get("away_src") or "Unknown"
    _sel_rn = sel.get("round_number", 0)
    if _sel_rn and _sel_rn >= 4:
        _stage_lbl = _STAGE_LABELS.get(_sel_rn, f"第{_sel_rn}轮")
        venue_info = f"🗓 {(_sch.beijing(sel['date_utc'])['full'] if sel.get('date_utc') else '—')}（北京） · {_stage_lbl} · 📍{sel.get('location','')}"
    else:
        venue_info = f"🗓 {_sch.beijing(sel['date_utc'])['full']}（北京） · {sel.get('group_name') or '淘汰赛'} · 📍{sel.get('location','')}"
    default_neutral = home not in HOSTS
else:
    selected_fixture = None
    teams = _get_wc_teams(model, fixtures)
    di = teams.index("Spain") if "Spain" in teams else 0
    ai = teams.index("Germany") if "Germany" in teams else 1
    c1, c2 = st.columns(2)
    home = c1.selectbox("主队", teams, index=di, format_func=zh)
    away = c2.selectbox("客队", teams, index=ai, format_func=zh)
    default_neutral = True

_fixture_state = load_live_fixture_state()
if _fixture_state["fixtures"]:
    _fixture_time = (_fixture_state.get("fetched_at") or "").replace("T", " ")[:19]
    st.caption(f"赛程：实时 feed · {_fixture_time} UTC · 5 分钟缓存；本地数据库仅作断网回退。")
elif _fixture_state.get("error"):
    st.warning("实时赛程源暂不可用，当前显示本地缓存；对阵与比分可能滞后。")

o1, o2, o3 = st.columns([1, 1, 1.4])
neutral = o1.checkbox("中立场", value=default_neutral,
                      help="世界杯多数为中立场；东道主(美/加/墨)在本国默认非中立")
use_context = o2.checkbox("应用情境调整", value=False,
                          help="东道主额外加成；小组赛末轮出线压力(赛事中)")
tank_risk = (o3.checkbox("⚠️ 疑似控分/默契球", value=False,
                         help="末轮出线已定可能消极比赛/算计排名：下调进球并提示爆冷风险")
             if use_context else False)
if action_button("🔄 一键全量刷新", help="逐步刷新；单个联网源失败会记录并继续后续步骤"):
    from wc2026.refresh import resilient_refresh
    with st.spinner("抓数据 + 回填赛果 + 重训 + 赛中修正中…"):
        _refresh_result = resilient_refresh()
        st.cache_resource.clear()
        st.cache_data.clear()
    _ok = _refresh_result["status"] == "ok"
    (st.success if _ok else st.warning)(
        f"刷新{'完成' if _ok else '部分完成'}，总耗时 {_refresh_result['seconds']}s。")
    for _step in _refresh_result["steps"]:
        _msg = f"{_step['label']}（{_step['seconds']}s）"
        if _step["ok"]:
            st.caption(f"✅ {_msg}")
        else:
            st.warning(f"⚠️ {_msg}失败：{_step.get('error')}")
    st.rerun()
st.caption("LLM 理由/分析：" + ("✅ 已配置，可手动触发" if llm_configured() else "⚠️ 规则模板(未接入)"))
st.markdown('</div>', unsafe_allow_html=True)

if home == away:
    st.warning("请选择两支不同的球队。")
    st.stop()

if home not in model.teams or away not in model.teams:
    st.warning("该比赛队伍尚未确定（slot 待定），请选择已有确定队伍的比赛。")
    st.stop()

section_title(f"{zh(home)} vs {zh(away)}")
if venue_info:
    st.caption(venue_info)
if selected_fixture is not None and st.button("🧾 进入本场推荐对比", key=f"go_rec_compare:{selected_fixture.get('match_number')}"):
    st.session_state["rec_focus_match_number"] = selected_fixture.get("match_number")
    st.session_state["_pending_nav_page"] = "推荐对比"
    st.rerun()
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
# 克莱门特组合模型为预测主链：基线 λ → 东道主/末轮战意/控分(context) → 有界软信号(战术/体能/射门残差)。
from wc2026.analysis import clemente
from wc2026.data import squads as squads_mod
from wc2026.data.sources import fbref as fbref_mod
_cl_group_state = auto_group_state if (use_context or auto_group_state is not None) else None
# 复用 FotMob 缓存(无网络)：真实阵型喂战术因子，总身价升级「阵容实力」维度为真实
_sq_h = squads_mod.load_fm_squad(home)
_sq_a = squads_mod.load_fm_squad(away)
_val_h = squads_mod.squad_value_summary(_sq_h["groups"])["total"] if _sq_h else 0.0
_val_a = squads_mod.squad_value_summary(_sq_a["groups"])["total"] if _sq_a else 0.0
# 复用 FBref 缓存(无网络)：真实 xG/射门 → 升级「射门效率」维度为真实(无缓存则回退 proxy)
_fin_h = fbref_mod.finishing_score(fbref_mod.load_shooting(home))
_fin_a = fbref_mod.finishing_score(fbref_mod.load_shooting(away))
cl = clemente.predict(model, home, away, neutral,
                      fixtures=fixtures, fixture=selected_fixture,
                      group_state=_cl_group_state, tank_risk=tank_risk if use_context else False,
                      home_formation=(_sq_h or {}).get("formation"),
                      away_formation=(_sq_a or {}).get("formation"),
                      squad_value_home=(_val_h or None), squad_value_away=(_val_a or None),
                      finishing_home=_fin_h, finishing_away=_fin_a)
# 战略分析回灌：根据出线形势/R32对位/金靴动机/对手实力修正预测（仅小组赛）
_is_knockout_match = selected_fixture and selected_fixture.get("round_number", 0) >= 4
if _is_knockout_match:
    _gsa_data = {"available": False, "text": "淘汰赛无小组赛战略因素"}
else:
    _gsa_data = _build_group_strategic_analysis(model, home, away, selected_fixture, fixtures)
_strat_h, _strat_a, _strat_notes = _strategic_factors(_gsa_data, model, home, away)
_apply_strategic_adjustment(cl, _strat_h, _strat_a, _strat_notes)
mat = cl["matrix"]
lam, mu = cl["exp_goals"]
context_notes = cl["notes"]
effective_tank = cl["tank_risk"]
if auto_group_state is not None and not use_context and auto_note:
    st.info("🎯 末轮战意自动修正(按当前积分形势)：" + auto_note)
markets = derive.summarize(mat)
reason = reasoning.generate_reason(model, home, away, neutral, markets, use_llm=False)
x, odds = markets["1x2"], markets["1x2_fair_odds"]

if context_notes:
    st.info("🎯 组合模型调整：" + "；".join(context_notes))

_conf_color = {"高": "#10b981", "中": "#f59e0b", "低": "#ef4444"}[cl["confidence"]]
_bl, _bm = cl["base_exp_goals"]
st.markdown(
    f'<div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:2px 0 8px;">'
    f'<span style="font-weight:700;color:{_conf_color};">置信度 {cl["confidence"]}</span>'
    f'<span style="color:var(--wc-muted);font-size:13px;">数据完整度 {cl["data_quality"]:.0%}</span>'
    f'<span style="color:var(--wc-muted);font-size:13px;">基线 λ {_bl:.2f}:{_bm:.2f} → 组合 λ {lam:.2f}:{mu:.2f}</span>'
    f'</div>', unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{zh(home)} 胜", f"{x['home']:.1%}", f"公平赔率 {odds['home']:.2f}")
c2.metric("平局", f"{x['draw']:.1%}", f"公平赔率 {odds['draw']:.2f}")
c3.metric(f"{zh(away)} 胜", f"{x['away']:.1%}", f"公平赔率 {odds['away']:.2f}")
c4.metric("组合模型预期进球", f"{lam:.2f} : {mu:.2f}")
st.caption(f"预测主链：克莱门特组合模型（九维加权 + 有界软信号，调整夹紧 ±15%；赔率不参与，仅在下方做后验校验）。"
           f"模型文件最近更新 {model_updated_label()}。")

env_report = match_environment_report(home, away, mat, fixture=selected_fixture)
from wc2026.analysis import dimensions as _dims
from wc2026.analysis import goal_strategy
from wc2026.analysis import intelligence as _intel
prof9 = cl["dimensions"]
_report = _intel.build_report(model, home, away, neutral, fixture=selected_fixture,
                              fixtures=fixtures, group_state=_cl_group_state, pred=cl)
gs = goal_strategy.recommend(mat, lam, mu)

section_title("本场决策摘要")
_outcome_labels = {"home": f"{zh(home)}胜", "draw": "平局", "away": f"{zh(away)}胜"}
_main_outcome = max(x, key=x.get)
_top_score = markets["correct_score_top"][0]
_ou25 = markets["over_under"]["2.5"]
_btts = markets["btts"]
dc1, dc2, dc3, dc4 = st.columns(4)
dc1.metric("90 分钟主方向", _outcome_labels[_main_outcome], f"模型 {x[_main_outcome]:.1%}")
dc2.metric("首选比分", _top_score["score"], f"单点概率 {_top_score['prob']:.1%}")
dc3.metric("总进球 2.5", "大" if _ou25["over"] >= _ou25["under"] else "小",
           f"{max(_ou25['over'], _ou25['under']):.1%}")
dc4.metric("双方进球", "是" if _btts["yes"] >= _btts["no"] else "否",
           f"{max(_btts.values()):.1%}")
st.info(_report["summary"]["text"])
st.caption("决策摘要仅压缩模型与结构化证据，不把赔率或新闻标题直接写入基础概率。下方保留可核验的模型、对位和风险细节。")
if _is_knockout_match:
    from wc2026.analysis import knockout_analysis as _knockout
    _ko = _knockout.build_knockout_payload(mat, lam, mu, home, away)
    st.markdown("**晋级概率（含加时与点球）**")
    ka1, ka2, ka3 = st.columns(3)
    ka1.metric(f"{zh(home)} 晋级", f"{_ko['advance']['home']:.1%}")
    ka2.metric(f"{zh(away)} 晋级", f"{_ko['advance']['away']:.1%}")
    ka3.metric("90 分钟战平", f"{_ko['outcomes_90']['draw']:.1%}", "之后进入加时")
    st.caption(f"加时赛主/平/客 {_ko['extra_time']['home']:.1%} / {_ko['extra_time']['draw']:.1%} / "
               f"{_ko['extra_time']['away']:.1%}；点球基础各 50%，未获得官方首发门将与点球顺序前不做主观加成。")

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
st.caption("爆冷指数衡量「把热门方当稳胆」的风险，不预测弱队一定爆冷；当前只量化胜平负、近期防守和战意。"
           "伤停、海拔、时差与天气在独立风险模块展示，避免重复计权。")

section_title("赛前环境与场地适应性")
env_score = env_report["score_pick"]
ec1, ec2 = st.columns([1, 3])
with ec1:
    st.metric("环境参考比分", env_score["score"], f"{env_score['prob']:.1%}", delta_color="off")
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

st.caption("球队适应性")
st.dataframe(pd.DataFrame(env_report["adaptation"]), hide_index=True, width="stretch")
st.caption("说明：该模块只参考可核验的时区、球场、海拔、开球时段天气和旅行信息；天气优先使用 Open-Meteo 缓存，缺失时回退场馆静态气候。")

section_title("九维度能力评分")
_radar_cats = _dims.DIMENSIONS + [_dims.DIMENSIONS[0]]  # 闭合多边形
sc1, sc2 = st.columns([3, 2])
with sc1:
    radar = go.Figure()
    for name, dd, color in [(zh(home), prof9["dims_home"], "#14b8a6"),
                            (zh(away), prof9["dims_away"], "#f59e0b")]:
        radar.add_trace(go.Scatterpolar(
            r=[dd[k] for k in _dims.DIMENSIONS] + [dd[_dims.DIMENSIONS[0]]],
            theta=_radar_cats, fill="toself", name=name, line=dict(color=color)))
    radar.update_layout(
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        height=420, margin=dict(l=40, r=40, t=30, b=30),
        legend=dict(orientation="h", y=-0.12),
        template="plotly_dark" if current_theme() == "dark" else "plotly_white",
        paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(radar, width="stretch")
with sc2:
    sm1, sm2 = st.columns(2)
    sm1.metric(f"{zh(home)} 综合", f"{prof9['score_home']:.0f}")
    sm2.metric(f"{zh(away)} 综合", f"{prof9['score_away']:.0f}")
    _names = [d["name"] for d in prof9["dims"]]
    bar = go.Figure()
    bar.add_trace(go.Bar(y=_names, x=[-d["home"] for d in prof9["dims"]], orientation="h",
                         name=zh(home), marker_color="#14b8a6",
                         customdata=[d["home"] for d in prof9["dims"]],
                         hovertemplate=zh(home) + " %{customdata:.0f}<extra></extra>"))
    bar.add_trace(go.Bar(y=_names, x=[d["away"] for d in prof9["dims"]], orientation="h",
                         name=zh(away), marker_color="#f59e0b",
                         hovertemplate=zh(away) + " %{x:.0f}<extra></extra>"))
    bar.update_layout(barmode="relative", height=360, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis=dict(range=[-100, 100], showticklabels=False),
                      legend=dict(orientation="h", y=-0.15),
                      template="plotly_dark" if current_theme() == "dark" else "plotly_white",
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(bar, width="stretch")
_conf_badge = {"real": "✅真实", "proxy": "🔶代理", "degraded": "⚪降级"}
st.dataframe(pd.DataFrame([
    {"维度": d["name"], "权重": f"{d['weight']:.0%}",
     zh(home): f"{d['home']:.0f}", zh(away): f"{d['away']:.0f}",
     "数据": _conf_badge.get(d["confidence"], d["confidence"]), "来源": d["source"]}
    for d in prof9["dims"]]), hide_index=True, width="stretch")
st.info(prof9["explanation"])
st.caption("九维度按开发需求文档权重加权（近期状态/阵容实力/战术素养/战术匹配/赛事动机/防守组织/历史交锋/外部条件/射门效率）。"
           "🔶代理=用模型系数近似、⚪降级=数据不足按中性处理（不编造）；赔率不作为维度，仅在下方做后验校验。")

section_title("关键对位与破局点")
from wc2026.analysis import matchups as _mu
from wc2026.data import squads as _sqm
_mu_res = _mu.analyze_matchups(
    home, away, exp_goals=(lam, mu),
    sq_home=_sqm.load_fm_squad(home), sq_away=_sqm.load_fm_squad(away),
    score_home=prof9["score_home"], score_away=prof9["score_away"])
_mt1, _mt2 = st.columns(2)
for _col, _t in [(_mt1, _mu_res["home_type"]), (_mt2, _mu_res["away_type"])]:
    _col.markdown(f"**{zh(_t['team'])}** · {_t['type']}")
    _col.caption(_t["reason"])
for _n in _mu_res["notes"]:
    st.markdown(f"- {_n}")
st.caption("对位/破局点为基于阵容身价（FotMob）与模型实力的规则化定性分析；"
           "阵容需先在下方「拉取阵容」后才有破局点，缺失时按模型实力降级。仅供参考、非投注建议。")

_sm = _report["summary"]
with st.expander("结论依据（主结论 / 依据 / 关键变量 / 市场 / 置信度）", expanded=False):
    st.markdown(f"- **主结论**：{_sm['main']}")
    st.markdown(f"- **核心依据**：{_sm['basis']}")
    st.markdown(f"- **关键变量**：{_sm['variables']}")
    st.markdown(f"- **市场验证**：{_sm['market']}")
    st.markdown(f"- **置信度**：{_sm['confidence']}")

section_title("风险提示与关键变量")
_risk_color = {"高": "#ef4444", "中": "#f59e0b", "低": "#9aa7b6"}
for _r in _report["risks"]:
    _c = _risk_color.get(_r["level"], "#9aa7b6")
    st.markdown(
        f'<div style="border-left:3px solid {_c};padding-left:10px;margin:4px 0;">'
        f'<span style="font-weight:700;color:{_c};">[{_r["level"]}] {_r["tag"]}</span>'
        f'<span style="color:var(--wc-muted);"> — {_r["detail"]}</span></div>',
        unsafe_allow_html=True)
st.caption("风险分级：高=可能改变结论或需重算情境；中=影响置信度；低=背景提示。首发/伤停/天气以赛前官方为准、赛前请刷新。")

from wc2026.markets import odds_signals as _osig
_sig = _osig.detect_odds_signals(home, away)
if _sig.get("signals"):
    st.markdown("**赔率走势信号**（市场热度≠真实稳妥）")
    _sig_color = {"高": "#ef4444", "中": "#f59e0b", "低": "#9aa7b6"}
    for _s in _sig["signals"]:
        _sc = _sig_color.get(_s["level"], "#9aa7b6")
        st.markdown(
            f'<div style="border-left:3px solid {_sc};padding-left:10px;margin:4px 0;">'
            f'<span style="font-weight:700;color:{_sc};">[{_s["level"]}] {_s["tag"]}</span>'
            f'<span style="color:var(--wc-muted);"> — {_s["detail"]}</span></div>',
            unsafe_allow_html=True)
    st.caption(_sig["note"])
elif _sig.get("enabled"):
    st.caption("赔率走势：暂无明显矛盾/过热信号（已剔水仅作走势参考）。")

section_title("可视化大屏 Beta")
from wc2026.analysis import dashboard_bridge as _bridge
from wc2026.analysis import match_insights as _match_insights
_bridge_payload = _bridge.build_dashboard_payload(
    model, home, away, neutral,
    fixture=selected_fixture,
    fixtures=fixtures,
    odds_1x2={"home": odds["home"], "draw": odds["draw"], "away": odds["away"]},
    group_state=_cl_group_state,
    pred=cl,
)
_ma = _bridge_payload.get("match_analysis") or {}
if not _ma.get("available"):
    st.warning(_ma.get("text", "分场分析暂无补充数据。"))
if action_button("🌐 联网补全分场分析数据", key=f"refresh_match_insight:{home}:{away}",
                 help="尝试拉取 ESPN 单场统计、FBref 射门/xG、FotMob 阵容/阵型/伤停和新闻，并写入本地缓存"):
    with st.spinner("联网补全分场分析数据…"):
        _mi_res = _match_insights.refresh_match_insight(
            home, away, model=model, fixture=selected_fixture)
        _bridge_payload["match_analysis"] = _match_insights.build_match_analysis(
            home, away, {"prediction": _bridge_payload.get("prediction", {})}
        )
    if _mi_res["ok"]:
        st.success("分场分析数据已补全。")
    else:
        st.warning("已写入可获取的数据；部分来源失败：" + "；".join(_mi_res["errors"][:4]))
    st.cache_data.clear()
    st.cache_resource.clear()
_bridge_payload["group_strategic_analysis"] = _gsa_data
if cl.get("strategic", {}).get("applied"):
    _bridge_payload["prediction"]["strategic"] = cl["strategic"]
with st.expander("打开参考项目风格大屏（HTML / Canvas 桥接版）", expanded=True):
    st.caption("数据来自当前 Python 模型与结构化赛果；人口、最佳成绩等静态资料来自 data/team_profiles.json。")
    render_bridge_dashboard(_bridge_payload)

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

    # 赔率验证（模型 vs 市场 · 文档 5.4 口径）：偏差=模型−市场，阈值 ±8%
    _mc = _intel.market_check(x, {"home": o_home, "draw": o_draw, "away": o_away})
    if _mc["enabled"]:
        _mc_emoji = {"基本一致": "⚪ 基本一致", "潜在价值（模型偏高）": "🟢 潜在价值（模型偏高）",
                     "市场高估": "🔴 市场高估"}
        st.markdown("**📐 赔率验证（模型 vs 市场）**")
        st.dataframe(pd.DataFrame([{
            "市场": it["market"], "赔率": f"{it['odds']:.2f}",
            "模型概率": f"{it['model_prob']:.1%}", "市场隐含(剔水)": f"{it['implied_prob']:.1%}",
            "偏差(模型−市场)": f"{it['diff']:+.1%}", "标签": _mc_emoji.get(it["label"], it["label"]),
        } for it in _mc["items"]]), hide_index=True, width="stretch")
        st.caption(f"水位 overround {_mc['overround']:.3f}。{_mc['note']} 偏差>+8%=模型比市场更看好(潜在价值，需风险复核)；"
                   "<−8%=市场更看好(可能高估)；±8% 内基本一致。")

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
        st.caption("暂无足够历史快照——需在赛前多次拉取本场赔率后才能形成走势。")

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

with st.expander("赛前情报与来源状态", expanded=True):
    news_key = f"news:{home}:{away}"
    if action_button("刷新实时情报（多源并行）", key=f"refresh_news:{home}:{away}"):
        with st.spinner("并行查询官方/权威定向、Google、Yahoo、GDELT、足球 RSS…"):
            st.session_state[news_key] = load_news(home, away)

    cached_news = st.session_state.get(news_key)
    if cached_news:
        items = cached_news["items"]
        _ns = cached_news["summary"]
        _news_time = (cached_news.get("fetched_at") or "").replace("T", " ")[:19]
        nc1, nc2, nc3 = st.columns(3)
        nc1.metric("相关资讯", len(items))
        nc2.metric("可用来源", f"{_ns['available']} / {_ns['total']}")
        nc3.metric("降级来源", _ns["failed"] + _ns["empty"])
        st.caption(f"抓取时间 {_news_time} UTC · 官方/权威 → 聚合 → 网页搜索兜底；单路失败不会中断其他来源。")
        if cached_news["status"] == "partial":
            st.warning("部分实时来源失败，当前结果来自其余可用来源；重要伤停仍需官方二次确认。")
        elif cached_news["status"] == "unavailable":
            st.warning("所有实时来源均无可用结果。当前不使用无关综合头条替代，也不对伤停作硬性推断。")
        with st.expander("查看来源健康明细", expanded=False):
            st.dataframe(pd.DataFrame([{
                "来源": s["provider"], "球队": s["team"], "等级": s["tier"],
                "状态": {"ok": "可用", "empty": "无结果", "failed": "失败"}.get(s["status"], s["status"]),
                "条数": s["count"], "耗时(ms)": s["latency_ms"],
                "错误": s.get("error") or "",
            } for s in cached_news["sources"]]), hide_index=True, width="stretch")
        if items:
            for it in items[:8]:
                _pub = f" · {it['pub']}" if it.get("pub") else ""
                st.markdown(
                    f"- [{it['title']}]({it['link']}) · {it['source_tier']} / {it['source']}{_pub}")
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
            st.caption("暂无可验证的本场资讯。赛前发布会、官方首发与伤停公告仍应在开赛前复核。")
    else:
        st.caption("尚未拉取。本模块按来源等级聚合，并保留抓取时间与失败明细。")

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


with st.expander("🎯 FBref 射门 / xG（升级「射门效率」维度 · 需 cloudscraper）", expanded=False):
    st.caption("FBref 提供真实射门/xG。注意：FBref 对数据中心 IP 常 403，本机/住宅 IP 通常可拉；"
               "拉取后结果缓存、九维「射门效率」自动升级为真实，失败则保持 proxy、不影响其他预测。")
    if action_button("🔄 拉取本场两队 FBref 射门/xG"):
        with st.spinner("从 FBref 拉取射门/xG（限速较慢）…"):
            for _t in (home, away):
                try:
                    _d = fbref_mod.fetch_team_shooting(_t)
                    st.success(f"{zh(_t)}：进球 {_d.get('goals')} · 射门 {_d.get('shots')} · "
                               f"xG {_d.get('xg')} · npxG {_d.get('npxg')}")
                except fbref_mod.FBrefError as exc:
                    st.warning(f"{zh(_t)} 拉取失败：{exc}")
                except Exception as exc:
                    st.warning(f"{zh(_t)} 拉取失败（可能缺 cloudscraper 或被 403）：{str(exc)[:120]}")
        st.rerun()
    _shoot_rows = []
    for _t, _fin in [(home, _fin_h), (away, _fin_a)]:
        _sd = fbref_mod.load_shooting(_t)
        if _sd:
            _shoot_rows.append({"球队": zh(_t), "进球": _sd.get("goals"), "射门": _sd.get("shots"),
                                "射正": _sd.get("sot"), "xG": _sd.get("xg"), "npxG": _sd.get("npxg"),
                                "射门效率分": (f"{_fin:.0f}" if _fin is not None else "—"),
                                "更新": (_sd.get("updated_at") or "")[:10]})
    if _shoot_rows:
        st.dataframe(pd.DataFrame(_shoot_rows), hide_index=True, width="stretch")
        st.caption("射门效率分由 转化率(进球/射门) + (进球−xG)/射门 的射手超预期折算 0-100；已并入上方九维度。")
    else:
        st.caption("尚无本场 FBref 缓存——点上方按钮拉取（结果缓存，再次查看不重复联网）。")


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
            "upset": ui, "strength": prof9, "goal_rec": gs,
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
