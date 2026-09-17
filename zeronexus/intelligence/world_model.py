"""
ZeroNexus - 四層世界認知架構模型 (Four-Layer World Model)
依據 Zero Intelligence 規格第 18、19、20、49、325、326、327、328、394 條規範落實。

核心設計哲學：
Zero Intelligence 拒絕將所有資訊扁平化傾倒進單一 Prompt，
必須嚴格解耦四層認知結構：
  Layer 1: 使用者私有記憶 (User Memory - Episodic & Personal Facts)
  Layer 2: 系統領域知識 (Domain Knowledge - Capabilities & Rules)
  Layer 3: 動態世界狀態 (World State - Dynamic Ground-Truth with TTL & Freshness)
  Layer 4: 執行時期任務狀態 (Runtime State - Working Memory & Action Ledger)
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
import logging

logger = logging.getLogger("zeronexus.intelligence.world_model")


@dataclass
class WorldStateSnapshot:
    """真實世界狀態快照單元"""
    key: str
    data: Any
    observed_at: datetime
    ttl_seconds: int = 300  # 預設 5 分鐘快取
    source_endpoint: str = "open_data"
    is_stale: bool = False

    def is_expired(self) -> bool:
        """檢查資料是否過期"""
        now = datetime.now(timezone.utc)
        return (now - self.observed_at).total_seconds() > self.ttl_seconds


class WorldModel:
    """四層世界認知模型管理器"""

    def __init__(self):
        # Layer 3: 動態外部世界事實儲存槽
        self._world_cache: Dict[str, WorldStateSnapshot] = {}

    def record_world_observation(
        self,
        key: str,
        data: Any,
        ttl_seconds: int = 300,
        source: str = "external_api"
    ) -> None:
        """
        記錄一項真實世界觀測數據（Layer 3: World State）。
        """
        self._world_cache[key] = WorldStateSnapshot(
            key=key,
            data=data,
            observed_at=datetime.now(timezone.utc),
            ttl_seconds=ttl_seconds,
            source_endpoint=source,
            is_stale=False
        )
        logger.debug(f"更新世界狀態快照 [{key}], TTL={ttl_seconds}s, 來源={source}")

    def get_world_observation(self, key: str) -> Optional[WorldStateSnapshot]:
        """
        取得動態世界數據，若過期則標記為 STALE 但維持可用性（Sec 327 降級快取策略）。
        """
        snapshot = self._world_cache.get(key)
        if not snapshot:
            return None

        if snapshot.is_expired():
            snapshot.is_stale = True

        return snapshot

    def build_unified_cognitive_context(
        self,
        user_id: int,
        user_memories: List[str],
        domain_knowledge_summary: str,
        active_world_keys: Optional[List[str]] = None,
        runtime_step_summary: Optional[str] = None
    ) -> str:
        """
        將四層認知模型動態編排為結構清晰的執行時期 Context。
        
        符合規格 143 條：不盲目拼接，精確依層級投影。
        """
        sections: List[str] = []

        # Layer 1: 使用者私有長期記憶
        if user_memories:
            mem_lines = "\n".join([f"- {m}" for m in user_memories])
            sections.append(f"【Layer 1: 使用者專屬記憶】\n{mem_lines}")

        # Layer 2: 系統領域知識與能力
        if domain_knowledge_summary:
            sections.append(f"【Layer 2: 系統即時能力】\n{domain_knowledge_summary}")

        # Layer 3: 動態外部世界觀測
        world_lines: List[str] = []
        if active_world_keys:
            for k in active_world_keys:
                obs = self.get_world_observation(k)
                if obs:
                    stale_flag = " (⚠️ 數據已過期，僅供參考)" if obs.is_stale else " (即時真實)"
                    world_lines.append(f"- [{k}]{stale_flag}: {obs.data}")

        if world_lines:
            sections.append("【Layer 3: 即時世界動態狀態】\n" + "\n".join(world_lines))

        # Layer 4: 執行時期任務帳本
        if runtime_step_summary:
            sections.append(f"【Layer 4: 執行時期工作狀態】\n{runtime_step_summary}")

        return "\n\n".join(sections)


# 全域單例
world_model = WorldModel()
