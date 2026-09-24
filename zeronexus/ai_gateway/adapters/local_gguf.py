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
        self._server_process: Optional[Any] = None
        self._server_port: int = 8089

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

    def _get_llama_server_path(self) -> Optional[str]:
        """取得官方自適應 llama-server 二進位檔絕對路徑 (方案 B 推薦)。"""
        cwd_cand = os.path.join(os.getcwd(), "data", "bin", "llama", "llama-server")
        if os.path.exists(cwd_cand) and os.access(cwd_cand, os.X_OK):
            return cwd_cand

        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        candidate = os.path.join(base_dir, "data", "bin", "llama", "llama-server")
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate

        return None

    async def _ensure_server_running(self, server_path: str, model_path: str) -> str:
        """確保 llama-server 於本地背景運行並處於就緒狀態。"""
        import httpx
        url = f"http://127.0.0.1:{self._server_port}"

        try:
            async with httpx.AsyncClient(timeout=1.0) as client:
                res = await client.get(f"{url}/health")
                if res.status_code == 200:
                    return url
        except Exception:
            pass

        bin_dir = os.path.dirname(server_path)
        env = os.environ.copy()
        current_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{bin_dir}:{current_ld}" if current_ld else bin_dir

        threads = max(1, min(os.cpu_count() or 2, 4))
        cmd = [
            server_path,
            "-m", model_path,
            "--port", str(self._server_port),
            "-t", str(threads),
            "-c", "2048",
            "--log-disable",
        ]

        import subprocess
        self._server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )

        for _ in range(30):
            await asyncio.sleep(0.5)
            try:
                async with httpx.AsyncClient(timeout=1.0) as client:
                    res = await client.get(f"{url}/health")
                    if res.status_code == 200:
                        log.info(f"本地自適應 llama-server 就緒！端點：{url}")
                        return url
            except Exception:
                continue

        return url

    async def _generate_via_server(
        self,
        server_url: str,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        timeout: float,
        model: str,
        start_time: float,
        model_path: str,
    ) -> AIResult:
        """透過本地 llama-server 執行標準 OpenAI Chat Completion 推論。"""
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

        payload = {
            "messages": formatted_messages,
            "max_tokens": min(max_tokens, 512),
            "temperature": temperature,
        }

        import httpx
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{server_url}/v1/chat/completions", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"llama-server 請求失敗 (HTTP {resp.status_code}): {resp.text}")
            data = resp.json()

        choices = data.get("choices", [])
        if not choices:
            raise ValueError("llama-server 未回傳任何文字內容")

        content = choices[0].get("message", {}).get("content", "").strip()
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens", len(str(formatted_messages)) // 3)
        completion_tokens = usage.get("completion_tokens", len(content) // 3)
        latency_ms = (time.perf_counter() - start_time) * 1000.0

        return AIResult(
            text=content,
            model_name=os.path.basename(model_path).replace(".gguf", ""),
            provider="local",
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw_response=data,
            requested_model=model,
        )

    _hardware_probe_cache: Dict[str, tuple[bool, str]] = {}

    @classmethod
    def probe_hardware_safety(cls, model_path: str) -> tuple[bool, str]:
        """以沙盒獨立子行程探測 CPU 指令集與 llama-cpp-python C++ 動態函式庫之硬體相容性 (防止 SIGILL 導致主行程崩潰)。"""
        if model_path in cls._hardware_probe_cache:
            return cls._hardware_probe_cache[model_path]

        # 檢視 Linux /proc/cpuinfo
        cpu_features_warning = ""
        if os.path.exists("/proc/cpuinfo"):
            try:
                with open("/proc/cpuinfo", "r", encoding="utf-8", errors="ignore") as f:
                    cpuinfo = f.read()
                    flags_line = next((line for line in cpuinfo.splitlines() if line.startswith("flags")), "")
                    if "avx2" not in flags_line.lower():
                        cpu_features_warning = " (主機 CPU 未具備 AVX2 指令集旗標)"
            except Exception:
                pass

        import subprocess
        import sys

        probe_script = (
            "import sys\n"
            "try:\n"
            "    import llama_cpp\n"
            f"    llm = llama_cpp.Llama(model_path={model_path!r}, n_ctx=16, verbose=False)\n"
            "    sys.exit(0)\n"
            "except Exception as e:\n"
            "    print(f'EXC:{e}', file=sys.stderr)\n"
            "    sys.exit(2)\n"
        )

        try:
            res = subprocess.run(
                [sys.executable, "-c", probe_script],
                capture_output=True,
                text=True,
                timeout=15,
            )
            # 檢查是否遭遇 SIGILL (Illegal instruction, 代碼 -4 或 132) 或崩潰
            if res.returncode in (-4, 132) or "illegal instruction" in (res.stderr or "").lower():
                err_msg = (
                    f"主機或託管伺服器 CPU 不支援該套件之向量加速指令集 (Illegal instruction / SIGILL){cpu_features_warning}。"
                    f"為保護機器人穩定運行，已安全停用本地推論模組，自動切換至雲端備援模型。"
                    f"（若為第三方託管環境，因虛擬 CPU 通常未提供 AVX2 指令集且無法本地編譯，建議直接於選單選用雲端頂級模型）"
                )
                cls._hardware_probe_cache[model_path] = (False, err_msg)
                return False, err_msg
            elif res.returncode != 0:
                err_detail = (res.stderr or "").strip()
                if "EXC:" in err_detail:
                    err_msg = err_detail.split("EXC:", 1)[1].strip()
                else:
                    err_msg = f"沙盒探測返回非零代碼 ({res.returncode}): {err_detail}"
                cls._hardware_probe_cache[model_path] = (False, err_msg)
                return False, err_msg

            cls._hardware_probe_cache[model_path] = (True, "OK")
            return True, "OK"
        except subprocess.TimeoutExpired:
            err_msg = "沙盒硬體安全探測逾時 (可能 CPU 負載過高或死鎖)。已安全隔離本地模型。"
            cls._hardware_probe_cache[model_path] = (False, err_msg)
            return False, err_msg
        except Exception as e:
            err_msg = f"執行硬體安全探測時發生異常: {e}"
            cls._hardware_probe_cache[model_path] = (False, err_msg)
            return False, err_msg

    def _get_or_load_llm(self, model_path: str, n_ctx: int = 4096) -> Any:
        """執行緒安全地載入或取得 llama_cpp.Llama 實例。"""
        with self._llm_lock:
            if self._llm is not None and self._current_loaded_path == model_path:
                return self._llm

            if not os.path.exists(model_path):
                log.warning(f"偵測到本地 GGUF 模型檔案不存在：'{model_path}'，啟動自動自癒補齊下載...")
                try:
                    from zeronexus.brain.bootstrap import ensure_gguf_model_ready
                    ensure_gguf_model_ready(models_dir=self.models_dir, console_output=True)
                except Exception as down_err:
                    log.warning(f"嘗試自動補齊 GGUF 模型異常: {down_err}")

                if not os.path.exists(model_path):
                    raise FileNotFoundError(
                        f"本地 GGUF 模型檔案不存在且自動自癒失敗：'{model_path}'。"
                        f"請確認模型是否已下載至 data/models/ 目錄中。"
                    )

            # 0. 執行前置硬體相容性沙盒探測 (零崩潰防護網)
            safe, reason = self.probe_hardware_safety(model_path)
            if not safe:
                log.warning(f"本地 GGUF 模型安全防護觸發：{reason}")
                raise RuntimeError(reason)

            log.info(f"正在載入本地 GGUF 模型至記憶體：{model_path} (n_ctx={n_ctx})")
            t0 = time.perf_counter()

            try:
                import llama_cpp
            except ImportError:
                log.warning("偵測到環境缺少 llama-cpp-python 套件，嘗試啟動大腦自動修復機制進行安裝...")
                try:
                    from zeronexus.brain.bootstrap import check_and_repair_dependencies
                    check_and_repair_dependencies()
                    import llama_cpp
                except Exception as repair_err:
                    raise RuntimeError(
                        "未安裝 llama-cpp-python 套件且動態修復受限，無法執行本地 GGUF 模型推論。"
                        "若在 Docker 容器內運行，請執行 'docker compose build --no-cache' 重新建置映像檔。"
                    ) from repair_err

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

    def _get_llama_cli_path(self) -> Optional[str]:
        """取得官方自適應 llama-cli 二進位檔絕對路徑 (方案 B)。"""
        # 1. 基於當前工作目錄
        cwd_cand = os.path.join(os.getcwd(), "data", "bin", "llama", "llama-cli")
        if os.path.exists(cwd_cand) and os.access(cwd_cand, os.X_OK):
            return cwd_cand

        # 2. 基於檔案所在目錄向上回溯 3 層 (zeronexus/ai_gateway/adapters -> 專案根目錄)
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        candidate = os.path.join(base_dir, "data", "bin", "llama", "llama-cli")
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate

        return None

    async def _generate_via_cli(
        self,
        cli_path: str,
        model_path: str,
        system_instruction: str,
        messages: List[Dict[str, Any]],
        max_tokens: int,
        temperature: float,
        timeout: float,
        model: str,
        start_time: float,
        **kwargs: Any,
    ) -> AIResult:
        """透過獨立自適應 llama-cli 二進位引擎執行推論 (免 AVX2 限制 / 支援託管環境)。"""
        log.info(f"啟動自適應二進位推論引擎 (方案 B)：{cli_path}，調用模型：{model_path}")

        # 構建 Qwen ChatML 標準提示詞
        prompt_parts: List[str] = []
        if system_instruction:
            prompt_parts.append(f"<|im_start|>system\n{system_instruction}<|im_end|>")

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

            prompt_parts.append(f"<|im_start|>{role}\n{content_str}<|im_end|>")

        prompt_parts.append("<|im_start|>assistant\n")
        full_prompt = "\n".join(prompt_parts)

        threads = max(1, min(os.cpu_count() or 2, 4))
        bin_dir = os.path.dirname(cli_path)
        env = os.environ.copy()
        current_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{bin_dir}:{current_ld}" if current_ld else bin_dir

        cmd = [
            cli_path,
            "-m", model_path,
            "-p", full_prompt,
            "-n", str(min(max_tokens, 512)),
            "--temp", str(temperature),
            "-t", str(threads),
            "--single-turn",
            "--no-display-prompt",
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout_data, stderr_data = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            raise TimeoutError(f"本地 GGUF 二進位推論逾時 ({timeout:.1f} 秒)")

        if proc.returncode != 0:
            err_msg = stderr_data.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"自適應二進位推論引擎異常退出 (代碼 {proc.returncode}): {err_msg[:300]}")

        raw_output = stdout_data.decode("utf-8", errors="replace").strip()

        # 解析真正的助理回覆部分
        if "<|im_start|>assistant" in raw_output:
            response_text = raw_output.split("<|im_start|>assistant", 1)[1]
        else:
            response_text = raw_output

        # 清除結尾統計資訊與標記
        if "[ Prompt:" in response_text:
            response_text = response_text.split("[ Prompt:", 1)[0]
        if "Exiting..." in response_text:
            response_text = response_text.split("Exiting...", 1)[0]

        for stop_tag in ("<|im_end|>", "<|endoftext|>", "</s>"):
            response_text = response_text.replace(stop_tag, "")

        clean_text = response_text.strip()

        latency_ms = (time.perf_counter() - start_time) * 1000.0
        prompt_tokens = max(1, len(full_prompt) // 3)
        completion_tokens = max(1, len(clean_text) // 3)

        return AIResult(
            text=clean_text,
            model_name=os.path.basename(model_path).replace(".gguf", ""),
            provider="local",
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            raw_response={"engine": "llama-cli", "output": raw_output},
            requested_model=model,
        )

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
        """透過本地 GGUF 模型進行非同步推論並回傳結果 (支援方案 B 優先調用)。"""
        start_time = time.perf_counter()
        model_path = self._resolve_model_path(model)

        # 優先方案 B：檢測或自癒就緒自適應二進位推論引擎 (server / cli)
        server_path = self._get_llama_server_path()
        cli_path = self._get_llama_cli_path()

        if server_path is None and cli_path is None:
            try:
                from zeronexus.brain.bootstrap import ensure_llama_binaries_ready
                ensure_llama_binaries_ready(console_output=False)
                server_path = self._get_llama_server_path()
                cli_path = self._get_llama_cli_path()
            except Exception as dl_err:
                log.warning(f"自癒準備自適應二進位引擎異常: {dl_err}")

        # 優先模式 1：llama-server (常駐記憶體・秒級極速回應・零卡頓)
        if server_path is not None and os.path.exists(model_path):
            try:
                server_url = await self._ensure_server_running(server_path, model_path)
                return await self._generate_via_server(
                    server_url=server_url,
                    system_instruction=system_instruction,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                    model=model,
                    start_time=start_time,
                    model_path=model_path,
                )
            except Exception as srv_err:
                log.warning(f"llama-server 模式調用異常，嘗試 cli 模式備援: {srv_err}")

        # 優先模式 2：llama-cli (獨立子行程・單次回合推論)
        if cli_path is not None and os.path.exists(model_path):
            try:
                return await self._generate_via_cli(
                    cli_path=cli_path,
                    model_path=model_path,
                    system_instruction=system_instruction,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    timeout=timeout,
                    model=model,
                    start_time=start_time,
                    **kwargs,
                )
            except Exception as cli_err:
                log.warning(f"自適應二進位引擎調用失敗，嘗試回退內部引擎: {cli_err}")

        # 備援模式 3：Python 內部 llama-cpp-python 引擎 (受沙盒防護)
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
        """釋放記憶體中的 GGUF 模型實例與背景伺服器程序。"""
        if self._server_process is not None:
            try:
                self._server_process.terminate()
                self._server_process.wait(timeout=2.0)
            except Exception:
                try:
                    self._server_process.kill()
                except Exception:
                    pass
            self._server_process = None
            log.info("本地自適應 llama-server 程序已終止釋放。")

        with self._llm_lock:
            self._llm = None
            self._current_loaded_path = None
        log.info("本地 GGUF 模型實例已從記憶體中卸載。")
