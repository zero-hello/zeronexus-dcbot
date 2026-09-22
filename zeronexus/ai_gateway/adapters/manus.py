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
        is_official = ("api.manus.ai" in raw_base) or ("api.manus.im" in raw_base)

        # ---------------------------------------------------------------------
        # 模式 1：Manus 官方非同步自主 Agent API (https://api.manus.ai/v1/tasks)
        # ---------------------------------------------------------------------
        if is_official:
            user_prompt = ""
            for m in reversed(messages):
                if m.get("role") == "user":
                    c = m.get("content", "")
                    if isinstance(c, list):
                        texts = [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text"]
                        user_prompt = " ".join(texts)
                    else:
                        user_prompt = str(c)
                    break
            if not user_prompt:
                user_prompt = "請協助處理任務"

            target_model = getattr(config.ai, "manus_model", "") or model or "manus-1.6-lite"
            if "max" in target_model.lower():
                agent_profile = "manus-2.0-max"
            elif "standard" in target_model.lower():
                agent_profile = "manus-1.6"
            else:
                agent_profile = "manus-1.6-lite"

            endpoint = "https://api.manus.ai/v1/tasks"
            headers = {
                "API_KEY": api_key,
                "x-manus-api-key": api_key,
                "Content-Type": "application/json",
                "User-Agent": "ZeroNexus/1.7.1 (Autonomous Agent System)",
            }
            payload = {
                "prompt": user_prompt,
                "agent_profile": agent_profile,
            }

            max_retries = 2
            last_error: Optional[Exception] = None

            for attempt in range(max_retries + 1):
                try:
                    response = await client.post(endpoint, headers=headers, json=payload)
                    if response.status_code in (429, 503) and attempt < max_retries:
                        backoff = (1.0 * (2 ** attempt)) + random.uniform(0.1, 0.5)
                        log.warning(f"Manus Official API HTTP {response.status_code}. Retrying in {backoff:.2f}s...")
                        await asyncio.sleep(backoff)
                        continue

                    if response.status_code != 200:
                        err_body = response.text[:300]
                        raise RuntimeError(f"Manus API Error (HTTP {response.status_code}): {redact_secrets(err_body)}")

                    data = response.json()
                    task_id = data.get("task_id", "")
                    task_title = data.get("task_title", "Manus 自主任務")
                    task_url = data.get("task_url", f"https://manus.im/app/{task_id}")

                    # 短暫輪詢等待 Agent 第一輪結果 (至多等待 3 秒)
                    final_answer = ""
                    if task_id:
                        for _ in range(2):
                            await asyncio.sleep(1.5)
                            try:
                                poll_resp = await client.get(
                                    f"https://api.manus.ai/v1/tasks/{task_id}",
                                    headers=headers,
                                )
                                if poll_resp.status_code == 200:
                                    task_data = poll_resp.json()
                                    outputs = task_data.get("output", [])
                                    for item in outputs:
                                        if item.get("role") == "assistant":
                                            for part in item.get("content", []):
                                                if part.get("type") in ("output_text", "text"):
                                                    final_answer = part.get("text", "")
                                    if final_answer:
                                        break
                            except Exception as poll_e:
                                log.debug(f"Manus poll error (non-fatal): {poll_e}")
                                break

                    # 若已取得具體回答則呈現回答；若任務仍在非同步運作則呈現精美任務看板
                    if final_answer:
                        text_content = (
                            f"{final_answer}\n\n"
                            f"🌐 [在 Manus 雲端檢視完整執行紀錄]({task_url})"
                        )
                    else:
                        text_content = (
                            f"🤖 **Manus AI 自主 Agent 任務已啟動！**\n\n"
                            f"• **任務名稱**：`{task_title}`\n"
                            f"• **執行規格**：`{agent_profile}`（自主雲端工作站）\n"
                            f"• **任務追蹤連結**：<{task_url}>\n\n"
                            f"✨ Manus 正在雲端專屬虛擬環境中全自動執行中，您可以點擊上方連結即時查看 Agent 的瀏覽器操作與生成報告！"
                        )

                    latency = (time.perf_counter() - start_time) * 1000
                    return AIResult(
                        text=text_content,
                        model_name=agent_profile,
                        provider="manus",
                        latency_ms=latency,
                        prompt_tokens=len(user_prompt) // 4,
                        completion_tokens=len(text_content) // 4,
                        is_fallback=False,
                        thinking_process=f"已成功為您在 Manus 雲端建立專屬 Agent 任務【{task_title}】，正在調度虛擬環境與瀏覽器推演...",
                        raw_response=data,
                    )
                except Exception as e:
                    last_error = e
                    log.warning(f"Manus Official API attempt {attempt} failed: {e}")
                    if attempt == max_retries:
                        raise last_error

        # ---------------------------------------------------------------------
        # 模式 2：第三方中轉站 / 自訂反代 (OpenAI-compatible /chat/completions)
        # ---------------------------------------------------------------------
        if not raw_base.endswith("/v1"):
            raw_base = f"{raw_base}/v1"
        endpoint = f"{raw_base}/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "x-manus-api-key": api_key,
            "API_KEY": api_key,
            "Content-Type": "application/json",
            "User-Agent": "ZeroNexus/1.7.1 (Autonomous Agent System)",
        }

        formatted_messages: List[Dict[str, Any]] = []
        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})

        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if i == len(messages) - 1 and images:
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

        target_model = getattr(config.ai, "manus_model", "") or model or "manus"
        payload = {
            "model": target_model,
            "messages": formatted_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        max_retries = 2
        last_error = None

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

                reasoning = (
                    message.get("reasoning_content")
                    or message.get("thought")
                    or data.get("thinking")
                    or None
                )

                tool_calls: List[Dict[str, Any]] = []
                raw_tool_calls = message.get("tool_calls", [])
                if raw_tool_calls:
                    for tc in raw_tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args_raw = fn.get("arguments", "{}")
                        try:
                            fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
                        except Exception:
                            fn_args = {"raw": fn_args_raw}
                        tool_calls.append({"name": fn_name, "args": fn_args, "id": tc.get("id")})

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
                    tool_calls=tool_calls if tool_calls else None,
                    thinking_process=reasoning,
                    raw_response=data,
                )
            except Exception as e:
                last_error = e
                log.warning(f"Manus API attempt {attempt} failed: {e}")
                if attempt < max_retries and ("timeout" in str(e).lower() or "connect" in str(e).lower()):
                    await asyncio.sleep(1.0)
                    continue
                break

        raise last_error or RuntimeError("Manus API inference failed with unknown error")
