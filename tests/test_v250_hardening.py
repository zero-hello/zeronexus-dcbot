"""ZeroNexus v2.5.0 安全防禦加固、效能優化與健全性測試套件。"""

import pytest
from zeronexus.agent.tool_arbiter import autonomous_tool_arbiter
from zeronexus.brain.semantic_memory import SemanticMemoryRetriever
from zeronexus.security.sanitizer import redact_secrets


class TestV250HardeningSuite:
    """驗證 v2.5.0 安全防禦與效能提升。"""

    @pytest.mark.asyncio
    async def test_tool_arbiter_long_input_resilience(self) -> None:
        """測試超長輸入防禦，確保不會因大量文字造成 ReDoS 或行程卡死。"""
        malicious_input = "幫我計算 " + "1+" * 500 + "1 等於多少？"
        # 算式超過 120 字元，仲裁器應安全略過，不引發例外
        results = await autonomous_tool_arbiter.arbitrate_and_execute(malicious_input)
        assert isinstance(results, dict)
        assert "精準數學計算器" not in results

    @pytest.mark.asyncio
    async def test_tool_arbiter_minecraft_path_traversal_defense(self) -> None:
        """測試 Minecraft 伺服器查詢防範路徑跳脫與惡意字元。"""
        malicious_host = "mc 伺服器 ../../../etc/passwd"
        results = await autonomous_tool_arbiter.arbitrate_and_execute(malicious_host)
        assert "Minecraft 伺服器即時資訊" not in results

    def test_semantic_memory_lru_cache_bounded(self) -> None:
        """測試語意記憶 LRU 快取具備有界上限，防範記憶體無限膨脹。"""
        retriever = SemanticMemoryRetriever()
        retriever._embedding_lru_cache.clear()

        for i in range(1100):
            retriever.encode_text(f"記憶測試語句條目第 {i} 號")

        assert len(retriever._embedding_lru_cache) <= retriever.MAX_CACHE_SIZE
        assert "記憶測試語句條目第 0 號" not in retriever._embedding_lru_cache
        assert "記憶測試語句條目第 1099 號" in retriever._embedding_lru_cache

    def test_secret_redaction_coverage(self) -> None:
        """測試全域脫敏函數能精準遮蔽各類敏感憑證。"""
        sample_log = (
            "連線發生錯誤：API Key 是 sk-proj-1234567890abcdef1234567890abcdef1234567890 "
            "且含有資料庫密碼 postgresql://user:super_secret_password@localhost:5432/db "
            "以及 GitHub Token ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        )
        redacted = redact_secrets(sample_log)
        assert "super_secret_password" not in redacted
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789" not in redacted
        assert "sk-proj-1234567890abcdef1234567890abcdef1234567890" not in redacted
        assert "••••" in redacted

    @pytest.mark.asyncio
    async def test_ai_gateway_parameter_dispatch_no_conflict(self) -> None:
        """測試 AI Gateway 傳入 temperature/top_p/max_tokens/timeout 時無多重值衝突。"""
        from unittest.mock import AsyncMock, MagicMock
        from zeronexus.ai_gateway.gateway import AIGateway
        from zeronexus.ai_gateway.adapters.base import AIResult

        gw = AIGateway()
        mock_adapter = MagicMock()
        captured_kwargs = {}

        async def fake_generate(**kwargs):
            nonlocal captured_kwargs
            captured_kwargs = dict(kwargs)
            return AIResult(
                text="測試回覆",
                model_name=kwargs.get("model", "test-model"),
                provider="gemini",
                latency_ms=12.5,
                prompt_tokens=10,
                completion_tokens=20,
            )

        mock_adapter.generate = AsyncMock(side_effect=fake_generate)
        gw.adapters["gemini"] = mock_adapter

        # 模擬 key pool 有可用 key
        mock_key = MagicMock()
        mock_key.raw_key = "AIzaSyTestMockKey"
        mock_key.masked = "••••Test"
        mock_key.is_available = True
        mock_pool = MagicMock()
        mock_pool.get_available_key.return_value = mock_key
        gw.key_pools["gemini"] = mock_pool

        # 傳遞覆寫參數呼叫 generate_response
        result, notice = await gw.generate_response(
            system_instruction="系統指引",
            messages=[{"role": "user", "content": "你好"}],
            override_model="gemini-2.5-flash",
            temperature=0.85,
            top_p=0.92,
            max_tokens=2048,
            timeout=45.0,
            custom_extra_param="custom_value",
        )

        assert result.text == "測試回覆"
        assert captured_kwargs["temperature"] == 0.85
        assert captured_kwargs["max_tokens"] == 2048
        assert captured_kwargs["timeout"] == 45.0
        assert captured_kwargs["top_p"] == 0.92
        assert captured_kwargs["custom_extra_param"] == "custom_value"
        # 顯式具名引數不應在額外解包中重覆出現
        assert "api_key" in captured_kwargs

