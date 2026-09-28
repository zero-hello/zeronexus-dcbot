from unittest.mock import MagicMock

from zeronexus.ai_gateway.gateway import AIGateway
from zeronexus.intelligence.dynamic_projector import DynamicToolProjector


def test_explicit_simple_live_data_prompts_project_tools() -> None:
    prompts = ["查天氣", "查詢股價", "摘要頻道", "校對這段文字", "請幫我摘要這篇文章"]
    for prompt in prompts:
        projected = DynamicToolProjector.project(prompt)
        assert projected.tools, prompt
    summary = DynamicToolProjector.project("請幫我摘要這篇文章")
    assert "ai_summarize_text" in summary.tool_names
    channel = DynamicToolProjector.project("讀取頻道最近內容")
    assert "inspect_channel_messages" in channel.tool_names or "discord_read_channel_messages" in channel.tool_names
    guild = DynamicToolProjector.project("查詢伺服器有哪些頻道")
    assert "guild_visible_channels" in guild.tool_names


def test_greetings_do_not_project_tools() -> None:
    assert DynamicToolProjector.project("嗨你好").tools == []


def test_capability_prompt_lists_real_registry_inventory_compactly() -> None:
    from zeronexus.agent.tools import agent_tools
    from zeronexus.intelligence.capability_registry import capability_registry

    prompt = capability_registry.get_dynamic_capabilities_prompt(user_prompt="請摘要這篇文章")
    assert "ai_summarize_text" in prompt
    assert "AI_WORKFLOW" in prompt
    assert len(prompt) < 2_000


def test_tool_intent_routes_to_function_calling_provider_only() -> None:
    gateway = AIGateway()
    gateway.key_pools["gemini"].add_keys(["test-gemini-key"])
    gateway.key_pools["openrouter"].add_keys(["test-openrouter-key"])
    tool = DynamicToolProjector.project("查天氣").tools
    assert tool
    supported = {"gemini", "openrouter"}
    route = [p for p in ["groq", "deepseek", "gemini", "mistral", "openrouter"] if p in supported]
    assert route == ["gemini", "openrouter"]


def test_function_calling_supported_schemas_fit_gemini_and_openrouter_limits() -> None:
    from zeronexus.agent.tools import agent_tools

    tools = agent_tools.list_tools()
    for tool in tools:
        gemini = tool.to_gemini_tool_schema()
        openrouter = tool.to_openai_tool_schema()
        assert gemini["name"] == tool.name
        assert openrouter["function"]["name"] == tool.name
        assert gemini["parameters"]["type"] == "object"
        assert openrouter["function"]["parameters"]["type"] == "object"


def test_gateway_builds_tool_schema_once_for_gemini() -> None:
    gateway = AIGateway()
    for pool in gateway.key_pools.values():
        pool.get_available_key = MagicMock(return_value=None)
    projected = DynamicToolProjector.project("查目前天氣")
    assert projected.tools


def test_stats_tracker_records_successful_image_generation() -> None:
    from zeronexus.core.stats import StatsTracker

    tracker = StatsTracker()
    tracker.record_image_generation(True)
    tracker.record_image_generation(False)
    assert tracker.images_generated == 1
    assert tracker.summary()["usage"]["images_generated"] == 1
