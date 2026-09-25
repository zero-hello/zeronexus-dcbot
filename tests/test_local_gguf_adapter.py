"""單元測試：本地 GGUF 推論引擎、適配器整合與模型選單項次驗證。"""

import os
import time
import pytest
from unittest.mock import MagicMock, patch

from zeronexus.ai_gateway.adapters.local_gguf import LocalGGUFAdapter
from zeronexus.ai_gateway.model_registry import model_registry
from zeronexus.ui.model_select_view import MODEL_SELECT_ENTRIES


class TestLocalGGUFIntegration:
    """本地 GGUF 模型各項整合邏輯測試。"""

    def test_model_select_entries_order_and_gemini25_removed(self) -> None:
        """驗證選單中第二項為 Q8_0 本地模型、第三項為 Q4_K_M 本地模型，且標籤清楚標記 8 與 4。"""
        # 1. 總數必須符合 Discord Select Menu 限制 (<= 25)
        assert len(MODEL_SELECT_ENTRIES) <= 25

        # 2. 第二個選項 (index 1) 必須為 qwen2.5-0.5b-instruct-q8_0 且清楚標示 8-bit / Q8_0
        assert MODEL_SELECT_ENTRIES[1]["id"] == "qwen2.5-0.5b-instruct-q8_0"
        assert "8" in MODEL_SELECT_ENTRIES[1]["label"] or "Q8" in MODEL_SELECT_ENTRIES[1]["label"]
        assert "GGUF" in MODEL_SELECT_ENTRIES[1]["label"]

        # 3. 第三個選項 (index 2) 必須為 qwen2.5-0.5b-instruct-q4_k_m 且清楚標示 4-bit / Q4_K_M
        assert MODEL_SELECT_ENTRIES[2]["id"] == "qwen2.5-0.5b-instruct-q4_k_m"
        assert "4" in MODEL_SELECT_ENTRIES[2]["label"] or "Q4" in MODEL_SELECT_ENTRIES[2]["label"]
        assert "GGUF" in MODEL_SELECT_ENTRIES[2]["label"]

        # 4. 確保所有 Gemini 2.5 模型皆已自選單中移除
        gemini_25_ids = [
            "gemini-2.5-flash",
            "gemini-2.5-pro",
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash-image",
        ]
        current_ids = [item["id"] for item in MODEL_SELECT_ENTRIES]
        for g25 in gemini_25_ids:
            assert g25 not in current_ids, f"Gemini 2.5 模型 {g25} 應自選單中移除"

    def test_model_registry_contains_local_model(self) -> None:
        """驗證模型註冊表中已正確註冊 Q8 與 Q4 本地模型及其元數據。"""
        # 驗證 Q8_0
        meta_q8 = model_registry.get("qwen2.5-0.5b-instruct-q8_0")
        assert meta_q8 is not None
        assert meta_q8.provider == "local"
        assert meta_q8.vendor == "qwen"
        assert meta_q8.is_free is True
        assert "8" in meta_q8.display_name or "Q8" in meta_q8.display_name

        alias_meta = model_registry.get("local/qwen2.5-0.5b-instruct")
        assert alias_meta is not None
        assert alias_meta.provider == "local"

        # 驗證 Q4_K_M
        meta_q4 = model_registry.get("qwen2.5-0.5b-instruct-q4_k_m")
        assert meta_q4 is not None
        assert meta_q4.provider == "local"
        assert meta_q4.vendor == "qwen"
        assert meta_q4.is_free is True
        assert "4" in meta_q4.display_name or "Q4" in meta_q4.display_name

        alias_q4 = model_registry.get("local/qwen2.5-0.5b-instruct-q4_k_m")
        assert alias_q4 is not None
        assert alias_q4.provider == "local"

    def test_local_gguf_adapter_file_not_found(self, tmp_path) -> None:
        """測試當 GGUF 模型檔案不存在時，適配器能拋出友善的 FileNotFoundError。"""
        empty_dir = str(tmp_path / "models")
        os.makedirs(empty_dir, exist_ok=True)

        adapter = LocalGGUFAdapter(models_dir=empty_dir)
        with patch("zeronexus.brain.bootstrap.ensure_gguf_model_ready", return_value=False):
            with pytest.raises(FileNotFoundError, match="本地 GGUF 模型檔案不存在"):
                adapter._get_or_load_llm(adapter._resolve_model_path("non_existent_model"))

    @pytest.mark.asyncio
    async def test_local_gguf_adapter_generate_mock(self) -> None:
        """測試 LocalGGUFAdapter.generate 成功推論時回傳標準 AIResult。"""
        adapter = LocalGGUFAdapter()

        mock_llm = MagicMock()
        mock_llm.create_chat_completion.return_value = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "您好！我是運行於地端的 Qwen 2.5 0.5B 本地模型。",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 25,
            },
        }

        # 模擬無原生二進位執行檔時，走 Python 套件推論路徑
        with (
            patch.object(adapter, "_get_llama_server_path", return_value=None),
            patch.object(adapter, "_get_llama_cli_path", return_value=None),
            patch.object(adapter, "_get_or_load_llm", return_value=mock_llm),
        ):
            result = await adapter.generate(
                system_instruction="請使用繁體中文回應",
                messages=[{"role": "user", "content": "你好"}],
                model="qwen2.5-0.5b-instruct-q8_0",
                temperature=0.7,
                max_tokens=256,
            )

            assert result.provider == "local"
            assert result.text == "您好！我是運行於地端的 Qwen 2.5 0.5B 本地模型。"
            assert result.prompt_tokens == 15
            assert result.completion_tokens == 25
            assert result.total_tokens == 40
            assert result.latency_ms > 0

    def test_bootstrap_gguf_verify_and_ensure(self, tmp_path) -> None:
        """測試 bootstrap 中的 GGUF 檔案健康校驗與缺失自癒邏輯。"""
        from zeronexus.brain.bootstrap import (
            verify_gguf_model,
            ensure_gguf_model_ready,
            GGUF_MODEL_SPEC,
        )

        dummy_model = tmp_path / GGUF_MODEL_SPEC["filename"]

        # 1. 檔案不存在
        assert verify_gguf_model(str(dummy_model)) is False

        # 2. 檔案過小 (殘缺/被截斷)
        dummy_model.write_bytes(b"x" * 2048)
        assert verify_gguf_model(str(dummy_model), min_bytes=1024) is True
        assert verify_gguf_model(str(dummy_model), min_bytes=GGUF_MODEL_SPEC["min_bytes"]) is False

        # 3. 模擬自癒觸發
        with patch("zeronexus.brain.bootstrap.download_gguf_model", return_value=True) as mock_dl:
            res = ensure_gguf_model_ready(models_dir=str(tmp_path), console_output=False)
            assert res is True
            mock_dl.assert_called_once()

    def test_hardware_safety_probe_sigill_protection(self, tmp_path) -> None:
        """測試 CPU 缺少指令集時觸發 SIGILL 的沙盒隔離與主行程零崩潰防護機制。"""
        adapter = LocalGGUFAdapter(models_dir=str(tmp_path))
        dummy_model = tmp_path / "test.gguf"
        dummy_model.write_bytes(b"dummy")

        LocalGGUFAdapter._hardware_probe_cache.clear()

        # 模擬子行程回傳 SIGILL (-4)
        mock_completed = MagicMock()
        mock_completed.returncode = -4
        mock_completed.stderr = "Illegal instruction (core dumped)"

        with patch("subprocess.run", return_value=mock_completed):
            safe, reason = LocalGGUFAdapter.probe_hardware_safety(str(dummy_model))
            assert safe is False
            assert "SIGILL" in reason

            # 快取生效
            assert str(dummy_model) in LocalGGUFAdapter._hardware_probe_cache

            # 驗證 _get_or_load_llm 攔截保護，主行程安全拋出例外防護
            with pytest.raises(RuntimeError, match="SIGILL"):
                adapter._get_or_load_llm(str(dummy_model))

    def test_bootstrap_ensure_llama_binaries(self, tmp_path) -> None:
        """測試 bootstrap 中的 llama.cpp 二進位執行檔自癒管理邏輯。"""
        from zeronexus.brain.bootstrap import (
            ensure_llama_binaries_ready,
            LLAMA_BIN_SPEC,
        )

        dummy_bin = tmp_path / LLAMA_BIN_SPEC["key_bin"]

        # 1. 檔案不存在，觸發下載
        with patch("zeronexus.brain.bootstrap.download_and_extract_llama_binaries", return_value=True) as mock_dl:
            res = ensure_llama_binaries_ready(bin_dir=str(tmp_path), console_output=False)
            assert res is True
            mock_dl.assert_called_once()

        # 2. 檔案已存在，秒速通過
        dummy_bin.write_bytes(b"bin" * 1024)
        with patch("zeronexus.brain.bootstrap.download_and_extract_llama_binaries") as mock_dl2:
            res2 = ensure_llama_binaries_ready(bin_dir=str(tmp_path), console_output=False)
            assert res2 is True
            mock_dl2.assert_not_called()

    @pytest.mark.asyncio
    async def test_generate_via_server_mode(self, tmp_path) -> None:
        """測試 LocalGGUFAdapter 的 llama-server HTTP 端點推論調用與結果解析。"""
        adapter = LocalGGUFAdapter(models_dir=str(tmp_path))
        dummy_model = tmp_path / "test.gguf"
        dummy_model.write_bytes(b"dummy")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "測試早安回應"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 8},
        }

        with patch("httpx.AsyncClient.post", return_value=mock_response):
            res = await adapter._generate_via_server(
                server_url="http://127.0.0.1:8089",
                system_instruction="系統提示",
                messages=[{"role": "user", "content": "你好"}],
                max_tokens=20,
                temperature=0.7,
                timeout=30.0,
                model="local/test",
                start_time=time.perf_counter(),
                model_path=str(dummy_model),
            )
            assert res.text == "測試早安回應"
            assert res.provider == "local"
            assert res.completion_tokens == 8

    def test_is_libgomp_available_check(self) -> None:
        """驗證 libgomp1 系統動態庫探測邏輯。"""
        # 於 Linux 測試環境應能正確返回 bool 值
        result = LocalGGUFAdapter._is_libgomp_available()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_generate_prioritizes_internal_python_engine(self) -> None:
        """驗證 LocalGGUFAdapter.generate 優先調用內部相容 Python 實例，不啟動外部程序。"""
        adapter = LocalGGUFAdapter()
        mock_llm = MagicMock()
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"role": "assistant", "content": "內部引擎優先回應"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5},
        }

        with (
            patch.object(adapter, "_get_or_load_llm", return_value=mock_llm),
            patch.object(adapter, "_ensure_server_running") as mock_server,
        ):
            res = await adapter.generate(
                system_instruction="系統提示",
                messages=[{"role": "user", "content": "測試"}],
                model="qwen2.5-0.5b-instruct-q8_0",
                max_tokens=50,
            )
            assert res.text == "內部引擎優先回應"
            # 確保不會啟動外部伺服器程序
            mock_server.assert_not_called()

    def test_q4_k_m_spec_and_resolution(self, tmp_path) -> None:
        """驗證 Q4_K_M 規格匹配、最小位元組門檻與適配器路徑解析。"""
        from zeronexus.brain.bootstrap import match_gguf_spec, GGUF_MODELS_SPEC

        spec_q4 = match_gguf_spec("qwen2.5-0.5b-instruct-q4_k_m")
        assert spec_q4["filename"] == "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        assert spec_q4["min_bytes"] == 300 * 1024 * 1024

        spec_q8 = match_gguf_spec("qwen2.5-0.5b-instruct-q8_0")
        assert spec_q8["filename"] == "qwen2.5-0.5b-instruct-q8_0.gguf"
        assert spec_q8["min_bytes"] == 600 * 1024 * 1024

        # 驗證適配器路徑解析
        adapter = LocalGGUFAdapter(models_dir=str(tmp_path))
        # 建立假的 q4 模型檔案
        q4_file = tmp_path / "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        q4_file.write_bytes(b"dummy_q4")

        resolved = adapter._resolve_model_path("qwen2.5-0.5b-instruct-q4_k_m")
        assert resolved == str(q4_file)

