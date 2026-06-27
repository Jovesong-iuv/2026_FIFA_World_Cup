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


def search_and_analyze(query: str, analysis_prompt: str,
                       max_search_results: int = 6,
                       max_tokens: int = 600,
                       temperature: float = 0.3,
                       timeout: float = 30) -> dict:
    """联网搜索 + LLM 综合分析。

    先用搜索引擎获取最新信息，再让 LLM 基于搜索结果生成分析。

    Args:
        query: 搜索关键词
        analysis_prompt: 分析指令（告诉 LLM 如何分析搜索结果）
        max_search_results: 最大搜索结果数
        max_tokens: LLM 最大输出 token 数
        temperature: LLM 温度
        timeout: 总超时（秒）

    Returns:
        {
            "text": str,           # LLM 生成的分析文本
            "sources": [str],      # 搜索结果来源
            "search_count": int,   # 搜索结果数量
            "source": "search_llm" | "search_raw",  # LLM 可用时为 search_llm
        }

    Raises:
        LLMError: LLM 不可用且无搜索结果时
    """
    from wc2026.data.sources import web_search as ws

    # 1) 联网搜索
    results = ws.web_search(query, max_results=max_search_results, timeout=min(timeout, 20))

    if not results:
        raise LLMError(f"联网搜索无结果: {query}")

    # 2) 构建搜索结果摘要
    snippets = []
    sources = []
    for r in results:
        title = r.get("title", "")
        snippet = r.get("snippet", "")
        url = r.get("url", "")
        if title:
            snippets.append(f"- {title}\n  {snippet[:200]}")
            sources.append(title[:50])

    search_text = "\n".join(snippets)

    # 3) LLM 综合分析
    full_prompt = (
        f"以下是联网搜索「{query}」的结果：\n\n"
        f"{search_text}\n\n"
        f"{analysis_prompt}\n\n"
        "要求：只基于上述搜索结果，不要编造。信息不足的部分直接说明。"
    )

    try:
        text = chat(full_prompt, max_tokens=max_tokens, temperature=temperature, timeout=timeout)
        return {
            "text": text,
            "sources": sources[:5],
            "search_count": len(results),
            "source": "search_llm",
        }
    except LLMError:
        # LLM 不可用，直接返回搜索摘要
        return {
            "text": "【搜索摘要】\n" + "\n".join(s[:120] for s in snippets[:5]),
            "sources": sources[:5],
            "search_count": len(results),
            "source": "search_raw",
        }
