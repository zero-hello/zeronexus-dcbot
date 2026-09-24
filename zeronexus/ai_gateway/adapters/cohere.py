"""Cohere 原生 REST 適配器 (Cohere Native REST Adapter)。

支援透過 Cohere 官方 v2/chat 端點進行多語言生成與檢索增強 (RAG) 對話：
端點：https://api.cohere.com/v2/chat
支援模型：command-r-plus-08-2024, command-r-08-2024, command-r7b-12-2024 等。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.security.sanitizer import redact_secrets

log = logging.getLogger("zeronexus.ai_gateway.adapters.cohere")


class CohereAdapter(BaseAIAdapter):
    """透過 HTTP REST API 與 Cohere v2 Chat 端點通訊。"""

    def __init__(self) -> None:
        super().__init__("cohere")
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
        """呼叫 Cohere v2 Chat API 產生對話回覆。"""
        start_time = time.perf_counter()
        client = await self._get_client(timeout)

        endpoint = "https://api.cohere.com/v2/chat"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ZeroNexus-Bot/1.9.0",
        }

        # 標準化模型識別碼
        target_model = model or "command-r-plus-08-2024"
        if target_model.startswith("cohere/"):
            target_model = target_model.replace("cohere/", "")

        model_lower = target_model.lower()
        if model_lower in ("command-r-plus", "command-r+", "c-r+"):
            target_model = "command-r-plus-08-2024"
        elif model_lower in ("command-r", "c-r"):
            target_model = "command-r-08-2024"

        # 組裝 Cohere v2 Chat 訊息格式
        formatted_messages: List[Dict[str, Any]] = []
        if system_instruction:
            sys_clean = system_instruction.strip()
            if len(sys_clean) > 3500:
                sys_clean = sys_clean[:3500] + "\n...(以下設定已智慧精簡，請保持活潑開朗且聰明的態度，並嚴格使用道地臺灣繁體中文回應)"
            formatted_messages.append({"role": "system", "content": sys_clean})

        for i, msg in enumerate(messages):
            raw_content = msg.get("content", "")
            if isinstance(raw_content, list):
                # 提取多部件文字
                text_parts = [
                    p.get("text", "")
                    for p in raw_content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                content_str = " ".join(text_parts)
            else:
                content_str = str(raw_content)

            # 若附帶圖片但模型不支援多模態時加上提示
            if i == len(messages) - 1 and images:
                content_str += " [備註：使用者上傳了圖片，若需檢視圖片請切換為多模態視覺模型]"

            role = msg.get("role", "user")
            # Cohere 支援 system, user, assistant
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
        top_p_val = kwargs.get("p") if "p" in kwargs else kwargs.get("top_p")
        if top_p_val is not None:
            payload["p"] = top_p_val

        response = await client.post(endpoint, headers=headers, json=payload, timeout=timeout)
        latency_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code != 200:
            err_text = redact_secrets(response.text[:300])
            raise RuntimeError(f"Cohere API Error (HTTP {response.status_code}): {err_text}")

        try:
            data = response.json()
        except Exception as json_err:
            raise ValueError(f"Cohere API 回傳非有效 JSON 格式: {json_err}")

        # 解析 v2/chat 格式：data.message.content (list of {type: 'text', text: '...'})
        text_result = ""
        msg_obj = data.get("message") or {}
        content_field = msg_obj.get("content")

        if isinstance(content_field, list):
            text_chunks = [
                c.get("text", "") for c in content_field if isinstance(c, dict) and c.get("type") == "text"
            ]
            text_result = "".join(text_chunks)
        elif isinstance(content_field, str):
            text_result = content_field
        elif "text" in data:
            # 兼顧部分端點格式
            text_result = data.get("text", "")

        if not text_result:
            raise ValueError("Cohere API 回傳內容為空。")

        # 讀取 Token 使用量
        usage = data.get("usage", {})
        tokens_info = usage.get("tokens", {}) if isinstance(usage, dict) else {}
        prompt_tokens = tokens_info.get("input_tokens", 0)
        completion_tokens = tokens_info.get("output_tokens", 0)

        return AIResult(
            text=text_result,
            model_name=target_model,
            provider="cohere",
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            requested_model=model,
        )
