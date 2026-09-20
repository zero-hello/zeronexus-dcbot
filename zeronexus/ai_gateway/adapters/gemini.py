"""Google Gemini Native REST Adapter."""

from __future__ import annotations

import asyncio
import inspect
import json
import random
import time
from typing import Any, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.core.config import config
from zeronexus.core.logger import log
from zeronexus.security.sanitizer import redact_secrets


def _sanitize_for_json(val: Any) -> Any:
    """Recursively converts objects to JSON-serializable primitives."""
    if isinstance(val, (str, int, float, bool)) or val is None:
        return val
    if isinstance(val, dict):
        return {str(k): _sanitize_for_json(v) for k, v in val.items()}
    if isinstance(val, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in val]
    if hasattr(val, "model_dump") and callable(val.model_dump):
        try:
            return _sanitize_for_json(val.model_dump())
        except Exception:
            pass
    if hasattr(val, "dict") and callable(val.dict):
        try:
            return _sanitize_for_json(val.dict())
        except Exception:
            pass
    if hasattr(val, "__dict__"):
        try:
            return _sanitize_for_json(vars(val))
        except Exception:
            pass
    return str(val)


class GeminiAdapter(BaseAIAdapter):
    """Communicates directly with Google Generative Language API via httpx."""

    def __init__(self) -> None:
        super().__init__("gemini")
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
        tool_executor: Optional[Any] = None,
        max_tool_rounds: int = 3,
        **kwargs: Any,
    ) -> AIResult:
        start_time = time.perf_counter()
        client = await self._get_client(timeout)

        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

        # Format contents
        contents: List[Dict[str, Any]] = []
        for i, msg in enumerate(messages):
            role = "user" if msg.get("role") in ("user", "system") else "model"
            parts: List[Dict[str, Any]] = [{"text": str(msg.get("content", ""))}]
            if i == len(messages) - 1 and images:
                for img in images:
                    parts.append({
                        "inline_data": {
                            "mime_type": img.get("mime_type", "image/png"),
                            "data": img.get("data", ""),
                        }
                    })
            contents.append({
                "role": role,
                "parts": parts,
            })

        gen_config: Dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        # 針對 Gemini 2.5/3.x 系列啟用原生深度思考 (含完整思維鏈輸出與 4096 tokens 思維預算)
        if any(v in model.lower() for v in ["2.5", "3.", "flash", "pro", "exp", "thinking"]):
            gen_config["thinkingConfig"] = {
                "includeThoughts": True,
                "thinkingBudget": 4096,
            }

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": gen_config,
        }
        if system_instruction:
            payload["system_instruction"] = {
                "parts": [{"text": system_instruction}],
            }

        if disable_safety:
            payload["safetySettings"] = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
            ]
        elif getattr(config.ai, "gemini_safety_settings", None):
            payload["safetySettings"] = [
                {"category": cat, "threshold": thresh}
                for cat, thresh in config.ai.gemini_safety_settings.items()
            ]
        else:
            payload["safetySettings"] = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
            ]

        # Format Gemini tools
        if tools:
            formatted_declarations: List[Dict[str, Any]] = []
            for t in tools:
                if "function" in t and isinstance(t["function"], dict):
                    formatted_declarations.append({
                        "name": t["function"].get("name", ""),
                        "description": t["function"].get("description", ""),
                        "parameters": t["function"].get("parameters", {}),
                    })
                elif "function_declarations" in t and isinstance(t["function_declarations"], list):
                    formatted_declarations.extend(t["function_declarations"])
                elif "name" in t:
                    formatted_declarations.append(t)
            if formatted_declarations:
                payload["tools"] = [{"function_declarations": formatted_declarations}]

        primary_model = model or "gemini-3.1-flash-lite"
        # 自動校正已退役之舊版模型名稱至官方現役穩定版
        if primary_model in ("gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.0-pro"):
            primary_model = "gemini-2.5-flash"

        if not allow_fallback:
            candidate_models = [primary_model]
        else:
            candidate_models = [primary_model]
            for bm in [
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash",
                "gemini-3.5-flash-lite",
                "gemini-flash-latest",
            ]:
                if bm not in candidate_models:
                    candidate_models.append(bm)

        last_error: Optional[Exception] = None
        max_retries = 3
        for cur_model in candidate_models:
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{cur_model}:generateContent"
            # Clone payload to ensure fresh state per model attempt
            cur_payload = {
                "contents": [dict(c) for c in contents],
                "generationConfig": dict(payload["generationConfig"]),
            }
            if "system_instruction" in payload:
                cur_payload["system_instruction"] = payload["system_instruction"]
            if "safetySettings" in payload:
                cur_payload["safetySettings"] = payload["safetySettings"]
            if "tools" in payload:
                cur_payload["tools"] = payload["tools"]

            executed_tool_calls: List[Dict[str, Any]] = []
            round_count = 0
            total_prompt_tokens = 0
            total_completion_tokens = 0
            last_data: Dict[str, Any] = {}
            real_model = cur_model
            text_result = ""
            native_thinking: Optional[str] = None

            try:
                while True:
                    response = None
                    last_http_exc = None
                    for attempt in range(max_retries + 1):
                        try:
                            response = await asyncio.wait_for(
                                client.post(endpoint, headers=headers, json=cur_payload, timeout=timeout),
                                timeout=timeout + 5.0,
                            )
                        except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, asyncio.TimeoutError, TimeoutError) as net_err:
                            last_http_exc = net_err
                            if attempt < max_retries:
                                backoff = (0.5 * (2 ** attempt)) + random.uniform(0.1, 0.5)
                                log.warning(
                                    f"Gemini API network error on {cur_model} ({net_err}). "
                                    f"Retrying in {backoff:.2f}s (attempt {attempt + 1}/{max_retries})..."
                                )
                                await asyncio.sleep(backoff)
                                continue
                            raise

                        if response.status_code in (429, 503) and attempt < max_retries:
                            retry_after = None
                            headers_obj = getattr(response, "headers", None)
                            if isinstance(headers_obj, (dict, httpx.Headers)):
                                retry_after = headers_obj.get("retry-after")
                            elif headers_obj is not None and hasattr(headers_obj, "get") and not inspect.iscoroutinefunction(headers_obj.get):
                                try:
                                    raw_val = headers_obj.get("retry-after")
                                    if isinstance(raw_val, str):
                                        retry_after = raw_val
                                except Exception:
                                    pass

                            if retry_after and isinstance(retry_after, str) and retry_after.isdigit():
                                # 強制限制單次退避上限為 5.0 秒，避免因極端 Retry-After (如 3600s) 導致協程死鎖掛起
                                backoff = min(float(retry_after), 5.0) + random.uniform(0.01, 0.05)
                            else:
                                backoff = min(2.0, (0.05 * (2 ** attempt))) + random.uniform(0.01, 0.05)
                            log.warning(
                                f"Gemini API returned HTTP {response.status_code} for {cur_model}. "
                                f"Retrying with backoff in {backoff:.2f}s (attempt {attempt + 1}/{max_retries})..."
                            )
                            await asyncio.sleep(backoff)
                            continue
                        break

                    if response is None:
                        if last_http_exc:
                            raise last_http_exc
                        raise RuntimeError(f"Gemini API failed to obtain response for model {cur_model}")

                    if response.status_code != 200:
                        error_data = response.text
                        raise RuntimeError(f"Gemini API Error (HTTP {response.status_code}): {redact_secrets(error_data[:300])}")

                    try:
                        data = response.json()
                    except Exception as json_err:
                        raise ValueError(f"Gemini returned invalid JSON payload: {json_err}")

                    if inspect.iscoroutine(data):
                        data = await data
                    last_data = data
                    candidates = data.get("candidates", [])
                    if not candidates:
                        raise ValueError("Gemini returned empty candidates.")

                    usage = data.get("usageMetadata", {})
                    total_prompt_tokens += usage.get("promptTokenCount", 0)
                    total_completion_tokens += usage.get("candidatesTokenCount", 0)
                    if data.get("modelVersion"):
                        real_model = data["modelVersion"]

                    # 安全讀取 parts，防範 candidates[0]["content"] 為 None 時觸發 AttributeError
                    cand_content = candidates[0].get("content") or {}
                    parts = cand_content.get("parts") or []
                    fc_parts = [p for p in parts if isinstance(p, dict) and (p.get("functionCall") or p.get("function_call"))]

                    thought_texts: List[str] = []
                    normal_texts: List[str] = []
                    for p in parts:
                        if not isinstance(p, dict):
                            continue
                        if p.get("thought") is True:
                            th = p.get("text", "").strip()
                            if th:
                                thought_texts.append(th)
                        elif p.get("text"):
                            normal_texts.append(p.get("text", ""))

                    if thought_texts:
                        native_thinking = "\n\n".join(thought_texts)

                    if not fc_parts or round_count >= max_tool_rounds:
                        text_result = "".join(normal_texts) if normal_texts else "".join(p.get("text", "") for p in parts if isinstance(p, dict))
                        break

                    round_count += 1
                    cur_payload["contents"].append({"role": "model", "parts": parts})

                    fn_response_parts: List[Dict[str, Any]] = []
                    for p in fc_parts:
                        fc = p.get("functionCall") or p.get("function_call")
                        if not fc or not isinstance(fc, dict):
                            continue
                        fname = str(fc.get("name") or "").strip()
                        if not fname:
                            continue
                        fargs = fc.get("args") or {}
                        if isinstance(fargs, str):
                            try:
                                fargs = json.loads(fargs)
                            except Exception:
                                fargs = {"raw_input": fargs}
                        # 強制保證 fargs 一定為 dict，防範模型回傳 list/string 時造成 **fargs 拋出 TypeError 崩潰
                        if not isinstance(fargs, dict):
                            fargs = {"raw_input": fargs}

                        if tool_executor:
                            try:
                                if inspect.iscoroutinefunction(tool_executor):
                                    res = await tool_executor(fname, fargs)
                                else:
                                    res = tool_executor(fname, fargs)
                                    if inspect.iscoroutine(res):
                                        res = await res
                            except Exception as te:
                                res = {"error": f"Tool execution failed: {te}"}
                        else:
                            from zeronexus.agent.tools import agent_tools
                            tool = agent_tools.get_tool(fname)
                            if tool:
                                try:
                                    exec_fn = tool.execute
                                    if inspect.iscoroutinefunction(exec_fn):
                                        res = await exec_fn(**fargs)
                                    else:
                                        res = exec_fn(**fargs)
                                        if inspect.iscoroutine(res):
                                            res = await res
                                except Exception as te:
                                    res = {"error": f"Tool '{fname}' failed: {te}"}
                            else:
                                res = {"error": f"Tool '{fname}' is not registered."}

                        clean_res = _sanitize_for_json(res)
                        executed_tool_calls.append({"name": fname, "args": fargs, "result": clean_res})

                        fn_response_parts.append({
                            "functionResponse": {
                                "name": fname,
                                "response": clean_res if isinstance(clean_res, dict) else {"result": clean_res},
                            }
                        })

                    if fn_response_parts:
                        cur_payload["contents"].append({"role": "function", "parts": fn_response_parts})

                latency_ms = (time.perf_counter() - start_time) * 1000
                is_fb = (cur_model != primary_model)

                return AIResult(
                    text=text_result,
                    model_name=real_model,
                    provider="gemini",
                    latency_ms=round(latency_ms, 2),
                    prompt_tokens=total_prompt_tokens,
                    completion_tokens=total_completion_tokens,
                    raw_response=last_data,
                    tool_calls=executed_tool_calls or None,
                    is_fallback=is_fb,
                    fallback_reason=f"Primary model '{primary_model}' failed, auto-switched to '{cur_model}'" if is_fb else None,
                    requested_model=primary_model,
                    thinking_process=native_thinking,
                )
            except Exception as exc:
                last_error = exc
                err_text = str(exc).lower()
                if "thinkingconfig" in err_text:
                    if "thinkingConfig" in cur_payload.get("generationConfig", {}):
                        log.warning(f"Model '{cur_model}' does not support thinkingConfig, retrying without it...")
                        del cur_payload["generationConfig"]["thinkingConfig"]
                        continue
                is_recoverable = (
                    "429" in err_text
                    or "503" in err_text
                    or "404" in err_text
                    or "quota" in err_text
                    or "resource_exhausted" in err_text
                    or "empty candidates" in err_text
                )
                if is_recoverable and cur_model != candidate_models[-1]:
                    log.warning(
                        f"Gemini model '{cur_model}' hit recoverable error: {exc}. "
                        f"Attempting next fallback candidate model..."
                    )
                    continue
                raise exc

        if last_error:
            raise last_error
        raise RuntimeError("All Gemini candidate models failed.")
