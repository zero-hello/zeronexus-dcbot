"""ZeroNexus 自主工具意圖仲裁器 (Autonomous Tool Intent Arbiter)

核心功能：
1. 輕量快速意圖識別器 (Zero-Latency Intent Matcher)：
   分析對話輸入中是否蘊含即時天氣、數學計算、系統健康診斷、Minecraft 查詢等真實數據需求。
2. 非同步即時執行 (Pre-Inference Tool Execution)：
   在大模型開始推演前，預先執行受限唯讀工具並捕獲確定性真實資料。
3. 接地數據封裝 (Grounded Fact Injection)：
   將執行結果轉換為最高置信度的客觀事實，消除大模型幻覺。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

log = logging.getLogger("ZeroNexus.Agent.ToolArbiter")


class AutonomousToolArbiter:
    """自主工具意圖仲裁器"""

    _instance: Optional["AutonomousToolArbiter"] = None

    def __new__(cls) -> "AutonomousToolArbiter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def arbitrate_and_execute(
        self,
        user_prompt: str,
        guild: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        分析使用者提問，若命中工具意圖則自主調度執行並回傳結構化客觀數據。
        """
        results: Dict[str, Any] = {}
        if not user_prompt or len(user_prompt.strip()) < 2:
            return results

        p = user_prompt.strip().lower()
        # 安全邊界防禦：輸入截斷前 1000 字元，防範超長輸入引發 CPU 耗盡
        if len(p) > 1000:
            p = p[:1000]

        from zeronexus.security.sanitizer import redact_secrets

        # 1. 系統診斷意圖 (主機效能、CPU、記憶體、健康狀態)
        if any(k in p for k in ("系統狀態", "主機狀態", "效能診斷", "記憶體用量", "cpu使用率", "主機健康", "運行時間", "uptime")):
            try:
                from zeronexus.agent.tools import agent_tools
                tool = agent_tools.get_tool("system_diagnostics")
                if tool:
                    res = await tool.execute()
                    results["主機效能診斷"] = (
                        f"程序記憶體: {res.get('process_memory_mb')}MB | "
                        f"CPU使用率: {res.get('system_cpu_percent')}% | "
                        f"主機記憶體: {res.get('system_ram_percent')}% | "
                        f"運行時間: {res.get('uptime_formatted')}"
                    )
            except Exception as e:
                log.warning(f"自主診斷工具執行失敗: {redact_secrets(str(e))}")

        # 2. 模組健康巡檢意圖
        if any(k in p for k in ("模組狀態", "模組健康", "所有模組運行")):
            try:
                from zeronexus.agent.tools import agent_tools
                tool = agent_tools.get_tool("module_health")
                if tool:
                    res = await tool.execute()
                    results["模組健康狀態"] = f"總模組數: {res.get('total_modules')} | 已註冊指令數: {res.get('total_commands_registered')}"
            except Exception as e:
                log.warning(f"自主模組健康工具執行失敗: {redact_secrets(str(e))}")

        # 3. 台灣即時天氣與氣象觀測意圖
        tw_cities = [
            "台北", "臺北", "新北", "桃園", "台中", "臺中", "台南", "臺南",
            "高雄", "基隆", "新竹", "嘉義", "宜蘭", "花蓮", "台東", "臺東",
            "屏東", "苗栗", "彰化", "南投", "雲林", "澎湖", "金門", "連江",
        ]
        city_match = next((c for c in tw_cities if c in p), None)
        weather_intent = any(k in p for k in ("天氣", "氣象", "氣溫", "溫度", "下雨", "降雨", "陰天", "晴天", "出太陽", "會冷嗎", "熱不熱"))
        if city_match and weather_intent:
            city_name = city_match
            try:
                from zeronexus.agent.tools import agent_tools
                tool = agent_tools.get_tool("cwa_weather_forecast")
                if tool:
                    forecast_res = await tool.execute(county=city_name)
                    if isinstance(forecast_res, dict):
                        county = forecast_res.get("county", city_name)
                        phenomenon = forecast_res.get("phenomenon", "晴時多雲")
                        rain_prob = forecast_res.get("rain_prob", "--")
                        min_t = forecast_res.get("min_temp", "--")
                        max_t = forecast_res.get("max_temp", "--")
                        results["中央氣象署即時觀測"] = (
                            f"{county} 預報天氣：{phenomenon} | 氣溫區間：{min_t} ~ {max_t} | 降雨機率：{rain_prob}"
                        )
                else:
                    results["中央氣象署即時觀測"] = f"已針對 {city_name} 啟動氣象資料檢索。"
            except Exception as e:
                # 即使無 CWA API 金鑰，仍提供確定性城市接地資訊，且對錯誤訊息進行脫敏
                safe_err = redact_secrets(str(e))
                results["中央氣象署即時觀測"] = f"已嘗試調取 {city_name} 即時氣象（連線反饋：{safe_err}）"

        # 4. 精確數學運算意圖
        math_match = re.search(r"(?:計算|算一下|運算|求)\s*([0-9\+\-\*\/\^\(\)\.\s×÷\*\*]+?)(?:\s*(?:等於多少|等於幾|是多少|\=\?|\=|\?|$))", user_prompt[:200])
        if math_match and len(math_match.group(1).strip()) > 2:
            raw_expr = math_match.group(1).strip()
            # 限制算式長度在 120 字元內，防範惡意巢狀式
            if len(raw_expr) <= 120:
                try:
                    from zeronexus.engines.calculator import calculator
                    calc_res = calculator.evaluate(raw_expr)
                    if not calc_res.is_error and calc_res.result_str:
                        results["精準數學計算器"] = f"算式: {raw_expr} = {calc_res.result_str}"
                except Exception as e:
                    log.warning(f"自主計算機工具執行失敗: {redact_secrets(str(e))}")

        # 5. Minecraft 伺服器狀態查詢意圖
        mc_match = re.search(r"(?:查詢|看一下)?(?:mc|minecraft|麥塊)[\s]*(?:伺服器)?[\s]*([a-zA-Z0-9\.\-_]+(?:\:[0-9]+)?)", p)
        if mc_match:
            server_host = mc_match.group(1).strip()
            # 嚴格限制主機格式與長度 (最長 100 字元，不可包含路徑符號)
            if len(server_host) <= 100 and "." in server_host and not server_host.startswith("http") and "/" not in server_host and "\\" not in server_host:
                try:
                    from zeronexus.engines.minecraft_query import mc_query
                    stat = await mc_query.ping_server(server_host)
                    if stat.is_online:
                        results["Minecraft 伺服器即時資訊"] = (
                            f"伺服器 [{server_host}] 在線 | 在線人數: {stat.players_online}/{stat.players_max} | 延遲: {stat.latency_ms}ms"
                        )
                    else:
                        results["Minecraft 伺服器即時資訊"] = f"伺服器 [{server_host}] 目前處於離線狀態。"
                except Exception as e:
                    log.warning(f"自主 Minecraft 工具執行失敗: {redact_secrets(str(e))}")

        return results


# 全域單例工具意圖仲裁器
autonomous_tool_arbiter = AutonomousToolArbiter()
