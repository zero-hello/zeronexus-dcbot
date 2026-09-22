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
        # 模式 1：Manus 官方 API 自然語言對話模式 (v2/task.create + v2/task.listMessages)
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
                user_prompt = "你好！"

            # 構建結構化自然對話上下文 (嚴格避免超過 Manus 5,000 tokens 上限)
            context_blocks: List[str] = []
            if system_instruction:
                sys_clean = system_instruction.strip()
                if len(sys_clean) > 1000:
                    sys_clean = sys_clean[:1000] + "\n...(以下設定省略，請保持活潑、可愛且聰明的態度，並嚴格使用道地繁體中文回應)"
                context_blocks.append(f"【角色設定與系統指示】\n{sys_clean}")

            # 附加前文對話歷史 (最近 2 則，每則上限 300 字元)
            history_lines: List[str] = []
            for msg in messages[:-1]:
                m_role = "使用者" if msg.get("role") == "user" else "ZeroNexus"
                m_content = msg.get("content", "")
                if isinstance(m_content, str) and m_content.strip():
                    clean_content = m_content.strip()
                    if len(clean_content) > 300:
                        clean_content = clean_content[:300] + "..."
                    history_lines.append(f"{m_role}: {clean_content}")
            if history_lines:
                context_blocks.append("【前文對話記錄】\n" + "\n".join(history_lines[-2:]))

            clean_user_prompt = user_prompt.strip()
            if len(clean_user_prompt) > 800:
                clean_user_prompt = clean_user_prompt[:800] + "..."
            context_blocks.append(f"【使用者最新訊息】\n{clean_user_prompt}")
            context_blocks.append("請以道地繁體中文自然流暢、生動有趣地直接回應使用者。")
            full_prompt = "\n\n".join(context_blocks)
            if len(full_prompt) > 2200:
                full_prompt = full_prompt[:2200]

            target_model = getattr(config.ai, "manus_model", "") or model or "manus-1.6-lite"
            if "max" in target_model.lower():
                agent_profile = "max"
            elif "standard" in target_model.lower():
                agent_profile = "standard"
            else:
                agent_profile = "lite"

            endpoint = "https://api.manus.ai/v2/task.create"
            headers = {
                "x-manus-api-key": api_key,
                "API_KEY": api_key,
                "Content-Type": "application/json",
                "User-Agent": "ZeroNexus/1.8.0 (Natural Chat Protocol)",
            }
            payload = {
                "message": {"content": full_prompt},
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
                    if not task_id:
                        raise RuntimeError("Manus API did not return a valid task_id")

                    # 輪詢等待對話回覆 (上限 45 秒)
                    poll_url = "https://api.manus.ai/v2/task.listMessages"
                    poll_start = time.perf_counter()
                    final_answer = ""
                    thinking_steps: List[str] = []

                    while (time.perf_counter() - poll_start) < min(timeout, 45.0):
                        await asyncio.sleep(1.5)
                        try:
                            poll_resp = await client.get(
                                poll_url,
                                headers=headers,
                                params={"task_id": task_id},
                            )
                            if poll_resp.status_code == 200:
                                p_data = poll_resp.json()
                                msgs = p_data.get("messages", [])
                                is_stopped = False
                                for m in msgs:
                                    m_type = m.get("type")
                                    if m_type == "status_update":
                                        st_info = m.get("status_update", {})
                                        st_status = st_info.get("agent_status")
                                        brief = st_info.get("brief") or st_info.get("description")
                                        if brief and brief not in thinking_steps:
                                            thinking_steps.append(brief)
                                        if st_status in ("stopped", "completed"):
                                            is_stopped = True
                                        elif st_status in ("failed", "error"):
                                            raise RuntimeError(f"Manus task execution failed: {brief}")
                                    elif m_type == "assistant_message":
                                        c = m.get("assistant_message", {}).get("content", "")
                                        if c and isinstance(c, str):
                                            final_answer = c.strip()

                                if final_answer and is_stopped:
                                    break
                        except Exception as poll_e:
                            if "failed" in str(poll_e):
                                raise poll_e
                            log.debug(f"Manus poll non-fatal error: {poll_e}")

                    if not final_answer:
                        raise RuntimeError("Manus API timed out waiting for natural language dialogue response")

                    latency = (time.perf_counter() - start_time) * 1000
                    thinking_str = "\n".join(thinking_steps) if thinking_steps else None

                    ret_model = model if (model and "manus" in model.lower()) else f"manus-{agent_profile}"
                    return AIResult(
                        text=final_answer,
                        model_name=ret_model,
                        provider="manus",
                        latency_ms=latency,
                        prompt_tokens=len(full_prompt) // 4,
                        completion_tokens=len(final_answer) // 4,
                        is_fallback=False,
                        thinking_process=thinking_str,
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
