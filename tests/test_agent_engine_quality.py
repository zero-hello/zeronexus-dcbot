from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from zeronexus.agent.engine import AgentEngine, AgentStep
from zeronexus.agent.tools import ReadOnlyTool
from zeronexus.core.stats import StatsTracker


def test_stats_tracker_records_tool_quality_metrics() -> None:
    stats = StatsTracker()
    stats.record_tool_execution("tool_a", 20, success=True)
    stats.record_tool_execution("tool_a", 40, success=False, timed_out=True)

    summary = stats.get_tool_execution_summary()
    assert summary[0]["tool"] == "tool_a"
    assert summary[0]["calls"] == 2
    assert summary[0]["success_rate_pct"] == 50
    assert summary[0]["timeouts"] == 1


@pytest.mark.asyncio
async def test_agent_never_runs_unprojected_tools() -> None:
    engine = AgentEngine()
    safe_tool = ReadOnlyTool(
        name="calculator",
        description="calc",
        parameters_desc="expression",
        handler=AsyncMock(return_value={"result": 42}),
    )
    engine.tools = type("Registry", (), {
        "get_tool": lambda self, name: safe_tool if name == "calculator" else None,
        "list_tools": lambda self: [safe_tool],
    })()

    async def fake_plan(goal, allowed_tool_names=None):
        return [AgentStep(step_id=1, title="not allowed", tool_name="guild_visible_channels", parameters={})]

    engine._plan_task = fake_plan
    with (
        patch("zeronexus.agent.engine.DynamicToolProjector.project") as project,
        patch("zeronexus.agent.engine.ai_gateway.generate_response", new=AsyncMock(return_value=(SimpleNamespace(text="report"), None))),
    ):
        project.return_value.tools = [type("Projected", (), {"name": "calculator"})()]
        result = await engine.run_task("general analysis", timeout_seconds=10)

    assert result.steps[0].status == "FAILED"
    assert "未投影" in (result.steps[0].error or "")
    safe_tool.handler.assert_not_awaited()
