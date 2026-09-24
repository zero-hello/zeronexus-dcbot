"""OpenRouter Native REST Adapter."""

from __future__ import annotations

import inspect
import json
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.core.config import config
from zeronexus.core.logger import log
from zeronexus.security.sanitizer import redact_secrets

OPENROUTER_STRICT_FREE_MODELS = [
    "openrouter/free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
    "liquid/lfm-2.5-2.6b:free",
    "nvidia/nemotron-3.5-lightning:free",
]


def is_openrouter_model_free(model_id: str) -> bool:
    """Strictly validates whether a model is 100% zero-cost.

    Rules:
    1. Must match 'openrouter/free' or any entry in OPENROUTER_STRICT_FREE_MODELS.
    2. OR contain ':free' suffix/tag.
    3. OR pricing.prompt == 0 and pricing.completion == 0 in model catalog.
    4. Any charged model returns False to eliminate billing risk.
    """
    if not model_id:
        return False
    mid = str(model_id).strip().lower()
    if mid == "openrouter/free" or mid in [m.lower() for m in OPENROUTER_STRICT_FREE_MODELS]:
        return True
    if ":free" in mid:
        return True

    # Check model_catalog
    try:
        from zeronexus.ai_gateway.model_catalog import model_catalog
        for item in getattr(model_catalog, "_all_models", []):
            if item.get("id", "").lower() == mid:
                pricing = item.get("pricing")
                if pricing and isinstance(pricing, dict):
                    p_prompt = float(pricing.get("prompt", 0) or 0)
                    p_comp = float(pricing.get("completion", 0) or 0)
                    if p_prompt == 0 and p_comp == 0:
                        return True
                if item.get("is_free") is True:
                    return True
    except Exception:
        pass

    # Check model_registry
    try:
        from zeronexus.ai_gateway.model_registry import model_registry
        meta = model_registry.get(model_id)
        if meta and meta.is_free and not meta.requires_paid_tier:
            return True
    except Exception:
        pass

    return False


