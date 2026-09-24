"""ZeroNexus 本地 GGUF 模型推論適配器 (Local GGUF Adapter).

基於 llama-cpp-python 驅動本地神經網路推論，具備延遲載入、執行緒安全鎖
與非同步背景執行 (asyncio.to_thread) 機制，提供零延遲、零額度消耗之端點自主推論。
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from typing import Any, Dict, List, Optional

from zeronexus.ai_gateway.adapters.base import AIResult, BaseAIAdapter
from zeronexus.core.logger import log


class LocalGGUFAdapter(BaseAIAdapter):
    """基於 llama-cpp-python 的地端 GGUF 模型推論適配器。"""

    DEFAULT_MODEL_FILENAME = "qwen2.5-0.5b-instruct-q8_0.gguf"

    def __init__(
        self,
        provider_name: str = "local",
        models_dir: Optional[str] = None,
    ) -> None:
        super().__init__(provider_name)
        if models_dir is None:
            self.models_dir = os.path.join(os.getcwd(), "data", "models")
        else:
            self.models_dir = models_dir

        self._llm: Optional[Any] = None
        self._llm_lock = threading.Lock()
        self._async_lock = asyncio.Lock()
        self._current_loaded_path: Optional[str] = None

    def _resolve_model_path(self, model: str) -> str:
        """解析模型檔案之完整絕對路徑。"""
        clean_name = model
        for prefix in ("local/", "gguf/", "models/"):
            if clean_name.startswith(prefix):
                clean_name = clean_name[len(prefix):]

        if not clean_name.endswith(".gguf"):
            clean_name = f"{clean_name}.gguf"

        target_path = os.path.join(self.models_dir, clean_name)
        if os.path.exists(target_path):
            return target_path

        default_path = os.path.join(self.models_dir, self.DEFAULT_MODEL_FILENAME)
        if os.path.exists(default_path):
            return default_path

        return target_path

    def _get_or_load_llm(self, model_path: str, n_ctx: int = 4096) -> Any:
        """執行緒安全地載入或取得 llama_cpp.Llama 實例。"""
        with self._llm_lock:
            if self._llm is not None and self._current_loaded_path == model_path:
                return self._llm

            if not os.path.exists(model_path):
                raise FileNotFoundError(
                    f"本地 GGUF 模型檔案不存在：'{model_path}'。"
                    f"請確認模型是否已下載至 data/models/ 目錄中。"
                )

            log.info(f"正在載入本地 GGUF 模型至記憶體：{model_path} (n_ctx={n_ctx})")
            t0 = time.perf_counter()

            try:
                import llama_cpp
            except ImportError as err:
                raise RuntimeError(
                    "未安裝 llama-cpp-python 套件，無法執行本地 GGUF 模型推論。"
                ) from err

            threads = max(1, (os.cpu_count() or 4) - 1)
            llm = llama_cpp.Llama(
                model_path=model_path,
                n_ctx=n_ctx,
                n_threads=threads,
                verbose=False,
            )

            load_ms = (time.perf_counter() - t0) * 1000.0
            log.info(f"本地 GGUF 模型載入完成！耗時：{load_ms:.2f}ms，配置執行緒：{threads}")

            self._llm = llm
            self._current_loaded_path = model_path
            return self._llm

    async def generate(
        self,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        model: str,
        api_key: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.7,
        timeout: float = 60.0,
        images: Optional[List[Dict[str, Any]]] = None,
        allow_fallback: bool = True,
        disable_safety: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_executor: Optional[Any] = None,
        max_tool_rounds: int = 3,
        free_only: bool = False,
        **kwargs: Any,
    ) -> AIResult:
        """透過本地 GGUF 模型進行非同步推論並回傳結果。"""
        start_time = time.perf_counter()
        model_path = self._resolve_model_path(model)

        async with self._async_lock:
            llm = await asyncio.to_thread(self._get_or_load_llm, model_path, 4096)

        formatted_messages: List[Dict[str, str]] = []
        if system_instruction:
            formatted_messages.append({"role": "system", "content": system_instruction})

        for msg in messages:
            role = msg.get("role", "user")
            if role in ("bot", "model"):
                role = "assistant"
            elif role not in ("system", "user", "assistant"):
                role = "user"

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

            formatted_messages.append({"role": role, "content": content_str})

        top_p = float(kwargs.get("top_p", 0.9))

        def _run_inference() -> Dict[str, Any]:
            return llm.create_chat_completion(
                messages=formatted_messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
            )

        try:
            raw_response = await asyncio.wait_for(
                asyncio.to_thread(_run_inference),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"本地 GGUF 模型推論逾時 ({timeout:.1f} 秒)")

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        choices = raw_response.get("choices", [])
        if not choices:
            raise ValueError("本地 GGUF 模型未產生任何回應內容")

        message_obj = choices[0].get("message", {})
        response_text = message_obj.get("content", "").strip()

        usage = raw_response.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        return AIResult(
            text=response_text,
            model_name=os.path.basename(model_path).replace(".gguf", ""),
            provider="local",
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw_response=raw_response,
            requested_model=model,
        )

    async def close(self) -> None:
        """釋放記憶體中的 GGUF 模型實例。"""
        with self._llm_lock:
            self._llm = None
            self._current_loaded_path = None
        log.info("本地 GGUF 模型實例已從記憶體中卸載。")
