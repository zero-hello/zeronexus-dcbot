"""Manus AI Native REST Adapter.

Supports autonomous task execution and reasoning via the official Manus API endpoint:
https://api.manus.ai/v1/chat/completions
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.core.config import config
from zeronexus.security.sanitizer import redact_secrets

log = logging.getLogger("zeronexus.ai_gateway.adapters.manus")


class ManusAdapter(BaseAIAdapter):
    """Communicates with Manus AI Agent API via httpx."""

    def __init__(self) -> None:
        super().__init__("manus")
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0),
            )
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None

    async def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        model: str,
        api_key: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: float = 60.0,
        images: Optional[List[Dict[str, Any]]] = None,
        allow_fallback: bool = True,
        disable_safety: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_executor: Optional[Any] = None,
        max_tool_rounds: int = 3,
        **kwargs: Any,
    ) -> AIResult:
        start_time = time.perf_counter()
        client = await self._get_client(timeout)

        raw_base = getattr(config.ai, "manus_base_url", "https://api.manus.ai/v1").strip().rstrip("/")
        if not raw_base.endswith("/v1"):
            raw_base = f"{raw_base}/v1"
        endpoint = f"{raw_base}/chat/completions"

        # Manus 雙重認證 Header 支持 (x-manus-api-key 與 Bearer Token)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "x-manus-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "ZeroNexus/1.6 (Autonomous Agent System)",
        }

        formatted_messages: List[Dict[str, Any]] = []
        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})

        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if i == len(messages) - 1 and images:
                # 視覺附件整合
                content_parts: List[Dict[str, Any]] = [{"type": "text", "text": str(content)}]
                for img in images:
                    mime = img.get("mime_type", "image/png")
                    data = img.get("data", "")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"}
                    })
                formatted_messages.append({"role": role, "content": content_parts})
            else:
                formatted_messages.append({"role": role, "content": str(content)})

        target_model = model or getattr(config.ai, "manus_model", "manus") or "manus"
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": formatted_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        max_retries = 2
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                response = await client.post(endpoint, headers=headers, json=payload)
                if response.status_code in (429, 503) and attempt < max_retries:
                    backoff = (1.0 * (2 ** attempt)) + random.uniform(0.1, 0.5)
                    log.warning(f"Manus API HTTP {response.status_code}. Retrying in {backoff:.2f}s...")
                    await asyncio.sleep(backoff)
                    continue

                if response.status_code != 200:
                    err_body = response.text[:300]
                    raise RuntimeError(f"Manus API Error (HTTP {response.status_code}): {redact_secrets(err_body)}")

                data = response.json()
                choices = data.get("choices", [])
                if not choices:
                    raise RuntimeError("Manus API returned empty choices array")

                choice = choices[0]
                message = choice.get("message", {})
                text_content = message.get("content") or ""

                # 提取思維鏈推理內容 (Chain of Thought / Reasoning)
                reasoning = (
                    message.get("reasoning_content")
                    or message.get("thought")
                    or data.get("thinking")
                    or None
                )

                tool_calls = message.get("tool_calls")
                usage = data.get("usage", {})
                prompt_tokens = usage.get("prompt_tokens", 0)
                completion_tokens = usage.get("completion_tokens", 0)
                total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

                latency = (time.perf_counter() - start_time) * 1000

                return AIResult(
                    text=text_content,
                    model_name=target_model,
                    provider="manus",
                    latency_ms=latency,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    is_fallback=False,
                    tool_calls=tool_calls,
                    thinking_process=reasoning,
                    raw_response=data,
                )

            except Exception as e:
                last_error = e
                if attempt < max_retries and ("timeout" in str(e).lower() or "connect" in str(e).lower()):
                    await asyncio.sleep(1.0)
                    continue
                break

        raise last_error or RuntimeError("Manus API inference failed with unknown error")
