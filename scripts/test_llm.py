"""LLM 连通性自测。改完 .env 后运行： python scripts/test_llm.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wc2026.config import settings
from wc2026.llm import provider


def main() -> None:
    key = settings.llm_api_key
    print("当前 LLM 配置：")
    print(f"  provider = {settings.llm_provider}")
    print(f"  base_url = {settings.llm_base_url}")
    print(f"  model    = {settings.llm_model}")
    print(f"  beta     = {settings.llm_anthropic_beta or '(无)'}")
    print(f"  key      = ...{key[-4:] if key else '(空)'}")
    print("-" * 40)
    try:
        text = provider.chat("请只回复两个字符：OK", max_tokens=20)
        print("响应:", text)
        print("✅ LLM 可用，理由/资讯分析将自动启用。")
    except provider.LLMError as exc:
        print("❌ 不可用：", exc)
        print("排查：1) 确认 DeepSeek API key 有效且账号余额充足；")
        print("      2) 确认 .env 使用 LLM_PROVIDER=openai、LLM_BASE_URL=https://api.deepseek.com、")
        print("         LLM_MODEL=deepseek-v4-flash、LLM_API_KEY=对应 key。")


if __name__ == "__main__":
    main()
