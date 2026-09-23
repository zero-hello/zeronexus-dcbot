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
