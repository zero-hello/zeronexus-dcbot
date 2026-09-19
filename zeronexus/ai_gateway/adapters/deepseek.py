"""DeepSeek Native REST Adapter."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.security.sanitizer import redact_secrets


class DeepSeekAdapter(BaseAIAdapter):
    """Communicates with DeepSeek OpenAI-compatible chat API via httpx."""

    def __init__(self) -> None:
        super().__init__("deepseek")
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0),
            )
        return self._http_client

    async def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, str]],
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
        start_time = time.perf_counter()
        client = await self._get_client(timeout)

        endpoint = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        formatted_messages: List[Dict[str, str]] = []
        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})
        
        for i, msg in enumerate(messages):
            content = str(msg.get("content", ""))
            if i == len(messages) - 1 and images:
                content += " [備註：使用者上傳了圖片檔案，若需要解析圖片內容，建議切換支援多模態的 AI 模型]"
            formatted_messages.append({"role": msg.get("role", "user"), "content": content})

        target_model = model or "deepseek-chat"
        if target_model.startswith("deepseek/"):
            target_model = target_model.replace("deepseek/", "")
        if target_model in ("deepseek-r1", "r1"):
            target_model = "deepseek-reasoner"
        elif target_model in ("deepseek-v3", "v3"):
            target_model = "deepseek-chat"

        payload = {
            "model": target_model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        response = await client.post(endpoint, headers=headers, json=payload, timeout=timeout)
        latency_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code != 200:
            raise RuntimeError(f"DeepSeek API Error (HTTP {response.status_code}): {redact_secrets(response.text[:300])}")

        try:
            data = response.json()
        except Exception as json_err:
            raise ValueError(f"DeepSeek returned invalid JSON: {json_err}")

        try:
            choices = data.get("choices", [])
            if not choices:
                raise ValueError("DeepSeek returned empty choices.")
            msg_obj = choices[0].get("message") or {}
            text_result = msg_obj.get("content") or ""
            reasoning = msg_obj.get("reasoning_content") or choices[0].get("reasoning")

            usage = data.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            real_model = data.get("model") or model

            return AIResult(
                text=text_result,
                model_name=real_model,
                provider="deepseek",
                latency_ms=round(latency_ms, 2),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                raw_response=data,
                thinking_process=str(reasoning).strip() if reasoning else None,
            )
        except Exception as e:
            raise ValueError(f"Failed to parse DeepSeek response: {redact_secrets(str(e))}")
