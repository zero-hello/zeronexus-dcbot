"""ZeroNexus Base Module & Lifecycle State Machine.

Lifecycle Transitions:
DISCOVERED -> INITIALIZING -> READY -> RUNNING -> DEGRADED -> DISABLED -> RECOVERING -> RUNNING
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from zeronexus.core.logger import log
from zeronexus.modules.state import ModuleState
from zeronexus.security.permissions import ZNPermissionLevel


@dataclass
class CommandMetadata:
    """Introspective metadata registered in CommandRegistry."""
    name: str
    full_name: str
    description: str
    group_name: str
    module_name: str
    permission_level: ZNPermissionLevel = ZNPermissionLevel.EVERYONE
    cooldown_seconds: float = 2.0
    guild_only: bool = True
    enabled: bool = True
    implemented: bool = True


class BaseModule(ABC):
    """Abstract base class governing domain module lifecycle and isolation."""

    def __init__(self, name: str, display_name: str, description: str) -> None:
        self.name = name
        self.display_name = display_name
        self.description = description
        self.state = ModuleState.DISCOVERED
        self.error_reason: Optional[str] = None
        self.registered_commands: List[CommandMetadata] = []
        self.loaded_at: Optional[float] = None
        self.last_state_change: float = time.time()

    def set_state(self, new_state: ModuleState, reason: Optional[str] = None) -> None:
        old_state = self.state
        self.state = new_state
        self.error_reason = reason
        self.last_state_change = time.time()
        log.info(f"模組「{self.display_name}」狀態切換：{old_state.value} ➔ {new_state.value} {f'({reason})' if reason else ''}")

    @abstractmethod
    async def initialize(self, bot: Any) -> None:
        """Executed during startup to initialize external connections and dependencies."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Executed during shutdown or module deactivation."""
        pass

    async def recover(self, bot: Any) -> bool:
        """Attempts to recover from DEGRADED or DISABLED state."""
        self.set_state(ModuleState.RECOVERING)
        try:
            await self.initialize(bot)
            self.set_state(ModuleState.RUNNING)
            return True
        except Exception as e:
            self.set_state(ModuleState.DISABLED, str(e))
            return False

    def register_command_meta(self, cmd: CommandMetadata) -> None:
        self.registered_commands.append(cmd)

    def health_summary(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "state": self.state.value,
            "icon": self.state.icon,
            "error_reason": self.error_reason,
            "commands_count": len(self.registered_commands),
            "uptime_seconds": round(time.time() - self.loaded_at, 1) if self.loaded_at else 0,
        }
