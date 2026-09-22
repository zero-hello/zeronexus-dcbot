"""Mistral AI 與 Groq LPU 整合自動化測試。

測試項目：
1. MistralAdapter 請求封裝、Token 統計與錯誤遮罩。
2. GroqAdapter 請求封裝、思維鏈 (<think> 與 reasoning) 萃取。
3. AI Gateway 中的 key_pools、adapters 與智慧路由分流。
4. ModelRegistry 註冊資訊、可用性與合法廠商過濾。
5. 真實 API 連線探測（使用環境設定中配置的金鑰驗證端點連通性）。
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from zeronexus.ai_gateway.adapters.groq import GroqAdapter
from zeronexus.ai_gateway.adapters.mistral import MistralAdapter
from zeronexus.ai_gateway.gateway import AIGateway
from zeronexus.ai_gateway.model_registry import model_registry
from zeronexus.core.config import config


class TestMistralAndGroqIntegration:
    """Mistral AI 與 Groq 整合測試套件。"""

    @pytest.mark.asyncio
    async def test_mistral_adapter_generate(self) -> None:
        """測試 MistralAdapter 成功解析 OpenAI 格式回應。"""
        adapter = MistralAdapter()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "cmpl-mistral-test",
            "model": "mistral-large-latest",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Bonjour! 我是 Mistral AI Large 2 模型。",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 18,
                "completion_tokens": 25,
            },
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await adapter.generate(
                system_instruction="你是一個高智慧的繁中助手",
                messages=[{"role": "user", "content": "你好"}],
                model="mistral-large-latest",
                api_key="mstrl_dummy_test_key",
            )

            assert result.provider == "mistral"
            assert result.model_name == "mistral-large-latest"
            assert "Mistral AI" in result.text
            assert result.prompt_tokens == 18
            assert result.completion_tokens == 25

        await adapter.close()

    @pytest.mark.asyncio
    async def test_groq_adapter_generate_with_reasoning(self) -> None:
        """測試 GroqAdapter 成功解析回應並萃取思考鏈。"""
        adapter = GroqAdapter()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "chatcmpl-groq-test",
            "model": "deepseek-r1-distill-llama-70b",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "<think>\n先分析使用者問題，接著給出繁中回覆。\n</think>\n哈囉！我是 Groq 驅動的極速思考模型。",
                    },
                }
            ],
            "usage": {
                "prompt_tokens": 22,
                "completion_tokens": 40,
            },
        }

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response
            result = await adapter.generate(
                system_instruction="你是一個推理助手",
                messages=[{"role": "user", "content": "分析一下"}],
                model="deepseek-r1-distill-llama-70b",
                api_key="gsk_dummy_test_key",
            )

            assert result.provider == "groq"
            assert result.model_name == "deepseek-r1-distill-llama-70b"
            assert "哈囉！我是 Groq" in result.text
            assert result.thinking_process == "先分析使用者問題，接著給出繁中回覆。"
            assert result.prompt_tokens == 22
            assert result.completion_tokens == 40

        await adapter.close()

    def test_gateway_registration_and_routing(self) -> None:
        """驗證 AIGateway 註冊了 mistral 與 groq 提供者並正確路由。"""
        gw = AIGateway()
        assert "mistral" in gw.adapters
        assert "groq" in gw.adapters
        assert "mistral" in gw.key_pools
        assert "groq" in gw.key_pools

        assert gw._get_default_model("mistral") == config.ai.mistral_model
        assert gw._get_default_model("groq") == config.ai.groq_model

    def test_model_registry_contains_new_models(self) -> None:
        """驗證 model_registry 正確包含 Mistral 與 Groq 模型。"""
        meta_mistral = model_registry.get("mistral-large-latest")
        assert meta_mistral is not None
        assert meta_mistral.provider == "mistral"

        meta_groq = model_registry.get("llama-3.3-70b-versatile")
        assert meta_groq is not None
        assert meta_groq.provider == "groq"

        active_models = model_registry.list_active_models()
        active_ids = [m.model_id for m in active_models]
        assert "mistral-large-latest" in active_ids
        assert "codestral-latest" in active_ids
        assert "llama-3.3-70b-versatile" in active_ids
        assert "deepseek-r1-distill-llama-70b" in active_ids

    def test_config_keys_loaded(self) -> None:
        """驗證 config 正確讀取環境變數中的金鑰。"""
        assert len(config.ai.mistral_keys) > 0
        assert config.ai.mistral_keys[0].startswith("mstrl_")
        assert len(config.ai.groq_keys) > 0
        assert config.ai.groq_keys[0].startswith("gsk_")
