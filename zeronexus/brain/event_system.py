"""ZeroNexus 語意事件系統 (Semantic Event System)

定義標準化事件協議與事件檢測器：
1. Event Schema:
   event_id, timestamp, source, event_type, importance, emotional_effect,
   related_user, related_memory, decay_rate
2. 支援事件類型：
   praise, criticism, success, failure, surprise, positive_interaction,
   negative_interaction, long_absence, return, achievement, mistake, joke,
   conflict, help, greeting, farewell
3. 具備擴充性與語意規則 / 模型預測感知。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SemanticEvent:
    """語意事件資料結構"""

    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    timestamp: float = field(default_factory=time.time)
    source: str = "user_interaction"
    event_type: str = "positive_interaction"
    importance: float = 1.0  # 0.2 ~ 3.0
    emotional_effect: Dict[str, float] = field(default_factory=dict)
    related_user: Optional[str] = None
    related_memory: Optional[str] = None
    decay_rate: float = 1.0  # 事件衰減速率調節係數
    context_snippet: Optional[str] = None


class EventDetector:
    """語意與意圖事件檢測器"""

    # 預設事件之基礎情緒增量映射範本
    EVENT_PRESETS: Dict[str, Dict[str, float]] = {
        "praise": {
            "happiness": 0.12,
            "trust": 0.06,
            "calmness": 0.04,
            "sadness": -0.05,
            "frustration": -0.06,
        },
        "criticism": {
            "sadness": 0.08,
            "frustration": 0.09,
            "happiness": -0.08,
            "calmness": -0.05,
        },
        "joke": {
            "happiness": 0.10,
            "excitement": 0.08,
            "calmness": 0.03,
        },
        "conflict": {
            "anger": 0.08,
            "frustration": 0.10,
            "calmness": -0.10,
            "happiness": -0.08,
        },
        "greeting": {
            "happiness": 0.05,
            "curiosity": 0.04,
            "social_need": -0.06,
        },
        "farewell": {
            "loneliness": 0.05,
            "calmness": 0.04,
            "happiness": 0.02,
        },
        "help": {
            "trust": 0.08,
            "happiness": 0.07,
            "curiosity": 0.06,
        },
        "achievement": {
            "happiness": 0.15,
            "excitement": 0.12,
            "energy": 0.05,
        },
        "mistake": {
            "frustration": 0.08,
            "fear": 0.04,
            "happiness": -0.05,
        },
        "surprise": {
            "curiosity": 0.12,
            "excitement": 0.10,
            "fear": 0.03,
        },
        "long_absence": {
            "social_need": 0.20,
            "loneliness": 0.15,
            "happiness": -0.05,
        },
        "return": {
            "happiness": 0.14,
            "excitement": 0.10,
            "social_need": -0.15,
            "trust": 0.06,
        },
    }

    @classmethod
    def detect_event_from_text(
        cls,
        text: str,
        user_id: Optional[str] = None,
        context: Optional[str] = None,
    ) -> SemanticEvent:
        """從使用者文本與情境中偵測事件類型與重要度"""
        clean_text = (text or "").strip()
        lower_text = clean_text.lower()

        # 預設日常通用互動
        event_type = "positive_interaction"
        importance = 1.0
        decay_rate = 1.0

        # 稱讚與感激
        if any(kw in lower_text for kw in ["太厲害", "好棒", "謝謝你", "愛你", "好聰明", "超強", "辛苦了", "感謝", "讚", "good job", "thank"]):
            event_type = "praise"
            importance = 1.3
        # 批評、質疑或不滿
        elif any(kw in lower_text for kw in ["很爛", "好笨", "聽不懂", "胡說八道", "亂講", "真廢", "答非所問", "錯誤", "不對"]):
            event_type = "criticism"
            importance = 1.4
            decay_rate = 1.2
        # 幽默玩笑
        elif any(kw in lower_text for kw in ["哈哈", "笑死", "xdd", "開玩笑", "好笑", "lol", "kuso", "幽默"]):
            event_type = "joke"
            importance = 1.1
        # 爭吵、對立衝突
        elif any(kw in lower_text for kw in ["吵架", "憑什麼", "閉嘴", "滾", "吵死", "不服", "誰有理", "評評理"]):
            event_type = "conflict"
            importance = 1.5
        # 問候打招呼
        elif any(kw in lower_text for kw in ["早安", "午安", "晚安", "嗨嗨", "哈囉", "你好", "hello", "hi"]):
            event_type = "greeting"
            importance = 0.9
        # 道別離線
        elif any(kw in lower_text for kw in ["去睡了", "先下了", "掰掰", "明天見", "再見", "bye", "good night"]):
            event_type = "farewell"
            importance = 1.0
        # 尋求協助
        elif any(kw in lower_text for kw in ["救我", "幫我", "怎麼辦", "求助", "拜託", "請問", "請教", "help"]):
            event_type = "help"
            importance = 1.2
        # 驚奇驚訝
        elif any(kw in lower_text for kw in ["竟然", "居然", "天啊", "真的假的", "驚呆", "omg", "wow"]):
            event_type = "surprise"
            importance = 1.2

        base_deltas = cls.EVENT_PRESETS.get(event_type, {"happiness": 0.02, "curiosity": 0.03})

        return SemanticEvent(
            event_type=event_type,
            importance=importance,
            emotional_effect=dict(base_deltas),
            related_user=user_id,
            decay_rate=decay_rate,
            context_snippet=clean_text[:120],
        )


class EventHistoryLogger:
    """近期事件追蹤環狀隊列（提供除錯與歷史回溯）"""

    def __init__(self, max_size: int = 50) -> None:
        self.max_size = max_size
        self._events: List[SemanticEvent] = []

    def log_event(self, event: SemanticEvent) -> None:
        self._events.append(event)
        if len(self._events) > self.max_size:
            self._events.pop(0)

    def get_recent_events(self, limit: int = 10) -> List[SemanticEvent]:
        return list(reversed(self._events[-limit:]))

    def format_recent_events_text(self, limit: int = 5) -> str:
        recent = self.get_recent_events(limit)
        if not recent:
            return "（近期無顯著事件日誌）"
        lines = []
        for e in recent:
            t_str = time.strftime("%H:%M:%S", time.localtime(e.timestamp))
            delta_desc = ", ".join(f"{k}:{'+' if v>0 else ''}{v:.2f}" for k, v in list(e.emotional_effect.items())[:3])
            lines.append(f"[{t_str}] 類型: {e.event_type} | 影響力: {e.importance:.1f} ({delta_desc})")
        return "\n".join(lines)


# 全域事件紀錄器單例
event_history_logger = EventHistoryLogger()
