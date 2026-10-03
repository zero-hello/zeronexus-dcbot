import json

import httpx
import pytest

from zeronexus.ai_gateway.adapters.openai_responses import OpenAIResponsesAdapter
from zeronexus.core.config import config


@pytest.mark.asyncio
async def test_responses_adapter_executes_function_call_through_relay(monkeypatch):
    requests = []

    async def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(200, json={
                "id": "resp_tool",
                "model": "relay-model",
                "output": [{
                    "type": "function_call",
                    "call_id": "call_123",
                    "name": "calculator",
                    "arguments": '{"expression":"1+1"}',
                }],
                "usage": {"input_tokens": 11, "output_tokens": 4},
            })
        return httpx.Response(200, json={
            "id": "resp_final",
            "model": "relay-model",
            "output": [{
                "type": "message",
                "content": [{"type": "output_text", "text": "結果是 2"}],
            }],
            "usage": {"input_tokens": 20, "output_tokens": 5},
        })

    monkeypatch.setattr(config.ai, "openai_base_url", "https://relay.example/v1")
    adapter = OpenAIResponsesAdapter()
    adapter._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    executed = []

    async def execute(name, args):
        executed.append((name, args))
        return {"value": 2}

    try:
        result = await adapter.generate(
            system_instruction="用繁體中文回答",
            messages=[{"role": "user", "content": "計算 1+1"}],
            model="openai/relay-model",
            api_key="test-key",
            tools=[{
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "計算",
                    "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}},
                },
            }],
            tool_executor=execute,
        )
    finally:
        await adapter.close()

    assert result.text == "結果是 2"
    assert result.provider == "openai"
    assert result.model_name == "openai/relay-model"
    assert result.tool_calls == [{"name": "calculator", "args": {"expression": "1+1"}, "result": {"value": 2}}]
    assert result.prompt_tokens == 31
    assert result.completion_tokens == 9
    assert executed == [("calculator", {"expression": "1+1"})]
    assert requests[0]["tools"] == [{
        "type": "function",
        "name": "calculator",
        "description": "計算",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}},
    }]
    assert any(item.get("type") == "function_call_output" for item in requests[1]["input"])


def test_responses_endpoint_accepts_root_or_full_endpoint():
    assert OpenAIResponsesAdapter._endpoint("https://relay.example/v1") == "https://relay.example/v1/responses"
    assert OpenAIResponsesAdapter._endpoint("https://relay.example/v1/responses") == "https://relay.example/v1/responses"


def test_registered_function_calling_inventory_exceeds_200():
    from zeronexus.agent.tools import agent_tools

    assert agent_tools.count() >= 200
    assert len(agent_tools.to_openai_tools()) == agent_tools.count()


@pytest.mark.asyncio
async def test_gateway_routes_openai_model_and_projects_function_tools(monkeypatch):
    from zeronexus.ai_gateway.adapters.base import AIResult
    from zeronexus.ai_gateway.gateway import AIGateway

    monkeypatch.setattr(config.ai, "openai_keys", ["test-openai-key"])
    gateway = AIGateway()
    captured = {}

    class FakeAdapter:
        async def generate(self, **kwargs):
            captured.update(kwargs)
            return AIResult(
                text="已完成",
                model_name="openai/relay-model",
                provider="openai",
                latency_ms=1,
            )

    gateway.adapters["openai"] = FakeAdapter()
    result, _ = await gateway.generate_response(
        system_instruction="用繁體中文回答",
        messages=[{"role": "user", "content": "查詢台北目前天氣"}],
        override_model="openai/relay-model",
        allow_fallback=False,
    )

    assert result.provider == "openai"
    assert captured["model"] == "openai/relay-model"
    assert 1 <= len(captured["tools"]) <= 8


