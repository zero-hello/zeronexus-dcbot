import asyncio

import pytest

from zeronexus.agent.tools import execute_tool


@pytest.mark.asyncio
async def test_regex_tools_keep_valid_match_and_replace_behavior():
    match = await execute_tool("regex_match_test", {"pattern": r"\d+", "text": "items 12 and 34"})
    replaced = await execute_tool(
        "regex_replace_test",
        {"pattern": r"\d+", "replacement": "#", "text": "items 12 and 34"},
    )

    assert match["is_matched"] is True
    assert match["match_count"] == 2
    assert replaced["replaced"] == "items # and #"


@pytest.mark.asyncio
async def test_regex_tools_reject_oversized_inputs():
    result = await execute_tool("regex_match_test", {"pattern": "a", "text": "a" * 4097})
    assert "error" in result
    assert "長度上限" in result["error"]


@pytest.mark.asyncio
async def test_regex_backtracking_timeout_does_not_block_event_loop():
    started = asyncio.get_running_loop().time()
    result = await execute_tool(
        "regex_match_test",
        {"pattern": r"(a+)+$", "text": "a" * 32 + "!"},
    )
    elapsed = asyncio.get_running_loop().time() - started

    assert result == {"error": "正則表達式執行逾時。"}
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_regex_subprocess_concurrency_is_bounded(monkeypatch):
    import importlib

    module = importlib.import_module("zeronexus.agent.tool_catalog")
    monkeypatch.setattr(module, "_REGEX_EXEC_SLOTS", asyncio.Semaphore(1))
    slow = asyncio.create_task(
        execute_tool("regex_match_test", {"pattern": r"(a+)+$", "text": "a" * 32 + "!"})
    )
    try:
        await asyncio.sleep(0.1)
        busy = await execute_tool("regex_match_test", {"pattern": "a", "text": "a"})
        assert busy == {"error": "正則測試服務目前忙碌，請稍後重試。"}
    finally:
        await slow
