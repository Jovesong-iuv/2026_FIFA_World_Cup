"""统一 LLM Provider 接口（可插拔）。

第一版走 Anthropic /v1/messages 格式（兼容 anyrouter 等中转）。
任何失败都抛 LLMError，由上层（reasoning）决定降级，绝不影响核心预测。
后续接 OpenAI 兼容模型(MiMo/DeepSeek)时在此扩展分支即可。
"""
from __future__ import annotations

import httpx

from wc2026.config import settings


class LLMError(Exception):
    pass


def chat(prompt: str, system: str | None = None,
         max_tokens: int = 800, temperature: float = 0.4,
         timeout: float | None = None) -> str:
    if not settings.llm_enabled:
        raise LLMError("LLM 未启用 (LLM_ENABLED=false)")
    if not settings.llm_api_key:
        raise LLMError("缺少 LLM_API_KEY")
    if settings.llm_provider == "anthropic":
        return _anthropic_chat(prompt, system, max_tokens, temperature, timeout)
    if settings.llm_provider == "openai":
        return _openai_chat(prompt, system, max_tokens, temperature, timeout)
    raise LLMError(f"未知 provider: {settings.llm_provider}")


def _anthropic_chat(prompt: str, system: str | None,
                    max_tokens: int, temperature: float,
                    timeout: float | None = None) -> str:
    url = settings.llm_base_url.rstrip("/") + "/v1/messages"
    headers = {
        "x-api-key": settings.llm_api_key,
        "Authorization": f"Bearer {settings.llm_api_key}",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if settings.llm_anthropic_beta:
        headers["anthropic-beta"] = settings.llm_anthropic_beta
    body: dict = {
        "model": settings.llm_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        body["system"] = system

    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=timeout or settings.llm_timeout)
    except Exception as exc:  # 网络层失败
        raise LLMError(f"请求失败: {exc}") from exc

    if resp.status_code != 200:
        raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    try:
        data = resp.json()
    except Exception as exc:
        raise LLMError(f"响应非 JSON: {resp.text[:200]}") from exc

    # 中转可能在 200 里塞 error（如"请启用 1m 上下文"）
    if isinstance(data, dict) and "error" in data and "content" not in data:
        raise LLMError(f"服务返回错误: {str(data['error'])[:200]}")

    # Anthropic 原生格式
    if isinstance(data.get("content"), list):
        text = "".join(p.get("text", "") for p in data["content"] if p.get("type") == "text")
        if text.strip():
            return text.strip()
    # 退化兼容 OpenAI 格式
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        raise LLMError(f"无法解析响应: {str(data)[:200]}") from exc


def _openai_chat(prompt: str, system: str | None,
                 max_tokens: int, temperature: float,
                 timeout: float | None = None) -> str:
    """OpenAI 兼容格式 /v1/chat/completions（适配 DeepSeek / MiMo / 多数中转）。"""
    url = settings.llm_base_url.rstrip("/") + "/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "content-type": "application/json",
    }
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {
        "model": settings.llm_model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=timeout or settings.llm_timeout)
    except Exception as exc:
        raise LLMError(f"请求失败: {exc}") from exc
    if resp.status_code != 200:
        raise LLMError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        data = resp.json()
    except Exception as exc:
        raise LLMError(f"响应非 JSON: {resp.text[:200]}") from exc
    if isinstance(data, dict) and "error" in data and "choices" not in data:
        raise LLMError(f"服务返回错误: {str(data['error'])[:200]}")
    try:
        return data["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        raise LLMError(f"无法解析响应: {str(data)[:200]}") from exc


def is_available() -> bool:
    """轻量探活：用于前端显示 LLM 状态。
    max_tokens 需足够大——部分模型(如 MiMo)会先输出 thinking，过小会令正文为空被误判。"""
    try:
        return bool(chat("Reply with OK", max_tokens=64))
    except LLMError:
        return False
