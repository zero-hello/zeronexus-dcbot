"""單元測試：本地 GGUF 推論引擎、適配器整合與模型選單項次驗證。"""

import os
import pytest
from unittest.mock import MagicMock, patch

from zeronexus.ai_gateway.adapters.local_gguf import LocalGGUFAdapter
from zeronexus.ai_gateway.model_registry import model_registry
from zeronexus.ui.model_select_view import MODEL_SELECT_ENTRIES


class TestLocalGGUFIntegration:
    """本地 GGUF 模型各項整合邏輯測試。"""

    def test_model_select_entries_order_and_gemini25_removed(self) -> None:
        """驗證選單中第二項為 GGUF 本地模型，且完全移除 Gemini 2.5 系列。"""
        # 1. 總數必須符合 Discord Select Menu 限制 (<= 25)
        assert len(MODEL_SELECT_ENTRIES) <= 25

        # 2. 第二個選項 (index 1) 必須為 qwen2.5-0.5b-instruct-q8_0
        assert MODEL_SELECT_ENTRIES[1]["id"] == "qwen2.5-0.5b-instruct-q8_0"
        assert "GGUF" in MODEL_SELECT_ENTRIES[1]["label"]

        # 3. 確保所有 Gemini 2.5 模型皆已自選單中移除
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
        """驗證模型註冊表中已正確註冊該本地模型及其元數據。"""
        meta = model_registry.get("qwen2.5-0.5b-instruct-q8_0")
        assert meta is not None
        assert meta.provider == "local"
        assert meta.vendor == "qwen"
        assert meta.is_free is True

        # 別名亦應可查詢
        alias_meta = model_registry.get("local/qwen2.5-0.5b-instruct")
        assert alias_meta is not None
        assert alias_meta.provider == "local"

    def test_local_gguf_adapter_file_not_found(self, tmp_path) -> None:
        """測試當 GGUF 模型檔案不存在時，適配器能拋出友善的 FileNotFoundError。"""
        empty_dir = str(tmp_path / "models")
        os.makedirs(empty_dir, exist_ok=True)

        adapter = LocalGGUFAdapter(models_dir=empty_dir)
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

        # 模擬 _get_or_load_llm 回傳 mock_llm
        with patch.object(adapter, "_get_or_load_llm", return_value=mock_llm):
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
