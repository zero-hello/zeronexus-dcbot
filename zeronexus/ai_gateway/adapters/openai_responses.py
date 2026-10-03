"""OpenAI Responses API adapter for OpenAI-compatible relay endpoints."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.core.config import config
from zeronexus.security.sanitizer import redact_secrets


class OpenAIResponsesAdapter(BaseAIAdapter):
    """Calls the Responses API, including its function-call continuation loop."""

    def __init__(self) -> None:
        super().__init__("openai")
        self._http_client: Optional[httpx.AsyncClient] = None

    async def _get_client(self, timeout: float) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
            )
        return self._http_client

    @staticmethod
    def _endpoint(base_url: str) -> str:
        base = (base_url or "https://api.openai.com/v1").strip().rstrip("/")
        if base.endswith("/responses"):
            return base
        return f"{base}/responses"

    @staticmethod
    def _normalize_tools(tools: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in tools or []:
            if not isinstance(item, dict):
                continue
            fn = item.get("function") if isinstance(item.get("function"), dict) else item
            if not fn.get("name"):
                continue
            normalized.append({
                "type": "function",
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return normalized

    @staticmethod
    def _content_parts(content: Any) -> List[Dict[str, Any]]:
        if isinstance(content, list):
            parts: List[Dict[str, Any]] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") in ("text", "input_text"):
                    parts.append({"type": "input_text", "text": str(item.get("text", ""))})
                elif item.get("type") in ("image_url", "input_image"):
                    image_url = item.get("image_url", "")
                    if isinstance(image_url, dict):
                        image_url = image_url.get("url", "")
                    if image_url:
                        parts.append({"type": "input_image", "image_url": image_url})
            return parts or [{"type": "input_text", "text": ""}]
        return [{"type": "input_text", "text": str(content or "")}]

    @staticmethod
    def _response_text(data: Dict[str, Any]) -> str:
        direct = data.get("output_text")
        if isinstance(direct, str) and direct:
            return direct
        chunks: List[str] = []
        for item in data.get("output", []) or []:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            for part in item.get("content", []) or []:
                if isinstance(part, dict) and part.get("type") in ("output_text", "text"):
                    text = part.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
        return "\n".join(chunks)

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
        started = time.perf_counter()
        client = await self._get_client(timeout)
        endpoint = self._endpoint(config.ai.openai_base_url)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        input_items: List[Dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role", "user"))
            role = "assistant" if role in ("bot", "model") else role
            if role not in ("user", "assistant", "system", "developer"):
                role = "user"
            input_items.append({"role": role, "content": self._content_parts(message.get("content", ""))})

        if images:
            image_parts = []
            for image in images:
                mime = image.get("mime_type", "image/png")
                payload = image.get("data", "")
                if payload:
                    image_parts.append({"type": "input_image", "image_url": f"data:{mime};base64,{payload}"})
            if image_parts:
                if input_items and input_items[-1].get("role") == "user":
                    input_items[-1]["content"].extend(image_parts)
                else:
                    input_items.append({"role": "user", "content": image_parts})

        response_tools = self._normalize_tools(tools)
        executed_calls: List[Dict[str, Any]] = []
        usage: Dict[str, Any] = {}
        final_data: Dict[str, Any] = {}
        rounds = 0

        while True:
            payload: Dict[str, Any] = {
                "model": model.removeprefix("openai/"),
                "input": input_items,
                "max_output_tokens": max_tokens,
            }
            if system_instruction:
                payload["instructions"] = system_instruction
            if response_tools:
                payload["tools"] = response_tools
                payload["tool_choice"] = "auto"
            if "temperature" in kwargs or temperature is not None:
                payload["temperature"] = temperature

            response = await client.post(endpoint, headers=headers, json=payload, timeout=timeout)
            if response.status_code < 200 or response.status_code >= 300:
                detail = redact_secrets(response.text[:500])
                raise RuntimeError(f"OpenAI Responses API HTTP {response.status_code}: {detail}")
            final_data = response.json()
            usage = final_data.get("usage") or usage
            calls = [item for item in (final_data.get("output") or []) if isinstance(item, dict) and item.get("type") == "function_call"]
            if not calls or not tool_executor or rounds >= max(0, max_tool_rounds):
                break

            rounds += 1
            input_items.extend(final_data.get("output") or calls)
            for call in calls:
                name = str(call.get("name", ""))
                call_id = str(call.get("call_id", ""))
                try:
                    args = json.loads(call.get("arguments") or "{}")
                except (TypeError, json.JSONDecodeError):
                    args = {}
                if not isinstance(args, dict):
                    args = {"raw_input": args}
                try:
                    result = await tool_executor(name, args)
                except Exception as exc:
                    result = {"error": redact_secrets(str(exc))}
                executed_calls.append({"name": name, "args": args, "result": result})
                output = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
                input_items.append({"type": "function_call_output", "call_id": call_id, "output": output})

        elapsed = (time.perf_counter() - started) * 1000
        target_model = str(final_data.get("model") or model.removeprefix("openai/"))
        return AIResult(
            text=self._response_text(final_data),
            model_name=f"openai/{target_model}",
            provider="openai",
            quota_model_id=f"openai/{target_model}",
            requested_model=model,
            latency_ms=elapsed,
            prompt_tokens=int(usage.get("input_tokens", 0) or 0),
            completion_tokens=int(usage.get("output_tokens", 0) or 0),
            tool_calls=executed_calls or None,
            raw_response=final_data,
        )