@pytest.mark.asyncio
async def test_forced_tool_route_uses_capable_provider_without_fallback(monkeypatch):
    from zeronexus.ai_gateway.adapters.base import AIResult
    from zeronexus.ai_gateway.gateway import AIGateway
    from zeronexus.agent.tools import agent_tools
    from zeronexus.intelligence.dynamic_projector import DynamicToolProjector

    monkeypatch.setattr(config.ai, "deepseek_keys", ["test-deepseek-key"])
    monkeypatch.setattr(config.ai, "gemini_keys", ["test-gemini-key"])
    monkeypatch.setattr(config.ai, "openrouter_keys", [])
    monkeypatch.setattr(config.ai, "openai_keys", [])
    monkeypatch.setattr(config.ai, "fallback_providers", ["gemini", "deepseek"])
    monkeypatch.setattr(DynamicToolProjector, "requires_tool", staticmethod(lambda _prompt: True))
    gateway = AIGateway()
    captured = {}

    class FakeAdapter:
        async def generate(self, **kwargs):
            captured.update(kwargs)
            return AIResult(text="完成", model_name="gemini-3.1-flash-lite", provider="gemini", latency_ms=1)

    gateway.adapters["gemini"] = FakeAdapter()
    tool = agent_tools.get_tool("calculator")
    assert tool is not None
    result, _ = await gateway.generate_response(
        system_instruction="回答使用者",
        messages=[{"role": "user", "content": "立刻計算 1+1"}],
        override_model="deepseek",
        allow_fallback=False,
        tools=[tool.to_openai_tool_schema()],
    )

    assert result.provider == "gemini"
    assert captured["model"].startswith("gemini")
    assert captured["tools"]


@pytest.mark.asyncio
async def test_reasoning_model_omits_temperature_and_returns_refusal_text(monkeypatch):
    captured = {}

    async def handler(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={
            "id": "resp_refusal",
            "model": "o3",
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "無法協助這項請求。"}]}],
            "usage": {"input_tokens": 2, "output_tokens": 3},
        })

    monkeypatch.setattr(config.ai, "openai_base_url", "https://relay.example/v1")
    adapter = OpenAIResponsesAdapter()
    adapter._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        result = await adapter.generate(
            system_instruction="",
            messages=[{"role": "user", "content": "受限制內容"}],
            model="openai/o3",
            api_key="test-key",
            temperature=0.7,
        )
    finally:
        await adapter.close()

    assert "temperature" not in captured
    assert result.text == "無法協助這項請求。"


@pytest.mark.asyncio
async def test_incomplete_response_is_not_reported_as_success(monkeypatch):
    async def handler(_request):
        return httpx.Response(200, json={
            "id": "resp_incomplete",
            "model": "relay-model",
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [],
        })

    monkeypatch.setattr(config.ai, "openai_base_url", "https://relay.example/v1")
    adapter = OpenAIResponsesAdapter()
    adapter._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match="未完成"):
            await adapter.generate(
                system_instruction="",
                messages=[{"role": "user", "content": "hello"}],
                model="relay-model",
                api_key="test-key",
            )
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_tool_call_at_round_limit_is_not_empty_success(monkeypatch):
    async def handler(_request):
        return httpx.Response(200, json={
            "id": "resp_tool_limit",
            "model": "relay-model",
            "status": "completed",
            "output": [{"type": "function_call", "call_id": "call_1", "name": "calculator", "arguments": "{}"}],
        })

    monkeypatch.setattr(config.ai, "openai_base_url", "https://relay.example/v1")
    adapter = OpenAIResponsesAdapter()
    adapter._http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(RuntimeError, match="最大工具回合數"):
            await adapter.generate(
                system_instruction="",
                messages=[{"role": "user", "content": "calculate"}],
                model="relay-model",
                api_key="test-key",
                tools=[{"type": "function", "function": {"name": "calculator", "parameters": {"type": "object"}}}],
                tool_executor=lambda *_args: None,
                max_tool_rounds=0,
            )
    finally:
        await adapter.close()
