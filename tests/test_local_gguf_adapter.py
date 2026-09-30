"""Regression tests for removal of local Qwen language models."""

import pytest

from zeronexus.ai_gateway.gateway import AIGateway
from zeronexus.ai_gateway.model_registry import model_registry
from zeronexus.ui.model_select_view import MODEL_SELECT_ENTRIES


def test_local_qwen_models_are_not_listed_or_registered() -> None:
    qwen_local_ids = {
        "qwen2.5-0.5b-instruct-q8_0",
        "local/qwen2.5-0.5b-instruct",
        "qwen2.5-0.5b-instruct-q4_k_m",
        "local/qwen2.5-0.5b-instruct-q4_k_m",
    }
    assert not qwen_local_ids.intersection(item["id"] for item in MODEL_SELECT_ENTRIES)
    assert all(model_registry.get(model_id) is None for model_id in qwen_local_ids)


@pytest.mark.asyncio
async def test_gateway_rejects_removed_local_qwen_model() -> None:
    gateway = AIGateway()
    with pytest.raises(RuntimeError, match="本地語言模型已移除"):
        await gateway.generate_response(
            system_instruction="",
            messages=[{"role": "user", "content": "hello"}],
            override_model="qwen2.5-0.5b-instruct-q8_0",
            allow_tools=False,
        )
