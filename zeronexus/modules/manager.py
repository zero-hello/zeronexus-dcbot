"""ZeroNexus Module Manager and Unified Command Registry.

Ensures strict Module Isolation:
If any single module fails to initialize or encounters a runtime crash,
it enters DISABLED/DEGRADED state without crashing the main ZeroNexus bot process.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from zeronexus.core.logger import log
from zeronexus.modules.base import BaseModule, CommandMetadata, ModuleState


class CommandRegistry:
    """Central registry maintaining introspective metadata of all registered Slash Commands."""

    def __init__(self) -> None:
        self._commands: Dict[str, CommandMetadata] = {}

    def register(self, meta: CommandMetadata) -> None:
        self._commands[meta.full_name] = meta

    def get_command(self, full_name: str) -> Optional[CommandMetadata]:
        return self._commands.get(full_name)

    def list_all(self) -> List[CommandMetadata]:
        return list(self._commands.values())

    def count(self) -> int:
        """Returns actual dynamic leaf command count."""
        return len(self._commands)

    def verify_minimum_requirement(self, minimum_threshold: int = 130) -> Dict[str, Any]:
        """Calculates dynamic count and checks minimum compliance."""
        total = self.count()
        passed = total >= minimum_threshold
        return {
            "registered_commands": total,
            "minimum_threshold": minimum_threshold,
            "status": "PASS" if passed else "FAIL",
            "passed": passed,
        }


class ModuleManager:
    """Governs module loading, hot reloading, isolation, and diagnostics."""

    def __init__(self) -> None:
        self.modules: Dict[str, BaseModule] = {}
        self.command_registry = CommandRegistry()
        self._bot: Any = None

    def register_module(self, module: BaseModule) -> None:
        self.modules[module.name] = module
        log.info(f"📦 已註冊核心領域模組：{module.display_name} ({module.name})")

    async def initialize_all(self, bot: Any) -> None:
        """以嚴格故障隔離架構初始化所有已註冊之模組。"""
        self._bot = bot
        log.info(f"⚙️  正在以隔離架構載入 {len(self.modules)} 個 ZeroNexus 核心領域模組...")

        for name, mod in self.modules.items():
            mod.set_state(ModuleState.INITIALIZING)
            try:
                await mod.initialize(bot)
                mod.loaded_at = time.time()
                if mod.state not in (ModuleState.DEGRADED, ModuleState.DISABLED):
                    mod.set_state(ModuleState.RUNNING)
                log.info(f"✅ 模組「{mod.display_name}」載入成功，目前狀態：{mod.state.value}")
            except Exception as e:
                mod.set_state(ModuleState.DISABLED, reason=str(e))
                log.error(f"❌ 模組「{mod.display_name}」初始化失敗：{e}，已安全隔離進入 DISABLED 狀態。", exc_info=True)

        # Collect command metadata into CommandRegistry
        for mod in self.modules.values():
            for cmd_meta in mod.registered_commands:
                self.command_registry.register(cmd_meta)

        # Self audit
        audit = self.command_registry.verify_minimum_requirement(130)
        status_str = "[通過]" if audit["passed"] else "[失敗]"
        log.info(
            f"📋 全域指令註冊稽核：已註冊 {audit['registered_commands']} 條指令 "
            f"（合規門檻：{audit['minimum_threshold']} 條）-> 狀態：{status_str}"
        )

    async def shutdown_all(self) -> None:
        log.info("🛑 正在依序停止所有 ZeroNexus 領域模組...")
        for name, mod in self.modules.items():
            try:
                await mod.shutdown()
                mod.set_state(ModuleState.DISABLED, reason="System shutdown")
            except Exception as e:
                log.error(f"Error shutting down module '{name}': {e}")

    def get_module(self, name: str) -> Optional[BaseModule]:
        return self.modules.get(name)

    def is_module_running(self, name: str) -> bool:
        mod = self.get_module(name)
        return mod is not None and mod.state in (ModuleState.RUNNING, ModuleState.READY)

    async def reload_module(self, name: str) -> bool:
        """Attempts to reload and re-initialize a specific module."""
        mod = self.get_module(name)
        if not mod:
            return False
        log.info(f"Reloading module '{name}'...")
        try:
            await mod.shutdown()
        except Exception as e:
            log.warning(f"Error during shutdown of module '{name}' before reload: {e}")

        return await mod.recover(self._bot)

    def get_health_summary(self) -> Dict[str, Any]:
        return {name: mod.health_summary() for name, mod in self.modules.items()}


# Singleton module manager
module_manager = ModuleManager()
