"""集中配置：从 .env 读取，全项目共享一个 settings 实例。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _secret(name: str, default: str = "") -> str:
    """Read Streamlit Cloud secrets as fallback without requiring Streamlit locally."""
    try:
        import streamlit as st

        return str(st.secrets.get(name, default))
    except Exception:
        return default


def _env_or_secret(name: str, default: str = "") -> str:
    return os.getenv(name) or _secret(name, default)


def _flag(name: str, default: str = "false") -> bool:
    return _env_or_secret(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # 路径
    root: Path = ROOT
    data_dir: Path = ROOT / "data"

    # 数据库（本地 sqlite，迁移时换 DATABASE_URL 即可）
    database_url: str = _env_or_secret("DATABASE_URL", "sqlite:///data/wc2026.db")

    # 数据源
    intl_results_base: str = _env_or_secret(
        "INTL_RESULTS_BASE",
        "https://raw.githubusercontent.com/martj42/international_results/master",
    )

    # LLM（可选增强）
    llm_enabled: bool = _flag("LLM_ENABLED", "true")
    llm_provider: str = _env_or_secret("LLM_PROVIDER", "anthropic")
    llm_base_url: str = _env_or_secret("LLM_BASE_URL", "")
    llm_api_key: str = _env_or_secret("LLM_API_KEY", "")
    llm_model: str = _env_or_secret("LLM_MODEL", "claude-opus-4-8")
    llm_anthropic_beta: str = _env_or_secret("LLM_ANTHROPIC_BETA", "")
    llm_timeout: float = float(_env_or_secret("LLM_TIMEOUT", "45"))

    # 赔率源（The Odds API）
    odds_api_key: str = _env_or_secret("ODDS_API_KEY", "")

    # 所有者口令：设置后仅 URL 带 ?owner=<该值> 进入所有者模式（可拉取/训练/AI）；
    # 其他访问为只读访客。留空则不限制（本机/单人使用时全功能）。
    owner_key: str = _env_or_secret("OWNER_KEY", "")

    # 站点访问口令：设置后，普通网址访问需先输入该口令才能查看（挡住陌生访问）；
    # 管理员仍用 URL ?owner=<OWNER_KEY> 进入，免口令（老方式不变）。留空则不限制。
    access_password: str = _env_or_secret("ACCESS_PASSWORD", "")

    @property
    def sqlite_path(self) -> Path:
        url = self.database_url
        if url.startswith("sqlite:///"):
            p = Path(url[len("sqlite:///") :])
            return p if p.is_absolute() else (self.root / p)
        return self.data_dir / "wc2026.db"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
