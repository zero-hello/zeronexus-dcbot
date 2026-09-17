"""
ZeroNexus - 執行時期調度總中樞 (Zero Intelligence Runtime Orchestrator)
依據 Zero Intelligence 規格第 0、3、40、41、42、43、44、151、371、392、401 條規範落實。

核心設計哲學：
Zero Intelligence 是環繞模型推論、工具執行、記憶與世界狀態的統一執行時期決策層。
將以下核心組件無縫縫合為單一執行管線：
1. 複雜度分流器 (ComplexityRouter)
2. 動態工具投影器 (DynamicProjector)
3. 終止智能哨兵 (StopSentinel)
4. 真理光譜 (TruthSpectrum)
5. 原子動作帳本 (ActionLedger)
6. 身分深層錨定器 (IdentityAnchor)
7. 社群語境圖譜 (SocialContextGraph)
8. 記憶安全寫入管線 (MemoryEngine)
9. 四層世界認知模型 (WorldModel)
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import logging

from zeronexus.intelligence.complexity_router import complexity_router, ComplexityLevel
from zeronexus.intelligence.dynamic_projector import dynamic_projector
from zeronexus.intelligence.stop_sentinel import stop_sentinel
from zeronexus.intelligence.action_ledger import ActionLedger
from zeronexus.intelligence.identity_anchor import identity_anchor
from zeronexus.intelligence.social_context import social_context_graph, InteractionType
from zeronexus.intelligence.memory_engine import memory_engine
from zeronexus.intelligence.world_model import world_model

logger = logging.getLogger("zeronexus.intelligence.orchestrator")


@dataclass
class OrchestrationTurnInput:
    """執行時期輸入脈絡"""
    raw_prompt: str
    user_id: int
    user_display_name: str
    is_dm: bool = False
    is_bot_mentioned: bool = False
    referenced_author_id: Optional[int] = None
    guild_id: Optional[int] = None
    channel_id: Optional[int] = None
    all_available_tools: Optional[List[Dict[str, Any]]] = None
    current_persona: Optional[str] = None


@dataclass
class OrchestrationTurnDecision:
    """執行時期決策結果"""
    normalized_prompt: str
    interaction_type: InteractionType
    complexity_level: ComplexityLevel
    active_tools: List[Dict[str, Any]]
    identity_system_prompt: str
    short_circuit_response: Optional[str] = None
    action_ledger: ActionLedger = field(default_factory=ActionLedger)


class ZeroIntelligenceRuntime:
    """Zero Intelligence 執行時期中樞"""

    def __init__(self):
        self.identity = identity_anchor
        self.social = social_context_graph
        self.memory = memory_engine
        self.world = world_model
        self.router = complexity_router
        self.projector = dynamic_projector
        self.sentinel = stop_sentinel

    async def orchestrate_incoming_turn(
        self,
        turn_input: OrchestrationTurnInput
    ) -> OrchestrationTurnDecision:
        """
        處理每一輪使用者進入的訊息：
        1. 規範化輸入並去除 Mention
        2. 社群互動型態辨識
        3. 記憶指令優先檢測（若是「記住」或「忘記」，走安全寫入管線短路回覆）
        4. 自適應複雜度分流
        5. 動態工具集投影 (Active Tool Set)
        6. 身分錨定快照注入
        """
        # 1. 規範化使用者提問
        normalized_prompt = self.social.normalize_message_content(turn_input.raw_prompt)

        # 2. 社群互動類型辨識
        interaction_type = self.social.analyze_interaction_type(
            content=turn_input.raw_prompt,
            is_dm=turn_input.is_dm,
            is_mentioned=turn_input.is_bot_mentioned,
            reference_message_author_id=turn_input.referenced_author_id,
        )

        # 3. 記憶安全指令攔截 (Sec 147, 149)
        # 若為明確的記憶寫入或刪除，直接透過管線完成，給予真實回覆
        importance_score, fact = self.memory.assess_importance(normalized_prompt)
        short_circuit_msg: Optional[str] = None

        if importance_score >= 1.0 and fact:
            mem_result = await self.memory.execute_memory_write_pipeline(
                user_id=turn_input.user_id,
                raw_text=normalized_prompt,
                guild_id=turn_input.guild_id,
                channel_id=turn_input.channel_id,
                speaker_name=turn_input.user_display_name
            )
            short_circuit_msg = mem_result.user_feedback_msg

        elif any(kw in normalized_prompt for kw in ["忘記", "刪除記憶", "forget"]):
            del_result = await self.memory.execute_memory_deletion(
                user_id=turn_input.user_id,
                raw_text=normalized_prompt
            )
            if del_result.action_taken != "IGNORED":
                short_circuit_msg = del_result.user_feedback_msg

        # 4. 自適應複雜度分流 (Sec 41, 42)
        complexity = self.router.evaluate(
            user_prompt=normalized_prompt,
            context={"interaction_type": interaction_type.value}
        )

        # 5. 動態工具投影 (Sec 43, 234)
        active_tools: List[Any] = []
        if complexity != ComplexityLevel.SIMPLE:
            active_set = self.projector.project(
                user_prompt=normalized_prompt,
                complexity=complexity
            )
            active_tools = active_set.tools

        # 6. 身分錨定系統提示詞 (Sec 31, 113)
        identity_prompt = self.identity.build_identity_system_prompt(
            current_persona=turn_input.current_persona
        )

        # 建立本輪對話之動作帳本
        ledger = ActionLedger(session_id=f"{turn_input.user_id}_{turn_input.channel_id}")

        return OrchestrationTurnDecision(
            normalized_prompt=normalized_prompt,
            interaction_type=interaction_type,
            complexity_level=complexity,
            active_tools=active_tools,
            identity_system_prompt=identity_prompt,
            short_circuit_response=short_circuit_msg,
            action_ledger=ledger
        )

    def orchestrate_post_tool_recovery(
        self,
        tool_results: List[Dict[str, Any]],
        original_prompt: str,
        speaker_name: str
    ) -> str:
        """
        Tool 呼叫返回後的 Post-Tool 身分重構指引 (Sec 114)。
        """
        return self.identity.reconstruct_post_tool_snapshot(
            tool_results=tool_results,
            original_intent=original_prompt,
            speaker_name=speaker_name
        )

    def finalize_response(
        self,
        raw_model_response: str,
        ledger: ActionLedger
    ) -> str:
        """
        最終回覆安全清洗與真實性審查 (Sec 259, 302, 369)：
        1. 阻絕假成功宣稱 (No False Success)
        2. 身分口吻防飄移 (第一人稱自然化)
        """
        # 1. 動作帳本審查：是否有虛假宣稱？
        sanitized = raw_model_response

        if ledger.has_false_success_claim(sanitized):
            logger.warning("偵測到模型虛假宣稱已完成操作，觸發真實性阻斷修正！")
            sanitized += "\n\n*(系統註記：上述操作尚未取得執行端點之實體驗證，請以實際伺服器狀態為準。)*"

        # 2. 身分人稱清洗
        sanitized = self.identity.sanitize_perspective(sanitized)

        return sanitized


# 全域單例
zero_intelligence_runtime = ZeroIntelligenceRuntime()
