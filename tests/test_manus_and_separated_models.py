"""針對專屬分離模型 (NORMAL_TEXT_MODEL, NORMAL_VISION_MODEL, NORMAL_GEN_IMAGE_MODEL) 與 Manus API 連線支援的單元測試。"""

from unittest.mock import AsyncMock
import pytest
from zeronexus.core.config import config
from zeronexus.ai_gateway.gateway import ai_gateway
from zeronexus.ai_gateway.adapters.manus import ManusAdapter


def test_separated_model_config_defaults():
    """驗證三個核心模型配置正常讀取且名稱正確。"""
    assert config.ai.normal_text_model == "gemini-3.1-flash-lite"
    assert config.ai.normal_vision_model == "gemini-2.5-flash"
    assert config.ai.normal_gen_image_model == "imagen-3.0-generate-002"
    assert config.ai.manus_model == "manus"
    assert "api.manus.ai" in config.ai.manus_base_url


def test_gateway_model_routing_separation():
    """驗證純文字與附帶圖片時，AI Gateway 正確分流至文字模型或視覺模型。"""
    # 純文字對話：使用文字模型
    text_model = ai_gateway._get_default_model("gemini", has_images=False)
    assert text_model == "gemini-3.1-flash-lite"

    # 包含圖片視覺附件：自動分流切換至視覺模型
    vision_model = ai_gateway._get_default_model("gemini", has_images=True)
    assert vision_model == "gemini-2.5-flash"

    # Manus 提供者：預設為 manus
    manus_model = ai_gateway._get_default_model("manus")
    assert manus_model == "manus"


@pytest.mark.asyncio
async def test_manus_adapter_request_generation():
    """驗證 ManusAdapter 成功發送正確的 Headers、Endpoint 與解析回傳資料。"""
    adapter = ManusAdapter()
    captured_request = {}

    class DummyResponse:
        status_code = 200
        def json(self):
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "哈囉！我是 Manus AI 自主智慧代理人，任務已為您規劃完成。",
                            "reasoning_content": "正在進行多步驟因果推演與工具協調規劃...",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 50,
                    "completion_tokens": 120,
                    "total_tokens": 170,
                }
            }

    class DummyClient:
        async def post(self, url, headers=None, json=None):
            captured_request["url"] = url
            captured_request["headers"] = headers
            captured_request["json"] = json
            return DummyResponse()

    adapter._get_client = AsyncMock(return_value=DummyClient())

    result = await adapter.generate(
        system_instruction="你是專業自主代理",
        messages=[{"role": "user", "content": "請規劃這項自動化任務"}],
        model="manus",
        api_key="sk-manus-test-key-12345",
        temperature=0.7,
    )

    assert result.provider == "manus"
    assert result.actual_model == "manus"
    assert "Manus AI 自主智慧代理人" in result.text
    assert result.thinking_process == "正在進行多步驟因果推演與工具協調規劃..."

    # 驗證 Header 同時包含 Bearer Token 與 x-manus-api-key
    assert captured_request["headers"]["Authorization"] == "Bearer sk-manus-test-key-12345"
    assert captured_request["headers"]["x-manus-api-key"] == "sk-manus-test-key-12345"
    assert captured_request["url"].endswith("/v1/chat/completions")
    assert captured_request["json"]["model"] == "manus"
