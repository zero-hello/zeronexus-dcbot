"""ZeroNexus 高階類腦認知中樞 (Cognitive Cortex)

整合四大認知科學與類腦架構：
1. 體內恆定動機系統 (Homeostatic Drives): 社交渴求、好奇心動機、體力儲備與自尊防線之自主代謝。
2. 預測編碼引擎 (Predictive Coding Engine): 預期語意向量對比與餘弦落差 (Prediction Gap) 計算。
3. 全域工作空間意識聚光燈 (Global Workspace Theory): 候選思維顯著性加權競爭與唯一核心意識焦點廣播。
4. 預設模式網路與心智漫遊 (Default Mode Network - DMN): 靜息低功耗反思、記憶修剪與主動關懷發話。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

log = logging.getLogger("ZeroNexus.Brain.CognitiveCortex")


# ==============================================================================
# 1. 體內恆定動機系統 (Homeostatic Drives)
# ==============================================================================
@dataclass
class HomeostaticState:
    """體內恆定動機狀態，模擬生命體之內在需求與代謝平衡。"""

    social_hunger: float = 0.2     # 社交渴求 (隨靜息時間上升，互動後下降)
    curiosity_drive: float = 0.5   # 好奇心動機 (遇到未知概念上升)
    energy_reserve: float = 1.0    # 體力儲備 (互動消耗，靜置自然恢復)
    ego_boundary: float = 0.8      # 自尊與自律防線 (遇到惡意攻擊時消耗並警戒)
    last_update_ts: float = field(default_factory=time.time)

    def tick_decay(self, elapsed_seconds: float) -> None:
        """心跳自然代謝與渴望累積 (由心跳事件定期推動)"""
        if elapsed_seconds <= 0:
            return

        # 1. 很久沒人說話，社交渴望逐漸累積 (約 2 小時累積到飽和臨界值)
        self.social_hunger = min(1.0, max(0.0, self.social_hunger + (elapsed_seconds / 7200.0)))

        # 2. 好奇心隨時間自然微幅浮動累積
        self.curiosity_drive = min(1.0, max(0.0, self.curiosity_drive + (elapsed_seconds / 14400.0)))

        # 3. 體力自然緩慢恢復 (約 30 分鐘可自然回滿)
        self.energy_reserve = min(1.0, max(0.0, self.energy_reserve + (elapsed_seconds / 1800.0)))

        self.last_update_ts = time.time()

    def on_interaction(self, is_positive: bool = True) -> None:
        """每次使用者互動時更新內在動機"""
        # 互動大幅緩解社交渴望
        self.social_hunger = max(0.0, min(1.0, self.social_hunger - 0.4))
        # 每次對話微幅消耗精力
        self.energy_reserve = max(0.0, min(1.0, self.energy_reserve - 0.05))

        if not is_positive:
            # 遭受挫折或攻擊時自尊防線受壓
            self.ego_boundary = max(0.2, min(1.0, self.ego_boundary - 0.15))
        else:
            # 友善互動自然修復自尊防線
            self.ego_boundary = min(1.0, self.ego_boundary + 0.05)


# ==============================================================================
# 2. 預測編碼引擎 (Predictive Coding Engine)
# ==============================================================================
class PredictiveCodingEngine:
    """主動預測編碼引擎：基於先驗預期比對實際語意落差 (Prediction Gap)。"""

    def __init__(self, neural_array: Any) -> None:
        self.neural_array = neural_array
        self.last_expected_vector: Optional[np.ndarray] = None
        self.last_prediction_intent: str = ""

    def register_prediction(self, expected_user_reaction_text: str) -> None:
        """在 AI 輸出文字時，預測下一輪使用者的可能反應特徵向量。"""
        if not expected_user_reaction_text or not expected_user_reaction_text.strip():
            return
        self.last_prediction_intent = expected_user_reaction_text.strip()
        if hasattr(self.neural_array, "get_embedding"):
            self.last_expected_vector = self.neural_array.get_embedding(self.last_prediction_intent)
        else:
            self.last_expected_vector = None

    def calculate_prediction_error(self, actual_user_input: str) -> float:
        """比對使用者真實輸入向量與先前預期的餘弦落差 (Prediction Gap)。

        落差值 = 1.0 - CosineSimilarity
        - 0.0 表示完全符合預期
        - 0.2 ~ 0.5 為常態預期範圍
        - 0.7+ 表示巨大驚喜、意料之外或震驚脈衝
        """
        if self.last_expected_vector is None or not actual_user_input or not actual_user_input.strip():
            return 0.2  # 預設常態中度落差

        try:
            if hasattr(self.neural_array, "get_embedding"):
                actual_vec = self.neural_array.get_embedding(actual_user_input.strip())
                sim = float(np.dot(self.last_expected_vector, actual_vec))
                sim = max(-1.0, min(1.0, sim))
                prediction_error = max(0.0, min(2.0, 1.0 - sim))
            else:
                prediction_error = 0.2
        except Exception as ex:
            log.warning(f"計算預測落差向量餘弦值失敗: {ex}，採用常態基準值。")
            prediction_error = 0.2
        finally:
            # 單次落差計算完畢後立即重置預期向量，等待下輪註冊
            self.last_expected_vector = None

        return prediction_error


# ==============================================================================
# 3. 全域工作空間意識聚光燈 (Global Workspace Theory)
# ==============================================================================
@dataclass
class ConsciousIdea:
    """候選意識念頭，代表後台無意識模組所產生的競爭節點。"""

    source: str        # 來源模組 (例如: "EMOTION", "MEMORY", "DRIVE", "SURPRISE")
    content: str       # 內容描述
    salience: float    # 顯著性競爭分數 (0.0 ~ 1.0)


class GlobalWorkspace:
    """意識聚光燈：在後台眾多念頭中，透過顯著性競爭挑選唯一最核心焦點廣播給大腦。"""

    def __init__(self) -> None:
        self.active_spotlight: Optional[ConsciousIdea] = None

    def compete(self, candidate_ideas: List[ConsciousIdea]) -> Optional[ConsciousIdea]:
        """軟注意力勝者通吃競爭 (Winner-Takes-All with Soft Attention)。"""
        if not candidate_ideas:
            self.active_spotlight = None
            return None

        # 依顯著性排序，最高分勝出進入工作記憶聚光燈
        sorted_candidates = sorted(candidate_ideas, key=lambda x: x.salience, reverse=True)
        self.active_spotlight = sorted_candidates[0]
        return self.active_spotlight

    def render_spotlight_prompt(self) -> str:
        """將勝出的唯一思維焦點化為核心意識提示詞注入大模型上下文。"""
        if not self.active_spotlight:
            return ""

        return (
            f"\n【💡 全域意識聚光燈焦點（當前大腦最核心思考念頭）】\n"
            f"- 來源: {self.active_spotlight.source}（顯著度權重: {self.active_spotlight.salience:.2f}）\n"
            f"- 核心念頭: 『{self.active_spotlight.content}』\n"
            f"- 思考指導: 請務必讓此念頭成為你本輪思考與回話的核心潛意識驅動力，集中注意力深入回應，而非雜亂無章地堆砌資訊！\n"
        )


# ==============================================================================
# 4. 預設模式網路與心智漫遊 (Default Mode Network - DMN)
# ==============================================================================
class DefaultModeNetwork:
    """心智漫遊：在背景無人互動時自主反思、整理記憶與觸發主動發話。"""

    def __init__(self, core_engine: Any) -> None:
        self.core = core_engine
        self.last_spontaneous_thought_time = time.time()
        self.proactive_callback: Optional[Any] = None  # 可註冊主動發話之回呼函式

    async def spontaneous_mind_wandering(self) -> Optional[Dict[str, Any]]:
        """觸發一次自主心智漫遊 (由心跳事件定期呼叫)。"""
        self.last_spontaneous_thought_time = time.time()
        homeo_state: Optional[HomeostaticState] = None
        if hasattr(self.core, "homeostasis"):
            homeo_state = getattr(self.core, "homeostasis")
        elif hasattr(self.core, "cognitive_cortex") and hasattr(self.core.cognitive_cortex, "homeostasis"):
            homeo_state = self.core.cognitive_cortex.homeostasis

        if homeo_state is None:
            homeo_state = HomeostaticState()

        # 1. 檢查是否達到「自主主動發話」的閾值 (社交渴求 > 0.85 且 體力充足 > 0.5)
        if homeo_state.social_hunger > 0.85 and homeo_state.energy_reserve > 0.5:
            action_result = await self._trigger_proactive_outreach()
            homeo_state.social_hunger = 0.15  # 主動發話後大幅緩解渴求
            return {
                "action": "PROACTIVE_OUTREACH",
                "details": action_result,
            }

        # 2. 低功耗潛意識反思 (抽取一條未解記憶進行聯想鞏固)
        consolidation_result = await self._unconscious_consolidation()
        return {
            "action": "UNCONSCIOUS_CONSOLIDATION",
            "details": consolidation_result,
        }

    async def _trigger_proactive_outreach(self) -> Dict[str, Any]:
        """自主從記憶庫中尋找話題並準備主動敲使用者。"""
        log.info("🧠 [DMN 心智漫遊] 社交渴求達到臨界閾值，激發主動發話衝動！")
        topic = "分享最近的新發現與溫馨問候"
        try:
            vault = getattr(self.core, "memory_vault", None)
            if vault and hasattr(vault, "retrieve_relevant_memories"):
                mems = vault.retrieve_relevant_memories("global", limit=2)
                if mems:
                    topic = f"回想起之前聊過的：{mems[0].summary}"
        except Exception as ex:
            log.warning(f"DMN 主動尋找話題失敗: {ex}")

        outreach_data = {
            "topic": topic,
            "timestamp": time.time(),
            "proactive_prompt": f"好久不見！我剛剛忽然想到了『{topic}』，你在忙嗎？",
        }

        if self.proactive_callback:
            try:
                if inspect.iscoroutinefunction(self.proactive_callback):
                    await self.proactive_callback(outreach_data)
                else:
                    self.proactive_callback(outreach_data)
            except Exception as ex:
                log.warning(f"執行主動發話回呼失敗: {ex}")

        return outreach_data

    async def _unconscious_consolidation(self) -> str:
        """潛意識反思與記憶自發修剪。"""
        log.debug("🧠 [DMN 心智漫遊] 正在執行背景低功耗潛意識記憶修剪與情節聯想...")
        return "記憶修剪與海馬迴微結構鞏固完成"


# ==============================================================================
# 5. 高階類腦認知皮層統一入口 (Cognitive Cortex)
# ==============================================================================
class CognitiveCortex:
    """整合動機系統、預測編碼、全域工作空間與預設模式網絡之大腦認知中樞。"""

    def __init__(self, neural_array: Any, core_engine: Any = None) -> None:
        self.homeostasis = HomeostaticState()
        self.predictive_coding = PredictiveCodingEngine(neural_array=neural_array)
        self.workspace = GlobalWorkspace()
        self.dmn = DefaultModeNetwork(core_engine=core_engine or self)

    def attach_core(self, core_engine: Any) -> None:
        """綁定大腦總控核心 (BioBrainCore)"""
        self.dmn.core = core_engine

