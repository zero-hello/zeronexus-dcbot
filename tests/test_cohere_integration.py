"""ZeroNexus Cohere API 整合與優雅降級自動化測試。

測試範疇：
1. 未配置金鑰（或空字串）時，系統完全優雅降級，絕不阻斷流程。
2. Cohere Rerank 多語言重排器功能與錯誤恢復回退。
3. CohereAdapter 在 AI Gateway 中的模型路由與生成解析。
4. 海馬迴記憶檢索與 MemoryService 的 Rerank 整合驗證。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from zeronexus.ai_gateway.adapters.cohere import CohereAdapter
from zeronexus.ai_gateway.gateway import AIGateway
from zeronexus.ai_gateway.model_registry import model_registry
from zeronexus.brain.core import BioBrainCore
from zeronexus.external.cohere_client import CohereService, cohere_service
from zeronexus.services.memory_service import MemoryService


class TestCohereIntegration:
    """Cohere 整合功能與優雅降級測試套件。"""

    def test_cohere_service_fallback_when_unconfigured(self) -> None:
        """驗證金鑰未配置時，is_available 為 False，且 rerank 輸出原始順序降級結果。"""
        empty_service = CohereService(api_key="")
        assert not empty_service.is_available

        docs = ["蘋果", "香蕉", "橘子", "芭樂"]
        # 同步 rerank 降級
        results = empty_service.rerank(query="水果", documents=docs, top_n=3)
        assert len(results) == 3
        assert results[0]["document"] == "蘋果"
        assert results[0]["index"] == 0
        assert results[1]["document"] == "香蕉"

    @pytest.mark.asyncio
    async def test_cohere_service_rerank_async_fallback(self) -> None:
        """驗證非同步 rerank_async 在無金鑰或連線異常時維持優雅降級。"""
        empty_service = CohereService(api_key="")
        docs = ["台北", "台中", "高雄"]
        results = await empty_service.rerank_async(query="城市", documents=docs, top_n=2)
        assert len(results) == 2
        assert results[0]["document"] == "台北"
        assert results[1]["document"] == "台中"

    @pytest.mark.asyncio
    async def test_cohere_service_mock_api_success(self) -> None:
        """模擬 Cohere API 成功回應，驗證重排順序與相關度分數解析。"""
        test_service = CohereService(api_key="co-test-dummy-key")
        assert test_service.is_available

        mock_response_data = {
            "id": "rerank-test-123",
            "results": [
                {"index": 2, "relevance_score": 0.98},
                {"index": 0, "relevance_score": 0.85},
            ],
        }

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = mock_response_data

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_http_response
            docs = ["文件A", "文件B", "文件C"]
            ranked = await test_service.rerank_async(query="測試問題", documents=docs, top_n=2)

            assert len(ranked) == 2
            # 第一名應該是 index 2 (文件C)
            assert ranked[0]["index"] == 2
            assert ranked[0]["document"] == "文件C"
            assert ranked[0]["relevance_score"] == 0.98
            # 第二名應該是 index 0 (文件A)
            assert ranked[1]["index"] == 0
            assert ranked[1]["document"] == "文件A"

    @pytest.mark.asyncio
    async def test_cohere_adapter_generate(self) -> None:
        """驗證 CohereAdapter 生成對話與 token 統計回傳。"""
        adapter = CohereAdapter()
        mock_chat_data = {
            "id": "chat-test-456",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "你好！我是 Cohere Command 模型。"}
                ],
            },
            "usage": {
                "tokens": {
                    "input_tokens": 15,
                    "output_tokens": 28,
                }
            },
        }

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.json.return_value = mock_chat_data

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_http_response
            result = await adapter.generate(
                system_instruction="你是一個有禮貌的助手",
                messages=[{"role": "user", "content": "你好"}],
                model="command-r-plus-08-2024",
                api_key="co-dummy-test-key",
            )

            assert result.provider == "cohere"
            assert result.model_name == "command-r-plus-08-2024"
            assert result.text == "你好！我是 Cohere Command 模型。"
            assert result.prompt_tokens == 15
            assert result.completion_tokens == 28

        await adapter.close()

    def test_model_registry_contains_cohere_models(self) -> None:
        """驗證 model_registry 已註冊 Cohere Command R+ 與 Command R。"""
        meta_plus = model_registry.get("command-r-plus-08-2024")
        assert meta_plus is not None
        assert meta_plus.provider == "cohere"
        assert meta_plus.vendor == "cohere"

        meta_r = model_registry.get("command-r-08-2024")
        assert meta_r is not None
        assert meta_r.provider == "cohere"

        active = model_registry.list_active_models()
        active_ids = [m.model_id for m in active]
        assert "command-r-plus-08-2024" in active_ids
        assert "command-r-08-2024" in active_ids

        # 驗證具備有效金鑰時，get_available_models 包含 Cohere
        mock_pool = MagicMock()
        mock_pool.has_active_keys = True
        mock_pool.get_status_summary.return_value = [{"state": "🟢 正常", "has_paid_quota": True}]
        available = model_registry.get_available_models(key_pools={"cohere": mock_pool})
        avail_ids = [m.model_id for m in available]
        assert "command-r-plus-08-2024" in avail_ids

    def test_ai_gateway_cohere_routing(self) -> None:
        """驗證 AI Gateway 包含 cohere adapter 與 key pool，並能正確指派預設模型。"""
        gw = AIGateway()
        assert "cohere" in gw.adapters
        assert "cohere" in gw.key_pools

        default_model = gw._get_default_model("cohere")
        assert "command-r" in default_model

    @pytest.mark.asyncio
    async def test_memory_service_graceful_search(self) -> None:
        """驗證 MemoryService 搜尋記憶在各環境下皆能穩定工作。"""
        mem_svc = MemoryService(db=None)
        # 即使 db 為 None，search_memory 依然回傳空列表而非拋錯
        res = await mem_svc.search_memory("test_user", "食物", limit=3)
        assert isinstance(res, list)

    def test_brain_core_prompt_capsule_with_cohere(self) -> None:
        """驗證海馬迴大腦核心在組裝膠囊時能夠安全執行。"""
        brain = BioBrainCore()
        capsule = brain.get_prompt_capsule(user_id="test_user_123")
        assert isinstance(capsule, str)
        assert len(capsule) > 0
        assert "【本地大腦即時生理與生物鐘狀態" in capsule
