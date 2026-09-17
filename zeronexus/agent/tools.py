"""ZeroNexus Restricted Read-Only Agent Tool Registry.

Enforces strict read-only execution boundaries:
AI Agent is strictly forbidden from mutating guild configuration, banning/kicking members,
or modifying databases. Only read-only probes, calculation engines, and diagnostics are allowed.
Equipped with 130+ specialized deterministic tools across 12 functional domains.
"""

from __future__ import annotations

import json
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

from zeronexus.agent.tool_catalog import get_all_tool_specs
from zeronexus.core.logger import log


class ReadOnlyTool:
    """Wraps an introspectable read-only agent tool with performance and audit logging."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters_desc: str,
        handler: Callable[..., Coroutine[Any, Any, Dict[str, Any]]],
        parameters_schema: Optional[Dict[str, Any]] = None,
        category: str = "一般工具",
    ) -> None:
        self.name = name
        self.description = description
        self.parameters_desc = parameters_desc
        self.handler = handler
        self.parameters_schema = parameters_schema or {"type": "object", "properties": {}}
        self.category = category

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        t0 = time.perf_counter()
        clean_args = {
            k: str(v) if not isinstance(v, (int, float, bool, list, dict, type(None))) else v
            for k, v in kwargs.items()
            if k != "guild"
        }
        args_repr = json.dumps(clean_args, ensure_ascii=False, default=str)
        if len(args_repr) > 100:
            args_repr = args_repr[:97] + "..."
        try:
            res = await self.handler(**kwargs)
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            log.info(
                f"[🛠️ 工具調用 / TOOL CALL] 執行: {self.name} | 參數: {args_repr} | 耗時: {latency_ms}ms | 狀態: [成功]"
            )
            return res
        except Exception as e:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            log.error(
                f"[🛠️ 工具調用 / TOOL CALL] 執行: {self.name} | 參數: {args_repr} | 耗時: {latency_ms}ms | 狀態: [失敗] | 錯誤: {e}"
            )
            raise

    def to_openai_tool_schema(self) -> Dict[str, Any]:
        """Exports standard OpenAPI/JSON Schema for model function calling."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    def to_gemini_tool_schema(self) -> Dict[str, Any]:
        """Exports standard Gemini Function Calling schema declaration."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }


class AgentToolRegistry:
    """Central registry of strictly read-only diagnostics and utility tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, ReadOnlyTool] = {}
        self._register_default_tools()

    def register(self, tool: ReadOnlyTool) -> None:
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Optional[ReadOnlyTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[ReadOnlyTool]:
        return list(self._tools.values())

    def count(self) -> int:
        return len(self._tools)

    def list_by_category(self, category: str) -> List[ReadOnlyTool]:
        return [t for t in self._tools.values() if t.category == category]

    def get_categories(self) -> List[str]:
        seen = set()
        cats = []
        for t in self._tools.values():
            if t.category not in seen:
                seen.add(t.category)
                cats.append(t.category)
        return cats

    def get_tools_prompt_summary(self) -> str:
        """Generates a concise categorized tools summary for Agent prompt context."""
        lines = []
        for cat in self.get_categories():
            cat_tools = self.list_by_category(cat)
            lines.append(f"### 【{cat}】({len(cat_tools)}項)")
            for t in cat_tools:
                lines.append(f"- **{t.name}**: {t.description} (參數: {t.parameters_desc})")
        return "\n".join(lines)

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        return [t.to_openai_tool_schema() for t in self._tools.values()]

    def to_gemini_tools(self) -> List[Dict[str, Any]]:
        return [t.to_gemini_tool_schema() for t in self._tools.values()]

    def get_tool_schema(self, name: str, format: str = "openai") -> Optional[Dict[str, Any]]:
        tool = self.get_tool(name)
        if not tool:
            return None
        if format.lower() == "gemini":
            return tool.to_gemini_tool_schema()
        return tool.to_openai_tool_schema()

    def _register_default_tools(self) -> None:
        specs = get_all_tool_specs()
        for s in specs:
            tool = ReadOnlyTool(
                name=s["name"],
                category=s.get("category", "一般工具"),
                description=s["description"],
                parameters_desc=s["parameters_desc"],
                parameters_schema=s.get("parameters_schema"),
                handler=s["handler"],
            )
            self.register(tool)


# Master singleton instance
agent_tools = AgentToolRegistry()


async def execute_tool(name: str, args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
    """Safely executes a registered tool by name with arguments."""
    tool = agent_tools.get_tool(name)
    if not tool:
        return {"error": f"Tool '{name}' is not registered in agent tool catalog."}
    merged_args = dict(args or {})
    merged_args.update(kwargs)
    return await tool.execute(**merged_args)


__all__ = ["ReadOnlyTool", "AgentToolRegistry", "agent_tools", "execute_tool"]
