"""Mistral AI 原生 REST 適配器 (Mistral AI Native REST Adapter)。

支援透過 Mistral AI 官方端點進行高智慧、多語言對話與程式碼生成：
端點：https://api.mistral.ai/v1/chat/completions
主力模型：mistral-large-latest, mistral-small-latest, codestral-latest, pixtral-12b-2409
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.security.sanitizer import redact_secrets

log = logging.getLogger("zeronexus.ai_gateway.adapters.mistral")


class MistralAdapter(BaseAIAdapter):
    """透過 HTTP REST API 與 Mistral AI 官方端點通訊。"""

    def __init__(self) -> None:
        super().__init__("mistral")
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0),
            )
        return self._http_client

    async def close(self) -> None:
        """關閉底層 HTTP 用戶端連線。"""
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
        **kwargs: Any,
    ) -> AIResult:
        """呼叫 Mistral AI Chat Completions API 產生對話回覆。"""
        start_time = time.perf_counter()
        client = await self._get_client(timeout)

        endpoint = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ZeroNexus-Bot/1.9.0",
        }

        # 標準化模型識別碼
        target_model = model or "mistral-large-latest"
        if target_model.startswith("mistral/"):
            target_model = target_model.replace("mistral/", "")

        formatted_messages: List[Dict[str, Any]] = []
        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})

        for i, msg in enumerate(messages):
            raw_content = msg.get("content", "")
            if isinstance(raw_content, list):
                text_parts = [
                    p.get("text", "")
                    for p in raw_content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content_str = " ".join(text_parts)
            else:
                content_str = str(raw_content)

            if i == len(messages) - 1 and images:
                content_str += " [備註：使用者附加了圖片，若需檢視圖片請使用多模態視覺模型 Pixtral]"

            role = msg.get("role", "user")
            if role in ("bot", "model"):
                role = "assistant"
            elif role not in ("system", "user", "assistant"):
                role = "user"

            formatted_messages.append({"role": role, "content": content_str})

        payload = {
            "model": target_model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        response = await client.post(endpoint, headers=headers, json=payload, timeout=timeout)
        latency_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code != 200:
            err_text = redact_secrets(response.text[:300])
            raise RuntimeError(f"Mistral AI API Error (HTTP {response.status_code}): {err_text}")

        try:
            data = response.json()
        except Exception as json_err:
            raise ValueError(f"Mistral AI 回傳非有效 JSON 格式: {json_err}")

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("Mistral AI 回傳之 choices 為空。")

        msg_obj = choices[0].get("message") or {}
        text_result = msg_obj.get("content") or ""

        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        real_model = data.get("model") or target_model

        return AIResult(
            text=text_result,
            model_name=real_model,
            provider="mistral",
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            requested_model=model,
        )
