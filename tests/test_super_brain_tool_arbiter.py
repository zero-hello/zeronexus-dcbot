"""ZeroNexus 超級大腦 - 自主工具意圖仲裁器自動化測試。"""

import pytest
from zeronexus.agent.tool_arbiter import autonomous_tool_arbiter


class TestSuperBrainToolArbiterSuite:
    """測試自主意圖識別與工具預檢執行。"""

    @pytest.mark.asyncio
    async def test_math_arbitration(self) -> None:
        """測試數學運算意圖命中與計算。"""
        results = await autonomous_tool_arbiter.arbitrate_and_execute("請幫我計算 128 * 4 + 512 等於多少？")
        assert "精準數學計算器" in results
        assert "1024" in results["精準數學計算器"]

    @pytest.mark.asyncio
    async def test_system_diagnostics_arbitration(self) -> None:
        """測試主機效能診斷意圖。"""
        results = await autonomous_tool_arbiter.arbitrate_and_execute("可以看一下目前的系統狀態與主機健康嗎")
        assert "主機效能診斷" in results
        assert "CPU使用率" in results["主機效能診斷"]

    @pytest.mark.asyncio
    async def test_cwa_weather_arbitration(self) -> None:
        """測試台灣氣象觀測意圖命中。"""
        results = await autonomous_tool_arbiter.arbitrate_and_execute("請問台北現在的天氣如何？會下雨嗎")
        assert "中央氣象署即時觀測" in results
        assert "臺北" in results["中央氣象署即時觀測"] or "台北" in results["中央氣象署即時觀測"]

    @pytest.mark.asyncio
    async def test_no_intent_passthrough(self) -> None:
        """日常普通話題不應誤觸發工具。"""
        results = await autonomous_tool_arbiter.arbitrate_and_execute("今天心情真好，想跟你聊聊天！")
        assert len(results) == 0
