"""Zero Intelligence - 執行時期智慧核心架構 (Runtime Intelligence Architecture)

核心規範與設計原則：
- Agent. But More Intelligent.
- 核心真實性公理：執行時期真實（Runtime Truth）> 模型猜測（Model Guess）；工具觀測結果 > 模型記憶。
- 嚴禁 MODEL_CLAIM -> RUNTIME_TRUTH（模型口頭說做完了不等於真實做完）。
- 嚴禁 REQUESTED -> COMPLETED（使用者請求不等於已完成）。
- 絕對隔離保護音樂串流播放組件，不改動現有音樂邏輯。
"""

from zeronexus.intelligence.truth_spectrum import (
    TruthLevel,
    TruthFact,
    TruthViolationError,
    TruthConflictError,
    compare_facts,
    resolve_conflict,
    downgrade_on_conflict,
    assert_truth,
    verify_runtime_truth,
)
from zeronexus.intelligence.action_ledger import (
    ActionState,
    ActionRecord,
    ActionLedger,
    ActionForgeError,
    LedgerIntegrityError,
    handle_discord_divergence,
)
from zeronexus.intelligence.complexity_router import (
    ComplexityDecision,
    ComplexityLevel,
    ComplexityRouter,
    analyze_complexity,
    evaluate_complexity,
    complexity_router,
)
from zeronexus.intelligence.dynamic_projector import (
    ActiveToolSet,
    DynamicToolProjector,
    ProjectedTool,
    project_active_tools,
    dynamic_projector,
)
from zeronexus.intelligence.stop_sentinel import (
    SentinelDecision,
    StopSentinel,
    ToolCallRecord,
    stop_sentinel,
)
from zeronexus.intelligence.capability_registry import (
    CapabilityDomain,
    SystemCapability,
    CapabilityRegistry,
    capability_registry,
)
from zeronexus.intelligence.identity_anchor import (
    IdentityProfile,
    IdentityAnchor,
    identity_anchor,
)
from zeronexus.intelligence.social_context import (
    InteractionType,
    SpeakerInfo,
    ConversationMessage,
    SocialContextGraph,
    social_context_graph,
)
from zeronexus.intelligence.memory_engine import (
    MemoryWriteResult,
    MemoryEngine,
    memory_engine,
)
from zeronexus.intelligence.world_model import (
    WorldStateSnapshot,
    WorldModel,
    world_model,
)
from zeronexus.intelligence.runtime_orchestrator import (
    OrchestrationTurnInput,
    OrchestrationTurnDecision,
    ZeroIntelligenceRuntime,
    zero_intelligence_runtime,
)

__all__ = [
    # 真理光譜
    "TruthLevel",
    "TruthFact",
    "TruthViolationError",
    "TruthConflictError",
    "compare_facts",
    "resolve_conflict",
    "downgrade_on_conflict",
    "assert_truth",
    "verify_runtime_truth",
    # 動作帳本
    "ActionState",
    "ActionRecord",
    "ActionLedger",
    "ActionForgeError",
    "LedgerIntegrityError",
    "handle_discord_divergence",
    # 自適應複雜度控制器
    "ComplexityLevel",
    "ComplexityDecision",
    "ComplexityRouter",
    "evaluate_complexity",
    "analyze_complexity",
    "complexity_router",
    # 動態能力投影器
    "ProjectedTool",
    "ActiveToolSet",
    "DynamicToolProjector",
    "project_active_tools",
    "dynamic_projector",
    # 終止智能與迴圈熔斷器
    "ToolCallRecord",
    "SentinelDecision",
    "StopSentinel",
    "stop_sentinel",
    # 執行時期動態能力註冊表
    "CapabilityDomain",
    "SystemCapability",
    "CapabilityRegistry",
    "capability_registry",
    # 身分智能深層錨定
    "IdentityProfile",
    "IdentityAnchor",
    "identity_anchor",
    # 社群語境圖譜
    "InteractionType",
    "SpeakerInfo",
    "ConversationMessage",
    "SocialContextGraph",
    "social_context_graph",
    # 記憶引擎與安全寫入管線
    "MemoryWriteResult",
    "MemoryEngine",
    "memory_engine",
    # 四層世界認知模型
    "WorldStateSnapshot",
    "WorldModel",
    "world_model",
    # 執行時期調度總中樞
    "OrchestrationTurnInput",
    "OrchestrationTurnDecision",
    "ZeroIntelligenceRuntime",
    "zero_intelligence_runtime",
]
