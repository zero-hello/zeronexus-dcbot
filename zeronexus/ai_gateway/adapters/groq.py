"""Groq LPU 原生 REST 適配器 (Groq Native REST Adapter)。

支援透過 Groq 官方 OpenAI 相容端點進行極速低延遲生成與推理思考：
端點：https://api.groq.com/openai/v1/chat/completions
主力模型：llama-3.3-70b-versatile, deepseek-r1-distill-llama-70b, llama-3.1-8b-instant
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.security.sanitizer import redact_secrets

log = logging.getLogger("zeronexus.ai_gateway.adapters.groq")


class GroqAdapter(BaseAIAdapter):
    """透過 HTTP REST API 與 Groq 極速 LPU 端點通訊。"""

    def __init__(self) -> None:
        super().__init__("groq")
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
        """呼叫 Groq Chat Completions API 產生對話回覆。"""
        start_time = time.perf_counter()
        client = await self._get_client(timeout)

        endpoint = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ZeroNexus-Bot/1.9.0",
        }

        # 標準化模型識別碼
        target_model = model or "llama-3.3-70b-versatile"
        if target_model.startswith("groq/"):
            target_model = target_model.replace("groq/", "")

        formatted_messages: List[Dict[str, Any]] = []
        if system_instruction:
            sys_clean = system_instruction.strip()
            # 針對 Groq 每分鐘 7,000 輸入 Token 嚴格防護限制進行智慧壓縮提煉
            if len(sys_clean) > 2600:
                sys_clean = sys_clean[:2600] + "\n...(以下設定已智慧提煉，請保持活潑、可愛且聰明的態度，並嚴格使用道地臺灣繁體中文回應)"
            formatted_messages.append({"role": "system", "content": sys_clean})

        # 僅保留最近 8 則訊息，避免歷史對話過長導致 413 超限
        recent_messages = messages[-8:] if len(messages) > 8 else messages

        for i, msg in enumerate(recent_messages):
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

            # 若歷史長文過長亦做安全上限保護
            if len(content_str) > 1500:
                content_str = content_str[:1500] + "..."

            if i == len(recent_messages) - 1 and images:
                content_str += " [備註：使用者附加了圖片，若需檢視圖片請使用多模態視覺模型]"

            role = msg.get("role", "user")
            if role in ("bot", "model"):
                role = "assistant"
            elif role not in ("system", "user", "assistant"):
                role = "user"

            formatted_messages.append({"role": role, "content": content_str})

        # 對於 DeepSeek R1 Distill 推理模型，官方推薦適度微調溫度以取得最佳思維表現
        adjusted_temperature = temperature
        if "deepseek-r1" in target_model.lower() and temperature > 0.65:
            adjusted_temperature = 0.6

        payload = {
            "model": target_model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": adjusted_temperature,
        }

        response = await client.post(endpoint, headers=headers, json=payload, timeout=timeout)
        latency_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code != 200:
            err_text = redact_secrets(response.text[:300])
            raise RuntimeError(f"Groq API Error (HTTP {response.status_code}): {err_text}")

        try:
            data = response.json()
        except Exception as json_err:
            raise ValueError(f"Groq API 回傳非有效 JSON 格式: {json_err}")

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("Groq API 回傳之 choices 為空。")

        msg_obj = choices[0].get("message") or {}
        text_result = msg_obj.get("content") or ""

        # 提取思維鏈 (Thinking / Reasoning)
        thinking_process: Optional[str] = (
            msg_obj.get("reasoning")
            or msg_obj.get("reasoning_content")
            or choices[0].get("reasoning")
        )

        # 若模型將思考過程放在 <think>...</think> 區塊中，予以萃取
        if not thinking_process and "<think>" in text_result:
            match = re.search(r"<think>(.*?)</think>", text_result, re.DOTALL)
            if match:
                thinking_process = match.group(1).strip()
                text_result = re.sub(r"<think>.*?</think>", "", text_result, flags=re.DOTALL).strip()

        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        real_model = data.get("model") or target_model

        return AIResult(
            text=text_result,
            model_name=real_model,
            provider="groq",
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            requested_model=model,
            thinking_process=thinking_process,
        )
