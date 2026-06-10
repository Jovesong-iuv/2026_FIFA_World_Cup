"""国际赛历史结果数据源：martj42/international_results（1872→今，免费）。"""
from __future__ import annotations

import io

import pandas as pd
import requests

from wc2026.config import settings

_COLUMNS = [
    "date", "home_team", "away_team", "home_score", "away_score",
    "tournament", "city", "country", "neutral", "is_competitive",
]


def _is_competitive(tournament: object) -> int:
    """友谊赛信号弱，单独标记；其余(世界杯/预选/洲际杯/国家联赛等)视为正式赛。"""
    if not isinstance(tournament, str) or not tournament.strip():
        return 0
    return 0 if tournament.strip().lower() == "friendly" else 1


def fetch_results() -> pd.DataFrame:
    """下载并清洗历史结果，返回带 is_competitive 标记的 DataFrame。"""
    url = f"{settings.intl_results_base}/results.csv"
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))

    df = df.dropna(subset=["home_score", "away_score"]).copy()
    df["home_score"] = df["home_score"].astype(int)
    df["away_score"] = df["away_score"].astype(int)
    df["neutral"] = (
        df["neutral"].astype(str).str.strip().str.upper().isin({"TRUE", "1"}).astype(int)
    )
    df["is_competitive"] = df["tournament"].apply(_is_competitive)
    for col in ("tournament", "city", "country"):
        if col in df:
            df[col] = df[col].astype(str)
    return df[_COLUMNS]
