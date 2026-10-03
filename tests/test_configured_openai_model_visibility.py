import pytest

from zeronexus.core.config import config
from zeronexus.ui.model_select_view import get_model_select_entries


def test_relay_model_is_hidden_without_credentials(monkeypatch):
    monkeypatch.setattr(config.ai, "openai_keys", [])
    entries = get_model_select_entries()
    assert not any(item["label"].startswith("OpenAI 中轉站") for item in entries)
    assert not any(item["id"] == "openai/gpt-4.1-mini" for item in entries)


def test_configured_relay_model_is_listed_with_capability_description(monkeypatch):
    monkeypatch.setattr(config.ai, "openai_keys", ["test-key"])
    monkeypatch.setattr(config.ai, "openai_model", "relay/custom-model")

    entry = next(item for item in get_model_select_entries() if item["id"] == "openai/relay/custom-model")
    assert "OpenAI 中轉站" in entry["label"]
    assert "Responses API" in entry["tag"]
    assert "Function Calling" in entry["tag"]


def test_registry_resolves_configured_relay_model(monkeypatch):
    from zeronexus.ai_gateway.model_registry import model_registry

    monkeypatch.setattr(config.ai, "openai_keys", ["test-key"])
    monkeypatch.setattr(config.ai, "openai_model", "relay/custom-model")

    resolved = model_registry.resolve("openai/relay/custom-model")
    assert resolved.success
    assert resolved.model is not None
    assert resolved.model.provider == "openai"
    assert "Function Calling" in resolved.model.description


@pytest.mark.asyncio
async def test_switch_autocomplete_includes_configured_relay_description(monkeypatch):
    from zeronexus.modules.ai.cog import switch_model_autocomplete

    monkeypatch.setattr(config.ai, "openai_keys", ["test-key"])
    monkeypatch.setattr(config.ai, "openai_model", "relay/custom-model")

    choices = await switch_model_autocomplete(None, "openai/relay/custom")
    choice = next(item for item in choices if item.value == "openai/relay/custom-model")
    assert "Responses API" in choice.name
    assert "Function Calling" in choice.name
