"""ZeroNexus Module Lifecycle State."""

from __future__ import annotations

from enum import Enum


class ModuleState(str, Enum):
    DISCOVERED = "DISCOVERED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    DISABLED = "DISABLED"
    RECOVERING = "RECOVERING"

    @property
    def icon(self) -> str:
        if self == ModuleState.RUNNING:
            return "🟢"
        if self == ModuleState.READY:
            return "🟢"
        if self == ModuleState.DEGRADED:
            return "🟡"
        if self == ModuleState.DISABLED:
            return "🔴"
        return "⚪"
