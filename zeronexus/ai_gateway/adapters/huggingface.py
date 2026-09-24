"""Hugging Face Serverless / Router REST Adapter.

Supports:
- Hugging Face Router & Serverless Inference API (OpenAI-compatible)
- Endpoint: https://router.huggingface.co/hf-inference/v1/chat/completions
- Fallback Endpoint: https://api-inference.huggingface.co/v1/chat/completions
- High-performance httpx async streaming & retry
- Absolute credential redaction
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

import httpx

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.core.logger import log
from zeronexus.security.sanitizer import redact_secrets


class HuggingFaceAdapter(BaseAIAdapter):
    """Communicates with Hugging Face Inference API via OpenAI-compatible endpoints."""

    def __init__(self) -> None:
        super().__init__("huggingface")
        self._http_client: Optional[httpx.AsyncClient] = None
        self.primary_endpoint = "https://router.huggingface.co/hf-inference/v1/chat/completions"
        self.fallback_endpoint = "https://api-inference.huggingface.co/v1/chat/completions"

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
        start_time = time.perf_counter()
        client = await self._get_client(timeout)

        target_model = model or "Qwen/Qwen2.5-72B-Instruct"
        # Strip provider prefixes if passed e.g. "huggingface/meta-llama/..." or "huggingface/Qwen/..."
        if target_model.startswith("huggingface/"):
            target_model = target_model.replace("huggingface/", "", 1)

        compatible_serverless_models = [
            "Qwen/Qwen2.5-72B-Instruct",
            "mistralai/Mistral-7B-Instruct-v0.3",
        ]

        if not allow_fallback:
            candidate_models = [target_model]
        else:
            candidate_models = [target_model]
            for cm in compatible_serverless_models:
                if cm not in candidate_models:
                    candidate_models.append(cm)

        formatted_messages: List[Dict[str, str]] = []
        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})

        for i, msg in enumerate(messages):
            content = str(msg.get("content", ""))
            if i == len(messages) - 1 and images:
                content += " [備註：使用者附加了圖片檔案，Hugging Face 文字模型以純文字理解進行推論]"
            formatted_messages.append({"role": msg.get("role", "user"), "content": content})

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ZeroNexus-AIGateway/1.0",
        }

        last_error: Optional[Exception] = None

        for cur_model in candidate_models:
            payload = {
                "model": cur_model,
                "messages": formatted_messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if "top_p" in kwargs and kwargs["top_p"] is not None:
                payload["top_p"] = kwargs["top_p"]

            endpoints = [
                self.primary_endpoint,
                self.fallback_endpoint,
                f"https://api-inference.huggingface.co/models/{cur_model}/v1/chat/completions",
            ]

            for endpoint in endpoints:
                try:
                    response = await client.post(endpoint, headers=headers, json=payload, timeout=timeout)
                    latency_ms = (time.perf_counter() - start_time) * 1000

                    if response.status_code == 200:
                        try:
                            data = response.json()
                        except Exception as json_err:
                            log.warning(f"Hugging Face endpoint returned invalid JSON: {json_err}")
                            continue
                        choices = data.get("choices", [])
                        if not choices:
                            raise ValueError("Hugging Face API returned empty choices list.")

                        msg_obj = choices[0].get("message") or {}
                        text_result = msg_obj.get("content") or ""
                        usage = data.get("usage", {})
                        prompt_tokens = usage.get("prompt_tokens", 0)
                        completion_tokens = usage.get("completion_tokens", 0)
                        real_model = data.get("model") or cur_model
                        is_fb = (cur_model != target_model)

                        return AIResult(
                            text=text_result,
                            model_name=real_model,
                            provider="huggingface",
                            latency_ms=round(latency_ms, 2),
                            prompt_tokens=prompt_tokens,
                            completion_tokens=completion_tokens,
                            raw_response=data,
                            is_fallback=is_fb,
                            fallback_reason=f"Primary model '{target_model}' failed on Hugging Face, switched to '{cur_model}'" if is_fb else None,
                            requested_model=model,
                        )
                    else:
                        error_body = redact_secrets(response.text[:400])
                        log.warning(
                            f"Hugging Face endpoint '{endpoint}' for model '{cur_model}' returned HTTP {response.status_code}: {error_body}"
                        )
                        last_error = RuntimeError(f"Hugging Face API Error (HTTP {response.status_code}): {error_body}")
                except Exception as e:
                    last_error = e
                    log.warning(f"Error calling Hugging Face endpoint '{endpoint}' for model '{cur_model}': {redact_secrets(str(e))}")

        raise last_error or RuntimeError("Hugging Face inference failed across all models and endpoints.")
