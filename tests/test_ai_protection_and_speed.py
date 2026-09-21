"""針對 AI 防護功能（每分鐘 5 則速率限制）、官方人格預設值與 Gemini 極速直出模式的單元測試。"""

from unittest.mock import AsyncMock
import pytest
from zeronexus.security.ratelimit import RateLimiter
from zeronexus.models.guild import GuildSettings


def test_ai_message_rate_limit():
    """驗證每個人 1 分鐘內最多發送 5 則訊息給 AI，超過 5 則立即攔截並提供冷卻秒數。"""
    limiter = RateLimiter()
    user_id = 9988776655

    # 前 5 次發言皆應允許通行 (False, 0.0)
    for i in range(5):
        limited, retry_after = limiter.check_ai_message_rate(user_id, max_requests=5, window_seconds=60.0)
        assert limited is False, f"第 {i+1} 次發言不應被攔截"
        assert retry_after == 0.0

    # 第 6 次發言應被精準擋下 (True, retry_after > 0)
    limited, retry_after = limiter.check_ai_message_rate(user_id, max_requests=5, window_seconds=60.0)
    assert limited is True, "第 6 次發言應被速率限制攔截"
    assert retry_after > 0.0, "應回傳大於 0 的冷卻等待秒數"


def test_guild_settings_default_persona():
    """驗證伺服器預設人格必須為官方旗艦人格 normal_persona 而非可愛貓貓 01_cat。"""
    assert GuildSettings.__table__.columns["ai_persona"].default.arg == "normal_persona"


@pytest.mark.asyncio
async def test_gemini_thinking_budget_control():
    """驗證 Gemini Adapter 在日常對話傳入 thinking_budget=0 時，thinkingConfig 將設為 0 以關閉思考加速直出。"""
    from zeronexus.ai_gateway.adapters.gemini import GeminiAdapter
    adapter = GeminiAdapter()

    captured_payload = None

    class DummyResponse:
        status_code = 200
        text = '{"candidates": [{"content": {"role": "model", "parts": [{"text": "哈囉！我是 ZeroNexus！"}]}, "finishReason": "STOP"}]}'
        def json(self):
            return {
                "candidates": [
                    {
                        "content": {
                            "role": "model",
                            "parts": [{"text": "哈囉！我是 ZeroNexus！"}]
                        },
                        "finishReason": "STOP"
                    }
                ]
            }

    class DummyClient:
        async def post(self, url, json=None, headers=None, timeout=None):
            nonlocal captured_payload
            captured_payload = json
            return DummyResponse()

    adapter._get_client = AsyncMock(return_value=DummyClient())

    # 1. 測試日常極速模式：thinking_budget=0
    res = await adapter.generate(
        system_instruction="系統指令",
        messages=[{"role": "user", "content": "你好"}],
        model="gemini-3.1-flash-lite",
        api_key="dummy_key",
        thinking_budget=0,
    )
    assert res.text == "哈囉！我是 ZeroNexus！"
    assert captured_payload is not None
    assert captured_payload["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}

    # 2. 測試深度思考模式：thinking_budget=4096
    await adapter.generate(
        system_instruction="系統指令",
        messages=[{"role": "user", "content": "請深度思考這個數學題"}],
        model="gemini-3.1-flash-lite",
        api_key="dummy_key",
        thinking_budget=4096,
    )
    assert captured_payload["generationConfig"]["thinkingConfig"] == {
        "includeThoughts": True,
        "thinkingBudget": 4096,
    }
