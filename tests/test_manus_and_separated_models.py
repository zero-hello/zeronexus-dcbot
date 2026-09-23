"""針對專屬分離模型 (NORMAL_TEXT_MODEL, NORMAL_VISION_MODEL, NORMAL_GEN_IMAGE_MODEL) 與 Manus API 連線支援的單元測試。"""

from unittest.mock import AsyncMock
import pytest
from zeronexus.core.config import config
from zeronexus.ai_gateway.gateway import ai_gateway
from zeronexus.ai_gateway.adapters.manus import ManusAdapter


def test_separated_model_config_defaults():
    """驗證三個核心模型配置正常讀取且名稱正確。"""
    assert config.ai.normal_text_model == "gemini-3.1-flash-lite"
    assert config.ai.normal_vision_model in ("gemini-3.1-flash-lite", "gemini-2.5-flash")
    assert config.ai.normal_gen_image_model in ("imagen-3.0-generate-002", "google/gemini-2.5-flash-image", "gemini-2.5-flash-image")
    assert "manus" in config.ai.manus_model.lower()
    assert "api.manus.ai" in config.ai.manus_base_url


def test_gateway_model_routing_separation():
    """驗證純文字與附帶圖片時，AI Gateway 正確分流至文字模型或視覺模型。"""
    # 純文字對話：使用文字模型
    text_model = ai_gateway._get_default_model("gemini", has_images=False)
    assert text_model == "gemini-3.1-flash-lite"

    # 包含圖片視覺附件：自動分流切換至視覺模型
    vision_model = ai_gateway._get_default_model("gemini", has_images=True)
    assert vision_model in ("gemini-3.1-flash-lite", "gemini-2.5-flash")

    # Manus 提供者：包含 manus
    manus_model = ai_gateway._get_default_model("manus")
    assert "manus" in manus_model.lower()


@pytest.mark.asyncio
async def test_manus_adapter_request_generation():
    """驗證 ManusAdapter 在官方模式下進行真實自然語言對話請求與輪詢。"""
    adapter = ManusAdapter()
    captured_request = {}

    class DummyCreateResponse:
        status_code = 200
        def json(self):
            return {
                "ok": True,
                "task_id": "test_task_123",
                "task_title": "打招呼任務",
                "task_url": "https://manus.im/app/test_task_123",
            }

    class DummyPollResponse:
        status_code = 200
        def json(self):
            return {
                "ok": True,
                "messages": [
                    {
                        "type": "status_update",
                        "status_update": {"agent_status": "stopped", "brief": "Manus 完成回覆"},
                    },
                    {
                        "type": "assistant_message",
                        "assistant_message": {"content": "嗨！很高興見到你，今天有什麼我可以協助你的？"},
                    },
                ],
            }

    class DummyClient:
        async def post(self, url, headers=None, json=None):
            captured_request["url"] = url
            captured_request["headers"] = headers
            captured_request["json"] = json
            return DummyCreateResponse()

        async def get(self, url, headers=None, params=None):
            captured_request["poll_url"] = url
            captured_request["poll_params"] = params
            return DummyPollResponse()

    adapter._get_client = AsyncMock(return_value=DummyClient())

    result = await adapter.generate(
        system_instruction="你是 ZeroNexus，個性開朗活潑",
        messages=[{"role": "user", "content": "嗨"}],
        model="manus",
        api_key="sk-manus-test-key-12345",
        temperature=0.7,
    )

    assert result.provider == "manus"
    assert "manus" in result.actual_model.lower()
    assert result.text == "嗨！很高興見到你，今天有什麼我可以協助你的？"
    assert result.thinking_process == "Manus 完成回覆"

    # 驗證 Header 包含 x-manus-api-key 與正確的 v2 端點
    assert captured_request["headers"]["x-manus-api-key"] == "sk-manus-test-key-12345"
    assert captured_request["url"].endswith("/v2/task.create")
    assert "message" in captured_request["json"]
    assert "agent_profile" in captured_request["json"]
    assert captured_request["poll_url"].endswith("/v2/task.listMessages")
    assert captured_request["poll_params"]["task_id"] == "test_task_123"



def test_manus_in_model_select_entries():
    """驗證 Manus 正式收錄在 Discord 模型下拉選單 MODEL_SELECT_ENTRIES 中。"""
    from zeronexus.ui.model_select_view import MODEL_SELECT_ENTRIES
    manus_entry = next((e for e in MODEL_SELECT_ENTRIES if e["id"] == "manus"), None)
    assert manus_entry is not None
    assert "Manus" in manus_entry["label"]
    assert "30" in manus_entry["tag"]


def test_manus_quota_default_is_thirty():
    """驗證 Manus 預設每日配額為 30 句。"""
    from zeronexus.ai_gateway.quota_service import quota_service
    assert quota_service.get_model_default_limit("manus") == 30
    assert quota_service.get_model_default_limit("manus.ai/manus") == 30


@pytest.mark.asyncio
async def test_manus_quota_exhaustion_blocking():
    """驗證 Manus 額度達到 30 次上限後，用完就沒了（正確阻斷請求）。"""
    from zeronexus.ai_gateway.quota_service import quota_service
    from zeronexus.core.database import db
    from zeronexus.models.user import AIModelQuotaRecord
    from sqlalchemy import select

    await db.initialize()
    test_user_id = 999888777666555  # 非 dev 測試用戶
    today_str = quota_service.get_today_str()

    # 模擬將該用戶 Manus 已使用次數設定為 30
    async with db.session() as s:
        stmt = select(AIModelQuotaRecord).where(
            AIModelQuotaRecord.user_id == test_user_id,
            AIModelQuotaRecord.model_id == "manus",
            AIModelQuotaRecord.date_str == today_str,
        )
        res = await s.execute(stmt)
        rec = res.scalars().first()
        if not rec:
            rec = AIModelQuotaRecord(
                user_id=test_user_id,
                model_id="manus",
                date_str=today_str,
                used_count=30,
                limit_override=30,
            )
            s.add(rec)
        else:
            rec.used_count = 30
        await s.commit()

    allowed, resv, used, limit = await quota_service.reserve_model_quota(test_user_id, "manus")
    assert allowed is False
    assert resv is None
    assert used >= 30
    assert limit == 30


