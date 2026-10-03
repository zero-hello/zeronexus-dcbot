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
