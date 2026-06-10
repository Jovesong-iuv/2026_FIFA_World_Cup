"""集中配置：从 .env 读取，全项目共享一个 settings 实例。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _flag(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # 路径
    root: Path = ROOT
    data_dir: Path = ROOT / "data"

    # 数据库（本地 sqlite，迁移时换 DATABASE_URL 即可）
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/wc2026.db")

    # 数据源
    intl_results_base: str = os.getenv(
        "INTL_RESULTS_BASE",
        "https://raw.githubusercontent.com/martj42/international_results/master",
    )

    # LLM（可选增强）
    llm_enabled: bool = _flag("LLM_ENABLED", "true")
    llm_provider: str = os.getenv("LLM_PROVIDER", "anthropic")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "claude-opus-4-8")
    llm_anthropic_beta: str = os.getenv("LLM_ANTHROPIC_BETA", "")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "45"))

    # 赔率源（The Odds API）
    odds_api_key: str = os.getenv("ODDS_API_KEY", "")

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
