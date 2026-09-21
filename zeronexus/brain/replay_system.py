"""ZeroNexus 心智狀態歷史重放系統 (Mental State Replay System)

嚴格依據計畫書第 38 條規範設計：
可重放指定歷史時間區間內的事件序列：
給定 [start_time, end_time] ➔ 重新執行：
Event ➔ Memory ➔ Emotion Model ➔ State Engine
精準排查：「為什麼在特定時間點狀態突然改變？」
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from zeronexus.brain.emotion_state_engine import ContinuousEmotionState, EmotionStateEngine
from zeronexus.brain.event_system import SemanticEvent

log = logging.getLogger("ZeroNexus.Brain.Replay")


@dataclass
class ReplayStepResult:
    """重放單一步驟狀態記錄"""

    step_index: int
    timestamp: float
    event_type: str
    importance: float
    deltas_applied: Dict[str, float]
    state_after: Dict[str, float]


class MentalStateReplayer:
    """心智狀態沙盒重放器"""

    def __init__(self, baseline_engine: Optional[EmotionStateEngine] = None) -> None:
        self.engine = baseline_engine or EmotionStateEngine()

    def replay_events(
        self,
        events: List[SemanticEvent],
        initial_state: Optional[ContinuousEmotionState] = None,
    ) -> List[ReplayStepResult]:
        """在沙盒環境中連續重放事件序列，輸出完整的狀態演進軌跡"""
        # 使用副本建立沙盒狀態，絕不破壞生產環境當前活體狀態
        sandbox_state = ContinuousEmotionState()
        if initial_state:
            for k, v in initial_state.__dict__.items():
                if hasattr(sandbox_state, k):
                    setattr(sandbox_state, k, v)

        # 排序事件序列
        sorted_events = sorted(events, key=lambda e: e.timestamp)
        results: List[ReplayStepResult] = []

        for idx, evt in enumerate(sorted_events):
            # 1. 依照事件時間戳記套用時間代謝
            self.engine.apply_time_decay(current_time=evt.timestamp)
            # 2. 套用事件
            applied_deltas = self.engine.update_state(
                deltas=evt.emotional_effect,
                source=f"replay_{evt.event_type}",
                importance=evt.importance,
            )
            snap = self.engine.get_snapshot()["emotions"]

            results.append(
                ReplayStepResult(
                    step_index=idx + 1,
                    timestamp=evt.timestamp,
                    event_type=evt.event_type,
                    importance=evt.importance,
                    deltas_applied=applied_deltas,
                    state_after=snap,
                )
            )

        return results

    def format_replay_report(self, results: List[ReplayStepResult]) -> str:
        """格式化產出重放軌跡報告"""
        if not results:
            return "（指定時間區間內無可重放之歷史事件）"

        lines = ["# ⏪ ZeroNexus 心智狀態歷史重放軌跡報告"]
        for r in results:
            t_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.timestamp))
            lines.append(
                f"### [步驟 {r.step_index}] {t_str} | 事件: `{r.event_type}` (重要度: {r.importance})"
            )
            delta_str = ", ".join(f"{k}: {v:+.3f}" for k, v in r.deltas_applied.items())
            lines.append(f"- **刺激增量 (Deltas)**: `{delta_str or '無顯著變動'}`")
            lines.append(
                f"- **狀態截圖**: 喜悅={r.state_after['happiness']:.2f}, 好奇={r.state_after['curiosity']:.2f}, "
                f"信任={r.state_after['trust']:.2f}, 憤怒={r.state_after['anger']:.2f}, 精力={r.state_after['energy']:.2f}"
            )
            lines.append("")

        return "\n".join(lines)


# 全域單例
mental_state_replayer = MentalStateReplayer()
