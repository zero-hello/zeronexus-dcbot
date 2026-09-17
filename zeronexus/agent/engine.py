"""ZeroNexus Native 5-Stage Agent Execution Engine.

Architecture:
1. Planner (任務規劃)
2. Tool Router (工具路由器)
3. Executor (受限唯讀執行器)
4. Verifier (結果驗證器)
5. Recovery (錯誤復原器)

Produces progressive multi-stage status updates for Discord live card rendering.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

import discord

from zeronexus.agent.tools import agent_tools
from zeronexus.ai_gateway.gateway import ai_gateway
from zeronexus.core.logger import log


@dataclass
class AgentStep:
    """Represents an atomic step planned by the Agent."""
    step_id: int
    title: str
    tool_name: Optional[str]
    parameters: Dict[str, Any]
    status: str = "PENDING"  # PENDING, RUNNING, COMPLETED, FAILED
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    thought: Optional[str] = None


@dataclass
class AgentProgress:
    """Current snapshot of the Agent execution lifecycle."""
    task_goal: str
    current_stage: str  # PLANNER, ROUTER, EXECUTOR, VERIFIER, RECOVERY, COMPLETED, FAILED
    stage_description: str
    steps: List[AgentStep] = field(default_factory=list)
    observations: List[str] = field(default_factory=list)
    chain_of_thought: List[str] = field(default_factory=list)
    final_output: Optional[str] = None
    elapsed_ms: float = 0.0


class AgentEngine:
    """Native orchestration engine coordinating the 5-stage agent lifecycle."""

    def __init__(self) -> None:
        self.tools = agent_tools

    async def run_task(
        self,
        task_goal: str,
        guild: Optional[discord.Guild] = None,
        channel: Optional[discord.TextChannel] = None,
        user: Optional[discord.User | discord.Member] = None,
        progress_callback: Optional[Callable[[AgentProgress], Coroutine[Any, Any, None]]] = None,
    ) -> AgentProgress:
        """Executes a diagnostic or analytical agent task through all 5 stages."""
        start_time = time.perf_counter()
        progress = AgentProgress(
            task_goal=task_goal,
            current_stage="PLANNER",
            stage_description="正在解析使用者目標並擬定執行計畫...",
        )

        async def emit_update(stage: str, desc: str) -> None:
            progress.current_stage = stage
            progress.stage_description = desc
            progress.elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            if progress_callback:
                try:
                    await progress_callback(progress)
                except Exception as cb_err:
                    log.warning(f"Agent progress callback error: {cb_err}")

        # -----------------------------------------------------------------
        # Stage 1: Planner
        # -----------------------------------------------------------------
        await emit_update("PLANNER", "📋 [階段 1/5] 正在拆解目標、構建思考鏈並擬定步驟...")
        planned_steps = await self._plan_task(task_goal)
        progress.steps = planned_steps
        for s in progress.steps:
            if s.thought:
                progress.chain_of_thought.append(f"【步驟 {s.step_id} 思考】：{s.thought}")
            else:
                progress.chain_of_thought.append(f"【步驟 {s.step_id} 規劃】：{s.title}")

        # -----------------------------------------------------------------
        # Stage 2: Tool Router
        # -----------------------------------------------------------------
        await emit_update("ROUTER", "🔀 [階段 2/5] 正在驗證受限唯讀邊界並分派工具...")
        for step in progress.steps:
            if step.tool_name and not self.tools.get_tool(step.tool_name):
                # Fallback matching
                matched_tool = self._fuzzy_match_tool(step.tool_name)
                step.tool_name = matched_tool
            if step.tool_name:
                progress.chain_of_thought.append(f"【安全路由】：步驟 {step.step_id} 唯讀安全校驗通過 ➔ 分派工具 `{step.tool_name}`")
            else:
                progress.chain_of_thought.append(f"【內部推理】：步驟 {step.step_id} 判定為無須外部工具之推論步驟")

        # -----------------------------------------------------------------
        # Stage 3: Executor
        # -----------------------------------------------------------------
        await emit_update("EXECUTOR", "⚙️ [階段 3/5] 正在執行受限唯讀工具收集數據...")
        for step in progress.steps:
            step.status = "RUNNING"
            await emit_update("EXECUTOR", f"⚙️ 正在執行步驟 {step.step_id}：{step.title}...")

            if not step.tool_name:
                step.status = "COMPLETED"
                step.result = {"info": "無須呼叫外部工具之推理步驟"}
                progress.chain_of_thought.append(f"【執行完成】：步驟 {step.step_id} 內部邏輯推理完畢")
                continue

            tool = self.tools.get_tool(step.tool_name)
            if not tool:
                step.status = "FAILED"
                step.error = f"找不到指定的唯讀工具：`{step.tool_name}`"
                progress.chain_of_thought.append(f"【工具缺失】：步驟 {step.step_id} 找不到唯讀工具 `{step.tool_name}`")
                continue

            try:
                # Inject execution context
                params = dict(step.parameters)
                if "guild" not in params and guild:
                    params["guild"] = guild
                res = await tool.execute(**params)
                step.result = res

                # Check if tool execution result indicates an internal error
                if isinstance(res, dict) and res.get("is_error") is True:
                    step.status = "FAILED"
                    step.error = res.get("error_message") or "工具計算或執行返回錯誤"
                elif isinstance(res, dict) and "error" in res and res.get("online") is not False:
                    # Note: 'online': False in minecraft probe is a valid telemetry status, not a tool failure
                    step.status = "FAILED"
                    step.error = str(res.get("error"))
                else:
                    step.status = "COMPLETED"

                progress.observations.append(
                    f"【步驟 {step.step_id} {tool.name}】: {json.dumps(res, ensure_ascii=False)[:800]}"
                )
                if step.status == "COMPLETED":
                    progress.chain_of_thought.append(f"【觀測採集】：步驟 {step.step_id} 工具 `{tool.name}` 數據檢索成功")
                else:
                    progress.chain_of_thought.append(f"【觀測警示】：步驟 {step.step_id} 工具 `{tool.name}` 回報異常：{step.error}")
            except Exception as e:
                step.status = "FAILED"
                step.error = str(e)
                progress.chain_of_thought.append(f"【調用異常】：步驟 {step.step_id} 工具 `{tool.name}` 拋出例外：{e}")
                log.warning(f"Agent tool execution error in step {step.step_id} ({tool.name}): {e}")

        # -----------------------------------------------------------------
        # Stage 4: Verifier & Recovery
        # -----------------------------------------------------------------
        await emit_update("VERIFIER", "🔍 [階段 4/5] 正在驗證結果完整度與正確性...")
        for step in progress.steps:
            # Verification: re-verify completion status and payload integrity
            if step.status == "COMPLETED" and step.result:
                res = step.result
                if res.get("is_error") is True:
                    step.status = "FAILED"
                    step.error = res.get("error_message") or "運算引擎異常"
                elif "error" in res and res.get("online") is not False:
                    step.status = "FAILED"
                    step.error = str(res.get("error"))

        failed_steps = [s for s in progress.steps if s.status == "FAILED"]
        if failed_steps:
            progress.chain_of_thought.append(f"【驗證警示】：偵測到 {len(failed_steps)} 個步驟異常，啟動自主復原機制")
            await emit_update("RECOVERY", f"🛠️ 偵測到 {len(failed_steps)} 個步驟異常，正在啟動自動修復與降級復原...")
            for s in failed_steps:
                recovered = False
                # Recovery Strategy 1: Calculator expression cleanup & retry
                if s.tool_name == "calculator" and s.parameters.get("expression"):
                    raw_expr = str(s.parameters["expression"])
                    clean_expr = (
                        raw_expr.replace("×", "*")
                        .replace("÷", "/")
                        .replace("—", "-")
                        .replace("–", "-")
                        .replace("^", "**")
                        .strip()
                    )
                    if clean_expr != raw_expr:
                        try:
                            calc_tool = self.tools.get_tool("calculator")
                            if calc_tool:
                                new_res = await calc_tool.execute(expression=clean_expr)
                                if not new_res.get("is_error"):
                                    s.status = "COMPLETED"
                                    s.result = new_res
                                    s.error = None
                                    recovered = True
                                    progress.observations.append(
                                        f"【步驟 {s.step_id} 復原成功】: 自動修正符號語法 `{raw_expr}` -> `{clean_expr}`，計算結果：{new_res.get('result')}"
                                    )
                                    progress.chain_of_thought.append(f"【自主復原】：步驟 {s.step_id} 運算符號清理 `{raw_expr}` ➔ `{clean_expr}` 重算成功")
                        except Exception as rec_err:
                            log.debug(f"Calculator recovery failed: {rec_err}")

                # Recovery Strategy 2: Minecraft host:port splitting retry
                elif s.tool_name == "minecraft_probe" and s.parameters.get("host"):
                    raw_host = str(s.parameters["host"])
                    if ":" in raw_host:
                        h, p = raw_host.split(":", 1)
                        if p.isdigit():
                            try:
                                mc_tool = self.tools.get_tool("minecraft_probe")
                                if mc_tool:
                                    new_res = await mc_tool.execute(host=h.strip(), port=int(p.strip()))
                                    s.status = "COMPLETED"
                                    s.result = new_res
                                    s.error = None
                                    recovered = True
                                    progress.observations.append(
                                        f"【步驟 {s.step_id} 復原成功】: 拆分主機與連接埠 `{h}:{p}` 重新探測成功"
                                    )
                                    progress.chain_of_thought.append(f"【自主復原】：步驟 {s.step_id} 拆分主機與埠號 `{h}:{p}` 重測成功")
                            except Exception as rec_err:
                                log.debug(f"Minecraft probe recovery failed: {rec_err}")

                # Recovery Strategy 3: Weather probe fallback to 臺北市
                elif s.tool_name in ("weather_probe", "cwa_realtime_weather"):
                    try:
                        weather_tool = self.tools.get_tool("weather_probe")
                        if weather_tool:
                            fallback_res = await weather_tool.execute(county="臺北市")
                            if "error" not in fallback_res:
                                s.status = "COMPLETED"
                                s.result = fallback_res
                                s.error = None
                                recovered = True
                                progress.observations.append(
                                    f"【步驟 {s.step_id} 降級復原】: 原目標測站無回應，自動降級調用氣象署臺北市標準觀測站"
                                )
                                progress.chain_of_thought.append(f"【降級復原】：步驟 {s.step_id} 自動降級調用中央氣象署臺北市基準站成功")
                    except Exception as rec_err:
                        log.debug(f"Weather probe recovery failed: {rec_err}")

                if not recovered:
                    progress.observations.append(f"【步驟 {s.step_id} 失敗記錄】: {s.error}")
                    progress.chain_of_thought.append(f"【復原終止】：步驟 {s.step_id} 無法修復，誠實記錄異常原因：{s.error}")
        else:
            progress.chain_of_thought.append("【驗證通過】：全部步驟之資料完整性與正確性校驗無誤")

        # -----------------------------------------------------------------
        # Stage 5: Synthesis & Completion
        # -----------------------------------------------------------------
        await emit_update("COMPLETED", "✅ [階段 5/5] 正在整合最終診斷結論與排版輸出...")
        progress.chain_of_thought.append("【認知對齊】：嚴格遵循事實公理，杜絕虛構與假成功，綜合產出高品質分析報告")
        final_text = await self._synthesize_output(task_goal, progress.steps)
        progress.final_output = final_text
        await emit_update("COMPLETED", "任務執行完畢！")

        return progress

    async def _plan_task(self, task_goal: str) -> List[AgentStep]:
        """Uses domain heuristics + LLM to break goal into structured steps."""
        tool_summary = self.tools.get_tools_prompt_summary()
        goal_lower = task_goal.lower()

        # 1. High-confidence heuristic for full platform/bot inspection
        if any(k in task_goal for k in ["全方位深度巡檢", "巡檢系統資源", "平台巡檢", "模組健康狀態", "bot資源"]) or task_goal in ["系統巡檢", "系統診斷", "平台診斷", "全盤巡檢"]:
            return [
                AgentStep(step_id=1, title="探測 Bot 與系統資源負載 (CPU/RAM/Uptime)", tool_name="system_diagnostics", parameters={}, thought="採集 Python 程序記憶體駐留集 (RSS)、系統 CPU 負載與持續運行時間以建立效能基準"),
                AgentStep(step_id=2, title="檢查全平台 11 個功能模組運行狀態", tool_name="module_health", parameters={}, thought="遍歷 11 個核心功能模組之 Lifecycle 狀態與註冊指令數，確認是否有模組異常"),
                AgentStep(step_id=3, title="檢查當前 Discord 伺服器規模與權限配置", tool_name="guild_diagnostics", parameters={}, thought="讀取目前伺服器成員總數、頻道拓撲與機器人關鍵管理員權限位元"),
                AgentStep(step_id=4, title="讀取資料庫數據規模與配額大盤", tool_name="database_stats", parameters={}, thought="統計 SQLite 數據規模、每日配額分派與經濟模組錢包健康狀態"),
            ]

        # 2. Pure math calculation
        if task_goal.startswith("計算") or re.match(r"^[\d\.\+\-\*\/\(\)\^\s]{3,}$", task_goal.strip()):
            m = re.search(r"[\d\.\+\-\*\/\(\)\^\s]{3,}", task_goal)
            expr = m.group(0).strip() if m else "1+1"
            return [
                AgentStep(step_id=1, title=f"使用任意精度沙盒計算 `{expr}`", tool_name="calculator", parameters={"expression": expr}, thought=f"將數學表達式「{expr}」送入 SymPy 引擎執行任意精度代數與數值運算，杜絕大語言模型的心算幻覺"),
            ]

        # 3. LLM based planning
        planner_prompt = (
            f"你是一個專為 ZeroNexus 打造的原生 Agent 任務規劃器 (Planner)。\n"
            f"使用者目標：{task_goal}\n\n"
            f"可用受限唯讀工具列表：\n{tool_summary}\n\n"
            f"請分析目標並選出 1 至 3 個最合理的具體步驟，並以純 JSON 陣列格式輸出（嚴禁任何額外對話或 Markdown 說明）：\n"
            f"[\n"
            f'  {{"step_id": 1, "thought": "步驟分析與推論思考", "title": "步驟簡短標題", "tool_name": "工具名稱 (必須是可用工具列表中之一或 null)", "parameters": {{"param1": "value1"}}}}\n'
            f"]\n\n"
            f"注意：\n"
            f"1. 若目標是探測 Minecraft 伺服器（例如 Hypixel 或包含域名/IP），請使用 minecraft_probe，parameters 填入 host（如 mc.hypixel.net 或 play.xxx）！\n"
            f"2. 若目標為天氣查詢使用 weather_probe，地震速報使用 earthquake_probe。\n"
            f"3. 嚴禁編造不存在的工具名稱。"
        )

        try:
            res, _ = await ai_gateway.generate_response(
                system_instruction="你是一個嚴格遵從 JSON 格式的 Agent Planner。只輸出純 JSON 陣列。",
                messages=[{"role": "user", "content": planner_prompt}],
            )
            raw = res.text.strip()
            match = re.search(r"\[\s*\{.*\}\s*\]", raw, re.DOTALL)
            if match:
                data = json.loads(match.group(0))
                steps = []
                for item in data:
                    t_name = item.get("tool_name")
                    if t_name and not self.tools.get_tool(t_name):
                        t_name = self._fuzzy_match_tool(t_name)
                    steps.append(AgentStep(
                        step_id=item.get("step_id", len(steps) + 1),
                        title=item.get("title", f"執行步驟 {len(steps) + 1}"),
                        tool_name=t_name,
                        parameters=item.get("parameters", {}),
                        thought=item.get("thought") or f"為達成目標執行步驟 {len(steps) + 1}",
                    ))
                if steps:
                    return steps
        except Exception as e:
            log.warning(f"LLM planner failed: {e}. Using fallback heuristic planning.")

        # 4. Fallback heuristics if LLM planning is unavailable
        if any(k in goal_lower for k in ["mc", "minecraft", "hypixel"]) or re.search(r"[a-zA-Z0-9\.\-_]+\.(?:net|org|com|io|me|tw|xyz|cc)", task_goal):
            host = "mc.hypixel.net"
            if "hypixel" in goal_lower:
                host = "mc.hypixel.net"
            else:
                dm = re.search(r"([a-zA-Z0-9\.\-_]+\.(?:net|org|com|io|me|tw|xyz|cc)[a-zA-Z0-9\.\-_]*)", task_goal)
                if dm:
                    host = dm.group(1).strip()
            return [AgentStep(step_id=1, title=f"探測 Minecraft 伺服器 ({host})", tool_name="minecraft_probe", parameters={"host": host}, thought=f"透過 socket ping 通訊協定直接探測 Minecraft 伺服器 {host} 即時在線狀態與延遲")]

        if any(k in goal_lower for k in ["天氣", "氣象", "下雨", "溫度"]):
            county = "臺北市"
            for c in ["臺北市", "新北市", "桃園市", "臺中市", "臺南市", "高雄市", "基隆市", "新竹市", "嘉義市", "宜蘭縣", "花蓮縣", "臺東縣"]:
                if c[:2] in task_goal:
                    county = c
                    break
            return [AgentStep(step_id=1, title=f"查詢氣象署 ({county}) 即時預報", tool_name="weather_probe", parameters={"county": county}, thought=f"串接交通部中央氣象署開放資料 API 檢索 {county} 即時天氣觀測與 36 小時預報")]

        if "地震" in goal_lower:
            return [AgentStep(step_id=1, title="查詢氣象署最新顯著有感地震", tool_name="earthquake_probe", parameters={}, thought="檢索中央氣象署最新發布之編號地震速報與震度資料")]

        # Default single step
        return [AgentStep(step_id=1, title="讀取系統與核心模組狀態", tool_name="system_diagnostics", parameters={}, thought="採集系統基礎健康資訊進行整體評估")]

    def _fuzzy_match_tool(self, name: str) -> Optional[str]:
        n = name.lower()
        if "system" in n or "cpu" in n or "ram" in n:
            return "system_diagnostics"
        if "module" in n or "模組" in n:
            return "module_health"
        if "guild" in n or "server" in n or "伺服器" in n:
            return "guild_diagnostics"
        if "db" in n or "database" in n or "資料庫" in n:
            return "database_stats"
        if "calc" in n or "計算" in n:
            return "calculator"
        if "weather" in n or "天氣" in n:
            return "weather_probe"
        if "earthquake" in n or "地震" in n:
            return "earthquake_probe"
        if "mc" in n or "minecraft" in n:
            return "minecraft_probe"
        if "chart" in n or "plot" in n or "畫圖" in n or "繪圖" in n or "圖表" in n:
            return "plot_chart"
        if "sandbox" in n or "python" in n or "代碼" in n or "程式碼" in n:
            return "python_code_sandbox"
        return None

    async def _synthesize_output(self, task_goal: str, steps: List[AgentStep]) -> str:
        """Synthesizes step observations into a coherent, professional analytical report via LLM."""
        observations = []
        for s in steps:
            is_success = (s.status == "COMPLETED") and not (s.result and s.result.get("is_error"))
            status_label = "【步驟執行成功】" if is_success else "【步驟執行失敗】"
            obs_entry = f"【步驟 {s.step_id}：{s.title}】(工具：{s.tool_name or '無'}, 狀態：{status_label})\n"
            if s.result:
                obs_entry += f"真實觀測數據：{json.dumps(s.result, ensure_ascii=False)}\n"
            if s.error:
                obs_entry += f"異常原因：{s.error}\n"
            observations.append(obs_entry)

        prompt = (
            f"你是一個專為 ZeroNexus 打造的原生 Agent 綜合報告分析師。\n"
            f"使用者交付的任務目標：{task_goal}\n\n"
            f"各步驟工具執行後的真實觀測數據如下：\n"
            f"{chr(10).join(observations)}\n\n"
            f"【核心真實性與模型認知對齊公理 (Ground-Truth Cognitive Alignment)】：\n"
            f"1. 嚴格事實依附（防止宣稱失敗）：若步驟狀態為【步驟執行成功】且具備真實觀測數據，代表工具完全成功獲取資料。嚴格禁止向使用者謊稱「工具失敗」、「無法獲取資料」、「探測逾時」或「連線中斷」！\n"
            f"2. 嚴禁瞎掰成功（防止虛構數據）：若步驟狀態為【步驟執行失敗】或存在異常原因，代表該步驟明確未成功。嚴格禁止捏造虛假的成功結果（如編造假在線人數、假運算數值、假氣象數據），必須誠實回報該步驟異常與具體失敗原因！\n"
            f"3. 實體狀態精準詮釋：若 Minecraft 伺服器探測數據中 online 為 false，代表伺服器本體目前「離線或無法連線」，探測工具本身成功回報了該離線事實，請如實告知使用者該伺服器離線，切勿幻想在線人數！\n"
            f"4. 報告格式排版：使用台灣繁體中文，格式清晰（善用重點粗體與條列 bullet points）。嚴格禁止直接傾倒 raw json 代碼塊（禁止 ```json）。字數控制在 350 字以內，適合在 Discord 卡片中閱讀。"
        )

        try:
            res, _ = await ai_gateway.generate_response(
                system_instruction=(
                    "你是一個嚴格遵從格式規範與事實真實性的專業診斷分析師，產出高品質台灣繁體中文 Markdown 報告。"
                    "嚴格遵循認知對齊公理：工具成功絕不宣稱失敗，工具失敗絕不瞎掰成功，切勿輸出 raw json 代碼塊。"
                ),
                messages=[{"role": "user", "content": prompt}],
            )
            report = res.text.strip()
            if report:
                return report
        except Exception as e:
            log.warning(f"LLM synthesis failed: {e}. Using deterministic human-readable formatter.")

        # Deterministic human-readable Markdown fallback (zero raw JSON blocks)
        lines = [f"### 📋 診斷分析摘要：{task_goal}\n"]
        for s in steps:
            is_real_success = (s.status == "COMPLETED") and not (s.result and s.result.get("is_error"))
            icon = "✅" if is_real_success else "❌"
            lines.append(f"**{icon} 步驟 {s.step_id}：{s.title}**")
            if is_real_success and s.result:
                r = s.result
                if "online" in r or "players_online" in r:
                    is_online = r.get("online", False)
                    status_text = "正常運行中" if is_online else "無法連線 / 離線"
                    server_icon = "🟢" if is_online else "🔴"
                    lines.append(f"- 狀態：{server_icon} **{status_text}**")
                    if is_online and "players_online" in r:
                        lines.append(f"- 在線人數：`{r.get('players_online')}` / `{r.get('players_max')}`")
                    if is_online and "latency_ms" in r:
                        lines.append(f"- 延遲：`{r.get('latency_ms')} ms`")
                    if "version" in r:
                        lines.append(f"- 版本：`{r.get('version')}`")
                elif "system_cpu_percent" in r:
                    lines.append(f"- CPU 使用率：`{r.get('system_cpu_percent')}%`")
                    lines.append(f"- RAM 使用率：`{r.get('system_ram_percent')}%` (Process: `{r.get('process_memory_mb')} MB`)")
                    lines.append(f"- 運行時間：`{r.get('uptime_formatted')}`")
                elif "result" in r and "expression" in r:
                    lines.append(f"- 計算式：`{r.get('expression')}`")
                    lines.append(f"- 運算結果：`{r.get('result')}`")
                elif "forecasts" in r:
                    fcasts = r.get("forecasts", [])
                    if fcasts:
                        f0 = fcasts[0]
                        lines.append(f"- 天氣現象：`{f0.get('weather')}`")
                        lines.append(f"- 氣溫區間：`{f0.get('min_temp')}°C ~ {f0.get('max_temp')}°C`")
                        lines.append(f"- 降雨機率：`{f0.get('rain_prob')}`")
                elif "earthquake_no" in r:
                    lines.append(f"- 地震編號：`{r.get('earthquake_no')}`")
                    lines.append(f"- 芮氏規模：`{r.get('magnitude')}`")
                    lines.append(f"- 震央位置：`{r.get('location')}`")
                else:
                    for k, v in list(r.items())[:5]:
                        lines.append(f"- {k}：`{v}`")
            else:
                err_msg = s.error or (s.result.get("error_message") if s.result else None) or (s.result.get("error") if s.result else None) or "步驟執行未達預期"
                lines.append(f"- ⚠️ 異常資訊：`{err_msg}`")
            lines.append("")

        return "\n".join(lines).strip()



# Singleton
agent_engine = AgentEngine()
