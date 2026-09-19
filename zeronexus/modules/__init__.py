"""ZeroNexus Domain Modules Package.

Registers and coordinates domain modules and top-level commands.
"""

from zeronexus.modules.base import BaseModule, ModuleState, CommandMetadata
from zeronexus.modules.manager import module_manager, CommandRegistry


def register_all_modules() -> None:
    """Registers all domain modules into the central ModuleManager."""
    from zeronexus.modules.moderation.cog import ModerationModule
    from zeronexus.modules.server.cog import ServerModule
    from zeronexus.modules.tools.cog import ToolsModule
    from zeronexus.modules.ai.cog import AIModule
    from zeronexus.modules.entertainment.cog import EntertainmentModule
    from zeronexus.modules.interactions.cog import InteractionsModule
    from zeronexus.modules.settings.cog import SettingsModule
    from zeronexus.modules.system.cog import SystemModule
    from zeronexus.modules.standalone.cog import StandaloneModule
    from zeronexus.modules.agent.cog import AgentModule
    from zeronexus.modules.community.cog import CommunityModule
    from zeronexus.modules.tickets.cog import TicketsModule
    from zeronexus.modules.master.cog import MasterModule

    if "moderation" not in module_manager.modules:
        module_manager.register_module(ModerationModule())
    if "server" not in module_manager.modules:
        module_manager.register_module(ServerModule())
    if "tools" not in module_manager.modules:
        module_manager.register_module(ToolsModule())
    if "ai" not in module_manager.modules:
        module_manager.register_module(AIModule())
    if "entertainment" not in module_manager.modules:
        module_manager.register_module(EntertainmentModule())
    if "interactions" not in module_manager.modules:
        module_manager.register_module(InteractionsModule())
    if "settings" not in module_manager.modules:
        module_manager.register_module(SettingsModule())
    if "system" not in module_manager.modules:
        module_manager.register_module(SystemModule())
    if "standalone" not in module_manager.modules:
        module_manager.register_module(StandaloneModule())
    if "agent" not in module_manager.modules:
        module_manager.register_module(AgentModule())
    if "community" not in module_manager.modules:
        module_manager.register_module(CommunityModule())
    if "tickets" not in module_manager.modules:
        module_manager.register_module(TicketsModule())
    if "master" not in module_manager.modules:
        module_manager.register_module(MasterModule())


__all__ = [
    "BaseModule",
    "ModuleState",
    "CommandMetadata",
    "module_manager",
    "CommandRegistry",
    "register_all_modules",
]
