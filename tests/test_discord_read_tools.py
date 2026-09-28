from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from zeronexus.agent.discord_read_tools import get_discord_read_tool_specs
from zeronexus.agent.tools import ReadOnlyTool
from zeronexus.engines.channel_inspector import ChannelInspectorEngine


def _member(user_id: int, guild: object, view: bool) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, guild=guild, guild_permissions=SimpleNamespace(view_channel=view))


def test_channel_access_is_current_guild_and_viewer_scoped() -> None:
    bot = _member(10, None, True)
    guild = SimpleNamespace(id=1, me=bot, get_member=lambda user_id: requester if user_id == requester.id else None)
    bot.guild = guild
    requester = _member(20, guild, True)
    requester.guild_permissions.read_message_history = True
    hidden_user = _member(21, guild, False)
    history_denied_user = _member(22, guild, True)
    history_denied_user.guild_permissions.read_message_history = False
    channel = SimpleNamespace(guild=guild, name="public", permissions_for=lambda who: SimpleNamespace(
        view_channel=(who.id in {10, 20, 22}), read_message_history=(who.id in {10, 20})
    ))
    foreign_guild = SimpleNamespace(id=2)

    assert ChannelInspectorEngine.authorize_channel_access(channel, requester, guild) is None
    assert "沒有查看" in ChannelInspectorEngine.authorize_channel_access(channel, hidden_user, guild)
    assert "歷史" in ChannelInspectorEngine.authorize_channel_access(channel, history_denied_user, guild)
    assert "目前互動" in ChannelInspectorEngine.authorize_channel_access(channel, requester, foreign_guild)
    assert "跨伺服器查詢" in ChannelInspectorEngine.authorize_channel_access(channel, None, guild)


@pytest.mark.asyncio
async def test_channel_fetch_fails_closed_without_requester_and_rejects_foreign_guild() -> None:
    bot = _member(10, None, True)
    guild = SimpleNamespace(id=1, me=bot, get_member=lambda user_id: None)
    bot.guild = guild
    history = AsyncMock()
    channel = SimpleNamespace(
        guild=guild,
        name="private",
        history=history,
        permissions_for=lambda who: SimpleNamespace(view_channel=True, read_message_history=True),
    )
    inspector = ChannelInspectorEngine()

    msgs, err = await inspector.fetch_channel_messages(channel, requester=None, expected_guild=guild)
    assert not msgs and err and "跨伺服器" in err
    history.assert_not_called()


@pytest.mark.asyncio
async def test_channel_history_requires_requester_read_history_permission() -> None:
    bot = _member(10, None, True)
    guild = SimpleNamespace(id=1, me=bot, get_member=lambda user_id: requester)
    bot.guild = guild
    requester = _member(20, guild, True)
    requester.guild_permissions.read_message_history = False
    history = AsyncMock()
    channel = SimpleNamespace(
        guild=guild,
        name="limited-history",
        history=history,
        permissions_for=lambda who: SimpleNamespace(
            view_channel=True,
            read_message_history=(who.id == bot.id),
        ),
    )

    messages, error = await ChannelInspectorEngine().fetch_channel_messages(
        channel, requester=requester, expected_guild=guild
    )
    assert messages == []
    assert error and "歷史" in error
    history.assert_not_called()


def test_discord_and_ai_tool_names_are_unique_and_have_handlers() -> None:
    from zeronexus.agent.ai_workflow_tools import get_ai_workflow_tool_specs

    specs = get_discord_read_tool_specs() + get_ai_workflow_tool_specs()
    names = [item["name"] for item in specs]
    assert len(names) >= 55
    assert len(names) == len(set(names))
    assert all(callable(item["handler"]) for item in specs)
    assert all(item["parameters_schema"]["type"] == "object" for item in specs)


@pytest.mark.asyncio
async def test_discord_specs_register_as_real_tools() -> None:
    registry = __import__("zeronexus.agent.tools", fromlist=["AgentToolRegistry"]).AgentToolRegistry()
    initial_count = registry.count()
    for spec in get_discord_read_tool_specs():
        registry.register(ReadOnlyTool(
            name=spec["name"],
            description=spec["description"],
            parameters_desc=spec["parameters_desc"],
            parameters_schema=spec["parameters_schema"],
            handler=spec["handler"],
            category=spec["category"],
        ))
    assert registry.count() >= initial_count
    result = await registry.get_tool("guild_visible_overview").execute(guild=None, user=None, bot=None)
    assert "error" in result


@pytest.mark.asyncio
async def test_registered_catalog_has_at_least_200_unique_real_tools() -> None:
    from zeronexus.agent.tools import AgentToolRegistry

    registry = AgentToolRegistry()
    tools = registry.list_tools()
    assert registry.count() >= 200
    assert len({tool.name for tool in tools}) == registry.count()
    assert all(callable(tool.handler) for tool in tools)
    assert all(tool.parameters_schema.get("type") == "object" for tool in tools)
    assert all(tool.metadata.get("trigger_keywords") for tool in tools)
