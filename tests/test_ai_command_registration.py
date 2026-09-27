from discord import app_commands

from zeronexus.modules.ai.cog import AICog


def test_ai_command_group_respects_discord_child_command_limit() -> None:
    assert len(AICog.ai_group.commands) <= 25
    assert len(AICog.ai_group.commands) == 25


def test_conversation_summary_is_registered_as_a_top_level_command() -> None:
    cog_commands = {command.name: command for command in AICog.__cog_app_commands__}

    assert "對話摘要" in cog_commands
    assert isinstance(cog_commands["對話摘要"], app_commands.Command)
    assert "對話摘要" not in {command.name for command in AICog.ai_group.commands}