class OpenRouterAdapter(BaseAIAdapter):
    """Communicates with OpenRouter AI Gateway via httpx with explicit model extraction,
    strict zero-cost fallback filtering, and ReAct function calling."""

    def __init__(self) -> None:
        super().__init__("openrouter")
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._http_client is None or getattr(self._http_client, "is_closed", False) is True:
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50, keepalive_expiry=60.0),
            )
        return self._http_client

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
        tool_executor: Optional[Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Any]]] = None,
        max_tool_rounds: int = 3,
        free_only: bool = False,
        **kwargs: Any,
    ) -> AIResult:
        start_time = time.perf_counter()
        client = await self._get_client(timeout)

        endpoint = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://zeronexus.platform",
            "X-Title": "ZeroNexusTest",
            "Content-Type": "application/json",
        }

        # Check if fallback key is active or free_only is requested
        fallback_key_val = getattr(config.ai, "openrouter_fallback_key", "")
        is_fallback_key = bool(
            free_only
            or (api_key and fallback_key_val and api_key == fallback_key_val)
        )

        formatted_messages: List[Dict[str, Any]] = []
        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})

        for i, msg in enumerate(messages):
            role = msg.get("role", "user")
            content_text = str(msg.get("content", ""))
            if i == len(messages) - 1 and images:
                parts: List[Dict[str, Any]] = [{"type": "text", "text": content_text}]
                for img in images:
                    mime = img.get("mime_type", "image/png")
                    b64 = img.get("data", "")
                    parts.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime};base64,{b64}"
                        }
                    })
                formatted_messages.append({"role": role, "content": parts})
            else:
                formatted_messages.append({"role": role, "content": content_text})

        primary_model = model or "google/gemini-2.5-flash"

        # Standardize deepseek models without provider prefix for OpenRouter
        if primary_model.startswith("deepseek-"):
            low_p = primary_model.lower()
            if "r1" in low_p or "reasoner" in low_p:
                primary_model = "deepseek/deepseek-r1"
            elif "v4" in low_p:
                primary_model = "deepseek/deepseek-v4-flash-vision-exp"
            elif "chat" in low_p or "v3" in low_p:
                primary_model = "deepseek/deepseek-chat"
            else:
                primary_model = f"deepseek/{primary_model}"

        # Under fallback key, strictly reject non-free models and switch to free model pool
        if is_fallback_key:
            if not is_openrouter_model_free(primary_model):
                chosen_free = OPENROUTER_STRICT_FREE_MODELS[0]
                log.warning(
                    f"[OpenRouter 0-Cost Guard] Non-free model '{primary_model}' rejected under fallback key. "
                    f"Programmatically switched to 100% zero-cost model '{chosen_free}' to eliminate billing risk."
                )
                primary_model = chosen_free

        # Build candidate models
        if not allow_fallback:
            candidate_models = [primary_model]
        elif is_fallback_key:
            candidate_models = [primary_model]
            for fm in OPENROUTER_STRICT_FREE_MODELS:
                if fm not in candidate_models and len(candidate_models) < 3:
                    candidate_models.append(fm)
            # Strict guarantee: filter out any model that is not free
            candidate_models = [m for m in candidate_models if is_openrouter_model_free(m)]
            if not candidate_models:
                candidate_models = list(OPENROUTER_STRICT_FREE_MODELS[:3])
        else:
            candidate_models = [primary_model]
            pm_lower = primary_model.lower()
            if ":free" in pm_lower or primary_model == "openrouter/free":
                backup_pool = [
                    "openrouter/free",
                    "google/gemma-4-26b-a4b-it:free",
                    "google/gemma-4-31b-it:free",
                ]
            elif "qwen" in pm_lower or "qwq" in pm_lower:
                backup_pool = [
                    "qwen/qwen-2.5-72b-instruct",
                    "qwen/qwen2.5-vl-72b-instruct",
                    "qwen/qwen-plus",
                    "qwen/qwq-32b",
                ]
            elif "deepseek" in pm_lower:
                backup_pool = [
                    "deepseek/deepseek-chat",
                    "deepseek/deepseek-r1",
                    "deepseek/deepseek-v4-flash-vision-exp",
                ]
            else:
                backup_pool = [
                    "google/gemini-2.5-flash",
                    "deepseek/deepseek-chat",
                    "qwen/qwen-2.5-72b-instruct",
                ]
            for bm in backup_pool:
                if bm not in candidate_models and len(candidate_models) < 3:
                    candidate_models.append(bm)

        # Format OpenAPI tools
        formatted_tools: List[Dict[str, Any]] = []
        if tools:
            for t in tools:
                if "type" in t and "function" in t:
                    formatted_tools.append(t)
                elif "name" in t and "parameters" in t:
                    formatted_tools.append({
                        "type": "function",
                        "function": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "parameters": t.get("parameters", {}),
                        },
                    })

        last_error_text = ""
        last_status = 500
        executed_tool_calls: List[Dict[str, Any]] = []

        for candidate in candidate_models:
            # Absolute zero-cost safeguard
            if is_fallback_key and not is_openrouter_model_free(candidate):
                log.error(f"[CRITICAL SAFEGUARD] Blocked charged model '{candidate}' on OpenRouter fallback key.")
                continue

            payload: Dict[str, Any] = {
                "model": candidate,
                "messages": formatted_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "include_reasoning": True,
            }
            if "top_p" in kwargs and kwargs["top_p"] is not None:
                payload["top_p"] = kwargs["top_p"]
            if formatted_tools:
                payload["tools"] = formatted_tools
                payload["tool_choice"] = "auto"

            if disable_safety:
                payload["transforms"] = []
            if allow_fallback and len(candidate_models) > 1:
                # Filter payload models if under fallback key
                if is_fallback_key:
                    payload["models"] = [m for m in candidate_models if is_openrouter_model_free(m)]
                else:
                    payload["models"] = candidate_models

            try:
                response = await client.post(endpoint, headers=headers, json=payload, timeout=timeout)
                # If model does not support tools (HTTP 400), gracefully retry without tools
                if response.status_code == 400 and formatted_tools and "tool" in response.text.lower():
                    log.warning(f"Model {candidate} does not support tools. Retrying without tools parameter...")
                    clean_payload = dict(payload)
                    clean_payload.pop("tools", None)
                    clean_payload.pop("tool_choice", None)
                    response = await client.post(endpoint, headers=headers, json=clean_payload, timeout=timeout)
            except Exception as net_err:
                sanitized_err = redact_secrets(str(net_err))
                log.warning(f"OpenRouter network attempt failed for model {candidate}: {sanitized_err}")
                last_error_text = sanitized_err
                if not allow_fallback:
                    raise RuntimeError(f"OpenRouter network failure for requested model {candidate}: {sanitized_err}")
                continue

            if response.status_code == 200:
                data = response.json()
                if inspect.iscoroutine(data):
                    data = await data
                try:
                    choices = data.get("choices", [])
                    if not choices:
                        raise ValueError("OpenRouter returned empty choices.")

                    msg = choices[0].get("message") or {}
                    current_msg = msg
                    current_data = data
                    loop_messages = list(formatted_messages)
                    round_count = 0

                    # ReAct loop for tool calling (up to max_tool_rounds)
                    while (current_msg.get("tool_calls") or current_msg.get("function_call")) and round_count < max_tool_rounds:
                        round_count += 1
                        loop_messages.append(current_msg)

                        tc_list = current_msg.get("tool_calls")
                        fc = current_msg.get("function_call")

                        if tc_list:
                            for tc in tc_list:
                                if not isinstance(tc, dict):
                                    continue
                                tc_id = tc.get("id", f"call_{round_count}")
                                fn = tc.get("function") or {}
                                fn_name = str(fn.get("name") or "").strip()
                                fn_args_raw = fn.get("arguments", "{}")
                                try:
                                    fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
                                except Exception:
                                    fn_args = {}
                                # 強制保證 fn_args 為 dict，避免模型回傳 list 或其它型別引發 **fn_args TypeError 崩潰
                                if not isinstance(fn_args, dict):
                                    fn_args = {"raw_input": fn_args}

                                if tool_executor:
                                    try:
                                        if inspect.iscoroutinefunction(tool_executor):
                                            tool_res = await tool_executor(fn_name, fn_args)
                                        else:
                                            tool_res = tool_executor(fn_name, fn_args)
                                            if inspect.iscoroutine(tool_res):
                                                tool_res = await tool_res
                                    except Exception as te:
                                        tool_res = {"error": f"Tool execution failed: {te}"}
                                else:
                                    from zeronexus.agent.tools import agent_tools
                                    tool = agent_tools.get_tool(fn_name)
                                    if tool:
                                        try:
                                            exec_fn = tool.execute
                                            if inspect.iscoroutinefunction(exec_fn):
                                                tool_res = await exec_fn(**fn_args)
                                            else:
                                                tool_res = exec_fn(**fn_args)
                                                if inspect.iscoroutine(tool_res):
                                                    tool_res = await tool_res
                                        except Exception as te:
                                            tool_res = {"error": f"Tool '{fn_name}' failed: {te}"}
                                    else:
                                        tool_res = {"error": f"Tool '{fn_name}' not registered."}

                                executed_tool_calls.append({"name": fn_name, "args": fn_args, "result": tool_res})

                                loop_messages.append({
                                    "role": "tool",
                                    "tool_call_id": tc_id,
                                    "name": fn_name,
                                    "content": json.dumps(tool_res, ensure_ascii=False) if not isinstance(tool_res, str) else tool_res,
                                })
                        elif fc and isinstance(fc, dict):
                            fn_name = str(fc.get("name") or "").strip()
                            fn_args_raw = fc.get("arguments", "{}")
                            try:
                                fn_args = json.loads(fn_args_raw) if isinstance(fn_args_raw, str) else fn_args_raw
                            except Exception:
                                fn_args = {}
                            if not isinstance(fn_args, dict):
                                fn_args = {"raw_input": fn_args}
                            log.info(f"[OpenRouter ReAct Round {round_count}] Function called: {fn_name}({fn_args})")

                            if tool_executor:
                                try:
                                    if inspect.iscoroutinefunction(tool_executor):
                                        tool_res = await tool_executor(fn_name, fn_args)
                                    else:
                                        tool_res = tool_executor(fn_name, fn_args)
                                        if inspect.iscoroutine(tool_res):
                                            tool_res = await tool_res
                                except Exception as te:
                                    tool_res = {"error": f"Tool execution failed: {te}"}
                            else:
                                from zeronexus.agent.tools import agent_tools
                                tool = agent_tools.get_tool(fn_name)
                                if tool:
                                    try:
                                        exec_fn = tool.execute
                                        if inspect.iscoroutinefunction(exec_fn):
                                            tool_res = await exec_fn(**fn_args)
                                        else:
                                            tool_res = exec_fn(**fn_args)
                                            if inspect.iscoroutine(tool_res):
                                                tool_res = await tool_res
                                    except Exception as te:
                                        tool_res = {"error": f"Tool '{fn_name}' failed: {te}"}
                                else:
                                    tool_res = {"error": f"Tool '{fn_name}' not registered."}

                            executed_tool_calls.append({"name": fn_name, "args": fn_args, "result": tool_res})

                            loop_messages.append({
                                "role": "function",
                                "name": fn_name,
                                "content": json.dumps(tool_res, ensure_ascii=False) if not isinstance(tool_res, str) else tool_res,
                            })

                        sub_payload = dict(payload)
                        sub_payload["messages"] = loop_messages
                        if round_count >= max_tool_rounds:
                            # Conclude final text answer without further tool calls
                            sub_payload.pop("tools", None)
                            sub_payload.pop("tool_choice", None)

                        sub_resp = await client.post(endpoint, headers=headers, json=sub_payload, timeout=timeout)
                        if sub_resp.status_code != 200:
                            break
                        try:
                            sub_data = sub_resp.json()
                        except Exception:
                            break
                        if inspect.iscoroutine(sub_data):
                            sub_data = await sub_data
                        sub_choices = sub_data.get("choices", [])
                        if not sub_choices:
                            break
                        current_msg = sub_choices[0].get("message") or {}
                        current_data = sub_data

                    text_result = current_msg.get("content", "") or ""
                    native_thinking = (
                        current_msg.get("reasoning_content")
                        or current_msg.get("reasoning")
                        or (choices[0].get("reasoning") if choices else None)
                    )
                    usage = current_data.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens", 0)
                    completion_tokens = usage.get("completion_tokens", 0)
                    real_model = current_data.get("model") or candidate
                    is_fb = (real_model.lower() != primary_model.lower())

                    latency_ms = (time.perf_counter() - start_time) * 1000

                    return AIResult(
                        text=text_result,
                        model_name=real_model,
                        provider="openrouter",
                        latency_ms=round(latency_ms, 2),
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        raw_response=current_data,
                        is_fallback=is_fb,
                        fallback_reason=f"原要求模型 {primary_model} 故障，由 OpenRouter 候選池 {real_model} 接手" if is_fb else None,
                        requested_model=primary_model,
                        tool_calls=executed_tool_calls or None,
                        thinking_process=str(native_thinking).strip() if native_thinking else None,
                    )
                except Exception as e:
                    raise ValueError(f"Failed to parse OpenRouter response: {redact_secrets(str(e))}")

            last_status = response.status_code
            last_error_text = redact_secrets(response.text)

            is_credit_limit = (
                last_status in (402, 403)
                or "credit" in last_error_text.lower()
                or "payment required" in last_error_text.lower()
                or "insufficient credits" in last_error_text.lower()
            )

            if is_credit_limit:
                log.warning(
                    f"OpenRouter model {candidate} hit credit limit (HTTP {last_status}: {last_error_text[:120]}). "
                    f"Smoothly transitioning to OpenRouter free models pool starting with 'openrouter/free'..."
                )
                break

            if not allow_fallback:
                raise RuntimeError(f"OpenRouter API Error (HTTP {last_status}): {last_error_text[:300]}")

            should_failover = (
                last_status in (400, 404, 429, 500, 502, 503, 504) or
                "upstream" in last_error_text.lower() or
                "temporarily rate-limited" in last_error_text.lower() or
                "quota" in last_error_text.lower() or
                "limit exceeded" in last_error_text.lower()
            )

            if should_failover and candidate != candidate_models[-1]:
                log.warning(
                    f"OpenRouter model {candidate} failed (HTTP {last_status}: {last_error_text[:120]}). "
                    f"Failing over to next candidate model in OpenRouter..."
                )
                continue
            else:
                break

        if not allow_fallback and not is_credit_limit:
            raise RuntimeError(f"OpenRouter API Error (HTTP {last_status}): {last_error_text[:300]}")

        # Emergency fallback 1: single-model call to google/gemini-2.5-flash (PAID - strictly prohibited for fallback key or credit limit)
        if not is_fallback_key and candidate_models != ["google/gemini-2.5-flash"] and last_status not in (402, 403) and not is_credit_limit:
            try:
                log.warning("All OpenRouter candidates exhausted. Attempting clean emergency fallback to google/gemini-2.5-flash...")
                em_payload = {
                    "model": "google/gemini-2.5-flash",
                    "messages": formatted_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "include_reasoning": True,
                }
                em_resp = await client.post(endpoint, headers=headers, json=em_payload, timeout=timeout)
                if em_resp.status_code == 200:
                    try:
                        data = em_resp.json()
                    except Exception:
                        data = None
                    if inspect.iscoroutine(data):
                        data = await data
                    choices = (data or {}).get("choices", [])
                    if choices:
                        msg_obj = choices[0].get("message") or {}
                        text_result = msg_obj.get("content") or ""
                        em_thinking = msg_obj.get("reasoning_content") or msg_obj.get("reasoning") or choices[0].get("reasoning")
                        usage = (data or {}).get("usage", {})
                        latency_ms = (time.perf_counter() - start_time) * 1000
                        return AIResult(
                            text=text_result,
                            model_name="google/gemini-2.5-flash",
                            provider="openrouter",
                            latency_ms=round(latency_ms, 2),
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            raw_response=data,
                            is_fallback=True,
                            fallback_reason=f"原要求模型 {primary_model} 額度或連線耗盡，緊急降級至 google/gemini-2.5-flash",
                            requested_model=primary_model,
                            tool_calls=executed_tool_calls or None,
                            thinking_process=str(em_thinking).strip() if em_thinking else None,
                        )
            except Exception as em_err:
                log.error(f"Clean emergency fallback also failed: {redact_secrets(str(em_err))}")

        # Emergency fallback 2: zero-cost fallback to OpenRouter free models (starts with openrouter/free)
        free_fallback_pool = OPENROUTER_STRICT_FREE_MODELS
        for free_model in free_fallback_pool:
            if free_model in candidate_models and not is_credit_limit:
                continue
            try:
                log.warning(f"Attempting zero-cost emergency fallback to OpenRouter free model: {free_model}...")
                free_payload = {
                    "model": free_model,
                    "messages": formatted_messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "include_reasoning": True,
                }
                free_resp = await client.post(endpoint, headers=headers, json=free_payload, timeout=timeout)
                if free_resp.status_code == 200:
                    try:
                        data = free_resp.json()
                    except Exception:
                        data = None
                    if inspect.iscoroutine(data):
                        data = await data
                    choices = (data or {}).get("choices", [])
                    if choices:
                        msg_obj = choices[0].get("message") or {}
                        text_result = msg_obj.get("content") or ""
                        free_thinking = msg_obj.get("reasoning_content") or msg_obj.get("reasoning") or choices[0].get("reasoning")
                        usage = (data or {}).get("usage", {})
                        latency_ms = (time.perf_counter() - start_time) * 1000
                        log.info(f"OpenRouter free-tier fallback succeeded with {free_model}.")
                        return AIResult(
                            text=text_result,
                            model_name=free_model,
                            provider="openrouter",
                            latency_ms=round(latency_ms, 2),
                            prompt_tokens=usage.get("prompt_tokens", 0),
                            completion_tokens=usage.get("completion_tokens", 0),
                            raw_response=data,
                            is_fallback=True,
                            fallback_reason=f"付費配額已耗盡 (HTTP {last_status})，已自動切換至零成本免費模型 {free_model}",
                            requested_model=primary_model,
                            tool_calls=executed_tool_calls or None,
                            thinking_process=str(free_thinking).strip() if free_thinking else None,
                        )
            except Exception as free_err:
                log.error(f"Free-tier fallback {free_model} failed: {redact_secrets(str(free_err))}")

        raise RuntimeError(f"OpenRouter API Error (HTTP {last_status}): {last_error_text[:300]}")

